"""Data-only community PGN + EPD validation and canonicalization.

No executable/ZIP/script uploads and no implicit engine authentication.
Validated submissions may be auto-published independently of the official
trusted-worker or quarantined-challenger arena leaderboard.

One GitHub PR must add EXACTLY:
  submissions/<12-40 lowercase hex id>/games.pgn
  submissions/<same id>/openings.epd

GitHub PR files stay unmerged. Only sanitized PGN, EPD and bounded JSON
metadata are committed into the public GitHub Pages data directory.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass

import chess
import chess.pgn

from match_protocol import MatchValidationError, parse_pgn_results

MAX_COMMUNITY_PGN = 2_000_000
MAX_COMMUNITY_EPD = 512 * 1024
MAX_COMMUNITY_GAMES = 200
MAX_COMMUNITY_OPENINGS = 500
MAX_EPD_LINE = 4096
SUBMISSION_ID = re.compile(r"^[0-9a-f]{12,40}$")
SUBMISSION_PATH = re.compile(
    r"^submissions/([0-9a-f]{12,40})/(games\.pgn|openings\.epd)$"
)


class InvalidCommunitySubmission(ValueError):
    """A source file violates the data-only community publication policy."""


@dataclass(frozen=True)
class CommunityReport:
    games: int
    wins: int
    draws: int
    losses: int
    penta: tuple[int, int, int, int, int]
    pairs: int
    epd_positions: int
    opening_start: int
    pgn: bytes
    epd: bytes
    pgn_sha256: str
    epd_sha256: str

    def public_metadata(self, contribution_id: str, submitter: str, timestamp: str):
        return {
            "id": contribution_id,
            "contributor": submitter,
            "submitted_at": timestamp,
            "games": self.games,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "points": self.wins + self.draws / 2,
            "penta": list(self.penta),
            "pairs": self.pairs,
            "book_positions": self.epd_positions,
            "book_pair_offset": self.opening_start,
            "pgn_sha256": self.pgn_sha256,
            "epd_sha256": self.epd_sha256,
            "verified": False,
            "verification": "legal_pgn_and_openings_only_engine_execution_unverified",
        }


def check_pr_paths(changes: list[dict]) -> str:
    """Reject ALL changes except two new PGN/EPD data files in one ID folder."""
    if len(changes) != 2:
        raise InvalidCommunitySubmission("PR must add exactly two data files: games.pgn and openings.epd")
    identifiers = set()
    suffixes = set()
    for file in changes:
        name = file.get("filename", "")
        match = SUBMISSION_PATH.fullmatch(name)
        if not match:
            raise InvalidCommunitySubmission(
                "Only submissions/<id>/games.pgn and openings.epd are allowed"
            )
        if file.get("status") != "added":
            raise InvalidCommunitySubmission("Only new, immutable PGN/EPD files are accepted")
        size = file.get("size")
        if size is not None and (
            not isinstance(size, int) or size > max(MAX_COMMUNITY_PGN, MAX_COMMUNITY_EPD)
        ):
            raise InvalidCommunitySubmission("GitHub file exceeds source size quota")
        if not re.fullmatch(r"[0-9a-f]{40}", file.get("sha", "")):
            raise InvalidCommunitySubmission("Invalid Git blob identity")
        identifiers.add(match.group(1))
        suffixes.add(match.group(2))
    if len(identifiers) != 1 or suffixes != {"games.pgn", "openings.epd"}:
        raise InvalidCommunitySubmission("Both source files must use exactly the same submission ID")
    return identifiers.pop()


def _read_epd(payload: bytes):
    if not 0 < len(payload) <= MAX_COMMUNITY_EPD:
        raise InvalidCommunitySubmission("EPD must be nonempty and <=512 KiB")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeError as exc:
        raise InvalidCommunitySubmission("EPD must be UTF-8 text") from exc
    positions = []
    seen = set()
    for number, line in enumerate(text.splitlines(), 1):
        if len(line) > MAX_EPD_LINE:
            raise InvalidCommunitySubmission("An EPD line exceeds 4096 characters")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(positions) >= MAX_COMMUNITY_OPENINGS:
            raise InvalidCommunitySubmission("EPD must contain at most 500 positions")
        try:
            board = chess.Board()
            board.set_epd(line)
            if not board.is_valid() or board.is_game_over(claim_draw=True):
                raise ValueError("Illegal/terminal position")
        except (ValueError, TypeError, OverflowError) as exc:
            raise InvalidCommunitySubmission(f"Invalid opening EPD at line {number}") from exc
        fen = board.fen(en_passant="fen")
        if fen in seen:
            raise InvalidCommunitySubmission("Duplicate opening position in EPD")
        seen.add(fen)
        positions.append((fen, board.epd(en_passant="fen")))
    if not positions:
        raise InvalidCommunitySubmission("EPD contains no legal chess openings")
    return positions


def validate_pair(payload_pgn: bytes, payload_epd: bytes) -> CommunityReport:
    if not 0 < len(payload_pgn) <= MAX_COMMUNITY_PGN:
        raise InvalidCommunitySubmission("PGN must be nonempty and <=2 MB")

    try:
        source = io.StringIO(payload_pgn.decode("utf-8-sig"))
    except UnicodeError as exc:
        raise InvalidCommunitySubmission("PGN must be UTF-8 text") from exc

    raw_games = []
    recorded_fens = []
    while len(raw_games) <= MAX_COMMUNITY_GAMES:
        try:
            game = chess.pgn.read_game(source)
        except (ValueError, chess.InvalidMoveError, UnicodeError) as exc:
            raise InvalidCommunitySubmission("Cannot parse legal PGN") from exc
        if game is None:
            break
        if game.errors:
            raise InvalidCommunitySubmission("PGN contains illegal chess moves")
        raw_games.append(game)
        recorded_fens.append(game.board().fen(en_passant="fen"))
    if not 2 <= len(raw_games) <= MAX_COMMUNITY_GAMES or len(raw_games) % 2:
        raise InvalidCommunitySubmission("PGN must contain 2-200 even-numbered color-paired games")

    try:
        results = parse_pgn_results(payload_pgn, len(raw_games))
    except MatchValidationError as exc:
        raise InvalidCommunitySubmission(str(exc)) from exc

    openings = _read_epd(payload_epd)
    pairs = len(raw_games) // 2
    if len(openings) < pairs:
        raise InvalidCommunitySubmission("EPD has fewer opening positions than PGN pairs")
    pairs_fen = [recorded_fens[i] for i in range(0, len(raw_games), 2)]
    epd_fen = [opening[0] for opening in openings]
    # A partial worker batch can use a contiguous subset of a larger book.
    index = next((
        offset for offset in range(len(openings) - pairs + 1)
        if epd_fen[offset:offset + pairs] == pairs_fen
    ), None)
    if index is None:
        raise InvalidCommunitySubmission("PGN starting FEN pairs do not match contiguous EPD openings")

    # Reconstruct a canonical, comment-free PGN: no user-provided comments,
    # event metadata, URLs, variants or instructions are carried forward.
    published_games = []
    for i, raw in enumerate(raw_games, 1):
        board = raw.board()
        safe = chess.pgn.Game()
        safe.headers["Event"] = "OpenFishtest Community"
        safe.headers["White"] = raw.headers["White"]
        safe.headers["Black"] = raw.headers["Black"]
        safe.headers["Round"] = str(i)
        safe.headers["Result"] = raw.headers["Result"]
        if board.fen(en_passant="fen") != chess.STARTING_FEN:
            safe.setup(board)
        node = safe
        for move in raw.mainline_moves():
            node = node.add_main_variation(move)
        published_games.append(safe.accept(chess.pgn.StringExporter(
            headers=True, variations=False, comments=False
        )))
    canonical_pgn = ("\n\n".join(published_games) + "\n").encode("utf-8")
    canonical_epd = ("\n".join(line for _, line in openings) + "\n").encode("utf-8")
    if len(canonical_pgn) > MAX_COMMUNITY_PGN or len(canonical_epd) > MAX_COMMUNITY_EPD:
        raise InvalidCommunitySubmission("Canonical result exceeds publication size quota")
    return CommunityReport(
        games=len(raw_games), wins=results.wins, draws=results.draws,
        losses=results.losses, penta=results.penta, pairs=pairs,
        epd_positions=len(openings), opening_start=index,
        pgn=canonical_pgn, epd=canonical_epd,
        pgn_sha256=hashlib.sha256(canonical_pgn).hexdigest(),
        epd_sha256=hashlib.sha256(canonical_epd).hexdigest()
    )
