"""Bulk PGN backfill dry-run, dedup, submission ledger and quota tests."""
import datetime as dt
import json
from unittest.mock import patch

import chess

from contributor_backfill import scan_results, run_backfill


def make_match(root, name, result="1/2-1/2"):
    folder = root / name
    folder.mkdir()
    board = chess.Board()
    epd = board.epd() + "\n"
    (folder / "openings.epd").write_text(epd, encoding="utf-8")
    games = []
    for white, black in [("Challenger", "Stockless"), ("Stockless", "Challenger")]:
        games.append(
            f'[Event "Test"]\n[White "{white}"]\n[Black "{black}"]\n'
            f'[Result "{result}"]\n\n1. e4 e5 {result}\n\n'
        )
    (folder / "games.pgn").write_text("".join(games), encoding="utf-8")
    return folder


def test_dry_run_never_submits_and_detects_duplicate(tmp_path):
    make_match(tmp_path, "match-001")
    make_match(tmp_path, "match-002")
    (tmp_path / "match-broken").mkdir()
    with patch("contributor_backfill.submit") as mocked:
        rows = run_backfill(tmp_path, submit_now=False, skip_remote=True)
    assert mocked.call_count == 0
    assert [r["status"] for r in rows] == ["ready", "duplicate", "missing"]
    assert not (tmp_path / ".community-submissions.json").exists()


def test_submits_and_persists_ledger_then_skips_duplicate(tmp_path):
    make_match(tmp_path, "match-001")
    with patch("contributor_backfill.submit",
               return_value="https://github.com/gaong5247-cmd/OpenFishtest/pull/123") as mocked:
        run_backfill(tmp_path, submit_now=True, skip_remote=True)
        run_backfill(tmp_path, submit_now=True, skip_remote=True)
    assert mocked.call_count == 1
    ledger = json.loads((tmp_path / ".community-submissions.json").read_text())
    assert len(ledger["records"]) == 1
    assert next(iter(ledger["records"].values()))["status"] == "submitted"


def test_rolling_daily_quota_blocks_new_pr(tmp_path):
    make_match(tmp_path, "match-001")
    ledger = {
        "version": 1,
        "records": {
            f"old-{n}": {
                "status": "submitted",
                "pgn_sha256": str(n),
                "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat()
            } for n in range(3)
        }
    }
    (tmp_path / ".community-submissions.json").write_text(json.dumps(ledger))
    with patch("contributor_backfill.submit") as mocked:
        run_backfill(tmp_path, submit_now=True, skip_remote=True)
    mocked.assert_not_called()


def test_remote_index_dedupe(tmp_path):
    make_match(tmp_path, "match-001")
    row = scan_results(tmp_path)[0]
    result = scan_results(tmp_path, published_digests={row["pgn_sha256"]})
    assert result[0]["status"] == "duplicate"
