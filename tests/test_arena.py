"""Regression tests for quarantine, public upload, 55-point evaluation and owner inbox."""
import hashlib
import io
import os
import stat
import sys
import zipfile
import importlib
import json
import sqlite3
from pathlib import Path

import chess
import pytest
from fastapi.testclient import TestClient

from arena_core import (
    UnsafeArchive, MAX_UPLOAD_BYTES, classify_score, validate_archive,
    extract_quarantined
)
from arena_runner import finalize_match, finalize_error
from match_protocol import parse_pgn_results


def sample_elf():
    header = bytearray(96)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = (62).to_bytes(2, "little")
    header[24:64] = os.urandom(40)
    return bytes(header)


def zip_bytes(content=None):
    dest = io.BytesIO()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("engine", content or sample_elf())
        zipped.writestr("approved.nnue", os.urandom(128))
    return dest.getvalue()


def test_archive_file_types_and_elf(tmp_path):
    path = tmp_path / "candidate.zip"
    path.write_bytes(zip_bytes())
    accepted = validate_archive(path)
    assert accepted.auxiliary_nets == 1
    assert len(accepted.engine_sha256) == 64
    destination = tmp_path / "unpacked"
    extracted = extract_quarantined(path, destination)
    assert extracted.engine_sha256 == accepted.engine_sha256
    assert (destination / "engine").read_bytes().startswith(b"\x7fELF")
    with pytest.raises(FileExistsError):
        extract_quarantined(path, destination)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zipout:
        zipout.writestr("../escape", b"bad")
        zipout.writestr("engine", sample_elf())
    with pytest.raises(UnsafeArchive):
        validate_archive(path)
    assert not (tmp_path / "escape").exists()
    path.write_bytes(zip_bytes(b"Fake EXE, not ELF"))
    with pytest.raises(UnsafeArchive, match="ELF"):
        validate_archive(path)


def test_100_game_selection_rule_exact_score():
    assert classify_score(54, 2, 44)["passed"]  # 54 + 1 = 55
    assert classify_score(55, 0, 45)["score"] == 55
    assert classify_score(54, 1, 45)["passed"] is False
    assert classify_score(0, 100, 0)["score"] == 50
    with pytest.raises(ValueError):
        classify_score(55, 0, 44)


@pytest.fixture
def arena_api(tmp_path, monkeypatch):
    book = tmp_path / "openings.epd"
    book.write_text(chess.Board().epd() + "\n" * 0 if False else
                    (chess.Board().epd() + "\n") * 50, encoding="utf-8")
    monkeypatch.setenv("OPENFISHTEST_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("OPENFISHTEST_ADMIN_TOKEN", "secret-admin")
    monkeypatch.setenv("OPENFISHTEST_ARENA_BOOK", str(book))
    monkeypatch.setenv("OPENFISHTEST_ARENA_UPLOADS", "1")
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app) as api:
        yield api, server


def set_reference(api):
    r = api.post("/api/admin/engines", headers={"X-Admin-Token": "secret-admin"},
                 json={"name": "Stockless", "version": "v0.7-linux",
                       "sha256": "a" * 64})
    assert r.status_code == 201, r.text
    pinned = api.post("/api/admin/reference",
        headers={"X-Admin-Token": "secret-admin"}, json={"engine_id":r.json()["id"]})
    assert pinned.status_code == 200, pinned.text


def upload(api, data):
    return api.post("/api/arena/submit", params={
        "engine_name": "Challenger", "engine_version": "2026.10",
        "source_url": "https://example.org/challenger"
    }, content=data, headers={"Content-Type": "application/zip"})


def build_100_pgn(wins=54, draws=2):
    games = []
    for i in range(100):
        white = "Challenger" if i % 2 == 0 else "Stockless"
        black = "Stockless" if i % 2 == 0 else "Challenger"
        if i < wins:
            outcome = "1-0" if white == "Challenger" else "0-1"
        elif i < wins + draws:
            outcome = "1/2-1/2"
        else:
            outcome = "0-1" if white == "Challenger" else "1-0"
        games.append(
            f'[Event "OpenFishtest Arena"]\n[White "{white}"]\n'
            f'[Black "{black}"]\n[Result "{outcome}"]\n'
            f'[Round "{i//2+1}"]\n\n1. e4 e5 {outcome}\n\n'
        )
    return "".join(games).encode()


