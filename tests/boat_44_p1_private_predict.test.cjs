"use strict";
/* Deliberately synthetic; not evidence of real BOAT forecasts or training. */
const assert = require("assert");
const overlay = require("../race_ai/boat_six_way_probability_overlay.cjs");
const batch = require("../scripts/boat_44_p1_private_predict.cjs");
const asof = "2026-11-09T10:00:00+09:00";
const cutoff = "2026-11-09T11:30:00+09:00";
const race = "20261109-04-01";
const input = {};
const gaps = {}, board = [];
for (let c=1; c<=6; c++) {
  const id = String(4100+c);
  input[String(c)] = {frame:c, racer_id:id,
    tilt_deg: c >=5 ? 2 : .5,
    outer_high_tilt_marker:c>=5,
    historical_inward_move_win_rate:.2+c*.02,
    historical_outward_move_top3_rate:.3,
    inner_pressure_kept_course_rate:.4};
  gaps[id] = c-3;
  board.push({racer_id:id,official_rank:c,eligibility:"ELIGIBLE",
    official_rate:8.5});
}
const styles = Object.fromEntries(overlay.STYLES.map(n=>[n,.2]));
const record = {stage:"P1",cutoff_at:cutoff,
 context:{schema:overlay.INPUT,race_id:race,as_of:asof,
   six_course_features:styles,
   formation:{slow_count:3,kado_course:4,kado_uke_course:3},
   entry_tilt_cross_features:input,
   qualifying_rank_and_point_gaps:{
     border_status:"CURRENT_RANK_ONLY_NOT_FINAL",rate_gaps:gaps,standings:board
   },
   current_venue_rule_status:"CLAIMED_CURRENT_RECEIPT_REQUIRES_INDEPENDENT_AUTH"
 },
 baseline:{race_id:race,as_of:asof,
  full_120:overlay.TICKETS.map(ticket=>({ticket,score:1/120}))}
};
const beta = Array(overlay.FACTORS.length).fill(0);
beta[overlay.FACTORS.indexOf("winner_high_tilt")] = 3;
const model = {schema:overlay.MODEL,frozen:true,stage:"P1",
 trained_through:"2026-10-01T00:00:00Z",training_ids:[],
 feature_names:[...overlay.FACTORS],coefficients:beta,
 production_eligible:false};
const make = (modelArg, mode="prospective") => ({
 schema:batch.SCHEMA,mode,frozen_44_model:modelArg,
 races:[{race_id:race,status:"P1_CONTEXT_READY_UNVERIFIED",record}]
});
const actual = batch.scoreBatch(make(model),{now:"2026-11-09T10:30:00+09:00"});
assert.strictEqual(actual.count,1);
assert.strictEqual(actual.evaluated,1);
assert.strictEqual(actual.rows[0].full_120.length,120);
assert(Math.abs(actual.rows[0].full_120.reduce((s,x)=>s+x.probability,0)-1)<1e-10);
assert.notDeepStrictEqual(actual.rows[0].baseline_top8,actual.rows[0].tactical_top8);
assert.strictEqual(actual.rows[0].status,"EXPERIMENTAL_PRE_CUTOFF_UNATTESTED");
assert.strictEqual(actual.rows[0].accepted_as_prospective_proof,false);
assert.strictEqual(actual.safe_to_promote_to_main,false);
const missing = batch.scoreBatch(make(null),{now:"2026-11-09T10:30:00+09:00"});
assert.strictEqual(missing.rows[0].status,"HOLD_NO_FROZEN_TACTICAL_MODEL");
assert.strictEqual(missing.evaluated,0);
const late = batch.scoreBatch(make(model),{now:"2026-11-09T11:31:00+09:00"});
assert.strictEqual(late.rows[0].status,"HOLD_NOT_IN_PRE_CUTOFF_WINDOW");
assert.strictEqual(late.evaluated,0);
const replay = batch.scoreBatch(make(model,"historical_replay"),{
  now:"2026-11-10T09:00:00+09:00"});
assert.strictEqual(replay.rows[0].status,"EXPERIMENTAL_TACTICAL_REPLAY_NOT_CERTIFIED");
assert.strictEqual(replay.rows[0].accepted_as_prospective_proof,false);
const noFacts = batch.scoreBatch({schema:batch.SCHEMA,mode:"prospective",
 frozen_44_model:model,races:[{race_id:race,status:"HOLD_MISSING_ACTUAL_SOURCE_FACTS",
 missing:["tilt"],record:null}]},{now:"2026-11-09T10:30:00+09:00"});
assert.strictEqual(noFacts.rows[0].status,"HOLD_MISSING_SOURCE_FACTS");
assert.strictEqual(noFacts.rows[0].reason[0],"tilt");
assert.throws(()=>batch.scoreBatch({
 ...make(model),races:[{race_id:race,status:"P1_CONTEXT_READY_UNVERIFIED",
 record:{...record,baseline:{...record.baseline,race_id:"20261109-04-02"}}}]
},{now:"2026-11-09T10:30:00+09:00"}),/RACE_DATA_MISMATCH/);
// All-day 11x12 source-free contract: do NOT mistake synthetic coverage
// or one evaluated fixture for 132 verified real-model forecasts.
const badRecord = structuredClone(record);
badRecord.context.race_id = "20261109-04-02";
badRecord.baseline.race_id = badRecord.context.race_id;
badRecord.baseline.full_120[0].score = 2; // intentionally invalid
const nationwideRows = [];
for (let venue=1; venue<=11; venue++) {
  for (let rno=1; rno<=12; rno++) {
    const rid = "20261109-" + String(venue).padStart(2, "0") +
      "-" + String(rno).padStart(2, "0");
    nationwideRows.push(rid === race ?
      {race_id:rid,status:"P1_CONTEXT_READY_UNVERIFIED",record} :
      rid === badRecord.context.race_id ?
      {race_id:rid,status:"P1_CONTEXT_READY_UNVERIFIED",record:badRecord} :
      {race_id:rid,status:"HOLD_MISSING_ACTUAL_SOURCE_FACTS",
        missing:["real six-boat history, P1 evidence or cutoff receipt"],record:null});
  }
}
const national = batch.scoreBatch({
  schema:batch.SCHEMA,mode:"prospective",frozen_44_model:model,
  races:nationwideRows
},{now:"2026-11-09T10:30:00+09:00"});
assert.strictEqual(national.count,132);
assert.strictEqual(national.evaluated,1);
assert.strictEqual(national.status_counts.EXPERIMENTAL_PRE_CUTOFF_UNATTESTED,1);
assert.strictEqual(national.status_counts.HOLD_TACTICAL_INPUT_OR_MODEL_INVALID,1);
assert.strictEqual(national.status_counts.HOLD_MISSING_SOURCE_FACTS,130);
assert.strictEqual(Object.values(national.status_counts).reduce((a,b)=>a+b,0),132);
assert.strictEqual(national.rows.find(x=>x.race_id==="20261109-04-02").full_120,null);
assert.strictEqual(national.safe_to_promote_to_main,false);
assert.strictEqual(national.prediction_originals_frozen_externally,false);
console.log("BOAT_44_PRIVATE_SYNTHETIC_CONTRACT_PASS");
