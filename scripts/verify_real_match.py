"""Validate genuine Fastchess PGN and output a reproducible JSON report.

This script reads files produced by actual engines. It never creates mock
results, and a 2-game smoke test is never described as meaningful Elo.
"""
import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.pgn

from arena_core import GAMES, classify_score
from match_protocol import parse_pgn_results


def verify_opening_book(pgn_bytes: bytes, book_file: Path, games: int):
    positions = []
    for line in book_file.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        board = chess.Board()
        board.set_epd(line)
        positions.append(board.fen(en_passant="fen"))
        if len(positions) == games // 2:
            break
    if len(positions) != games // 2:
        raise ValueError("EPD does not contain enough paired opening positions")

    source = io.StringIO(pgn_bytes.decode("utf-8-sig"))
    for i in range(games):
        game = chess.pgn.read_game(source)
        if game is None or game.errors:
            raise ValueError(f"Missing/illegal PGN opening #{i + 1}")
        position = game.board().fen(en_passant="fen")
        if position != positions[i // 2]:
            raise ValueError(f"PGN game #{i + 1} diverged from book opening")
    if chess.pgn.read_game(source) is not None:
        raise ValueError("Extra games beyond requested opening pairs")


def make_report(pgn: Path, book: Path, games: int,
                challenger_sha256: str, reference_sha256: str, tc: str):
    if games < 2 or games % 2:
        raise ValueError("Expected a positive even number of games")
    if pgn.stat().st_size > 2_000_000:
        raise ValueError("PGN exceeds the current parser's 2MB maximum")
    raw = pgn.read_bytes()
    results = parse_pgn_results(raw, games)
    verify_opening_book(raw, book, games)
    report = {
        "type": "verified_pgn_legal_moves_not_authenticated_engine_origin",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Fastchess real UCI match on GitHub Actions",
        "games": games, "time_control": tc,
        "opening_book_sha256": hashlib.sha256(book.read_bytes()).hexdigest(),
        "reference": {"engine": "Stockless", "executable_sha256": reference_sha256},
        "challenger": {"engine": "Stockfish", "executable_sha256": challenger_sha256},
        "wins": results.wins, "draws": results.draws,
        "losses": results.losses, "penta": list(results.penta),
        "score": results.wins + 0.5 * results.draws,
        "pgn_sha256": hashlib.sha256(raw).hexdigest(),
        "confidence": "None: worker results require independent reproduction",
        "classification": "smoke_only" if games < GAMES else "100_game_screening",
        "qualifies_under_arena_rule": (
            classify_score(results.wins, results.draws, results.losses)["passed"]
            if games == GAMES else None
        ),
        "note": "Scoring is from the challenger's perspective; no fabricated PGNs."
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pgn", type=Path, required=True)
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--tc", required=True)
    parser.add_argument("--reference-sha256", required=True)
    parser.add_argument("--challenger-sha256", required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    report = make_report(
        args.pgn, args.book, args.games,
        args.challenger_sha256, args.reference_sha256, args.tc
    )
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
