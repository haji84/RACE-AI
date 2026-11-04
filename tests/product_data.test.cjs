"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const target = path.join(__dirname, "../web/product-data.js");
let M;
try { M = require(target); } catch (error) { if (error.code !== "MODULE_NOT_FOUND") throw error; }
const SHA = "a".repeat(64), INPUT = "b".repeat(64), RESULT = "c".repeat(64);
const cutoff = "2030-01-01T10:00:00+09:00";
function prediction(stage = "P0", extra = {}) {
  return {stage, model_id:"existing-model", model_version:"saved-v1", ordered_top8:[[1,2,3],[1,3,2]],
    generated_at:"2030-01-01T09:00:00+09:00", persisted_at:"2030-01-01T09:01:00+09:00", cutoff_at:cutoff,
    input_sha256:INPUT, prediction_sha256:SHA, odds_independent:true, external_receipt_verified:true,
    external_receipt:{authority:"saved-importer", content_sha256:SHA, source_sha256:INPUT,
      server_received_at:"2030-01-01T09:01:00+09:00"}, ...extra};
}
function result(extra = {}) {
  return {status:"final", winning_combinations:[[1,2,3]], confirmed_at:"2030-01-01T10:20:00+09:00",
    payout_yen_per_100:1500, official:true, source_sha256:RESULT,
    evidence:{authority:"saved-official-result-importer", content_sha256:RESULT,
      observed_at:"2030-01-01T10:20:00+09:00"}, ...extra};
}
function row(id = "boat:2030-01-01:test:1", extra = {}) {
  return {race_id:id, sport:"boat", venue:"保存原本テスト場", race_no:1, cutoff_at:cutoff,
    offering_status:"TRIFECTA_OFFERED", source_provenance:"SAVED_OWNER_IMPORT", source_sha256:INPUT,
    scope:"official", prediction:prediction(), result:result(), ...extra};
}
const pack = (records, dataset_status = "REAL_REPORTED") => ({schema:"RACE_AI_FORECAST_AUDIT_V1", dataset_status, records});

