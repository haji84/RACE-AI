"use strict";
/* Single existing BOAT six-way 120-ticket engine: matched A/B/C research.
 * A = stored P1 120 distribution (unchanged).
 * B = fit tactical covariates from earlier races.
 * C = B + observed grade-history flags fit from SAME earlier race cohort.
 * Outputs are research metrics; source hashes and receipts are claims until
 * independently authenticated inside the existing owner Actions boundary.
 * No remote GET, production model promotion, actual purchase or scheduler.
 */
const overlay=require("./boat_six_way_probability_overlay.cjs");
const SCHEMA="RACE_AI_BOAT_SIXWAY_MATCHED_ABLATION_V1";
const GRADE_SCHEMA="RACE_AI_BOAT_GRADE_TRANSITION_RESEARCH_V1";
const NAMES=["first_former_A_current_B","second_former_A_current_B",
 "third_former_A_current_B","first_next_A_pending","first_next_A_confirmed",
 "second_next_A_pending","first_observed_long_gap","second_observed_long_gap",
 "first_former_A_x_recent_gap","first_vs_second_former_A_interaction"];
const TICKETS=overlay.TICKETS;
function need(cond,msg){if(!cond)throw Error(msg);}
function time(s){
 need(typeof s==="string"&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(s),"MATCHED_TIME_REQUIRED");
 const t=Date.parse(s);need(Number.isFinite(t),"MATCHED_TIME_INVALID");return t;
}
function numeric(v){return typeof v==="number"&&Number.isFinite(v);}
function all120(prepared,beta){
 need(beta.length===overlay.FACTORS.length&&beta.every(numeric),"MATCHED_TACTICAL_WEIGHTS");
 const log=prepared.prior.map((v,i)=>Math.log(v)+prepared.vectors[i].reduce((a,v,j)=>a+v*beta[j],0));
 return soft(log);
}
function soft(log){
 const peak=Math.max(...log),a=log.map(v=>Math.exp(v-peak));
 const sum=a.reduce((s,v)=>s+v,0);need(sum>0&&Number.isFinite(sum),"MATCHED_SOFTMAX_FAILED");
 return a.map(v=>v/sum);
}
function grades(record,prepared){
 const data=record.grade_transition;
 need(data&&data.schema===GRADE_SCHEMA&&data.race_id===prepared.race&&
  time(data.as_of)===prepared.asof&&data.production_model_changed===false,
  "MATCHED_GRADE_ASOF_IDENTITY_HOLD");
 need(data.source_claims_require_independent_Actions_readback===true,
  "MATCHED_GRADE_PROOF_ORIGIN_HOLD");
 need(Array.isArray(data.all_six)&&data.all_six.length===6,
  "MATCHED_SIX_GRADE_ROWS_HOLD");
 const rows=new Map();
 for(const g of data.all_six){
  need(g&&Number.isInteger(g.boat)&&g.boat>=1&&g.boat<=6&&!rows.has(g.boat)&&
   /^\d{4}$/.test(g.racer_id),"MATCHED_GRADE_BOAT_DUPLICATE");
  const entry=record.context.entry_tilt_cross_features;
  const racers=Object.values(entry).filter(e=>e.frame===g.boat);
  need(racers.length===1&&racers[0].racer_id===g.racer_id,
   "MATCHED_GRADE_ENTRY_BOAT_RACER_MISMATCH");
  need(g.current_grade_status==="SOURCE_CLAIM_CONFIRMED"&&
   ["A1","A2","B1","B2"].includes(g.official_current_grade)&&
   g.program_class===g.official_current_grade,
   "MATCHED_CURRENT_GRADE_HOLD");
  const nextStatus=g.next_grade_publication_status;
  need(["OFFICIALLY_CONFIRMED","ANNOUNCED_SUBJECT_TO_CONFIRMATION","UNAVAILABLE"].includes(nextStatus),
   "MATCHED_NEXT_GRADE_STATUS_HOLD");
  if(nextStatus==="UNAVAILABLE"){
   // Missing next-term source is NOT evidence the competitor will be B.
   need(g.next_official_announcement_grade===null,"MATCHED_UNAVAILABLE_NEXT_GRADE_CONFLICT");
  }else need(["A1","A2","B1","B2"].includes(g.next_official_announcement_grade),
   "MATCHED_PUBLISHED_NEXT_GRADE_REQUIRED");
  if(nextStatus!=="UNAVAILABLE"){
   need(g.classes_by_application_period?.some(r=>
    r.grade===g.next_official_announcement_grade &&
    r.release_status===(nextStatus==="OFFICIALLY_CONFIRMED"?"OFFICIALLY_CONFIRMED":"ANNOUNCED_PENDING") &&
    time(r.source_captured_at)<=prepared.asof &&
    /^\d{4}-\d\d-\d\d$/.test(r.applies_from)),
    "MATCHED_NEXT_GRADE_PUBLISHED_AFTER_FORECAST");
  }
  const previous=g.classes_by_application_period;
  need(Array.isArray(previous)&&previous.every(r=>r&&
   typeof r.source_captured_at==="string"&&time(r.source_captured_at)<=prepared.asof),
   "MATCHED_HISTORICAL_GRADE_AFTER_CUTOFF");
  const former=(g.research_tags||[]).includes("FORMER_A_CURRENT_B_CLASS");
  need(typeof former==="boolean"&&Array.isArray(g.research_tags)&&
   !g.research_tags.some(t=>t.startsWith("HOLD_")),
   "MATCHED_GRADE_RESEARCH_HOLD");
  const recentGap=g.observed_start_gap?.status==="RECENT_RETURN_AFTER_OBSERVED_START_GAP";
  if(recentGap)need(g.observed_start_gap?.return_candidate?.absence_reason==="UNKNOWN"&&
    g.observed_start_gap.return_candidate.independently_verified_complete_coverage===false,
    "MATCHED_GAP_IS_NOT_CONFIRMED_LEAVE");
  rows.set(g.boat,{
    former:Number(former),gap:Number(recentGap),
    futurePending:Number(["A1","A2"].includes(g.next_official_announcement_grade)&&
       nextStatus==="ANNOUNCED_SUBJECT_TO_CONFIRMATION"),
    futureConfirmed:Number(["A1","A2"].includes(g.next_official_announcement_grade)&&
       nextStatus==="OFFICIALLY_CONFIRMED"),
    futureMissing:nextStatus==="UNAVAILABLE"
  });
 }
 need(rows.size===6,"MATCHED_SIX_RACERS_REQUIRED");
 // Compare only when all six have a valid, published next-term snapshot.
 // If any are missing, C holds rather than silently treating 'not found' as B.
 need([...rows.values()].every(r=>!r.futureMissing),"MATCHED_NEXT_GRADE_COVERAGE_HOLD");
 return TICKETS.map(ticket=>{
  const [a,b,c]=ticket.split("-").map(Number);
  const x=rows.get(a),y=rows.get(b),z=rows.get(c);
  return [x.former,y.former,z.former,x.futurePending,x.futureConfirmed,
    y.futurePending,x.gap,y.gap,x.former*x.gap,x.former*y.former];
 });
}
function detail(row){
 need(row&&row.input&&typeof row.result_ticket==="string"&&
  TICKETS.includes(row.result_ticket)&&
  /^[a-f0-9]{64}$/.test(row.result_source_sha256),"MATCHED_RESULT_RECEIPT_HOLD");
 const p=overlay.prepare(row.input),captured=time(row.result_captured_at);
 need(captured>p.cutoff&&p.asof<p.cutoff,"MATCHED_RESULT_TIME_LEAKAGE");
 need(typeof row.original_sha256==="string"&&/^[a-f0-9]{64}$/.test(row.original_sha256),
  "MATCHED_FROZEN_ORIGINAL_SHA_REQUIRED");
 const originalSaved=time(row.original_saved_at);
 need(p.asof<=originalSaved&&originalSaved<p.cutoff,
  "MATCHED_ORIGINAL_NOT_SAVED_BEFORE_CUTOFF");
 const g=grades(row.input,p);
 const idx=TICKETS.indexOf(row.result_ticket);
 const payout=row.payout_per_100_yen;
 need(payout===null||Number.isInteger(payout)&&payout>=0&&payout<100000000,
  "MATCHED_PAYOUT_CLAIM_INVALID");
 const refunded=row.refund_boats;
 need(Array.isArray(refunded)&&refunded.length<=6&&
  refunded.every(n=>Number.isInteger(n)&&n>=1&&n<=6)&&
  new Set(refunded).size===refunded.length,"MATCHED_REFUND_DISPOSITION_REQUIRED");
 need(row.result_status==="FINAL_SETTLED","MATCHED_FINAL_RESULT_REQUIRED");
 need(!refunded.some(n=>row.result_ticket.split("-").includes(String(n))),
  "MATCHED_WINNER_CAN_NOT_BE_REFUNDED");
 // This is just a CLAIM; formal official settled payout must be authenticated
 // separately to count it as true ROI. Missing payout remains null.
 return {p,g,index:idx,payout,refunded,captured,day:p.race.slice(0,8)};
}
function apply(raw,gradeVectors,weight){
 need(weight.length===NAMES.length,"MATCHED_GRADE_COEFFICIENT_LENGTH");
 return soft(raw.map((prob,i)=>Math.log(prob)+gradeVectors[i].reduce((s,f,j)=>s+f*weight[j],0)));
}
function fitGrade(cases,tacticalWeights,{epochs=50,lr=.45,penalty=1.7}={}){
 need(Number.isInteger(epochs)&&epochs>=1&&epochs<=160&&
  numeric(lr)&&lr>=.005&&lr<=1&&numeric(penalty)&&penalty>=.1&&penalty<=30,
  "MATCHED_FIT_SETTINGS_INVALID");
 const casesWithB=cases.map(x=>({...x,priorB:all120(x.p,tacticalWeights)}));
 let beta=NAMES.map(()=>0);
 for(let epoch=0;epoch<epochs;epoch++){
  let gradient=beta.map(w=>penalty*w/casesWithB.length);
  for(const row of casesWithB){
   const probs=apply(row.priorB,row.g,beta);
   for(let j=0;j<beta.length;j++){
    let expect=0;for(let i=0;i<120;i++)expect+=probs[i]*row.g[i][j];
    gradient[j]+=(expect-row.g[row.index][j])/casesWithB.length;
   }
  }
  const learningRate=lr/Math.sqrt(1+epoch/8);
  beta=beta.map((w,j)=>Math.max(-5,Math.min(5,w-learningRate*gradient[j])));
 }
 return beta;
}
function top8(probs){
 return [...probs.keys()].sort((a,b)=>probs[b]-probs[a]||a-b).slice(0,8);
}
function metrics(cases,tacticalWeight,gradeWeight){
 const groups=[{name:"A_FROZEN_BASELINE",logs:0,brier:0,hits:0,highEvents:0,
  highHits:0,roiStake:0,roiBack:0,completePayouts:true},
  {name:"B_SIX_COURSE_TACTICS",logs:0,brier:0,hits:0,highEvents:0,
   highHits:0,roiStake:0,roiBack:0,completePayouts:true},
  {name:"C_TACTICS_PLUS_GRADE",logs:0,brier:0,hits:0,highEvents:0,
   highHits:0,roiStake:0,roiBack:0,completePayouts:true}];
 for(const row of cases){
  const original=row.p.prior,tactical=all120(row.p,tacticalWeight);
  const combined=apply(tactical,row.g,gradeWeight),vals=[original,tactical,combined];
  for(let j=0;j<3;j++){
   const grp=groups[j],pr=vals[j],ix=row.index;
   grp.logs-=Math.log(pr[ix]);
   grp.brier+=pr.reduce((sum,p,i)=>sum+(p-(i===ix?1:0))**2,0);
   const picks=top8(pr),hit=picks.includes(ix);
   grp.hits+=Number(hit);
   if(row.payout===null){grp.completePayouts=false;continue}
   grp.roiStake+=picks.length*100;
   grp.roiBack+=(hit?row.payout:0)+picks.filter(k=>
    TICKETS[k].split("-").some(n=>row.refunded.includes(Number(n)))).length*100;
   if(row.payout>=10000){grp.highEvents++;grp.highHits+=Number(hit)}
  }
 }
 return groups.map(g=>({
  variant:g.name,independent_races:cases.length,
  mean_log_loss:g.logs/cases.length,mean_brier120:g.brier/cases.length,
  hit_at8_count:g.hits,hit_at8_rate:g.hits/cases.length,
  high_payout_event_count:g.completePayouts?g.highEvents:null,
  high_payout_hit_count:g.completePayouts?g.highHits:null,
  hypothetical_8x100_investment_yen:g.completePayouts?g.roiStake:null,
  hypothetical_return_yen:g.completePayouts?g.roiBack:null,
  hypothetical_net_yen:g.completePayouts?g.roiBack-g.roiStake:null,
  hypothetical_roi:g.completePayouts&&g.roiStake?g.roiBack/g.roiStake:null,
  real_purchase_yen:null,source_proof_independent:false,
  officially_authenticated_result:false
 }));
}
function compare(records,options={}){
 need(Array.isArray(records)&&records.length>=50&&records.length<=2500,
  "MATCHED_RECORDS_INSUFFICIENT");
 const seen=new Set(),cases=[];
 for(const row of records){
  const d=detail(row);
  need(!seen.has(d.p.race),"MATCHED_DUPLICATE_RACE");
  seen.add(d.p.race);cases.push(d);
 }
 cases.sort((a,b)=>a.p.asof-b.p.asof||a.p.race.localeCompare(b.p.race));
 const fraction=options.holdoutFraction??.25;
 need(numeric(fraction)&&fraction>=.1&&fraction<=.4,"MATCHED_HOLDOUT_FRACTION");
 const target=Math.floor(cases.length*(1-fraction));
 let n=target;
 while(n<cases.length&&cases[n].day===cases[n-1].day)n++;
 if(cases.length-n<10){
  n=target;while(n>40&&cases[n].day===cases[n-1].day)n--;
 }
 need(n>=40&&cases.length-n>=10,"MATCHED_HOLDOUT_NOT_ENOUGH_DATES");
 const train=cases.slice(0,n),test=cases.slice(n);
 const freeze=Math.max(...train.map(r=>r.captured));
 need(freeze<Math.min(...test.map(r=>r.p.asof)),
  "MATCHED_SAME_DATE_OR_RESULT_LEAKAGE");
 // This is the SAME base overlay feature set, with a frozen tactical fit.
 const tactical=overlay.fitChronological(records.map(r=>({
  input:r.input,result_ticket:r.result_ticket,
  result_captured_at:r.result_captured_at,
  result_source_sha256:r.result_source_sha256
 })),{...options});
 need(JSON.stringify(tactical.holdout_ids)===JSON.stringify(test.map(r=>r.p.race)),
  "MATCHED_TACTICAL_HOLDOUT_NOT_SAME");
 const degree=tactical.frozen.coefficients;
 const grade=fitGrade(train,degree,options);
 return {schema:SCHEMA,
  status:"RESEARCH_COMPARISON_REQUIRES_AUTHENTICATED_REAL_PROOF",
  frozen_training_through:new Date(freeze).toISOString(),
  train_races:train.length,holdout_races:test.length,
  holdout_race_count:test.length,
  ablations:metrics(test,degree,grade),
  coefficients_trained_locally:true,
  grade_feature_names:[...NAMES],
  grade_source_current_full_coverage_claim:true,
  model_family_added:false,source_get_count:0,
  old_predictions_overwritten:false,model_promoted:false,
  private_actual_purchases:null,all_claims_require_independent_readback:true,
  prospective_future_comparison_complete:false};
}
module.exports={SCHEMA,GRADE_SCHEMA,NAMES,detail,compare};
