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
let arenaApiBase = "";
let arenaPolicy = null;
let arenaUploading = false;
let lastArenaSubmissionId = null;
let selectedEngineFile = null;
let selectedBookFile = null;
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

function renderCommunityIndex(data, error = false) {
  const rows = $("community-rows");
  if (!rows) return;
  rows.replaceChildren();
  const entries = Array.isArray(data?.entries) ? data.entries : [];
  if (error || entries.length === 0) {
    return emptyRow(rows, 5, translate(
      error ? "community_error" : "community_empty"
    ));
  }
  for (const entry of entries.slice(0, 30)) {
    if (!/^[0-9a-f]{12,40}$/.test(String(entry.id || ""))) continue;
    const tr = document.createElement("tr");
    const author = tableCell(tr, String(entry.contributor || "Unknown"), "engine-name");
    const note = document.createElement("div");
    note.className = "engine-version";
    note.textContent = entry.submitted_at ?
      formatDate(entry.submitted_at) : "Unverified";
    author.append(note);
    tableCell(tr, formatCount(entry.games));
    tableCell(tr, [entry.wins, entry.draws, entry.losses]
      .map(formatCount).join(" / "));
    tableCell(tr, String(entry.points ?? "—"), "elo");
    const files = tableCell(tr, "", "community-downloads");
    for (const [filename, key] of [
      ["games.pgn", "community_pgn"],
      ["openings.epd", "community_epd"]
    ]) {
      const link = document.createElement("a");
      link.href = "./data/community/" + entry.id + "/" + filename;
      link.rel = "noopener noreferrer";
      link.textContent = translate(key);
      link.setAttribute("download", "");
      files.append(link);
    }
    rows.append(tr);
  }
  if (!rows.children.length) emptyRow(rows, 5, translate("community_empty"));
}

