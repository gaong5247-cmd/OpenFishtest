/* OpenFishtest combined static + localhost upload page.
 *
 * On github.io: show instructions and a local app link, never request a PAT.
 * On 127.0.0.1:8765: the Python helper reuses gh auth login, identifies
 * owner vs Contributor, and submits data by the established GitHub API path.
 *
 * No GitHub credential is read or stored by this JavaScript file.
 */
"use strict";
(function () {
  const $ = id => document.getElementById(id);
  const MAX_PGN = 2_000_000;
  const MAX_EPD = 512 * 1024;
  const IS_LOCAL = location.hostname === "127.0.0.1" &&
    location.port === "8765" && location.protocol === "http:";
  const selected = {pgn: null, epd: null};
  let role = null;
  let username = null;
  let uploading = false;

  function setStatus(message, kind = "info") {
    $("upload-progress").textContent = String(message);
    $("upload-progress").dataset.kind = kind;
  }
  function setAuthStatus(message, kind = "info") {
    $("auth-status").textContent = String(message);
    $("auth-status").dataset.kind = kind;
  }
  function ready() {
    $("publish-button").disabled = uploading || !role ||
      !selected.pgn || !selected.epd || !$("publish-consent").checked;
    $("refresh-auth").disabled = uploading;
  }

  function chooseFile(kind, file) {
    const isPgn = kind === "pgn";
    if (!file || !(isPgn ? /\.pgn$/i : /\.epd$/i).test(file.name)) {
      setStatus(isPgn ? "PGN 파일(.pgn)을 선택해 줘." :
        "정규화된 EPD 파일(.epd)을 선택해 줘.", "error");
      return;
    }
    const limit = isPgn ? MAX_PGN : MAX_EPD;
    if (file.size <= 0 || file.size > limit) {
      setStatus(isPgn ? "PGN은 최대 2MB까지 공개할 수 있어." :
        "EPD는 최대 512KiB야. Contributor의 openings.epd를 선택해.", "error");
      return;
    }
    selected[kind] = file;
    $(kind + "-name").textContent = file.name + " · " +
      (file.size / 1024).toFixed(1) + "KiB";
    $(kind + "-drop").classList.add("chosen");
    setStatus("파일을 선택했어. 로그인과 공개 동의를 확인해 줘.");
    ready();
  }

  function bindFile(kind) {
    const input = $(kind + "-file");
    const area = $(kind + "-drop");
    area.addEventListener("click", () => input.click());
    area.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });
    input.addEventListener("change", () => chooseFile(kind, input.files?.[0]));
    ["dragenter", "dragover"].forEach(name => {
      area.addEventListener(name, event => {
        event.preventDefault();
        area.classList.add("dragging");
      });
    });
    ["dragleave", "drop"].forEach(name => {
      area.addEventListener(name, event => {
        event.preventDefault();
        area.classList.remove("dragging");
      });
    });
    area.addEventListener("drop", event => {
      if (!event.dataTransfer || event.dataTransfer.files.length !== 1) {
        setStatus("PGN과 EPD를 각각 한 파일씩 넣어줘.", "error");
        return;
      }
      chooseFile(kind, event.dataTransfer.files[0]);
    });
  }

  async function checkLogin() {
    if (uploading) return;
    role = null;
    username = null;
    setAuthStatus("로컬 GitHub CLI 계정 확인 중…");
    ready();
    try {
      const response = await fetch("/api/status", {cache: "no-store"});
      if (!response.ok) throw new Error("로컬 서버 응답 오류");
      const data = await response.json();
      if (!data.authenticated || !data.username ||
          !["owner", "contributor"].includes(data.role)) {
        throw new Error("먼저 PowerShell에서 gh auth login을 한 번 실행해 줘.");
      }
      username = data.username;
      role = data.role;
      setAuthStatus("✓ GitHub 로그인됨: " + username, "success");
      $("role-mode").textContent = role === "owner" ?
        "관리자 · PR 없이 직접 업로드 → Actions 검증 후 공개" :
        "Contributor · 본인 GitHub 계정으로 PR 자동 제출 → Actions 검증 후 공개";
    } catch (error) {
      $("role-mode").textContent = "로그인 후 다시 확인할 수 있어.";
      setAuthStatus(
        "GitHub 로그인 확인 실패: " + String(error.message || error), "error"
      );
    } finally {
      ready();
    }
  }

  function base64FromArray(buffer) {
    const data = new Uint8Array(buffer);
    let binary = "";
    const chunk = 0x6000;
    for (let index = 0; index < data.length; index += chunk) {
      binary += String.fromCharCode(...data.subarray(index, index + chunk));
    }
    return btoa(binary);
  }

  async function loadFile(file, label) {
    if (!file) throw new Error("두 파일을 모두 선택해 줘.");
    const buffer = await file.arrayBuffer();
    let text;
    try {
      text = new TextDecoder("utf-8", {fatal:true}).decode(buffer);
    } catch (_) {
      throw new Error(label + " 파일은 UTF-8 텍스트여야 해.");
    }
    if (text.includes("\u0000")) {
      throw new Error(label + " 파일은 텍스트 PGN/EPD여야 해.");
    }
    return {buffer, text};
  }

  function link(target, name, href) {
    const node = document.createElement("a");
    node.textContent = name;
    node.href = href;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
    target.append(node);
  }

  function resetFiles() {
    selected.pgn = null;
    selected.epd = null;
    for (const kind of ["pgn", "epd"]) {
      $(kind + "-file").value = "";
      $(kind + "-drop").classList.remove("chosen");
      $(kind + "-name").textContent = kind === "pgn" ?
        "최대 2,000,000바이트" : "최대 512KiB";
    }
    $("publish-consent").checked = false;
  }

  async function publish() {
    if (!IS_LOCAL || uploading || !role || !selected.pgn || !selected.epd ||
        !$("publish-consent").checked) return;
    uploading = true;
    ready();
    try {
      setStatus("PGN·EPD 텍스트 파일 확인 중…");
      const [pgn, epd] = await Promise.all([
        loadFile(selected.pgn, "PGN"),
        loadFile(selected.epd, "EPD"),
      ]);
      if (!pgn.text.includes("[White ") ||
          !pgn.text.includes("[Black ") ||
          !pgn.text.includes("[Result ")) {
        throw new Error("PGN에 White/Black/Result 태그가 없어.");
      }
      setStatus("로컬 프로그램에 PGN·EPD 전달 중…");
      const response = await fetch("/api/upload", {
        method: "POST",
        cache: "no-store",
        credentials: "omit",
        headers: {
          "Content-Type": "application/json",
          "X-OpenFishtest-Local": "1"
        },
        body: JSON.stringify({
          pgn_base64: base64FromArray(pgn.buffer),
          epd_base64: base64FromArray(epd.buffer)
        })
      });
      let body = {};
      try { body = await response.json(); } catch (_) {}
      if (response.status !== 202) {
        throw new Error(String(body.error || ("HTTP " + response.status)));
      }
      // A queued GitHub upload is NOT proof that the subsequent Actions job
      // has finished or passed. Keep the distinction visible.
      const container = $("upload-progress");
      container.replaceChildren();
      container.dataset.kind = "success";
      const title = document.createElement("strong");
      title.textContent = "✓ 파일 전달 완료 · " + body.games +
        "판 · " + body.points + "점";
      container.append(title);
      const detail = document.createElement("p");
      detail.textContent = body.method === "direct" ?
        "관리자 경로로 PR 없이 GitHub에 전달했어. Actions 검증과 Pages 반영은 아직 진행 중일 수 있어." :
        "Contributor PR을 자동 생성했어. GitHub Actions 검증 통과 후 공개돼.";
      container.append(detail);
      if (typeof body.url === "string" &&
          body.url.startsWith("https://github.com/gaong5247-cmd/OpenFishtest/")) {
        link(container, body.method === "direct" ?
          "Actions 결과 확인 ↗" : "자동 제출 PR 확인 ↗", body.url);
      }
      link(container, "공개 기보 보기 ↗",
        "https://gaong5247-cmd.github.io/OpenFishtest/#community");
      resetFiles();
    } catch (error) {
      // Local input files remain untouched even if GH API fails.
      setStatus(
        "업로드 실패: " + String(error.message || error).slice(0, 320) +
        " · 파일은 PC에 보존되어 있으니 다시 시도할 수 있어.",
        "error"
      );
    } finally {
      uploading = false;
      ready();
    }
  }

  function main() {
    $("static-notice").hidden = IS_LOCAL;
    $("local-interface").hidden = !IS_LOCAL;
    if (!IS_LOCAL) return;
    bindFile("pgn");
    bindFile("epd");
    $("refresh-auth").addEventListener("click", () => void checkLogin());
    $("publish-consent").addEventListener("change", ready);
    $("publish-button").addEventListener("click", () => void publish());
    ready();
    void checkLogin();
  }
  main();
})();
