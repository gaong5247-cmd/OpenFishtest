"""Authenticated local-worker job queue for OpenFishtest v0.2.

Prototype security model: one server-side shared worker secret, approved engine
SHA-256 identities, leased jobs and unverified worker-reported PGN evidence.
Run behind localhost/private network. No arbitrary engine downloads or execution.
"""
import base64
import binascii
import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from match_protocol import MAX_PGN_BYTES, MatchValidationError, parse_pgn_results

LEASE_SECONDS = 180
MAX_BATCH_GAMES = 20
MAX_PGN_BASE64 = 2_700_000


class WorkerIdentity(BaseModel):
    worker_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")


class LeaseRequest(BaseModel):
    lease_id: str = Field(min_length=20, max_length=100)


class FinishRequest(LeaseRequest):
    pgn_base64: str = Field(min_length=8, max_length=MAX_PGN_BASE64)
    pgn_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class FailRequest(LeaseRequest):
    reason: str = Field(min_length=1, max_length=500)


def setup_job_schema(connection):
    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS test_settings (
                test_id INTEGER PRIMARY KEY REFERENCES tests(id),
                tc TEXT NOT NULL DEFAULT '10+0.1',
                book_sha256 TEXT,
                book_format TEXT NOT NULL DEFAULT 'epd',
                batch_games INTEGER NOT NULL DEFAULT 20
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                test_id INTEGER NOT NULL REFERENCES tests(id),
                start_game INTEGER NOT NULL,
                games INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                lease_id TEXT,
                lease_expires REAL NOT NULL DEFAULT 0,
                worker_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                draws INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                pgn_sha256 TEXT,
                pgn_path TEXT,
                last_error TEXT,
                created_at REAL NOT NULL,
                completed_at REAL,
                UNIQUE(test_id, start_game)
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, lease_expires);
            CREATE INDEX IF NOT EXISTS idx_jobs_test ON jobs(test_id);
        """)


def register_job_api(app: FastAPI, connection, used_bytes, data_dir: Path):
    setup_job_schema(connection)

    def require_worker(token):
        expected = os.getenv("OPENFISHTEST_WORKER_TOKEN", "")
        if not expected or not secrets.compare_digest(expected, token or ""):
            raise HTTPException(403, "Valid X-Worker-Token required")

    def get_job(db, job_id):
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        return row

    def check_lease(row, lease_id):
        if not row["lease_id"] or not secrets.compare_digest(row["lease_id"], lease_id):
            raise HTTPException(409, "Incorrect or outdated lease")
        if row["status"] == "done":
            return "done"
        if row["status"] != "leased" or row["lease_expires"] < time.time():
            raise HTTPException(409, "Lease has expired or been revoked")
        return "leased"

    @app.post("/api/worker/claim", status_code=200)
    def claim(body: WorkerIdentity, x_worker_token: str | None = Header(None)):
        require_worker(x_worker_token)
        if used_bytes() >= 4_250_000_000:
            raise HTTPException(507, "Storage limit: no new work")
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # An expired job is retried using the SAME start_game (no duplicates).
            # Repeated crashes eventually halt a test instead of looping forever.
            now = time.time()
            db.execute(
                "UPDATE tests SET status='worker_error' WHERE id IN "
                "(SELECT test_id FROM jobs WHERE status='leased' AND "
                "lease_expires < ? AND attempts >= 3)",
                (now,)
            )
            db.execute(
                "UPDATE jobs SET status='failed',lease_id=NULL,lease_expires=0 "
                "WHERE status='leased' AND lease_expires < ? AND attempts >= 3",
                (now,)
            )
            db.execute(
                "UPDATE jobs SET status='queued',lease_id=NULL,lease_expires=0,"
                "worker_id=NULL WHERE status='leased' AND lease_expires < ?",
                (now,)
            )
            job = db.execute("""
                SELECT j.* FROM jobs j JOIN tests t ON t.id=j.test_id
                WHERE j.status='queued' AND t.status IN ('queued','running')
                ORDER BY j.id LIMIT 1
            """).fetchone()
            if job is None:
                tests = db.execute(
                    "SELECT * FROM tests WHERE status IN ('queued','running') ORDER BY id"
                ).fetchall()
                for test in tests:
                    allocated = db.execute(
                        "SELECT COALESCE(SUM(games),0) FROM jobs WHERE test_id=?",
                        (test["id"],)
                    ).fetchone()[0]
                    if allocated >= test["games_target"]:
                        continue
                    settings = db.execute(
                        "SELECT batch_games FROM test_settings WHERE test_id=?",
                        (test["id"],)
                    ).fetchone()
                    batch_size = settings["batch_games"] if settings else MAX_BATCH_GAMES
                    games = min(batch_size, test["games_target"] - allocated)
                    if games % 2 or games < 2:
                        raise HTTPException(500, "Unexpected unpaired job")
                    cur = db.execute(
                        "INSERT INTO jobs(test_id,start_game,games,created_at) VALUES(?,?,?,?)",
                        (test["id"], allocated, games, time.time())
                    )
                    job = get_job(db, cur.lastrowid)
                    break
            if job is None:
                return Response(status_code=204)

            engine = db.execute(
                "SELECT id,name,version,sha256 FROM engines WHERE id="
                "(SELECT engine_id FROM tests WHERE id=?)", (job["test_id"],)
            ).fetchone()
            reference = db.execute(
                "SELECT id,name,version,sha256 FROM engines WHERE id="
                "(SELECT reference_id FROM tests WHERE id=?)", (job["test_id"],)
            ).fetchone()
            if not engine or not reference:
                raise HTTPException(500, "Test has missing engine records")
            if reference["name"].casefold() != "stockless":
                raise HTTPException(409, "Job has no Stockless reference")
            lease = secrets.token_urlsafe(32)
            db.execute(
                "UPDATE jobs SET status='leased',lease_id=?,lease_expires=?,"
                "worker_id=?,attempts=attempts+1 WHERE id=?",
                (lease, time.time() + LEASE_SECONDS, body.worker_id, job["id"])
            )
            db.execute(
                "UPDATE tests SET status='running' WHERE id=? AND status='queued'",
                (job["test_id"],)
            )
            settings = db.execute(
                "SELECT * FROM test_settings WHERE test_id=?", (job["test_id"],)
            ).fetchone()
            return {
                "job_id": job["id"], "test_id": job["test_id"],
                "start_game": job["start_game"], "games": job["games"],
                "lease_id": lease, "lease_seconds": LEASE_SECONDS,
                "challenger": dict(engine), "reference": dict(reference),
                "tc": settings["tc"] if settings else "10+0.1",
                "book_sha256": settings["book_sha256"] if settings else None,
                "book_format": settings["book_format"] if settings else "epd",
            }

    @app.post("/api/worker/jobs/{job_id}/heartbeat")
    def heartbeat(job_id: int, body: LeaseRequest,
                  x_worker_token: str | None = Header(None)):
        require_worker(x_worker_token)
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = get_job(db, job_id)
            if check_lease(job, body.lease_id) != "leased":
                raise HTTPException(409, "Completed job cannot be heartbeated")
            db.execute(
                "UPDATE jobs SET lease_expires=? WHERE id=?",
                (time.time() + LEASE_SECONDS, job_id)
            )
        return {"job_id": job_id, "lease_seconds": LEASE_SECONDS}

    @app.post("/api/worker/jobs/{job_id}/failed")
    def failed(job_id: int, body: FailRequest,
               x_worker_token: str | None = Header(None)):
        require_worker(x_worker_token)
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = get_job(db, job_id)
            if check_lease(job, body.lease_id) != "leased":
                raise HTTPException(409, "Job already finished")
            exhausted = job["attempts"] >= 3
            db.execute(
                "UPDATE jobs SET status=?,lease_id=NULL,lease_expires=0,"
                "last_error=? WHERE id=?",
                ("failed" if exhausted else "queued", body.reason, job_id)
            )
            if exhausted:
                db.execute(
                    "UPDATE tests SET status='worker_error' WHERE id=?",
                    (job["test_id"],)
                )
        return {"job_id": job_id, "retry_allowed": not exhausted}

    @app.post("/api/worker/jobs/{job_id}/finish")
    def finish(job_id: int, body: FinishRequest,
               x_worker_token: str | None = Header(None)):
        require_worker(x_worker_token)
        try:
            pgn = base64.b64decode(body.pgn_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "Invalid PGN base64") from exc
        if len(pgn) > MAX_PGN_BYTES:
            raise HTTPException(413, "PGN batch too large")
        actual_digest = hashlib.sha256(pgn).hexdigest()
        if not secrets.compare_digest(body.pgn_sha256.lower(), actual_digest):
            raise HTTPException(422, "PGN checksum mismatch")

        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = get_job(db, job_id)
            if check_lease(job, body.lease_id) == "done":
                if job["pgn_sha256"] != actual_digest:
                    raise HTTPException(409, "Already completed with different PGN")
                return {"job_id": job_id, "accepted": True, "duplicate": True}
            try:
                result = parse_pgn_results(pgn, job["games"])
            except MatchValidationError as exc:
                raise HTTPException(422, str(exc)) from exc
            if used_bytes() + len(pgn) > 5_000_000_000:
                raise HTTPException(507, "Not enough disk space for PGN")
            relative = f"pgn/test-{job['test_id']}/job-{job_id}.pgn"
            destination = data_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            pending = destination.with_suffix(".upload")
            try:
                with pending.open("wb") as handle:
                    handle.write(pgn)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(pending, destination)
                db.execute(
                    "UPDATE jobs SET status='done',wins=?,draws=?,losses=?,"
                    "pgn_sha256=?,pgn_path=?,completed_at=? WHERE id=?",
                    (result.wins, result.draws, result.losses, actual_digest,
                     relative, time.time(), job_id)
                )
                db.execute(
                    "UPDATE tests SET wins=wins+?,draws=draws+?,losses=losses+? "
                    "WHERE id=?",
                    (result.wins, result.draws, result.losses, job["test_id"])
                )
                stats = db.execute(
                    "SELECT wins,draws,losses,games_target FROM tests WHERE id=?",
                    (job["test_id"],)
                ).fetchone()
                completed = (
                    stats["wins"] + stats["draws"] + stats["losses"]
                    == stats["games_target"]
                )
                db.execute(
                    "UPDATE tests SET status=? WHERE id=?",
                    ("complete_worker_reported" if completed else "running",
                     job["test_id"])
                )
            except Exception:
                pending.unlink(missing_ok=True)
                raise

        return {
            "job_id": job_id, "accepted": True, "duplicate": False,
            "results": {
                "wins": result.wins, "draws": result.draws,
                "losses": result.losses, "games": result.games
            },
            "verification": "worker_reported_not_independently_verified"
        }
