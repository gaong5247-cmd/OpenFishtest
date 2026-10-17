"""Run approved local UCI engines through Fastchess and report PGN to server.

Worker only executes programs explicitly configured by its operator, after
matching their SHA-256 with administrator-approved engine identities.
Never download or execute a command supplied by the server.
"""
import argparse
import base64
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from match_protocol import MAX_PGN_BYTES, parse_pgn_results, sha256_path

HEARTBEAT_INTERVAL = 30


def server_url(url: str) -> str:
    url = url.rstrip("/")
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Server URL must be an origin without credentials or query")
    if parsed.path not in ("", "/"):
        raise ValueError("Server URL must not contain a path")
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return url
    raise ValueError("Use HTTPS for remote servers; plain HTTP is permitted on localhost only")


def request_json(base_url, token, endpoint, payload):
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    req = Request(
        base_url + endpoint, data=encoded, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Worker-Token": token,
            "User-Agent": "OpenFishtest-Worker/0.2"
        }
    )
    with urlopen(req, timeout=20) as response:
        if response.status == 204:
            return None
        return json.loads(response.read(65536).decode("utf-8"))


def load_settings(config_file: Path):
    base = config_file.parent.resolve()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuration must be an object")
    if not isinstance(data.get("engines"), dict):
        raise ValueError("engines must map exact SHA-256 digests to local paths")
    if not isinstance(data.get("books", {}), dict):
        raise ValueError("books must map SHA-256 digests to local paths")
    data["_base"] = base
    concurrency = int(data.get("concurrency", 1))
    if not 1 <= concurrency <= 8:
        raise ValueError("concurrency must be between 1 and 8")
    data["concurrency"] = concurrency
    return data


def checked_file(config, mapping, digest):
    location = mapping.get(digest)
    if not isinstance(location, str) or not location:
        raise ValueError(f"No local file mapped to SHA-256 {digest}")
    path = Path(location).expanduser()
    if not path.is_absolute():
        path = config["_base"] / path
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"Not a regular file: {path}")
    if sha256_path(path) != digest:
        raise ValueError(f"SHA-256 mismatch: {path}")
    return path


