// CI contract for the simplified one-click static dashboard.
"use strict";
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("docs/index.html", "utf8");
const translations = fs.readFileSync("docs/i18n.js", "utf8");
const app = fs.readFileSync("docs/app.js", "utf8");
const scoreModule = fs.readFileSync("docs/score.js", "utf8");
const ctx = {window: {}};
vm.runInNewContext(translations, ctx, {filename:"docs/i18n.js"});
const languages = ctx.window.OPENFISHTEST_LOCALES;

if (!languages || !languages.en || !languages.ko) {
  throw new Error("Missing English/Korean language dictionaries");
}
const keys = [
  ...html.matchAll(/data-i18n(?:-placeholder)?="([^"]+)"/g)
].map(match => match[1]);
const dynamicKeys = [...app.matchAll(/\bt\("([A-Za-z0-9_]+)"\)/g)]
  .map(match => match[1]);
for (const language of ["en","ko"]) {
  for (const key of [...new Set([...keys,...dynamicKeys])]) {
    if (typeof languages[language][key] !== "string" ||
        languages[language][key].length === 0) {
      throw new Error("Missing " + language + " translation: " + key);
    }
  }
}

const domIds = [...app.matchAll(/\$\("([a-z0-9-]+)"\)/g)]
  .map(match => match[1]);
for (const id of new Set(domIds)) {
  if (!html.includes('id="' + id + '"')) {
    throw new Error("Missing JS-controlled element: " + id);
  }
}
for (const id of [
  "featured-match", "results-rows", "result-search", "result-sort",
  "calc-wins", "calc-draws", "calc-losses", "refresh-button",
  "stat-games", "contribute", "community", "arena", "lang-switch"
]) {
  if (!html.includes('id="' + id + '"')) {
    throw new Error("Missing one-click feature: " + id);
  }
}
if (!html.includes('<script src="./score.js"') ||
    !html.includes('<script src="./app.js"')) {
  throw new Error("Scoring and app scripts must load in the right order");
}
if (html.includes('id="arena-submit"') || html.includes('id="arena-zip"')) {
  throw new Error("Deprecated HTTPS upload form must not appear on Pages");
}
if (!scoreModule.includes("const TARGET_PERCENT = 55")) {
  throw new Error("Missing shared 55% score-screening rule");
}
console.log(
  "One-click UI: " + new Set(keys).size + " translated labels, " +
  new Set(domIds).size + " DOM references and live scorer validated."
);
