"use strict";
// No secrets are embedded in HTML or written to browser storage.
const $ = id => document.getElementById(id);
let snapshot = null;
const token = () => $("admin-secret").value.trim();
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "ok";
}
async function request(path, method = "GET", data = null) {
  const options = {method, headers: {"X-Admin-Token": token()}};
  if (data !== null) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(data);
  }
  const result = await fetch(path, options);
  let content = null;
  try { content = await result.json(); } catch (_) {}
  if (!result.ok) throw new Error(
    String(content?.detail || content?.message || "HTTP " + result.status)
  );
  return content;
}
const formValue = (form, key) => String(new FormData(form).get(key) || "").trim();
function rowCell(row, text) {
  const td = document.createElement("td");
  td.textContent = String(text ?? "—");
  row.append(td);
  return td;
}
function addAction(cell, label, operation) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.className = "secondary";
  button.addEventListener("click", async () => {
    const answer = window.confirm(label + " this test or worker?");
    if (!answer) return;
    try {
      await request(operation, "POST", {});
      notice("Success: " + label);
      await refresh();
    } catch (error) {
      notice(error.message, true);
    }
  });
  cell.append(button);
}
function populateSelect(selectId, engines) {
  const select = $(selectId);
  const selected = select.value;
  select.replaceChildren();
  for (const engine of engines) {
    const option = document.createElement("option");
    option.value = String(engine.id);
    option.textContent = engine.name + " " + engine.version + " (#" + engine.id + ")";
    select.append(option);
  }
  if (Array.from(select.options).some(o => o.value === selected)) select.value = selected;
}
function render(data, workers, arena) {
  snapshot = data;
  $("ref-version").textContent = data.reference ?
    data.reference.name + " · " + data.reference.version : "Not pinned yet";
  $("storage").textContent = (Number(data.storage?.used_bytes || 0) / 1e9)
    .toFixed(3) + " GB / 5 GB";
  $("used").value = Number(data.storage?.used_bytes || 0);
  populateSelect("reference-choice",
    (data.engines || []).filter(e => e.is_reference || e.name?.toLowerCase() === "stockless"));
  populateSelect("challenger-choice", (data.engines || []).filter(e => !e.is_reference));
  const rows = $("test-rows");
  rows.replaceChildren();
  for (const test of data.tests || []) {
    const tr = document.createElement("tr");
    rowCell(tr, "#" + test.id);
    rowCell(tr, test.engine_name + " vs " + test.reference_name);
    rowCell(tr, test.games_done + " / " + test.games_target);
    rowCell(tr, test.status);
    const actions = rowCell(tr, "");
    if (["queued","running","worker_error"].includes(test.status)) {
      addAction(actions, "Pause", "/api/admin/tests/" + test.id + "/pause");
    }
    if (["paused","worker_error"].includes(test.status)) {
      addAction(actions, "Resume", "/api/admin/tests/" + test.id + "/resume");
    }
    if (["queued","running","paused","worker_error"].includes(test.status)) {
      addAction(actions, "Cancel", "/api/admin/tests/" + test.id + "/cancel");
    }
    rows.append(tr);
  }
  if (!rows.children.length) {
    const tr = document.createElement("tr");
    const td = rowCell(tr, "No tests queued yet");
    td.colSpan = 5;
    rows.append(tr);
  }
  const workerRows = $("worker-rows");
  workerRows.replaceChildren();
  for (const worker of workers) {
    const tr = document.createElement("tr");
    rowCell(tr, worker.id);
    rowCell(tr, worker.display_name);
    rowCell(tr, worker.active ? "Approved" : "Revoked");
    const actions = rowCell(tr, "");
    if (worker.active) {
      addAction(actions, "Revoke", "/api/admin/workers/" +
        encodeURIComponent(worker.id) + "/revoke");
    }
    workerRows.append(tr);
  }
  if (!workerRows.children.length) {
    const tr = document.createElement("tr");
    const td = rowCell(tr, "No workers approved yet");
    td.colSpan = 4;
    workerRows.append(tr);
  }
  renderArenaInbox(arena);
}
async function refresh() {
  const [status, workers, arena] = await Promise.all([
    request("/api/public/snapshot"),
    request("/api/admin/workers"),
    request("/api/admin/arena")
  ]);
  render(status, workers, arena);
}
async function downloadCandidate(entryId) {
  if (!token()) return notice("Administrator secret required.", true);
  const url = "/api/admin/arena/" + Number(entryId) + "/download";
  const response = await fetch(url, {
    headers: {"X-Admin-Token": token()},
    cache: "no-store"
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(String(detail.detail || ("Download HTTP " + response.status)));
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = "OpenFishtest-candidate-" + entryId + "-QUARANTINED.zip";
    document.body.append(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}

function arenaButton(cell, label, handler) {
  const button = document.createElement("button");
  button.className = "secondary";
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    try {
      await handler();
      await refresh();
    } catch (error) {
      notice(error.message || String(error), true);
    }
  });
  cell.append(button);
}

function renderArenaInbox(data) {
  const tbody = $("arena-admin-rows");
  const candidates = Array.isArray(data?.entries) ? data.entries : [];
  $("arena-notification-count").textContent = String(data?.notifications || 0);
  tbody.replaceChildren();
  for (const item of candidates) {
    const tr = document.createElement("tr");
    const name = rowCell(tr, "#" + item.id + " · " + item.engine_name);
    const version = document.createElement("div");
    version.className = "muted";
    version.textContent = item.engine_version;
    name.append(version);
    rowCell(tr, item.score == null ? "—" : Number(item.score).toFixed(1) + "/100");
    rowCell(tr, item.status);
    const hash = rowCell(tr, String(item.reference_version || "?") + " · " +
      String(item.reference_sha256 || "").slice(0, 12) + "…");
    hash.title = String(item.reference_sha256 || "");
    const actions = rowCell(tr, "");
    if (item.download_available) {
      arenaButton(actions, "Download ZIP", async () => {
        await downloadCandidate(item.id);
        notice("Quarantined candidate downloaded. Inspect it in an isolated VM.");
      });
      arenaButton(actions, "Mark Release URL", async () => {
        const url = window.prompt(
          "Paste the GitHub Release URL YOU manually published for this engine. " +
          "This does not upload anything.", "https://github.com/"
        );
        if (!url) return;
        if (!url.startsWith("https://github.com/")) {
          throw new Error("Release URL must use https://github.com/");
        }
        const result = await request(
          "/api/admin/arena/" + item.id + "/mark-released", "POST",
          {release_url:url}
        );
        notice("Recorded manual release: " + result.url);
      });
      arenaButton(actions, "Discard binary", async () => {
        if (!window.confirm("Permanently delete candidate #" + item.id +
          " ZIP? Historical PGN will remain.")) return;
        await request("/api/admin/arena/" + item.id + "/discard", "POST", {});
        notice("Candidate ZIP deleted; PGN retained.");
      });
    } else if (item.status === "queued" || item.status === "running") {
      const state = document.createElement("span");
      state.className = "muted";
      state.textContent = "Automatic sandbox testing";
      actions.append(state);
    } else if (item.status === "rejected" || item.status === "discarded") {
      const state = document.createElement("span");
      state.className = "muted";
      state.textContent = "Binary deleted";
      actions.append(state);
    } else {
      const state = document.createElement("span");
      state.className = "muted";
      state.textContent = "No candidate available";
      actions.append(state);
    }
    tbody.append(tr);
  }
  if (!candidates.length) {
    const tr = document.createElement("tr");
    rowCell(tr, "No uploads received. Arena may be disabled until HTTPS/VM is configured.")
      .colSpan = 5;
    tbody.append(tr);
  }
}

function bindSubmit(id, action) {
  $(id).addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    if (!token()) return notice("Enter your administrator token first", true);
    try {
      await action(form);
      await refresh();
    } catch (error) {
      notice(error.message, true);
    }
  });
}
function setup() {
  $("load").addEventListener("click", async () => {
    try { await refresh(); notice("Server data loaded."); }
    catch (error) { notice(error.message, true); }
  });
  bindSubmit("engine-form", async form => {
    const result = await request("/api/admin/engines", "POST", {
      name:formValue(form, "name"), version:formValue(form,"version"),
      sha256:formValue(form,"sha256"),
      source_url:formValue(form,"source_url") || null
    });
    form.reset();
    notice("Approved engine build #" + result.id + " registered.");
  });
  bindSubmit("reference-form", async () => {
    const result = await request("/api/admin/reference", "POST", {
      engine_id:Number($("reference-choice").value)
    });
    notice("Stockless reference build pinned: #" + result.reference_engine_id);
  });
  bindSubmit("test-form", async form => {
    const games = Number(formValue(form,"games"));
    const book = formValue(form, "book");
    if (!Number.isInteger(games) || games < 2 || games % 2) {
      return notice("Total games must be an even positive integer.", true);
    }
    const test = await request("/api/admin/tests", "POST", {
      engine_id:Number($("challenger-choice").value),
      games_target:games, batch_games:Number(formValue(form,"batch")),
      tc:formValue(form,"tc"), book_sha256: book || null
    });
    notice("Test #" + test.id + " successfully queued.");
  });
  bindSubmit("worker-form", async form => {
    const result = await request("/api/admin/workers", "POST", {
      worker_id:formValue(form,"worker_id"),
      display_name:formValue(form,"display_name")
    });
    $("issued-token").hidden = false;
    $("issued-text").textContent =
      "Worker ID: " + result.worker_id + "\nToken: " + result.worker_token;
    form.reset();
    notice("Worker enrolled. Give their unique secret to the approved volunteer privately.");
  });
  $("copy-token").addEventListener("click", async () => {
    const value = $("issued-text").textContent;
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      notice("One-time secret copied; do not post it publicly.");
    } catch (error) {
      notice("Clipboard blocked. Select the secret manually.", true);
    }
  });
}
setup();
