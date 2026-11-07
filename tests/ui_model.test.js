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
const venueRows = Object.freeze([
  Object.freeze({race_id:"coded", sport:"boat", venue:"場コード01", race_no:1}),
  Object.freeze({race_id:"named", sport:"boat", venue:"桐生", race_no:2}),
  Object.freeze({race_id:"other-venue", sport:"boat", venue:"場コード24", race_no:1}),
  Object.freeze({race_id:"other-sport", sport:"horse", venue:"場コード01", race_no:1})
]);
const venueBefore = JSON.stringify(venueRows);
assert.deepEqual(M.filterRaces(venueRows, {sport:"boat", query:"桐生"}).map(r=>r.race_id), ["coded","named"], "venue-name searches find both coded history and named imports");
assert.deepEqual(M.filterRaces(venueRows, {sport:"boat", venue:"桐生"}).map(r=>r.race_id), ["coded","named"], "one named venue filter includes both stored representations");
assert.deepEqual(M.filterRaces(venueRows, {sport:"boat", query:"場コード01"}).map(r=>r.race_id), ["coded"], "original venue codes remain searchable");
assert.deepEqual(M.filterRaces(venueRows, {sport:"boat", venue:"場コード01"}).map(r=>r.race_id), ["coded"], "existing code filter values remain valid");
for (const [code,name] of [['01','桐生'],['02','戸田'],['03','江戸川'],['04','平和島'],['05','多摩川'],['06','浜名湖'],['07','蒲郡'],['08','常滑'],['09','津'],['10','三国'],['11','びわこ'],['12','住之江'],['13','尼崎'],['14','鳴門'],['15','丸亀'],['16','児島'],['17','宮島'],['18','徳山'],['19','下関'],['20','若松'],['21','芦屋'],['22','福岡'],['23','唐津'],['24','大村']]) {
  assert.equal(M.venueName({sport:"boat",venue:"場コード"+code}),name);
}
for (const venue of [null,undefined,'場コード00','場コード25','場コード1','場コード01 test','架空の会場','桐生']) {
  assert.equal(M.venueName({sport:"boat",venue}),venue,"unknown venue metadata is never guessed from a race ID");
}
assert.equal(M.venueName(venueRows[3]),"場コード01","venue codes are scoped to their sport");
assert.equal(JSON.stringify(venueRows),venueBefore,"presentation must preserve stored venue codes and race identities");
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

