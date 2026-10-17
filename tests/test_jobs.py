import base64
import hashlib
import importlib
import sys
import time

import pytest
from fastapi.testclient import TestClient

from match_protocol import sha256_path


SAMPLE_PGN = (
    '[Event "OpenFishtest"]\n'
    '[White "Challenger"]\n'
    '[Black "Stockless"]\n'
    '[Result "1-0"]\n\n'
    '1. e4 e5 1-0\n\n'
    '[Event "OpenFishtest"]\n'
    '[White "Stockless"]\n'
    '[Black "Challenger"]\n'
    '[Result "0-1"]\n\n'
    '1. e4 e5 0-1\n\n'
).encode("utf-8")


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFISHTEST_DATA", str(tmp_path))
    monkeypatch.setenv("OPENFISHTEST_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("OPENFISHTEST_WORKER_TOKEN", "worker-secret")
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app) as client:
        yield client, server


def admin(api, path, payload):
    return api.post(path, headers={"X-Admin-Token": "admin-secret"}, json=payload)


def work(api, path, payload):
    return api.post(path, headers={"X-Worker-Token": "worker-secret"}, json=payload)


def prepare_test(api, games=4, batch=2, book=None):
    reference = admin(api, "/api/admin/engines", {
        "name": "Stockless", "version": "v0.7", "sha256": "a" * 64
    }).json()["id"]
    challenger = admin(api, "/api/admin/engines", {
        "name": "RubiChess", "version": "v1", "sha256": "b" * 64
    }).json()["id"]
    assert admin(api, "/api/admin/reference", {"engine_id": reference}).status_code == 200
    response = admin(api, "/api/admin/tests", {
        "engine_id": challenger, "games_target": games, "batch_games": batch,
        "book_sha256": book, "tc": "10+0.1"
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def submit(api, job, raw=SAMPLE_PGN):
    return work(api, f"/api/worker/jobs/{job['job_id']}/finish", {
        "lease_id": job["lease_id"],
        "pgn_base64": base64.b64encode(raw).decode("ascii"),
        "pgn_sha256": hashlib.sha256(raw).hexdigest()
    })


def test_claim_finish_retry_idempotent_and_stats(api):
    client, server = api
    test_id = prepare_test(client)
    assert work(client, "/api/worker/claim", {"worker_id": "pc"}).status_code == 200
    first = work(client, "/api/worker/claim", {"worker_id": "pc"}).json()
    assert first["start_game"] == 2
    assert first["games"] == 2
    assert first["reference"]["name"] == "Stockless"
    assert work(client, f"/api/worker/jobs/{first['job_id']}/heartbeat", {
        "lease_id": first["lease_id"]
    }).status_code == 200
    response = submit(client, first)
    assert response.status_code == 200, response.text
    assert response.json()["results"] == {"wins": 2, "draws": 0, "losses": 0, "games": 2}
    assert submit(client, first).json()["duplicate"] is True
    assert client.put(f"/api/admin/tests/{test_id}/results",
        headers={"X-Admin-Token": "admin-secret"},
        json={"wins": 0, "draws": 0, "losses": 4}).status_code == 409
    # Only one of the two jobs is finished here.
    snap = client.get("/api/public/snapshot").json()
    row = next(t for t in snap["tests"] if t["id"] == test_id)
    assert row["games_done"] == 2
    with server.connection() as db:
        remaining = db.execute(
            "SELECT * FROM jobs WHERE test_id=? AND status='leased'", (test_id,)
        ).fetchone()
        assert remaining is not None
        original_lease = remaining["lease_id"]
    # Expire the first claim and let another worker finish the same starting index.
    with server.connection() as db:
        db.execute("UPDATE jobs SET lease_expires=? WHERE id=?",
                   (time.time() - 10, remaining["id"]))
    other = work(client, "/api/worker/claim", {"worker_id": "pc2"}).json()
    assert other["job_id"] == remaining["id"]
    assert other["start_game"] == 0
    assert other["lease_id"] != original_lease
    assert submit(client, other).status_code == 200
    snap = client.get("/api/public/snapshot").json()
    row = next(t for t in snap["tests"] if t["id"] == test_id)
    assert row["games_done"] == 4
    assert row["status"] == "complete_worker_reported"
    assert work(client, "/api/worker/claim", {"worker_id": "idle"}).status_code == 204
    assert snap["reference"]["name"] == "Stockless"
    assert sum(e["games"] for e in snap["engines"]) == 4
    assert (server.DATA_DIR / f"pgn/test-{test_id}/job-{first['job_id']}.pgn").is_file()


def test_rejects_invalid_pgn_and_invalid_worker_secret(api):
    client, server = api
    prepare_test(client, games=2)
    assert client.post("/api/worker/claim", headers={"X-Worker-Token": "wrong"},
        json={"worker_id": "pc"}).status_code == 403
    job = work(client, "/api/worker/claim", {"worker_id": "pc"}).json()
    bad = submit(client, job, raw=b"invalid game")
    assert bad.status_code == 422
    invalid_lease = work(client, f"/api/worker/jobs/{job['job_id']}/heartbeat", {
        "lease_id": "incorrect" * 5
    })
    assert invalid_lease.status_code == 409
    assert submit(client, job).status_code == 200


def test_failed_jobs_stop_after_3_attempts(api):
    client, server = api
    test_id = prepare_test(client, games=2)
    for trial in range(3):
        job = work(client, "/api/worker/claim", {"worker_id": "pc"}).json()
        res = work(client, f"/api/worker/jobs/{job['job_id']}/failed", {
            "lease_id": job["lease_id"], "reason": "test-only setup issue"
        })
        assert res.status_code == 200
        assert res.json()["retry_allowed"] == (trial < 2)
    assert work(client, "/api/worker/claim", {"worker_id": "pc"}).status_code == 204
    row = next(t for t in client.get("/api/public/snapshot").json()["tests"]
               if t["id"] == test_id)
    assert row["status"] == "worker_error"


def test_admin_pause_resume_cancel_revokes_leases(api):
    client, server = api
    test_id = prepare_test(client, games=2)
    first = work(client, "/api/worker/claim", {"worker_id": "pc1"}).json()
    admin_headers = {"X-Admin-Token": "admin-secret"}
    paused = client.post(f"/api/admin/tests/{test_id}/pause", headers=admin_headers)
    assert paused.status_code == 200
    heartbeat = work(client, f"/api/worker/jobs/{first['job_id']}/heartbeat", {
        "lease_id": first["lease_id"]
    })
    assert heartbeat.status_code == 409
    assert work(client, "/api/worker/claim", {"worker_id": "pc2"}).status_code == 204
    resumed = client.post(f"/api/admin/tests/{test_id}/resume", headers=admin_headers)
    assert resumed.status_code == 200
    second = work(client, "/api/worker/claim", {"worker_id": "pc2"}).json()
    assert second["job_id"] == first["job_id"]
    assert second["lease_id"] != first["lease_id"]
    cancelled = client.post(f"/api/admin/tests/{test_id}/cancel", headers=admin_headers)
    assert cancelled.status_code == 200
    assert submit(client, second).status_code == 409
    assert work(client, "/api/worker/claim", {"worker_id": "pc3"}).status_code == 204
    row = next(t for t in client.get("/api/public/snapshot").json()["tests"]
               if t["id"] == test_id)
    assert row["status"] == "cancelled"
