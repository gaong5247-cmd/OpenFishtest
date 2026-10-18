"""Local uploader integration tests, without any external GitHub traffic."""
import base64
import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch

import chess
import pytest

from local_upload_server import (
    LocalUploadHTTPServer, LocalUploadHandler, github_login, submit_bytes,
    MAX_COMMUNITY_PGN, MAX_COMMUNITY_EPD
)


def paired_pgn_epd():
    pgn = (
        '[Event "Local"]\n[White "Challenger"]\n[Black "Stockless"]\n'
        '[Result "1-0"]\n\n1. e4 e5 1-0\n\n'
        '[Event "Local"]\n[White "Stockless"]\n[Black "Challenger"]\n'
        '[Result "0-1"]\n\n1. e4 e5 0-1\n'
    ).encode("utf-8")
    return pgn, (chess.Board().epd() + "\n").encode("utf-8")


def test_owner_uses_same_publication_pipeline_without_pr():
    pgn, epd = paired_pgn_epd()
    with patch("local_upload_server.stage_owner_upload") as stage, \
         patch("local_upload_server.github_token", return_value="private-gh-token"):
        stage.return_value = {
            "id": "a" * 24,
            "actions_url": "https://github.com/gaong5247-cmd/OpenFishtest/actions",
        }
        result = submit_bytes(pgn, epd, username="gaong5247-cmd")
    assert result["role"] == "owner"
    assert result["method"] == "direct"
    assert result["status"] == "queued_for_actions"
    assert result["games"] == 2
    assert result["points"] == 2
    assert "pull/" not in result["url"]
    assert result["upload_id"] == "a" * 24
    assert stage.call_count == 1
    assert stage.call_args.kwargs["uploader"] == "gaong5247-cmd"
    assert stage.call_args.args[0] == "private-gh-token"


def test_other_contributors_keep_vetted_pr_workflow():
    pgn, epd = paired_pgn_epd()
    url = "https://github.com/gaong5247-cmd/OpenFishtest/pull/100"
    with patch("local_upload_server.submit", return_value=url) as submit, \
         patch("local_upload_server.github_token") as gh_secret, \
         patch("local_upload_server.stage_owner_upload") as stage:
        result = submit_bytes(pgn, epd, username="Volunteer-01")
    assert result["method"] == "pull_request"
    assert result["role"] == "contributor"
    assert result["url"] == url
    assert submit.call_count == 1
    assert not gh_secret.called
    assert not stage.called


def test_invalid_data_never_calls_git_or_cli():
    pgn, epd = paired_pgn_epd()
    with patch("local_upload_server.github_login") as login, \
         patch("local_upload_server.stage_owner_upload") as stage:
        with pytest.raises(ValueError):
            submit_bytes(b"This is not chess PGN", epd)
    login.assert_not_called()
    stage.assert_not_called()


@pytest.fixture
def test_server(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, content in [
        ("upload.html", "<html>Safe static upload interface</html>"),
        ("upload.js", "console.log('local')"),
        ("upload.css", "body{}"),
        ("styles.css", "*{}"),
    ]:
        (docs / name).write_text(content, encoding="utf-8")
    server = LocalUploadHTTPServer(
        ("127.0.0.1", 0), LocalUploadHandler, docs=docs
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_port, timeout=3
    )
    supplied_headers = {
        "Host": "127.0.0.1:" + str(server.server_port)
    }
    supplied_headers.update(headers or {})
    connection.request(
        method, path, body=body, headers=supplied_headers
    )
    response = connection.getresponse()
    result = response.read()
    headers = dict(response.getheaders())
    status = response.status
    connection.close()
    return status, result, headers


def upload_payload():
    pgn, epd = paired_pgn_epd()
    return json.dumps({
        "pgn_base64": base64.b64encode(pgn).decode("ascii"),
        "epd_base64": base64.b64encode(epd).decode("ascii"),
    }).encode("utf-8")


def correct_upload_headers(server):
    return {
        "Origin": "http://127.0.0.1:" + str(server.server_port),
        "X-OpenFishtest-Local": "1",
        "Sec-Fetch-Site": "same-origin",
        "Content-Type": "application/json",
    }


def test_local_status_lists_role_and_never_returns_token(test_server):
    with patch("local_upload_server.github_login", return_value="gaong5247-cmd"):
        code, raw, _ = request(test_server, "GET", "/api/status")
    assert code == 200
    status = json.loads(raw)
    assert status["role"] == "owner"
    assert status["username"] == "gaong5247-cmd"
    assert status["token_required_in_browser"] is False
    assert "token" not in status
    assert "access_token" not in status
    assert "ghp_" not in raw.decode("utf-8")


def test_loopback_only_host_origin_and_csrf(test_server):
    payload = upload_payload()
    with patch("local_upload_server.submit_bytes") as submit:
        code, _, _ = request(
            test_server, "POST", "/api/upload", payload,
            {**correct_upload_headers(test_server), "Origin": "https://evil.example"}
        )
        assert code == 403
        code, _, _ = request(
            test_server, "POST", "/api/upload", payload,
            {k:v for k,v in correct_upload_headers(test_server).items()
             if k != "X-OpenFishtest-Local"}
        )
        assert code == 403
        code, _, _ = request(
            test_server, "POST", "/api/upload", payload,
            {**correct_upload_headers(test_server), "Host":"attacker.example"}
        )
        assert code == 403
        code, _, _ = request(
            test_server, "OPTIONS", "/api/upload"
        )
        assert code == 403
        submit.assert_not_called()


def test_happy_path_posts_only_two_data_fields(test_server):
    payload = upload_payload()
    with patch("local_upload_server.submit_bytes") as send:
        send.return_value = {
            "role":"owner", "method":"direct",
            "status":"queued_for_actions","games":2,"points":2,
            "url":"https://github.com/gaong5247-cmd/OpenFishtest/actions"
        }
        code, raw, headers = request(
            test_server, "POST", "/api/upload", payload,
            correct_upload_headers(test_server)
        )
        assert code == 202, raw
        assert json.loads(raw)["status"] == "queued_for_actions"
        assert send.call_count == 1
        pgn, epd = paired_pgn_epd()
        assert send.call_args.args == (pgn, epd)
        assert headers["Cache-Control"] == "no-store"


def test_failed_upload_preserves_source_and_hides_credentials(test_server):
    payload = upload_payload()
    with patch("local_upload_server.submit_bytes",
               side_effect=RuntimeError("private-gh-token must not leak")):
        code, raw, _ = request(
            test_server, "POST", "/api/upload", payload,
            correct_upload_headers(test_server)
        )
    assert code == 502
    assert b"private-gh-token" not in raw
    assert b"Original PGN/EPD remain on PC" in raw
    assert not any(test_server.docs.glob("*.pgn"))
    assert not any(test_server.docs.glob("*.epd"))


def test_reject_untrusted_paths_and_oversize(test_server):
    with patch("local_upload_server.submit_bytes") as submit:
        code, _, _ = request(
            test_server, "GET", "/../contributor_submit.py"
        )
        assert code == 404
        code, _, _ = request(
            test_server, "POST", "/api/upload", b'{"anything":true}',
            correct_upload_headers(test_server)
        )
        assert code == 422
        code, _, _ = request(
            test_server, "POST", "/api/upload", b'{"wrong":true}',
            {**correct_upload_headers(test_server),
             "Content-Length":str(10_000_000)}
        )
        assert code == 413
        submit.assert_not_called()
