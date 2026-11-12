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

function privateCycle(extra = {}) {
  const p = {stage:"P0", model_id:"boat-observed-pairwise-factor-v1", model_version:null,
    variant:"BASELINE", ordered_top8:[[1,2,3],[1,3,2]], ordered_candidates:[[1,2,3],[1,3,2],[2,1,3]],
    generated_at:null, as_of:"2030-01-01T09:00:00+09:00", persisted_at:"2030-01-01T09:01:00+09:00",
    server_saved_at:"2030-01-01T09:01:00+09:00", cutoff_at:cutoff, input_sha256:null, source_sha256:null,
    prediction_sha256:SHA, model_sha256:SHA, original_json_sha256:INPUT, artifact_id:17,
    odds_independent:null, external_receipt_verified:false, missing_reasons:["MODEL_VERSION_NOT_SAVED"]};
  const observation = {race_id:"20300101-01-01", captured_at:"2030-01-01T10:20:00+09:00", source_sha256:RESULT,
    status:"AVAILABLE", data:{status:"settled", top3:[1,2,3], payouts:[{bet_type:"trifecta", combination:[1,2,3], payout_per_100_yen:1500}]}};
  return {schema:"RACE_AI_PRIVATE_CYCLE_VIEW_V1", dataset_status:"REAL_REPORTED", event_date_jst:"2030-01-01", source_state_sha256:RESULT,
    records:[{race_id:"20300101-01-01", sport:"boat", venue:"場コード01", race_no:1, event_date_jst:"2030-01-01", cutoff_at:cutoff,
      offering_status:"UNKNOWN", scope:"research", source_provenance:"OWNER_LOCAL_RECOVERED_CYCLE", source_sha256:null,
      participants:[{number:1, registration_no:"4430"}], prediction:p, comparison_predictions:[],
      result:{status:"final", winning_combinations:[[1,2,3]], payout_yen_per_100:1500, official:false,
        confirmed_at:null, observed_at:observation.captured_at, source_sha256:RESULT},
      result_observations:[observation], result_revisions:[], missing_reasons:["INDEPENDENT_RECEIPT_NOT_VERIFIED"]}], ...extra};
}
test("gen125 official result display names require original SP result URL and exact race registration", () => {
  const make = (change={}) => {
    const raw=privateCycle();
    raw.records[0].participants[0].name="公式結果保存名";
    raw.records[0].participants[0].name_source={
      kind:"SAME_RACE_RESULT", registration_no:"4430", race_id:"20300101-01-01",
      source_sha256:RESULT, captured_at:"2030-01-01T10:20:00+09:00",
      source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=1",
      ...change
    };
    return raw;
  };
  const original=make(),serialized=JSON.stringify(original);
  const parsed=M.parse(original),row=parsed.records[0];
  assert.equal(row.participants[0].name,"公式結果保存名");
  assert.equal(row.participants[0].name_source.kind,"SAME_RACE_RESULT");
  assert.equal(JSON.stringify(original),serialized);
  assert.equal(row.prediction.prediction_sha256,SHA);
  assert.equal(M.eligiblePrediction(row,row.prediction),false);
  for(const change of [
    {registration_no:"4999"},{race_id:"20300101-01-02"},
    {source_sha256:"invalid"},{captured_at:"not-a-date"},
    {captured_at:"2029-12-31T23:59:59+09:00"},
    {source_url:"https://example.invalid/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=1"},
    {source_url:"http://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=1"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=2"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300102&jcd=01&rno=1"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=1&debug=1"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=1&hd=20300101"}
  ]) {
    assert.throws(()=>M.parse(make(change)),/出典|選手名|不正/,JSON.stringify(change));
  }
  assert.throws(()=>M.parse(make({kind:"UNVERIFIED_RESULT"})),/出典|選手名/);
});

