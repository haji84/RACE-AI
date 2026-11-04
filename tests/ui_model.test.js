"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const filename = path.join(__dirname, "../web/ui-model.js");
assert.ok(fs.existsSync(filename), "the reusable UI allocation model must exist");
const M = require(filename);

assert.equal(M.validateTicket([1, 3, 2], 700), null);
assert.equal(M.validateTicket([7, 9, 12], 100, 18), null, "horse/keirin entrants are not capped at six");
for (const [lanes, amount] of [[[1, 1, 2], 100], [[0, 3, 2], 100], [[1, 3, 7], 100], [[1, 3, 2], 50], [[1, 3, 2], Infinity]]) {
  assert.ok(M.validateTicket(lanes, amount));
}
assert.deepEqual(M.allocate(2000, 3), [700, 700, 600]);
assert.deepEqual(M.allocate(200, 3), [], "never assign zero-yen tickets");
assert.deepEqual(M.allocate(3200, 32), Array(32).fill(100));
assert.deepEqual(M.allocate(3300, 33), []);
const drafts = [{lanes: [1, 2, 3], amount: 700}, {lanes: [1, 3, 2], amount: 600}];
assert.equal(M.validateDraft(drafts, 2000, 8), null);
assert.ok(M.validateDraft(drafts, 1000, 8), "over-budget candidates cannot be confirmed");
assert.ok(M.validateDraft([...drafts, {...drafts[0]}], 2000, 8), "duplicate tickets cannot be confirmed");
assert.ok(M.validateDraft(Array.from({length: 9}, (_, i) => ({lanes: [1, 2, i + 3], amount: 100})), 2000, 8, 18), "lowering the point cap preserves drafts but blocks confirmation");
assert.ok(M.validateDraft([], 2000, 8));
assert.deepEqual(M.summarize([]), {spent: 0, returned: 0, purchases: 0, settled: 0, hits: 0, roi: null, hitRate: null});
assert.deepEqual(M.summarize([{amount: 700, payout: null}, {amount: 500, payout: 2000}, {amount: 400, payout: 0}]), {spent: 1600, returned: 2000, purchases: 3, settled: 2, hits: 1, roi: 2000 / 900 * 100, hitRate: 50});

const records = [
  {race_id: "a", sport: "boat", venue: "児島", race_no: 1, event_date_jst: "2026-11-04", cutoff_at: "2026-11-04T15:00:00+09:00", participants: [{number: 1, name: "取得選手"}], prediction: null},
  {race_id: "b", sport: "horse", venue: "東京", race_no: 2, event_date_jst: "2026-11-04", cutoff_at: "2026-11-04T14:00:00+09:00", prediction: {model_id: "saved-model"}},
  {race_id: "c", sport: "boat", venue: "児島", race_no: 3, event_date_jst: "2026-11-03", cutoff_at: null, prediction: null}
];
assert.deepEqual(M.filterRaces(records, {sport: "boat", day: "2026-11-04"}).map(r => r.race_id), ["a"]);
assert.deepEqual(M.filterRaces(records, {sport: "boat", day: "2026-11-04", allDates: true, query: "取得選手"}).map(r => r.race_id), ["a"]);
assert.deepEqual(M.filterRaces(records, {allDates: true, sort: "time"}).map(r => r.race_id), ["b", "a", "c"], "unknown cutoff sorts last");
assert.deepEqual(M.filterRaces(records, {allDates: true, candidatesOnly: true, candidateRaceIds: ["a"]}).map(r => r.race_id), ["a"]);
assert.deepEqual(M.filterRaces(records, {allDates: true, forecastOnly: true}).map(r => r.race_id), ["b"]);
assert.equal(records[0].race_id, "a", "filtering never mutates saved records");
assert.deepEqual(M.filterRaces(records, {sport: "boat", day: "2026-11-04", period: "week"}).map(r => r.race_id), ["a", "c"], "week includes historical records from the same JST calendar week");
const resultRow = {prediction: {ordered_top8: [[1, 2, 3]]}, result: {status: "final", winning_combinations: [[1, 2, 3]]}};
assert.equal(M.outcome(resultRow, {predictionEligible: true, resultEligible: true}), "HIT");
assert.equal(M.outcome(resultRow, {predictionEligible: false, resultEligible: false}), "PREDICTION_UNVERIFIED", "synthetic/research apparent wins never become official hits");
assert.equal(M.outcome({...resultRow, result: {...resultRow.result, winning_combinations: [[1, 3, 2]]}}, {predictionEligible: true, resultEligible: true}), "MISS");
assert.equal(M.outcome({...resultRow, prediction: null}), "NO_FORECAST");
assert.equal(M.outcome({...resultRow, result: {status: "pending"}}, {predictionEligible: true}), "PENDING");
assert.equal(M.outcome({...resultRow, result: {status: "void"}}), "VOID");
assert.equal(M.refundSummary({refunds: [], refund_boats: [6], refund_yen: 100}), "返還対象番号 6 / 返還額 100円", "empty refund arrays cannot hide targets or amounts");
assert.equal(M.refundSummary({refund_combinations: [[1, 2, 3]], refund_yen: 0}), "返還対象券 [[1,2,3]] / 返還額 0円");
assert.equal(M.refundSummary({}), "未取得");
console.log("UI model behavior passed: variable entrants, allocation limits, manual ledger and real filters");
