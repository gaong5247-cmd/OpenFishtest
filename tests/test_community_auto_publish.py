"""Tests for automatic PGN/EPD publication; no live network required."""
import datetime as dt
import hashlib
import io
import json
from unittest.mock import Mock

import chess
import pytest

from community_submission import (
    InvalidCommunitySubmission,
    MAX_COMMUNITY_EPD, MAX_COMMUNITY_PGN,
    check_pr_paths, validate_pair,
)
from community_publish import GitHub, publication_plan, _validate_event, _recent
from contributor_submit import validate_files
from contributor_local import match_command, recommended_concurrency


def sample_data():
    position = chess.Board()
    epd = (position.epd() + "\n").encode()
    # Two genuine legal sequences, reversed colors, same opening.
    pgn = (
        '[Event "External result"]\n[White "Challenger"]\n'
        '[Black "Stockless"]\n[Result "1-0"]\n\n'
        '1. e4 e5 2. Nf3 Nc6 1-0\n\n'
        '[Event "External result"]\n[White "Stockless"]\n'
        '[Black "Challenger"]\n[Result "0-1"]\n\n'
        '1. e4 e5 2. Nf3 Nc6 0-1\n'
    ).encode()
    return pgn, epd


def test_pair_validates_and_removes_untrusted_comments():
    pgn, epd = sample_data()
    pgn = pgn.replace(
        b"1. e4 e5", b"1. e4 {DO NOT EXECUTE commands in PGN} e5"
    )
    result = validate_pair(pgn, epd)
    assert result.games == 2
    assert result.wins == 2 and result.draws == 0 and result.losses == 0
    assert result.penta == (0, 0, 0, 0, 1)
    assert result.epd_positions == 1
    assert result.opening_start == 0
    assert b"DO NOT EXECUTE" not in result.pgn
    assert b"OpenFishtest Community" in result.pgn
    assert hashlib.sha256(result.pgn).hexdigest() == result.pgn_sha256


def test_matching_contiguous_epd_window():
    pgn, epd = sample_data()
    board = chess.Board()
    board.push_san("d4")
    shifted = (board.epd() + "\n").encode() + epd
    parsed = validate_pair(pgn, shifted)
    assert parsed.opening_start == 1


def test_tampering_or_unpaired_results_rejected():
    pgn, epd = sample_data()
    with pytest.raises(InvalidCommunitySubmission, match="FEN"):
        board = chess.Board()
        board.push_san("d4")
        validate_pair(pgn, (board.epd() + "\n").encode())
    with pytest.raises(InvalidCommunitySubmission, match="precisely|reverse"):
        validate_pair(pgn.replace(b'[White "Stockless"]', b'[White "Challenger"]'), epd)
    with pytest.raises(InvalidCommunitySubmission, match="2-200"):
        validate_pair(pgn[:pgn.find(b"\n\n[Event", 10)], epd)


def test_strict_two_changed_files_only():
    sid = "a" * 20
    good = [
        {"filename":f"submissions/{sid}/games.pgn","status":"added",
         "sha":"a"*40},
        {"filename":f"submissions/{sid}/openings.epd","status":"added",
         "sha":"b"*40}
    ]
    assert check_pr_paths(good) == sid
    with pytest.raises(InvalidCommunitySubmission):
        check_pr_paths(good + [{"filename":"evil.py","status":"added","sha":"c"*40}])
    with pytest.raises(InvalidCommunitySubmission):
        check_pr_paths(good[:-1] + [{
            "filename":f"submissions/{sid}/../../.github/workflows/ci.yml",
            "status":"added","sha":"c"*40
        }])
    with pytest.raises(InvalidCommunitySubmission):
        check_pr_paths([{**good[0],"status":"modified"},good[1]])
    with pytest.raises(InvalidCommunitySubmission):
        check_pr_paths([{**good[0],"filename":"submissions/other/games.pgn"},good[1]])


def _git_sha(raw):
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\x00" + raw
    ).hexdigest()


