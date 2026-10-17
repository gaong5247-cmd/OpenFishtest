"""Read recent, actually submitted PGNs for safe public board replay.

Each item is derived from an existing worker job on local disk. No examples or
fabricated games are inserted in public snapshots. Output sizes are bounded.
"""
import io
from pathlib import Path

import chess.pgn

MAX_PUBLIC_GAMES = 8
MAX_PUBLIC_PLIES = 500
MAX_PGN_SOURCE = 400_000


def recent_games(connection, data_dir: Path, limit: int = MAX_PUBLIC_GAMES):
    limit = max(0, min(MAX_PUBLIC_GAMES, limit))
    if not limit:
        return []
    with connection() as db:
        rows = db.execute("""
            SELECT j.id, j.test_id, j.pgn_path, j.completed_at,
                   c.name AS challenger, c.version AS challenger_version,
                   s.name AS reference, s.version AS reference_version
            FROM jobs j JOIN tests t ON j.test_id=t.id
            JOIN engines c ON t.engine_id=c.id
            JOIN engines s ON t.reference_id=s.id
            WHERE j.status='done' AND j.pgn_path IS NOT NULL
            ORDER BY j.completed_at DESC, j.id DESC LIMIT 30
        """).fetchall()
    games = []
    root = data_dir.resolve()
    for row in rows:
        if len(games) >= limit:
            break
        try:
            file = (root / row["pgn_path"]).resolve()
            if not file.is_relative_to(root) or not file.is_file():
                continue
            if file.stat().st_size > MAX_PGN_SOURCE:
                continue
            content = file.read_text(encoding="utf-8-sig")
            source = io.StringIO(content)
            index = 0
            while len(games) < limit:
                game = chess.pgn.read_game(source)
                if game is None:
                    break
                if game.errors:
                    index += 1
                    continue
                board = game.board()
                positions = [board.fen(en_passant="fen")]
                san = []
                truncated = False
                for move in game.mainline_moves():
                    if len(san) >= MAX_PUBLIC_PLIES:
                        truncated = True
                        break
                    san.append(board.san(move))
                    board.push(move)
                    positions.append(board.fen(en_passant="fen"))
                if not san:
                    index += 1
                    continue
                # Each game is self-contained for offline replay and PGN download.
                game_text = str(game.accept(chess.pgn.StringExporter(
                    headers=True, variations=False, comments=False
                )))
                if len(game_text) > 24_000:
                    game_text = ""
                games.append({
                    "id": f"{row['test_id']}-{row['id']}-{index}",
                    "test_id": row["test_id"],
                    "job_id": row["id"],
                    "white": game.headers.get("White", "?"),
                    "black": game.headers.get("Black", "?"),
                    "challenger": row["challenger"],
                    "challenger_version": row["challenger_version"],
                    "reference": row["reference"],
                    "reference_version": row["reference_version"],
                    "result": game.headers.get("Result", "*"),
                    "round": game.headers.get("Round", "?"),
                    "date": game.headers.get("Date", "?"),
                    "played_at": row["completed_at"],
                    "moves_san": san,
                    "fens": positions,
                    "truncated": truncated,
                    "pgn": game_text,
                    "verified": False,
                })
                index += 1
        except (OSError, UnicodeError, ValueError):
            # Archived/unavailable PGNs are not invented or silently replaced.
            continue
    return games
