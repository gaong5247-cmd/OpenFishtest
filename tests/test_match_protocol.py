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

    different_fens = make_game("Challenger", "Stockless", "1-0", "FEN1") + make_game(
        "Stockless", "Challenger", "1-0", "FEN2"
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
