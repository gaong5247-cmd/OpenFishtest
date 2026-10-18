/* OpenFishtest existing-PGN web uploader.
 *
 * Static GitHub Pages cannot accept files itself. An authorized repository
 * owner supplies a short-lived, single-repository Fine-grained PAT (Contents:
 * read/write) in this tab. The token is NEVER stored, logged, sent to Pages,
 * or included in a public commit. All requests using it go to api.github.com.
 *
 * A browser action creates ONE Git commit in a new data-only
 * community-upload/<id> branch, which triggers a trusted GitHub Actions
 * publisher. No PR or Fastchess rerun is created.
 *
 * This is OWNER-ONLY. Untrusted community users should NOT grant a public
 * website repository write permission; use the PR Contributor flow instead.
 */
"use strict";
(function () {
  const $ = id => document.getElementById(id);
  const REPO = "gaong5247-cmd/OpenFishtest";
  const OWNER = "gaong5247-cmd";
  const API = "https://api.github.com";
  const MAX_PGN = 2_000_000;
  const MAX_EPD = 512 * 1024;
  const HEX_40 = /^[0-9a-f]{40}$/;
  const HEX_24 = /^[0-9a-f]{24}$/;
  const selected = {pgn:null,epd:null};
  let authorized = false;
  let busy = false;

  function status(message, kind = "info") {
    const output = $("upload-progress");
    output.textContent = message;
    output.dataset.kind = kind;
  }

  function authStatus(message, kind = "info") {
    const element = $("auth-status");
    element.textContent = message;
    element.dataset.kind = kind;
  }

  function updateControls() {
    $("publish-button").disabled = busy || !authorized ||
      !selected.pgn || !selected.epd || !$("publish-consent").checked;
    $("check-auth").disabled = busy;
  }

  function selectedFile(type, file) {
    const isPgn = type === "pgn";
    const limit = isPgn ? MAX_PGN : MAX_EPD;
    const extension = isPgn ? /\.pgn$/i : /\.epd$/i;
    if (!file || !extension.test(file.name)) {
      status(
        isPgn ? "PGN 파일(.pgn)만 선택할 수 있어." :
          "정규화된 EPD 파일(.epd)만 선택할 수 있어.",
        "error"
      );
      return;
    }
    if (!Number.isFinite(file.size) || file.size <= 0 || file.size > limit) {
      status(
        isPgn ?
          "PGN은 2,000,000바이트 이하만 가능해." :
          "이 게시 방식의 EPD는 512KiB 이하만 가능해. Contributor가 생성한 openings.epd를 선택해.",
        "error"
      );
      return;
    }
    selected[type] = file;
    $(type + "-name").textContent = file.name + " · " +
      (file.size / 1024).toFixed(1) + " KiB";
    $(type + "-drop").classList.add("chosen");
    status("두 파일을 선택했다면 GitHub 인증 후 게시를 시작해.");
    updateControls();
  }

  function bindDrop(type) {
    const drop = $(type + "-drop");
    const input = $(type + "-file");
    drop.addEventListener("click", () => input.click());
    drop.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });
    input.addEventListener("change", () => {
      selectedFile(type, input.files?.[0]);
    });
    for (const eventName of ["dragenter", "dragover"]) {
      drop.addEventListener(eventName, event => {
        event.preventDefault();
        drop.classList.add("dragging");
      });
    }
    for (const eventName of ["dragleave","drop"]) {
      drop.addEventListener(eventName, event => {
        event.preventDefault();
        drop.classList.remove("dragging");
      });
    }
    drop.addEventListener("drop", event => {
      if (event.dataTransfer?.files?.length !== 1) {
        status("한 번에 파일 하나씩 PGN/EPD 칸에 넣어줘.", "error");
        return;
      }
      selectedFile(type, event.dataTransfer.files[0]);
    });
  }

  async function github(method, path, token, payload) {
    // No untrusted arbitrary URL argument, only a fixed GitHub host.
    if (!path.startsWith("/")) throw new Error("Invalid GitHub API path");
    const result = await fetch(API + path, {
      method,
      cache: "no-store",
      headers: {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        ...(payload === undefined ? {} : {"Content-Type":"application/json"})
      },
      ...(payload === undefined ? {} : {body:JSON.stringify(payload)})
    });
    let body = {};
    try { body = await result.json(); } catch (_) {}
    if (!result.ok) {
      // Never stringify headers, the token, arbitrary file contents or a
      // request object into user-visible errors.
      const sanitized = (
        typeof body.message === "string" ? body.message : "GitHub API request failed"
      ).slice(0, 240);
      throw new Error("GitHub HTTP " + result.status + ": " + sanitized);
    }
    return body;
  }

  function tokenValue() {
    return $("github-token").value.trim();
  }

  async function checkAuth() {
    if (busy) return;
    if (authorized) {
      $("github-token").value = "";
      authorized = false;
      $("check-auth").textContent = "권한 확인";
      authStatus("관리자 인증 해제됨", "info");
      updateControls();
      return;
    }
    const token = tokenValue();
    if (token.length < 25) {
      authStatus("Fine-grained PAT를 입력해 줘.", "error");
      return;
    }
    busy = true;
    updateControls();
    authStatus("GitHub 계정 확인 중…");
    try {
      const user = await github("GET", "/user", token);
      if ((user.login || "").toLowerCase() !== OWNER.toLowerCase()) {
        throw new Error("이 화면은 저장소 소유자 gaong5247-cmd 계정만 사용 가능해. 다른 기여자는 PR 방식을 이용해 줘.");
      }
      const repo = await github("GET", "/repos/" + REPO, token);
      if (repo.full_name !== REPO ||
          (repo.permissions && !repo.permissions.push)) {
        throw new Error("OpenFishtest 저장소 Contents 읽기/쓰기 권한이 부족해.");
      }
      authorized = true;
      $("check-auth").textContent = "인증 해제";
      authStatus("✓ 관리자 gaong5247-cmd 확인됨 · 토큰은 이 탭에만 유지", "success");
    } catch (error) {
      authorized = false;
      authStatus(error.message || "GitHub 인증 실패", "error");
    } finally {
      busy = false;
      updateControls();
    }
  }

  function encodeBase64(data) {
    // Bounded file sizes: <=2MB + 512KiB. Chunked conversion avoids
    // argument stack overflow and large temporary arrays.
    const chunkSize = 0x6000;
    let result = "";
    for (let pos = 0; pos < data.length; pos += chunkSize) {
      const chunk = data.subarray(pos, pos + chunkSize);
      result += String.fromCharCode(...chunk);
    }
    return btoa(result);
  }

  async function readText(file, label) {
    const buffer = await file.arrayBuffer();
    try {
      const text = new TextDecoder("utf-8", {fatal:true}).decode(buffer);
      if (text.includes("\u0000")) {
        throw new Error(label + " 파일에 바이너리 내용이 포함되어 있어.");
      }
      return {buffer, text};
    } catch (error) {
      throw new Error(
        label + " 파일은 유효한 UTF-8 텍스트여야 해. " +
        String(error.message || "").slice(0, 90)
      );
    }
  }

  function randomId() {
    const bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, n => n.toString(16).padStart(2,"0")).join("");
  }

  async function stageFiles(token, pgn, epd) {
    const id = randomId();
    if (!HEX_24.test(id)) throw new Error("Invalid upload identifier");
    const base = "/repos/" + REPO;
    status("1/5 · GitHub main 브랜치 조회 중…");
    const ref = await github("GET", base + "/git/ref/heads/main", token);
    const baseSha = ref?.object?.sha;
    if (!HEX_40.test(baseSha || "")) {
      throw new Error("기준 main 커밋을 확인할 수 없어.");
    }
    const baseCommit = await github(
      "GET", base + "/git/commits/" + baseSha, token
    );
    if (!HEX_40.test(baseCommit?.tree?.sha || "")) {
      throw new Error("기준 Git 트리 확인에 실패했어.");
    }

    const prefix = "submissions/" + id + "/";
    status("2/5 · PGN Git 데이터 생성 중…");
    const rawPgn = new Uint8Array(pgn);
    const pg = await github("POST", base + "/git/blobs", token, {
      content: encodeBase64(rawPgn), encoding: "base64"
    });
    if (!HEX_40.test(pg.sha || "")) throw new Error("PGN Git blob 오류");

    status("3/5 · EPD Git 데이터 생성 중…");
    const rawEpd = new Uint8Array(epd);
    const ep = await github("POST", base + "/git/blobs", token, {
      content: encodeBase64(rawEpd), encoding: "base64"
    });
    if (!HEX_40.test(ep.sha || "")) throw new Error("EPD Git blob 오류");

    const tree = await github("POST", base + "/git/trees", token, {
      base_tree: baseCommit.tree.sha,
      tree: [
        {path:prefix + "games.pgn",mode:"100644",type:"blob",sha:pg.sha},
        {path:prefix + "openings.epd",mode:"100644",type:"blob",sha:ep.sha}
      ]
    });
    if (!HEX_40.test(tree.sha || "")) throw new Error("Git tree 오류");

    status("4/5 · PGN·EPD 두 파일만 담긴 임시 커밋 생성 중…");
    const commit = await github("POST", base + "/git/commits", token, {
      message:"data(owner-upload): stage PGN and EPD " + id,
      tree:tree.sha, parents:[baseSha]
    });
    if (!HEX_40.test(commit.sha || "")) throw new Error("Git commit 오류");

    status("5/5 · PR 없이 검증 작업 시작 중…");
    await github("POST", base + "/git/refs", token, {
      ref:"refs/heads/community-upload/" + id,
      sha:commit.sha
    });
    return id;
  }

  function appendLink(container, text, url) {
    const link = document.createElement("a");
    link.textContent = text;
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    container.append(link);
    return link;
  }

  function showNextSteps(id) {
    const container = $("upload-progress");
    container.replaceChildren();
    container.dataset.kind = "success";
    const intro = document.createElement("strong");
    intro.textContent = "✓ 전송 완료! #" + id;
    container.append(intro);
    const help = document.createElement("p");
    help.textContent = "이제 GitHub Actions가 PGN과 EPD를 검증해서 자동 게시해. 검증 실패 시 원래 파일 그대로 다시 올리면 돼. 대국이나 PR은 다시 만들 필요 없어.";
    container.append(help);
    appendLink(
      container, "자동 게시 작업 확인 ↗",
      "https://github.com/" + REPO + "/actions/workflows/community-direct-upload.yml"
    );
    appendLink(
      container, "공개 기보 결과 보기 ↗",
      "./#community"
    );
  }

  async function publish() {
    if (busy || !authorized || !selected.pgn || !selected.epd ||
        !$("publish-consent").checked) return;

    // Read only the current token and explicitly selected small source files.
    // No localStorage, cookies, analytics or external script dependencies.
    const token = tokenValue();
    if (token.length < 25) {
      authorized = false;
      updateControls();
      authStatus("토큰이 비어 있어. 다시 인증해 줘.", "error");
      return;
    }
    busy = true;
    updateControls();
    try {
      const pgn = selected.pgn;
      const epd = selected.epd;
      if (pgn.size > MAX_PGN || epd.size > MAX_EPD) {
        throw new Error("PGN 2MB 또는 EPD 512KiB 제한을 초과했어.");
      }
      status("선택한 PGN·EPD가 UTF-8 텍스트인지 확인 중…");
      const [pgnData, epdData] = await Promise.all([
        readText(pgn, "PGN"), readText(epd, "EPD")
      ]);
      if (
        !pgnData.text.includes("[White ") ||
        !pgnData.text.includes("[Black ") ||
        !pgnData.text.includes("[Result ")
      ) {
        throw new Error("PGN에서 필수 대국 헤더를 찾을 수 없어.");
      }
      if (!epdData.text.trim()) {
        throw new Error("EPD 파일에 오프닝 포지션이 없어.");
      }
      // Cryptographic digests are calculated on the server as well; the
      // GitHub-side action is the authoritative chess validator.
      const id = await stageFiles(
        token, pgnData.buffer, epdData.buffer
      );
      showNextSteps(id);
      // Ready for another upload in the same tab without repeated auth.
      selected.pgn = null;
      selected.epd = null;
      $("pgn-file").value = "";
      $("epd-file").value = "";
      $("pgn-drop").classList.remove("chosen");
      $("epd-drop").classList.remove("chosen");
      $("pgn-name").textContent = "PGN 최대 2,000,000바이트";
      $("epd-name").textContent = "EPD 최대 512KiB · 대국에 사용한 정규화 북";
      $("publish-consent").checked = false;
    } catch (error) {
      status(
        String(error.message || "GitHub 업로드 오류").slice(0, 500) +
        " · 같은 기보를 고쳐서 다시 게시할 수 있어.",
        "error"
      );
    } finally {
      busy = false;
      updateControls();
    }
  }

  function init() {
    bindDrop("pgn");
    bindDrop("epd");
    $("check-auth").addEventListener("click", () => void checkAuth());
    $("github-token").addEventListener("input", () => {
      authorized = false;
      $("check-auth").textContent = "권한 확인";
      authStatus("토큰이 변경됨 · GitHub 권한을 다시 확인해 줘");
      updateControls();
    });
    $("publish-consent").addEventListener("change", updateControls);
    $("publish-button").addEventListener("click", () => void publish());
    updateControls();
  }
  init();
})();
