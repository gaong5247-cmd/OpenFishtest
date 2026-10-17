"""End-to-end contract test with a tiny fake Fastchess CLI.

The fake executable only exercises worker process invocation, PGN transport and
server accounting; it is NOT proof that real engines have played any games.
"""
import hashlib
import importlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

import worker
from match_protocol import sha256_path


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only executable fixture")
def test_local_worker_executes_and_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFISHTEST_DATA", str(tmp_path / "server-data"))
    monkeypatch.setenv("OPENFISHTEST_ADMIN_TOKEN", "admin")
    monkeypatch.setenv("OPENFISHTEST_WORKER_TOKEN", "worker")
    sys.modules.pop("server", None)
    server = importlib.import_module("server")

    challenger_exe = tmp_path / "challenger.bin"
    challenger_exe.write_bytes(b"Approved challenger binary")
    stockless_exe = tmp_path / "stockless.bin"
    stockless_exe.write_bytes(b"Approved Stockless binary")
    fake_fastchess = tmp_path / "fastchess"
    fake_fastchess.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib,sys\n"
        "path=next(x[5:] for x in sys.argv if x.startswith('file='))\n"
        "pathlib.Path(path).write_text("
        "'[Event \"OpenFishtest\"]\\n"
        "[White \"Challenger\"]\\n[Black \"Stockless\"]\\n"
        "[Result \"1-0\"]\\n\\n1. e4 e5 1-0\\n\\n"
        "[Event \"OpenFishtest\"]\\n"
        "[White \"Stockless\"]\\n[Black \"Challenger\"]\\n"
        "[Result \"0-1\"]\\n\\n1. e4 e5 0-1\\n',"
        "encoding='utf-8')\n",
        encoding="utf-8"
    )
    fake_fastchess.chmod(0o755)

    with TestClient(server.app) as api:
        admin_headers = {"X-Admin-Token": "admin"}
        def register(name, path):
            r = api.post("/api/admin/engines", headers=admin_headers, json={
                "name": name, "version": "test", "sha256": sha256_path(path)
            })
            assert r.status_code == 201, r.text
            return r.json()["id"]
        reference_id = register("Stockless", stockless_exe)
        challenger_id = register("ExampleEngine", challenger_exe)
        r = api.post("/api/admin/reference", headers=admin_headers,
                     json={"engine_id": reference_id})
        assert r.status_code == 200
        r = api.post("/api/admin/tests", headers=admin_headers,
                     json={"engine_id": challenger_id, "games_target": 2,
                           "batch_games": 2, "tc": "1+0.01"})
        assert r.status_code == 201, r.text
        test_id = r.json()["id"]

        def mocked_request_json(base_url, token, endpoint, payload):
            assert base_url == "http://127.0.0.1:8000"
            assert token == "worker"
            response = api.post(endpoint, headers={"X-Worker-Token": token},
                                json=payload)
            assert response.status_code in (200, 204), response.text
            return None if response.status_code == 204 else response.json()
        monkeypatch.setattr(worker, "request_json", mocked_request_json)
        config = {
            "_base": tmp_path, "fastchess": str(fake_fastchess), "concurrency": 1,
            "engines": {
                sha256_path(challenger_exe): str(challenger_exe),
                sha256_path(stockless_exe): str(stockless_exe)
            },
            "books": {}
        }
        job = worker.request_json("http://127.0.0.1:8000", "worker",
                                  "/api/worker/claim", {"worker_id": "e2e"})
        assert job["reference"]["name"] == "Stockless"
        success = worker.run_match(
            job, config, "worker", "http://127.0.0.1:8000",
            max_seconds=30, work_dir=tmp_path / "worker-results"
        )
        assert success
        snap = api.get("/api/public/snapshot").json()
        test = next(t for t in snap["tests"] if t["id"] == test_id)
        assert test["status"] == "complete_worker_reported"
        assert (test["wins"], test["draws"], test["losses"]) == (2, 0, 0)
        assert list((server.DATA_DIR / f"pgn/test-{test_id}").glob("job-*.pgn"))
        assert list((tmp_path / "worker-results").glob("*.pgn")) == []