def command_for_job(job, config, output):
    """Build a safe argv list (shell=False) for color-reversed games."""
    games = int(job["games"])
    if games < 2 or games % 2 or games > 20:
        raise ValueError("Job games must be paired and at most 20")
    challenger = job["challenger"]
    reference = job["reference"]
    if reference["name"].casefold() != "stockless":
        raise ValueError("Worker refuses non-Stockless reference")

    engines = {str(k).lower(): v for k, v in config["engines"].items()}
    challenger_exe = checked_file(config, engines, challenger["sha256"].lower())
    stockless_exe = checked_file(config, engines, reference["sha256"].lower())
    fastchess = Path(config["fastchess"]).expanduser()
    if not fastchess.is_absolute():
        fastchess = config["_base"] / fastchess
    fastchess = fastchess.resolve(strict=True)
    if not fastchess.is_file():
        raise ValueError("Configured Fastchess executable is not a file")

    args = [
        str(fastchess),
        "-engine", f"cmd={challenger_exe}", "name=Challenger", f"dir={challenger_exe.parent}",
        "-engine", f"cmd={stockless_exe}", "name=Stockless", f"dir={stockless_exe.parent}",
        "-each", "proto=uci", f"tc={job['tc']}",
        "-games", "2", "-rounds", str(games // 2), "-repeat",
        "-concurrency", str(config["concurrency"]),
        "-ratinginterval", "0", "-autosaveinterval", "0",
        "-pgnout", f"file={output}", "notation=san", "append=false",
        "-event", "OpenFishtest",
    ]
    book_digest = job.get("book_sha256")
    if book_digest:
        books = {str(k).lower(): v for k, v in config.get("books", {}).items()}
        book = checked_file(config, books, book_digest.lower())
        format_name = job.get("book_format", "epd")
        if format_name not in ("epd", "pgn"):
            raise ValueError("Unsupported opening format")
        args.extend([
            "-openings", f"file={book}", f"format={format_name}",
            "order=sequential", f"start={1 + int(job['start_game']) // 2}"
        ])
    return args


def terminate_match(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def heartbeat_loop(stop, lost_lease, base_url, token, job):
    while not stop.wait(HEARTBEAT_INTERVAL):
        try:
            request_json(base_url, token,
                         f"/api/worker/jobs/{job['job_id']}/heartbeat",
                         {"lease_id": job["lease_id"]})
        except HTTPError as exc:
            if exc.code in (401, 403, 404, 409):
                print("Worker lease revoked; stopping match.", file=sys.stderr)
                lost_lease.set()
                return
            print(f"Heartbeat HTTP {exc.code}; will retry", file=sys.stderr)
        except (URLError, TimeoutError, OSError) as exc:
            print(f"Heartbeat temporarily unavailable: {exc}", file=sys.stderr)


def run_match(job, config, token, base_url, max_seconds, work_dir):
    work_dir.mkdir(parents=True, exist_ok=True)
    basename = f"test-{job['test_id']}-job-{job['job_id']}-{job['lease_id'][:10]}"
    pgn = work_dir / (basename + ".pgn")
    log = work_dir / (basename + ".log")
    command = command_for_job(job, config, pgn)
    print(f"Running job #{job['job_id']}: {job['games']} games, "
          f"{job['challenger']['name']} vs Stockless")
    if not job.get("book_sha256"):
        print("WARNING: no opening book configured; all games begin from start position.")
    stop = threading.Event()
    lost_lease = threading.Event()
    thread = threading.Thread(target=heartbeat_loop,
                              args=(stop, lost_lease, base_url, token, job),
                              daemon=True)
    completed = False
    process = None
    try:
        with log.open("wb") as output:
            options = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt" else {"start_new_session": True}
            )
            process = subprocess.Popen(
                command, cwd=str(config["_base"]), stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT,
                shell=False, **options
            )
            thread.start()
            deadline = time.monotonic() + max_seconds
            while process.poll() is None:
                if lost_lease.is_set():
                    raise RuntimeError("Lease lost during match")
                if log.stat().st_size > 2_000_000:
                    raise RuntimeError("Fastchess log exceeded 2 MB")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"Fastchess exceeded {max_seconds}s timeout")
                try:
                    process.wait(timeout=min(5, remaining))
                except subprocess.TimeoutExpired:
                    continue
            if lost_lease.is_set():
                raise RuntimeError("Lease lost during match")
            if process.returncode != 0:
                raise RuntimeError(f"Fastchess returned exit code {process.returncode}")
            if not pgn.exists():
                raise RuntimeError("Fastchess did not write a PGN")
            raw = pgn.read_bytes()
            # Verify expected results *locally* before upload.
            counts = parse_pgn_results(raw, int(job["games"]))
            if len(raw) > MAX_PGN_BYTES:
                raise RuntimeError("Output PGN exceeds 2 MB")
            digest = hashlib.sha256(raw).hexdigest()
            request_json(
                base_url, token, f"/api/worker/jobs/{job['job_id']}/finish",
                {
                    "lease_id": job["lease_id"],
                    "pgn_sha256": digest,
                    "pgn_base64": base64.b64encode(raw).decode("ascii")
                }
            )
            completed = True
            print(f"Accepted job #{job['job_id']}: "
                  f"{counts.wins}W {counts.draws}D {counts.losses}L")
            # Local copy is not needed after the server safely receives the PGN.
            pgn.unlink(missing_ok=True)
            log.unlink(missing_ok=True)
            return True
    except Exception as exc:
        print(f"Job #{job['job_id']} failed: {exc}", file=sys.stderr)
        # Preserve local PGN and log for manual recovery.
        try:
            request_json(
                base_url, token, f"/api/worker/jobs/{job['job_id']}/failed",
                {"lease_id": job["lease_id"], "reason": str(exc)[:500]}
            )
        except Exception as report_error:
            print(f"Could not report failure: {report_error}", file=sys.stderr)
        return False
    finally:
        if process is not None and process.poll() is None:
            terminate_match(process)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        stop.set()
        if thread.is_alive():
            thread.join(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description="OpenFishtest trusted Fastchess worker")
    parser.add_argument("--config", default="worker-config.json")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--once", action="store_true", help="Claim at most one job")
    parser.add_argument("--poll", type=int, default=15, help="Idle polling interval (seconds)")
    parser.add_argument("--max-seconds", type=int, default=3600, help="Time limit per batch")
    parser.add_argument("--worker-id", default=platform.node()[:40] or "local-worker")
    args = parser.parse_args(argv)
    if not (1 <= args.poll <= 3600 and 10 <= args.max_seconds <= 172800):
        parser.error("Invalid polling interval or max-seconds")
    if not 1 <= len(args.worker_id) <= 40 or not all(
        c.isascii() and (c.isalnum() or c in "_-") for c in args.worker_id
    ):
        parser.error("Worker ID must have 1-40 ASCII letters, numbers, underscores or dashes")

    try:
        base_url = server_url(args.server)
        token = os.getenv("OPENFISHTEST_WORKER_TOKEN")
        if not token:
            parser.error("Set OPENFISHTEST_WORKER_TOKEN (not the admin token)")
        config_path = Path(args.config).expanduser().resolve(strict=True)
        config = load_settings(config_path)
        work_dir = config_path.parent / "worker-results"
        while True:
            job = request_json(
                base_url, token, "/api/worker/claim",
                {"worker_id": args.worker_id}
            )
            if job is None:
                if args.once:
                    print("No pending jobs.")
                    return 0
                time.sleep(args.poll)
                continue
            success = run_match(job, config, token, base_url, args.max_seconds, work_dir)
            if args.once:
                return 0 if success else 1
    except KeyboardInterrupt:
        print("\nWorker stopped by operator.")
        return 130
    except (ValueError, FileNotFoundError, URLError, HTTPError) as exc:
        print(f"Worker error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
