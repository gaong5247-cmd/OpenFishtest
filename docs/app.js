// OpenFishtest public-only application. No admin or worker secrets here.
// All user-generated text is inserted with textContent (never innerHTML).
"use strict";

const $ = id => document.getElementById(id);
const dictionaries = window.OPENFISHTEST_LOCALES || {en: {}};
const getSavedLanguage = () => {
  try {
    const saved = localStorage.getItem("openfishtest-language");
    if (saved === "ko" || saved === "en") return saved;
  } catch (_) {}
  return (navigator.language || "").toLowerCase().startsWith("ko") ? "ko" : "en";
};
let language = getSavedLanguage();
const translate = key => dictionaries[language]?.[key] || dictionaries.en?.[key] || key;
const formatCount = value => Number(value || 0).toLocaleString(language === "ko" ? "ko-KR" : "en-US");
const setText = (id, value) => { if ($(id)) $(id).textContent = value; };

let current = null;
let connectedRemotely = false;
let activeFilter = "all";
let searchText = "";
let gameIndex = 0;
let moveIndex = 0;
let boardFlipped = false;
const PIECES = {
  K:"♔", Q:"♕", R:"♖", B:"♗", N:"♘", P:"♙",
  k:"♚", q:"♛", r:"♜", b:"♝", n:"♞", p:"♟"
};

