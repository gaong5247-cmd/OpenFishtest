"""Minimal shared PGN batch protocol for Fastchess workers.

This checks game headers, pairing, and reported result accounting. It does NOT
validate move legality, engine provenance or trusted hardware execution.
"""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

MAX_PGN_BYTES = 2_000_000
HEADER_RE = re.compile(r'^\[([A-Za-z][A-Za-z0-9_]*)\s+"((?:\\.|[^"\\])*)"\]\s*$')


class MatchValidationError(ValueError):
    """PGN batch does not meet the expected protocol."""


@dataclass(frozen=True)
class MatchResult:
    wins: int
    draws: int
    losses: int
    games: int


def sha256_path(filename: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(filename).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_pgn_results(pgn: bytes, expected_games: int) -> MatchResult:
    """Count challenger results in complete paired Fastchess PGNs.

    Names MUST be the canonical Fastchess names 'Challenger' and 'Stockless'.
    Each consecutive pair must swap colors and start from the same FEN when
    a FEN tag is present. This is metadata validation, not proof of fair play.
    """
    if not pgn or len(pgn) > MAX_PGN_BYTES:
        raise MatchValidationError("Missing PGN or PGN exceeds 2 MB")
    if expected_games < 2 or expected_games % 2:
        raise MatchValidationError("Expected games must be positive and even")
    try:
        data = pgn.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MatchValidationError("PGN must be UTF-8 text") from exc
    games: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in data.splitlines():
        match = HEADER_RE.fullmatch(line.strip())
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if key == "Event":
            if current is not None:
                games.append(current)
            current = {}
        if current is not None:
            if key in current:
                raise MatchValidationError(f"Duplicate PGN header: {key}")
            current[key] = value

    if current is not None:
        games.append(current)
    if len(games) != expected_games:
        raise MatchValidationError(
            f"Expected {expected_games} PGN games, found {len(games)}"
        )

    wins = draws = losses = 0
    for idx, game in enumerate(games):
        white = game.get("White")
        black = game.get("Black")
        result = game.get("Result")
        if {white, black} != {"Challenger", "Stockless"}:
            raise MatchValidationError(
                "Game must contain precisely Challenger vs Stockless"
            )
        if result not in ("1-0", "0-1", "1/2-1/2"):
            raise MatchValidationError(f"Invalid result in game {idx + 1}")
        if idx % 2 == 1:
            previous = games[idx - 1]
            if white == previous["White"]:
                raise MatchValidationError("Pair did not reverse engine colors")
            if game.get("FEN") != previous.get("FEN"):
                raise MatchValidationError("Both games in pair must share the opening FEN")
        if result == "1/2-1/2":
            draws += 1
        elif (result == "1-0" and white == "Challenger") or (
            result == "0-1" and black == "Challenger"
        ):
            wins += 1
        else:
            losses += 1
    return MatchResult(wins, draws, losses, len(games))
