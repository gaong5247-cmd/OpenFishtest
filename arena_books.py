"""Convert uploaded EPD / PGN opening books to canonical, tested EPD lines.

No code is executed. Users drag a book in the browser and receive an internal
SHA-256 automatically; the arena pins that exact normalized EPD for the match.
Books need at least 50 distinct legal, nonterminal positions for 100 paired
games and are limited to 5 MiB to protect a small self-hosted server.
"""
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.pgn


MAX_BOOK_BYTES = 5 * 1024 * 1024
MIN_OPENINGS = 50
MAX_OPENINGS = 500


class InvalidBook(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedBook:
    content: bytes
    digest: str
    positions: int
    original_format: str


def _unique_legal_positions(boards):
    lines = []
    seen = set()
    for board in boards:
        if not board.is_valid() or board.is_game_over(claim_draw=True):
            raise InvalidBook("Book contains an invalid or terminal opening position")
        # EPD excludes halfmove/fullmove counters, but includes castling
        # and en-passant rights. Use normalized FEN as a distinctness key.
        fen = board.fen(en_passant="fen")
        if fen in seen:
            continue
        seen.add(fen)
        lines.append(board.epd(en_passant="fen"))
        if len(lines) >= MAX_OPENINGS:
            break
    if len(lines) < MIN_OPENINGS:
        raise InvalidBook(
            "Opening book must contain at least 50 distinct legal positions"
        )
    return lines


def _epd_positions(text):
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        board = chess.Board()
        try:
            board.set_epd(line.strip())
        except (ValueError, TypeError) as exc:
            raise InvalidBook(f"Invalid EPD line {n}") from exc
        yield board


def _pgn_positions(text):
    stream = io.StringIO(text)
    games = 0
    while games < MAX_OPENINGS * 4:
        try:
            game = chess.pgn.read_game(stream)
        except (ValueError, chess.InvalidMoveError) as exc:
            raise InvalidBook("Invalid PGN game") from exc
        if game is None:
            break
        games += 1
        if game.errors:
            raise InvalidBook(f"Illegal move in PGN game #{games}")
        board = game.board()
        # Extract a reproducible position after the first eight half-moves,
        # which is a sensible *initial* smoke-test opening, not an official
        # balanced engine-tournament book.
        n = 0
        for move in game.mainline_moves():
            board.push(move)
            n += 1
            if n >= 8:
                break
        if n < 4:
            continue
        yield board


def normalize_book(raw: bytes, filename: str) -> NormalizedBook:
    if not raw or len(raw) > MAX_BOOK_BYTES:
        raise InvalidBook("Book size must be from 1 byte to 5 MiB")
    safe_filename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in (".epd", ".pgn"):
        raise InvalidBook("Only .epd and .pgn books are supported")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidBook("Book must be UTF-8 text") from exc
    if "\x00" in text:
        raise InvalidBook("Book contains binary data")
    lines = _unique_legal_positions(
        _pgn_positions(text) if suffix == ".pgn" else _epd_positions(text)
    )
    content = ("\n".join(lines) + "\n").encode("utf-8")
    if len(content) > MAX_BOOK_BYTES:
        raise InvalidBook("Normalized opening book exceeds size limit")
    return NormalizedBook(
        content, hashlib.sha256(content).hexdigest(),
        len(lines), suffix.lstrip(".")
    )


def persisted_book(path: Path, expected_digest: str):
    """Resolve a book by its hash; never trust a path from the browser."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise InvalidBook("Invalid book SHA-256 identifier")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BOOK_BYTES:
        raise InvalidBook("Book file is missing, symlinked, or too large")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_digest:
        raise InvalidBook("Stored book SHA-256 does not match submitted book")
    return {
        "path": path, "sha256": expected_digest,
        "positions": sum(bool(line.strip()) for line in path.read_text(
            encoding="utf-8").splitlines()),
    }
