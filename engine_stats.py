"""Transparent *approximate* Elo intervals and paired Gaussian SPRT.

Stockfish Fishtest uses more sophisticated GSPRT/pentanomial methods; this
module deliberately labels its confidence intervals and sequential tests as
exploratory rather than claiming equivalence to official Fishtest statistics.
"""
import math
from typing import Iterable

Z_95 = 1.959963984540054
ALPHA = BETA = 0.05
PENTA_SCORES = (0.0, 0.25, 0.5, 0.75, 1.0)


def probability(elo: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-elo / 400.0))


def elo_for(score: float) -> float:
    return 400.0 * math.log10(score / (1.0 - score))


def _elo_safe(score: float) -> float:
    return elo_for(min(1.0 - 1e-9, max(1e-9, score)))


def _wilson(score: float, n: int):
    """Wilson score interval; treats draws as fractional successes.

    This is an approximation, *not* a 95% CI under a proper trinomial model.
    """
    z2 = Z_95 * Z_95
    denom = 1 + z2 / n
    centre = (score + z2 / (2 * n)) / denom
    half = Z_95 * math.sqrt(score * (1 - score) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def analyze(wins: int, draws: int, losses: int,
            penta: Iterable[int] | None = None,
            elo0: float = 0.0, elo1: float = 5.0) -> dict:
    """Estimates challenger Elo *difference* (relative to the reference).

    Paired outcomes are from 2 color-reversed games: each pair scores
    0, .25, .5, .75, or 1. This reduces opening noise when available.
    SPRT here uses a Gaussian log likelihood approximation for paired scores
    and should be interpreted as experimental, not certified GSPRT.
    """
    if min(wins, draws, losses) < 0:
        raise ValueError("Negative game count")
    if not math.isfinite(elo0) or not math.isfinite(elo1) or elo1 <= elo0:
        raise ValueError("Expected elo1 > elo0")
    n = wins + draws + losses
    result = {
        "games": n, "score": None, "elo_diff": None,
        "ci95_low": None, "ci95_high": None,
        "ci_method": "insufficient_data", "provisional": True,
        "penta": None, "pairs": 0,
        "sprt": {
            "method": "paired_gaussian_experimental",
            "status": "insufficient_data",
            "elo0": elo0, "elo1": elo1,
            "alpha": ALPHA, "beta": BETA,
            "llr": None, "lower": round(math.log(BETA / (1 - ALPHA)), 4),
            "upper": round(math.log((1 - BETA) / ALPHA), 4),
        },
    }
    if n == 0:
        return result
    score = (wins + 0.5 * draws) / n
    # Haldane/Jeffreys-style continuity correction at the two extremes.
    corrected = score if 0 < score < 1 else (wins + draws / 2 + 0.5) / (n + 1)
    result["score"] = round(score, 5)
    result["elo_diff"] = round(elo_for(corrected), 1)
    lo, hi = _wilson(score, n)
    result["ci95_low"] = round(_elo_safe(lo), 1)
    result["ci95_high"] = round(_elo_safe(hi), 1)
    result["ci_method"] = "wilson_fractional_draws_approx"

    counts = list(penta) if penta is not None else None
    if counts is None or len(counts) != 5 or any(
        not isinstance(x, int) or x < 0 for x in counts
    ):
        return result
    pairs = sum(counts)
    if pairs == 0 or pairs * 2 > n:
        return result
    result["penta"] = counts
    result["pairs"] = pairs
    mean = sum(x * y for x, y in zip(PENTA_SCORES, counts)) / pairs
    # Sample variance per opening pair, rather than per game.
    variance = (
        sum(y * (x - mean) ** 2 for x, y in zip(PENTA_SCORES, counts))
        / (pairs - 1) if pairs > 1 else 0.0
    )
    if pairs >= 30 and variance > 1e-10 and pairs * 2 == n:
        margin = Z_95 * math.sqrt(variance / pairs)
        result["ci95_low"] = round(_elo_safe(mean - margin), 1)
        result["ci95_high"] = round(_elo_safe(mean + margin), 1)
        result["ci_method"] = "paired_gaussian_approx"
    # No credible sequential inference with too few pairs or no variation.
    if pairs < 40 or variance < 1e-10 or pairs * 2 != n:
        return result

    p0, p1 = probability(elo0), probability(elo1)
    llr = pairs * (p1 - p0) * (mean - (p0 + p1) / 2) / variance
    lower = math.log(BETA / (1 - ALPHA))
    upper = math.log((1 - BETA) / ALPHA)
    if llr >= upper:
        status = "favor_h1"
    elif llr <= lower:
        status = "favor_h0"
    else:
        status = "continue"
    result["sprt"]["status"] = status
    result["sprt"]["llr"] = round(llr, 4)
    return result