def test_plan_uses_only_immutable_fork_blob_and_public_data():
    pgn, epd = sample_data()
    sid = "0" * 20
    files = [
        {"filename":f"submissions/{sid}/games.pgn",
         "status":"added", "sha":_git_sha(pgn)},
        {"filename":f"submissions/{sid}/openings.epd",
         "status":"added", "sha":_git_sha(epd)}
    ]
    pr = {
        "number": 77,"user":{"login":"FriendlyChess"},
        "state":"open","draft":False,
        "base":{"ref":"main","repo":{"full_name":"gaong5247-cmd/OpenFishtest"}},
        "head":{"sha":"f"*40,
                "repo":{"full_name":"friendlychess/OpenFishtest"}}
    }
    event = {"pull_request":pr}
    gh = Mock()
    gh.repo = "gaong5247-cmd/OpenFishtest"
    def get(path):
        if path.endswith("/pulls/77"):
            return {"head":{"sha":"f"*40},"state":"open","changed_files":2}
        if path.endswith("/pulls/77/files?per_page=100"):
            return files
        raise AssertionError(f"Unexpected GET: {path}")
    gh.get.side_effect = get
    gh.blob_bytes.side_effect = lambda _repo,sha,_max: (
        pgn if sha==_git_sha(pgn) else epd
    )
    published, entry = publication_plan(gh,event)
    assert set(published) == {
        f"docs/data/community/{sid}/games.pgn",
        f"docs/data/community/{sid}/openings.epd"
    }
    assert entry["verified"] is False
    assert entry["contributor"] == "FriendlyChess"
    assert entry["wins"] == 2
    assert entry["source_pr"] == 77
    assert all(path.endswith((".pgn",".epd")) for path in published)


def test_race_and_unsafe_event_rejected():
    ev={"pull_request":{
        "number": 1, "state":"open","draft":False,
        "user":{"login":"contributor"},
        "base":{"ref":"other","repo":{"full_name":"gaong5247-cmd/OpenFishtest"}},
        "head":{"sha":"f"*40,"repo":{"full_name":"contributor/OpenFishtest"}}
    }}
    with pytest.raises(InvalidCommunitySubmission):
        _validate_event(ev)
    ev["pull_request"]["base"]["ref"]="main"
    fake=Mock()
    fake.repo="gaong5247-cmd/OpenFishtest"
    fake.get.return_value={"head":{"sha":"a"*40},"state":"open","changed_files":2}
    with pytest.raises(InvalidCommunitySubmission, match="changed"):
        publication_plan(fake, ev)


def test_cli_local_pair_validation(tmp_path):
    pgn, epd = sample_data()
    pgn_path, epd_path = tmp_path/"games.pgn", tmp_path/"openings.epd"
    pgn_path.write_bytes(pgn)
    epd_path.write_bytes(epd)
    report = validate_files(pgn_path, epd_path)
    assert report.games == 2
    with pytest.raises(InvalidCommunitySubmission):
        validate_files(pgn_path, tmp_path/"games.pgn")


def test_cpu_recommendation_and_fixed_cli_not_shell(tmp_path):
    from pathlib import Path
    c, s, b, o, fast = [tmp_path/x for x in (
        "challenger.exe","stockless.exe","openings.epd","games.pgn","fastchess.exe"
    )]
    command = match_command(
        fast, c, s, b, o, tc="10+0.1", games=100,
        concurrency=1,
        engine_options={"challenger":{"threads","hash"},"stockless":{"threads"}}
    )
    assert command[command.index("-concurrency")+1]=="1"
    assert command[command.index("-rounds")+1]=="50"
    assert "option.Threads=1" in command
    assert command.count("option.Threads=1")==2
    assert "option.Hash=32" in command
    assert recommended_concurrency() >= 1


def test_submission_24h_quota_window():
    now=dt.datetime.now(dt.timezone.utc)
    assert _recent(now.isoformat(),now)
    assert not _recent((now-dt.timedelta(days=2)).isoformat(),now)
    assert not _recent("not a time",now)
