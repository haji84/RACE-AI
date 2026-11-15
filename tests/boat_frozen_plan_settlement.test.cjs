'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process'),crypto=require('node:crypto');
const Freeze=require('../scripts/boat_budget_plan.cjs');
const file=path.join(__dirname,'../scripts/boat_frozen_plan_settlement.cjs');
const M=fs.existsSync(file)?require(file):null;
const top=[[1,2,3],[1,2,4],[1,3,2],[1,3,4],[1,4,2],[1,4,3],[2,1,3],[2,1,4]];
const peer=[top[4],[6,5,4],[6,5,3],[6,4,3],[5,6,4],[5,6,3],[5,4,3],[4,6,5]];
const day='2030-04-01';
function canonical(v){return Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);}
const sha=v=>crypto.createHash('sha256').update(v).digest('hex');
function fixture(n=1){
 const records=Array.from({length:n},(_,i)=>{
  const p={model_id:'initial-family',model_version:'v1',stage:'P0',ordered_top8:structuredClone(top),prediction_sha256:'a'.repeat(64),
   output_sha256:'b'.repeat(64),original_json_sha256:'c'.repeat(64),as_of:day+'T07:00:00+09:00',generated_at:day+'T07:00:00+09:00',
   persisted_at:day+'T07:01:00+09:00',cutoff_at:day+'T12:00:00+09:00'};
  return {race_id:'20300401-01-'+String(i+1).padStart(2,'0'),sport:'boat',scope:'research',venue:'SECRET-VENUE',race_no:i+1,event_date_jst:day,
   cutoff_at:p.cutoff_at,saved_cutoff_variants:[p.cutoff_at],offering_status:'UNKNOWN',participants:Array.from({length:6},(_,j)=>({number:j+1,registration_no:String(4000+j),name:'SECRET-NAME'})),
   prediction:p,comparison_predictions:[{...structuredClone(p),model_id:'initial-peer',prediction_sha256:'d'.repeat(64),ordered_top8:structuredClone(peer)}],result:null,
   result_observations:[],result_revisions:[],missing_reasons:[]};
 });
 const view={schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'REAL_REPORTED',records,event_date_jst:day,secret_key:'SECRET-KEY'};
 // The fixture is frozen before any test supplies an outcome. Settlement must
 // never call the freezer or its allocation methods after this point.
 const frozen=Freeze.freezePlan(view,{day,createdAt:day+'T07:30:00+09:00',policyCommit:'1'.repeat(40),dailyBudgets:[n*1000],raceBudgets:[1000]});
 return {view,plan:frozen.privateBundle,registration:{...frozen.safeSummary,schema:'RACE_AI_PROSPECTIVE_EVALUATION_REGISTRATION_V1',
  evaluation:{hit_denominator:'NORMAL_MATCHED_SETTLED_RACES_EXCLUDING_VOID_AND_PARTIAL_REFUND',promotion_allowed:false,improvement_proven:false}}};
}
function final(row,win=top[4],payout=2000){row.result={status:'final',winning_combinations:[structuredClone(win)],payout_yen_per_100:payout};}
function settle(f){assert.ok(M&&typeof M.settleFrozenPlan==='function','frozen allocation settlement reader is absent');return M.settleFrozenPlan(f.plan,f.view,f.registration);}
function family(result){return result.scenarios.find(s=>s.id===1);}

test('frozen unequal ticket amounts survive later model intake and display reordering',()=>{
 const f=fixture(),frozen=canonical(f.plan);assert.deepEqual(f.plan.plans[0].races[0].tickets.map(t=>t.amount_yen),[100,100,100,100,300,100,100,100]);
 final(f.view.records[0]);const before=canonical(f.view),first=settle(f),s=family(first);
 assert.equal(first.status,'SETTLED');assert.equal(s.spent,1000);assert.equal(s.payout,6000);assert.equal(s.net,5000);assert.equal(s.hits,1);assert.equal(s.misses,0);
 assert.equal(canonical(f.view),before);assert.equal(canonical(f.plan),frozen);
 const later={...structuredClone(f.view.records[0].prediction),model_id:'later-intake-family',prediction_sha256:'e'.repeat(64),
  ordered_top8:[top[0],[6,5,4],[6,5,3],[6,4,3],[5,6,4],[5,6,3],[5,4,3],[4,6,5]]};
 f.view.records[0].comparison_predictions.push(later);
 const original=f.view.records[0].prediction;f.view.records[0].prediction=f.view.records[0].comparison_predictions.pop();f.view.records[0].comparison_predictions.reverse();f.view.records[0].comparison_predictions.push(original);
 assert.deepEqual(settle(f),first);assert.equal(canonical(f.plan),frozen);
});

