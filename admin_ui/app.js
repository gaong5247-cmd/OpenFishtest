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
function render(data, workers) {
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
}
async function refresh() {
  const [status, workers] = await Promise.all([
    request("/api/public/snapshot"),
    request("/api/admin/workers")
  ]);
  render(status, workers);
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
      sha256:formValue(form,"sha256")
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