def test_pin_stockless_before_arena_upload(arena_api):
    api, server = arena_api
    assert api.get("/api/arena/policy").json()["accepting"] is False
    assert upload(api, zip_bytes()).status_code == 503
    set_reference(api)
    assert api.get("/api/arena/policy").json()["accepting"] is True


def test_public_upload_and_private_shortlist(arena_api):
    api, server = arena_api
    set_reference(api)
    uploaded = upload(api, zip_bytes())
    assert uploaded.status_code == 201, uploaded.text
    idx = uploaded.json()["id"]
    assert uploaded.json()["games"] == 100
    assert uploaded.json()["pass_points"] == 55
    public = api.get(f"/api/arena/entries/{idx}").json()
    assert public["status"] == "queued"
    assert "archive_path" not in public
    private = api.get("/api/admin/arena", headers={"X-Admin-Token":"secret-admin"})
    assert private.status_code == 200
    assert private.json()["entries"][0]["archive_path"]
    assert api.get(f"/api/admin/arena/{idx}/download").status_code == 403
    assert api.get(f"/api/admin/arena/{idx}/download",
                   headers={"X-Admin-Token":"secret-admin"}).status_code == 404
    pgndata = build_100_pgn(54, 2)
    parsed = parse_pgn_results(pgndata, 100)
    assert parsed.wins == 54 and parsed.draws == 2
    with server.connection() as db:
        db.execute("UPDATE arena_entries SET status='running',run_id='abc' WHERE id=?",
                   (idx,))
        row = dict(db.execute("SELECT * FROM arena_entries WHERE id=?", (idx,)).fetchone())
    score = classify_score(parsed.wins, parsed.draws, parsed.losses)
    outcome = finalize_match(server.connection, server.DATA_DIR, row, "abc",
                             pgndata, parsed, score, row["book_sha256"])
    assert outcome == "passed"
    private = api.get("/api/admin/arena", headers={"X-Admin-Token":"secret-admin"})
    assert private.json()["notifications"] == 1
    assert private.json()["entries"][0]["download_available"] is True
    assert api.get(f"/api/admin/arena/{idx}/download",
                   headers={"X-Admin-Token":"secret-admin"}).status_code == 200
    assert api.get(f"/api/arena/entries/{idx}/pgn").status_code == 200
    assert api.get("/api/public/snapshot").json()["arena"][0]["score"] == 55
    assert api.get("/api/public/snapshot").json()["recent_games"]
    release = api.post(f"/api/admin/arena/{idx}/mark-released",
                       headers={"X-Admin-Token":"secret-admin"},
                       json={"release_url":"https://github.com/example/repo/releases/tag/v1"})
    assert release.status_code == 200, release.text


def test_rejected_upload_file_is_deleted_and_data_retained(arena_api):
    api, server = arena_api
    set_reference(api)
    uploaded = upload(api, zip_bytes())
    idx = uploaded.json()["id"]
    with server.connection() as db:
        db.execute("UPDATE arena_entries SET status='running',run_id='abc' WHERE id=?", (idx,))
        row = dict(db.execute("SELECT * FROM arena_entries WHERE id=?", (idx,)).fetchone())
    raw = build_100_pgn(40, 0)
    result = parse_pgn_results(raw, 100)
    outcome = finalize_match(server.connection, server.DATA_DIR, row, "abc", raw,
                             result, classify_score(result.wins, result.draws, result.losses),
                             row["book_sha256"])
    assert outcome == "rejected"
    assert not (server.DATA_DIR / row["archive_path"]).exists()
    assert (server.DATA_DIR / "pgn" / "arena" / f"arena-{idx}.pgn").is_file()
    public = api.get(f"/api/arena/entries/{idx}").json()
    assert public["score"] == 40
    assert public["pgn_available"]
    assert api.get(f"/api/arena/entries/{idx}/pgn").status_code == 200


def test_rate_limit_and_invalid_zip(arena_api):
    api, server = arena_api
    set_reference(api)
    assert upload(api, b"bad").status_code == 422
    assert upload(api, zip_bytes()).status_code == 201
    assert upload(api, zip_bytes()).status_code == 429  # failed attempt counts
    assert upload(api, zip_bytes()).status_code == 429
