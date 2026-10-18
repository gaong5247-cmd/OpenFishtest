/* OpenFishtest: GitHub Pages-only Contributor dashboard.
 * Real data source: ./data/community/index.json, published by trusted
 * GitHub Actions from canonicalized PGN/EPD. No backend or secret required.
 */
"use strict";
(function () {
  const $ = id => document.getElementById(id);
  const scores = window.OpenFishtestScores;
  const dictionaries = window.OPENFISHTEST_LOCALES || {};
  if (!scores) throw new Error("Score module failed to load");

  const INDEX_URL = "./data/community/index.json";
  const ROOT_DATA_URL = "./data/community/";
  const GH_PR_BASE = "https://github.com/gaong5247-cmd/OpenFishtest/pull/";
  let locale = initialLocale();
  let entries = [];
  let state = "loading"; // loading, ready, error
  let lastUpdate = null;
  let filterText = "";
  let sortMode = "recent";
  let calculatorTouched = false;

  function initialLocale() {
    try {
      const saved = localStorage.getItem("openfishtest-language");
      if (saved === "ko" || saved === "en") return saved;
    } catch (_) {}
    return (navigator.language || "").toLowerCase().startsWith("ko") ?
      "ko" : "en";
  }

  function t(key) {
    return dictionaries[locale]?.[key] || dictionaries.en?.[key] || key;
  }

  function put(id, value) {
    const node = $(id);
    if (node) node.textContent = String(value);
  }

  function formatNumber(n) {
    return new Intl.NumberFormat(
      locale === "ko" ? "ko-KR" : "en-US",
      {maximumFractionDigits: 0}
    ).format(n);
  }

  function formatPoints(n) {
    return new Intl.NumberFormat(
      locale === "ko" ? "ko-KR" : "en-US",
      {minimumFractionDigits: 0, maximumFractionDigits: 1}
    ).format(n);
  }

  function formatPercent(n) {
    if (typeof n !== "number" || !Number.isFinite(n)) return "—";
    return new Intl.NumberFormat(
      locale === "ko" ? "ko-KR" : "en-US",
      {minimumFractionDigits: 1, maximumFractionDigits: 2}
    ).format(n) + "%";
  }

  function formatDate(value) {
    const timestamp = Date.parse(value || "");
    if (!Number.isFinite(timestamp)) return "—";
    return new Intl.DateTimeFormat(
      locale === "ko" ? "ko-KR" : "en-US",
      {year: "numeric", month: "short", day: "numeric",
       hour: "2-digit", minute: "2-digit"}
    ).format(new Date(timestamp));
  }

  function formatElo(n) {
    if (typeof n !== "number" || !Number.isFinite(n)) return t("calc_elo_unavailable");
    const rounded = Math.round(n);
    return (rounded > 0 ? "+" : rounded < 0 ? "−" : "±") +
      formatNumber(Math.abs(rounded));
  }

  function applyTranslations() {
    document.documentElement.lang = locale;
    $("lang-switch").textContent = locale === "ko" ? "English" : "한국어";
    document.querySelectorAll("[data-i18n]").forEach(node => {
      node.textContent = t(node.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(node => {
      node.placeholder = t(node.dataset.i18nPlaceholder);
    });
  }

  function node(tag, value, className = "") {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (value != null) result.textContent = String(value);
    return result;
  }

  function makeCell(row, value, className = "") {
    const td = node("td", value, className);
    row.append(td);
    return td;
  }

  function emptyTable(message) {
    const body = $("results-rows");
    body.replaceChildren();
    const row = node("tr");
    const td = makeCell(row, message, "empty-row");
    td.colSpan = 7;
    body.append(row);
  }

  function communityFiles(entry, container) {
    for (const [filename, name] of [
      ["games.pgn", "data_pgn"], ["openings.epd", "data_epd"]
    ]) {
      const a = node("a", t(name));
      // Entry IDs have already passed strict allowlist validation.
      a.href = ROOT_DATA_URL + entry.id + "/" + filename;
      a.download = filename;
      a.rel = "noopener noreferrer";
      container.append(a);
    }
  }

  function renderStats() {
    const summary = scores.summarize(entries);
    put("stat-submissions", formatNumber(summary.submissions));
    put("stat-games", formatNumber(summary.games));
    put("stat-contributors", formatNumber(summary.contributors));
    const latest = entries.length ? scores.entryScore(entries[0]) : null;
    put("stat-latest", latest ? formatPercent(latest.scorePercent) : "—");
    put("last-updated", state === "error" ?
      t("activity_unavailable") :
      lastUpdate ? t("activity_updated") + ": " + formatDate(lastUpdate) :
      t("activity_loading"));
  }

  function renderFeatured() {
    const latest = entries[0];
    const wrapper = $("featured-match");
    if (!latest) {
      wrapper.hidden = true;
      return;
    }
    const result = scores.entryScore(latest);
    if (!result) {
      wrapper.hidden = true;
      return;
    }
    wrapper.hidden = false;
    put("featured-title", t("featured_match"));
    put(
      "featured-byline",
      t("featured_byline") + " " + String(latest.contributor || "Unknown") +
      " · " + formatDate(latest.submitted_at)
    );
    $("featured-pgn").href = ROOT_DATA_URL + latest.id + "/games.pgn";
    $("featured-pgn").download = "games.pgn";
    put("featured-percent", formatPercent(result.scorePercent));
    put(
      "featured-points",
      formatPoints(result.points) + " / " +
      formatNumber(result.games) + " " + t("featured_points").split("/")[0].trim()
    );
    put("featured-check", t(result.passedScreen ?
      "featured_screen_above" : "featured_screen_below"));
    put("featured-count", formatNumber(result.games) + " " + t("featured_count"));
    put("featured-wins", formatNumber(result.wins));
    put("featured-draws", formatNumber(result.draws));
    put("featured-losses", formatNumber(result.losses));
    $("track-wins").style.width = (100 * result.wins / result.games) + "%";
    $("track-draws").style.width = (100 * result.draws / result.games) + "%";
    $("track-losses").style.width = (100 * result.losses / result.games) + "%";
    $("outcome-track").setAttribute(
      "aria-label", result.wins + " " + t("outcome_wins") +
      ", " + result.draws + " " + t("outcome_draws") +
      ", " + result.losses + " " + t("outcome_losses")
    );
    put("featured-per100", formatPoints(result.perHundred) + " / 100");
    put("featured-elo", formatElo(result.estimatedElo));
    const ci = result.confidence;
    put("featured-ci", ci ?
      formatPercent(ci.lowPercent) + " – " + formatPercent(ci.highPercent) :
      t("featured_ci_unavailable"));
  }

  function dataTimestamp(entry) {
    return Date.parse(entry.submitted_at || "") || 0;
  }

  function renderTable() {
    const body = $("results-rows");
    body.replaceChildren();
    if (state === "error" && entries.length === 0) {
      return emptyTable(t("table_unavailable"));
    }
    if (entries.length === 0) {
      return emptyTable(t("table_empty"));
    }
    const matching = entries.filter(item => {
      const target = (
        String(item.contributor || "") + " " +
        String(item.source_pr ?? "") + " " + item.id
      ).toLowerCase();
      return target.includes(filterText);
    });
    matching.sort((a, b) => {
      if (sortMode === "score") {
        const diff = scores.entryScore(b).scorePercent -
                     scores.entryScore(a).scorePercent;
        if (Math.abs(diff) > 1e-9) return diff;
      }
      if (sortMode === "games") {
        const diff = b.games - a.games;
        if (diff) return diff;
      }
      return dataTimestamp(b) - dataTimestamp(a);
    });
    if (!matching.length) return emptyTable(t("table_no_match"));

    for (const item of matching.slice(0, 100)) {
      const stats = scores.entryScore(item);
      if (!stats) continue;
      const row = node("tr");
      const first = makeCell(row, null);
      first.append(node(
        "div", item.contributor || "Unknown", "td-primary"
      ));
      const line = node(
        "div",
        formatDate(item.submitted_at) +
        (Number.isSafeInteger(item.source_pr) ? " · PR #" + item.source_pr : ""),
        "td-sub"
      );
      first.append(line);
      makeCell(row, formatNumber(stats.games), "td-mono");
      makeCell(
        row,
        [stats.wins, stats.draws, stats.losses].map(formatNumber).join(" / "),
        "td-mono"
      );
      makeCell(
        row,
        formatPoints(stats.points) + " / " + formatNumber(stats.games),
        "td-mono"
      );
      const scoreCell = makeCell(row, null);
      const scoreButton = node(
        "button", formatPercent(stats.scorePercent), "score-button"
      );
      scoreButton.type = "button";
      scoreButton.title = t("calc_title");
      scoreButton.addEventListener("click", () => {
        setCalculator(stats);
        $("score").scrollIntoView({behavior: "smooth", block: "start"});
      });
      scoreCell.append(scoreButton);
      const elo = makeCell(row, formatElo(stats.estimatedElo), "td-mono");
      if (stats.estimatedElo !== null) {
        elo.classList.add(stats.estimatedElo >= 0 ? "elo-positive" : "elo-negative");
      }
      const downloadCell = makeCell(row, null, "data-links");
      communityFiles(item, downloadCell);
      body.append(row);
    }
  }

  function intInput(id) {
    const value = $(id).value.trim();
    if (!/^(0|[1-9][0-9]{0,6})$/.test(value)) return null;
    return Number(value);
  }

  function renderCalculator() {
    const wins = intInput("calc-wins");
    const draws = intInput("calc-draws");
    const losses = intInput("calc-losses");
    const computed = scores.calculate(wins, draws, losses);
    $("calc-error").hidden = Boolean(computed);
    if (!computed) {
      put("calc-error", t("calc_invalid"));
      for (const name of [
        "calc-points", "calc-rate", "calc-per100", "calc-target", "calc-elo"
      ]) put(name, "—");
      put("calc-verdict", "—");
      return;
    }
    put(
      "calc-points",
      formatPoints(computed.points) + " / " + formatNumber(computed.games)
    );
    put("calc-rate", formatPercent(computed.scorePercent));
    put("calc-per100", formatPoints(computed.perHundred) + " / 100");
    // In practice points advance by .5: round required 55% score upwards
    // to the next reachable half-point, including odd game counts.
    const required = Math.ceil(
      computed.qualifyingPoints * 2 - 1e-9
    ) / 2;
    put(
      "calc-target",
      formatPoints(required) + " / " + formatNumber(computed.games)
    );
    put("calc-elo", formatElo(computed.estimatedElo));
    put("calc-verdict", t(computed.passedScreen ?
      "calc_above" : "calc_below"));
    $("calc-verdict").classList.toggle("below", !computed.passedScreen);
  }

  function setCalculator(stats) {
    put("calc-wins", stats.wins);
    put("calc-draws", stats.draws);
    put("calc-losses", stats.losses);
    calculatorTouched = true;
    renderCalculator();
  }

  function renderAll() {
    applyTranslations();
    renderStats();
    renderFeatured();
    renderTable();
    if (entries.length && !calculatorTouched) {
      const latest = scores.entryScore(entries[0]);
      if (latest) setCalculator(latest);
    } else {
      renderCalculator();
    }
  }

  async function refresh() {
    const button = $("refresh-button");
    button.disabled = true;
    try {
      const response = await fetch(INDEX_URL, {cache: "no-store"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      const index = await response.json();
      if (!index || !Array.isArray(index.entries)) {
        throw new Error("Unsupported index structure");
      }
      entries = scores.validEntries(index).slice(0, 200);
      lastUpdate = index.updated_at || null;
      state = "ready";
    } catch (error) {
      state = "error";
      // Keep previously loaded records if the user loses their connection.
      if (entries.length === 0) lastUpdate = null;
    } finally {
      renderAll();
      button.disabled = false;
    }
  }

  function bind() {
    $("lang-switch").addEventListener("click", () => {
      locale = locale === "ko" ? "en" : "ko";
      try {
        localStorage.setItem("openfishtest-language", locale);
      } catch (_) {}
      renderAll();
    });
    $("refresh-button").addEventListener("click", () => {
      void refresh();
    });
    $("result-search").addEventListener("input", event => {
      filterText = event.target.value.toLowerCase().trim();
      renderTable();
    });
    $("result-sort").addEventListener("change", event => {
      sortMode = event.target.value;
      renderTable();
    });
    for (const name of ["calc-wins", "calc-draws", "calc-losses"]) {
      $(name).addEventListener("input", () => {
        calculatorTouched = true;
        renderCalculator();
      });
    }
    $("reset-calculator").addEventListener("click", () => {
      calculatorTouched = false;
      const latest = entries.length ? scores.entryScore(entries[0]) : null;
      if (latest) {
        setCalculator(latest);
      } else {
        for (const name of ["calc-wins", "calc-draws", "calc-losses"]) {
          $(name).value = "";
        }
        renderCalculator();
      }
    });
    renderAll();
    void refresh();
    setInterval(() => void refresh(), 90_000);
  }

  bind();
})();