function translateStatic() {
  document.documentElement.lang = language;
  document.querySelectorAll("[data-i18n]").forEach(node => {
    node.textContent = translate(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(node => {
    node.placeholder = translate(node.dataset.i18nPlaceholder);
  });
  $("lang-switch").textContent = language === "ko" ? "English" : "한국어";
  $("lang-switch").title = translate("language");
}

function tableCell(row, value, className = "") {
  const td = document.createElement("td");
  td.className = className;
  td.textContent = value === null || value === undefined ? "—" : String(value);
  row.append(td);
  return td;
}

function emptyRow(tbody, columns, message) {
  const tr = document.createElement("tr");
  const td = tableCell(tr, message, "empty-state");
  td.colSpan = columns;
  tbody.append(tr);
}

function formatDate(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(
    typeof timestamp === "number" ? timestamp * 1000 : timestamp
  );
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(language === "ko" ? "ko-KR" : "en-US", {
    year:"numeric", month:"short", day:"numeric", hour:"2-digit", minute:"2-digit"
  });
}

function renderStatus(data) {
  const isPublished = Boolean(data?.updated_at);
  const title = connectedRemotely ?
    translate("snapshot_live") : isPublished ?
    translate("snapshot_stale") : translate("snapshot_empty");
  setText("connection-state", title);
  setText("connection-detail", isPublished ?
    translate("snapshot_age") + ": " + formatDate(data.updated_at) :
    translate("snapshot_none"));
  $("connection-dot").classList.toggle("online", connectedRemotely || isPublished);
}

function renderLeaderboard(data) {
  const body = $("leaderboard-rows");
  body.replaceChildren();
  const engines = Array.isArray(data.engines) ? [...data.engines] : [];
  engines.sort((a, b) =>
    Number(Boolean(b.is_reference)) - Number(Boolean(a.is_reference)) ||
    (b.rating ?? -Infinity) - (a.rating ?? -Infinity) ||
    String(a.name).localeCompare(String(b.name))
  );
  const visible = engines.filter(e => [e.name, e.version].some(v =>
    String(v || "").toLowerCase().includes(searchText)
  ));
  if (!visible.length) return emptyRow(body, 6, translate(
    engines.length ? "rank_no_match" : "rank_empty"
  ));
  visible.forEach((engine, index) => {
    const tr = document.createElement("tr");
    tableCell(tr, String(index + 1).padStart(2, "0"), "rank");
    const name = tableCell(tr, engine.name || "Unknown", "engine-name");
    if (engine.is_reference) {
      const tag = document.createElement("span");
      tag.className = "ref-tag";
      tag.textContent = translate("rank_ref");
      name.append(tag);
    }
    const version = document.createElement("div");
    version.className = "engine-version";
    version.textContent = engine.version || "—";
    name.append(version);
    if (typeof engine.source_url === "string") {
      try {
        const sourceUrl = new URL(engine.source_url);
        if (sourceUrl.protocol === "https:") {
          const link = document.createElement("a");
          link.href = sourceUrl.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.className = "engine-source";
          link.textContent = translate("engine_source");
          name.append(link);
        }
      } catch (_) { /* Ignore malformed legacy URLs. */ }
    }
    tableCell(tr, formatCount(engine.games));
    tableCell(tr, [engine.wins, engine.draws, engine.losses].map(formatCount).join(" / "));
    tableCell(tr, engine.rating == null ? "—" : formatCount(engine.rating), "align-right elo");
    const ci = Array.isArray(engine.rating_ci95) && engine.rating_ci95.length === 2 ?
      engine.rating_ci95.map(formatCount).join(" – ") : "—";
    tableCell(tr, ci, "align-right small-data");
    body.append(tr);
  });
}

const STATUS_KEY = {
  queued:"queued", running:"running", paused:"paused", cancelled:"cancelled",
  worker_error:"worker_error",
  complete_worker_reported:"worker_reported",
  complete_unverified:"reported", partial_unverified:"reported"
};

function sprtLabel(stats) {
  const value = stats?.sprt;
  if (!value || value.status === "insufficient_data") return translate("sprt_pending");
  if (value.status === "favor_h1") return translate("sprt_h1");
  if (value.status === "favor_h0") return translate("sprt_h0");
  return translate("sprt_continue");
}

function renderTests(data) {
  const body = $("test-rows");
  body.replaceChildren();
  const tests = (Array.isArray(data.tests) ? data.tests : []).filter(test =>
    activeFilter === "all" ||
    (activeFilter === "queued" ?
      ["queued", "running", "paused"].includes(test.status) :
      !["queued", "running", "paused"].includes(test.status))
  );
  if (!tests.length) return emptyRow(body, 6, translate("test_empty"));
  tests.slice(0, 100).forEach(test => {
    const tr = document.createElement("tr");
    tableCell(tr, "#" + test.id, "rank");
    const match = tableCell(
      tr, (test.engine_name || "Unknown") + " vs " +
      (test.reference_name || "Stockless")
    );
    const detail = document.createElement("div");
    detail.className = "engine-version";
    detail.textContent = "TC " + (test.tc || "10+0.1");
    match.append(detail);
    tableCell(tr, formatCount(test.games_done) + " / " + formatCount(test.games_target));
    tableCell(tr, [test.wins, test.draws, test.losses].map(formatCount).join(" / "));
    const sprt = tableCell(tr, sprtLabel(test.statistics), "small-data");
    const value = test.statistics?.sprt?.llr;
    if (value !== null && value !== undefined) {
      sprt.title = "LLR " + value + " / " + test.statistics.sprt.elo0 +
        " vs " + test.statistics.sprt.elo1 + " Elo";
    }
    const td = tableCell(tr, "", "align-right");
    const tag = document.createElement("span");
    const pending = ["queued", "running", "paused"].includes(test.status);
    tag.className = "state " + (pending ? "queued" : "complete");
    tag.textContent = translate(STATUS_KEY[test.status] || "reported");
    td.append(tag);
    body.append(tr);
  });
}

function renderWorkers(data) {
  const body = $("worker-rows");
  body.replaceChildren();
  const workers = Array.isArray(data.workers) ? data.workers : [];
  if (!workers.length) return emptyRow(body, 5, translate("workers_empty"));
  workers.forEach((worker, i) => {
    const tr = document.createElement("tr");
    tableCell(tr, String(i + 1).padStart(2, "0"), "rank");
    tableCell(tr, worker.name || "—", "engine-name");
    tableCell(tr, formatCount(worker.completed_jobs));
    tableCell(tr, formatCount(worker.games), "elo");
    tableCell(tr, formatDate(worker.last_completed), "align-right small-data");
    body.append(tr);
  });
}

function selectedGame() {
  return Array.isArray(current?.recent_games) ? current.recent_games[gameIndex] : null;
}

function parseFen(fen) {
  if (typeof fen !== "string") return null;
  const ranks = fen.split(" ")[0]?.split("/") || [];
  if (ranks.length !== 8) return null;
  const cells = [];
  for (const rank of ranks) {
    const row = [];
    for (const character of rank) {
      if (/^[1-8]$/.test(character)) {
        for (let k = 0; k < Number(character); k++) row.push("");
      } else if (Object.prototype.hasOwnProperty.call(PIECES, character)) {
        row.push(character);
      } else {
        return null;
      }
    }
    if (row.length !== 8) return null;
    cells.push(row);
  }
  return cells;
}

function renderBoard() {
  const game = selectedGame();
  const board = $("chess-board");
  board.replaceChildren();
  if (!game) return;
  const fens = Array.isArray(game.fens) ? game.fens : [];
  moveIndex = Math.max(0, Math.min(moveIndex, fens.length - 1));
  const grid = parseFen(fens[moveIndex]);
  if (!grid) return;
  const reverse = boardFlipped;
  for (let visibleRank = 0; visibleRank < 8; visibleRank++) {
    for (let visibleFile = 0; visibleFile < 8; visibleFile++) {
      const rowIndex = reverse ? 7 - visibleRank : visibleRank;
      const colIndex = reverse ? 7 - visibleFile : visibleFile;
      const piece = grid[rowIndex][colIndex];
      const square = document.createElement("div");
      const coordinate = String.fromCharCode(97 + colIndex) + (8 - rowIndex);
      square.className = "chess-square " +
        ((rowIndex + colIndex) % 2 === 0 ? "square-light" : "square-dark");
      square.setAttribute("aria-label", coordinate + (piece ? " " + piece : ""));
      square.textContent = PIECES[piece] || "";
      if (piece) square.classList.add(piece === piece.toUpperCase() ? "white-piece" : "black-piece");
      if (visibleRank === 7) {
        const letter = document.createElement("span");
        letter.className = "board-coordinate board-file";
        letter.textContent = String.fromCharCode(97 + colIndex);
        square.append(letter);
      }
      if (visibleFile === 0) {
        const number = document.createElement("span");
        number.className = "board-coordinate board-rank";
        number.textContent = String(8 - rowIndex);
        square.append(number);
      }
      board.append(square);
    }
  }
  setText("move-progress", moveIndex + " / " + Math.max(0, fens.length - 1));
  $("move-first").disabled = moveIndex <= 0;
  $("move-prev").disabled = moveIndex <= 0;
  $("move-next").disabled = moveIndex >= fens.length - 1;
  $("move-last").disabled = moveIndex >= fens.length - 1;
  document.querySelectorAll("#move-list .chess-move").forEach(node => {
    node.classList.toggle("selected", Number(node.dataset.ply) === moveIndex);
  });
  const focused = document.querySelector("#move-list .chess-move.selected");
  if (focused) focused.scrollIntoView({block:"nearest"});
}

function renderMoveList(game) {
  const target = $("move-list");
  target.replaceChildren();
  const moves = Array.isArray(game.moves_san) ? game.moves_san : [];
  const fragment = document.createDocumentFragment();
  for (let i = 0; i < moves.length; i += 2) {
    const line = document.createElement("div");
    line.className = "move-pair";
    const number = document.createElement("span");
    number.className = "move-number";
    number.textContent = (i / 2 + 1) + ".";
    line.append(number);
    for (let j = i; j < Math.min(i + 2, moves.length); j++) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chess-move";
      button.dataset.ply = String(j + 1);
      button.textContent = moves[j];
      button.addEventListener("click", () => {
        moveIndex = j + 1;
        renderBoard();
      });
      line.append(button);
    }
    fragment.append(line);
  }
  target.append(fragment);
}

function renderReplay(previousGameId = null) {
  const games = Array.isArray(current?.recent_games) ? current.recent_games : [];
  const selector = $("game-selector");
  selector.replaceChildren();
  if (!games.length) {
    $("replay-content").hidden = true;
    $("games-empty").hidden = false;
    const option = document.createElement("option");
    option.textContent = "—";
    selector.append(option);
    return;
  }
  games.forEach((game, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = "#" + game.test_id + " · " +
      game.white + " vs " + game.black + " (" + game.result + ")";
    selector.append(option);
  });
  const restoredIndex = games.findIndex(game => game.id === previousGameId);
  if (restoredIndex >= 0) gameIndex = restoredIndex;
  gameIndex = Math.max(0, Math.min(gameIndex, games.length - 1));
  selector.value = String(gameIndex);
  $("games-empty").hidden = true;
  $("replay-content").hidden = false;
  const game = selectedGame();
  setText("game-white", game.white || "White");
  setText("game-black", game.black || "Black");
  setText("game-result", game.result || "*");
  setText("game-test", "Test #" + game.test_id + " · " +
    (game.reference_version || "Stockless") + " / " + (game.challenger_version || "—"));
  renderMoveList(game);
  moveIndex = Math.min(moveIndex, (game.fens || []).length - 1);
  renderBoard();
  $("download-pgn").disabled = !game.pgn;
}

function render(data) {
  const previousGameId = selectedGame()?.id || null;
  current = data;
  setText("reference-version", data.reference ?
    "Pinned · " + (data.reference.version || "—") : translate("ref_not_pinned"));
  setText("engine-count", formatCount((data.engines || []).length));
  setText("game-count", formatCount((data.tests || []).reduce((n, row) =>
    n + Number(row.games_done || 0), 0)));
  setText("worker-count", formatCount(data.active_workers || 0));
  renderLeaderboard(data);
  renderTests(data);
  renderWorkers(data);
  renderReplay(previousGameId);
  renderStatus(data);
}

function downloadPgn() {
  const game = selectedGame();
  if (!game?.pgn) return;
  const blob = new Blob([game.pgn], {type:"application/x-chess-pgn;charset=utf-8"});
  const uri = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = uri;
  link.download = "openfishtest-test-" + game.test_id + "-game-" + game.id + ".pgn";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(uri), 1000);
}

function makeIssue(title, body) {
  // This opens the GitHub Issue composer; it does not silently post an issue.
  const uri = new URL("https://github.com/gaong5247-cmd/OpenFishtest/issues/new");
  uri.searchParams.set("title", title.slice(0, 120));
  uri.searchParams.set("body", body.slice(0, 5000));
  window.location.assign(uri.href);
}

function formText(form, key) {
  return String(new FormData(form).get(key) || "").trim();
}

function wireForms() {
  $("engine-form").addEventListener("submit", event => {
    event.preventDefault();
    const f = event.currentTarget;
    if (!f.reportValidity()) return;
    const name = formText(f, "name"), version = formText(f, "version"), url = formText(f, "url");
    makeIssue("[ENGINE] " + name + " " + version,
      "## Engine registration request\n\n- Engine: " + name +
      "\n- Version: " + version + "\n- Public source or release: " + url +
      "\n\nMaintainer approval required. Do not attach untrusted executables.");
  });
  $("test-form").addEventListener("submit", event => {
    event.preventDefault();
    const f = event.currentTarget;
    if (!f.reportValidity()) return;
    const engine = formText(f, "engine");
    makeIssue("[TEST] " + engine + " vs Stockless",
      "## Requested Stockless reference test\n\n- Challenger: " + engine +
      "\n- Target games (color-reversed pairs): " + formText(f, "games") +
      "\n- Time control: " + formText(f, "tc") +
      "\n- Purpose: " + (formText(f, "purpose") || "Not specified") +
      "\n\nTest execution requires a maintainer-approved engine and available trusted workers.");
  });
  $("worker-form").addEventListener("submit", event => {
    event.preventDefault();
    const f = event.currentTarget;
    if (!f.reportValidity()) return;
    const alias = formText(f, "alias");
    makeIssue("[WORKER] " + alias,
      "## Volunteer worker request\n\n- Public alias: " + alias +
      "\n- Operating system: " + formText(f, "os") +
      "\n- Optional CPU info: " + (formText(f, "cpu") || "Not specified") +
      "\n\nI will run only locally approved UCI binaries and understand the worker can be stopped. " +
      "Please contact me through GitHub, not through a public token.");
  });
}

async function readJson(url) {
  const response = await fetch(url, {cache:"no-store"});
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}

async function refresh() {
  $("refresh-button").disabled = true;
  try {
    let config = {};
    try {
      config = await readJson("./config.json");
    } catch (_) {
      config = {};
    }
    const base = String(config.api_base || "").trim().replace(/\/+$/, "");
    connectedRemotely = /^https:\/\//i.test(base);
    const url = connectedRemotely ?
      base + "/api/public/snapshot" : "./data/status.json";
    const data = await readJson(url);
    render(data);
  } catch (error) {
    connectedRemotely = false;
    if (!current) render({reference:null, engines:[], tests:[], workers:[], recent_games:[]});
    setText("connection-state", translate("snapshot_failed"));
    setText("connection-detail", String(error.message || error));
    $("connection-dot").classList.remove("online");
  } finally {
    $("refresh-button").disabled = false;
  }
}

function init() {
  translateStatic();
  $("lang-switch").addEventListener("click", () => {
    language = language === "en" ? "ko" : "en";
    try { localStorage.setItem("openfishtest-language", language); } catch (_) {}
    translateStatic();
    if (current) render(current);
  });
  $("refresh-button").addEventListener("click", refresh);
  $("engine-search").addEventListener("input", event => {
    searchText = event.target.value.toLowerCase().trim();
    if (current) renderLeaderboard(current);
  });
  document.querySelectorAll("[data-filter]").forEach(button => {
    button.addEventListener("click", () => {
      activeFilter = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach(element =>
        element.classList.toggle("active", element === button));
      if (current) renderTests(current);
    });
  });
  $("game-selector").addEventListener("change", event => {
    gameIndex = Math.max(0, Number(event.target.value) || 0);
    moveIndex = 0;
    renderReplay();
  });
  $("move-first").addEventListener("click", () => { moveIndex = 0; renderBoard(); });
  $("move-prev").addEventListener("click", () => { moveIndex -= 1; renderBoard(); });
  $("move-next").addEventListener("click", () => { moveIndex += 1; renderBoard(); });
  $("move-last").addEventListener("click", () => {
    moveIndex = (selectedGame()?.fens || []).length - 1;
    renderBoard();
  });
  $("flip-board").addEventListener("click", () => {
    boardFlipped = !boardFlipped;
    renderBoard();
  });
  $("download-pgn").addEventListener("click", downloadPgn);
  wireForms();
  refresh();
  setInterval(refresh, 60_000);
}
init();
