"""Run a trusted local 2-engine Fastchess match, then submit PGN+EPD to GitHub.

No central API, admin token, public IP, VPN or HTTPS backend is required.
The contributor must explicitly select and trust their OWN executable files.
The published files are only PGN + EPD; engine binaries never leave the PC.

This local match mode is distinct from the private HTTPS isolated Arena and
from the old server-issued worker queue. Results are community-unverified.
"""
from __future__ import annotations

import os
import queue
import re
import secrets
import signal
import subprocess
import threading
import time
from pathlib import Path

from arena_books import normalize_book_file, InvalidBook
from community_submission import InvalidCommunitySubmission, validate_pair
from contributor_submit import submit as submit_to_github
from match_protocol import sha256_path


class MatchCancelled(RuntimeError):
    pass


def recommended_concurrency():
    """Two single-thread engines per game; keep room for the user's OS."""
    available = os.cpu_count() or 2
    return max(1, min(8, available // 2))


def probe_local_uci(executable: Path, timeout_seconds=12):
    """Probe only a contributor's explicitly selected, locally trusted binary.

    UCI is user data, not a malware scanner. A background reader avoids
    indefinite blocking on stdout.readline() on Windows.
    """
    if not executable.is_file():
        raise ValueError(f"UCI engine not found: {executable}")
    messages = queue.Queue(maxsize=256)
    proc = subprocess.Popen(
        [str(executable)], cwd=str(executable.parent),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        ),
        **({"start_new_session": True} if os.name != "nt" else {})
    )

    def reader():
        seen = 0
        try:
            for raw in proc.stdout:
                seen += len(raw)
                if seen > 24576:
                    messages.put(("ERROR", "UCI output exceeds 24 KiB"))
                    return
                try:
                    messages.put_nowait(raw.decode("utf-8", "replace").strip())
                except queue.Full:
                    return
        finally:
            try: messages.put_nowait(("EOF", None))
            except queue.Full: pass

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    name, supported = None, set()
    try:
        proc.stdin.write(b"uci\n")
        proc.stdin.flush()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                line = messages.get(timeout=min(0.5, deadline - time.monotonic()))
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            if isinstance(line, tuple):
                raise ValueError("UCI engine terminated or sent invalid output")
            if line.startswith("id name "):
                name = "".join(ch for ch in line[8:80] if ch.isprintable())
            if line.startswith("option name ") and " type " in line:
                option = line.split(" type ", 1)[0][12:].strip().lower()
                supported.add(option)
            if line == "uciok":
                if not name:
                    raise ValueError("Engine did not report its UCI name")
                return {"name": name, "options": supported}
        raise ValueError(f"UCI handshake timed out for {executable.name}")
    finally:
        try:
            if proc.poll() is None:
                proc.stdin.write(b"quit\n")
                proc.stdin.flush()
                proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10, check=False
                )
            else:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: pass


