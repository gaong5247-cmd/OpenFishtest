"""Regression for six-field FEN opening books stored with .epd extension."""
import chess
import pytest

from arena_books import InvalidBook, normalize_book


def test_fen6_book_is_accepted_and_normalized_to_epd():
    # Fifty unique legal FEN6 lines with real move clocks.
    records = []
    seen = set()
    for a in range(1, 51):
        board = chess.Board()
        for ply in range(2 + a % 6):
            move = sorted(board.legal_moves, key=lambda m: m.uci())[
                (a * 7 + ply) % board.legal_moves.count()
            ]
            board.push(move)
        fen = board.fen(en_passant="fen")
        if fen not in seen:
            seen.add(fen)
            records.append(fen)
    assert len(records) == 50
    book = normalize_book(("\n".join(records) + "\n").encode(), "book.epd")
    assert book.positions == 50
    for line in book.content.decode().splitlines():
        assert len(line.split()) == 4
        parsed = chess.Board()
        parsed.set_epd(line)
        assert parsed.is_valid()


def test_invalid_fen6_rejected():
    bad = ("8/8/8/8/8/8/8/8 w - - 0 1\n" * 50).encode()
    with pytest.raises(InvalidBook):
        normalize_book(bad, "broken.epd")
