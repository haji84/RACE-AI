'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const file=path.join(__dirname,'../web/saved-performance.js');
test('saved-result comparison and editable daily-budget module exists',()=>assert.ok(fs.existsSync(file)));
if(fs.existsSync(file)){
 const P=require(file);
 const top8=[[1,2,3],[1,2,4],[1,3,2],[1,3,4],[1,4,2],[1,4,3],[2,1,3],[2,1,4]];
 const group={scope:'research',sport:'boat',model_id:'invented',model_version:'v1',stage:'P0',variant:'HISTORY_BASELINE'};
 function row(n=1,day='2026-11-06'){
  return {race_id:`${day}-01-${String(n).padStart(2,'0')}`,event_date_jst:day,sport:'boat',scope:'research',private_cycle_view:true,
   cutoff_at:day+'T12:00:00+09:00',offering_status:'UNKNOWN',
   prediction:{model_id:group.model_id,model_version:'v1',stage:'P0',variant:group.variant,ordered_top8:structuredClone(top8),
    as_of:day+'T07:00:00+09:00',generated_at:day+'T07:00:00+09:00',persisted_at:day+'T07:01:00+09:00'},comparison_predictions:[],result:null};
 }
 function final(r,combination=[1,2,3],payout=2000){r.result={status:'final',winning_combinations:[combination],payout_yen_per_100:payout};return r;}
 function supported(r){
  const peer=structuredClone(r.prediction);peer.model_id='independent-peer';peer.ordered_top8=[...structuredClone(top8.slice(4,6)),[6,5,4],[6,5,3],[6,4,3],[5,6,4],[5,6,3],[5,4,3]];
  r.comparison_predictions=[peer,{...structuredClone(peer),variant:'HISTORY_ADDED'}];return r;
 }
 test('1,000-yen allocation follows cross-model support rather than the first forecast rank',()=>{
  const r=supported(final(row(),top8[4])),before=JSON.stringify(r),a=P.allocate(r,r.prediction,1000);
  assert.deepEqual(a.tickets.map(t=>t.amount),[100,100,100,100,200,200,100,100]);
  assert.equal(a.tickets[4].families,2);assert.equal(a.tickets[4].stableFamilies,1);
  const result=P.simulate([r],group,10000,{raceBudget:1000});
  assert.equal(result.spent,1000);assert.equal(result.payout,4000);assert.equal(result.net,3000);assert.equal(result.settledCount,1);
  assert.equal(JSON.stringify(r),before);
 });
 test('1,000-yen plans reserve10 daily slots and do not reinvest weighted returns',()=>{
  const rows=Array.from({length:13},(_,i)=>supported(final(row(i+1),top8[4],100000)));
  const a=P.simulate(rows,group,10000,{raceBudget:1000});
  assert.equal(a.bought,10);assert.equal(a.spent,10000);assert.equal(a.reserved,10000);assert.equal(a.unspent,0);assert.equal(a.payout,2000000);
  assert.equal(P.simulate(rows,group,5000,{raceBudget:1000}).bought,5);
 });
 test('missing or correlated evidence holds200 instead of topping up the first forecast',()=>{
  const r=final(row());r.comparison_predictions=[{...structuredClone(r.prediction),variant:'HISTORY_ADDED'}];
  const a=P.simulate(Array.from({length:12},(_,i)=>({...structuredClone(r),race_id:'held-'+i})),group,10000,{raceBudget:1000});
  assert.equal(a.bought,10);assert.equal(a.spent,8000);assert.equal(a.held,2000);assert.equal(a.unspent,2000);
  assert.equal(a.rows[0].allocation.evidenceStatus,'ADDITIONAL_EVIDENCE_MISSING');assert.equal(a.rows[0].allocation.tickets[0].amount,100);
 });
 test('future, different-stage, different-asof, mismatched-cutoff and duplicate peers cannot influence extra allocation',()=>{
  for(const mutate of [p=>{p.persisted_at='2026-11-06T07:02:00+09:00';},p=>{p.stage='P1';},p=>{p.as_of='2026-11-06T06:59:00+09:00';},p=>{p.cutoff_at='2026-11-06T12:01:00+09:00';}]){
   const r=supported(row());r.comparison_predictions.forEach(mutate);assert.equal(P.allocate(r,r.prediction,1000).held,200);
  }
  const r=supported(row());r.comparison_predictions=r.comparison_predictions.flatMap(p=>[p,structuredClone(p)]);
  assert.equal(P.allocate(r,r.prediction,1000).held,200);
 });
 test('weighted refunds, cancellation, dead heat and unknown payouts use the actual ticket amounts',()=>{
  const r=supported(final(row()));r.result.refund_boats=[4];let a=P.simulate([r],group,10000,{raceBudget:1000});assert.equal(a.refund,700);assert.equal(a.net,1700);
  r.result={status:'void',winning_combinations:[]};a=P.simulate([r],group,10000,{raceBudget:1000});assert.equal(a.refund,1000);assert.equal(a.net,0);
  r.result={status:'final',winning_combinations:[top8[4],top8[0]],payouts:[{bet_type:'trifecta',combination:top8[4],payout_per_100_yen:1200},{bet_type:'trifecta',combination:top8[0],payout_per_100_yen:500}]};
  a=P.simulate([r],group,10000,{raceBudget:1000});assert.equal(a.payout,2900);assert.equal(a.net,1900);
  delete r.result.payouts;a=P.simulate([r],group,10000,{raceBudget:1000});assert.equal(a.pendingStake,1000);assert.equal(a.net,null);
 });
 test('a sole supported candidate receives both100-yen units and weighted overflow is rejected',()=>{
  const r=supported(final(row(),top8[4]));r.comparison_predictions.forEach(p=>{p.ordered_top8[1]=[6,4,2];});
  const a=P.simulate([r],group,10000,{raceBudget:1000});assert.equal(a.rows[0].allocation.tickets[4].amount,300);assert.equal(a.payout,6000);
  r.result.payout_yen_per_100=Number.MAX_SAFE_INTEGER;assert.throws(()=>P.simulate([r],group,10000,{raceBudget:1000}));
 });
 test('1,000-yen caps reset per JST day while held additions stay unused',()=>{
  const rows=[supported(row(1)),supported(row(2)),supported(row(1,'2026-11-07')),supported(row(2,'2026-11-07'))];
  const a=P.simulate(rows,group,1000,{raceBudget:1000});assert.equal(a.bought,2);assert.equal(a.spent,2000);assert.equal(a.pendingStake,2000);assert.equal(a.days.length,2);
 });
 test('support allocation is independent of future results and uses a declared combination tie break',()=>{
  const r=supported(row()),before=P.allocate(r,r.prediction,1000);final(r,[6,5,4],999999);
  assert.deepEqual(P.allocate(r,r.prediction,1000),before);
  const flat=row();flat.comparison_predictions=[{...structuredClone(flat.prediction),model_id:'peer'}];
  const a=P.allocate(flat,flat.prediction,1000);flat.prediction.ordered_top8.reverse();
  const b=P.allocate(flat,flat.prediction,1000);
  assert.deepEqual(a.tickets.filter(t=>t.amount>100).map(t=>t.combination),b.tickets.filter(t=>t.amount>100).map(t=>t.combination).sort((x,y)=>x.join('-').localeCompare(y.join('-'))));
  assert.throws(()=>P.simulate([r],group,10000,{raceBudget:900}));
 });
 test('Top8 matches are visible without promoting research to official performance',()=>{
  const r=final(row());const before=JSON.stringify(r);
  assert.equal(P.compare(r,r.prediction).status,'HIT');
  assert.equal(P.compare(final(row(2),[6,5,4]),r.prediction).status,'MISS');
  assert.equal(P.compare(row(),r.prediction).status,'PENDING');
  assert.equal(P.compare(r,null).status,'NO_FORECAST');
  assert.equal(JSON.stringify(r),before);assert.equal(r.scope,'research');
 });
 test('10,000 per day buys12 complete Top8 plans, spends9,600 and retains400 without reinvesting',()=>{
  const rows=Array.from({length:16},(_,i)=>final(row(i+1),[1,2,3],100000));const before=JSON.stringify(rows);
  const a=P.simulate(rows,group,10000);assert.equal(a.bought,12);assert.equal(a.spent,9600);assert.equal(a.unspent,400);
  assert.equal(a.skippedBudget,4);assert.equal(a.payout,1200000);assert.equal(a.net,1190400);
  assert.equal(a.boughtComparison.hits,12);assert.equal(a.comparison.hits,16);
  assert.equal(P.simulate(rows,group,5000).bought,6);assert.equal(P.simulate(rows,group,700).spent,0);
  assert.equal(JSON.stringify(rows),before);
 });
 test('purchases follow cutoff then race ID, independent of results and display order',()=>{
  const later=row(2),early=row(1);later.cutoff_at='2026-11-06T13:00:00+09:00';
  const a=P.simulate([later,early],group,800);assert.equal(a.rows.find(r=>r.stake>0).race_id,early.race_id);
  final(later);final(early,[6,5,4]);const b=P.simulate([early,later],group,800);
  assert.deepEqual(b.rows.map(r=>[r.race_id,r.stake]),a.rows.map(r=>[r.race_id,r.stake]));
 });
 test('each JST day receives its own editable budget',()=>{
  const rows=[row(1),row(2),row(1,'2026-11-07'),row(2,'2026-11-07')];const a=P.simulate(rows,group,1000);
  assert.equal(a.days.length,2);assert.equal(a.budgetTotal,2000);assert.equal(a.bought,2);assert.equal(a.spent,1600);assert.equal(a.unspent,400);
 });
 test('missing results and missing winning payouts remain financially pending',()=>{
  const pending=row(),hit=final(row(2),[1,2,3],null),miss=final(row(3),[6,5,4],null);
  const a=P.simulate([pending,hit,miss],group,10000);
  assert.equal(a.pendingStake,1600);assert.equal(a.settledStake,800);assert.equal(a.settledNet,-800);assert.equal(a.net,null);
  assert.equal(a.comparison.hits,1);assert.equal(a.comparison.misses,1);assert.equal(a.comparison.pending,1);
 });
 test('void refunds are returned without creating more buying power',()=>{
  const rows=Array.from({length:13},(_,i)=>row(i+1));rows.forEach(r=>r.result={status:'void',winning_combinations:[]});
  const a=P.simulate(rows,group,10000);assert.equal(a.bought,12);assert.equal(a.refund,9600);assert.equal(a.net,0);assert.equal(a.balance,10000);
 });
 test('explicit partial refunds and dead-heat payouts are counted by combination',()=>{
  const r=final(row());r.result.refund_boats=[4];const a=P.simulate([r],group,10000);
  assert.equal(a.refund,500);assert.equal(a.payout,2000);assert.equal(a.net,1700);
  const tied=final(row());tied.result.winning_combinations=[[1,2,3],[1,3,2]];tied.result.payout_yen_per_100=99999;
  tied.result.payouts=[{bet_type:'trifecta',combination:[1,2,3],payout_per_100_yen:1000},{bet_type:'trifecta',combination:[1,3,2],payout_per_100_yen:1200}];
  const b=P.simulate([tied],group,10000);assert.equal(b.payout,2200);assert.equal(b.net,1400);
  delete tied.result.payouts;assert.equal(P.simulate([tied],group,10000).net,null);
 });
 test('unattributed refunds, conflicting winner/refund and unsafe payouts stay under review',()=>{
  const r=final(row());r.result.refund_yen=300;assert.equal(P.simulate([r],group,10000).pendingStake,800);
  delete r.result.refund_yen;r.result.refund_boats=[1];assert.equal(P.simulate([r],group,10000).pendingStake,800);
  delete r.result.refund_boats;r.result.payout_yen_per_100=Number.MAX_SAFE_INTEGER+1;
  assert.equal(P.simulate([r],group,10000).net,null);
 });
 test('refund detail amounts and aliases must explicitly support a full per100 refund',()=>{
  for(const detail of [{combination:[1,2,4],refund_yen_per_100:0},{combination:[1,2,4],refund_yen_per_100:50},{combination:[1,2,4],refund_yen:700}]){
   const r=final(row(),[6,5,4]);r.result.refunds=[detail];const a=P.simulate([r],group,10000);
   assert.equal(a.pendingStake,800);assert.equal(a.net,null);
  }
  const r=final(row(),[6,5,4]);r.result.refunds=[{combination:[1,2,4],refund_yen_per_100:100}];
  assert.equal(P.simulate([r],group,10000).refund,100);
  r.result.refund_combinations=[[1,3,4]];assert.equal(P.simulate([r],group,10000).net,null);
 });
 test('an entire refunded Top8 is shown as refunded instead of a losing race',()=>{
  const r=final(row(),[6,5,4]);r.result.refund_boats=[1];assert.equal(P.compare(r,r.prediction).status,'VOID');
  const a=P.simulate([r],group,10000);assert.equal(a.refund,800);assert.equal(a.net,0);
 });
 test('a single winning combination can use its explicit individual payout',()=>{
  const r=final(row(),[1,2,3],null);r.result.payouts=[{bet_type:'trifecta',combination:[1,2,3],payout_per_100_yen:1300}];
  assert.equal(P.simulate([r],group,10000).net,500);
  r.result.payout_yen_per_100=1400;assert.equal(P.simulate([r],group,10000).net,null);
 });
 test('model variants, late saved forecasts and invalid plans cannot be silently bought',()=>{
  const r=final(row());const h=structuredClone(r.prediction);h.variant='HISTORY_ADDED';h.ordered_top8=top8.slice().reverse();r.comparison_predictions=[h];
  assert.equal(P.pick(r,{...group,variant:'HISTORY_ADDED'}),h);
  assert.equal(P.simulate([r],{...group,model_id:'not-present'},10000).spent,0);
  r.prediction.persisted_at=r.cutoff_at;assert.equal(P.simulate([r],group,10000).spent,0);
  r.prediction.persisted_at='2026-11-06T07:01:00+09:00';r.prediction.ordered_top8[7]=r.prediction.ordered_top8[0];
  assert.equal(P.simulate([r],group,10000).spent,0);
 });
 test('missing model identity/version or stage cannot be merged into a hypothetical purchase plan',()=>{
  for(const [field,value] of [['model_id',null],['model_version',null],['stage','UNKNOWN']]){
   const r=final(row());r.prediction[field]=value;
   assert.equal(P.simulate([r],{...group,[field]:value},10000).spent,0);
  }
 });
 test('invalid budgets and accumulated payout overflow are rejected',()=>{
  for(const n of [NaN,-100,0,99,1050,10000100])assert.throws(()=>P.simulate([row()],group,n));
  const rows=[final(row(),[1,2,3],Number.MAX_SAFE_INTEGER),final(row(2),[1,2,3],Number.MAX_SAFE_INTEGER)];
  assert.throws(()=>P.simulate(rows,group,10000));
  assert.equal(P.summarize(rows,group).hits,2,'result comparison survives financial overflow');
  const noForecast=final(row());noForecast.prediction=null;
  assert.equal(P.summarize([noForecast],null).available,1);
 });
}
