#!/usr/bin/env node
'use strict';
/* Authenticated view in stdin; only aggregate expectations leave stdout. */
const fs=require('node:fs'),crypto=require('node:crypto');
const Data=require('../web/product-data.js'),Performance=require('../web/saved-performance.js');
const {report}=require('./saved_performance_report.cjs');
const retired=new Set(require('../web/existing-model-catalog.js').retired_model_ids);
const schema='RACE_AI_SAVED_SITE_SIMULATION_EXPECTED_V1';
const financialFields=['budgetPerDay','raceBudget','budgetTotal','spent','reserved','held','unspent','payout','refund','settledStake','settledCount','pendingStake','bought','skippedBudget','balance','settledNet','net','roi'];
const comparisonFields=['hits','misses','pending','void','noForecast','review'];
const observedFields=['races','available',...comparisonFields];
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const select=(value,fields)=>Object.fromEntries(fields.map(key=>[key,value[key]]));
function readBounded(fd=0,maximum=64*1024*1024){
  if(!Number.isSafeInteger(maximum)||maximum<1||maximum>64*1024*1024)throw new Error('INPUT_LIMIT');
  const chunks=[];let size=0;
  for(;;){
    const chunk=Buffer.allocUnsafe(Math.min(65536,maximum+1-size)),length=fs.readSync(fd,chunk,0,chunk.length,null);
    if(!length)return Buffer.concat(chunks,size);
    size+=length;if(size>maximum)throw new Error('INPUT_LIMIT');chunks.push(chunk.subarray(0,length));
  }
}
function phase(row,when,today){
  if(['final','settled','void','cancelled'].includes(row.result?.status))return 'closed';
  const valid=value=>typeof value==='string'&&Number.isFinite(Date.parse(value));
  const deadline=valid(row.cutoff_at)?row.cutoff_at:
    [...(row.saved_cutoff_variants||[]),...Data.candidates(row).map(p=>p.cutoff_at)].filter(valid).sort((a,b)=>Date.parse(a)-Date.parse(b))[0];
  return deadline?(Date.parse(deadline)>when?'upcoming':'closed'):row.event_date_jst<today?'closed':'unknown';
}
function buildExpected(input){
  const {view,day,generation,as_of:asOf,native_groups:required}=input||{};
  if(!view||!Array.isArray(view.records)||typeof day!=='string'||!/^\d{4}-\d\d-\d\d$/.test(day)||
     !Number.isFinite(Date.parse(day+'T00:00:00Z'))||new Date(day+'T00:00:00Z').toISOString().slice(0,10)!==day||
     !Number.isSafeInteger(generation)||generation<1||typeof asOf!=='string'||
     !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(asOf)||!Number.isFinite(Date.parse(asOf))||
     !Array.isArray(required)||!required.length||
     required.some(g=>!Array.isArray(g)||g.length!==4||typeof g[0]!=='string'||!g[0]||g.slice(1).some(v=>v!==null&&typeof v!=='string')))
    throw new Error('SAVED_SITE_SIMULATION_INPUT_INVALID');
  const requiredKeys=new Set(required.map(g=>JSON.stringify(g)));
  if(requiredKeys.size!==required.length)throw new Error('SAVED_SITE_SIMULATION_INPUT_INVALID');
  const source={...view,event_date_jst:day,records:view.records.filter(r=>r?.sport==='boat'&&r.event_date_jst===day)};
  if(!source.records.length)throw new Error('SAVED_SITE_SIMULATION_DAY_EMPTY');
  const rows=Data.parse(source).records,groups=Data.modelGroups(rows),rawRows=new Map(source.records.map(r=>[r.race_id,r]));
  const when=Date.parse(asOf),today=new Date(when+9*3600000).toISOString().slice(0,10);
  if(day>today)throw new Error('SAVED_SITE_SIMULATION_INPUT_INVALID');
  const candidates=[];
  for(const [index,group] of groups.entries()){
    const identity=JSON.stringify([group.model_id,group.model_version??null,group.variant??null,group.code_identity??null]);
    if(group.stage!=='P1'||retired.has(group.model_id)||!requiredKeys.has(identity))continue;
    let eligible=0;
    for(const row of rows){
      const p=Performance.pick(row,group);if(!p||Performance.planReason(row,p))continue;
      const raw=Data.candidates(rawRows.get(row.race_id))[Data.candidates(row).indexOf(p)];
      if(raw?.native_dispatch_prediction===true&&raw.external_receipt_verified===true&&raw.eligible_pre_cutoff===true&&
         ['generated_at','as_of','persisted_at'].every(k=>Number.isFinite(Date.parse(raw[k]))&&Date.parse(raw[k])<=when))eligible++;
    }
    if(eligible)candidates.push({group,index,eligible});
  }
  candidates.sort((a,b)=>b.eligible-a.eligible||(a.group.key<b.group.key?-1:a.group.key>b.group.key?1:0));
  const chosen=candidates[0];if(!chosen)throw new Error('SAVED_SITE_SIMULATION_NATIVE_GROUP_REQUIRED');
  const aggregate=report(source,{dailyBudgets:[10000,5000],raceBudgets:[800,1000]}).groups[chosen.index];
  const scenarios=aggregate.simulations.map(s=>({...select(s,financialFields),comparison:select(s.comparison,comparisonFields),boughtComparison:select(s.boughtComparison,comparisonFields)}));
  const capped=[800,1000].every(raceBudget=>scenarios.find(s=>s.budgetPerDay===10000&&s.raceBudget===raceBudget).bought>
    scenarios.find(s=>s.budgetPerDay===5000&&s.raceBudget===raceBudget).bought);
  const lifecycle={as_of:asOf,closed:0,upcoming:0,unknown:0},closed=[];
  for(const row of rows){const value=phase(row,when,today);lifecycle[value]++;if(value==='closed')closed.push(row);}
  return {schema,day,generation,group_sha256:sha(chosen.group.key),eligible_native_races:chosen.eligible,issued_races:chosen.group.issued,
    observed:select(aggregate.observed,observedFields),observed_closed:select(Performance.summarize(closed,chosen.group),observedFields),lifecycle,scenarios,budget_cap_exercised:capped,
    budget_cap_coverage:capped?'EXERCISED':'INSUFFICIENT_ELIGIBLE_RACES'};
}
if(require.main===module){
  try{
    if(process.argv.length!==2)throw new Error('ARGUMENTS');
    const raw=readBounded();
    process.stdout.write(JSON.stringify(buildExpected(JSON.parse(raw.toString('utf8'))))+'\n');
  }catch{process.stdout.write(JSON.stringify({status:'SAVED_SITE_SIMULATION_CONTEXT_REJECTED'})+'\n');process.exitCode=2;}
}
module.exports=Object.freeze({buildExpected,readBounded,schema,financialFields,comparisonFields,observedFields});
