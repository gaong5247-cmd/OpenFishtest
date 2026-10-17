"""OpenFishtest MVP API: local-only administration and public read-only snapshots.

This prototype stores manually reported aggregate results. It does NOT run games,
assign volunteer workers, verify engine binaries, or automatically archive PGNs.
"""
import json
import math
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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

app = FastAPI(title="OpenFishtest", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["GET"],
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


class ReferenceInput(BaseModel):
    engine_id: int = Field(ge=1)


class TestInput(BaseModel):
    engine_id: int = Field(ge=1)
    games_target: int = Field(ge=2, le=1000000)


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
    used = used_bytes()
    with connection() as db:
        reference_id = get_reference_id(db)
        all_engines = [dict(r) for r in db.execute(
            "SELECT id,name,version,sha256 FROM engines WHERE approved=1 ORDER BY id"
        )]
        engine_by_id = {e["id"]: e for e in all_engines}
        all_tests = [dict(r) for r in db.execute(
            "SELECT * FROM tests ORDER BY id DESC LIMIT 100"
        )]
    leaderboard = []
    for engine in all_engines:
        # Only count results reported against the current pinned Stockless build.
        games = wins = draws = losses = 0
        if engine["id"] != reference_id:
            for test in all_tests:
                if test["engine_id"] == engine["id"] and test["reference_id"] == reference_id:
                    wins += test["wins"]
                    draws += test["draws"]
                    losses += test["losses"]
            games = wins + draws + losses
        score = (wins + 0.5 * draws) / games if games else None
        # This is a simple score-to-Elo conversion, NOT a statistically
        # validated or cross-pool engine rating.
        delta = (
            round(400 * math.log10(score / (1 - score)))
            if score is not None and 0 < score < 1 else None
        )
        leaderboard.append({
            "id": engine["id"], "name": engine["name"],
            "version": engine["version"],
            "is_reference": engine["id"] == reference_id,
            "games": games, "wins": wins, "draws": draws, "losses": losses,
            "rating": REFERENCE_RATING if engine["id"] == reference_id
            else REFERENCE_RATING + delta if delta is not None else None
        })
    for test in all_tests:
        test["engine_name"] = engine_by_id.get(test["engine_id"], {}).get("name", "Unknown")
        test["reference_name"] = engine_by_id.get(test["reference_id"], {}).get("name", "Unknown")
        test["games_done"] = test["wins"] + test["draws"] + test["losses"]
    return {
        "project": "OpenFishtest",
        "updated_at": now_iso(),
        "mode": "manual-results-mvp",
        "reference": engine_by_id.get(reference_id),
        "reference_rating": REFERENCE_RATING,
        "engines": leaderboard,
        "tests": all_tests,
        "storage": {
            "used_bytes": used,
            "max_bytes": MAX_BYTES,
            "archive_start_bytes": ARCHIVE_START_BYTES,
            "stop_bytes": STOP_BYTES,
            "archive_recommended": used >= ARCHIVE_START_BYTES,
            "accept_new_tests": used < STOP_BYTES,
        }
    }


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
                "INSERT INTO engines(name,version,sha256) VALUES(?,?,?)",
                (body.name.strip(), body.version.strip(), body.sha256.lower())
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
    if body.games_target % 2 != 0:
        raise HTTPException(422, "Paired-opening tests require an even game count")
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
        return {"id": cur.lastrowid, "status": "queued", "execution": "not_implemented"}


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
        status = "complete_unverified" if total == row["games_target"] else "partial_unverified"
        db.execute(
            "UPDATE tests SET wins=?,draws=?,losses=?,status=? WHERE id=?",
            (body.wins, body.draws, body.losses, status, test_id)
        )
    return {"id": test_id, "games_done": total, "status": status}
