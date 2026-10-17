// Static CI: every localized element has EN+KO text; JS IDs exist in HTML.
"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("docs/index.html", "utf8");
const translations = fs.readFileSync("docs/i18n.js", "utf8");
const client = fs.readFileSync("docs/app.js", "utf8");
const ctx = {window: {}};
vm.runInNewContext(translations, ctx, {filename:"docs/i18n.js"});
const languages = ctx.window.OPENFISHTEST_LOCALES;
if (!languages || !languages.en || !languages.ko) {
  throw new Error("Missing language dictionaries");
}
const keys = [...html.matchAll(/data-i18n(?:-placeholder)?="([^"]+)"/g)].map(m => m[1]);
for (const locale of ["en","ko"]) {
  for (const key of keys) {
    if (typeof languages[locale][key] !== "string") {
      throw new Error("Missing " + locale + " translation: " + key);
    }
  }
}
const ids = [...client.matchAll(/\$\("([a-z0-9-]+)"\)/g)].map(m => m[1]);
for (const id of ids) {
  if (!html.includes('id="' + id + '"')) throw new Error("Missing DOM ID " + id);
}
for (const id of ["engine-form","test-form","worker-form","chess-board","lang-switch"]) {
  if (!html.includes('id="' + id + '"')) throw new Error("Missing community feature " + id);
}
console.log("Verified " + keys.length + " translated bindings and " +
  new Set(ids).size + " DOM IDs.");
