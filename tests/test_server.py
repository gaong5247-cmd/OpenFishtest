import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFISHTEST_DATA", str(tmp_path))
    monkeypatch.setenv("OPENFISHTEST_ADMIN_TOKEN", "test-token")
    if "server" in sys.modules:
        del sys.modules["server"]
    server = importlib.import_module("server")
    with TestClient(server.app) as client:
        yield client


def post(api, path, payload, token="test-token"):
    return api.post(path, json=payload, headers={"X-Admin-Token": token})


def test_empty_snapshot_and_auth(api):
    response = api.get("/api/public/snapshot")
    assert response.status_code == 200
    body = response.json()
    assert body["reference"] is None
    assert body["engines"] == []
    assert body["storage"]["max_bytes"] == 5_000_000_000
    assert post(api, "/api/admin/engines", {
        "name": "Stockless", "version": "v0.7", "sha256": "a" * 64
    }, token="invalid").status_code == 403


def test_reference_enforced_and_report_is_idempotent(api):
    sf = post(api, "/api/admin/engines", {
        "name": "Stockless", "version": "v0.7", "sha256": "a" * 64
    }).json()["id"]
    challenger = post(api, "/api/admin/engines", {
        "name": "RubiChess", "version": "test", "sha256": "b" * 64
    }).json()["id"]
    assert post(api, "/api/admin/reference", {"engine_id": challenger}).status_code == 422
    assert post(api, "/api/admin/tests", {
        "engine_id": challenger, "games_target": 20
    }).status_code == 409
    assert post(api, "/api/admin/reference", {"engine_id": sf}).status_code == 200
    assert post(api, "/api/admin/tests", {
        "engine_id": challenger, "games_target": 21
    }).status_code == 422
    created = post(api, "/api/admin/tests", {
        "engine_id": challenger, "games_target": 20
    })
    assert created.status_code == 201
    test_id = created.json()["id"]
    result = {"wins": 9, "draws": 8, "losses": 3}
    for _ in range(2):
        updated = api.put(
            f"/api/admin/tests/{test_id}/results", json=result,
            headers={"X-Admin-Token": "test-token"}
        )
        assert updated.status_code == 200
    body = api.get("/api/public/snapshot").json()
    record = next(e for e in body["engines"] if e["name"] == "RubiChess")
    assert record["games"] == 20
    assert record["rating"] > 3000
    assert body["tests"][0]["status"] == "complete_unverified"
    assert body["tests"][0]["games_done"] == 20


def test_untrusted_inputs_and_overflow(api):
    assert post(api, "/api/admin/engines", {
        "name": "Fake", "version": "x", "sha256": "not-a-digest"
    }).status_code == 422
    response = api.put(
        "/api/admin/tests/999/results", json={"wins": 0, "draws": 0, "losses": 0},
        headers={"X-Admin-Token": "test-token"}
    )
    assert response.status_code == 404
