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
 assert.equal(M.score(row("synthetic-hit","boat")),true);
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


test("JST day and Monday-Sunday week use event day, not verification timestamp",()=>{
 const thu=row("boat:2026-10-22:01:1","boat",{event_date_jst:"2026-10-22"});
 const mon=row("boat:2026-10-19:01:1","boat",{event_date_jst:"2026-10-19"});
 const sun=row("boat:2026-10-25:01:1","boat",{event_date_jst:"2026-10-25"});
 const prev=row("boat:2026-10-18:01:1","boat",{event_date_jst:"2026-10-18"});
 assert.equal(M.monday("2026-10-22"),"2026-10-19");
 assert.equal(M.inPeriod(thu,"today","2026-10-22"),true);
 assert.equal(M.inPeriod(mon,"today","2026-10-22"),false);
 assert.deepEqual([mon,thu,sun,prev].filter(x=>M.inPeriod(x,"week","2026-10-22")).map(x=>x.race_id),[mon,thu,sun].map(x=>x.race_id));
 assert.equal(M.filtered([mon,thu,sun,prev],{sport:"boat",period:"today",day:"2026-10-22"}).length,1);
});
test("sport and outcome tabs preserve the complete denominator",()=>{
 const a=row("a","boat");
 const b=row("b","boat",{result:{status:"final",winning_combinations:[[3,2,1]]}});
 const c=row("c","keirin",{prediction:null});
 const d=row("d","autorace",{result:{status:"pending",winning_combinations:[]}});
 const all=[a,b,c,d];
 assert.equal(M.filtered(all,{sport:"boat",state:"HIT"}).length,1);
 assert.equal(M.filtered(all,{sport:"boat",state:"MISS"}).length,1);
 assert.equal(M.filtered(all,{state:"NO_FORECAST"}).length,1);
 assert.equal(M.filtered(all,{state:"PENDING"}).length,1);
 assert.equal(M.summary(all).overall.evaluable,3);
 assert.equal(M.summary(all).overall.hits,1);
});
test("payout sort uses confirmed official 100 yen value and puts unknown last",()=>{
 const low=row("low","boat",{result:{status:"final",winning_combinations:[[1,2,3]],payout_yen_per_100:500}});
 const high=row("high","boat",{result:{status:"final",winning_combinations:[[1,2,3]],payout_yen_per_100:10000}});
 const unknown=row("unknown","boat",{result:{status:"pending",winning_combinations:[]}});
 assert.deepEqual(M.sortRaces([low,unknown,high],"payout").map(x=>x.race_id),["high","low","unknown"]);
});
test("model group calculation remains reference-only for different race cohorts",()=>{
 const x=row("boat:2030-01-01:1","boat",{prediction:{...row("x").prediction,model_id:"first",model_version:"A"}});
 const y=row("boat:2030-01-01:2","boat",{prediction:{...row("x").prediction,model_id:"second",model_version:"B"},
  result:{status:"final",winning_combinations:[[3,2,1]]}});
 const z=M.modelComparison([x,y]);
 assert.equal(z.length,2);
 assert.ok(z.every(g=>g.comparison.includes("未証明")));
 assert.ok(M.sortRaces([y,x],"modelRate",[x,y]).every(r=>r.prediction));
 assert.equal(M.sortRaces([y,x],"modelRate",[x,y])[0].race_id,x.race_id);
});
test("revision history must be sequential and latest result consistent",()=>{
 const base=row("revision-race"),first={status:"final",winning_combinations:[[3,2,1]],confirmed_at:"2030-01-01T11:00:00+09:00",revision_no:1};
 const latest={status:"final",winning_combinations:[[1,2,3]],confirmed_at:"2030-01-01T11:20:00+09:00",revision_no:2};
 assert.doesNotThrow(()=>M.parse(pack([{...base,result:latest,result_revisions:[first,latest]}])));
 assert.throws(()=>M.parse(pack([{...base,result:latest,result_revisions:[latest,first]}])),/結果改訂/);
 assert.throws(()=>M.parse(pack([{...base,result:first,result_revisions:[first,latest]}])),/一致/);
 assert.equal(M.score({...base,result:latest}),true);
});
test("market-bearing prediction and fabricated paid receipt cannot enter audit",()=>{
 const r=row("risk");
 assert.throws(()=>M.parse(pack([{...r,prediction:{...r.prediction,market_implied_win_probability:0.5}}])),/市場/);
 assert.throws(()=>M.parse(pack([{...r,actual_purchase:{confirmed:false,stake_yen:100,payout_yen:0,refund_yen:0}}])),/実購入/);
 assert.throws(()=>M.parse(pack([{...r,result:{...r.result,payout_yen_per_100:-1}}])),/公式払戻/);
});
test("confirmed actual purchase is distinct from prediction and never inferred",()=>{
 const a=row("purchased","boat",{actual_purchase:{confirmed:true,stake_yen:800,payout_yen:2300,refund_yen:100}});
 const b=row("not-purchased");
 const all=M.summary([a,b]).overall;
 assert.equal(all.actualPurchases,1);
 assert.equal(all.actualStake,800);
 assert.equal(all.actualNet,1600);
 assert.equal(all.hits,2);
});
test("files keep synthetic metrics entirely separate from real reports",()=>{
 assert.throws(()=>M.merge([pack([row("s")],"SYNTHETIC_ONLY"),pack([row("r")],"REAL_REPORTED")]),/混在/);
});
test("render screen contains tactile four sport tabs, history and owner controls",()=>{
 const fs=require("node:fs"),path=require("node:path");
 const html=fs.readFileSync(path.join(__dirname,"../web/forecast-audit.html"),"utf8");
 for(const key of ["data-sport=\"boat\"","data-sport=\"keirin\"","data-sport=\"autorace\"","data-sport=\"horse\"",
   "data-state=\"HIT\"","data-state=\"MISS\"","data-period=\"today\"","data-period=\"week\"",
   "data-period=\"all\"","value=\"modelRate\"","id=\"model-breakdown\"","id=\"race-list\""])
   assert.ok(html.includes(key),key);
});
