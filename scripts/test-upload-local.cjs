/* Static Pages / localhost upload portal integration tests. No GitHub traffic. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const code = fs.readFileSync("docs/upload.js", "utf8");
const html = fs.readFileSync("docs/upload.html", "utf8");
assert.ok(!html.includes("github_pat_"));
assert.ok(!html.includes('id="github-token"'));
assert.ok(!code.includes("localStorage"));
assert.ok(!code.includes("sessionStorage"));

class Element {
  constructor(id = "") {
    this.id = id;
    this.textContent = "";
    this.value = "";
    this.files = [];
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.children = [];
    this.dataset = {};
    this.events = {};
    this.classes = new Set();
    this.classList = {
      add: value => this.classes.add(value),
      remove: value => this.classes.delete(value),
      contains: value => this.classes.has(value)
    };
  }
  addEventListener(key, callback) { this.events[key] = callback; }
  replaceChildren(...items) { this.children = items; }
  append(...items) { this.children.push(...items); }
  click() {}
}

function fakeFile(name, data) {
  const raw = Buffer.from(data, "utf8");
  return {
    name,
    size: raw.length,
    arrayBuffer: async () => raw.buffer.slice(
      raw.byteOffset, raw.byteOffset + raw.byteLength
    )
  };
}

function createPage(location, fetchMock) {
  const ids = [
    ...html.matchAll(/\bid="([^"]+)"/g)
  ].map(match => match[1]);
  const nodes = new Map(ids.map(id => [id, new Element(id)]));
  const get = id => {
    assert.ok(nodes.has(id), "Missing upload.html ID " + id);
    return nodes.get(id);
  };
  const context = {
    location, document: {
      getElementById: get,
      createElement: tag => new Element(tag)
    },
    fetch: fetchMock,
    TextDecoder, Uint8Array,
    btoa: data => Buffer.from(data, "binary").toString("base64"),
    console
  };
  vm.runInNewContext(code, context, {filename: "docs/upload.js"});
  return get;
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  let remoteFetches = 0;
  let get = createPage({
    hostname: "gaong5247-cmd.github.io",
    port: "", protocol: "https:"
  }, async () => {
    remoteFetches++;
    throw new Error("Static GitHub Pages must not POST credentials");
  });
  assert.equal(get("static-notice").hidden, false);
  assert.equal(get("local-interface").hidden, true);
  assert.equal(remoteFetches, 0);

  let uploadCount = 0;
  let statusCount = 0;
  get = createPage({
    hostname: "127.0.0.1", port: "8765", protocol: "http:"
  }, async (url, options = {}) => {
    assert.ok(url === "/api/status" || url === "/api/upload");
    if (url === "/api/status") {
      statusCount++;
      return {ok:true,json:async () => ({
        authenticated:true,username:"gaong5247-cmd",role:"owner",
        token_required_in_browser:false
      })};
    }
    uploadCount++;
    assert.equal(options.method,"POST");
    assert.equal(options.headers["X-OpenFishtest-Local"],"1");
    assert.equal(options.headers["Content-Type"],"application/json");
    assert.ok(!options.headers.Authorization);
    const fields=JSON.parse(options.body);
    assert.deepEqual(Object.keys(fields).sort(),
      ["epd_base64","pgn_base64"]);
    assert.ok(Buffer.from(fields.pgn_base64,"base64")
      .toString().includes('[White "Challenger"]'));
    assert.ok(Buffer.from(fields.epd_base64,"base64")
      .toString().startsWith("rnbqkbnr/"));
    return {status:202,json:async()=>({
      method:"direct",role:"owner",status:"queued_for_actions",
      games:2,points:2,url:"https://github.com/gaong5247-cmd/OpenFishtest/actions"
    })};
  });
  await tick();
  assert.ok(statusCount>=1);
  assert.equal(get("static-notice").hidden,true);
  assert.equal(get("local-interface").hidden,false);
  assert.equal(get("role-mode").textContent.includes("PR 없이"),true);
  const pgn = '[Event "Test"]\n[White "Challenger"]\n'+
    '[Black "Stockless"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n';
  const epd = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -\n";
  get("pgn-file").files = [fakeFile("games.pgn",pgn)];
  get("epd-file").files = [fakeFile("openings.epd",epd)];
  get("pgn-file").events.change();
  get("epd-file").events.change();
  assert.equal(get("publish-button").disabled,true);
  get("publish-consent").checked=true;
  get("publish-consent").events.change();
  assert.equal(get("publish-button").disabled,false);
  get("publish-button").events.click();
  await tick();await tick();
  assert.equal(uploadCount,1);
  assert.equal(get("upload-progress").dataset.kind,"success");
  assert.ok(get("upload-progress").children.length>=2);
  assert.equal(get("pgn-file").value,"");
  assert.equal(get("epd-file").value,"");

  // A secondary GitHub login gets contributor behavior without any PAT.
  get=createPage({
    hostname:"127.0.0.1",port:"8765",protocol:"http:"
  }, async () => ({ok:true,json:async()=>({
    authenticated:true,username:"ContributorTest",role:"contributor",
    requires_pr:true
  })}));
  await tick();
  assert.ok(get("role-mode").textContent.includes("PR 자동 제출"));
  console.log("Local upload portal UI passed: owner/contributor and no tokens in JS.");
})().catch(error=>{
  console.error(error);
  process.exitCode=1;
});
