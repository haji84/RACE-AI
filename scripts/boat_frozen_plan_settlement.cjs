#!/usr/bin/env node
'use strict';
/* Read frozen allocations only. No selection, allocation, fetching or bets. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const Data=require('../web/product-data.js'),Performance=require('../web/saved-performance.js');
const root=path.resolve(__dirname,'..'),MAX_BYTES=64*1024*1024;
const SCHEMA='RACE_AI_FROZEN_BUDGET_PLAN_SETTLEMENT_V1';
const policies=['web/product-data.js','web/saved-performance.js','scripts/boat_budget_plan.cjs'];
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const money=value=>Number.isSafeInteger(value)&&value>=0;
const key=t=>t.join('-');
const ticket=t=>Array.isArray(t)&&t.length===3&&t.every(n=>Number.isInteger(n)&&n>=1&&n<=99)&&new Set(t).size===3;
const day=value=>typeof value==='string'&&/^\d{4}-\d\d-\d\d$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
const time=value=>typeof value==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)&&day(value.slice(0,10))&&Number.isFinite(Date.parse(value));
function canonical(value){
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(object(value))return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
 return JSON.stringify(value);
}
class Hold extends Error{}
const need=(ok,reason)=>{if(!ok)throw new Hold(reason);};
function add(a,b){const value=a+b;need(Number.isSafeInteger(value),'FINANCIAL_AMOUNT_REVIEW_REQUIRED');return value;}
function multiply(a,b){const value=a*b;need(Number.isSafeInteger(value),'FINANCIAL_AMOUNT_REVIEW_REQUIRED');return value;}
function input(value){
 const raw=typeof value==='string'?value:JSON.stringify(value);
 need(typeof raw==='string'&&Buffer.byteLength(raw)<=MAX_BYTES,'INPUT_BOUND_OR_SCHEMA_REVIEW_REQUIRED');
 const result=typeof value==='string'?JSON.parse(raw):value;
 need(object(result),'INPUT_BOUND_OR_SCHEMA_REVIEW_REQUIRED');return result;
}
function reference(value){
 need(object(value)&&canonical(Object.keys(value).sort())===canonical(['original_json_sha256','output_sha256','prediction_sha256','race_id','saved_identity'])&&
  typeof value.race_id==='string'&&value.race_id.length>0&&typeof value.saved_identity==='string'&&value.saved_identity.length>0&&
  ['original_json_sha256','output_sha256','prediction_sha256'].every(k=>value[k]===null||hash(value[k]))&&
  (hash(value.prediction_sha256)||hash(value.output_sha256)),'FROZEN_ORIGINAL_REVIEW_REQUIRED');
 return canonical([value.race_id,value.saved_identity]);
}
function groupKey(row,p){
 const code=p.private_cycle_view?Data.codeIdentity(p):null;
 return canonical([row.scope,row.sport,p.stage,p.model_id||null,p.model_version,p.private_cycle_view?p.variant??null:null,...(code?[code]:[])]);
}

// These financial rules mirror the registered policy's private settlement
// function. Only the immutable ticket amounts are supplied; no allocator or
// group picker is called against the later view.
function refundRule(result){
 const boats=result.refund_boats||[],combinations=result.refund_combinations||[],details=result.refunds||[];
 if(!Array.isArray(boats)||boats.some(n=>!Number.isInteger(n)||n<1||n>99)||new Set(boats).size!==boats.length||
  !Array.isArray(combinations)||!combinations.every(ticket)||new Set(combinations.map(key)).size!==combinations.length||!Array.isArray(details))return null;
 for(const detail of details)if(!object(detail)||!ticket(detail.combination)||detail.refund_yen_per_100!==100||
  Object.keys(detail).some(k=>!['combination','refund_yen_per_100','bet_type'].includes(k))||
  detail.bet_type!==undefined&&detail.bet_type!=='trifecta')return null;
 const detailed=details.map(d=>key(d.combination));if(new Set(detailed).size!==detailed.length)return null;
 if(result.refund_combinations!==undefined&&result.refunds!==undefined&&
  canonical(combinations.map(key).sort())!==canonical([...detailed].sort()))return null;
 if(result.refund_yen>0&&!boats.length&&!combinations.length&&!details.length)return null;
 const returned=new Set([...combinations.map(key),...detailed]);
 return combination=>combination.some(n=>boats.includes(n))||returned.has(key(combination));
}
function settleTickets(row,p,entry){
 const comparison=Performance.compare(row,p),result=row.result;
 const pending=()=>({comparison:comparison.status,payout:null,refund:null,settled:false});
 if(comparison.status==='VOID')return {comparison:'VOID',payout:0,refund:entry.stake_yen,settled:true};
 if(!['HIT','MISS'].includes(comparison.status))return pending();
 const refunded=refundRule(result);if(!refunded)return pending();
 let payout=0,refund=0;
 for(const {combination,amount_yen:stake} of entry.tickets){
  if(refunded(combination)){refund=add(refund,stake);continue;}
  if(!comparison.matches.some(w=>key(w)===key(combination)))continue;
  let amount;
  if(result.payouts!==undefined){
   if(!Array.isArray(result.payouts))return pending();
   const found=result.payouts.filter(p=>p?.bet_type==='trifecta'&&ticket(p.combination)&&key(p.combination)===key(combination));
   if(found.length!==1)return pending();amount=found[0].payout_per_100_yen;
   if(result.winning_combinations.length===1&&result.payout_yen_per_100!=null&&result.payout_yen_per_100!==amount)return pending();
  }else if(result.winning_combinations.length===1)amount=result.payout_yen_per_100;
  else return pending();
  if(!money(amount))return pending();payout=add(payout,multiply(amount,stake/100));
 }
 return {comparison:refund===entry.stake_yen?'VOID':comparison.status,payout,refund,settled:true};
}

function verify(plan,view,registration){
 need(plan.schema==='RACE_AI_PRE_OUTCOME_BUDGET_PLAN_V1'&&registration.schema==='RACE_AI_PROSPECTIVE_EVALUATION_REGISTRATION_V1'&&
  day(plan.day)&&time(plan.created_at)&&/^[a-f0-9]{40}$/.test(plan.policy_commit)&&
  plan.actual_purchases===false&&plan.results_used===false&&plan.alternative_scenarios===true&&
  registration.actual_purchases===false&&registration.results_used===false&&registration.alternative_scenarios===true,
  'REGISTRATION_REVIEW_REQUIRED');
 need(hash(registration.plan_sha256)&&sha(canonical(plan))===registration.plan_sha256,'FROZEN_PLAN_HASH_MISMATCH');
 need(['day','created_at','policy_commit','cohort_sha256'].every(k=>plan[k]===registration[k])&&
  Array.isArray(plan.cohort)&&plan.cohort.length>0&&hash(plan.cohort_sha256)&&sha(canonical(plan.cohort))===plan.cohort_sha256&&
  plan.cohort.length===registration.cohort_forecasts,'COHORT_REGISTRATION_MISMATCH');
 need(object(plan.policy_files_sha256)&&object(registration.policy_files_sha256)&&
  canonical(Object.keys(plan.policy_files_sha256).sort())===canonical([...policies].sort())&&
  canonical(plan.policy_files_sha256)===canonical(registration.policy_files_sha256)&&
  policies.every(name=>hash(plan.policy_files_sha256[name])&&sha(fs.readFileSync(path.join(root,name)))===plan.policy_files_sha256[name]),
  'REGISTERED_POLICY_FILES_MISMATCH');
 need(registration.evaluation?.hit_denominator==='NORMAL_MATCHED_SETTLED_RACES_EXCLUDING_VOID_AND_PARTIAL_REFUND',
  'REGISTRATION_REVIEW_REQUIRED');
 const data=Data.parse(view),rows=new Map(data.records.map(r=>[r.race_id,r])),originals=new Map(),cohort=new Set();
 for(const row of data.records)for(const p of Data.candidates(row)){
  const id=canonical([row.race_id,Data.savedPredictionIdentity(p)]);
  need(!originals.has(id),'FROZEN_ORIGINAL_REVIEW_REQUIRED');originals.set(id,{row,p});
 }
 for(const ref of plan.cohort){
  const id=reference(ref),found=originals.get(id);
  need(!cohort.has(id)&&found&&found.row.event_date_jst===plan.day&&
   ['prediction_sha256','output_sha256','original_json_sha256'].every(k=>(found.p[k]??null)===ref[k])&&
   time(found.p.persisted_at)&&Date.parse(found.p.persisted_at)<=Date.parse(plan.created_at)&&
   time(found.p.as_of)&&Date.parse(found.p.as_of)<=Date.parse(plan.created_at),'FROZEN_ORIGINAL_REVIEW_REQUIRED');
  cohort.add(id);
 }
 need(Array.isArray(plan.plans)&&plan.plans.length>0&&plan.plans.length<=10000&&plan.plans.length===registration.scenarios&&
  Array.isArray(registration.scenario_counts)&&registration.scenario_counts.length===plan.plans.length,
  'SCENARIO_REGISTRATION_MISMATCH');
 const declared=new Map(),seen=new Set(),groups=new Map(),races=new Set(),cutoffs=[];
 for(const summary of registration.scenario_counts){need(object(summary)&&Number.isSafeInteger(summary.id)&&summary.id>0&&!declared.has(summary.id),'SCENARIO_REGISTRATION_MISMATCH');declared.set(summary.id,summary);}
 for(const scenario of plan.plans){
  need(object(scenario)&&Number.isSafeInteger(scenario.id)&&scenario.id>0&&!seen.has(scenario.id)&&declared.has(scenario.id)&&
   Number.isSafeInteger(scenario.model_group_index)&&scenario.model_group_index>0&&scenario.model_group_index<=registration.model_groups&&
   typeof scenario.model_group==='string'&&scenario.model_group.length>0&&Number.isSafeInteger(scenario.daily_budget)&&
   scenario.daily_budget>=100&&scenario.daily_budget<=10000000&&scenario.daily_budget%100===0&&[800,1000].includes(scenario.race_budget)&&
   scenario.settlement_status==='UNSETTLED_PLAN'&&Array.isArray(scenario.races)&&scenario.races.length<=10000,'SCENARIO_REGISTRATION_MISMATCH');
  seen.add(scenario.id);
  need(!groups.has(scenario.model_group_index)||groups.get(scenario.model_group_index)===scenario.model_group,'SCENARIO_REGISTRATION_MISMATCH');
  groups.set(scenario.model_group_index,scenario.model_group);
  const summary=declared.get(scenario.id);
  need(['id','model_group_index','daily_budget','race_budget','bought','planned_stake_yen','reserved_yen','held_yen','unspent_yen'].every(k=>summary[k]===scenario[k]),'SCENARIO_REGISTRATION_MISMATCH');
  let bought=0,spent=0,held=0;const perScenario=new Set();
  for(const entry of scenario.races){
   need(object(entry)&&typeof entry.race_id==='string'&&!perScenario.has(entry.race_id)&&rows.has(entry.race_id)&&
    rows.get(entry.race_id).event_date_jst===plan.day&&money(entry.stake_yen)&&entry.stake_yen%100===0&&money(entry.held_yen)&&
    entry.held_yen%100===0&&Array.isArray(entry.tickets),'FROZEN_TICKET_PLAN_REVIEW_REQUIRED');
   perScenario.add(entry.race_id);races.add(entry.race_id);
   let found=null;
   if(entry.forecast!==null){
    const id=reference(entry.forecast);found=originals.get(id);
    need(entry.forecast.race_id===entry.race_id&&cohort.has(id)&&found&&groupKey(found.row,found.p)===scenario.model_group&&
     ['prediction_sha256','output_sha256','original_json_sha256'].every(k=>(found.p[k]??null)===entry.forecast[k]),'FROZEN_ORIGINAL_REVIEW_REQUIRED');
    const actual=found.p.cutoff_at??found.row.cutoff_at??null;
    need(actual===null?entry.cutoff_at===null:time(entry.cutoff_at)&&Date.parse(actual)===Date.parse(entry.cutoff_at),'FROZEN_ORIGINAL_REVIEW_REQUIRED');
   }
   if(entry.stake_yen===0){need(entry.tickets.length===0&&entry.held_yen===0,'FROZEN_TICKET_PLAN_REVIEW_REQUIRED');continue;}
   need(found&&time(entry.cutoff_at)&&Date.parse(plan.created_at)<Date.parse(entry.cutoff_at)&&
    canonical(entry.tickets.map(t=>t?.combination))===canonical(found.p.ordered_top8)&&
    entry.tickets.every(t=>object(t)&&ticket(t.combination)&&Number.isSafeInteger(t.amount_yen)&&t.amount_yen>=100&&t.amount_yen%100===0)&&
    entry.tickets.reduce((n,t)=>add(n,t.amount_yen),0)===entry.stake_yen&&
    add(entry.stake_yen,entry.held_yen)===scenario.race_budget,'FROZEN_TICKET_PLAN_REVIEW_REQUIRED');
   bought++;spent=add(spent,entry.stake_yen);held=add(held,entry.held_yen);cutoffs.push(entry.cutoff_at);
  }
  const reserved=multiply(bought,scenario.race_budget);
  need(scenario.bought===bought&&scenario.planned_stake_yen===spent&&scenario.reserved_yen===reserved&&
   scenario.held_yen===held&&reserved<=scenario.daily_budget&&scenario.unspent_yen===scenario.daily_budget-spent,'FROZEN_TICKET_PLAN_REVIEW_REQUIRED');
 }
 need(groups.size===registration.model_groups&&new Set(groups.values()).size===groups.size&&races.size===registration.cohort_races&&
  cutoffs.length>0&&time(registration.first_included_cutoff_at)&&
  Math.min(...cutoffs.map(Date.parse))===Date.parse(registration.first_included_cutoff_at),'SCENARIO_REGISTRATION_MISMATCH');
 return {rows,originals};
}

function settleFrozenPlan(plan,view,registration){
 let checkpoint='PRE_INPUT';
 const base={schema:SCHEMA,status:'HOLD',day:null,plan_sha256:null,scenarios:[],actual_purchases:false,alternative_scenarios:true,
  hypothetical_budget_returns:true,independent_pre_cutoff_receipt_verified:false,accuracy_improvement_proven:false,promotion_allowed:false};
 try{
  checkpoint='PLAN_INPUT';plan=input(plan);
  checkpoint='SAVED_VIEW_INPUT';view=input(view);
  checkpoint='REGISTRATION_INPUT';registration=input(registration);
  base.day=day(registration.day)?registration.day:null;base.plan_sha256=hash(registration.plan_sha256)?registration.plan_sha256:null;
  checkpoint='REGISTERED_VERIFY';
  const verified=verify(plan,view,registration),scenarios=[];
  checkpoint='SETTLEMENT_CALCULATION';
  for(const scenario of plan.plans){
   const out={id:scenario.id,model_group_index:scenario.model_group_index,budget:scenario.daily_budget,race_budget:scenario.race_budget,
    status:'SETTLED',bought:scenario.bought,spent:scenario.planned_stake_yen,settledStake:0,pendingStake:0,settledCount:0,
    payout:0,refund:0,net:null,roi:null,hits:0,misses:0,void:0,pending:0,review:0,partialRefund:0,hitDenominator:0,hitRate:null};
   for(const entry of scenario.races){
    if(!entry.stake_yen)continue;
    const found=verified.originals.get(reference(entry.forecast)),settled=settleTickets(found.row,found.p,entry);
    if(!settled.settled){out.pendingStake=add(out.pendingStake,entry.stake_yen);out[settled.comparison==='PENDING'?'pending':'review']++;continue;}
    out.settledStake=add(out.settledStake,entry.stake_yen);out.settledCount++;
    out.payout=add(out.payout,settled.payout);out.refund=add(out.refund,settled.refund);
    if(settled.comparison==='VOID')out.void++;
    else if(settled.refund>0||found.row.result?.refund_boats?.length||found.row.result?.refunds?.length||
      found.row.result?.refund_combinations?.length||found.row.result?.refund_yen>0)out.partialRefund++;
    else out[settled.comparison==='HIT'?'hits':'misses']++;
   }
   const returned=add(out.payout,out.refund);
   out.net=out.pendingStake?null:add(returned,-out.spent);
   out.roi=out.settledStake?returned/out.settledStake*100:null;
   out.hitDenominator=out.hits+out.misses;out.hitRate=out.hitDenominator?out.hits/out.hitDenominator:null;
   out.status=out.review?'REVIEW':out.pendingStake?'PENDING':'SETTLED';scenarios.push(out);
  }
  return {...base,status:scenarios.some(s=>s.review)?'REVIEW':scenarios.some(s=>s.pendingStake)?'PENDING':'SETTLED',scenarios};
 }catch(error){
  if(error instanceof Hold)return {...base,reason:error.message};
  // Fixed vocabulary only. A native exception message/stack may contain an
  // owner path or data, so never print it or return it in the report.
  const kind=['TypeError','RangeError','SyntaxError','ReferenceError','Error'].includes(error?.name)?error.name:'Other';
  const allowed={
   'product-data':'PRODUCT_DATA',
   'saved-performance':'SAVED_PERFORMANCE',
   'forecast-audit-model':'FORECAST_AUDIT',
   'boat_frozen_plan_settlement':'FROZEN_SETTLEMENT'
  };
  const positions=[...String(error?.stack||'').matchAll(/(product-data|saved-performance|forecast-audit-model|boat_frozen_plan_settlement)\.(?:js|cjs):([0-9]+):([0-9]+)/g)]
   .slice(0,3).map(m=>({module:allowed[m[1]]||'UNRESOLVED',line:Math.min(Number(m[2])||0,99999)}));
  return {...base,reason:'FROZEN_INPUT_REVIEW_REQUIRED',diagnostic_stage:checkpoint,
   diagnostic_class:kind,diagnostic_module:positions[0]?.module||'UNRESOLVED',
   diagnostic_line:positions[0]?.line||0,diagnostic_caller_module:positions[1]?.module||'UNRESOLVED',
   diagnostic_caller_line:positions[1]?.line||0,diagnostic_origin_module:positions[2]?.module||'UNRESOLVED',
   diagnostic_origin_line:positions[2]?.line||0};
 }
}
function readInput(name){const stat=fs.lstatSync(name);if(!stat.isFile()||stat.isSymbolicLink()||stat.size>MAX_BYTES)throw Error('INPUT');return JSON.parse(fs.readFileSync(name,'utf8'));}
if(require.main===module){
 try{
  const args=process.argv.slice(2),values={};
  for(let i=0;i<args.length;i+=2){if(!['--plan','--view','--registration'].includes(args[i])||!args[i+1]||Object.hasOwn(values,args[i]))throw Error('ARGUMENTS');values[args[i]]=args[i+1];}
  if(Object.keys(values).length!==3)throw Error('ARGUMENTS');
  const result=settleFrozenPlan(readInput(values['--plan']),readInput(values['--view']),readInput(values['--registration']));
  process.stdout.write(JSON.stringify(result)+'\n');if(result.status==='HOLD')process.exitCode=2;
 }catch{process.stderr.write('BOAT_FROZEN_PLAN_SETTLEMENT_REJECTED\n');process.exitCode=1;}
}
module.exports=Object.freeze({settleFrozenPlan});
