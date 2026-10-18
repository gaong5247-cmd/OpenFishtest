/* CI: exact scoring, variable match lengths, and real published records.
 * Do not change 55%-of-games into a fixed 55 raw points.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const S = require("../docs/score.js");

const equal = (actual, expected, tolerance=1e-9) =>
  assert.ok(Math.abs(actual-expected) <= tolerance,
    "expected "+expected+", got "+actual);

let x=S.calculate(29,46,25);
assert.equal(x.games,100);
equal(x.points,52);
equal(x.scorePercent,52);
equal(x.perHundred,52);
equal(x.qualifyingPoints,55);
assert.equal(x.passedScreen,false);

x=S.calculate(25,73,102,[16,52,26,5,1]);
assert.equal(x.games,200);
equal(x.points,61.5);
equal(x.scorePercent,30.75);
equal(x.perHundred,30.75);
equal(x.qualifyingPoints,110);
assert.equal(x.passedScreen,false);
assert.equal(x.confidence?.method,"paired_score_normal_approximation");
assert.ok(x.confidence.lowPercent < x.scorePercent);
assert.ok(x.confidence.highPercent > x.scorePercent);
assert.ok(x.estimatedElo < 0);

x=S.calculate(60,59,81,[14,24,35,23,4]);
equal(x.points,89.5);
equal(x.scorePercent,44.75);
assert.equal(x.passedScreen,false);

x=S.calculate(59,67,74,[14,21,37,22,6]);
equal(x.points,92.5);
equal(x.scorePercent,46.25);
assert.equal(x.passedScreen,false);

// The same 55% means 55 points / 100, but 110 / 200.
const hundred=S.calculate(54,2,44);
equal(hundred.points,55);
equal(hundred.scorePercent,55);
assert.equal(hundred.passedScreen,true);
const twoHundred=S.calculate(100,20,80);
equal(twoHundred.points,110);
equal(twoHundred.scorePercent,55);
assert.equal(twoHundred.passedScreen,true);
const notQualified=S.calculate(54,2,144);
equal(notQualified.points,55);
equal(notQualified.scorePercent,27.5);
assert.equal(notQualified.passedScreen,false);

const below=S.calculate(54,1,45);
equal(below.points,54.5);
assert.equal(below.passedScreen,false);

assert.equal(S.calculate(0,0,0),null);
assert.equal(S.calculate(-1,0,5),null);
assert.equal(S.calculate(3.5,1,4),null);
assert.equal(S.calculate(9999999,0,1),null);
assert.equal(S.calculate(0,0,100).estimatedElo,null);
assert.equal(S.calculate(100,0,0).estimatedElo,null);
assert.equal(S.calculate(9,1,0).estimatedElo,null); // n < 20

assert.equal(S.entryScore({games:100,wins:29,draws:46,losses:25,
  points:55}),null);
assert.equal(S.entryScore({games:100,wins:29,draws:46,losses:25,
  points:52})?.points,52);

const sample=[
  {id:"a".repeat(20),games:100,wins:29,draws:46,losses:25,
   points:52,pgn_sha256:"b".repeat(64),
   contributor:"TestA",submitted_at:"2026-10-18T06:00:00Z"},
  {id:"c".repeat(20),games:200,wins:25,draws:73,losses:102,
   points:61.5,pgn_sha256:"d".repeat(64),
   contributor:"TestB",submitted_at:"2026-10-18T07:00:00Z"},
  {id:"e".repeat(20),games:200,wins:25,draws:73,losses:102,
   points:61.5,pgn_sha256:"d".repeat(64),
   contributor:"TestB",submitted_at:"2026-10-18T08:00:00Z"}
];
const unique=S.validEntries({entries:sample});
assert.equal(unique.length,2);
assert.equal(unique[0].contributor,"TestB");
const summary=S.summarize(unique);
assert.deepEqual(summary,{
  submissions:2,games:300,points:113.5,contributors:2
});

// Future valid contributions may be appended; verify all current metadata.
const published=JSON.parse(fs.readFileSync(
  "docs/data/community/index.json","utf8"
));
for (const entry of published.entries) {
  const p=S.entryScore(entry);
  assert.ok(p,"inconsistent published match "+entry.id);
  equal(p.points,entry.wins + entry.draws/2);
  equal(p.scorePercent,100*p.points/entry.games);
  assert.equal(p.verifiedOrigin,false);
}
console.log("Score tests passed ("+published.entries.length+" actual published records).");
