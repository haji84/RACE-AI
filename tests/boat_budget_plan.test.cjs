'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process');
const file=path.join(__dirname,'../scripts/boat_budget_plan.cjs'),M=fs.existsSync(file)?require(file):null;
const top=[[1,2,3],[1,2,4],[1,3,2],[1,3,4],[1,4,2],[1,4,3],[2,1,3],[2,1,4]];
function fixture(){
 const records=[];
 for(const day of ['2030-04-01','2030-04-02'])for(let i=0;i<14;i++){
  const p={model_id:'invented-family',model_version:'v1',stage:'P0',ordered_top8:structuredClone(top),prediction_sha256:'a'.repeat(64),
   as_of:day+'T07:00:00+09:00',generated_at:day+'T07:00:00+09:00',persisted_at:day+'T07:01:00+09:00',cutoff_at:day+'T12:00:00+09:00'};
  records.push({race_id:day.replaceAll('-','')+'-01-'+String(i+1).padStart(2,'0'),sport:'boat',scope:'research',venue:'SECRET-VENUE-DO-NOT-EMIT',race_no:i+1,event_date_jst:day,cutoff_at:p.cutoff_at,saved_cutoff_variants:[p.cutoff_at],offering_status:'UNKNOWN',
   participants:Array.from({length:6},(_,j)=>({number:j+1,registration_no:String(4000+j),name:'SECRET-NAME-DO-NOT-EMIT'})),prediction:p,
   comparison_predictions:[{...structuredClone(p),model_id:'invented-peer'}],result:{status:'final',winning_combinations:[[6,5,4]],payout_yen_per_100:1234567},result_observations:[],result_revisions:[],missing_reasons:[]});
 }
 return {schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'REAL_REPORTED',records,event_date_jst:null,secret_key:'SECRET-KEY-DO-NOT-EMIT'};
}
const options={day:'2030-04-02',createdAt:'2030-04-02T07:30:00+09:00',policyCommit:'1'.repeat(40),dailyBudgets:[5000,10000],raceBudgets:[800,1000]};
test('prospective plan freezer is available',()=>assert.ok(M&&typeof M.freezePlan==='function'));
test('day filtering, pending stakes and exact result-independent plan hashes preserve all alternative scenarios',()=>{
 assert.ok(M);const input=fixture(),before=JSON.stringify(input),one=M.freezePlan(input,options);
 assert.equal(JSON.stringify(input),before);assert.equal(one.safeSummary.cohort_races,14);assert.equal(one.safeSummary.cohort_forecasts,28);assert.equal(one.safeSummary.scenarios,8);
 assert.equal(one.privateBundle.plans.length,8);assert.ok(one.privateBundle.plans.every(p=>p.races.every(r=>r.race_id.startsWith('20300402'))));
 const thousand=one.privateBundle.plans.find(p=>p.daily_budget===10000&&p.race_budget===1000);
 assert.equal(thousand.bought,10);assert.equal(thousand.planned_stake_yen,10000);assert.equal(thousand.settlement_status,'UNSETTLED_PLAN');assert.ok(!Object.hasOwn(thousand,'net'));
 for(const row of input.records){row.result={status:'void',winning_combinations:[]};row.result_observations=[{SECRET:'NEW-RESULT'}];row.result_observation_rejections=[{SECRET:'NEW-REJECTION'}];}
 input.results_synced_at='2030-04-03T20:00:00Z';
 const two=M.freezePlan(input,options);assert.equal(one.safeSummary.plan_sha256,two.safeSummary.plan_sha256);assert.deepEqual(one.privateBundle,two.privateBundle);
 const reordered=fixture();reordered.records.reverse();for(const row of reordered.records){const p=row.prediction;row.prediction=row.comparison_predictions[0];row.comparison_predictions=[p];}
 assert.equal(M.freezePlan(reordered,options).safeSummary.plan_sha256,one.safeSummary.plan_sha256);
 assert.ok(!JSON.stringify(one.privateBundle).includes('1234567'));assert.ok(!JSON.stringify(one.privateBundle).includes('SECRET-'));
});
test('receipt availability and first included cutoff prevent backdated or late allocation locks',()=>{
 assert.ok(M);assert.throws(()=>M.freezePlan(fixture(),{...options,createdAt:'2030-04-02T12:00:00+09:00'}));
 const early=fixture();early.records.filter(r=>r.event_date_jst===options.day)[0].prediction.persisted_at='2030-04-02T07:45:00+09:00';
 assert.throws(()=>M.freezePlan(early,options));
 assert.throws(()=>M.freezePlan(fixture(),{...options,day:'2030-04-03'}));
 assert.throws(()=>M.freezePlan(fixture(),{...options,policyCommit:'UNKNOWN'}));
});
test('CLI writes a 0600 private bundle outside Git and prints hashes and counts without picks or names',()=>{
 assert.ok(M);const folder=fs.mkdtempSync(path.join(os.tmpdir(),'budget-lock-'));try{
  const input=path.join(folder,'input.json'),output=path.join(folder,'lock.json');fs.writeFileSync(input,JSON.stringify(fixture()));
  const run=cp.spawnSync(process.execPath,[file,'--input',input,'--output',output,'--day',options.day,'--created-at',options.createdAt,'--policy-commit',options.policyCommit],{encoding:'utf8'});
  assert.equal(run.status,0,run.stderr);const summary=JSON.parse(run.stdout);assert.equal(summary.cohort_forecasts,28);assert.equal(fs.statSync(output).mode&0o777,0o600);
  assert.equal(require('node:crypto').createHash('sha256').update(fs.readFileSync(output)).digest('hex'),summary.plan_sha256);
  assert.ok(JSON.parse(fs.readFileSync(output,'utf8')).plans);for(const text of ['SECRET-','combination','race_id','ordered_top8','invented-family'])assert.ok(!run.stdout.includes(text),text);
  const gitFolder=path.join(folder,'git');fs.mkdirSync(gitFolder);fs.mkdirSync(path.join(gitFolder,'.git'));
  const bad=cp.spawnSync(process.execPath,[file,'--input',input,'--output',path.join(gitFolder,'lock.json'),'--day',options.day,'--created-at',options.createdAt,'--policy-commit',options.policyCommit],{encoding:'utf8'});
  assert.notEqual(bad.status,0);assert.ok(!bad.stderr.includes('SECRET-'));
 }finally{fs.rmSync(folder,{recursive:true,force:true});}
});
