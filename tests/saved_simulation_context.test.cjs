'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),crypto=require('node:crypto');
const file=path.join(__dirname,'../scripts/boat_saved_simulation_context.cjs');
const Oracle=fs.existsSync(file)?require(file):null;
const day='2030-04-01',top=[[1,2,3],[1,2,4],[1,3,2],[1,3,4],[1,4,2],[1,4,3],[2,1,3],[2,1,4]];
const digest=value=>crypto.createHash('sha256').update(value).digest('hex');
const groupKey=model=>JSON.stringify(['research','boat','P1',model,'v1',null]);
function fixture(){
  const records=[];
  for(let i=0;i<14;i++){
    const cutoff=day+'T12:'+String(i).padStart(2,'0')+':00+09:00';
    const p={model_id:'SECRET-MOST',model_version:'v1',stage:'P1',ordered_top8:structuredClone(top),prediction_sha256:'a'.repeat(64),output_sha256:'b'.repeat(64),
      native_dispatch_prediction:true,external_receipt_verified:true,eligible_pre_cutoff:true,
      as_of:day+'T07:00:00+09:00',generated_at:day+'T07:00:00+09:00',persisted_at:day+'T07:01:00+09:00',cutoff_at:cutoff};
    const peer={...structuredClone(p),model_id:'SECRET-PEER',native_dispatch_prediction:false};
    const comparisons=[peer];if(i<2)comparisons.push({...structuredClone(p),model_id:'SECRET-RARE'});
    let result={status:'final',winning_combinations:[[6,5,4]],payout_yen_per_100:1000};
    if(i===0||i===6)result={status:'final',winning_combinations:[[1,2,3]],payout_yen_per_100:2500};
    if(i===2)result={status:'void',winning_combinations:[]};
    if(i===3)result={status:'pending',winning_combinations:[]};
    if(i===4)result={status:'final',winning_combinations:[[1,2,3]]};
    if(i===5)result.refund_boats=[1];
    if(i===6)result.refund_combinations=[[1,2,4]];
    records.push({race_id:'20300401-01-'+String(i+1).padStart(2,'0'),sport:'boat',event_date_jst:day,venue:'SECRET-VENUE',race_no:i+1,cutoff_at:cutoff,saved_cutoff_variants:[cutoff],offering_status:'TRIFECTA_OFFERED',
      participants:Array.from({length:6},(_,n)=>({number:n+1,registration_no:String(4000+n),name:'SECRET-PERSON'})),prediction:p,comparison_predictions:comparisons,result,result_observations:[],result_revisions:[]});
  }
  return {schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'REAL_REPORTED',event_date_jst:null,records,owner_key:'SECRET-OWNER-KEY'};
}
function request(view=fixture()){return {view,day,generation:12,as_of:day+'T15:00:00+09:00',native_groups:[['SECRET-MOST','v1',null,null],['SECRET-RARE','v1',null,null]]};}
function build(value=request()){assert.ok(Oracle&&typeof Oracle.buildExpected==='function','the counts-only simulation oracle is available');return Oracle.buildExpected(value);}
const wanted=[
  {budgetPerDay:10000,raceBudget:800,spent:9600,reserved:9600,held:0,unspent:400,payout:5000,refund:1700,settledStake:8000,settledCount:10,pendingStake:1600,bought:12,skippedBudget:2,balance:7100,settledNet:-1300,net:null,roi:83.75,boughtComparison:{hits:3,misses:6,pending:1,void:2,noForecast:0,review:0}},
  {budgetPerDay:10000,raceBudget:1000,spent:10000,reserved:10000,held:0,unspent:0,payout:10000,refund:2200,settledStake:8000,settledCount:8,pendingStake:2000,bought:10,skippedBudget:4,balance:12200,settledNet:4200,net:null,roi:152.5,boughtComparison:{hits:3,misses:4,pending:1,void:2,noForecast:0,review:0}},
  {budgetPerDay:5000,raceBudget:800,spent:4800,reserved:4800,held:0,unspent:200,payout:2500,refund:1600,settledStake:3200,settledCount:4,pendingStake:1600,bought:6,skippedBudget:8,balance:4300,settledNet:900,net:null,roi:128.125,boughtComparison:{hits:2,misses:1,pending:1,void:2,noForecast:0,review:0}},
  {budgetPerDay:5000,raceBudget:1000,spent:5000,reserved:5000,held:0,unspent:0,payout:5000,refund:1000,settledStake:3000,settledCount:3,pendingStake:2000,bought:5,skippedBudget:9,balance:6000,settledNet:3000,net:null,roi:200,boughtComparison:{hits:2,misses:1,pending:1,void:1,noForecast:0,review:0}}
];
test('literal four-scenario totals include refunds, unknown payouts, pending stakes and exact hit denominators',()=>{
  const input=request(),before=JSON.stringify(input),value=build(input);
  assert.equal(JSON.stringify(input),before);assert.equal(value.schema,'RACE_AI_SAVED_SITE_SIMULATION_EXPECTED_V1');
  assert.equal(value.day,day);assert.equal(value.generation,12);assert.equal(value.group_sha256,digest(groupKey('SECRET-MOST')));
  assert.equal(value.eligible_native_races,14);assert.equal(value.budget_cap_exercised,true);
  assert.equal(value.budget_cap_coverage,'EXERCISED');
  assert.deepEqual(value.observed,{races:14,available:13,hits:3,misses:8,pending:1,void:2,noForecast:0,review:0});
  assert.equal(value.scenarios.length,4);
  for(const expected of wanted){
    const actual=value.scenarios.find(s=>s.budgetPerDay===expected.budgetPerDay&&s.raceBudget===expected.raceBudget);
    for(const [key,want] of Object.entries(expected))assert.deepEqual(actual[key],want,key);
  }
});
test('the native group uses forecast availability only, with canonical ties and no outcome-based selection',()=>{
  const input=request(),first=build(input);
  for(const row of input.view.records)row.result={status:'void',winning_combinations:[]};
  const voids=build(input);assert.equal(voids.group_sha256,first.group_sha256);
  for(const scenario of voids.scenarios){assert.equal(scenario.refund,scenario.spent);assert.equal(scenario.payout,0);assert.equal(scenario.net,0);assert.equal(scenario.roi,100);}
  for(const row of input.view.records)row.comparison_predictions.push({...structuredClone(row.prediction),model_id:'A-SECRET-TIE'});
  input.native_groups.push(['A-SECRET-TIE','v1',null,null]);
  assert.equal(build(input).group_sha256,digest(groupKey('A-SECRET-TIE')));
});
test('late, unverified and retired originals cannot win the native group selection',()=>{
  const input=request();
  for(let i=2;i<input.view.records.length;i++)input.view.records[i].prediction.external_receipt_verified=false;
  input.view.records[1].prediction.persisted_at=input.view.records[1].prediction.cutoff_at;
  assert.equal(build(input).group_sha256,digest(groupKey('SECRET-RARE')));
  input.native_groups=[['seller-shadow-v1-20261104','v1',null,null]];
  assert.throws(()=>build(input));
});
test('a native model without a saved version binds its verified saved code identity',()=>{
  const input=request(),commit='c'.repeat(40);
  for(const row of input.view.records)Object.assign(row.prediction,{model_version:null,source_code_commit:commit,artifact_id:31,original_json_sha256:'d'.repeat(64)});
  input.native_groups[0]=['SECRET-MOST',null,null,commit];
  const value=build(input);
  assert.equal(value.group_sha256,digest(JSON.stringify(['research','boat','P1','SECRET-MOST',null,null,commit])));
  assert.equal(value.eligible_native_races,14);
});
test('only the selected day is parsed and a small cohort reports insufficient budget-cap coverage',()=>{
  const input=request();input.view.records=input.view.records.slice(0,2);
  input.view.records.push({sport:'boat',event_date_jst:'2030-03-31',race_id:'SECRET-IRRELEVANT',prediction:{ordered_top8:'invalid'}});
  const value=build(input);assert.equal(value.observed.races,2);assert.equal(value.budget_cap_exercised,false);
  assert.equal(value.budget_cap_coverage,'INSUFFICIENT_ELIGIBLE_RACES');
  assert.equal(value.scenarios.find(s=>s.budgetPerDay===10000&&s.raceBudget===800).spent,1600);
});
test('fully settled amounts remain numeric instead of becoming unknown or retaining the old pending balance',()=>{
  const input=request();input.view.records[3].result={status:'final',winning_combinations:[[6,5,4]],payout_yen_per_100:1000};
  input.view.records[4].result.payout_yen_per_100=2500;
  const value=build(input).scenarios.find(s=>s.budgetPerDay===10000&&s.raceBudget===800);
  assert.equal(value.pendingStake,0);assert.equal(value.settledStake,9600);assert.equal(value.payout,7500);
  assert.equal(value.refund,1700);assert.equal(value.net,-400);assert.equal(value.settledNet,-400);
});
test('closed-only result cards exclude upcoming rows without changing the all-row financial simulation',()=>{
  const input=request();input.as_of=day+'T09:00:00+09:00';
  const value=build(input);
  assert.deepEqual(value.lifecycle,{as_of:input.as_of,closed:13,upcoming:1,unknown:0});
  assert.deepEqual(value.observed_closed,{races:13,available:13,hits:3,misses:8,pending:0,void:2,noForecast:0,review:0});
  assert.equal(value.observed.pending,1);assert.equal(value.scenarios[0].pendingStake,1600);
  input.as_of=day+'T12:04:00+09:00';
  assert.equal(build(input).observed_closed.pending,1);
});
test('stdin CLI emits aggregates and a group hash without private picks, names, identifiers or keys',()=>{
  assert.ok(Oracle);const run=cp.spawnSync(process.execPath,[file],{input:JSON.stringify(request()),encoding:'utf8'});
  assert.equal(run.status,0,run.stderr);assert.equal(run.stderr,'');assert.equal(JSON.parse(run.stdout).scenarios.length,4);
  for(const text of ['SECRET','ordered_top8','race_id','winning_combinations','participants','model_id','prediction_sha256'])assert.ok(!run.stdout.includes(text),text);
  const bad=cp.spawnSync(process.execPath,[file],{input:'SECRET-MALFORMED-PRIVATE-INPUT',encoding:'utf8'});
  assert.notEqual(bad.status,0);assert.equal(bad.stderr,'');assert.ok(!bad.stdout.includes('SECRET'));
});
test('bounded input rejects at the byte limit without reading the remaining private payload',()=>{
  assert.equal(typeof Oracle.readBounded,'function');
  const os=require('node:os'),folder=fs.mkdtempSync(path.join(os.tmpdir(),'simulation-bounded-'));
  let fd;
  try{
    const input=path.join(folder,'invented.bin');fs.writeFileSync(input,Buffer.from(Array.from({length:256},(_,i)=>i)));
    fd=fs.openSync(input,'r');assert.throws(()=>Oracle.readBounded(fd,16));
    const next=Buffer.alloc(1);assert.equal(fs.readSync(fd,next,0,1,null),1);assert.equal(next[0],17,'only limit+1 bytes were consumed');
  }finally{if(fd!==undefined)fs.closeSync(fd);fs.rmSync(folder,{recursive:true,force:true});}
});
