import pytest

from match_protocol import MatchValidationError, parse_pgn_results


def make_game(white, black, result, fen=None):
    headers = (
        '[Event "OpenFishtest"]\n'
        f'[White "{white}"]\n'
        f'[Black "{black}"]\n'
        f'[Result "{result}"]\n'
    )
    if fen:
        headers += f'[FEN "{fen}"]\n'
    return (headers + "\n1. e4 e5 " + result + "\n\n").encode()


def test_counts_challenger_wdl_by_color():
    pgn = make_game("Challenger", "Stockless", "1-0") + make_game(
        "Stockless", "Challenger", "0-1"
    )
    result = parse_pgn_results(pgn, 2)
    assert (result.wins, result.draws, result.losses, result.games) == (2, 0, 0, 2)


def test_rejects_unpaired_or_changed_opening():
    same_colors = make_game("Challenger", "Stockless", "1-0") * 2
    with pytest.raises(MatchValidationError, match="reverse"):
        parse_pgn_results(same_colors, 2)

    different_fens = make_game("Challenger", "Stockless", "1-0",
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1") + make_game(
        "Stockless", "Challenger", "1-0",
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 2"
    )
    with pytest.raises(MatchValidationError, match="FEN"):
        parse_pgn_results(different_fens, 2)


def test_rejects_result_and_count_errors():
    pgn = make_game("Challenger", "Stockless", "*") + make_game(
        "Stockless", "Challenger", "1/2-1/2"
    )
    with pytest.raises(MatchValidationError, match="Invalid result"):
        parse_pgn_results(pgn, 2)
    with pytest.raises(MatchValidationError, match="Expected 4"):
        parse_pgn_results(make_game("Challenger", "Stockless", "1-0"), 4)


def test_all_draws():
    pgn = make_game("Challenger", "Stockless", "1/2-1/2") + make_game(
        "Stockless", "Challenger", "1/2-1/2"
    )
    result = parse_pgn_results(pgn, 2)
    assert (result.wins, result.draws, result.losses) == (0, 2, 0)



def test_interleaved_concurrent_pgn_pairs():
    import chess
    board = chess.Board()
    board.push_san("d4")
    fen2 = board.fen()
    # Fastchess concurrency: games finish in non-paired order.
    pgn = (
        make_game("Challenger", "Stockless", "1-0")
        + make_game("Challenger", "Stockless", "1/2-1/2", fen2)
        + make_game("Stockless", "Challenger", "0-1")
        + make_game("Stockless", "Challenger", "1/2-1/2", fen2)
    )
    # The sample fixture starts each game with e4 e5, so the custom
    # d4 position cannot accept e4. Use two valid starting boards below.
    from io import StringIO
    import chess.pgn
    def game(white, black, result, fen):
        board = chess.Board(fen)
        first = next(iter(board.legal_moves))
        g = chess.pgn.Game()
        g.setup(board)
        g.headers["White"], g.headers["Black"], g.headers["Result"] = (
            white, black, result
        )
        g.add_variation(first)
        return str(g) + "\n\n"
    pgn = (
        game("Challenger","Stockless","1-0",chess.STARTING_FEN)
        + game("Challenger","Stockless","1/2-1/2",fen2)
        + game("Stockless","Challenger","0-1",chess.STARTING_FEN)
        + game("Stockless","Challenger","1/2-1/2",fen2)
    ).encode()
    result = parse_pgn_results(pgn, 4)
    assert (result.wins, result.draws, result.losses) == (2, 2, 0)
    assert result.penta == (0, 0, 1, 0, 1)


def test_interleaved_missing_reverse_color_is_rejected():
    pgn = (
        make_game("Challenger", "Stockless", "1-0") * 2
        + make_game("Stockless", "Challenger", "0-1")
        + make_game("Stockless", "Challenger", "1/2-1/2")
    )
    # Both colors exist for the same opening, so this is two legal pairs.
    assert parse_pgn_results(pgn, 4).games == 4
    with pytest.raises(MatchValidationError, match="reverse"):
        parse_pgn_results(make_game("Challenger","Stockless","1-0") * 4, 4)