async function refreshCommunityIndex() {
  try {
    const index = await readJson("./data/community/index.json");
    renderCommunityIndex(index);
  } catch (_) {
    renderCommunityIndex(null, true);
  }
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
  renderArena(data);
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

const ARENA_STATUS_TRANSLATION = {
  queued:"arena_wait",running:"arena_running",uploading:"arena_wait",
  passed:"arena_pass",rejected:"arena_fail",invalid:"arena_invalid",
  error:"arena_error",released:"arena_released",discarded:"arena_discarded"
};

function renderArena(data) {
  const rows = $("arena-rows");
  rows.replaceChildren();
  const entries = Array.isArray(data.arena) ? data.arena : [];
  if (!entries.length) return emptyRow(rows, 5, translate("arena_no_results"));
  entries.slice(0, 30).forEach(item => {
    const tr = document.createElement("tr");
    tableCell(tr, "#" + item.id, "rank");
    const engine = tableCell(tr, item.engine_name || "Unnamed", "engine-name");
    const version = document.createElement("div");
    version.className = "engine-version";
    version.textContent = item.engine_version || "";
    engine.append(version);
    if (item.uci_name) {
      const info = document.createElement("div");
      info.className = "engine-version";
      const optionCount = Array.isArray(item.uci_options) ?
        item.uci_options.length : 0;
      info.textContent = "UCI: " + item.uci_name +
        " · " + optionCount + " options auto-detected";
      engine.append(info);
    }
    const score = item.score == null ? "—" :
      String(Number(item.score).toFixed(1)) + " / 100";
    tableCell(tr, score, "elo");
    const status = ARENA_STATUS_TRANSLATION[item.status] || "arena_wait";
    const decision = tableCell(tr, translate(status),
      item.status === "passed" ? "arena-qualified" :
      item.status === "rejected" ? "arena-disqualified" : "small-data");
    if (item.status === "passed") decision.title = "Owner review required";
    const pgnCell = tableCell(tr, "");
    if (item.pgn_available && arenaApiBase) {
      const link = document.createElement("a");
      link.textContent = translate("arena_pgn_download");
      link.href = arenaApiBase + "/api/arena/entries/" + Number(item.id) + "/pgn";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.className = "engine-source";
      pgnCell.append(link);
    } else if (item.pgn_available) {
      const link = document.createElement("a");
      link.textContent = translate("arena_pgn_replay");
      link.href = "#games";
      link.className = "engine-source";
      pgnCell.append(link);
    } else {
      pgnCell.textContent = "—";
    }
    rows.append(tr);
  });
}

function updateArenaControls() {
  const isExe = selectedEngineFile?.name?.toLowerCase().endsWith(".exe");
  const supportsWindows = Boolean(arenaPolicy?.windows_sandbox_enabled);
  const ready = Boolean(
    arenaApiBase && arenaPolicy?.reference &&
    (arenaPolicy.accepting ||
      (selectedBookFile && arenaPolicy.book_upload_enabled))
  );
  const enabled = ready && selectedEngineFile && !arenaUploading &&
    (!isExe || supportsWindows);
  $("arena-submit").disabled = !enabled;
  const message = $("arena-policy-message");
  const container = $("arena-connect-status");
  container.classList.remove("arena-connected");
  if (!arenaApiBase) {
    message.textContent = translate("arena_disconnected");
  } else if (!arenaPolicy) {
    message.textContent = translate("arena_policy_offline");
  } else if (isExe && !supportsWindows) {
    message.textContent = translate("arena_windows_unavailable");
  } else if (ready) {
    message.textContent = selectedBookFile ?
      translate("arena_custom_book_ready") : translate("arena_ready");
    container.classList.add("arena-connected");
  } else {
    message.textContent = translate("arena_disabled") +
      (arenaPolicy.reason || "—");
  }
}

async function refreshArenaPolicy() {
  if (!arenaApiBase) {
    arenaPolicy = null;
    updateArenaControls();
    return;
  }
  try {
    arenaPolicy = await readJson(arenaApiBase + "/api/arena/policy");
  } catch (_) {
    arenaPolicy = null;
  }
  updateArenaControls();
}

function setSelectedUpload(kind, file) {
  if (!file) return;
  const engine = kind === "engine";
  const extension = file.name.split(".").pop()?.toLowerCase();
  const allowed = engine ? ["exe", "zip"] : ["epd", "pgn"];
  const max = engine ? 128 * 1024 * 1024 : 200 * 1024 * 1024;
  if (!allowed.includes(extension)) {
    if (engine) {
      selectedEngineFile = null;
      $("arena-engine-zone").classList.remove("selected");
      setText("arena-engine-name", translate("arena_drop_click"));
    } else {
      selectedBookFile = null;
      $("arena-book-zone").classList.remove("selected");
      setText("arena-book-name", translate("arena_book_default"));
    }
    setText("arena-upload-message", translate(engine ?
      "arena_file_type_error" : "arena_book_type_error"));
    updateArenaControls();
    return;
  }
  if (file.size > max || file.size === 0) {
    if (engine) {
      selectedEngineFile = null;
      $("arena-engine-zone").classList.remove("selected");
      setText("arena-engine-name", translate("arena_drop_click"));
    } else {
      selectedBookFile = null;
      $("arena-book-zone").classList.remove("selected");
      setText("arena-book-name", translate("arena_book_default"));
    }
    setText("arena-upload-message", translate(engine ?
      "arena_large_file" : "arena_large_book"));
    updateArenaControls();
    return;
  }
  if (engine) {
    selectedEngineFile = file;
    setText("arena-engine-name", file.name +
      " · " + (file.size / 1048576).toFixed(1) + " MiB");
    $("arena-engine-zone").classList.add("selected");
  } else {
    selectedBookFile = file;
    setText("arena-book-name", file.name +
      " · " + (file.size / 1048576).toFixed(2) + " MiB");
    $("arena-book-zone").classList.add("selected");
  }
  setText("arena-upload-message", "");
  updateArenaControls();
}

function wireDropZone(zoneId, inputId, kind) {
  const zone = $(zoneId);
  const input = $(inputId);
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => {
    setSelectedUpload(kind, input.files?.[0]);
  });
  ["dragenter", "dragover"].forEach(name => zone.addEventListener(name, event => {
    event.preventDefault();
    zone.classList.add("drag-over");
  }));
  ["dragleave", "drop"].forEach(name => zone.addEventListener(name, event => {
    event.preventDefault();
    zone.classList.remove("drag-over");
  }));
  zone.addEventListener("drop", event => {
    const files = event.dataTransfer?.files;
    if (files && files.length === 1) {
      setSelectedUpload(kind, files[0]);
    } else {
      setText("arena-upload-message", translate("arena_one_file"));
    }
  });
}

