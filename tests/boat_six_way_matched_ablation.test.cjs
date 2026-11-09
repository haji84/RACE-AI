"use strict";
/* Synthetic-only matched research. No provider GET or real wager. */
const assert=require("node:assert/strict");
const O=require("../race_ai/boat_six_way_probability_overlay.cjs");
const A=require("../race_ai/boat_six_way_matched_ablation.cjs");
function one(i) {
 const date=new Date(Date.UTC(2026,10,1+Math.floor(i/5))).toISOString().slice(0,10);
 const race=date.replace(/-/g,"")+"-04-"+String(i%5+1).padStart(2,"0");
 const clock=date+"T10:00:00+09:00",s={},entry={},gaps={},board=[],grade=[];
 for(const [j,k] of O.STYLES.entries())s[k]=.15+((j*13+i*3)%45)/100;
 for(let c=1;c<=6;c++){
  const rid=String(4100+c),tilt=c>=5?2:0;
  entry[c]={frame:c,racer_id:rid,tilt_deg:tilt,outer_high_tilt_marker:c>=5,
   historical_inward_move_win_rate:.3,historical_outward_move_top3_rate:.4,
   inner_pressure_kept_course_rate:.5};
  gaps[rid]=c-3;board.push({racer_id:rid,official_rank:c,
   eligibility:"ELIGIBLE",official_rate:10});
  grade.push({boat:c,racer_id:rid,official_current_grade:"B1",program_class:"B1",
   current_grade_status:"SOURCE_CLAIM_CONFIRMED",
   next_grade_publication_status:"ANNOUNCED_SUBJECT_TO_CONFIRMATION",
   next_official_announcement_grade:c>=5?"A2":"B1",
   classes_by_application_period:[{
    grade:c>=5?"A2":"B1",release_status:"ANNOUNCED_PENDING",
    source_captured_at:"2026-11-01T09:00:00+09:00",
    applies_from:"2027-01-01"}],
   research_tags:c>=5?["FORMER_A_CURRENT_B_CLASS"]:[],
   observed_start_gap:{status:"NO_LONG_INTERVAL_IN_RETAINED_STARTS"}});
 }
 const slow=i%2?4:3;
 const input={stage:"P1",cutoff_at:date+"T10:30:00+09:00",
  context:{schema:O.INPUT,race_id:race,as_of:clock,
   six_course_features:s,
   formation:{slow_count:slow,kado_course:slow+1,kado_uke_course:slow},
   entry_tilt_cross_features:entry,
   current_venue_rule_status:"CLAIMED_CURRENT_RECEIPT_REQUIRES_INDEPENDENT_AUTH",
   qualifying_rank_and_point_gaps:{
    border_status:"CURRENT_RANK_ONLY_NOT_FINAL",rate_gaps:gaps,standings:board}},
  baseline:{race_id:race,as_of:clock,
   full_120:O.TICKETS.map(ticket=>({ticket,score:1/120}))},
  grade_transition:{schema:A.GRADE_SCHEMA,race_id:race,as_of:clock,
   production_model_changed:false,
   source_claims_require_independent_Actions_readback:true,
   all_six:grade}};
 return {input,result_ticket:i%3===0?"5-6-1":i%3===1?"1-2-3":"6-5-4",
  result_status:"FINAL_SETTLED",result_source_sha256:"a".repeat(64),
  original_saved_at:date+"T10:05:00+09:00",
  original_sha256:"b".repeat(64),
  result_captured_at:date+"T10:40:00+09:00",
  payout_per_100_yen:i%3===0?15000:1100,refund_boats:[]};
}
const cases=Array.from({length:75},(_,i)=>one(i));
const unmodified=JSON.stringify(cases);
const out=A.compare(cases,{epochs:8,learningRate:.3});
assert.equal(JSON.stringify(cases),unmodified);
assert.equal(out.train_races,60);
assert.equal(out.holdout_races,15);
assert.equal(out.ablations.length,3);
assert.deepEqual(out.ablations.map(g=>g.variant),
 ["A_FROZEN_BASELINE","B_SIX_COURSE_TACTICS","C_TACTICS_PLUS_GRADE"]);
assert.ok(out.ablations.every(x=>x.independent_races===15&&
 Number.isFinite(x.mean_log_loss)&&x.hypothetical_8x100_investment_yen===12000));
assert.ok(out.ablations.every(x=>x.source_proof_independent===false&&
 x.real_purchase_yen===null));
assert.equal(out.model_promoted,false);
assert.equal(out.prospective_future_comparison_complete,false);
const copy=x=>JSON.parse(JSON.stringify(x));
const hold=(x,code)=>assert.throws(()=>A.detail(x),err=>err.message.includes(code));
const f=copy(cases[0]);
f.input.grade_transition.all_six[0].next_grade_publication_status="UNAVAILABLE";
f.input.grade_transition.all_six[0].next_official_announcement_grade=null;
hold(f,"NEXT_GRADE_COVERAGE_HOLD");
const before=copy(cases[0]);
before.input.grade_transition.all_six[0].classes_by_application_period[0].source_captured_at="2026-11-02T08:00:00+09:00";
hold(before,"NEXT_GRADE_PUBLISHED_AFTER_FORECAST");
const mismatch=copy(cases[0]);
mismatch.input.grade_transition.all_six[0].racer_id="4999";
hold(mismatch,"GRADE_ENTRY_BOAT_RACER_MISMATCH");
const downgraded=copy(cases[0]);
downgraded.input.grade_transition.all_six[0].current_grade_status="HOLD_UNCONFIRMED";
hold(downgraded,"CURRENT_GRADE_HOLD");
const missing=copy(cases[0]);missing.refund_boats=null;
hold(missing,"REFUND_DISPOSITION_REQUIRED");
const voided=copy(cases[0]);voided.result_status="VOID";
hold(voided,"FINAL_RESULT_REQUIRED");
const wrongDay=copy(cases[0]);wrongDay.input.context.as_of="2026-11-01T10:50:00+09:00";
hold(wrongDay,"BASELINE_ID_CLOCK_MISMATCH");
const refund=copy(cases[0]);refund.refund_boats=[3];
assert.equal(A.detail(refund).refunded[0],3);
const payoutUnknown=cases.map(c=>({...c,payout_per_100_yen:null}));
const noMoney=A.compare(payoutUnknown,{epochs:1,learningRate:.3});
assert.ok(noMoney.ablations.every(x=>x.hypothetical_roi===null&&
 x.high_payout_hit_count===null));
const lateOriginal=copy(cases[0]);lateOriginal.original_saved_at="2026-11-01T10:35:00+09:00";
hold(lateOriginal,"ORIGINAL_NOT_SAVED_BEFORE_CUTOFF");
assert.throws(()=>A.compare([...cases,cases[0]],{epochs:1}),/DUPLICATE_RACE/);
console.log("SIX_WAY_MATCHED_ABLATION_SYNTHETIC_PASS",
 JSON.stringify({cases:75,train:out.train_races,holdout:out.holdout_races,
 three_variants:true,source_authenticated:false,real_investment:false}));