test('partial results retain the whole unknown stake and never turn pending into a miss',()=>{
 const f=fixture(2);final(f.view.records[0]);const result=settle(f),s=family(result);
 assert.equal(result.status,'PENDING');assert.equal(s.budget,2000);assert.equal(s.bought,2);assert.equal(s.spent,2000);
 assert.equal(s.settledStake,1000);assert.equal(s.pendingStake,1000);assert.equal(s.payout,6000);assert.equal(s.refund,0);assert.equal(s.net,null);assert.equal(s.roi,600);
 assert.equal(s.hits,1);assert.equal(s.misses,0);assert.equal(s.pending,1);assert.equal(s.review,0);
});

test('void and weighted partial refunds settle cash separately from normal hit denominators',()=>{
 const f=fixture(2);f.view.records[0].result={status:'void',winning_combinations:[]};final(f.view.records[1],[6,5,3]);f.view.records[1].result.refund_boats=[4];
 const s=family(settle(f));assert.equal(s.spent,2000);assert.equal(s.settledStake,2000);assert.equal(s.pendingStake,0);assert.equal(s.refund,1700);assert.equal(s.payout,0);assert.equal(s.net,-300);
 assert.equal(s.void,1);assert.equal(s.partialRefund,1);assert.equal(s.hitDenominator,0);assert.equal(s.hits,0);assert.equal(s.misses,0);
});

test('explicit refund combinations use their actual amounts and unattributed or partial refund values remain under review',()=>{
 const f=fixture();final(f.view.records[0]);f.view.records[0].result.refunds=[{combination:top[1],refund_yen_per_100:100}];
 let s=family(settle(f));assert.equal(s.refund,100);assert.equal(s.payout,6000);assert.equal(s.net,5100);assert.equal(s.partialRefund,1);assert.equal(s.hits,0);
 for(const result of [{status:'final',winning_combinations:[top[4]],payout_yen_per_100:2000,refund_yen:700},
  {status:'final',winning_combinations:[top[4]],payout_yen_per_100:2000,refunds:[{combination:top[1],refund_yen_per_100:50}]}]){
  f.view.records[0].result=result;s=family(settle(f));assert.equal(s.pendingStake,1000);assert.equal(s.net,null);assert.equal(s.refund,0);assert.equal(s.review,1);assert.equal(s.misses,0);
 }
});

test('refund races outside the bought ticket scope remain outside the registered normal hit denominator',()=>{
 const f=fixture();final(f.view.records[0]);f.view.records[0].result.refund_boats=[6];
 const s=family(settle(f));assert.equal(s.refund,0);assert.equal(s.payout,6000);assert.equal(s.net,5000);
 assert.equal(s.partialRefund,1);assert.equal(s.hits,0);assert.equal(s.misses,0);assert.equal(s.hitDenominator,0);
});

test('combined known payout and refund overflow cannot be hidden by another pending race',()=>{
 const f=fixture(3);final(f.view.records[0],top[0],Number.MAX_SAFE_INTEGER);f.view.records[1].result={status:'void',winning_combinations:[]};
 const result=settle(f);assert.equal(result.status,'HOLD');assert.deepEqual(result.scenarios,[]);
});

test('dead heat payouts scale each frozen amount and unknown or duplicate winning payouts stay pending review',()=>{
 const f=fixture();f.view.records[0].result={status:'final',winning_combinations:[top[4],top[0]],payouts:[
  {bet_type:'trifecta',combination:top[4],payout_per_100_yen:1200},{bet_type:'trifecta',combination:top[0],payout_per_100_yen:500}]};
 let s=family(settle(f));assert.equal(s.payout,4100);assert.equal(s.net,3100);assert.equal(s.hits,1);
 delete f.view.records[0].result.payouts;s=family(settle(f));assert.equal(s.pendingStake,1000);assert.equal(s.net,null);assert.equal(s.misses,0);assert.equal(s.review,1);
 f.view.records[0].result={status:'final',winning_combinations:[top[4]],payout_yen_per_100:2000,payouts:[
  {bet_type:'trifecta',combination:top[4],payout_per_100_yen:2000},{bet_type:'trifecta',combination:top[4],payout_per_100_yen:2000}]};
 s=family(settle(f));assert.equal(s.pendingStake,1000);assert.equal(s.net,null);assert.equal(s.review,1);
});

test('a confirmed unrefunded miss can settle without an irrelevant winner payout',()=>{
 const f=fixture();final(f.view.records[0],[6,5,3],null);const s=family(settle(f));
 assert.equal(s.pendingStake,0);assert.equal(s.settledStake,1000);assert.equal(s.payout,0);assert.equal(s.net,-1000);assert.equal(s.misses,1);assert.equal(s.hitDenominator,1);
});