test("same-day saved official result name is proven by source race and exact target registration", () => {
  const make = (changes={}) => {
    const raw=privateCycle();
    raw.records[0].participants[0].name="別レース確認済み架空選手";
    raw.records[0].participants[0].name_source={
      kind:"SAME_DAY_OFFICIAL_RESULT", registration_no:"4430",
      race_id:"20300101-01-01", source_race_id:"20300101-01-02",
      source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=2",
      source_sha256:RESULT, captured_at:"2030-01-01T10:20:00+09:00",
      ...changes
    };
    return raw;
  };
  const original=make(),before=JSON.stringify(original),parsed=M.parse(original);
  assert.equal(JSON.stringify(original),before);
  assert.equal(parsed.records[0].participants[0].name_source.source_race_id,"20300101-01-02");
  assert.equal(parsed.records[0].prediction.prediction_sha256,SHA);
  assert.equal(M.eligiblePrediction(parsed.records[0],parsed.records[0].prediction),false);
  for(const change of [
    {registration_no:"4999"}, {race_id:"20300101-01-03"},
    {source_race_id:"20300101-01-01"}, {source_race_id:"20300101-01-03"},
    {source_race_id:"20300102-01-02"}, {source_race_id:"20300101-00-02"},
    {source_sha256:"invalid"}, {captured_at:"invalid"},
    {captured_at:"2029-12-31T23:59:59+09:00"},
    {source_url:"https://example.invalid/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=2"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=1"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=02&rno=2"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300102&jcd=01&rno=2"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=2&debug=1"},
    {source_url:"https://www.boatrace.jp/owsp/sp/spdata?type=raceresult&hd=20300101&jcd=01&rno=2&hd=20300101"}
  ]) {
    assert.throws(()=>M.parse(make(change)),/出典|選手名|不正/,JSON.stringify(change));
  }
  assert.throws(()=>M.parse(make({kind:"NOT_VERIFIED"})),/出典|選手名|不正/);
});

