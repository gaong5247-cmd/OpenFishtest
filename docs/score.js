/* OpenFishtest public score calculations.
 *
 * A match's points ALWAYS mean W + D/2, with maximum = GAMES (not 100).
 * The percent score normalizes different match lengths to a common 0–100%.
 * A 55% screening threshold corresponds to 55/100 or 110/200 points.
 *
 * Elo difference is an exploratory logistic score conversion:
 *   ΔElo = 400 log10(p/(1-p)), where p = points/games.
 * It is NOT a certified rating, SPRT, or proof of engine identity.
 * Confidence intervals below are paired-score Gaussian APPROXIMATIONS only.
 */
(function (root) {
  "use strict";
  const TARGET_PERCENT = 55;
  const PENTA_SCORES = [0, 0.25, 0.5, 0.75, 1];
  const MAX_SAFE_GAMES = 1_000_000;

  function isCount(value) {
    return typeof value === "number" &&
      Number.isSafeInteger(value) &&
      value >= 0 && value <= MAX_SAFE_GAMES;
  }

  function calculate(wins, draws, losses, pentanomial) {
    if (![wins, draws, losses].every(isCount)) return null;
    const games = wins + draws + losses;
    if (games <= 0 || games > MAX_SAFE_GAMES) return null;

    // Use integer half-points internally: avoids incorrect "55 points"
    // qualification on 200-game test records.
    const halfPoints = 2 * wins + draws;
    const points = halfPoints / 2;
    const rate = halfPoints / (2 * games);
    const scorePercent = rate * 100;
    const qualifyingPoints = 0.55 * games;
    const passedScreen = halfPoints * 10 >= games * 11;

    let estimatedElo = null;
    if (games >= 20 && rate > 0 && rate < 1) {
      estimatedElo = 400 * Math.log10(rate / (1 - rate));
    }

    let confidence = null;
    const pent = pentanomial;
    const pairs = games / 2;
    if (
      games % 2 === 0 &&
      Array.isArray(pent) && pent.length === 5 &&
      pent.every(isCount) && pent.reduce((a, b) => a + b, 0) === pairs &&
      pairs >= 30
    ) {
      const mean = pent.reduce(
        (sum, count, i) => sum + count * PENTA_SCORES[i], 0
      ) / pairs;
      if (Math.abs(mean - rate) <= 1e-9) {
        const variance = pent.reduce(
          (sum, count, i) => sum + count * (PENTA_SCORES[i] - mean) ** 2, 0
        ) / (pairs - 1);
        const margin = 1.96 * Math.sqrt(variance / pairs);
        confidence = {
          lowPercent: 100 * Math.max(0, mean - margin),
          highPercent: 100 * Math.min(1, mean + margin),
          method: "paired_score_normal_approximation"
        };
      }
    }

    return {
      wins, draws, losses, games,
      halfPoints, points, scorePercent,
      perHundred: scorePercent,
      qualifyingPoints, targetPercent: TARGET_PERCENT,
      passedScreen, estimatedElo, confidence,
      verifiedOrigin: false
    };
  }

  function entryScore(entry) {
    if (!entry || typeof entry !== "object") return null;
    const scored = calculate(
      entry.wins, entry.draws, entry.losses, entry.penta
    );
    if (!scored) return null;
    if (entry.games !== scored.games) return null;
    if (
      entry.points !== undefined && entry.points !== null &&
      (typeof entry.points !== "number" ||
       Math.abs(scored.points - entry.points) > 0.000001)
    ) return null;
    return scored;
  }

  function validEntries(source) {
    const entries = Array.isArray(source?.entries) ? source.entries : [];
    const seenIds = new Set();
    const seenPgnHashes = new Set();
    return entries.filter(entry => {
      if (!/^[0-9a-f]{12,40}$/.test(String(entry?.id || ""))) return false;
      const scored = entryScore(entry);
      if (!scored) return false;
      if (seenIds.has(entry.id)) return false;
      seenIds.add(entry.id);
      const digest = entry.pgn_sha256;
      if (typeof digest === "string" && /^[a-f0-9]{64}$/.test(digest)) {
        if (seenPgnHashes.has(digest)) return false;
        seenPgnHashes.add(digest);
      }
      return true;
    }).sort((a, b) => (
      (Date.parse(b.submitted_at || "") || 0) -
      (Date.parse(a.submitted_at || "") || 0)
    ));
  }

  function summarize(entries) {
    const source = Array.isArray(entries) ? entries : [];
    let games = 0;
    let points = 0;
    const authors = new Set();
    for (const entry of source) {
      const scored = entryScore(entry);
      if (!scored) continue;
      games += scored.games;
      points += scored.points;
      if (typeof entry.contributor === "string" && entry.contributor.trim()) {
        authors.add(entry.contributor.toLowerCase());
      }
    }
    return {
      submissions: source.length,
      games,
      points,
      contributors: authors.size
      // We intentionally do not aggregate an "overall Elo": contributor
      // submissions can test DIFFERENT builds, time controls and hardware.
    };
  }

  const api = Object.freeze({
    TARGET_PERCENT, calculate, entryScore, validEntries, summarize
  });
  root.OpenFishtestScores = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
