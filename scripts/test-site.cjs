/* Browser-free interactive smoke test with a tiny DOM adapter (no npm).
 * Tests the actual public app.js against realistic GitHub community records.
 */
"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const score = require("../docs/score.js");

class Element {
  constructor(id = "") {
    this.id = id;
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.events = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.className = "";
    this.classes = new Set();
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name),
      contains: name => this.classes.has(name),
      toggle: (name, value) => {
        const v = value === undefined ? !this.classes.has(name) : value;
        if (v) this.classes.add(name);
        else this.classes.delete(name);
        return v;
      }
    };
  }
  replaceChildren(...args) { this.children = args; }
  append(...args) { this.children.push(...args); }
  addEventListener(name, listener) { this.events[name] = listener; }
  setAttribute(name, value) { this.attributes[name] = value; }
  scrollIntoView() {}
}

(async () => {
  const html = fs.readFileSync("docs/index.html", "utf8");
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
  const dom = new Map(ids.map(id => [id, new Element(id)]));
  const doc = {
    documentElement: {lang:"en"},
    getElementById: id => {
      assert.ok(dom.has(id), "app referenced absent HTML ID: " + id);
      return dom.get(id);
    },
    createElement: tag => new Element(tag),
    querySelectorAll: () => []
  };
  const $ = id => doc.getElementById(id);
  const now = "2026-10-18T07:00:00+00:00";
  const sample = [
    {id:"a".repeat(20),contributor:"TestA",submitted_at:"2026-10-18T06:00:00+00:00",
      games:200,wins:60,draws:59,losses:81,points:89.5,
      penta:[14,24,35,23,4],pgn_sha256:"b".repeat(64),source_pr:18},
    {id:"c".repeat(20),contributor:"TestB",submitted_at:now,
      games:200,wins:25,draws:73,losses:102,points:61.5,
      penta:[16,52,26,5,1],pgn_sha256:"d".repeat(64),source_pr:21}
  ];
  const idx = {version:1,updated_at:now,entries:sample};
  const languages = {window:{}};
  vm.runInNewContext(
    fs.readFileSync("docs/i18n.js","utf8"),languages
  );
  const window = {
    OpenFishtestScores:score,
    OPENFISHTEST_LOCALES: languages.window.OPENFISHTEST_LOCALES
  };
  let fetchCount = 0;
  const context = {
    window,
    document:doc,
    navigator:{language:"ko-KR"},
    localStorage:{getItem:()=>null,setItem:()=>{}},
    fetch:async url => {
      assert.equal(url,"./data/community/index.json");
      fetchCount += 1;
      return {ok:true,json:async()=>idx};
    },
    setInterval:()=>0,
    console
  };
  vm.runInNewContext(
    fs.readFileSync("docs/app.js","utf8"),context,{filename:"docs/app.js"}
  );
  // Let asynchronous fetch/json microtasks settle.
  for (let i=0; i<8; i++) await Promise.resolve();
  assert.ok(fetchCount>=1);
  assert.equal(doc.documentElement.lang,"ko");
  assert.equal($("stat-submissions").textContent,"2");
  assert.equal($("stat-games").textContent,"400");
  assert.equal($("stat-contributors").textContent,"2");
  assert.equal($("stat-latest").textContent,"30.75%");
  assert.equal($("featured-percent").textContent,"30.75%");
  assert.equal($("featured-points").textContent,"61.5 / 200점");
  assert.equal($("calc-wins").value,"25");
  assert.equal($("calc-draws").value,"73");
  assert.equal($("calc-losses").value,"102");
  assert.equal($("calc-rate").textContent,"30.75%");
  assert.ok($("featured-ci").textContent.includes("%"));
  assert.equal($("results-rows").children.length,2);

  // Row score link should load that match's counts into the calculator.
  const row=$("results-rows").children[1];
  row.children[4].children[0].events.click();
  assert.equal($("calc-wins").value,"60");
  assert.equal($("calc-draws").value,"59");
  assert.equal($("calc-losses").value,"81");
  assert.equal($("calc-rate").textContent,"44.75%");

  // A 200-game 110-point result is EXACTLY 55%, no fixed-55 error.
  $("calc-wins").value="100";
  $("calc-draws").value="20";
  $("calc-losses").value="80";
  $("calc-wins").events.input();
  assert.equal($("calc-points").textContent,"110 / 200");
  assert.equal($("calc-target").textContent,"110 / 200");
  assert.equal($("calc-rate").textContent,"55.0%");

  // Language switching must keep the computed score consistent.
  $("lang-switch").events.click();
  assert.equal(doc.documentElement.lang,"en");
  assert.equal($("calc-rate").textContent,"55.0%");
  assert.equal($("stat-games").textContent,"400");
  console.log("Static UI smoke test passed: real rows, formulas, calculator, EN/KO.");
})().catch(err=>{console.error(err);process.exitCode=1;});