test('missing originals, native hash changes, top8 changes and plan or registration tampering hold all scenarios',()=>{
 const cases=[f=>{f.view.records[0].prediction=null;},f=>{f.view.records[0].prediction.prediction_sha256='f'.repeat(64);},
  f=>{f.view.records[0].prediction.output_sha256='f'.repeat(64);},f=>{f.view.records[0].prediction.original_json_sha256='f'.repeat(64);},
  f=>{f.view.records[0].prediction.ordered_top8.reverse();},f=>{f.plan.plans[0].races[0].tickets[0].amount_yen=200;},
  f=>{f.registration.cohort_sha256='f'.repeat(64);},f=>{f.registration.policy_files_sha256['web/product-data.js']='f'.repeat(64);},
  f=>{f.registration.scenario_counts[0].planned_stake_yen=900;}];
 for(const mutate of cases){const f=fixture();mutate(f);const result=settle(f);assert.equal(result.status,'HOLD');assert.deepEqual(result.scenarios,[]);}
});

test('policy byte mismatch holds without modifying the three registered files',t=>{
 const f=fixture(),original=fs.readFileSync;
 t.mock.method(fs,'readFileSync',function(name,...args){if(path.resolve(String(name))===path.resolve(__dirname,'../web/saved-performance.js'))return Buffer.from('different policy');return original.call(this,name,...args);});
 assert.equal(settle(f).status,'HOLD');
});

test('settlement never invokes allocation, group picking, simulation or plan freezing after outcomes',()=>{
 const f=fixture();final(f.view.records[0]);const directory=fs.mkdtempSync(path.join(os.tmpdir(),'frozen-no-reallocate-'));
 try{
  const input=path.join(directory,'input.json');fs.writeFileSync(input,JSON.stringify(f),{mode:0o600});
  const code=`const fs=require('node:fs'),p=require.resolve('./web/saved-performance.js'),old=require(p);require.cache[p].exports={...old,allocate(){throw Error('NO_REALLOCATION')},simulate(){throw Error('NO_REALLOCATION')},pick(){throw Error('NO_RECHOOSING')}};const b=require.resolve('./scripts/boat_budget_plan.cjs');require(b);require.cache[b].exports={freezePlan(){throw Error('NO_REFREEZING')}};const f=JSON.parse(fs.readFileSync(process.argv[1]));const r=require('./scripts/boat_frozen_plan_settlement.cjs').settleFrozenPlan(f.plan,f.view,f.registration);process.stdout.write(JSON.stringify(r));`;
  const run=cp.spawnSync(process.execPath,['-e',code,input],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});
  assert.equal(run.status,0,run.stderr);assert.equal(JSON.parse(run.stdout).status,'SETTLED');
 }finally{fs.rmSync(directory,{recursive:true,force:true});}
});

test('CLI exposes aggregates only and gives a fixed safe error for invalid or oversized private inputs',()=>{
 assert.ok(M);const f=fixture();final(f.view.records[0]);const folder=fs.mkdtempSync(path.join(os.tmpdir(),'frozen-settle-cli-'));
 try{
  const names={plan:path.join(folder,'plan.json'),view:path.join(folder,'view.json'),registration:path.join(folder,'registration.json')};
  for(const [key,name] of Object.entries(names))fs.writeFileSync(name,JSON.stringify(f[key]),{mode:0o600});
  const args=['--plan',names.plan,'--view',names.view,'--registration',names.registration];let run=cp.spawnSync(process.execPath,[file,...args],{encoding:'utf8'});
  assert.equal(run.status,0,run.stderr);const result=JSON.parse(run.stdout);assert.equal(result.status,'SETTLED');
  for(const forbidden of ['SECRET-','race_id','saved_identity','combination','initial-family','initial-peer','ordered_top8'])assert.ok(!run.stdout.includes(forbidden),forbidden);
  fs.writeFileSync(names.view,'SECRET-PRIVATE-INVALID-JSON');run=cp.spawnSync(process.execPath,[file,...args],{encoding:'utf8'});
  assert.equal(run.status,1);assert.equal(run.stdout,'');assert.equal(run.stderr,'BOAT_FROZEN_PLAN_SETTLEMENT_REJECTED\n');
  fs.truncateSync(names.view,64*1024*1024+1);run=cp.spawnSync(process.execPath,[file,...args],{encoding:'utf8'});
  assert.equal(run.status,1);assert.equal(run.stdout,'');assert.equal(run.stderr,'BOAT_FROZEN_PLAN_SETTLEMENT_REJECTED\n');
 }finally{fs.rmSync(folder,{recursive:true,force:true});}
});
