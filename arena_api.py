"""Public self-service challenger uploads + local administrator review inbox.

Security boundaries:
- Public upload is DISABLED unless OPENFISHTEST_ARENA_UPLOADS=1.
- API never executes submitted files or hands them to volunteer PCs.
- Anonymous uploads are streamed to a bounded quarantine, rate limited by
  salted IP hash, have global queue limits, and require pinned Stockless+EPD.
- Only the separately installed Linux rootless-container runner may execute
  the uploaded ELF, in its own isolated environment.
- Public endpoints reveal metadata and real scores, never download candidate
  binaries, local paths, private identities or administrator credentials.
"""
import hashlib
import io
import hmac
import json
import os
import secrets
import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl

from arena_core import (
    GAMES, MAX_UPLOAD_BYTES, PASS_SCORE_X2,
    UnsafeArchive
)
from match_protocol import sha256_path
from candidate_formats import inspect_candidate
from arena_books import InvalidBook, normalize_book, persisted_book, MAX_BOOK_BYTES

MAX_QUEUED = 6
MAX_PER_IP_PER_DAY = 2
MAX_CONTENT_LENGTH = MAX_UPLOAD_BYTES
UPLOADS_ENABLED_VAR = "OPENFISHTEST_ARENA_UPLOADS"
DAILY_SECONDS = 86_400


class ReleaseLink(BaseModel):
    release_url: HttpUrl


