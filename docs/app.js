// OpenFishtest public dashboard. No secret token or privileged action lives here.
const $ = id => document.getElementById(id);
const fmt = n => Number(n || 0).toLocaleString("en-US");
const text = (id, value) => { $(id).textContent = value; };
let current = null;
let filter = "all";
let query = "";

function cell(tr, value, className) {
  const td = document.createElement("td");
  if (className) td.className = className;
  td.textContent = value;
  tr.append(td);
  return td;
}
function empty(tbody, message, columns) {
  const row = document.createElement("tr");
  const td = cell(row, message, "empty-state");
  td.colSpan = columns;
  tbody.append(row);
}
function setStatus(title, detail, online) {
  text("connection-state", title);
  text("connection-detail", detail);
  $("connection-dot").classList.toggle("online", online);
}
function formatWhen(value) {
  if (!value) return "No published result snapshot yet";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "Timestamp unavailable" : "Updated " + d.toLocaleString();
}
function renderLeaderboard(data) {
  const tbody = $("leaderboard-rows");
  tbody.replaceChildren();
  const engines = Array.isArray(data.engines) ? [...data.engines] : [];
  engines.sort((a, b) => Number(b.is_reference) - Number(a.is_reference) ||
    (b.rating ?? -Infinity) - (a.rating ?? -Infinity) ||
    String(a.name).localeCompare(String(b.name)));
  const visible = engines.filter(e => [e.name, e.version].some(s =>
    String(s || "").toLowerCase().includes(query)));
  if (!visible.length) return empty(tbody, engines.length ? "No engines match your search." :
    "No engines registered yet. Stockless reference setup is pending.", 5);
  visible.forEach((e, i) => {
    const tr = document.createElement("tr");
    cell(tr, String(i + 1).padStart(2, "0"), "rank");
    const name = cell(tr, "", "engine-name");
    name.textContent = e.name || "Unknown engine";
    if (e.is_reference) {
      const ref = document.createElement("span");
      ref.className = "ref-tag";
      ref.textContent = "REFERENCE";
      name.append(ref);
    }
    const version = document.createElement("div");
    version.className = "engine-version";
    version.textContent = e.version || "Version unknown";
    name.append(version);
    cell(tr, fmt(e.games));
    cell(tr, [e.wins, e.draws, e.losses].map(fmt).join(" / "));
    const elo = cell(tr, e.rating == null ? "—" : fmt(e.rating), "align-right elo");
    if (e.rating == null) elo.classList.add("unknown");
    tbody.append(tr);
  });
}
function renderTests(data) {
  const tbody = $("test-rows");
  tbody.replaceChildren();
  const tests = (Array.isArray(data.tests) ? data.tests : []).filter(t =>
    filter === "all" || (filter === "queued" ?
      t.status === "queued" : t.status !== "queued"));
  if (!tests.length) return empty(tbody, "No tests in this view yet.", 5);
  tests.slice(0, 100).forEach(t => {
    const tr = document.createElement("tr");
    cell(tr, "#" + t.id, "rank");
    cell(tr, (t.engine_name || "Unknown") + " vs " + (t.reference_name || "Stockless"));
    cell(tr, fmt(t.games_done) + " / " + fmt(t.games_target));
    cell(tr, [t.wins, t.draws, t.losses].map(fmt).join(" / "));
    const status = cell(tr, "", "align-right");
    const badge = document.createElement("span");
    badge.className = "state " + (t.status === "queued" ? "queued" : "complete");
    badge.textContent = t.status === "queued" ? "Queued" : "Reported · unverified";
    status.append(badge);
    tbody.append(tr);
  });
}
function render(data) {
  current = data;
  text("reference-version", data.reference ?
    "Pinned build · " + data.reference.version : "Not pinned yet");
  text("engine-count", fmt((data.engines || []).length));
  text("game-count", fmt((data.tests || []).reduce(
    (n, t) => n + (Number(t.games_done) ||
      Number(t.wins || 0) + Number(t.draws || 0) + Number(t.losses || 0)), 0)));
  renderLeaderboard(data);
  renderTests(data);
}
async function readJson(url) {
  const response = await fetch(url, {cache: "no-store"});
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}
async function refresh() {
  $("refresh-button").disabled = true;
  try {
    let config = {};
    try { config = await readJson("./config.json"); } catch (_) {}
    const base = String(config.api_base || "").trim().replace(/\/+$/, "");
    const remote = /^https:\/\//i.test(base);
    const url = remote ? base + "/api/public/snapshot" : "./data/status.json";
    const data = await readJson(url);
    render(data);
    setStatus(
      remote ? "Public API connected" : "Static preview · no live server",
      formatWhen(data.updated_at) + (remote ? " · Public read-only data" : " · Setup required for live tests"),
      remote
    );
  } catch (err) {
    setStatus("Data unavailable", "Could not load public snapshot · " + String(err.message), false);
    if (!current) {
      render({engines: [], tests: [], reference: null});
    }
  } finally {
    $("refresh-button").disabled = false;
  }
}
$("refresh-button").addEventListener("click", refresh);
$("engine-search").addEventListener("input", event => {
  query = event.target.value.toLowerCase().trim();
  if (current) renderLeaderboard(current);
});
document.querySelectorAll("[data-filter]").forEach(button => {
  button.addEventListener("click", () => {
    filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach(b =>
      b.classList.toggle("active", b === button));
    if (current) renderTests(current);
  });
});
refresh();
setInterval(refresh, 60_000);