function transferFile(url, file, mime, startPercent, endPercent) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.setRequestHeader("Content-Type", mime);
    xhr.timeout = file.size > 80 * 1024 * 1024 ? 15 * 60 * 1000 : 4 * 60 * 1000;
    xhr.upload.onprogress = event => {
      if (!event.lengthComputable) return;
      const progress = event.loaded / event.total;
      const pct = Math.round(startPercent +
        progress * (endPercent - startPercent));
      $("arena-upload-progress").value = pct;
      setText("arena-progress-label", pct + "%");
    };
    xhr.onload = () => {
      let response = {};
      try { response = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 201) resolve(response);
      else reject(new Error(String(response.detail || "HTTP " + xhr.status)));
    };
    xhr.onerror = () => reject(new Error("Network error / HTTPS backend offline"));
    xhr.ontimeout = () => reject(new Error("Upload timed out"));
    xhr.send(file);
  });
}

async function submitArenaUpload(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  if (!selectedEngineFile) {
    setText("arena-upload-message", translate("arena_select_file"));
    return;
  }
  if (!arenaApiBase || !arenaPolicy?.reference) {
    setText("arena-upload-message", translate("arena_disconnected"));
    return;
  }
  if (!arenaPolicy.accepting &&
      !(selectedBookFile && arenaPolicy.book_upload_enabled)) {
    setText("arena-upload-message", translate("arena_no_book_available"));
    return;
  }
  if (selectedEngineFile.name.toLowerCase().endsWith(".exe") &&
      !arenaPolicy.windows_sandbox_enabled) {
    setText("arena-upload-message", translate("arena_windows_unavailable"));
    return;
  }

  arenaUploading = true;
  updateArenaControls();
  $("arena-upload-progress-container").hidden = false;
  $("arena-upload-progress").value = 0;
  setText("arena-progress-label", "0%");
  try {
    let bookSha = null;
    if (selectedBookFile) {
      setText("arena-upload-message", translate("arena_book_processing"));
      const params = new URLSearchParams({filename:selectedBookFile.name});
      const book = await transferFile(
        arenaApiBase + "/api/arena/books?" + params,
        selectedBookFile, "application/octet-stream", 0, 25
      );
      bookSha = book.book_sha256;
      if (!/^[a-f0-9]{64}$/i.test(bookSha || "")) {
        throw new Error("Opening book response did not include valid SHA-256");
      }
    }
    setText("arena-upload-message", translate("arena_uploading"));
    const params = new URLSearchParams();
    if (bookSha) params.set("book_sha256", bookSha);
    const result = await transferFile(
      arenaApiBase + "/api/arena/submit?" + params,
      selectedEngineFile, "application/octet-stream",
      selectedBookFile ? 25 : 0, 100
    );
    lastArenaSubmissionId = result.id;
    form.reset();
    selectedEngineFile = null;
    selectedBookFile = null;
    $("arena-engine-zone").classList.remove("selected");
    $("arena-book-zone").classList.remove("selected");
    setText("arena-engine-name", translate("arena_drop_click"));
    setText("arena-book-name", translate("arena_book_default"));
    setText("arena-upload-message", translate("arena_upload_success") +
      result.id + ". " + translate("arena_uci_pending"));
    await refresh();
  } catch (error) {
    setText("arena-upload-message", translate("arena_upload_error") +
      String(error.message || error));
  } finally {
    arenaUploading = false;
    updateArenaControls();
  }
}

function wireArena() {
  wireDropZone("arena-engine-zone", "arena-engine-file", "engine");
  wireDropZone("arena-book-zone", "arena-book-file", "book");
  $("arena-upload-form").addEventListener("submit", submitArenaUpload);
  updateArenaControls();
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
    arenaApiBase = connectedRemotely ? base : "";
    const url = connectedRemotely ?
      base + "/api/public/snapshot" : "./data/status.json";
    const data = await readJson(url);
    render(data);
    await refreshArenaPolicy();
  } catch (error) {
    connectedRemotely = false;
    arenaPolicy = null;
    updateArenaControls();
    if (!current) render({reference:null, engines:[], tests:[], workers:[], recent_games:[]});
    setText("connection-state", translate("snapshot_failed"));
    setText("connection-detail", String(error.message || error));
    $("connection-dot").classList.remove("online");
  } finally {
    await refreshCommunityIndex();
    $("refresh-button").disabled = false;
  }
}

function awaitCommunityWithoutBlocking() {
  void refreshCommunityIndex();
}

function init() {
  translateStatic();
  $("lang-switch").addEventListener("click", () => {
    language = language === "en" ? "ko" : "en";
    try { localStorage.setItem("openfishtest-language", language); } catch (_) {}
    translateStatic();
    if (current) render(current);
    awaitCommunityWithoutBlocking();
    updateArenaControls();
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
  wireArena();
  refresh();
  setInterval(refresh, 60_000);
}
init();
