"""Paired PGN parsing with legal chess move validation.

This checks move legality and tag/result consistency for worker-submitted PGNs.
A legal PGN is still NOT cryptographic proof that an engine honestly played.
"""
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.pgn

MAX_PGN_BYTES = 2_000_000
MAX_PLIES_PER_GAME = 800


class MatchValidationError(ValueError):
    """PGN batch does not meet the expected protocol."""


@dataclass(frozen=True)
class MatchResult:
    wins: int
    draws: int
    losses: int
    games: int
    penta: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)


def sha256_path(filename: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(filename).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_pgn_results(pgn: bytes, expected_games: int) -> MatchResult:
    """Count results in paired Fastchess PGNs, verifying legal move sequences.

    Names must be exactly 'Challenger' and 'Stockless'. Opening pairs
    swap colors and have the same starting board, regardless of PGN completion
    order under concurrent Fastchess execution. Results remain
    worker-reported; resignations and agreed draws cannot be independently
    authenticated from PGN text.
    """
    if not pgn or len(pgn) > MAX_PGN_BYTES:
        raise MatchValidationError("Missing PGN or PGN exceeds 2 MB")
    if expected_games < 2 or expected_games % 2:
        raise MatchValidationError("Expected games must be positive and even")
    try:
        data = pgn.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MatchValidationError("PGN must be UTF-8 text") from exc

    stream = io.StringIO(data)
    games = []
    while True:
        if len(games) >= expected_games:
            try:
                extra = chess.pgn.read_game(stream)
            except (ValueError, chess.InvalidMoveError) as exc:
                raise MatchValidationError("Malformed trailing PGN") from exc
            if extra is not None:
                raise MatchValidationError("More games than expected")
            break
        try:
            game = chess.pgn.read_game(stream)
        except (ValueError, chess.InvalidMoveError) as exc:
            raise MatchValidationError("Malformed chess PGN") from exc
        if game is None:
            break
        if game.errors:
            raise MatchValidationError(f"Illegal or invalid moves: {game.errors[0]}")
        headers = game.headers
        white, black, result = (
            headers.get("White"), headers.get("Black"), headers.get("Result")
        )
        if {white, black} != {"Challenger", "Stockless"}:
            raise MatchValidationError(
                "Game must contain precisely Challenger vs Stockless"
            )
        if result not in ("1-0", "0-1", "1/2-1/2"):
            raise MatchValidationError("Invalid result in PGN")
        try:
            board = game.board()
            initial_fen = board.fen(en_passant="fen")
            ply_count = 0
            for move in game.mainline_moves():
                if not board.is_legal(move):
                    raise MatchValidationError("Game has an illegal move")
                board.push(move)
                ply_count += 1
                if ply_count > MAX_PLIES_PER_GAME:
                    raise MatchValidationError("Game exceeds maximum ply count")
            if not ply_count:
                raise MatchValidationError("Game contains no moves")
            # Check forced checkmates against declared Result (resign/draw
            # outcomes are possible in non-terminal positions).
            if board.is_checkmate():
                winner = "0-1" if board.turn == chess.WHITE else "1-0"
                if winner != result:
                    raise MatchValidationError("Checkmate contradicts PGN Result")
        except (ValueError, chess.InvalidMoveError) as exc:
            raise MatchValidationError("Invalid initial chess position or moves") from exc

        if result == "1/2-1/2":
            points = 1
        elif (result == "1-0" and white == "Challenger") or (
            result == "0-1" and black == "Challenger"
        ):
            points = 2
        else:
            points = 0
        games.append((white, black, initial_fen, result, points))

    if len(games) != expected_games:
        raise MatchValidationError(
            f"Expected {expected_games} PGN games, found {len(games)}"
        )
    # Fastchess writes PGNs as games finish. With concurrency > 1,
    # completion order is NOT opening-pair order. Pair by opening position
    # and opposite engine colors, while preserving the first occurrence
    # order of each distinct opening for the EPD book consistency check.
    # Repeated openings can be ambiguous if the same position is reused;
    # consume one game of each color per opening for every pair.
    from collections import OrderedDict
    grouped = OrderedDict()
    for white, black, initial_fen, result, points in games:
        bucket = grouped.setdefault(initial_fen, {True: [], False: []})
        bucket[white == "Challenger"].append(points)
    pentanomial = [0, 0, 0, 0, 0]
    for fen, by_color in grouped.items():
        white_challenger = by_color[True]
        black_challenger = by_color[False]
        if len(white_challenger) != len(black_challenger):
            raise MatchValidationError(
                "Pair did not reverse engine colors for opening FEN"
            )
        for a_points, b_points in zip(white_challenger, black_challenger):
            pentanomial[a_points + b_points] += 1
    wins = sum(g[4] == 2 for g in games)
    draws = sum(g[4] == 1 for g in games)
    losses = sum(g[4] == 0 for g in games)
    return MatchResult(wins, draws, losses, len(games), tuple(pentanomial))
