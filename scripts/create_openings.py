"""Deterministic, legal 50-position EPD book for smoke/benchmark infrastructure.

A generated opening book is not necessarily competition-quality. For serious
ratings, replace with a published, curated, licensed, balanced book and pin
its SHA-256 for EVERY tested build. This utility is reproducible and offline.
"""
import argparse
import hashlib
import random
from pathlib import Path

import chess

# SAN move sequences from common human opening families. The script varies
# plies in reproducible legal positions; no evaluation-engine feedback is used.
FAMILIES = [
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6",
    "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6",
    "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6",
    "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6",
    "e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nc6",
    "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7",
    "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Nd7",
    "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6",
    "e4 Nf6 e5 Nd5 d4 d6 Nf3 g6",
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7",
    "d4 d5 c4 c6 Nf3 Nf6 Nc3 e6",
    "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6",
    "d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5",
    "d4 f5 c4 Nf6 Nc3 e6 Nf3 d5",
    "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5",
    "c4 c5 Nc3 Nc6 Nf3 Nf6 g3 g6",
    "c4 Nf6 Nc3 e6 Nf3 d5 d4 Be7",
    "Nf3 d5 d4 Nf6 c4 e6 Nc3 Be7",
    "Nf3 Nf6 g3 d5 Bg2 c6 O-O Bg4",
    "g3 d5 Bg2 Nf6 d3 e5 Nf3 Nc6",
    "b3 e5 Bb2 Nc6 e3 d5 Nf3 Bd6",
    "e4 e5 Nc3 Nf6 f4 d5 fxe5 Nxe4",
    "d4 d5 Bf4 Nf6 e3 c5 Nf3 Nc6"
]


def generate_positions(count=50, seed=20261018):
    rng = random.Random(seed)
    records = []
    seen = set()
    for attempt in range(count * 200):
        board = chess.Board()
        family = FAMILIES[attempt % len(FAMILIES)].split()
        max_plies = rng.choice([4, 5, 6, 7, 8])
        try:
            for san in family[:max_plies]:
                board.push_san(san)
        except ValueError:
            continue
        # Occasionally extend with one deterministic, legal, non-capturing
        # human-like development or center pawn move to diversify openings.
        if attempt % 4 == 0 and board.legal_moves.count() > 0:
            extras = [m for m in board.legal_moves
                      if not board.is_capture(m) and not board.gives_check(m)]
            if extras:
                moves = sorted(extras, key=board.san)
                board.push(rng.choice(moves))
        if not board.is_valid() or board.is_game_over(claim_draw=True):
            continue
        fen = board.fen(en_passant="fen")
        if fen in seen:
            continue
        seen.add(fen)
        records.append(board.epd())
        if len(records) >= count:
            return records
    raise RuntimeError("Unable to generate enough unique legal chess openings")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args(argv)
    if args.count < 1 or args.count > 500:
        parser.error("--count must be 1..500")
    data = "\n".join(generate_positions(args.count)) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(data, encoding="utf-8", newline="\n")
    print(f"Generated {args.count} legal openings: {args.output}")
    print(f"SHA-256: {hashlib.sha256(data.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