const catalogPath = path.join(__dirname, "../web/existing-model-catalog.js");
assert.ok(fs.existsSync(catalogPath), "all active existing families must be available without a provider request");
const catalog = require(catalogPath);
assert.equal(catalog.models.length, 15);
assert.equal(new Set(catalog.models.map(m => m.model_id)).size, 15);
for (const [sport, expected] of [["boat", 14], ["keirin", 5], ["autorace", 6], ["horse", 5]]) {
  const emptyCoverage = M.modelCoverage([], catalog.models, {sport});
  assert.equal(emptyCoverage.models.length, 15, "unconnected active families never disappear");
  assert.equal(emptyCoverage.applicable_models, expected);
  assert.equal(emptyCoverage.not_applicable_models, 15 - expected);
  assert.equal(emptyCoverage.target_races, 0);
  assert.equal(emptyCoverage.counts_only, true);
  assert.ok(emptyCoverage.models.filter(m => m.applicable).every(m => m.state === "INPUT_MISSING"));
  assert.ok(emptyCoverage.models.filter(m => !m.applicable).every(m => m.state === "NOT_APPLICABLE" && m.target_races === 0 && m.missing_races === 0));
}
const sharedId = "multisport-factor-interaction-v1";
const coverageInput = [
  {race_id: "boat:one", sport: "boat", scope: "research", prediction: {model_id: sharedId, model_version: "v1", stage: "P0"}, comparison_predictions: [
    {model_id: sharedId, model_version: "v2", stage: "P0"},
    {model_id: sharedId, model_version: "v2", stage: "P1"},
    {model_id: "outside-the-catalog", model_version: "v1", stage: "P0"}
  ]},
  {race_id: "boat:missing", sport: "boat", scope: "research", prediction: null},
  {race_id: "boat:unknown-stage", sport: "boat", scope: "synthetic", prediction: {model_id: sharedId, model_version: "v1", stage: "UNKNOWN"}},
  {race_id: "horse:ignored", sport: "horse", scope: "research", prediction: {model_id: sharedId, model_version: "v1", stage: "P0"}}
];
const beforeCoverage = JSON.stringify(coverageInput);
const coverage = M.modelCoverage(coverageInput, catalog.models, {sport: "boat"});
const sharedCoverage = coverage.models.find(m => m.model_id === sharedId);
assert.equal(coverage.target_races, 3, "selected-sport missing forecasts remain in denominator");
assert.equal(sharedCoverage.saved_races, 2, "versions and stages do not double count a race");
assert.equal(sharedCoverage.missing_races, 1);
assert.equal(sharedCoverage.stages.P0.target_races, 3);
assert.equal(sharedCoverage.stages.P0.saved_races, 1);
assert.equal(sharedCoverage.stages.P0.missing_races, 2);
assert.equal(sharedCoverage.stages.P1.target_races, 3);
assert.equal(sharedCoverage.stages.P1.saved_races, 1);
assert.equal(sharedCoverage.stages.UNKNOWN.saved_races, 1);
assert.equal(sharedCoverage.versions.length, 4, "saved scope/stage/version variants stay separate");
assert.deepEqual(coverage.additional_model_ids, ["outside-the-catalog"]);
assert.ok(coverage.models.filter(m => m.applicable && m.model_id !== sharedId).every(m => m.saved_races === 0 && m.missing_races === 3));
assert.equal(JSON.stringify(coverageInput), beforeCoverage, "coverage must never rewrite saved original predictions");
assert.equal(Object.hasOwn(sharedCoverage, "hit8"), false, "saved-count coverage never fabricates performance");
const specialistId = catalog.models.find(m => m.applicable_sports.length === 1 && m.applicable_sports[0] === "boat").model_id;
const incompatible = M.modelCoverage([{race_id: "horse:bad-family", sport: "horse", scope: "research", prediction: {model_id: specialistId, model_version: "v1", stage: "P0"}}], catalog.models, {sport: "horse"}).models.find(m => m.model_id === specialistId);
assert.equal(incompatible.state, "NOT_APPLICABLE");
assert.equal(incompatible.saved_races, 0, "a specialist import cannot turn another sport operational");
assert.equal(incompatible.inapplicable_saved_races, 1, "the incompatible supplied original stays visible as a mismatch");
const autoCoverage=M.modelCoverage([
  {race_id:"auto:saved",sport:"autorace",scope:"research",prediction:{model_id:sharedId,model_version:"v1",stage:"A_PRE_TRIAL"},comparison_predictions:[{model_id:sharedId,model_version:"v1",stage:"B_POST_TRIAL"}]},
  {race_id:"auto:missing",sport:"autorace",scope:"research",prediction:null}
],catalog.models,{sport:"autorace"});
const autoShared=autoCoverage.models.find(m=>m.model_id===sharedId);
assert.deepEqual(autoCoverage.display_stages,["A_PRE_TRIAL","B_POST_TRIAL"]);
assert.equal(autoShared.stages.A_PRE_TRIAL.saved_races,1);
assert.equal(autoShared.stages.B_POST_TRIAL.saved_races,1);
assert.equal(autoShared.stages.A_PRE_TRIAL.missing_races,1);
assert.equal(autoShared.stages.UNKNOWN.saved_races,0,"native trial phases cannot disappear into unknown");
const declaredAuto=M.modelCoverage([{race_id:"auto:declared",sport:"autorace",scope:"research",scheduled_stages:["P0","A_PRE_TRIAL","B_POST_TRIAL"],
  prediction:{model_id:sharedId,model_version:"v1",stage:"P0"},dispatch_slots:[{stage:"A_PRE_TRIAL",model_id:sharedId,status:"INPUT_MISSING"},{stage:"B_POST_TRIAL",model_id:sharedId,status:"INPUT_MISSING"}]}],catalog.models,{sport:"autorace"});
assert.deepEqual(declaredAuto.display_stages,["P0","A_PRE_TRIAL","B_POST_TRIAL"],"declared missing phases stay visible without adding unscheduledP1");
const declaredShared=declaredAuto.models.find(m=>m.model_id===sharedId);
assert.equal(declaredShared.stages.B_POST_TRIAL.target_races,1);assert.equal(declaredShared.stages.B_POST_TRIAL.missing_races,1);
assert.equal(declaredShared.stages.P1.target_races,0);
assert.deepEqual(coverage.display_stages,["P0","P1"]);
const unknownMetadata=[{race_id:"actual:opaque-race",sport:"boat",event_date_jst:"2030-01-01",venue:null,race_no:null,prediction:null}];
assert.equal(M.filterRaces(unknownMetadata,{sport:"boat",day:"2030-01-01",query:"opaque",sort:"venue"}).length,1);
assert.equal(M.filterRaces([...unknownMetadata,{...unknownMetadata[0],race_id:"other:opaque-race",venue:"known"}],{sport:"boat",day:"2030-01-01",sort:"venue"}).length,2);
console.log("UI model behavior passed: allocation, manual ledger, real filters and all fifteen active model families");