def match_command(fastchess, challenger, stockless, epd, output,
                  tc, games, concurrency, engine_options):
    if games < 2 or games > 200 or games % 2:
        raise ValueError("Even games count required (2-200)")
    if not 1 <= concurrency <= min(16, os.cpu_count() or 1):
        raise ValueError("CPU concurrency must fit the hardware")
    if not re.fullmatch(r"\d{1,5}(?:\+\d+(?:\.\d+)?)?", tc):
        raise ValueError("Unsupported time-control format")
    args = [
        str(fastchess),
        "-engine", f"cmd={challenger}", "name=Challenger",
        f"dir={challenger.parent}",
    ]
    for option in sorted(engine_options["challenger"]):
        if option == "threads":
            args.append("option.Threads=1")
        elif option == "hash":
            args.append("option.Hash=32")
    args += [
        "-engine", f"cmd={stockless}", "name=Stockless",
        f"dir={stockless.parent}"
    ]
    for option in sorted(engine_options["stockless"]):
        if option == "threads":
            args.append("option.Threads=1")
        elif option == "hash":
            args.append("option.Hash=32")
    args += [
        "-each", "proto=uci", f"tc={tc}",
        "-openings", f"file={epd}", "format=epd", "order=sequential", "start=1",
        "-games", "2", "-rounds", str(games // 2), "-repeat",
        "-concurrency", str(concurrency),
        "-ratinginterval", "0", "-autosaveinterval", "0",
        "-pgnout", f"file={output}", "notation=san", "append=false",
        "-event", "OpenFishtest Contributor Match",
    ]
    return args


def _kill_proc(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10, check=False
        )
    else:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired: pass


def play_and_submit(fastchess_path, stockless_path, challenger_path, book_path,
                    concurrency=None, games=100, tc="10+0.1",
                    stop_event=None, progress=print,
                    submit=True, output_dir=None, timeout=14400):
    fastchess = Path(fastchess_path).expanduser().resolve(strict=True)
    stockless = Path(stockless_path).expanduser().resolve(strict=True)
    challenger = Path(challenger_path).expanduser().resolve(strict=True)
    book = Path(book_path).expanduser().resolve(strict=True)
    for path in (fastchess, stockless, challenger, book):
        if not path.is_file():
            raise ValueError(f"File not found: {path}")
    if challenger == stockless:
        raise ValueError("Challenger and Stockless must be different executable paths")
    if concurrency is None:
        concurrency = recommended_concurrency()
    if stop_event is None:
        stop_event = threading.Event()
    output_dir = Path(output_dir) if output_dir else Path.home() / "OpenFishtest-Results"
    output_dir.mkdir(parents=True, exist_ok=True)
    root = output_dir / f"match-{secrets.token_hex(6)}"
    root.mkdir(mode=0o700)
    log_path, pgn, epd = (
        root / "fastchess.log", root / "games.pgn", root / "openings.epd"
    )
    progress("Checking locally selected UCI engines (not uploaded to GitHub)...")
    opt_challenger = probe_local_uci(challenger)
    opt_stockless = probe_local_uci(stockless)
    progress(
        f"Challenger: {opt_challenger['name']} | Stockless: {opt_stockless['name']}"
    )
    progress("Converting the opening book to legal EPD positions...")
    normalized = normalize_book_file(book, book.name)
    if normalized.positions < games // 2:
        raise InvalidBook("The opening book does not cover all requested opening pairs")
    epd.write_bytes(normalized.content)
    progress(
        f"Book: {normalized.positions} distinct openings, "
        f"SHA-256 {normalized.digest[:12]}…"
    )
    progress(
        f"Starting real Fastchess: {games} games, "
        f"{concurrency} concurrent games (~{concurrency * 2} engine threads)."
    )
    cmd = match_command(
        fastchess, challenger, stockless, epd, pgn, tc,
        games, concurrency, {
            "challenger": opt_challenger["options"],
            "stockless": opt_stockless["options"]
        }
    )
    creation = (
        {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS
         | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt" else {"start_new_session": True}
    )
    proc = None
    try:
        with log_path.open("wb") as output:
            proc = subprocess.Popen(
                cmd, cwd=str(root), stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT,
                shell=False, **creation
            )
            start = time.monotonic()
            while proc.poll() is None:
                if stop_event.is_set():
                    raise MatchCancelled("Contributor stopped CPU donation")
                if time.monotonic() - start > timeout:
                    raise TimeoutError("Fastchess match exceeded time limit")
                if log_path.stat().st_size > 2_000_000:
                    raise RuntimeError("Fastchess log exceeded 2MB")
                try: proc.wait(timeout=1)
                except subprocess.TimeoutExpired: pass
        if proc.returncode:
            raise RuntimeError(
                f"Fastchess exited with {proc.returncode}; see {log_path}"
            )
        if not pgn.is_file():
            raise RuntimeError("Fastchess produced no PGN file")
        result = validate_pair(pgn.read_bytes(), epd.read_bytes())
        progress(
            f"Real local match finished: {result.wins}W "
            f"{result.draws}D {result.losses}L | "
            f"{result.wins + result.draws/2}/{result.games} points."
        )
        if not submit:
            return {"pgn": str(pgn), "epd": str(epd),
                    "games": result.games, "submitted": False}
        if stop_event.is_set():
            raise MatchCancelled("User stopped before GitHub submission")
        progress("Automatically uploading PGN and EPD via your GitHub account...")
        url = submit_to_github(pgn, epd, progress=progress)
        return {"pgn": str(pgn), "epd": str(epd),
                "games": result.games, "submitted": True, "pull_request": url}
    finally:
        if proc is not None and proc.poll() is None:
            _kill_proc(proc)
        progress(f"Local PGN / EPD and log are kept at: {root}")
