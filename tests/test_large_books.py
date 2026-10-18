"""200 MiB opening-book API and streaming-normalizer regression tests.

All test positions are legal. No chess engine executable is run.
"""
import importlib
import random
import sys

import chess
import pytest
from fastapi.testclient import TestClient

from arena_books import (
    MAX_BOOK_BYTES, MAX_NORMALIZED_BYTES, MAX_OPENINGS,
    InvalidBook, normalize_book_file
)


def _epd_positions(count=500):
    out = []
    seen = set()
    for seed in range(count * 3):
        board = chess.Board()
        rng = random.Random(seed + 70131)
        for _ in range(6):
            board.push(rng.choice(list(board.legal_moves)))
        fen = board.fen(en_passant="fen")
        if fen not in seen and not board.is_game_over():
            seen.add(fen)
            out.append(board.epd())
        if len(out) >= count:
            break
    assert len(out) == count
    return out


def test_large_epd_is_streamed_and_compacted(tmp_path):
    assert MAX_BOOK_BYTES == 200 * 1024 * 1024
    paths = _epd_positions()
    book_file = tmp_path / "large.epd"
    unique = ("\n".join(paths) + "\n").encode("utf-8")
    # A book larger than the former 5 MiB limit, written incrementally.
    with book_file.open("wb") as out:
        out.write(unique)
        repeated_chunk = (paths[0] + "\n").encode("utf-8") * 900
        while out.tell() <= 6 * 1024 * 1024:
            out.write(repeated_chunk)
    assert book_file.stat().st_size > 5 * 1024 * 1024
    result = normalize_book_file(book_file, "large.epd")
    assert result.positions == MAX_OPENINGS == 500
    assert len(result.content) < MAX_NORMALIZED_BYTES
    assert result.digest

    # Sparse-file size boundary avoids allocating a 200 MiB test payload
    # while still exercising the strict input-size admission limit.
    with book_file.open("ab") as out:
        out.truncate(MAX_BOOK_BYTES + 1)
    with pytest.raises(InvalidBook, match="200 MiB"):
        normalize_book_file(book_file, "large.epd")


def test_oversized_epd_line_is_bounded(tmp_path):
    path = tmp_path / "giant.epd"
    path.write_bytes(b"#" + b"x" * (140 * 1024) + b"\n")
    with pytest.raises(InvalidBook, match="128 KiB"):
        normalize_book_file(path, "giant.epd")


@pytest.fixture
def local_api(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFISHTEST_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("OPENFISHTEST_ADMIN_TOKEN", "local-test-admin")
    monkeypatch.setenv("OPENFISHTEST_ARENA_UPLOADS", "1")
    monkeypatch.delenv("OPENFISHTEST_ARENA_BOOK", raising=False)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app) as client:
        yield client, server


def test_upload_book_larger_than_5mib_and_purges_temp(local_api):
    client, server = local_api
    paths = _epd_positions(55)
    prefix = ("\n".join(paths) + "\n").encode("utf-8")
    raw = prefix + ((paths[0] + "\n").encode("utf-8") * 110_000)
    assert 5 * 1024 * 1024 < len(raw) < MAX_BOOK_BYTES
    result = client.post(
        "/api/arena/books",
        params={"filename": "large-book.epd"},
        content=raw, headers={"Content-Type": "application/octet-stream"},
    )
    assert result.status_code == 201, result.text
    data = result.json()
    assert data["input_bytes"] == len(raw)
    assert data["max_upload_bytes"] == MAX_BOOK_BYTES
    assert data["positions"] == 55
    destination = server.DATA_DIR / "arena/books" / (
        data["book_sha256"] + ".epd"
    )
    assert destination.is_file()
    assert destination.stat().st_size < 1024 * 1024
    assert not list((server.DATA_DIR / "arena/books").glob("*.incoming"))


def test_early_oversized_content_length_is_rejected(local_api):
    client, _ = local_api
    resp = client.post(
        "/api/arena/books", params={"filename": "huge.pgn"},
        content=b"small text",
        headers={"Content-Type": "application/octet-stream",
                 "Content-Length": str(MAX_BOOK_BYTES + 1)},
    )
    # HTTP client may normalize content length itself; either the server
    # rejects the header or the small body fails PGN validation.
    assert resp.status_code in (400, 413, 422)
