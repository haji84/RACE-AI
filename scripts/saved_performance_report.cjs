#!/usr/bin/env node
'use strict';
/* No fetch, inference, selection rewrite, key handling or private row output. */
const fs=require('node:fs'),crypto=require('node:crypto');
const Data=require('../web/product-data.js'),Performance=require('../web/saved-performance.js');
const publicModels=new Set(require('../web/existing-model-catalog.js').models.map(m=>m.model_id));
const variants=new Set(['HISTORY_BASELINE','HISTORY_ADDED','LEARNED_SHADOW','LEARNED_VIDEO_EXPERIMENTAL']);
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const financialFields=['budgetPerDay','raceBudget','budgetTotal','spent','reserved','held','unspent','payout','refund','settledStake','settledCount','pendingStake','bought','skippedBudget','balance','settledNet','net','roi'];
const financial=simulation=>Object.fromEntries(financialFields.map(k=>[k,simulation[k]]));
const sameInstant=(a,b)=>Number.isFinite(Date.parse(a))&&Date.parse(a)===Date.parse(b);
function wilson(hits,n){
 if(!n)return null;const z=1.959963984540054,p=hits/n,den=1+z*z/n,mid=(p+z*z/(2*n))/den,width=z*Math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den;
 return [Math.max(0,mid-width),Math.min(1,mid+width)];
}
function discordanceProbability(a,b){
 const n=a+b;if(!n)return 1;let logTerm=-n*Math.LN2,logSum=logTerm;
 for(let k=0;k<Math.min(a,b);k++){logTerm+=Math.log(n-k)-Math.log(k+1);const high=Math.max(logSum,logTerm);logSum=high+Math.log(Math.exp(logSum-high)+Math.exp(logTerm-high));}
 return Math.min(1,2*Math.exp(logSum));
}
function conditions(row,baseline,challenger,axis){
 if(baseline.stage!==challenger.stage||baseline.model_id!==challenger.model_id||
    !sameInstant(baseline.as_of,challenger.as_of)||!sameInstant(baseline.cutoff_at||row.cutoff_at,challenger.cutoff_at||row.cutoff_at))return false;
 const a=Data.effectivePredictionFacts(row,baseline),b=Data.effectivePredictionFacts(row,challenger);
 if(axis==='HISTORY_INPUT_ADDITION')return !!baseline.pair_sha256&&baseline.pair_sha256===challenger.pair_sha256&&
    !!baseline.physical_receipt_sha256&&baseline.physical_receipt_sha256===challenger.physical_receipt_sha256&&
    baseline.original_json_sha256===challenger.original_json_sha256&&sameInstant(baseline.persisted_at,challenger.persisted_at)&&a.model_version===b.model_version;
 return !!challenger.baseline_model_sha256&&challenger.baseline_model_sha256===baseline.prediction_sha256&&
    !!a.input_sha256&&a.input_sha256===b.input_sha256&&!!challenger.training_sha256&&
    (baseline.source_code_commit??null)===(challenger.source_code_commit??null);
}
function hasRefund(result){return !!(result?.refund_boats?.length||result?.refunds?.length||result?.refund_combinations?.length||result?.refund_yen>0);}
function pairedComparison(records,baselineGroup,challengerGroup,axis,options,ids){
 const excluded={missing_or_ambiguous:0,condition_mismatch:0,plan_ineligible:0,pending:0,void:0,refund:0,review:0,duplicate_pair:0};
 let both_hit=0,baseline_only=0,challenger_only=0,both_miss=0;const cohort=[],seenPairs=new Set();
 for(const row of records){
  if(row.scope!==baselineGroup.scope||row.sport!==baselineGroup.sport)continue;
  const a=Performance.pick(row,baselineGroup),b=Performance.pick(row,challengerGroup);
  if(!a||!b){excluded.missing_or_ambiguous++;continue;}
  if(!conditions(row,a,b,axis)){excluded.condition_mismatch++;continue;}
  if(Performance.planReason(row,a)||Performance.planReason(row,b)){excluded.plan_ineligible++;continue;}
  if(row.result?.status==='void'){excluded.void++;continue;}
  if(hasRefund(row.result)){excluded.refund++;continue;}
  const x=Performance.compare(row,a).status,y=Performance.compare(row,b).status;
  if(x==='PENDING'||y==='PENDING'){excluded.pending++;continue;}
  if(!['HIT','MISS'].includes(x)||!['HIT','MISS'].includes(y)){excluded.review++;continue;}
  const receipt=axis==='HISTORY_INPUT_ADDITION'?a.pair_sha256:JSON.stringify([a.artifact_id,a.prediction_sha256,b.prediction_sha256]);
  if(seenPairs.has(receipt)){excluded.duplicate_pair++;continue;}seenPairs.add(receipt);
  if(x==='HIT'&&y==='HIT')both_hit++;else if(x==='HIT')baseline_only++;else if(y==='HIT')challenger_only++;else both_miss++;
  cohort.push(row);
 }
 const n=cohort.length,baseline_hits=both_hit+baseline_only,challenger_hits=both_hit+challenger_only;
 const simulations=[];
 for(const dailyBudget of options.dailyBudgets)for(const raceBudget of options.raceBudgets){
  const a=Performance.simulate(cohort,baselineGroup,dailyBudget,{raceBudget}),b=Performance.simulate(cohort,challengerGroup,dailyBudget,{raceBudget});
  const selected=s=>s.rows.filter(r=>r.stake).map(r=>r.race_id);
  simulations.push({daily_budget:dailyBudget,race_budget:raceBudget,identical_selected_races:JSON.stringify(selected(a))===JSON.stringify(selected(b)),baseline:financial(a),challenger:financial(b)});
 }
 return {baseline_group:ids.get(baselineGroup),challenger_group:ids.get(challengerGroup),stage:baselineGroup.stage,
  axis,paired_races:n,both_hit,baseline_only,challenger_only,both_miss,baseline_hits,challenger_hits,
  baseline_hit_rate:n?baseline_hits/n:null,challenger_hit_rate:n?challenger_hits/n:null,
  hit_rate_difference:n?(challenger_hits-baseline_hits)/n:null,
  exact_discordance_p_value:n?discordanceProbability(baseline_only,challenger_only):null,
  uncertainty:{method:'EXACT_TWO_SIDED_DISCORDANCE_BINOMIAL_AND_WILSON_95',discordant_pairs:baseline_only+challenger_only,
   baseline_hit_rate_95:wilson(baseline_hits,n),challenger_hit_rate_95:wilson(challenger_hits,n),
   exploratory_multiple_comparisons:true},excluded,simulations,
  evidence_scope:'DESCRIPTIVE_SAVED_ORIGINAL_COMPARISON',independent_receipts_verified:false,
  accuracy_improvement_proven:false,prospective_allocation_verified:false};
}
function report(view,options={}){
 const config={dailyBudgets:options.dailyBudgets??[10000],raceBudgets:options.raceBudgets??[800,1000]};
 if(!Array.isArray(config.dailyBudgets)||!config.dailyBudgets.length||config.dailyBudgets.length>10||config.dailyBudgets.some(n=>!Number.isSafeInteger(n)||n<100||n>10000000||n%100)||
    !Array.isArray(config.raceBudgets)||!config.raceBudgets.length||config.raceBudgets.length>2||config.raceBudgets.some(n=>![800,1000].includes(n)))throw new Error('SAVED_REPORT_OPTIONS_INVALID');
 const data=Data.parse(view),records=data.records,groups=Data.modelGroups(records),ids=new Map(groups.map((g,i)=>[g,i+1]));
 const statusCounts=rows=>Object.fromEntries(['final','void','pending','unsupported','missing'].map(status=>[status,rows.filter(r=>(r.result?.status??'missing')===status).length]));
 const countForecasts=rows=>rows.reduce((n,r)=>n+Data.candidates(r).length,0);
 const output={schema:'RACE_AI_SAVED_PERFORMANCE_AGGREGATES_V1',coverage:{races:records.length,forecasts:countForecasts(records),
  result_states:statusCounts(records),days:[...new Set(records.map(r=>r.event_date_jst))].sort().map(day=>{const selected=records.filter(r=>r.event_date_jst===day);return {day,races:selected.length,forecasts:countForecasts(selected),result_states:statusCounts(selected)};})},
  groups:groups.map(g=>({id:ids.get(g),model_id:publicModels.has(g.model_id)?g.model_id:'UNLISTED_MODEL',scope:g.scope,sport:g.sport,stage:g.stage,
   variant:g.variant==null?null:variants.has(g.variant)?g.variant:'OTHER_SAVED_VARIANT',
   saved_version_ref:g.model_version==null?null:sha(g.model_version),source_code_commit:g.code_identity??null,
   issued:g.issued,ambiguous_originals:g.ambiguous_originals,observed:Performance.summarize(records,g),
   simulations:config.dailyBudgets.flatMap(dailyBudget=>config.raceBudgets.map(raceBudget=>{
    const s=Performance.simulate(records,g,dailyBudget,{raceBudget});return {...financial(s),comparison:s.comparison,boughtComparison:s.boughtComparison,hypothetical:true};}))})),
  paired_comparisons:[],accuracy_improvement_proven:false,prospective_allocation_verified:false,
  actual_purchases:false,models_are_alternative_scenarios:true,hypothetical_budget_returns:true,
  conclusion:'DESCRIPTIVE_COMPARISON_ONLY_PROSPECTIVE_IMPROVEMENT_NOT_DEMONSTRATED'};
 for(const challenger of groups){
  const axis=challenger.variant==='HISTORY_ADDED'?'HISTORY_INPUT_ADDITION':challenger.variant==='LEARNED_SHADOW'?'LEARNED_WEIGHT_VERSION':null;
  if(!axis)continue;
  const expected=axis==='HISTORY_INPUT_ADDITION'?'HISTORY_BASELINE':null;
  const baselines=groups.filter(g=>g.scope===challenger.scope&&g.sport===challenger.sport&&g.stage===challenger.stage&&g.model_id===challenger.model_id&&g.variant===expected&&
   (g.code_identity??null)===(challenger.code_identity??null)&&(axis!=='HISTORY_INPUT_ADDITION'||g.model_version===challenger.model_version));
  for(const baseline of baselines)output.paired_comparisons.push(pairedComparison(records,baseline,challenger,axis,config,ids));
 }
 return output;
}
if(require.main===module){
 try{
  const args=process.argv.slice(2);if(args.length!==2||args[0]!=='--input')throw new Error('ARGUMENTS');
  const stat=fs.statSync(args[1]);if(!stat.isFile()||stat.size>64*1024*1024)throw new Error('INPUT');
  process.stdout.write(JSON.stringify(report(fs.readFileSync(args[1],'utf8')))+'\n');
 }catch{process.stderr.write('SAVED_PERFORMANCE_REPORT_REJECTED\n');process.exitCode=1;}
}
module.exports=Object.freeze({report});
