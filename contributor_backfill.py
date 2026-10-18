"""Backfill existing OpenFishtest-Results/match-* PGN+EPD via GitHub PRs.

Safety/operational behavior:
- Dry-run by default: inspect and validate without uploading.
- --submit explicitly opts in to GitHub PR creation.
- Never rerun engines or delete local PGNs.
- One PR per valid match; GitHub auto-publisher quota is 3 accepted PRs per
  contributor per rolling 24 hours, so default --limit=3.
- Local JSON ledger records PR links; public index SHA-256 dedupes already
  published canonical PGNs. Pending local PRs are not resubmitted.
- No GitHub admin/worker token required; gh auth login is user-scoped.
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from community_submission import InvalidCommunitySubmission
from contributor_submit import SubmissionError, submit, validate_files

DEFAULT_RESULTS = Path.home() / "OpenFishtest-Results"
LEDGER_NAME = ".community-submissions.json"
PUBLIC_INDEX = (
    "https://gaong5247-cmd.github.io/OpenFishtest/"
    "data/community/index.json"
)


def _load_ledger(path):
    if not path.exists():
        return {"version": 1, "records": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
        raise ValueError("Invalid local submission ledger")
    return data


def _write_ledger(path, ledger):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as writer:
        json.dump(ledger, writer, ensure_ascii=False, indent=2)
        writer.write("\n")
        writer.flush()
    tmp.replace(path)


def _remote_pgn_digests():
    try:
        request = Request(
            PUBLIC_INDEX, headers={"User-Agent": "OpenFishtest-Backfill/1.0"}
        )
        with urlopen(request, timeout=12) as response:
            if int(response.headers.get("Content-Length", "0")) > 2_000_000:
                raise ValueError("Public index exceeds maximum size")
            payload = response.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError("Public index exceeds maximum size")
        data = json.loads(payload)
        return {
            row["pgn_sha256"]
            for row in data.get("entries", [])
            if isinstance(row, dict) and isinstance(row.get("pgn_sha256"), str)
        }
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
        print(f"Warning: public index unavailable ({exc}); local ledger only.")
        return set()


def scan_results(root, ledger=None, published_digests=None):
    ledger = ledger or {"records": {}}
    published_digests = published_digests or set()
    records = ledger.get("records", {})
    seen = set(published_digests)
    # Count locally submitted PRs as already-seen, including ones still in
    # the GitHub Actions queue, even if the public index has not refreshed.
    seen.update(
        record.get("pgn_sha256")
        for record in records.values()
        if record.get("status") == "submitted"
    )
    results = []
    for folder in sorted(root.glob("match-*"), key=lambda p: p.name):
        if not folder.is_dir():
            continue
        pgn, epd = folder / "games.pgn", folder / "openings.epd"
        item = {"folder": str(folder), "pgn": str(pgn), "epd": str(epd)}
        if not pgn.is_file() or not epd.is_file():
            item.update(status="missing", reason="games.pgn or openings.epd missing")
            results.append(item)
            continue
        try:
            report = validate_files(pgn, epd)
            digest = report.pgn_sha256
            item.update(
                pgn_sha256=digest, games=report.games,
                wins=report.wins, draws=report.draws, losses=report.losses,
                score=report.wins + report.draws / 2,
            )
            if digest in seen:
                item.update(status="duplicate", reason="Already submitted or published")
            else:
                item["status"] = "ready"
                seen.add(digest)
        except (InvalidCommunitySubmission, ValueError, OSError) as exc:
            item.update(status="invalid", reason=str(exc)[:250])
        results.append(item)
    return results


def run_backfill(root, submit_now=False, limit=3, skip_remote=False):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Results directory not found: {root}")
    ledger_path = root / LEDGER_NAME
    ledger = _load_ledger(ledger_path)
    published = set() if skip_remote else _remote_pgn_digests()
    rows = scan_results(root, ledger, published)
    counts = {}
    for item in rows:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        folder = Path(item["folder"]).name
        if item["status"] == "ready":
            print(f"[READY] {folder}: {item['games']} games, "
                  f"{item['wins']}W/{item['draws']}D/{item['losses']}L")
        else:
            print(f"[{item['status'].upper()}] {folder}: "
                  f"{item.get('reason', '')}")
    print("Summary:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    if not submit_now:
        print("DRY RUN only. To submit up to 3 validated matches, add --submit.")
        return rows

    if not 1 <= limit <= 3:
        raise ValueError("Automatic publisher permits up to 3 accepted submissions per 24h")
    successes = 0
    for item in rows:
        if item["status"] != "ready" or successes >= limit:
            continue
        folder = str(Path(item["folder"]).resolve())
        try:
            url = submit(item["pgn"], item["epd"])
            ledger["records"][folder] = {
                "status": "submitted", "pgn_sha256": item["pgn_sha256"],
                "pull_request": url,
                "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "games": item["games"],
            }
            _write_ledger(ledger_path, ledger)
            print(f"[SUBMITTED] {Path(folder).name} -> {url}")
            successes += 1
        except (SubmissionError, InvalidCommunitySubmission, OSError) as exc:
            print(f"[FAILED] {Path(folder).name}: {exc}", file=sys.stderr)
            print("Stopping batch to avoid repeated failing PR attempts.")
            break
    print(f"Created {successes} new PR(s). Local PGNs/EPDs were not modified.")
    print(f"Submission history: {ledger_path}")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scan old local PGN results and optionally resubmit via GitHub"
    )
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--submit", action="store_true",
                        help="Actually create PRs (dry-run is the default)")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--skip-remote", action="store_true",
                        help="Skip public GitHub Pages index lookup")
    args = parser.parse_args(argv)
    try:
        run_backfill(args.results, args.submit, args.limit, args.skip_remote)
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Backfill error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
