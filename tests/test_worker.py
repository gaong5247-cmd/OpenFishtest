from pathlib import Path

import pytest

from match_protocol import sha256_path
from worker import command_for_job, load_settings, server_url


def test_server_requires_tls_outside_localhost():
    assert server_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert server_url("https://example.org") == "https://example.org"
    with pytest.raises(ValueError, match="HTTPS"):
        server_url("http://example.org:8000")
    with pytest.raises(ValueError, match="path"):
        server_url("https://example.org/evil")


def test_worker_command_checks_hashes_and_pairs(tmp_path):
    fastchess = tmp_path / "fastchess"
    fastchess.write_bytes(b"fastchess")
    candidate = tmp_path / "candidate"
    candidate.write_bytes(b"challenger")
    stockless = tmp_path / "stockless"
    stockless.write_bytes(b"stockless")
    book = tmp_path / "openings.epd"
    book.write_bytes(b"test openings")
    config = {
        "_base": tmp_path, "fastchess": str(fastchess),
        "engines": {sha256_path(candidate): str(candidate),
                    sha256_path(stockless): str(stockless)},
        "books": {sha256_path(book): str(book)}, "concurrency": 1
    }
    job = {
        "games": 4, "start_game": 20, "tc": "10+0.1",
        "challenger": {"name": "RubiChess", "sha256": sha256_path(candidate)},
        "reference": {"name": "Stockless", "sha256": sha256_path(stockless)},
        "book_sha256": sha256_path(book), "book_format": "epd"
    }
    command = command_for_job(job, config, tmp_path / "batch.pgn")
    assert "-rounds" in command
    assert command[command.index("-rounds") + 1] == "2"
    assert "start=11" in command
    assert command.count("-engine") == 2
    stockless.write_bytes(b"tampered!")
    with pytest.raises(ValueError, match="SHA-256"):
        command_for_job(job, config, tmp_path / "batch.pgn")