test("read-only saved-record adapter exposes its public interface", () => {
  assert.ok(fs.existsSync(target), "saved-record adapter has not been implemented");
  for (const key of ["parse","summary","selectPrediction","modelGroups","eligiblePrediction","eligibleResult","candidates"])
    assert.equal(typeof M[key], "function", key);
});
test("parse clones and freezes original provenance, dates, participants and saved tickets", () => {
  const raw = pack([row(undefined, {participants:[{number:1, name:"保存名"}], observed_at:"2030-01-01T08:59:00+09:00"})]);
  const before = JSON.stringify(raw), parsed = M.parse(raw), r = parsed.records[0];
  assert.equal(JSON.stringify(raw), before);
  assert.notEqual(r, raw.records[0]);
  assert.equal(r.event_date_jst, "2030-01-01");
  assert.equal(r.source_sha256, INPUT);
  assert.equal(r.prediction.prediction_sha256, SHA);
  assert.equal(r.prediction.stage, "P0");
  assert.deepEqual(r.participants, raw.records[0].participants);
  assert.ok(Object.isFrozen(r.prediction.ordered_top8[0]));
  assert.throws(() => { r.prediction.ordered_top8[0][0] = 9; }, TypeError);
  assert.equal(r.evidence_imported_only, true);
});
test("existing audit-only and synthetic fixtures remain visible without official metrics", () => {
  for (const file of ["2026-10-22-forecast-audit.json", "example-synthetic-forecast-audit.json"]) {
    const raw = JSON.parse(fs.readFileSync(path.join(__dirname,"../web/data",file),"utf8"));
    const parsed = M.parse(raw), stats = M.summary(parsed.records).overall;
    assert.equal(stats.ledger, raw.records.length);
    assert.equal(stats.hit8, null);
    assert.equal(stats.evaluable, 0);
    assert.equal(stats.actualPurchases, 0);
    assert.ok(parsed.records.every(r => r.scope === (raw.dataset_status === "SYNTHETIC_ONLY" ? "synthetic" : "research")));
  }
});
test("boolean-only receipt claims never produce official rates", () => {
  const r = row(undefined, {prediction:prediction("P0", {external_receipt:null}), result:result({evidence:null})});
  const parsed = M.parse(pack([r])).records[0], stats = M.summary([parsed]).overall;
  assert.equal(M.eligiblePrediction(parsed, parsed.prediction), false);
  assert.equal(M.eligibleResult(parsed), false);
  assert.equal(stats.hit8, null);
  assert.ok(parsed.missing_reasons.includes("EXTERNAL_RECEIPT_PIN_MISSING_OR_MISMATCHED"));
});
test("explicit matching importer evidence allows reported official scores only", () => {
  const parsed = M.parse(pack([row()])).records, stats = M.summary(parsed).overall;
  assert.equal(M.eligiblePrediction(parsed[0], parsed[0].prediction), true);
  assert.equal(M.eligibleResult(parsed[0]), true);
  assert.equal(stats.hits, 1); assert.equal(stats.evaluable, 1); assert.equal(stats.hit8, 1);
  assert.equal(stats.evidence_imported_only, true);
});
test("wrong pinned hashes or times cannot count as frozen or official", () => {
  for (const receipt of [
    {...prediction().external_receipt, content_sha256:RESULT},
    {...prediction().external_receipt, server_received_at:"2030-01-01T10:01:00+09:00"},
    {...prediction().external_receipt, source_sha256:RESULT},
  ]) {
    const r=M.parse(pack([row(undefined,{prediction:prediction("P0",{external_receipt:receipt})})])).records[0];
    assert.equal(M.eligiblePrediction(r,r.prediction),false);
  }
  const r=M.parse(pack([row(undefined,{result:result({evidence:{...result().evidence,content_sha256:INPUT}})})])).records[0];
  assert.equal(M.eligibleResult(r),false);
});
test("missing source hash or explicit official scope stays research with reasons", () => {
  for (const changes of [{source_sha256:null},{scope:undefined}]) {
    const r=M.parse(pack([row(undefined,changes)])).records[0];
    assert.equal(r.scope,"research"); assert.equal(M.summary([r]).overall.hit8,null);
    assert.ok(r.missing_reasons.length>0);
  }
});
test("synthetic or audit dataset cannot assert official scope", () => {
  assert.equal(M.parse(pack([row()],"SYNTHETIC_ONLY")).records[0].scope,"synthetic");
  assert.equal(M.parse(pack([row()],"AUDIT_ONLY")).records[0].scope,"research");
});
test("research rows cannot add official hits or simulated money to actual purchases", () => {
  const records=M.parse(pack([row(undefined,{scope:"research",actual_purchase:{confirmed:true,stake_yen:800,payout_yen:1500,refund_yen:100}})])).records;
  const s=M.summary(records).overall;
  assert.equal(s.hit8,null); assert.equal(s.actualPurchases,0); assert.equal(s.actualNet,null);
});
test("same model version P0 and P1 remain separate selectable originals", () => {
  const primary=prediction("P0"), p1=prediction("P1", {prediction_sha256:RESULT});
  const r=M.parse(pack([row(undefined,{prediction:primary,comparison_predictions:[p1]})])).records[0];
  assert.equal(M.selectPrediction(r).stage,"P0");
  assert.equal(M.selectPrediction(r,{stage:"P1",modelId:"existing-model",version:"saved-v1"}).prediction_sha256,RESULT);
  assert.equal(M.selectPrediction(r,{stage:"P1",modelId:"absent"}),null);
  assert.equal(M.modelGroups([r]).length,2);
  assert.deepEqual(M.modelGroups([r]).map(x=>x.stage).sort(),["P0","P1"]);
});
test("unknown stage remains explicit and duplicate stage/model/version cannot replace original", () => {
  const p=prediction(); delete p.stage;
  const r=M.parse(pack([row(undefined,{prediction:p})])).records[0];
  assert.equal(r.prediction.stage,"UNKNOWN");
  assert.throws(()=>M.parse(pack([row(undefined,{comparison_predictions:[prediction()]})])),/重複/);
  assert.throws(()=>M.parse(pack([row(undefined,{prediction:prediction("P2")})])),/時点/);
});
test("ranked candidate universe is preserved, never recalculated, and must match saved top8", () => {
  const ordered=[{combination:[1,2,3],score:0.4},{combination:[1,3,2],score:0.3},{combination:[2,1,3],score:0.2}];
  const r=M.parse(pack([row(undefined,{prediction:prediction("P0",{candidates:ordered})})])).records[0];
  assert.deepEqual(r.prediction.candidates,ordered);
  assert.throws(()=>M.parse(pack([row(undefined,{prediction:prediction("P0",{candidates:ordered.slice().reverse()})})])),/候補順位/);
  assert.throws(()=>M.parse(pack([row(undefined,{prediction:prediction("P0",{candidates:[ordered[0],ordered[0]]})})])),/候補/);
});
test("market data nested in prediction cannot bypass reused audit validation", () => {
  assert.throws(()=>M.parse(pack([row(undefined,{prediction:prediction("P0",{rationale_data:{market_odds:12}})})])),/市場/);
  assert.throws(()=>M.parse(pack([row(undefined,{prediction:prediction("P0",{ordered_top8:[[1,1,2]]})})])),/3連単予想/);
});
test("result revisions retain payout and refunds separately from frozen prediction", () => {
  const first={...result({winning_combinations:[[3,2,1]],payout_yen_per_100:2500}),revision_no:1};
  const latest={...result({refund_boats:[6],refunds:[{combination:[6,1,2],refund_yen_per_100:100}]}),revision_no:2};
  const r=M.parse(pack([row(undefined,{result:latest,result_revisions:[first,latest]})])).records[0];
  assert.deepEqual(r.result_revisions,[first,latest]);
  assert.deepEqual(r.prediction.ordered_top8,[[1,2,3],[1,3,2]]);
  assert.equal(M.summary([r]).overall.hit8,null, "refund cases require their own review");
});
test("latest result and history must agree on payout, refunds and provenance", () => {
  const latest={...result(),revision_no:1};
  for (const changes of [{payout_yen_per_100:1200},{refunds:[{participant:6,refund_yen:100}]},{source_sha256:INPUT}]) {
    assert.throws(()=>M.parse(pack([row(undefined,{result:{...latest,...changes},result_revisions:[latest]})])),/一致/);
  }
  assert.throws(()=>M.parse(pack([row(undefined,{result:latest,result_revisions:[{...latest,revision_no:2}]})])),/改訂/);
});
test("official all-race denominator retains a missing prediction without hiding it", () => {
  const records=M.parse(pack([row(),row("boat:2030-01-01:test:2",{prediction:null,no_forecast_reason:"NO_SAVED_P0"})])).records;
  const s=M.summary(records).overall;
  assert.equal(s.ledger,2); assert.equal(s.evaluable,2); assert.equal(s.hits,1); assert.equal(s.hit8,0.5);
});
test("model denominators use sport/scope/stage/version instead of pooling P0/P1 or research", () => {
  const records=M.parse(pack([
    row(),row("boat:2030-01-01:test:2",{prediction:null}),
    row("boat:2030-01-01:test:3",{scope:"research",prediction:prediction("P1")})
  ])).records;
  const groups=M.modelGroups(records), p0=groups.find(g=>g.stage==="P0"), p1=groups.find(g=>g.stage==="P1");
  assert.equal(p0.ledger,2);assert.equal(p0.issued,1);assert.equal(p0.evaluable,2);assert.equal(p0.hit8,0.5);
  assert.equal(p1.ledger,1);assert.equal(p1.hit8,null);
});
test("summary exposes stage ledgers and withholds a pooled mixed-stage official rate", () => {
  const records=M.parse(pack([row(),row("boat:2030-01-01:test:2",{prediction:prediction("P1")})])).records;
  const s=M.summary(records);
  assert.equal(s.byStage.P0.ledger,2);assert.equal(s.byStage.P1.ledger,2);
  assert.equal(s.byStage.P0.hit8,0.5);assert.equal(s.byStage.P1.hit8,0.5);
  assert.equal(s.overall.hit8,null);assert.equal(s.overall.stage_mixed,true);
});
test("same-stage mixed models or versions cannot pool their official rates", () => {
  for (const different of [{model_id:"other-model"},{model_version:"saved-v2"}]) {
    const records=M.parse(pack([
      row(),row("boat:2030-01-01:test:2",{prediction:prediction("P0",different)}),
      row("boat:2030-01-01:test:3",{prediction:null})
    ])).records;
    const s=M.summary(records), groups=M.modelGroups(records);
    assert.equal(s.overall.evaluable,3);assert.equal(s.overall.hits,2);
    assert.equal(s.overall.hit8,null);assert.equal(s.overall.identity_mixed,true);
    assert.equal(s.overall.stage_mixed,false);
    assert.equal(s.overall.prediction_identities.length,2);
    assert.equal(s.byStage.P0.hit8,null);assert.equal(s.byStage.P0.identity_mixed,true);
    assert.equal(groups.length,2);
    assert.ok(groups.every(g=>g.evaluable===3 && g.hits===1 && g.hit8===1/3 && !g.identity_mixed));
  }
});
test("stage cohort keeps eligible schedules lacking a saved prediction", () => {
  const records=M.parse(pack([
    row(),row("boat:2030-01-01:test:2"),row("boat:2030-01-01:test:3",{prediction:null})
  ])).records;
  const s=M.summary(records);
  assert.equal(s.byStage.P0.ledger,3);assert.equal(s.byStage.P0.evaluable,3);
  assert.equal(s.byStage.P0.hits,2);assert.equal(s.byStage.P0.hit8,2/3);
  assert.equal(s.byStage.P0.noForecast,1);
  assert.equal(s.byStage.UNKNOWN.ledger,1);assert.equal(s.byStage.UNKNOWN.hit8,null);
});
test("stage summaries use preserved variants and suppress a rate with no saved identity", () => {
  const p1=prediction("P1");
  const records=M.parse(pack([row(undefined,{comparison_predictions:[p1]}),row("boat:2030-01-01:test:2",{prediction:null})])).records;
  assert.equal(M.summary(records).byStage.P1.hit8,0.5);
  const missing=M.parse(pack([row(undefined,{prediction:null})])).records;
  assert.equal(M.summary(missing).overall.hit8,null);
  assert.deepEqual(M.summary(missing).overall.prediction_identities,[]);
});
test("refund combination aliases remain review cases and cannot inflate official rates", () => {
  const records=M.parse(pack([row(undefined,{result:result({refund_combinations:[[6,1,2]]})})])).records;
  assert.deepEqual(records[0].result.refund_combinations,[[6,1,2]]);
  assert.equal(M.eligibleResult(records[0]),false);
  assert.equal(M.summary(records).overall.hit8,null);
  assert.ok(records[0].missing_reasons.includes("REFUND_REVIEW_REQUIRED"));
});
test("refund combination aliases validate unique tickets and agree with supplied refund details", () => {
  for (const refund_combinations of [[[6,6,2]],[[6,1,2],[6,1,2]],"6-1-2"]) {
    assert.throws(()=>M.parse(pack([row(undefined,{result:result({refund_combinations})})])),/返還/);
  }
  assert.throws(()=>M.parse(pack([row(undefined,{result:result({refund_combinations:[[6,1,2]],refunds:[{combination:[5,1,2],refund_yen_per_100:100}]})})])),/返還.*一致/);
  assert.doesNotThrow(()=>M.parse(pack([row(undefined,{result:result({refund_combinations:[[6,1,2]],refunds:[{combination:[6,1,2],refund_yen_per_100:100}]})})])));
});
test("actual confirmed purchases remain separate and are never inferred from candidate stake", () => {
  const records=M.parse(pack([row(),row("boat:2030-01-01:test:2",{actual_purchase:{confirmed:true,stake_yen:800,payout_yen:1500,refund_yen:100}})])).records;
  const s=M.summary(records).overall;
  assert.equal(s.actualPurchases,1);assert.equal(s.actualStake,800);assert.equal(s.actualNet,800);
});
test("strict schema rejects duplicates, invalid dates, malformed refunds and non-JSON data", () => {
  assert.throws(()=>M.parse(pack([row(),row()])),/重複/);
  assert.throws(()=>M.parse(pack([row(undefined,{event_date_jst:"2030-02-30"})])),/JST/);
  assert.throws(()=>M.parse(pack([row(undefined,{result:result({refunds:[{refund_yen:-1}]})})])),/返還/);
  assert.throws(()=>M.parse(pack([row(undefined,{unexpected:Infinity})])),/JSON/);
  assert.throws(()=>M.parse({schema:"UNSUPPORTED",records:[]}),/未対応/);
});
test("calendar timestamp and explicit JST day must agree", () => {
  assert.throws(()=>M.parse(pack([row(undefined,{cutoff_at:"2030-02-30T10:00:00+09:00"})])),/時刻/);
  assert.throws(()=>M.parse(pack([row(undefined,{event_date_jst:"2030-01-02"})])),/JST/);
});
test("missing model identity is displayed without official eligibility or a false model match", () => {
  const unknown=prediction("P0",{model_id:null}), known=prediction("P0",{model_id:"known",ordered_top8:[[3,2,1]]});
  const r=M.parse(pack([row(undefined,{prediction:known,comparison_predictions:[unknown]})])).records[0];
  assert.equal(M.eligiblePrediction(r,r.comparison_predictions[0]),false);
  const groups=M.modelGroups([r]);
  assert.equal(groups.find(g=>g.model_id===null).hit8,0);
  assert.equal(groups.find(g=>g.model_id==="known").hit8,0);
});
test("hash aliases preserve their source and conflicting provenance is rejected", () => {
  const r=row(); delete r.source_sha256; r.source_sha=INPUT;
  const parsed=M.parse(pack([r])).records[0];
  assert.equal(parsed.source_sha256,INPUT);assert.equal(parsed.source_sha,INPUT);
  assert.throws(()=>M.parse(pack([row(undefined,{source_sha:RESULT})])),/SHA/);
});
test("repeated local parsing is deterministic and has no network, clock or storage dependency", () => {
  const raw=pack([row()]), before=JSON.stringify(raw);
  assert.deepEqual(M.parse(JSON.stringify(raw)),M.parse(raw));
  assert.equal(JSON.stringify(raw),before);
  const source=fs.readFileSync(target,"utf8");
  assert.doesNotMatch(source,/\bfetch\s*\(|XMLHttpRequest|localStorage|sessionStorage|Date\.now\s*\(/);
});
