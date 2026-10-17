"""Dedicated *Linux VM* arena runner for untrusted UCI challenger uploads.

MUST run on a separate disposable Linux VM with a rootless Docker daemon.
Does not serve HTTP and does not distribute uploaded executables to volunteers.
Docker isolation mitigates risk, but is NOT an absolute security guarantee.

Usage (on isolated Linux VM with access to OPENFISHTEST_DATA):
  OPENFISHTEST_ARENA_BOOK=/path/openings.epd \
  OPENFISHTEST_ARENA_REFERENCE_DIR=/path/trusted-stockless \
  python arena_runner.py --once

Build a trusted container image from deployment/Dockerfile.arena (the
operator must supply a locally built trusted Fastchess ELF).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import chess
import chess.pgn

from arena_api import arena_book_metadata, setup_arena_schema
from arena_core import (
    GAMES, MAX_PGN_BYTES, UnsafeArchive,
    classify_score, extract_quarantined
)
from match_protocol import parse_pgn_results, sha256_path

TIMEOUT_SECONDS = 7200
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_WORK_BYTES = 750 * 1024 * 1024
DOCKER_IMAGE = "openfishtest/arena:0.4"
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9_.:/-]{2,100}$")


class ArenaRunnerError(RuntimeError):
    pass


def require_dedicated_rootless(docker="docker"):
    if sys.platform != "linux":
        raise ArenaRunnerError(
            "Untrusted arena is Linux-only; use a dedicated disposable Linux VM"
        )
    if os.geteuid() == 0:
        raise ArenaRunnerError("Do not run the arena runner as root")
    process = subprocess.run(
        [docker, "info", "--format", "{{json .SecurityOptions}}"],
        capture_output=True, text=True, check=False, timeout=15
    )
    if process.returncode:
        raise ArenaRunnerError("Rootless Docker daemon is not available")
    try:
        options = json.loads(process.stdout)
    except (ValueError, TypeError) as exc:
        raise ArenaRunnerError("Could not inspect Docker security options") from exc
    if not isinstance(options, list) or not any(
        "rootless" in str(item).lower() for item in options
    ):
        raise ArenaRunnerError(
            "Refusing privileged Docker daemon; enable Docker rootless mode"
        )


def checked_reference(directory: Path, expected_sha256: str) -> Path:
    binary = directory / "engine"
    if binary.is_symlink() or not binary.is_file():
        raise ArenaRunnerError("Pinned Stockless engine binary missing")
    if sha256_path(binary) != expected_sha256:
        raise ArenaRunnerError("Pinned Stockless SHA-256 mismatch")
    return binary


def arena_command(entry_id, challenger_dir: Path, reference_dir: Path,
                  book: Path, results_dir: Path,
                  tc="10+0.1", image=DOCKER_IMAGE, cpus=2, memory_mb=768):
    """Only fixed, operator-configured paths, options and image are passed.

    All attacker bytes remain on read-only container mounts without a network.
    The container receives no Docker socket, host home directory or admin
    credentials. It writes only to the per-run /results bind mount.
    """
    if not IMAGE_RE.fullmatch(image):
        raise ValueError("Unexpected Docker image name")
    if not re.fullmatch(r"^[0-9]{1,5}(?:\+[0-9]+(?:\.[0-9]+)?)?$", tc):
        raise ValueError("Invalid arena time control")
    if cpus not in (1, 2, 4) or not 256 <= memory_mb <= 2048:
        raise ValueError("Invalid sandbox resource limits")
    container_name = f"openfishtest-arena-{int(entry_id)}"
    return [
        "docker", "run", "--rm", "--name", container_name,
        "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--pids-limit", "96", "--cpus", str(cpus),
        "--memory", f"{memory_mb}m", "--memory-swap", f"{memory_mb}m",
        "--user", "65534:65534", "--ulimit", "nofile=128:128",
        "--ulimit", "core=0:0",
        "--tmpfs", "/tmp:rw,nosuid,noexec,size=32m",
        "--mount", f"type=bind,src={challenger_dir.resolve()},dst=/challenger,readonly",
        "--mount", f"type=bind,src={reference_dir.resolve()},dst=/reference,readonly",
        "--mount", f"type=bind,src={book.resolve()},dst=/book/openings.epd,readonly",
        "--mount", f"type=bind,src={results_dir.resolve()},dst=/results",
        "--workdir", "/tmp", image,
        "fastchess",
        "-engine", "cmd=/challenger/engine", "name=Challenger",
        "dir=/challenger",
        "-engine", "cmd=/reference/engine", "name=Stockless",
        "dir=/reference",
        "-each", "proto=uci", f"tc={tc}",
        "-openings", "file=/book/openings.epd", "format=epd",
        "order=sequential", "start=1",
        "-games", "2", "-rounds", str(GAMES // 2), "-repeat",
        "-concurrency", "1",
        "-ratinginterval", "0", "-autosaveinterval", "0",
        "-pgnout", "file=/results/match.pgn", "notation=san", "append=false",
        "-event", f"OpenFishtest Arena #{int(entry_id)}"
    ]


def verify_expected_openings(pgn_bytes: bytes, book: Path):
    """Check that exactly fifty paired openings match the pinned EPD book."""
    import io

    openings = []
    with book.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            board = chess.Board()
            board.set_epd(line)
            openings.append(board.fen(en_passant="fen"))
            if len(openings) == GAMES // 2:
                break
    if len(openings) != GAMES // 2:
        raise ArenaRunnerError("Expected 50 opening positions")
    stream = io.StringIO(pgn_bytes.decode("utf-8-sig"))
    for idx in range(GAMES):
        game = chess.pgn.read_game(stream)
        if game is None or game.errors:
            raise ArenaRunnerError("PGN lacks complete legal opening pairs")
        observed = game.board().fen(en_passant="fen")
        if observed != openings[idx // 2]:
            raise ArenaRunnerError("PGN starting position differs from configured EPD")
    if chess.pgn.read_game(stream) is not None:
        raise ArenaRunnerError("PGN contains extra games")


def _cleanup_container(entry_id, docker="docker"):
    subprocess.run(
        [docker, "rm", "-f", f"openfishtest-arena-{int(entry_id)}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=15, check=False
    )


def _run_sandbox(command, entry_id, log_path: Path, result_path: Path,
                 timeout=TIMEOUT_SECONDS):
    # Use a file-backed log, never subprocess.PIPE for untrusted engine output.
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            command, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, shell=False
        )
        started = time.monotonic()
        try:
            while proc.poll() is None:
                if time.monotonic() - started >= timeout:
                    raise ArenaRunnerError("Sandbox time limit exceeded")
                if log_path.stat().st_size > MAX_LOG_BYTES:
                    raise ArenaRunnerError("Sandbox stdout limit exceeded")
                if result_path.exists() and result_path.stat().st_size > MAX_PGN_BYTES:
                    raise ArenaRunnerError("PGN output limit exceeded")
                if result_path.parent.parent.exists():
                    working_size = sum(
                        p.stat().st_size for p in result_path.parent.parent.rglob("*")
                        if p.is_file()
                    )
                    if working_size > MAX_WORK_BYTES:
                        raise ArenaRunnerError("Sandbox working directory quota exceeded")
                time.sleep(1)
            if proc.returncode != 0:
                raise ArenaRunnerError(f"Fastchess sandbox exited with code {proc.returncode}")
            if not result_path.is_file() or result_path.stat().st_size > MAX_PGN_BYTES:
                raise ArenaRunnerError("Missing or oversized arena PGN")
        except BaseException:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            raise
        finally:
            _cleanup_container(entry_id)


def claim_next(connection):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM arena_entries WHERE status='queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        token = uuid.uuid4().hex
        db.execute(
            "UPDATE arena_entries SET status='running',run_id=?,started_at=? WHERE id=?",
            (token, time.time(), row["id"])
        )
        return dict(row), token


def finalize_error(connection, data_dir: Path, row, token, kind="sandbox_error"):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT status,run_id,archive_path FROM arena_entries WHERE id=?",
            (row["id"],)
        ).fetchone()
        if not current or current["status"] != "running" or current["run_id"] != token:
            return False
        db.execute(
            "UPDATE arena_entries SET status='error',archive_path=NULL,"
            "error_class=?,completed_at=?,run_id=NULL WHERE id=?",
            (kind[:60], time.time(), row["id"])
        )
        db.execute(
            "INSERT INTO arena_events(arena_id,kind,summary,created_at) VALUES(?,?,?,?)",
            (row["id"], "error", "Quarantined failed upload discarded", time.time())
        )
    if row.get("archive_path"):
        p = (data_dir / row["archive_path"]).resolve()
        upload_root = (data_dir / "arena" / "uploads").resolve()
        if p.is_relative_to(upload_root):
            p.unlink(missing_ok=True)
    return True


def finalize_match(connection, data_dir: Path, row, token, pgn_bytes, result, score,
                   book_digest):
    # Atomic PGN file write before recording final result. Orphan PGNs can be
    # recovered after a crash; never count a fake PGN-only database row.
    pgn_dir = data_dir / "pgn" / "arena"
    pgn_dir.mkdir(parents=True, exist_ok=True)
    destination = pgn_dir / f"arena-{row['id']}.pgn"
    temp = pgn_dir / f".arena-{row['id']}.pgn.tmp"
    with temp.open("xb") as output:
        output.write(pgn_bytes)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, destination)
    status = "passed" if score["passed"] else "rejected"
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT status,run_id FROM arena_entries WHERE id=?",
            (row["id"],)
        ).fetchone()
        if not current or current["status"] != "running" or current["run_id"] != token:
            raise ArenaRunnerError("Arena lease was revoked")
        db.execute(
            "UPDATE arena_entries SET status=?,wins=?,draws=?,losses=?,score=?,"
            "penta_json=?,pgn_path=?,book_sha256=?,completed_at=?,run_id=NULL,"
            "archive_path=CASE WHEN ?='rejected' THEN NULL ELSE archive_path END "
            "WHERE id=?",
            (status, result.wins, result.draws, result.losses, score["score"],
             json.dumps(result.penta), str(destination.relative_to(data_dir)),
             book_digest, time.time(), status, row["id"])
        )
        summary = (
            f"Score {score['score']}/100 (threshold 55), "
            f"{result.wins}W/{result.draws}D/{result.losses}L"
        )
        db.execute(
            "INSERT INTO arena_events(arena_id,kind,summary,created_at)"
            " VALUES(?,?,?,?)",
            (row["id"], "candidate_ready" if score["passed"] else "discarded",
             summary, time.time())
        )
    if not score["passed"]:
        # The losing executable ZIP is discarded immediately. Its chess
        # results/PGN remain published for reproducibility.
        p = (data_dir / row["archive_path"]).resolve()
        if p.is_relative_to((data_dir / "arena" / "uploads").resolve()):
            p.unlink(missing_ok=True)
    return status


def run_one(connection, data_dir: Path, row, token, image=DOCKER_IMAGE,
            timeout=TIMEOUT_SECONDS):
    work_root = data_dir / "arena" / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    staging = work_root / f"job-{row['id']}-{uuid.uuid4().hex[:8]}"
    staging.mkdir(mode=0o755, parents=False)
    challenger = staging / "challenger"
    results = staging / "results"
    try:
        results.mkdir(mode=0o777)
        results.chmod(0o777)
        reference = Path(os.environ["OPENFISHTEST_ARENA_REFERENCE_DIR"]).resolve()
        book = arena_book_metadata()
        if not book or book["sha256"] != row["book_sha256"]:
            raise ArenaRunnerError("Arena opening book missing or changed")
        checked_reference(reference, row["reference_sha256"])
        upload = (data_dir / row["archive_path"]).resolve()
        if not upload.is_relative_to((data_dir / "arena" / "uploads").resolve()):
            raise ArenaRunnerError("Unsafe arena upload path")
        if sha256_path(upload) != row["archive_sha256"]:
            raise ArenaRunnerError("Archive SHA-256 changed since submission")
        details = extract_quarantined(upload, challenger)
        if details.engine_sha256 != row["engine_sha256"]:
            raise ArenaRunnerError("Quarantined engine digest mismatch")
        challenger.chmod(0o755)
        command = arena_command(
            row["id"], challenger, reference, book["path"], results,
            tc=row["tc"], image=image
        )
        result_path = results / "match.pgn"
        _run_sandbox(command, row["id"], staging / "fastchess.log",
                     result_path, timeout=timeout)
        if result_path.stat().st_size > MAX_PGN_BYTES:
            raise ArenaRunnerError("Arena PGN too large")
        pgn_bytes = result_path.read_bytes()
        parsed = parse_pgn_results(pgn_bytes, GAMES)
        verify_expected_openings(pgn_bytes, book["path"])
        score = classify_score(parsed.wins, parsed.draws, parsed.losses)
        return finalize_match(
            connection, data_dir, row, token, pgn_bytes, parsed, score,
            book["sha256"]
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def cleanup_orphans(connection, data_dir: Path, timeout: int):
    """Fail closed on stale uploads/crashed runner jobs and remove old ZIPs."""
    now = time.time()
    uploads = (data_dir / "arena" / "uploads").resolve()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        stale = [dict(row) for row in db.execute(
            "SELECT * FROM arena_entries WHERE "
            "(status='uploading' AND created_at<?) OR "
            "(status='running' AND started_at<?)",
            (now - 3600, now - timeout - 900)
        )]
        for row in stale:
            db.execute(
                "UPDATE arena_entries SET status='error',archive_path=NULL,"
                "error_class='stale_or_interrupted',run_id=NULL,completed_at=? "
                "WHERE id=?", (now, row["id"])
            )
            db.execute(
                "INSERT INTO arena_events(arena_id,kind,summary,created_at)"
                " VALUES(?,?,?,?)",
                (row["id"], "error", "Expired upload or crashed arena run purged", now)
            )
        # A prior crash between marking a rejection and unlink() must not
        # leave the unqualified executable on disk.
        terminal = [row["id"] for row in db.execute(
            "SELECT id FROM arena_entries WHERE status "
            "IN ('invalid','error','rejected','discarded')"
        )]
    for row in stale:
        terminal.append(row["id"])
    for entry_id in set(terminal):
        for extension in (".zip", ".incoming"):
            (uploads / f"{entry_id}{extension}").unlink(missing_ok=True)
    return len(stale)


def run_loop(connection, data_dir: Path, once=False, poll=20,
             timeout=TIMEOUT_SECONDS):
    setup_arena_schema(connection)
    # Refuse to run if the VM, Docker daemon, book or reference aren't verified.
    require_dedicated_rootless()
    image = os.getenv("OPENFISHTEST_ARENA_IMAGE", DOCKER_IMAGE)
    if not IMAGE_RE.fullmatch(image):
        raise ArenaRunnerError("Invalid trusted arena image")
    if not os.getenv("OPENFISHTEST_ARENA_REFERENCE_DIR"):
        raise ArenaRunnerError("Set the trusted Stockless reference directory")
    if not arena_book_metadata():
        raise ArenaRunnerError("Set a valid 50-opening EPD book")

    cleanup_orphans(connection, data_dir, timeout)
    print("Isolated arena runner started. Never use this on volunteer PCs.")
    while True:
        claimed = claim_next(connection)
        if not claimed:
            if once:
                print("No pending arena submissions.")
                return 0
            time.sleep(poll)
            continue
        row, token = claimed
        print(f"Arena #{row['id']}: 100 games against Stockless "
              f"({row['reference_version']})")
        try:
            result = run_one(connection, data_dir, row, token, image=image,
                             timeout=timeout)
            print(f"Arena #{row['id']} => {result}")
        except Exception as exc:
            print(f"Arena #{row['id']} failed safely: {type(exc).__name__}", file=sys.stderr)
            try:
                finalize_error(connection, data_dir, row, token,
                               "sandbox_or_pgn_validation_failed")
            except Exception:
                print("Failed to persist arena error; operator investigation required",
                      file=sys.stderr)
            if once:
                return 1
        if once:
            return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rootless Linux-only quarantined arena")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    if not 5 <= args.poll <= 300 or not 60 <= args.timeout <= 14400:
        parser.error("poll must be 5-300; timeout must be 60-14400 seconds")
    # Import server *after* env is configured on the isolated runner VM.
    from server import DATA_DIR, connection
    try:
        return run_loop(connection, DATA_DIR, once=args.once, poll=args.poll,
                        timeout=args.timeout)
    except (ArenaRunnerError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"Arena runner stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
