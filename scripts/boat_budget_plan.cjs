#!/usr/bin/env node
'use strict';
/* Freeze deterministic alternative allocations. No results, source GET or bet. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const Data=require('../web/product-data.js'),Performance=require('../web/saved-performance.js');
const root=path.resolve(__dirname,'..');
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
function canonical(value){
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
 return JSON.stringify(value);
}
const validDay=day=>typeof day==='string'&&/^\d{4}-\d\d-\d\d$/.test(day)&&Number.isFinite(Date.parse(day+'T00:00:00Z'))&&new Date(day+'T00:00:00Z').toISOString().slice(0,10)===day;
const validTime=time=>typeof time==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(time)&&validDay(time.slice(0,10))&&Number.isFinite(Date.parse(time));
function forecastReference(row,p){
 return {race_id:row.race_id,saved_identity:Data.savedPredictionIdentity(p),
  prediction_sha256:p.prediction_sha256??null,output_sha256:p.output_sha256??null,
  original_json_sha256:p.original_json_sha256??null};
}
function freezePlan(view,{day,createdAt,policyCommit,dailyBudgets=[5000,10000],raceBudgets=[800,1000]}={}){
 if(!validDay(day)||!validTime(createdAt)||typeof policyCommit!=='string'||!/^[a-f0-9]{40}$/.test(policyCommit)||
    !Array.isArray(dailyBudgets)||!dailyBudgets.length||dailyBudgets.length>10||dailyBudgets.some(n=>!Number.isSafeInteger(n)||n<100||n>10000000||n%100)||
    !Array.isArray(raceBudgets)||!raceBudgets.length||raceBudgets.length>2||raceBudgets.some(n=>![800,1000].includes(n)))throw new Error('BUDGET_PLAN_OPTIONS_INVALID');
 const source=typeof view==='string'?JSON.parse(view):structuredClone(view);
 if(!Array.isArray(source?.records))throw new Error('BUDGET_PLAN_INPUT_INVALID');
 // Filter before parsing or simulating. Outcome documents, their revisions and
 // derived result metadata cannot enter a plan or its content hash.
 const selected=source.records.filter(r=>r.event_date_jst===day).sort((a,b)=>a.race_id.localeCompare(b.race_id));
 if(!selected.length)throw new Error('BUDGET_PLAN_DAY_EMPTY');
 const clean=selected.map(row=>({...row,result:null,result_observations:[],result_revisions:[],result_observation_rejections:[]}));
 const data=Data.parse({...source,event_date_jst:day,records:clean});
 const records=data.records,groups=Data.modelGroups(records).sort((a,b)=>a.key.localeCompare(b.key));
 const when=Date.parse(createdAt),cohort=[];
 for(const row of records)for(const p of Data.candidates(row)){
  const facts=Data.effectivePredictionFacts(row,p);
  if(!validTime(p.persisted_at)||Date.parse(p.persisted_at)>when||!validTime(p.as_of)||Date.parse(p.as_of)>when||
    facts.generated_at!=null&&Date.parse(facts.generated_at)>when||facts.generation_completed_no_later_than!=null&&Date.parse(facts.generation_completed_no_later_than)>when)
   throw new Error('BUDGET_PLAN_FORECAST_NOT_AVAILABLE');
  cohort.push(forecastReference(row,p));
 }
 cohort.sort((a,b)=>canonical(a).localeCompare(canonical(b)));
 if(!cohort.length||!groups.length)throw new Error('BUDGET_PLAN_NO_FORECASTS');
 const policyFiles=Object.fromEntries(['web/product-data.js','web/saved-performance.js','scripts/boat_budget_plan.cjs'].map(name=>[name,sha(fs.readFileSync(path.join(root,name)))]));
 const plans=[],scenarioCounts=[],includedCutoffs=[];
 for(const [index,group] of groups.entries())for(const dailyBudget of [...new Set(dailyBudgets)].sort((a,b)=>a-b))for(const raceBudget of [...new Set(raceBudgets)].sort((a,b)=>a-b)){
  const sim=Performance.simulate(records,group,dailyBudget,{raceBudget}),raceMap=new Map(records.map(r=>[r.race_id,r]));
  const races=sim.rows.map(entry=>{
   const row=raceMap.get(entry.race_id),p=Performance.pick(row,group),cutoff=p?.cutoff_at??row.cutoff_at??null;
   if(entry.stake>0){if(!validTime(cutoff)||when>=Date.parse(cutoff))throw new Error('BUDGET_PLAN_FIRST_CUTOFF_REACHED');includedCutoffs.push(cutoff);}
   return {race_id:entry.race_id,forecast:p?forecastReference(row,p):null,cutoff_at:cutoff,
    stake_yen:entry.stake,reason:entry.reason,held_yen:entry.allocation?.held??0,
    tickets:(entry.allocation?.tickets??[]).map(t=>({combination:t.combination,amount_yen:t.amount,families:t.families,stable_families:t.stableFamilies}))};
  });
  const id=plans.length+1;
  plans.push({id,model_group_index:index+1,model_group:group.key,daily_budget:dailyBudget,race_budget:raceBudget,
   bought:sim.bought,planned_stake_yen:sim.spent,reserved_yen:sim.reserved,held_yen:sim.held,unspent_yen:sim.unspent,
   settlement_status:'UNSETTLED_PLAN',races});
  scenarioCounts.push({id,model_group_index:index+1,daily_budget:dailyBudget,race_budget:raceBudget,bought:sim.bought,
   planned_stake_yen:sim.spent,reserved_yen:sim.reserved,held_yen:sim.held,unspent_yen:sim.unspent});
 }
 if(!includedCutoffs.length)throw new Error('BUDGET_PLAN_NO_ELIGIBLE_ALLOCATIONS');
 const cohortSha=sha(canonical(cohort));
 const privateBundle={schema:'RACE_AI_PRE_OUTCOME_BUDGET_PLAN_V1',day,created_at:createdAt,policy_commit:policyCommit,
  policy_files_sha256:policyFiles,cohort_sha256:cohortSha,cohort,plans,
  results_used:false,actual_purchases:false,alternative_scenarios:true,
  independent_pre_cutoff_receipt_verified:false};
 const safeSummary={schema:'RACE_AI_PRE_OUTCOME_BUDGET_PLAN_COUNTS_V1',day,created_at:createdAt,policy_commit:policyCommit,
  policy_files_sha256:policyFiles,cohort_races:records.length,cohort_forecasts:cohort.length,model_groups:groups.length,scenarios:plans.length,
  cohort_sha256:cohortSha,plan_sha256:sha(canonical(privateBundle)),
  first_included_cutoff_at:includedCutoffs.sort((a,b)=>Date.parse(a)-Date.parse(b))[0],
  scenario_counts:scenarioCounts,results_used:false,actual_purchases:false,alternative_scenarios:true,
  independent_pre_cutoff_receipt_verified:false};
 return {privateBundle,safeSummary};
}
function savePrivate(output,bundle){
 const parent=fs.realpathSync(path.dirname(path.resolve(output))),target=path.join(parent,path.basename(output));
 for(let current=parent;;current=path.dirname(current)){
  if(fs.existsSync(path.join(current,'.git')))throw new Error('BUDGET_PLAN_OUTPUT_IN_GIT');
  if(current===path.dirname(current))break;
 }
 const body=canonical(bundle);
 if(fs.existsSync(target)){
  if(!fs.lstatSync(target).isFile()||fs.lstatSync(target).isSymbolicLink()||fs.readFileSync(target,'utf8')!==body)throw new Error('BUDGET_PLAN_OUTPUT_EXISTS');
  fs.chmodSync(target,0o600);return;
 }
 const temporary=path.join(parent,'.budget-plan-'+crypto.randomUUID());
 try{fs.writeFileSync(temporary,body,{mode:0o600,flag:'wx'});fs.renameSync(temporary,target);fs.chmodSync(target,0o600);}
 finally{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}
}
if(require.main===module){
 try{
  const args=process.argv.slice(2),values={};
  for(let i=0;i<args.length;i+=2){if(!['--input','--output','--day','--created-at','--policy-commit'].includes(args[i])||!args[i+1]||Object.hasOwn(values,args[i]))throw new Error('ARGUMENTS');values[args[i]]=args[i+1];}
  if(Object.keys(values).length!==5)throw new Error('ARGUMENTS');
  const stat=fs.statSync(values['--input']);if(!stat.isFile()||stat.size>64*1024*1024)throw new Error('INPUT');
  const {privateBundle,safeSummary}=freezePlan(fs.readFileSync(values['--input'],'utf8'),{day:values['--day'],createdAt:values['--created-at'],policyCommit:values['--policy-commit']});
  savePrivate(values['--output'],privateBundle);process.stdout.write(JSON.stringify(safeSummary)+'\n');
 }catch{process.stderr.write('BOAT_BUDGET_PLAN_REJECTED\n');process.exitCode=1;}
}
module.exports=Object.freeze({freezePlan});
