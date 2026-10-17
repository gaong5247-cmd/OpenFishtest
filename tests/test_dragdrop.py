"""Direct Windows EXE + drag/drop EPD/PGN + server hash auto-detection.

All 'engine' bytes here are fixture headers. This tests format gating and
queueing only; it does NOT claim those bytes run as real chess engines.
"""
import importlib
import random
import sys
from pathlib import Path

import chess
import pytest
from fastapi.testclient import TestClient

from candidate_formats import inspect_candidate, inspect_windows_exe
from arena_core import UnsafeArchive
from arena_books import InvalidBook, normalize_book


def synthetic_pe64():
    payload = bytearray(1024)
    payload[:2] = b"MZ"
    payload[60:64] = (128).to_bytes(4, "little")
    payload[128:132] = b"PE\x00\x00"
    payload[132:134] = (0x8664).to_bytes(2, "little")
    payload[152:154] = (0x020B).to_bytes(2, "little")
    return bytes(payload)


def openings(count=50):
    seen = set()
    result = []
    seed = 0
    while len(result) < count:
        rng = random.Random(seed)
        seed += 1
        board = chess.Board()
        for _ in range(6):
            board.push(rng.choice(list(board.legal_moves)))
        fen = board.fen(en_passant="fen")
        if fen not in seen and not board.is_game_over():
            seen.add(fen)
            result.append(board.epd())
        assert seed < 10000
    return result


def pgn_book():
    records = []
    for pos in openings():
        position = chess.Board()
        position.set_epd(pos)
        # Use a short legal line leading to the opening position.
        # Reproducibly derive one from the seeded openings below.
        records.append(pos)
    return records


def test_windows_exe_auto_sha_and_header_validation(tmp_path):
    exe = tmp_path / "uploaded.exe"
    exe.write_bytes(synthetic_pe64())
    candidate = inspect_windows_exe(exe)
    assert candidate.platform == "windows_x86_64"
    assert candidate.engine_sha256 == inspect_candidate(exe).engine_sha256
    assert len(candidate.engine_sha256) == 64
    exe.write_bytes(b"not actually a Windows binary")
    with pytest.raises(UnsafeArchive):
        inspect_candidate(exe)


def test_epd_conversion_auto_hash_and_reject_duplicates():
    normalized = normalize_book(("\n".join(openings()) + "\n").encode(), "book.epd")
    assert normalized.positions == 50
    assert normalized.digest == __import__("hashlib").sha256(normalized.content).hexdigest()
    assert normalized.content.endswith(b"\n")
    with pytest.raises(InvalidBook, match="50 distinct"):
        normalize_book((chess.Board().epd() + "\n").encode() * 50, "repeated.epd")


def test_pgn_conversion_autogenerates_book():
    import chess.pgn
    import io
    payload = []
    for i in range(50):
        board = chess.Board()
        rng = random.Random(i + 940)
        game = chess.pgn.Game()
        node = game
        for _ in range(8):
            move = rng.choice(list(board.legal_moves))
            node = node.add_variation(move)
            board.push(move)
        payload.append(str(game))
    book = normalize_book(("\n\n".join(payload)+"\n").encode(), "gamebook.pgn")
    assert book.positions >= 50
    assert book.original_format == "pgn"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFISHTEST_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("OPENFISHTEST_ADMIN_TOKEN", "admin-test-secret")
    monkeypatch.setenv("OPENFISHTEST_ARENA_UPLOADS", "1")
    monkeypatch.setenv("OPENFISHTEST_WINDOWS_ARENA", "1")
    monkeypatch.delenv("OPENFISHTEST_ARENA_BOOK", raising=False)
    sys.modules.pop("server", None)
    app = importlib.import_module("server")
    with TestClient(app.app) as client:
        yield client, app


def pin_reference(client):
    headers = {"X-Admin-Token": "admin-test-secret"}
    reg = client.post("/api/admin/engines", headers=headers, json={
        "name": "Stockless", "version":"Linux64", "sha256":"a" * 64
    })
    assert reg.status_code == 201
    pinned = client.post("/api/admin/reference", headers=headers, json={
        "engine_id": reg.json()["id"]
    })
    assert pinned.status_code == 200


def test_custom_book_and_direct_exe_queue_without_manual_fields(api):
    client, server = api
    pin_reference(client)
    state = client.get("/api/arena/policy").json()
    assert state["accepting"] is False
    assert state["book_upload_enabled"] is True
    data = ("\n".join(openings()) + "\n").encode()
    saved = client.post("/api/arena/books", params={"filename":"mybook.epd"},
        content=data, headers={"Content-Type":"application/octet-stream"})
    assert saved.status_code == 201, saved.text
    assert saved.json()["positions"] >= 50
    digest = saved.json()["book_sha256"]
    assert (server.DATA_DIR / "arena/books" / (digest + ".epd")).is_file()
    engine = client.post("/api/arena/submit", params={"book_sha256":digest},
        content=synthetic_pe64(),
        headers={"Content-Type":"application/octet-stream"})
    assert engine.status_code == 201, engine.text
    assert engine.json()["engine_platform"] == "windows_x86_64"
    assert len(engine.json()["engine_sha256"]) == 64
    public = client.get("/api/arena/entries/" + str(engine.json()["id"])).json()
    assert public["engine_name"] == "UCI detection pending"
    assert public["engine_platform"] == "windows_x86_64"
    assert public["uci_options"] == []


def test_unknown_book_and_disabled_windows_fail_closed(api, monkeypatch):
    client, _ = api
    pin_reference(client)
    response = client.post("/api/arena/submit",
        params={"book_sha256":"e" * 64},
        content=synthetic_pe64(),
        headers={"Content-Type":"application/octet-stream"})
    assert response.status_code == 503
    uploaded = client.post("/api/arena/books", params={"filename":"x.pgn"},
        content=b"invalid", headers={"Content-Type":"application/octet-stream"})
    assert uploaded.status_code == 422
    book = client.post("/api/arena/books", params={"filename":"good.epd"},
        content=("\n".join(openings())+"\n").encode(),
        headers={"Content-Type":"application/octet-stream"})
    assert book.status_code == 201
    monkeypatch.setenv("OPENFISHTEST_WINDOWS_ARENA", "0")
    response = client.post("/api/arena/submit",
        params={"book_sha256":book.json()["book_sha256"]},
        content=synthetic_pe64(),
        headers={"Content-Type":"application/octet-stream"})
    assert response.status_code == 503