test("private cycle projection admits exact saved partial metadata without fake time/hash/version", () => {
  const raw=privateCycle(), before=JSON.stringify(raw), parsed=M.parse(raw), r=parsed.records[0], p=r.prediction;
  assert.equal(JSON.stringify(raw),before);
  assert.equal(parsed.schema,"RACE_AI_PRIVATE_CYCLE_VIEW_V1");
  assert.equal(r.race_id,"20300101-01-01");assert.equal(r.venue,"場コード01");
  for(const field of ["generated_at","model_version","input_sha256","source_sha256","odds_independent"]) assert.equal(p[field],null,field);
  for(const field of ["as_of","persisted_at","prediction_sha256","original_json_sha256","artifact_id","model_sha256"]) assert.deepEqual(p[field],raw.records[0].prediction[field],field);
  assert.deepEqual(p.ordered_candidates,raw.records[0].prediction.ordered_candidates);
  assert.deepEqual(r.result_observations,raw.records[0].result_observations);
  assert.deepEqual(r.result_revisions,[]);
  assert.equal(r.result.confirmed_at,null);assert.equal(r.result.observed_at,raw.records[0].result.observed_at);
  assert.ok(Object.isFrozen(r.result_observations[0].data));
  assert.equal(M.summary(parsed.records).overall.hit8,null);assert.equal(M.eligiblePrediction(r,p),false);assert.equal(M.eligibleResult(r),false);
});
test("private cycle import cannot promote itself to official metrics with asserted evidence", () => {
  const raw=privateCycle();Object.assign(raw.records[0],{scope:"official", source_sha256:INPUT, offering_status:"TRIFECTA_OFFERED"});
  Object.assign(raw.records[0].prediction,prediction(),{variant:"BASELINE"});
  raw.records[0].prediction.ordered_candidates=raw.records[0].prediction.ordered_top8;
  Object.assign(raw.records[0].result,result());
  for(const status of ["REAL_REPORTED","SYNTHETIC_ONLY"]) {
    const parsed=M.parse({...raw,dataset_status:status}), r=parsed.records[0];
    assert.equal(r.scope,status==="SYNTHETIC_ONLY"?"synthetic":"research");
    assert.equal(r.prediction.external_receipt_verified,false);assert.equal(r.result.official,false);
    assert.equal(M.summary(parsed.records).overall.hit8,null);assert.equal(M.summary(parsed.records).overall.evaluable,0);
  }
});
test("private baseline and learned originals with unknown versions stay separately selectable", () => {
  const raw=privateCycle(), p=raw.records[0].prediction;
  raw.records[0].comparison_predictions=[{...structuredClone(p),variant:"LEARNED_SHADOW",prediction_sha256:"d".repeat(64),model_sha256:"d".repeat(64)}];
  const parsed=M.parse(raw), r=parsed.records[0], groups=M.modelGroups(parsed.records);
  assert.equal(groups.length,2);assert.ok(groups.every(g=>g.model_version===null && g.hit8===null));
  assert.deepEqual(groups.map(g=>g.variant).sort(),["BASELINE","LEARNED_SHADOW"]);
  assert.equal(M.selectPrediction(r,{version:null,variant:"LEARNED_SHADOW"}).prediction_sha256,"d".repeat(64));
  assert.equal(M.selectPrediction(r,{predictionSha:SHA}).variant,"BASELINE");
  raw.records[0].comparison_predictions.push(structuredClone(p));
  assert.throws(()=>M.parse(raw),/重複/);
});
test("partial-cycle admission remains bounded and strict about tickets, timestamps, identity and raw observations", () => {
  const mutations=[
    raw=>{raw.records[0].prediction.ordered_top8=[[1,1,2]];},
    raw=>{raw.records[0].prediction.ordered_candidates.reverse();},
    raw=>{raw.records[0].prediction.as_of="2030-02-30T09:00:00+09:00";},
    raw=>{raw.records[0].prediction.prediction_sha256="fake";},
    raw=>{raw.records[0].prediction.model_sha256="d".repeat(64);},
    raw=>{raw.records[0].prediction=false;},
    raw=>{raw.records[0].comparison_predictions=[null];},
    raw=>{raw.records[0].actual_purchase={confirmed:true,stake_yen:-1,payout_yen:0,refund_yen:0};},
    raw=>{raw.records[0].result_observations[0].race_id="20300101-02-01";},
    raw=>{raw.records[0].result_observations[0].captured_at="not-a-time";},
    raw=>{raw.records[0].result.winning_combinations=[[1,1,2]];},
    raw=>{raw.records[0].result_revisions=[{revision_no:1}];},
    raw=>{raw.records.push(structuredClone(raw.records[0]));}
  ];
  for(const mutate of mutations){const raw=privateCycle();mutate(raw);assert.throws(()=>M.parse(raw));}
  const raw=privateCycle();raw.schema="RACE_AI_FORECAST_AUDIT_V1";
  assert.throws(()=>M.parse(raw),/予想時刻|証拠|不正/,"legacy strict schema must still reject partial metadata");
});
test("private dispatch retains native AUTORACE phases without renaming them to P0/P1", () => {
  const raw=privateCycle(),r=raw.records[0];r.sport="autorace";r.prediction.stage="A_PRE_TRIAL";
  r.comparison_predictions=[{...structuredClone(r.prediction),stage:"B_POST_TRIAL",prediction_sha256:"d".repeat(64),model_sha256:"d".repeat(64)}];
  const parsed=M.parse(raw),summary=M.summary(parsed.records);
  assert.equal(M.selectPrediction(parsed.records[0],{stage:"B_POST_TRIAL"}).stage,"B_POST_TRIAL");
  assert.equal(summary.byStage.A_PRE_TRIAL.ledger,1);assert.equal(summary.byStage.B_POST_TRIAL.ledger,1);
  assert.equal(summary.byStage.P0.ledger,0);assert.equal(summary.overall.hit8,null);
  raw.records[0].sport="boat";assert.throws(()=>M.parse(raw),/時点|競技/);
});
test("private dispatcher output hash stays distinct from an unavailable native prediction hash", () => {
  const raw=privateCycle(),p=raw.records[0].prediction;
  Object.assign(p,{native_dispatch_prediction:true,prediction_sha256:null,model_sha256:null,output_sha256:SHA,hash_basis:"NATIVE_OUTPUT_CONTENT"});
  const parsed=M.parse(raw),saved=parsed.records[0].prediction;
  assert.equal(saved.prediction_sha256,null);assert.equal(saved.output_sha256,SHA);
  assert.ok(saved.missing_reasons.includes("NATIVE_PREDICTION_SHA_NOT_SAVED"));
  assert.equal(M.selectPrediction(parsed.records[0],{outputSha:SHA}).output_sha256,SHA);
  assert.equal(M.selectPrediction(parsed.records[0],{outputSha:"f".repeat(64)}),null);
  assert.equal(M.summary(parsed.records).overall.hit8,null);
  for(const change of [{output_sha256:null},{hash_basis:null},{native_dispatch_prediction:false}]) {
    const bad=structuredClone(raw);Object.assign(bad.records[0].prediction,change);assert.throws(()=>M.parse(bad));
  }
});
test("native dispatch model artifact SHA may differ from saved prediction SHA without repairing either", () => {
  const raw=privateCycle(),p=raw.records[0].prediction;
  Object.assign(p,{native_dispatch_prediction:true,output_sha256:INPUT,model_sha256:RESULT});
  const parsed=M.parse(raw).records[0].prediction;
  assert.equal(parsed.prediction_sha256,SHA);assert.equal(parsed.model_sha256,RESULT);
  const bad=structuredClone(raw);delete bad.records[0].prediction.native_dispatch_prediction;
  assert.throws(()=>M.parse(bad),/SHA/);
});
test("dispatch views retain unknown venue and race number without inventing schedule metadata", () => {
  const raw=privateCycle(),r=raw.records[0];Object.assign(r,{native_dispatch_view:true,venue:null,race_no:null});
  const parsed=M.parse(raw);assert.equal(parsed.records[0].venue,null);assert.equal(parsed.records[0].race_no,null);
  const legacy=structuredClone(raw);delete legacy.records[0].native_dispatch_view;assert.throws(()=>M.parse(legacy));
});
test("private dispatch slot status is bounded and cannot change its model/stage identity", () => {
  const raw=privateCycle(),r=raw.records[0];r.native_dispatch_view=true;
  r.dispatch_slots=[{stage:"P1",model_id:"boat-observed-pairwise-factor-v1",model_version:null,status:"INPUT_MISSING",reason:"NO_NATIVE_INPUT_SUPPLIED",applicable:true,projection_status:"NOT_PROJECTED",projection_reason:null,output_sha256:null,prediction_sha256:null}];
  assert.equal(M.parse(raw).records[0].dispatch_slots[0].status,"INPUT_MISSING");
  for(const change of [{stage:"B_POST_TRIAL"},{status:"VERIFIED_LIVE_SUCCESS"},{model_id:""},{output_sha256:"fake"}]) {
    const bad=structuredClone(raw);Object.assign(bad.records[0].dispatch_slots[0],change);assert.throws(()=>M.parse(bad));
  }
  const contradictory=structuredClone(raw);contradictory.records[0].scheduled_stages=["P0"];
  assert.throws(()=>M.parse(contradictory),/台帳|時点/);
});
test("declared private phases retain missing forecasts and do not add unscheduled comparison races", () => {
  const raw=privateCycle(),r=raw.records[0];r.sport="autorace";r.scheduled_stages=["A_PRE_TRIAL","B_POST_TRIAL"];r.prediction.stage="A_PRE_TRIAL";
  const next=structuredClone(r);next.race_id="autorace:another-actual-race";next.scheduled_stages=["B_POST_TRIAL"];next.prediction.stage="B_POST_TRIAL";next.result=null;next.result_observations=[];raw.records.push(next);
  const parsed=M.parse(raw),summary=M.summary(parsed.records),groups=M.modelGroups(parsed.records);
  assert.equal(summary.byStage.B_POST_TRIAL.ledger,2,"declared missing original retains the stage denominator");
  assert.equal(summary.byStage.A_PRE_TRIAL.ledger,1);
  assert.equal(groups.find(g=>g.stage==="A_PRE_TRIAL").ledger,1,"unscheduledA race cannot inflate cohort");
  assert.equal(groups.find(g=>g.stage==="B_POST_TRIAL").ledger,2);
  for(const stages of [["P2"],["A_PRE_TRIAL","A_PRE_TRIAL"],[]]) {
    const bad=privateCycle();bad.records[0].scheduled_stages=stages;assert.throws(()=>M.parse(bad));
  }
});
test("saved conflicting cutoff variants preserve each original and reject a fabricated single clock", () => {
  const raw=privateCycle(),r=raw.records[0],first=r.prediction.cutoff_at,second="2030-01-01T10:01:00+09:00";
  r.cutoff_at=null;r.saved_cutoff_variants=[first,second];r.result.status="unsupported";r.result.winning_combinations=[];
  r.comparison_predictions=[{...structuredClone(r.prediction),stage:"P1",cutoff_at:second,prediction_sha256:"d".repeat(64),model_sha256:"d".repeat(64)}];
  const parsed=M.parse(raw).records[0];assert.equal(parsed.cutoff_at,null);assert.equal(parsed.prediction.cutoff_at,first);assert.equal(parsed.comparison_predictions[0].cutoff_at,second);
  for(const mutate of [x=>x.saved_cutoff_variants=[first],x=>x.saved_cutoff_variants=[first,first],x=>x.saved_cutoff_variants=[first,"bad"],x=>x.cutoff_at=first,x=>x.result={...x.result,status:"final",winning_combinations:[[1,2,3]]}]) {
    const bad=structuredClone(raw);mutate(bad.records[0]);assert.throws(()=>M.parse(bad));
  }
});
test("quarantined result observations retain original capture identity and cannot appear final", () => {
  const raw=privateCycle(),r=raw.records[0],o=r.result_observations[0];
  Object.assign(r.result,{status:"unsupported",winning_combinations:[]});
  r.result_observation_rejections=[{captured_at:o.captured_at,source_sha256:o.source_sha256,reason:"RESULT_CUTOFF_MISMATCH"}];
  const parsed=M.parse(raw);assert.deepEqual(parsed.records[0].result_observations,r.result_observations);
  assert.equal(parsed.records[0].result_observation_rejections[0].reason,"RESULT_CUTOFF_MISMATCH");
  for(const mutate of [x=>x.result_observation_rejections[0].captured_at="2030-01-01T11:30:00+09:00",x=>x.result_observation_rejections[0].reason="",x=>Object.assign(x.result,{status:"final",winning_combinations:[[1,2,3]]})]) {
    const bad=structuredClone(raw);mutate(bad.records[0]);assert.throws(()=>M.parse(bad));
  }
});
test("observation cutoff variants retain quarantined wrong-day clocks and reject an invented canonical result", () => {
  const raw=privateCycle(),r=raw.records[0],first=r.cutoff_at,second="2030-01-02T10:00:00+09:00";
  Object.assign(r,{prediction:null,cutoff_at:null,saved_observation_cutoff_variants:[first,second]});
  Object.assign(r.result,{status:"unsupported",winning_combinations:[]});
  r.result_observations[0].closed_at=first;
  r.result_observations.push({...structuredClone(r.result_observations[0]),closed_at:second,captured_at:"2030-01-02T10:20:00+09:00"});
  r.result.observed_at=r.result_observations[1].captured_at;
  const before=JSON.stringify(raw),parsed=M.parse(raw).records[0];
  assert.equal(JSON.stringify(raw),before);assert.equal(parsed.cutoff_at,null);assert.equal(parsed.result.status,"unsupported");
  assert.deepEqual(parsed.saved_observation_cutoff_variants,[first,second]);
  assert.deepEqual(parsed.result_observations,r.result_observations);
  const mutations=[
    x=>x.saved_observation_cutoff_variants=first,
    x=>x.saved_observation_cutoff_variants=[first],
    x=>x.saved_observation_cutoff_variants=[first,first],
    x=>x.saved_observation_cutoff_variants=[first,"2030-01-01T01:00:00Z"],
    x=>x.saved_observation_cutoff_variants=[first,"bad"],
    x=>x.saved_observation_cutoff_variants=Array.from({length:65},(_,i)=>new Date(Date.UTC(2030,0,1,0,i)).toISOString()),
    x=>x.cutoff_at=first,
    x=>Object.assign(x.result,{status:"final",winning_combinations:[[1,2,3]]})
  ];
  for(const mutate of mutations){const bad=structuredClone(raw);mutate(bad.records[0]);assert.throws(()=>M.parse(bad));}
  for(const field of ["saved_cutoff_variants","saved_schedule_cutoff_variants"]){
    const bad=structuredClone(raw);delete bad.records[0].saved_observation_cutoff_variants;bad.records[0][field]=[first,second];
    assert.throws(()=>M.parse(bad),"forecast and schedule variants must still match the race day");
  }
  const empty=privateCycle();empty.records[0].saved_observation_cutoff_variants=[];
  assert.equal(M.parse(empty).records[0].result.status,"final","an empty variant list carries no ambiguity");
});
test("saved source observations admit missing race metadata while remaining separate from forecasts", () => {
  const raw=privateCycle(),r=raw.records[0];Object.assign(r,{source_observation_view:true,venue:null,race_no:null,cutoff_at:null,prediction:null,result:null,result_observations:[]});
  r.source_observation={source_url:"https://www.winticket.jp/keirin/fictional/racedetail/2030010101/1/1",source_uri:"https://www.winticket.jp/keirin/fictional/racedetail/2030010101/1/1",final_url:"https://www.winticket.jp/keirin/fictional/racedetail/2030010101/1/1",observed_at:"2030-01-01T08:00:00+09:00",source_sha256:SHA,original_json_sha256:INPUT,artifact_id:17,kind:"CAPTURED_PUBLIC_PAGE_FACTS",independent_source_verified:false,pre_cutoff_receipt_verified:false};
  r.race_id=r.source_observation.source_uri;
  const parsed=M.parse(raw).records[0];assert.equal(parsed.prediction,null);assert.equal(parsed.result,null);assert.equal(parsed.cutoff_at,null);assert.equal(parsed.scope,"research");
  for(const mutate of [x=>x.prediction=privateCycle().records[0].prediction,x=>x.source_observation.source_url="javascript:alert(1)",x=>x.source_observation.source_sha256="fake"]) {
    const bad=structuredClone(raw);mutate(bad.records[0]);assert.throws(()=>M.parse(bad));
  }
  for(const field of ["saved_cutoff_variants","saved_schedule_cutoff_variants","saved_observation_cutoff_variants"]){
    const bad=structuredClone(raw);bad.records[0][field]=[cutoff,"2030-01-01T10:01:00+09:00"];
    assert.throws(()=>M.parse(bad),"captured public pages cannot supply race cutoff metadata: "+field);
    raw.records[0][field]=[];
  }
  assert.equal(M.parse(raw).records[0].source_observation.kind,"CAPTURED_PUBLIC_PAGE_FACTS","empty producer arrays remain neutral");
});