def setup_arena_schema(connection):
    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS arena_entries (
                id INTEGER PRIMARY KEY,
                engine_name TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                source_url TEXT,
                archive_path TEXT,
                archive_sha256 TEXT,
                engine_sha256 TEXT,
                archive_bytes INTEGER NOT NULL DEFAULT 0,
                ip_hash TEXT NOT NULL,
                reference_id INTEGER NOT NULL REFERENCES engines(id),
                reference_sha256 TEXT NOT NULL,
                reference_version TEXT NOT NULL,
                book_sha256 TEXT NOT NULL,
                tc TEXT NOT NULL DEFAULT '10+0.1',
                status TEXT NOT NULL DEFAULT 'uploading',
                wins INTEGER NOT NULL DEFAULT 0,
                draws INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                score REAL,
                penta_json TEXT,
                pgn_path TEXT,
                error_class TEXT,
                run_id TEXT,
                started_at REAL,
                completed_at REAL,
                released_url TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_arena_status ON arena_entries(status,created_at);
            CREATE INDEX IF NOT EXISTS idx_arena_ip ON arena_entries(ip_hash,created_at);
            CREATE TABLE IF NOT EXISTS arena_books (
                digest TEXT PRIMARY KEY,
                original_format TEXT NOT NULL,
                positions INTEGER NOT NULL,
                ip_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_arena_books_owner
                ON arena_books(ip_hash,created_at);
            CREATE TABLE IF NOT EXISTS arena_events (
                id INTEGER PRIMARY KEY,
                arena_id INTEGER NOT NULL REFERENCES arena_entries(id),
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at REAL NOT NULL
            );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(arena_entries)")}
        for name, definition in (
            ("engine_platform", "TEXT"),
            ("uci_name", "TEXT"),
            ("uci_author", "TEXT"),
            ("uci_options_json", "TEXT"),
        ):
            if name not in columns:
                db.execute(f"ALTER TABLE arena_entries ADD COLUMN {name} {definition}")


def _secret_key(folder):
    """Stable per-installation local salt; not written to Git."""
    filename = folder / ".arena-ip-salt"
    try:
        salt = filename.read_bytes()
    except FileNotFoundError:
        try:
            fd = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return filename.read_bytes()
        with os.fdopen(fd, "wb") as handle:
            salt = secrets.token_bytes(32)
            handle.write(salt)
            handle.flush()
            os.fsync(handle.fileno())
    if len(salt) != 32:
        raise RuntimeError("Invalid local arena salt; repair private data directory")
    return salt


@lru_cache(maxsize=8)
def _book_info(path, mtime_ns, size):
    """Hash and minimally validate at least 50 legal EPD opening positions."""
    import chess
    digest = hashlib.sha256()
    count = 0
    with open(path, "rb") as fh:
        for raw in fh:
            digest.update(raw)
            if not raw.strip() or raw.lstrip().startswith(b"#"):
                continue
            if count < 50:
                try:
                    text = raw.decode("utf-8").strip()
                    board = chess.Board()
                    board.set_epd(text)
                    if not board.is_valid():
                        raise ValueError("Illegal chess position")
                except (UnicodeError, ValueError, chess.InvalidMoveError) as exc:
                    raise ValueError("Configured arena EPD has invalid positions") from exc
            count += 1
    if count < 50:
        raise ValueError("Arena requires at least 50 valid opening EPD lines")
    return digest.hexdigest(), count


def arena_book_metadata(book_sha256=None, data_dir=None):
    """Resolve the pinned default book or a user-uploaded, hashed EPD book."""
    if book_sha256 and data_dir is not None:
        custom = data_dir / "arena" / "books" / f"{book_sha256}.epd"
        if custom.is_file():
            try:
                return persisted_book(custom, book_sha256)
            except InvalidBook:
                return None
    raw = os.getenv("OPENFISHTEST_ARENA_BOOK", "").strip()
    if not raw:
        return None
    book = Path(raw).expanduser().resolve()
    if not book.is_file() or book.suffix.lower() != ".epd":
        return None
    try:
        st = book.stat()
        digest, count = _book_info(str(book), st.st_mtime_ns, st.st_size)
        return {"path": book, "sha256": digest, "positions": count} if not book_sha256 or digest == book_sha256 else None
    except (ValueError, OSError):
        return None


def public_row(row):
    """Whitelist public fields; uploaded executable archives are private."""
    return {
        "id": row["id"],
        "engine_name": row["engine_name"],
        "engine_version": row["engine_version"],
        "engine_platform": row["engine_platform"],
        "uci_name": row["uci_name"],
        "uci_author": row["uci_author"],
        "uci_options": json.loads(row["uci_options_json"]) if row["uci_options_json"] else [],
        "source_url": row["source_url"],
        "reference_version": row["reference_version"],
        "reference_sha256": row["reference_sha256"],
        "status": row["status"],
        "games": GAMES,
        "wins": row["wins"],
        "draws": row["draws"],
        "losses": row["losses"],
        "score": row["score"],
        "threshold": PASS_SCORE_X2 / 2,
        "qualified": row["status"] in ("passed", "released"),
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "released_url": row["released_url"],
        "pgn_available": bool(row["pgn_path"]),
    }


def register_arena_api(app: FastAPI, connection, get_reference_id,
                       used_bytes, data_dir: Path, require_admin,
                       local_admin_only):
    setup_arena_schema(connection)
    salt = _secret_key(data_dir)
    uploads_dir = data_dir / "arena" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    books_dir = data_dir / "arena" / "books"
    books_dir.mkdir(parents=True, exist_ok=True)

    def arena_ready(selected_book=None):
        if os.getenv(UPLOADS_ENABLED_VAR) != "1":
            return None, None, "Automatic uploads are disabled by the operator"
        book = arena_book_metadata(selected_book, data_dir)
        if used_bytes() + MAX_UPLOAD_BYTES > 4_250_000_000:
            return None, book, "Server quota requires archiving before accepting uploads"
        with connection() as db:
            reference_id = get_reference_id(db)
            ref = db.execute(
                "SELECT id,name,version,sha256 FROM engines "
                "WHERE id=? AND approved=1", (reference_id,)
            ).fetchone() if reference_id else None
            if ref is None or ref["name"].casefold() != "stockless":
                return None, book, "Pin a Stockless reference build first (local admin panel)"
            count = db.execute(
                "SELECT COUNT(*) FROM arena_entries WHERE status "
                "IN ('uploading','queued','running')"
            ).fetchone()[0]
            if count >= MAX_QUEUED:
                return dict(ref), book, "Arena submission queue is full"
        if book is None:
            return dict(ref), None, (
                "Drag in a .epd or .pgn opening book first, or configure a default book"
            )
        return dict(ref), book, None

    @app.get("/api/arena/policy")
    def arena_policy():
        reference, book, issue = arena_ready()
        # A volunteer can upload their own book if the server/reference is
        # operational even without an operator-provided default book.
        book_uploads_ready = (
            os.getenv(UPLOADS_ENABLED_VAR) == "1" and
            reference is not None and used_bytes() < 4_000_000_000
        )
        return {
            "accepting": issue is None,
            "reason": issue,
            "book_upload_enabled": book_uploads_ready,
            "games": GAMES,
            "pass_points": PASS_SCORE_X2 / 2,
            "max_zip_bytes": MAX_UPLOAD_BYTES,
            "max_book_bytes": MAX_BOOK_BYTES,
            "supported_engines": [
                "Windows x86_64 PE32+ .exe",
                "ZIP containing root-level Linux x86_64 ELF named engine",
            ],
            "windows_sandbox_enabled": os.getenv("OPENFISHTEST_WINDOWS_ARENA") == "1",
            "supported_books": [".epd", ".pgn"],
            "upload_format": "raw .exe (PE64) or Linux ELF ZIP (128 MiB max)",
            "reference": {
                "version": reference["version"], "sha256": reference["sha256"]
            } if reference else None,
            "opening_book_sha256": book["sha256"] if book else None,
            "score_rule": "win=1 draw=0.5 loss=0; 55/100 qualifies for private review",
            "archive_rule": "failed candidates discarded; PGNs/results retained",
            "safety": (
                "Untrusted EXE/ZIP uploads run only in a separate disposable "
                "Linux VM with a rootless container and no network; "
                "never on public volunteer PCs."
            )
        }

    @app.post("/api/arena/books", status_code=201)
    async def upload_opening_book(
        request: Request,
        filename: str = Query(min_length=5, max_length=120)
    ):
        """Drag and drop EPD/PGN: normalize to EPD and pin by server-computed SHA."""
        if os.getenv(UPLOADS_ENABLED_VAR) != "1":
            raise HTTPException(503, "Arena uploads not enabled")
        if request.headers.get("content-type", "").split(";")[0].lower().strip() not in (
            "application/octet-stream", "text/plain", "application/x-chess-pgn",
            "text/x-chess-epd"
        ):
            raise HTTPException(415, "Upload raw .epd or .pgn content")
        if not filename.lower().endswith((".epd", ".pgn")):
            raise HTTPException(422, "Expected .epd or .pgn opening book")
        if used_bytes() > 4_000_000_000:
            raise HTTPException(507, "Arena data directory nearing quota")
        ip = request.client.host if request.client else "unknown"
        identity = hmac.new(salt, ip.encode(), hashlib.sha256).hexdigest()
        with connection() as db:
            daily_count = db.execute(
                "SELECT COUNT(*) FROM arena_books WHERE ip_hash=? AND created_at>?",
                (identity, time.time() - DAILY_SECONDS)
            ).fetchone()[0]
            if daily_count >= 3:
                raise HTTPException(429, "Opening book daily limit reached (3)")
            all_count = db.execute("SELECT COUNT(*) FROM arena_books").fetchone()[0]
            if all_count >= 80:
                raise HTTPException(503, "Arena book capacity is full")
        data = bytearray()
        async for part in request.stream():
            data.extend(part)
            if len(data) > MAX_BOOK_BYTES:
                raise HTTPException(413, "Opening book exceeds 5 MiB")
        try:
            book = normalize_book(bytes(data), filename)
        except InvalidBook as exc:
            raise HTTPException(422, str(exc)) from exc
        target = books_dir / f"{book.digest}.epd"
        if not target.exists():
            staging = books_dir / f".{secrets.token_hex(12)}.incoming"
            try:
                with staging.open("xb") as writer:
                    writer.write(book.content)
                    writer.flush()
                    os.fsync(writer.fileno())
                os.replace(staging, target)
                target.chmod(0o444)
            finally:
                staging.unlink(missing_ok=True)
        with connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO arena_books "
                "(digest,original_format,positions,ip_hash,created_at) "
                "VALUES(?,?,?,?,?)",
                (book.digest, book.original_format, book.positions,
                 identity, time.time())
            )
        return {
            "book_sha256": book.digest,
            "positions": book.positions,
            "input_format": book.original_format,
            "normalized_format": "epd",
            "note": "Opening positions normalized, SHA-256 automatically pinned"
        }

    @app.get("/api/arena/entries/{entry_id}")
    def arena_entry_public(entry_id: int):
        with connection() as db:
            row = db.execute(
                "SELECT * FROM arena_entries WHERE id=?", (entry_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Arena entry not found")
        return public_row(row)

    @app.get("/api/arena/entries/{entry_id}/pgn")
    def public_arena_pgn(entry_id: int):
        with connection() as db:
            row = db.execute(
                "SELECT pgn_path,status FROM arena_entries WHERE id=?",
                (entry_id,)
            ).fetchone()
        if not row or row["status"] not in (
            "passed", "rejected", "released", "discarded"
        ) or not row["pgn_path"]:
            raise HTTPException(404, "Completed PGN not available")
        filename = (data_dir / row["pgn_path"]).resolve()
        trusted_root = (data_dir / "pgn" / "arena").resolve()
        if not filename.is_relative_to(trusted_root) or not filename.is_file():
            raise HTTPException(404, "PGN archived or unavailable")
        return FileResponse(
            filename,
            media_type="application/x-chess-pgn",
            filename=f"arena-{entry_id}-100-games.pgn",
            headers={"X-Content-Type-Options": "nosniff"}
        )

    @app.post("/api/arena/submit", status_code=201)
    async def upload_engine(
        request: Request,
        engine_name: str | None = Query(default=None, max_length=80),
        engine_version: str | None = Query(default=None, max_length=60),
        source_url: str | None = Query(default=None, max_length=350),
        book_sha256: str | None = Query(
            default=None, pattern=r"^[0-9a-fA-F]{64}$"
        )
    ):
        # No user-entered engine name, version, hash or UCI settings needed.
        # Engine identity comes from a restricted probe inside the arena VM.
        reference, book, issue = arena_ready(
            book_sha256.lower() if book_sha256 else None
        )
        if issue:
            raise HTTPException(503, issue)
        if request.headers.get("content-type", "").split(";")[0].strip().lower() not in (
            "application/zip", "application/octet-stream",
            "application/x-msdownload", "application/vnd.microsoft.portable-executable"
        ):
            raise HTTPException(
                415, "Send a raw x86_64 Windows EXE or Linux ELF ZIP"
            )
        if source_url:
            parsed = urlsplit(source_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise HTTPException(422, "source_url must be a public HTTPS URL")
        length_header = request.headers.get("content-length")
        if length_header:
            try:
                if int(length_header) > MAX_CONTENT_LENGTH:
                    raise HTTPException(413, "ZIP upload exceeds 128 MiB")
            except ValueError as exc:
                raise HTTPException(400, "Invalid Content-Length") from exc

        # Never trust X-Forwarded-For supplied by the client. A trusted local
        # reverse proxy/uvicorn setup may normalize request.client.host.
        ip = request.client.host if request.client else "unknown"
        ip_hash = hmac.new(salt, ip.encode(), hashlib.sha256).hexdigest()
        name = (engine_name or "").strip() or "UCI detection pending"
        version = (engine_version or "").strip() or "automatic"
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            recent = db.execute(
                "SELECT COUNT(*) FROM arena_entries "
                "WHERE ip_hash=? AND created_at>?",
                (ip_hash, time.time() - DAILY_SECONDS)
            ).fetchone()[0]
            if recent >= MAX_PER_IP_PER_DAY:
                raise HTTPException(429, "Daily upload limit reached")
            waiting = db.execute(
                "SELECT COUNT(*) FROM arena_entries WHERE "
                "status IN ('uploading','queued','running')"
            ).fetchone()[0]
            if waiting >= MAX_QUEUED:
                raise HTTPException(503, "Arena queue is full")
             cursor = db.execute("""
                INSERT INTO arena_entries(
                    engine_name,engine_version,source_url,ip_hash,
                    reference_id,reference_sha256,reference_version,
                    book_sha256,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
            """, (name, version, source_url, ip_hash,
                  reference["id"], reference["sha256"], reference["version"],
                  book["sha256"], time.time()))
            entry_id = cursor.lastrowid

        temp_path = uploads_dir / f"{entry_id}.incoming"
        destination = None
        digest = hashlib.sha256()
        size = 0
        try:
            with temp_path.open("xb") as output:
                async for part in request.stream():
                    size += len(part)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "EXE/ZIP upload exceeds 128 MiB")
                    if used_bytes() + len(part) > 4_250_000_000:
                        raise HTTPException(507, "Arena storage budget exceeded")
                    output.write(part)
                    digest.update(part)
                if size < 64:
                    raise HTTPException(422, "Upload is not a valid EXE/ZIP archive")
                output.flush()
                os.fsync(output.fileno())
            details = inspect_candidate(temp_path)
            if details.platform == "windows_x86_64" and (
                os.getenv("OPENFISHTEST_WINDOWS_ARENA") != "1"
            ):
                raise HTTPException(
                    503, "Windows EXE sandbox unavailable; configure the "
                         "dedicated rootless Wine VM runner first"
                )
            ext = ".exe" if details.platform == "windows_x86_64" else ".zip"
            destination = uploads_dir / f"{entry_id}{ext}"
            # Content digest is for reproducibility, not a guarantee of safety.
            os.replace(temp_path, destination)
            with connection() as db:
                db.execute(
                    "UPDATE arena_entries SET status='queued',archive_path=?,"
                    "archive_sha256=?,engine_sha256=?,archive_bytes=?,"
                    "engine_platform=? WHERE id=?",
                    (str(destination.relative_to(data_dir)), digest.hexdigest(),
                     details.engine_sha256, size, details.platform, entry_id)
                )
                db.execute(
                    "INSERT INTO arena_events(arena_id,kind,summary,created_at) "
                    "VALUES(?,?,?,?)",
                    (entry_id, "queued", "Anonymous upload accepted for isolated arena", time.time())
                )
            return {
                "id": entry_id, "status": "queued", "games": GAMES,
                "pass_points": PASS_SCORE_X2 / 2,
                "archive_sha256": digest.hexdigest(),
                "engine_platform": details.platform,
                "engine_sha256": details.engine_sha256,
                "note": "SHA-256 computed automatically; UCI identity will be probed "
                        "inside isolated VM. No volunteer PC execution."
            }
        except (UnsafeArchive, OSError, HTTPException, ValueError) as exc:
            for path in (temp_path, destination):
                if path is not None:
                    path.unlink(missing_ok=True)
            with connection() as db:
                db.execute(
                    "UPDATE arena_entries SET status='invalid',archive_path=NULL,"
                    "error_class=? WHERE id=?",
                    ("invalid_archive" if isinstance(exc, UnsafeArchive) else "upload_rejected", entry_id)
                )
            if isinstance(exc, HTTPException):
                raise
            if isinstance(exc, UnsafeArchive):
                raise HTTPException(422, str(exc)) from exc
            raise HTTPException(422, "Upload validation failed") from exc

    def admin_entries():
        with connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,engine_name,engine_version,source_url,"
                "archive_sha256,engine_sha256,archive_bytes,engine_platform,"
                "uci_name,uci_author,uci_options_json,"
                "reference_version,reference_sha256,book_sha256,"
                "status,wins,draws,losses,score,created_at,completed_at,"
                "released_url,error_class,archive_path,pgn_path "
                "FROM arena_entries ORDER BY id DESC LIMIT 100"
            )]

    @app.get("/api/admin/arena")
    def list_arena_entries(
        request: Request, x_admin_token: str | None = Header(None)
    ):
        local_admin_only(request)
        require_admin(x_admin_token)
        rows = admin_entries()
        return {
            "entries": [{**row, "download_available": bool(
                row["status"] == "passed" and row["archive_path"]
            )} for row in rows],
            "notifications": sum(1 for row in rows if row["status"] == "passed")
        }

    @app.get("/api/admin/arena/{entry_id}/download")
    def download_candidate(
        entry_id: int, request: Request, x_admin_token: str | None = Header(None)
    ):
        local_admin_only(request)
        require_admin(x_admin_token)
        with connection() as db:
            entry = db.execute(
                "SELECT archive_path,status,archive_sha256 FROM arena_entries WHERE id=?",
                (entry_id,)
            ).fetchone()
        if not entry or entry["status"] != "passed" or not entry["archive_path"]:
            raise HTTPException(404, "No shortlisted engine ZIP")
        file_path = (data_dir / entry["archive_path"]).resolve()
        if not file_path.is_relative_to(uploads_dir.resolve()) or not file_path.is_file():
            raise HTTPException(404, "Candidate ZIP unavailable")
        if sha256_path(file_path) != entry["archive_sha256"]:
            raise HTTPException(409, "Candidate integrity check failed")
        return FileResponse(
            file_path, media_type="application/octet-stream",
            filename=(
                f"OpenFishtest-candidate-{entry_id}-QUARANTINED"
                f"{file_path.suffix}"
            ),
            headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"}
        )

    @app.post("/api/admin/arena/{entry_id}/discard")
    def discard_candidate(
        entry_id: int, request: Request, x_admin_token: str | None = Header(None)
    ):
        local_admin_only(request)
        require_admin(x_admin_token)
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = db.execute(
                "SELECT status,archive_path FROM arena_entries WHERE id=?",
                (entry_id,)
            ).fetchone()
            if not entry or entry["status"] not in ("passed", "rejected", "error", "invalid"):
                raise HTTPException(409, "Only completed entries can be discarded")
            db.execute(
                "UPDATE arena_entries SET status='discarded',archive_path=NULL WHERE id=?",
                (entry_id,)
            )
            db.execute(
                "INSERT INTO arena_events(arena_id,kind,summary,created_at) "
                "VALUES(?,?,?,?)",
                (entry_id, "discarded", "Admin discarded uploaded binary", time.time())
            )
        if entry["archive_path"]:
            candidate = (data_dir / entry["archive_path"]).resolve()
            if candidate.is_relative_to(uploads_dir.resolve()):
                candidate.unlink(missing_ok=True)
        return {"id": entry_id, "status": "discarded", "pgn_and_results_preserved": True}

    @app.post("/api/admin/arena/{entry_id}/mark-released")
    def mark_release(
        entry_id: int, body: ReleaseLink, request: Request,
        x_admin_token: str | None = Header(None)
    ):
        local_admin_only(request)
        require_admin(x_admin_token)
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM arena_entries WHERE id=?", (entry_id,)
            ).fetchone()
            if not row or row["status"] != "passed":
                raise HTTPException(409, "Only shortlisted candidates can be marked released")
            # This is an administrative record of a manually published Release.
            # Do not upload anything automatically from a community submission.
            db.execute(
                "UPDATE arena_entries SET status='released',released_url=? WHERE id=?",
                (str(body.release_url), entry_id)
            )
            db.execute(
                "INSERT INTO arena_events(arena_id,kind,summary,created_at)"
                " VALUES(?,?,?,?)",
                (entry_id, "released", "Administrator recorded a manually chosen release", time.time())
            )
        return {"id": entry_id, "status": "released", "url": str(body.release_url)}

    return {
        "public_summary": lambda limit=30: arena_public_summary(connection, limit),
        "ready": arena_ready,
    }


def arena_public_summary(connection, limit=30):
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM arena_entries WHERE status != 'uploading' "
            "ORDER BY id DESC LIMIT ?", (max(1, min(100, limit)),)
        ).fetchall()
    return [public_row(r) for r in rows]
