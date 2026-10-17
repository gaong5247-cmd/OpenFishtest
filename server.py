"""OpenFishtest API: Stockless-referenced tests and leased trusted workers.

Worker results remain unverified until independent validation is available.
The API should remain on localhost or a controlled private network for now.
"""
import json
import time
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

DATA_DIR = Path(os.getenv("OPENFISHTEST_DATA", "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "openfishtest.sqlite3"
ADMIN_TOKEN = os.getenv("OPENFISHTEST_ADMIN_TOKEN", "")
MAX_BYTES = 5_000_000_000
ARCHIVE_START_BYTES = 3_000_000_000
STOP_BYTES = 4_250_000_000
REFERENCE_RATING = 3000
ALLOWED_ORIGIN = os.getenv(
    "OPENFISHTEST_PUBLIC_ORIGIN", "https://gaong5247-cmd.github.io"
)

app = FastAPI(title="OpenFishtest", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Content-Type"],
)


@contextmanager
def connection():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


with connection() as db:
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS engines (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            source_url TEXT,
            approved INTEGER NOT NULL DEFAULT 1,
            UNIQUE(name, version, sha256)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY,
            engine_id INTEGER NOT NULL REFERENCES engines(id),
            reference_id INTEGER NOT NULL REFERENCES engines(id),
            games_target INTEGER NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0,
            draws INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued',
            created_at TEXT NOT NULL
        );
    """)
    engine_cols = {r["name"] for r in db.execute("PRAGMA table_info(engines)")}
    if "source_url" not in engine_cols:
        db.execute("ALTER TABLE engines ADD COLUMN source_url TEXT")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def used_bytes():
    return sum(p.stat().st_size for p in DATA_DIR.rglob("*") if p.is_file())


def require_admin(token):
    if not ADMIN_TOKEN or not secrets.compare_digest(ADMIN_TOKEN, token or ""):
        raise HTTPException(403, "Admin token required (X-Admin-Token)")


class EngineInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=80)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    source_url: HttpUrl | None = None


class ReferenceInput(BaseModel):
    engine_id: int = Field(ge=1)


class TestInput(BaseModel):
    engine_id: int = Field(ge=1)
    games_target: int = Field(ge=2, le=1000000)
    tc: str = Field(default="10+0.1", pattern=r"^[0-9]{1,5}(?:\:[0-5][0-9])?(?:\.[0-9]{1,3})?(?:\+[0-9]{1,4}(?:\.[0-9]{1,3})?)?$")
    book_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    book_format: Literal["epd", "pgn"] = "epd"
    batch_games: int = Field(default=20, ge=2, le=20)


class ResultInput(BaseModel):
    wins: int = Field(ge=0)
    draws: int = Field(ge=0)
    losses: int = Field(ge=0)


def get_reference_id(db):
    row = db.execute(
        "SELECT value FROM settings WHERE key='reference_engine_id'"
    ).fetchone()
    return int(row["value"]) if row else None


def snapshot():
    """Publish real engine/test statistics, with explicit uncertainty labels.

    No simulated matches. Workers and engine authors are never implicitly
    trusted; all reported games remain unverified as to their origin.
    """
    from collections import defaultdict
    from engine_stats import analyze
    from public_games import recent_games, recent_arena_games
    from arena_api import arena_public_summary

    used = used_bytes()
    with connection() as db:
        reference_id = get_reference_id(db)
        all_engines = [dict(r) for r in db.execute(
            "SELECT id,name,version,sha256,source_url FROM engines WHERE approved=1 ORDER BY id"
        )]
        engine_by_id = {e["id"]: e for e in all_engines}
        all_tests = [dict(r) for r in db.execute(
            "SELECT * FROM tests ORDER BY id DESC LIMIT 100"
        )]
        aggregates = {
            r["engine_id"]: dict(r) for r in db.execute(
                "SELECT engine_id, SUM(wins) AS wins, SUM(draws) AS draws, "
                "SUM(losses) AS losses FROM tests WHERE reference_id=? GROUP BY engine_id",
                (reference_id,)
            )
        }
        test_settings = {
            r["test_id"]: dict(r) for r in db.execute("SELECT * FROM test_settings")
        }
        pair_by_test = defaultdict(lambda: [0] * 5)
        pair_by_engine = defaultdict(lambda: [0] * 5)
        for job in db.execute("""
            SELECT j.test_id, j.penta_json, t.engine_id, t.reference_id
            FROM jobs j JOIN tests t ON j.test_id=t.id
            WHERE j.status='done' AND j.penta_json IS NOT NULL
        """):
            try:
                values = json.loads(job["penta_json"])
                if len(values) != 5 or any(
                    not isinstance(v, int) or v < 0 for v in values
                ):
                    continue
            except (ValueError, TypeError):
                continue
            for idx, amount in enumerate(values):
                pair_by_test[job["test_id"]][idx] += amount
                if job["reference_id"] == reference_id:
                    pair_by_engine[job["engine_id"]][idx] += amount
        workers = [dict(row) for row in db.execute("""
            SELECT w.id, w.display_name, w.active,
                   COUNT(CASE WHEN j.status='done' THEN 1 END) AS completed_jobs,
                   COALESCE(SUM(CASE WHEN j.status='done' THEN j.games ELSE 0 END),0)
                   AS games,
                   MAX(CASE WHEN j.status='done' THEN j.completed_at END)
                   AS last_completed
            FROM workers w LEFT JOIN jobs j ON j.worker_id=w.id
            GROUP BY w.id
            ORDER BY games DESC, completed_jobs DESC, w.id
            LIMIT 50
        """)]
        live_workers = db.execute(
            "SELECT COUNT(DISTINCT worker_id) FROM jobs WHERE status='leased' "
            "AND lease_expires > ?", (time.time(),)
        ).fetchone()[0]

    leaderboard = []
    for engine in all_engines:
        is_ref = engine["id"] == reference_id
        totals = aggregates.get(engine["id"], {}) if not is_ref else {}
        wins, draws, losses = (totals.get("wins", 0), totals.get("draws", 0),
                               totals.get("losses", 0))
        stats = analyze(wins, draws, losses, pair_by_engine.get(engine["id"]))
        offset = stats["elo_diff"]
        # Avoid ranking a 1- or 2-game fluke as meaningful engine strength.
        # Even 20 games are merely exploratory; always display uncertainty.
        enough_for_display = stats["games"] >= 20
        elo = REFERENCE_RATING if is_ref else (
            round(REFERENCE_RATING + offset, 1)
            if enough_for_display and offset is not None else None
        )
        ci = [
            round(REFERENCE_RATING + stats["ci95_low"], 1),
            round(REFERENCE_RATING + stats["ci95_high"], 1)
        ] if (not is_ref and enough_for_display and
              stats["ci95_low"] is not None) else None
        leaderboard.append({
            "id": engine["id"], "name": engine["name"],
            "version": engine["version"],
            "source_url": engine.get("source_url"),
            "is_reference": is_ref,
            "games": stats["games"], "wins": wins, "draws": draws, "losses": losses,
            "rating": elo, "rating_ci95": ci,
            "statistics": stats
        })
    for test in all_tests:
        test["engine_name"] = engine_by_id.get(test["engine_id"], {}).get("name", "Unknown")
        test["reference_name"] = engine_by_id.get(test["reference_id"], {}).get("name", "Unknown")
        test["games_done"] = test["wins"] + test["draws"] + test["losses"]
        test["tc"] = test_settings.get(test["id"], {}).get("tc", "10+0.1")
        test["statistics"] = analyze(
            test["wins"], test["draws"], test["losses"], pair_by_test.get(test["id"])
        )
    # No raw worker token or machine hostnames are included in the public data.
    public_workers = [
        {"name": w["display_name"], "worker_id": w["id"],
         "games": w["games"], "completed_jobs": w["completed_jobs"],
         "last_completed": w["last_completed"]}
        for w in workers if w["games"] > 0 or w["active"]
    ]
    return {
        "project": "OpenFishtest",
        "updated_at": now_iso(),
        "mode": "quarantined_arena_v04",
        "verification": "worker_reported_unverified",
        "reference": engine_by_id.get(reference_id),
        "reference_rating": REFERENCE_RATING,
        "engines": leaderboard,
        "tests": all_tests,
        "workers": public_workers,
        "active_workers": live_workers,
        "recent_games": recent_arena_games(connection, DATA_DIR, 6) + recent_games(connection, DATA_DIR, 2),
        "arena": arena_public_summary(connection),
        "arena_rules": {"games": 100, "pass_points": 55.0, "score": "wins + 0.5*draws", "automatic_release": False},
        "statistics_notice": (
            "Provisional Elo and paired Gaussian SPRT are approximate; "
            "not FIDE/CCRL ratings or Stockfish GSPRT. "
            "PGN moves are parsed as legal chess but engine origin is unverified."
        ),
        "storage": {
            "used_bytes": used,
            "max_bytes": MAX_BYTES,
            "archive_start_bytes": ARCHIVE_START_BYTES,
            "stop_bytes": STOP_BYTES,
            "archive_recommended": used >= ARCHIVE_START_BYTES,
            "accept_new_tests": used < STOP_BYTES,
        }
    }


def local_admin_only(request: Request):
    # This interface is intentionally not exposed through GitHub Pages.
    # CAUTION: reverse proxies can obscure the original client's IP; never
    # publish this development server directly on the public internet.
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "Local administrator interface only")


ADMIN_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'; object-src 'none'"
)


@app.get("/admin")
def local_admin_page(request: Request):
    local_admin_only(request)
    return FileResponse(
        Path(__file__).parent / "admin_ui" / "index.html",
        media_type="text/html",
        headers={"Cache-Control":"no-store", "Content-Security-Policy":ADMIN_CSP,
                 "X-Content-Type-Options":"nosniff"}
    )


@app.get("/admin-ui/{filename}")
def local_admin_asset(filename: str, request: Request):
    local_admin_only(request)
    if filename not in ("app.js", "style.css"):
        raise HTTPException(404, "Unknown admin asset")
    return FileResponse(
        Path(__file__).parent / "admin_ui" / filename,
        headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"}
    )


@app.get("/api/ai/openapi.json", include_in_schema=False)
def assistant_actions_schema():
    """Only public, read-only operations are exposed to AI chat connectors."""
    from ai_openapi import schema
    return schema()


@app.get("/api/health")
def health():
    s = snapshot()
    return {"status": "ok", "storage": s["storage"], "reference_ready": s["reference"] is not None}


@app.get("/api/public/snapshot")
def public_snapshot():
    return snapshot()


@app.post("/api/admin/engines", status_code=201)
def register_engine(body: EngineInput, x_admin_token: str | None = Header(None)):
    require_admin(x_admin_token)
    with connection() as db:
        try:
            cur = db.execute(
                "INSERT INTO engines(name,version,sha256,source_url) VALUES(?,?,?,?)",
                (body.name.strip(), body.version.strip(), body.sha256.lower(),
                 str(body.source_url) if body.source_url else None)
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Engine build already registered") from None
        return {"id": cur.lastrowid}


@app.post("/api/admin/reference")
def pin_reference(body: ReferenceInput, x_admin_token: str | None = Header(None)):
    require_admin(x_admin_token)
    with connection() as db:
        row = db.execute("SELECT name FROM engines WHERE id=? AND approved=1",
                         (body.engine_id,)).fetchone()
        if not row or row["name"].casefold() != "stockless":
            raise HTTPException(422, "Reference engine must be an approved Stockless build")
        db.execute(
            "INSERT INTO settings(key,value) VALUES('reference_engine_id',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(body.engine_id),)
        )
    return {"reference_engine_id": body.engine_id, "rating_anchor": REFERENCE_RATING}


@app.post("/api/admin/tests", status_code=201)
def create_test(body: TestInput, x_admin_token: str | None = Header(None)):
    require_admin(x_admin_token)
    if used_bytes() >= STOP_BYTES:
        raise HTTPException(507, "Data quota safety limit reached")
    if body.games_target % 2 != 0 or body.batch_games % 2 != 0:
        raise HTTPException(422, "Paired-opening tests require even game counts")
    with connection() as db:
        reference_id = get_reference_id(db)
        if reference_id is None:
            raise HTTPException(409, "Pin a Stockless reference build first")
        if reference_id == body.engine_id:
            raise HTTPException(422, "Cannot test a build against itself")
        if not db.execute(
            "SELECT 1 FROM engines WHERE id=? AND approved=1",
            (body.engine_id,)
        ).fetchone():
            raise HTTPException(404, "Engine not found")
        cur = db.execute(
            "INSERT INTO tests(engine_id,reference_id,games_target,created_at) VALUES(?,?,?,?)",
            (body.engine_id, reference_id, body.games_target, now_iso())
        )
        db.execute(
            "INSERT INTO test_settings(test_id,tc,book_sha256,book_format,batch_games) VALUES(?,?,?,?,?)",
            (cur.lastrowid, body.tc, body.book_sha256.lower() if body.book_sha256 else None,
             body.book_format, body.batch_games)
        )
        return {"id": cur.lastrowid, "status": "queued", "execution": "fastchess_worker"}


@app.put("/api/admin/tests/{test_id}/results")
def report_results(test_id: int, body: ResultInput,
                   x_admin_token: str | None = Header(None)):
    """Idempotently SET manual cumulative results (not additive)."""
    require_admin(x_admin_token)
    total = body.wins + body.draws + body.losses
    with connection() as db:
        row = db.execute("SELECT games_target FROM tests WHERE id=?", (test_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Test not found")
        if total > row["games_target"]:
            raise HTTPException(422, "Results exceed requested game count")
        if db.execute("SELECT 1 FROM jobs WHERE test_id=? LIMIT 1", (test_id,)).fetchone():
            raise HTTPException(409, "Worker jobs exist; manual overwrite prohibited")
        status = "complete_unverified" if total == row["games_target"] else "partial_unverified"
        db.execute(
            "UPDATE tests SET wins=?,draws=?,losses=?,status=? WHERE id=?",
            (body.wins, body.draws, body.losses, status, test_id)
        )
    return {"id": test_id, "games_done": total, "status": status}


@app.post("/api/admin/tests/{test_id}/pause")
def pause_test(test_id: int, x_admin_token: str | None = Header(None)):
    """Revoke current job leases and keep unfinished work available for resume."""
    require_admin(x_admin_token)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        test = db.execute("SELECT status FROM tests WHERE id=?", (test_id,)).fetchone()
        if not test:
            raise HTTPException(404, "Test not found")
        if test["status"] not in ("queued", "running", "worker_error"):
            raise HTTPException(409, "Test cannot be paused in this state")
        db.execute("UPDATE tests SET status='paused' WHERE id=?", (test_id,))
        db.execute(
            "UPDATE jobs SET status='queued',lease_id=NULL,lease_expires=0 "
            "WHERE test_id=? AND status='leased'",
            (test_id,)
        )
    return {"id": test_id, "status": "paused"}


@app.post("/api/admin/tests/{test_id}/resume")
def resume_test(test_id: int, x_admin_token: str | None = Header(None)):
    """Allow manually paused or worker-error jobs to be reassigned."""
    require_admin(x_admin_token)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        test = db.execute("SELECT status FROM tests WHERE id=?", (test_id,)).fetchone()
        if not test:
            raise HTTPException(404, "Test not found")
        if test["status"] not in ("paused", "worker_error"):
            raise HTTPException(409, "Only paused or worker_error tests can resume")
        db.execute(
            "UPDATE jobs SET status='queued',lease_id=NULL,lease_expires=0,"
            "attempts=0 WHERE test_id=? AND status='failed'",
            (test_id,)
        )
        db.execute("UPDATE tests SET status='queued' WHERE id=?", (test_id,))
    return {"id": test_id, "status": "queued"}


@app.post("/api/admin/tests/{test_id}/cancel")
def cancel_test(test_id: int, x_admin_token: str | None = Header(None)):
    """Permanently stop a test and revoke all unfinished jobs."""
    require_admin(x_admin_token)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        test = db.execute("SELECT status FROM tests WHERE id=?", (test_id,)).fetchone()
        if not test:
            raise HTTPException(404, "Test not found")
        if test["status"] not in ("queued", "running", "paused", "worker_error"):
            raise HTTPException(409, "Test cannot be cancelled in this state")
        db.execute("UPDATE tests SET status='cancelled' WHERE id=?", (test_id,))
        db.execute(
            "UPDATE jobs SET status='cancelled',lease_id=NULL,lease_expires=0 "
            "WHERE test_id=? AND status IN ('queued','leased','failed')",
            (test_id,)
        )
    return {"id": test_id, "status": "cancelled"}


# Persistent worker job queue and PGN result endpoints.
from jobs_api import register_job_api
register_job_api(app, connection, used_bytes, DATA_DIR, require_admin)

# Public self-service ZIP submission; the HTTP server NEVER executes ZIPs.
from arena_api import register_arena_api
register_arena_api(app, connection, get_reference_id, used_bytes,
                   DATA_DIR, require_admin, local_admin_only)
