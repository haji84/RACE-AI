"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const M=require("../web/forecast-audit-model.js");
const SHA="0".repeat(64);
function row(id,sport="boat",data={}) {
 return {race_id:id,sport,venue:"架空テスト場",race_no:1,cutoff_at:"2030-01-01T10:00:00+09:00",
 offering_status:"TRIFECTA_OFFERED",race_status:"final",prediction:{
 ordered_top8:[[1,2,3],[2,1,3]],generated_at:"2030-01-01T09:00:00+09:00",
 persisted_at:"2030-01-01T09:05:00+09:00",cutoff_at:"2030-01-01T10:00:00+09:00",
 input_sha256:SHA,prediction_sha256:SHA,model_version:"synthetic-only",
 external_receipt_verified:true,odds_independent:true},result:{
 status:"final",winning_combinations:[[1,2,3]],confirmed_at:"2030-01-01T11:00:00+09:00"},...data};
}
const pack=(records,type="SYNTHETIC_ONLY")=>({schema:"RACE_AI_FORECAST_AUDIT_V1",dataset_status:type,records});
test("four sports with synthetic winners are clearly separate",()=>{
 const races=["boat","keirin","autorace","horse"].map((s,i)=>row("synthetic-"+i,s));
 const parsed=M.merge([pack(races)]),stats=M.summary(parsed.records);
 assert.equal(parsed.dataset_status,"SYNTHETIC_ONLY");
 assert.equal(stats.overall.ledger,4);
 assert.equal(stats.overall.evaluable,4);
 assert.equal(stats.overall.hits,4);
 for(const s of ["boat","keirin","autorace","horse"])assert.equal(stats.bySport[s].hits,1);
});
test("nonforecasts remain in full offered evaluable denominator",()=>{
 const notForecast=row("synthetic-not-forecast","keirin",{prediction:null,no_forecast_reason:"NO_VERIFIED_INPUT"});
 const s=M.summary([row("a"),notForecast]);
 assert.equal(s.overall.evaluable,2);
 assert.equal(s.overall.noForecast,1);
 assert.equal(s.overall.hits,1);
 assert.equal(s.overall.hit8,0.5);
});
test("not offered, void and pending are explicitly excluded",()=>{
 const rows=[
  row("unsold","keirin",{offering_status:"NOT_OFFERED"}),
  row("void","boat",{result:{status:"void",winning_combinations:[]}}),
  row("pending","horse",{result:null})];
 const a=M.summary(rows).overall;
 assert.equal(a.ledger,3);assert.equal(a.evaluable,0);
 assert.equal(a.excluded,3);assert.equal(a.hit8,null);
});
test("post-cutoff and missing external receipt are never counted as frozen",()=>{
 const late=row("late","horse",{prediction:{...row("x").prediction,persisted_at:"2030-01-01T10:02:00+09:00"}});
 const noReceipt=row("unverified","boat",{prediction:{...row("x").prediction,external_receipt_verified:false}});
 assert.equal(M.eligibleFreeze(late),false);
 assert.equal(M.score(late),false);
 assert.equal(M.eligibleFreeze(noReceipt),false);
 assert.equal(M.score(noReceipt),false);
});
test("winning combination must equal one of the ordered tickets",()=>{
 assert.equal(M.score(row("not-hit",{toString(){return "boat"}})),true);
 assert.equal(M.score(row("a","boat",{result:{status:"final",winning_combinations:[[3,2,1]]}})),false);
});
test("duplicate race IDs and conflicting files cannot silently overwrite",()=>{
 const a=pack([row("same")]);
 assert.throws(()=>M.merge([a,a]),/重複/);
 assert.throws(()=>M.parse(pack([row("same"),row("same")])),/重複/);
});
test("malformed bets, ninth ticket and odds dependence rejected",()=>{
 const r=row("x");
 assert.throws(()=>M.parse(pack([{...r,prediction:{...r.prediction,ordered_top8:[[1,1,2]]}}])),/3連単予想/);
 assert.throws(()=>M.parse(pack([{...r,prediction:{...r.prediction,ordered_top8:Array.from({length:9},(_,i)=>[i+1,i+2,i+3])}}])),/3連単予想/);
 assert.throws(()=>M.parse(pack([{...r,prediction:{...r.prediction,odds_independent:false}}])),/オッズ/);
});
test("synthetic and real must never mix",()=>{
 assert.throws(()=>M.merge([pack([row("s")]),pack([row("r")],"REAL_REPORTED")]),/混在/);
});
test("audit-only 322 slots should show unknown hit-rate, not zero",()=>{
 const rows=["boat","keirin","autorace","horse"].map((sport,i)=>row("audit-"+i,sport,{prediction:null,result:null,offering_status:"UNKNOWN"}));
 const a=M.summary(M.parse(pack(rows,"AUDIT_ONLY")).records);
 assert.equal(a.overall.ledger,4);assert.equal(a.overall.evaluable,0);assert.equal(a.overall.hit8,null);
});
