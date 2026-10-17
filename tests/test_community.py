"""Community enrollment, genuine replay, and exploratory statistics tests."""
import base64
import hashlib
import importlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

from engine_stats import analyze


def test_no_invented_statistics():
    empty = analyze(0, 0, 0)
    assert empty["elo_diff"] is None
    assert empty["ci95_low"] is None
    assert empty["sprt"]["status"] == "insufficient_data"
    draws = analyze(0, 100, 0, [0, 0, 50, 0, 0])
    assert draws["elo_diff"] == 0
    assert draws["sprt"]["status"] == "insufficient_data"


def test_paired_estimate_and_experimental_sprt():
    stats = analyze(120, 260, 20, [0, 20, 60, 120, 0])
    assert stats["pairs"] == 200
    assert stats["ci_method"] == "paired_gaussian_approx"
    assert stats["elo_diff"] > 0
    assert stats["ci95_low"] < stats["elo_diff"] < stats["ci95_high"]
    assert stats["sprt"]["status"] == "favor_h1"


@pytest.fixture
def local_api(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFISHTEST_DATA", str(tmp_path))
    monkeypatch.setenv("OPENFISHTEST_ADMIN_TOKEN", "local-admin-secret")
    monkeypatch.delenv("OPENFISHTEST_WORKER_TOKEN", raising=False)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app) as api:
        yield api, server


def admin(api, path, payload):
    return api.post(path, headers={"X-Admin-Token": "local-admin-secret"}, json=payload)


def prepare(api):
    reference = admin(api, "/api/admin/engines", {
        "name":"Stockless", "version":"v0.7", "sha256":"a"*64
    }).json()["id"]
    challenger = admin(api, "/api/admin/engines", {
        "name":"ChessEngine", "version":"v1.0", "sha256":"b"*64
    }).json()["id"]
    assert admin(api, "/api/admin/reference", {"engine_id":reference}).status_code == 200
    test = admin(api, "/api/admin/tests", {
        "engine_id":challenger, "games_target":2, "batch_games":2
    })
    assert test.status_code == 201, test.text
    return test.json()["id"]


def test_public_worker_identity_and_replay(local_api):
    api, server = local_api
    snap = api.get("/api/public/snapshot").json()
    assert snap["engines"] == []
    assert snap["recent_games"] == []
    assert snap["workers"] == []
    test_id = prepare(api)
    response = admin(api, "/api/admin/workers", {
        "worker_id":"volunteer_01", "display_name":"Test Contributor"
    })
    assert response.status_code == 201, response.text
    token = response.json()["worker_token"]
    assert len(token) > 35
    assert "worker_token" not in json.dumps(api.get(
        "/api/public/snapshot").json())

    def work(path, data, worker_token=token):
        return api.post(path, headers={"X-Worker-Token": worker_token}, json=data)

    assert work("/api/worker/claim", {"worker_id":"other_user"}).status_code == 403
    job_response = work("/api/worker/claim", {"worker_id":"volunteer_01"})
    assert job_response.status_code == 200, job_response.text
    job = job_response.json()
    assert job["reference"]["name"] == "Stockless"
    assert job["test_id"] == test_id
    pgn = (
        '[Event "OpenFishtest"]\n[White "Challenger"]\n'
        '[Black "Stockless"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n\n'
        '[Event "OpenFishtest"]\n[White "Stockless"]\n'
        '[Black "Challenger"]\n[Result "0-1"]\n\n1. e4 e5 0-1\n'
    ).encode()
    upload = {
        "lease_id":job["lease_id"],
        "pgn_sha256":hashlib.sha256(pgn).hexdigest(),
        "pgn_base64":base64.b64encode(pgn).decode("ascii")
    }
    sent = work("/api/worker/jobs/" + str(job["job_id"]) + "/finish", upload)
    assert sent.status_code == 200, sent.text
    assert work("/api/worker/jobs/" + str(job["job_id"]) + "/finish",
                upload).json()["duplicate"] is True
    result = api.get("/api/public/snapshot").json()
    assert result["workers"][0]["name"] == "Test Contributor"
    assert result["workers"][0]["games"] == 2
    non_ref = next(e for e in result["engines"] if not e["is_reference"])
    assert non_ref["statistics"]["pairs"] == 1
    assert result["recent_games"]
    assert result["recent_games"][0]["pgn"]
    assert len(result["recent_games"][0]["fens"]) == 3
    assert result["recent_games"][0]["verified"] is False
    assert result["tests"][0]["statistics"]["sprt"]["status"] == "insufficient_data"
    revoked = admin(api, "/api/admin/workers/volunteer_01/revoke", {})
    assert revoked.status_code == 200
    assert work("/api/worker/claim", {"worker_id":"volunteer_01"}).status_code == 403
    private = api.get("/api/admin/workers", headers={
        "X-Admin-Token":"local-admin-secret"
    }).json()
    assert private[0]["active"] == 0
    assert not any("token" in k for k in private[0])


def test_legacy_worker_requires_explicit_secret(local_api):
    api, _ = local_api
    prepare(api)
    assert api.post("/api/worker/claim",
        headers={"X-Worker-Token":"shared-guessed-token"},
        json={"worker_id":"pc"}).status_code == 403
