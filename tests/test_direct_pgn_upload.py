"""Owner direct PGN/EPD publication tests; never performs live GitHub requests."""
import hashlib
from unittest.mock import MagicMock, patch

import chess
import pytest

from community_submission import InvalidCommunitySubmission, validate_pair
from community_direct_upload import (
    plan_upload, publish_staged,
)
from community_direct_stage import stage_owner_upload


REPO = "gaong5247-cmd/OpenFishtest"
SID = "a" * 24
HEAD = "b" * 40
PARENT = "c" * 40
ACTOR = "gaong5247-cmd"


def sample_pair():
    pgn = (
        '[Event "Local Fastchess"]\n'
        '[White "Challenger"]\n[Black "Stockless"]\n'
        '[Result "1-0"]\n\n1. e4 e5 1-0\n\n'
        '[Event "Local Fastchess"]\n'
        '[White "Stockless"]\n[Black "Challenger"]\n'
        '[Result "0-1"]\n\n1. e4 e5 0-1\n'
    ).encode()
    epd = (chess.Board().epd() + "\n").encode()
    return pgn, epd


def git_sha(content):
    return hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\x00" + content
    ).hexdigest()


def event():
    return {
        "ref":"refs/heads/community-upload/" + SID,
        "after":HEAD,
        "created":True,
    }


def fake_source():
    pgn, epd = sample_pair()
    rows = [
        {"filename":f"submissions/{SID}/games.pgn",
         "status":"added","sha":git_sha(pgn)},
        {"filename":f"submissions/{SID}/openings.epd",
         "status":"added","sha":git_sha(epd)}
    ]
    gh = MagicMock()
    gh.get.side_effect = lambda path: {
        f"repos/{REPO}/git/ref/heads/community-upload/{SID}":
            {"object":{"sha":HEAD}},
        f"repos/{REPO}/git/commits/{HEAD}":
            {"parents":[{"sha":PARENT}]},
        f"repos/{REPO}/compare/{PARENT}...{HEAD}":
            {"status":"ahead","ahead_by":1,
             "total_commits":1,"files":rows}
    }[path]
    gh.blob_bytes.side_effect = lambda repo, sha, size: (
        pgn if sha == git_sha(pgn) else epd
    )
    return gh, rows


def test_data_only_commit_canonicalized_no_pr_required():
    gh, rows = fake_source()
    files, entry = plan_upload(gh, event(), actor=ACTOR, repository=REPO)
    assert set(files) == {
        f"docs/data/community/{SID}/games.pgn",
        f"docs/data/community/{SID}/openings.epd"
    }
    assert entry["id"] == SID
    assert entry["source"] == "owner_website_direct_upload"
    assert "source_pr" not in entry
    assert entry["verified"] is False
    assert entry["games"] == 2
    assert entry["points"] == 2
    assert entry["contributor"] == ACTOR
    assert b"Local Fastchess" not in files[
        f"docs/data/community/{SID}/games.pgn"
    ]
    assert all(".github/workflows/" not in name for name in files)


def test_reject_other_actor_unrelated_file_and_changed_branch():
    gh, rows = fake_source()
    with pytest.raises(InvalidCommunitySubmission, match="owner"):
        plan_upload(gh, event(), actor="untrusted-bot", repository=REPO)
    with pytest.raises(InvalidCommunitySubmission, match="Not an owner upload"):
        plan_upload(
            gh,
            {"ref":"refs/heads/feat/evil","after":HEAD},
            actor=ACTOR, repository=REPO
        )
    gh.get.side_effect = lambda path: (
        {"object":{"sha":"f"*40}}
        if "/git/ref/heads/" in path else {}
    )
    with pytest.raises(InvalidCommunitySubmission, match="replaced"):
        plan_upload(gh, event(), actor=ACTOR, repository=REPO)
    gh, rows = fake_source()
    rows.append({
        "filename":".github/workflows/evil.yml",
        "status":"added", "sha":"f"*40
    })
    with pytest.raises(InvalidCommunitySubmission, match="Only PGN"):
        plan_upload(gh, event(), actor=ACTOR, repository=REPO)


def test_publish_new_bypasses_pr_quotas_without_new_pr():
    gh, _ = fake_source()
    gh.index_for_main.return_value = {"version":1,"entries":[]}
    result = publish_staged(gh, event(), ACTOR, REPO)
    assert result == SID
    args, kwargs = gh.commit_publication.call_args
    assert kwargs["trusted_owner_upload"] is True
    assert args[1]["verified"] is False
    gh.deploy_pages.assert_called_once()
    gh.api.assert_called_once_with(
        "DELETE", f"repos/{REPO}/git/refs/heads/community-upload/{SID}"
    )
    assert not gh.post.called
    assert not gh.patch.called


def test_idempotent_retry_deploys_again_without_republishing():
    gh, _ = fake_source()
    _, entry = plan_upload(gh, event(), actor=ACTOR, repository=REPO)
    gh.index_for_main.return_value = {"entries":[{
        "id":SID,
        "pgn_sha256":entry["pgn_sha256"],
        "epd_sha256":entry["epd_sha256"],
    }]}
    result = publish_staged(gh, event(), ACTOR, REPO)
    assert result == SID
    gh.commit_publication.assert_not_called()
    gh.deploy_pages.assert_called_once()


def test_duplicate_canonical_pgn_does_not_double_count():
    gh, _ = fake_source()
    _, entry = plan_upload(gh, event(), actor=ACTOR, repository=REPO)
    gh.index_for_main.return_value = {"entries":[{
        "id":"d"*24,
        "pgn_sha256":entry["pgn_sha256"],
        "epd_sha256":entry["epd_sha256"],
    }]}
    assert publish_staged(gh, event(), ACTOR, REPO) == "d"*24
    gh.commit_publication.assert_not_called()
    gh.deploy_pages.assert_called_once()


def test_local_owner_stages_two_data_blobs_using_gh_token_not_pr():
    pgn, epd = sample_pair()
    fake = MagicMock()
    fake.get.return_value = {"login":ACTOR}
    fake.current_head.return_value = ("f"*40, "e"*40)
    fake.write_blob.side_effect = ["a"*40,"b"*40]
    def post(path,payload):
        if path.endswith("/git/trees"): return {"sha":"c"*40}
        if path.endswith("/git/commits"): return {"sha":"d"*40}
        if path.endswith("/git/refs"): return {}
        raise AssertionError(path)
    fake.post.side_effect = post
    with patch("community_direct_stage.GitHub", return_value=fake), \
         patch("community_direct_stage.secrets.token_hex", return_value=SID):
        result = stage_owner_upload("github-token-kept-in-memory-only",
            pgn,epd,uploader=ACTOR,progress=lambda _:None)
    assert result["id"] == SID
    assert result["status"] == "queued_for_verification"
    assert "/pull/" not in result["actions_url"]
    assert fake.write_blob.call_count == 2
    tree = fake.post.call_args_list[0].args[1]
    assert {v["path"] for v in tree["tree"]} == {
        f"submissions/{SID}/games.pgn",
        f"submissions/{SID}/openings.epd"
    }
    assert fake.post.call_args_list[2].args[1]["ref"] == (
        f"refs/heads/community-upload/{SID}"
    )


def test_reject_local_non_owner_before_any_network_call():
    pgn, epd = sample_pair()
    with patch("community_direct_stage.GitHub") as server:
        with pytest.raises(PermissionError):
            stage_owner_upload("opaque-secret", pgn, epd, uploader="not-owner")
        server.assert_not_called()
