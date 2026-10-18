"""Bounded-memory EPD/PGN opening-book normalization for the 100-game arena.

Accept uploads up to 200 MiB without ever loading the entire upload into RAM.
Only the first 500 *distinct legal* positions from a bounded prefix are
normalized into a small pinned EPD: a 200 MiB PGN is NOT used verbatim as the
Fastchess book. The deliberate parsing caps guard against anonymous DoS.
"""
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.pgn

MAX_BOOK_BYTES = 200 * 1024 * 1024
MAX_NORMALIZED_BYTES = 1 * 1024 * 1024
MIN_OPENINGS = 50
MAX_OPENINGS = 500
MAX_SCAN_RECORDS = 10_000
MAX_PGN_PARSE_BYTES = 24 * 1024 * 1024
MAX_LINE_CHARS = 128 * 1024


class InvalidBook(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedBook:
    content: bytes
    digest: str
    positions: int
    original_format: str


class _LimitedTextReader:
    """Bound how much of a PGN is parsed and how long one line may grow."""

    def __init__(self, source):
        self.source = source
        self.read_chars = 0

    def readline(self, size=-1):
        line = self.source.readline(MAX_LINE_CHARS + 1)
        if len(line) > MAX_LINE_CHARS:
            raise InvalidBook("PGN line exceeds 128 KiB parser safety limit")
        self.read_chars += len(line)
        if self.read_chars > MAX_PGN_PARSE_BYTES:
            raise InvalidBook(
                "PGN prefix exceeds 24 MiB parsing budget before enough openings"
            )
        return line

    def tell(self):
        return self.source.tell()

    def seek(self, *args):
        return self.source.seek(*args)


def _unique_legal_positions(boards):
    lines = []
    seen = set()
    for board in boards:
        if not board.is_valid() or board.is_game_over(claim_draw=True):
            raise InvalidBook("Book contains invalid or terminal opening position")
        fen = board.fen(en_passant="fen")
        if fen in seen:
            continue
        seen.add(fen)
        lines.append(board.epd(en_passant="fen"))
        if len(lines) == MAX_OPENINGS:
            break
    if len(lines) < MIN_OPENINGS:
        raise InvalidBook("Opening book must contain at least 50 distinct legal positions")
    return lines


def _epd_positions(source):
    seen_records = 0
    line_number = 0
    while True:
        # Never call unbounded readline() on a potentially 200 MiB single line.
        line = source.readline(MAX_LINE_CHARS + 1)
        if not line:
            break
        line_number += 1
        if len(line) > MAX_LINE_CHARS:
            raise InvalidBook(f"EPD line {line_number} exceeds 128 KiB")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        seen_records += 1
        if seen_records > MAX_SCAN_RECORDS:
            break
        try:
            # A number of popular opening books use six-field FEN lines
            # despite having a .epd extension. EPD itself uses four
            # position fields (optionally followed by EPD operations).
            # Try EPD first to preserve its operations and then FEN6.
            board = chess.Board()
            try:
                board.set_epd(line.strip())
            except (ValueError, TypeError):
                fields = line.strip().split()
                if len(fields) != 6:
                    raise
                board = chess.Board(line.strip())
            if not board.is_valid():
                raise ValueError("Invalid chess position")
        except (ValueError, TypeError) as exc:
            raise InvalidBook(f"Invalid EPD/FEN line {line_number}") from exc
        yield board


def _pgn_positions(source):
    reader = _LimitedTextReader(source)
    for games in range(1, MAX_SCAN_RECORDS + 1):
        try:
            game = chess.pgn.read_game(reader)
        except (ValueError, chess.InvalidMoveError) as exc:
            raise InvalidBook(f"Invalid PGN game #{games}") from exc
        if game is None:
            return
        if game.errors:
            raise InvalidBook(f"Illegal move in PGN game #{games}")
        board = game.board()
        # Take the position after 8 halfmoves from each legal PGN.
        # This is a deterministic quick benchmark book, NOT a calibrated
        # competition opening book.
        ply_count = 0
        for move in game.mainline_moves():
            board.push(move)
            ply_count += 1
            if ply_count == 8:
                break
        if ply_count >= 4:
            yield board


def _normalize_source(source, filename):
    suffix = Path(filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).suffix.lower()
    if suffix not in (".epd", ".pgn"):
        raise InvalidBook("Only .epd and .pgn opening books are supported")
    try:
        positions = (
            _pgn_positions(source) if suffix == ".pgn" else _epd_positions(source)
        )
        lines = _unique_legal_positions(positions)
    except UnicodeError as exc:
        raise InvalidBook("Opening book must be UTF-8 text") from exc
    content = ("\n".join(lines) + "\n").encode("utf-8")
    if len(content) > MAX_NORMALIZED_BYTES:
        raise InvalidBook("Normalized opening positions exceed 1 MiB")
    return NormalizedBook(
        content, hashlib.sha256(content).hexdigest(),
        len(lines), suffix.lstrip(".")
    )


def normalize_book(raw: bytes, filename: str) -> NormalizedBook:
    """Small-input convenience function retained for existing tests."""
    if not raw or len(raw) > MAX_BOOK_BYTES:
        raise InvalidBook("Book upload must be 1 byte to 200 MiB")
    try:
        return _normalize_source(io.StringIO(raw.decode("utf-8-sig")), filename)
    except UnicodeError as exc:
        raise InvalidBook("Opening book must be UTF-8 text") from exc


def normalize_book_file(path: Path, filename: str) -> NormalizedBook:
    """Parse an on-disk 200 MiB upload with constant-sized memory use."""
    if path.is_symlink() or not path.is_file():
        raise InvalidBook("Opening book upload is missing or not a regular file")
    if not 0 < path.stat().st_size <= MAX_BOOK_BYTES:
        raise InvalidBook("Book upload must be 1 byte to 200 MiB")
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict") as source:
            return _normalize_source(source, filename)
    except UnicodeError as exc:
        raise InvalidBook("Opening book must be UTF-8 text") from exc


def persisted_book(path: Path, expected_digest: str):
    """Resolve a normalized pinned book from its SHA-256; never arbitrary paths."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise InvalidBook("Invalid book SHA-256 identifier")
    if (
        path.is_symlink() or not path.is_file()
        or path.stat().st_size > MAX_NORMALIZED_BYTES
    ):
        raise InvalidBook("Normalized book missing, symlinked or oversized")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as reader:
        for line in reader:
            digest.update(line)
            if line.strip():
                count += 1
    if digest.hexdigest() != expected_digest:
        raise InvalidBook("Stored book SHA-256 differs from submitted hash")
    if count < MIN_OPENINGS:
        raise InvalidBook("Stored book has fewer than 50 openings")
    return {"path": path, "sha256": expected_digest, "positions": count}
