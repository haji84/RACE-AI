'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),os=require('node:os');
const file=path.join(__dirname,'../scripts/saved_performance_report.cjs');
const R=fs.existsSync(file)?require(file):null;
const top=[[1,2,3],[1,2,4],[1,3,2],[1,3,4],[1,4,2],[1,4,3],[2,1,3],[2,1,4]];
function prediction(mid,variant,hit=true){return {model_id:mid,model_version:'v1',stage:'P0',variant,private_cycle_view:true,
 ordered_top8:hit?structuredClone(top):top.map(t=>t.map(n=>7-n)),as_of:'2030-04-01T07:00:00+09:00',generated_at:'2030-04-01T07:00:00+09:00',persisted_at:'2030-04-01T07:01:00+09:00',
 cutoff_at:'2030-04-01T12:00:00+09:00',prediction_sha256:'a'.repeat(64),input_sha256:'c'.repeat(64),pair_sha256:'d'.repeat(64),physical_receipt_sha256:'e'.repeat(64),original_json_sha256:'f'.repeat(64)};}
function fixture(){
 const records=[];for(let i=0;i<6;i++){
  const p=prediction('family','HISTORY_BASELINE',[0,1].includes(i)),q=prediction('family','HISTORY_ADDED',[0,2,3].includes(i));
  p.pair_sha256=q.pair_sha256=String(i+1).repeat(64);
  records.push({race_id:`20300401-01-0${i+1}`,sport:'boat',scope:'research',venue:'invented-private-name-DO-NOT-EMIT',race_no:i+1,event_date_jst:'2030-04-01',cutoff_at:p.cutoff_at,saved_cutoff_variants:[p.cutoff_at],
   offering_status:'UNKNOWN',participants:Array.from({length:6},(_,j)=>({number:j+1,registration_no:String(4001+j),name:'SECRET-NAME-DO-NOT-EMIT'})),prediction:p,comparison_predictions:[q],result:i===4?{status:'void',winning_combinations:[]}:i===5?null:{status:'final',winning_combinations:[[1,2,3]],payout_yen_per_100:1200},result_observations:[],result_revisions:[],missing_reasons:[]});
 }
 return {schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'REAL_REPORTED',event_date_jst:'2030-04-01',records,secret_key:'SECRET-KEY-DO-NOT-EMIT'};
}
test('aggregate report module exists',()=>assert.ok(R&&typeof R.report==='function'));
test('paired report uses one shared normal cohort and exposes discordance uncertainty without an improvement claim',()=>{
 assert.ok(R);const source=fixture(),before=JSON.stringify(source),out=R.report(source,{dailyBudgets:[5000,10000],raceBudgets:[800,1000]});
 assert.equal(JSON.stringify(source),before);assert.equal(out.coverage.races,6);assert.equal(out.coverage.forecasts,12);
 const pair=out.paired_comparisons[0];assert.equal(pair.paired_races,4);assert.equal(pair.both_hit,1);assert.equal(pair.baseline_only,1);assert.equal(pair.challenger_only,2);assert.equal(pair.both_miss,0);
 assert.equal(pair.baseline_hits,2);assert.equal(pair.challenger_hits,3);assert.equal(pair.hit_rate_difference,0.25);assert.equal(pair.exact_discordance_p_value,1);
 assert.ok(pair.uncertainty);assert.equal(out.accuracy_improvement_proven,false);assert.equal(out.prospective_allocation_verified,false);
 assert.equal(out.groups[0].simulations.length,4);assert.equal(out.groups[0].observed.void,1);assert.equal(out.groups[0].observed.pending,1);
 const encoded=JSON.stringify(out);for(const s of ['SECRET-NAME','SECRET-KEY','invented-private-name','ordered_top8','combination','prediction_sha256','20300401-01-01'])assert.ok(!encoded.includes(s),s);
});
test('different source or stage cohorts and repeated versions are never counted as paired gains',()=>{
 assert.ok(R);const source=fixture();source.records[0].comparison_predictions[0].as_of='2030-04-01T06:59:00+09:00';source.records[1].comparison_predictions[0].stage='P1';source.records[2].comparison_predictions.push(structuredClone(source.records[2].comparison_predictions[0]));
 assert.throws(()=>R.report(source));
 source.records[2].comparison_predictions.pop();const out=R.report(source),pair=out.paired_comparisons.find(p=>p.stage==='P0');assert.equal(pair.paired_races,2);assert.ok(pair.excluded.condition_mismatch>=1);
});
test('pending winning payouts remain financially pending while void and explicit partial refunds retain their own amounts',()=>{
 assert.ok(R);const source=fixture();delete source.records[0].result.payout_yen_per_100;source.records[1].result.refund_boats=[4];
 const out=R.report(source,{dailyBudgets:[10000],raceBudgets:[800]});const group=out.groups.find(g=>g.variant==='HISTORY_BASELINE'),sim=group.simulations[0];
 assert.equal(sim.pendingStake,1600);assert.equal(sim.refund,1300);assert.equal(sim.net,null);assert.equal(group.observed.hits,2);
});
test('CLI prints only safe aggregates and never echoes malformed input contents',()=>{
 assert.ok(R);const root=fs.mkdtempSync(path.join(os.tmpdir(),'saved-report-'));try{
  const input=path.join(root,'private.json');fs.writeFileSync(input,JSON.stringify(fixture()));
  let run=cp.spawnSync(process.execPath,[file,'--input',input],{encoding:'utf8'});assert.equal(run.status,0,run.stderr);assert.ok(JSON.parse(run.stdout).coverage);assert.ok(!run.stdout.includes('SECRET-'));
  fs.writeFileSync(input,'SECRET-PRIVATE-MALFORMED');run=cp.spawnSync(process.execPath,[file,'--input',input],{encoding:'utf8'});assert.notEqual(run.status,0);assert.ok(!run.stdout.includes('SECRET-'));assert.ok(!run.stderr.includes('SECRET-'));
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
