"use strict";
/* BOAT grade transition and recent-return research. No model bonus, no GET.
 * Official term grade is NOT a continuous ability measure. A gap in collected
 * starts is NOT evidence of illness, suspension, maternity or reason for drop.
 * Input metadata claims require separate owner source/authentication readback.
 */
const SCHEMA="RACE_AI_BOAT_GRADE_TRANSITION_RESEARCH_V1";
const CLASS=["B2","B1","A2","A1"];
const SHA=/^[a-f0-9]{64}$/;
const RACE=/^(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$/;
const TERM=/^(20\d{2})-([12])$/;
const STATUS=new Set(["OFFICIALLY_CONFIRMED","ANNOUNCED_PENDING","HISTORIC_OFFICIAL"]);
function assert(ok,reason){if(!ok)throw Error(reason);}
function aware(s){
 assert(typeof s==="string"&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(s),
  "GRADE_AWARE_TIMESTAMP_REQUIRED");
 const t=Date.parse(s);assert(Number.isFinite(t),"GRADE_TIMESTAMP_INVALID");return t;
}
function jstDate(ms){return new Date(ms+9*3600*1000).toISOString().slice(0,10);}
function termWindow(term){
 const m=TERM.exec(term);
 assert(m!==null,"GRADE_TERM_INVALID");
 const year=Number(m[1]),half=Number(m[2]);
 const start=half===1?year+"-01-01":year+"-07-01";
 const end=half===1?year+"-06-30":year+"-12-31";
 return {term,start,end,startMs:Date.parse(start+"T00:00:00+09:00"),
  endMs:Date.parse(end+"T23:59:59.999+09:00")};
}
function currentTerm(now){
 const day=jstDate(now),year=Number(day.slice(0,4)),month=Number(day.slice(5,7));
 return year+"-"+(month<=6?"1":"2");
}
function nextTerm(term){
 const m=TERM.exec(term);
 assert(m,"GRADE_TERM_INVALID");
 return Number(m[2])===1?m[1]+"-2":String(Number(m[1])+1)+"-1";
}
function ranks(cl){return CLASS.indexOf(cl);}
function validGrade(g){return CLASS.includes(g);}
function validateTerm(r,now){
 assert(r&&typeof r==="object"&&!Array.isArray(r),"GRADE_TERM_ROW_INVALID");
 const {racer_id,term,recorded_class,status,captured_at,published_at,
  confirmation_at,source_sha256}=r;
 const previous=r.previous_classes??null;
 assert(previous===null||(Array.isArray(previous)&&previous.length===3&&
  previous.every(x=>x===""||validGrade(x))),"GRADE_PREVIOUS_CLASS_VALUES_INVALID");
 assert(/^\d{4}$/.test(racer_id)&&validGrade(recorded_class)&&STATUS.has(status)
  &&SHA.test(source_sha256),"GRADE_TERM_ROW_INCOMPLETE");
 const window=termWindow(term);
 const captured=aware(captured_at),published=aware(published_at);
 assert(published<=captured&&captured<=now,"GRADE_TERM_POST_ASOF");
 if(status==="OFFICIALLY_CONFIRMED"){
  assert(confirmation_at!==null&&aware(confirmation_at)<=captured&&
   aware(confirmation_at)>=published&&aware(confirmation_at)<=now,
   "GRADE_OFFICIAL_CONFIRMATION_REQUIRED");
 }else assert(confirmation_at===null,"GRADE_UNCONFIRMED_MUST_HAVE_NO_CONFIRMATION");
 return {...r,term_window:window};
}
function readStarts(records,now,people){
 assert(Array.isArray(records)&&records.length<=250000,"GRADE_HISTORY_BOUND_INVALID");
 const seen=new Set(),map=new Map([...people].map(x=>[x,[]]));
 for(const row of records){
  assert(row&&typeof row==="object"&&!Array.isArray(row),"GRADE_START_ROW_INVALID");
  const match=RACE.exec(row.race_id);
  assert(match&&/^\d{4}$/.test(row.racer_id)&&people.has(row.racer_id)&&
   typeof row.started==="boolean"&&SHA.test(row.source_sha256),
   "GRADE_START_ID_SOURCE_INVALID");
  const key=row.racer_id+"|"+row.race_id;
  assert(!seen.has(key),"GRADE_START_DUPLICATE");
  seen.add(key);
  const race=aware(row.raced_at),result=aware(row.result_captured_at);
  assert(race<result&&result<now&&
   jstDate(race).replace(/-/g,"")===match[1],
   "GRADE_START_FUTURE_OR_RACE_DAY_INVALID");
  assert(row.finish===null||Number.isInteger(row.finish)&&
   row.finish>=1&&row.finish<=6,"GRADE_FINISH_INVALID");
  assert(row.started||row.finish===null,"GRADE_ABSENT_CANNOT_HAVE_FINISH");
  if(row.started)map.get(row.racer_id).push({...row,_race:race});
 }
 for(const rows of map.values())rows.sort((a,b)=>a._race-b._race||a.race_id.localeCompare(b.race_id));
 return map;
}
function recentForm(records){
 const rows=records.slice(-10).filter(r=>r.finish!==null);
 return {observed_last_10_starts:Math.min(10,records.length),
  numeric_finish_samples:rows.length,
  wins:rows.filter(r=>r.finish===1).length,
  top3:rows.filter(r=>r.finish<=3).length,
  win_rate:rows.length?rows.filter(r=>r.finish===1).length/rows.length:null,
  top3_rate:rows.length?rows.filter(r=>r.finish<=3).length/rows.length:null,
  denominator:"verified numeric finishes in last 10 observed starts"};
}
function observedGap(starts,asof,{threshold_days,lookback_days,max_post_gap_starts}){
 if(starts.length<2)return {status:"NO_OBSERVED_CONSECUTIVE_START_GAP",
  largest_gap_days:null,return_candidate:null};
 let largest=0,last=null;
 for(let i=1;i<starts.length;i++){
  const prev=jstDate(starts[i-1]._race),curr=jstDate(starts[i]._race);
  const diff=Math.round((Date.parse(curr+"T00:00:00Z")-
                         Date.parse(prev+"T00:00:00Z"))/86400000);
  if(diff>largest)largest=diff;
  if(diff>=threshold_days)last={start_index:i,from:prev,return_date:curr,gap_days:diff};
 }
 if(!last)return {status:"NO_LONG_INTERVAL_IN_RETAINED_STARTS",
  largest_gap_days:largest,return_candidate:null};
 const after=starts.slice(last.start_index),returnAt=Date.parse(last.return_date+"T00:00:00Z");
 const daysSince=Math.round((Date.parse(jstDate(asof)+"T00:00:00Z")-returnAt)/86400000);
 const earlyReturn=daysSince>=0&&daysSince<=lookback_days&&
  after.length<=max_post_gap_starts;
 return {status:earlyReturn?"RECENT_RETURN_AFTER_OBSERVED_START_GAP":
  "HISTORICAL_LONG_INTERVAL_IN_RETAINED_STARTS",
  largest_gap_days:largest,
  return_candidate:{previous_start_date:last.from,first_subsequent_start_date:last.return_date,
   gap_days:last.gap_days,starts_since_interval:after.length,
   days_since_return:daysSince,early_post_gap_sample:recentForm(after),
   independently_verified_complete_coverage:false,
   absence_reason:"UNKNOWN",
   hiatus_causally_explains_grade:false}};
}
function summarize(input){
 assert(input&&input.schema===SCHEMA&&typeof input.race_id==="string"&&
  RACE.test(input.race_id),"GRADE_SCOPE_REQUIRED");
 const now=aware(input.as_of),day=jstDate(now);
 assert(day.replace(/-/g,"")===input.race_id.slice(0,8),
  "GRADE_EVENT_DAY_MISMATCH");
 assert(Array.isArray(input.roster)&&input.roster.length===6&&
  Array.isArray(input.term_records),"GRADE_SIX_RACER_ROSTER_REQUIRED");
 const ids=new Set(),boats=new Set();
 for(const r of input.roster){
  assert(r&&Number.isInteger(r.boat)&&r.boat>=1&&r.boat<=6&&
   /^\d{4}$/.test(r.racer_id)&&validGrade(r.program_class)&&
   !ids.has(r.racer_id)&&!boats.has(r.boat),"GRADE_ROSTER_INVALID");
  ids.add(r.racer_id);boats.add(r.boat);
 }
 const clock=now,current=currentTerm(now),upcoming=nextTerm(current);
 const terms=new Map([...ids].map(x=>[x,[]]));
 for(const raw of input.term_records){
  const r=validateTerm(raw,now);
  assert(ids.has(r.racer_id),"GRADE_EXTRANEOUS_TERM_RACER");
  const rows=terms.get(r.racer_id);
  assert(!rows.some(x=>x.term===r.term),"GRADE_DUPLICATE_PERIOD_OR_REVISION_HOLD");
  rows.push(r);
 }
 const races=readStarts(input.start_records,now,ids);
 const cfg={threshold_days:input.long_gap_threshold_days??60,
  lookback_days:input.return_lookback_days??120,
  max_post_gap_starts:input.max_early_return_starts??15};
 assert(Number.isInteger(cfg.threshold_days)&&cfg.threshold_days>=30&&
  cfg.threshold_days<=365&&Number.isInteger(cfg.lookback_days)&&
  cfg.lookback_days>=30&&cfg.lookback_days<=365&&
  Number.isInteger(cfg.max_post_gap_starts)&&
  cfg.max_post_gap_starts>=1&&cfg.max_post_gap_starts<=50,
  "GRADE_RESEARCH_GAP_PARAMETERS_INVALID");
 const result=[];
 for(const racer of input.roster){
  const rows=terms.get(racer.racer_id);
  const curr=rows.find(x=>x.term===current)??null;
  const next=rows.find(x=>x.term===upcoming)??null;
  const history=rows.filter(x=>x.term_window.endMs<now&&
   x.term_window.endMs<termWindow(current).startMs);
  history.sort((a,b)=>a.term_window.startMs-b.term_window.startMs);
  const formerA=history.filter(x=>ranks(x.recorded_class)>=2);
  // The source's previous three grade slots have no verified term mapping here.
  // They can establish prior A membership, never its exact effective dates.
  const priorAFromCurrent=curr?.previous_classes?.filter(g=>ranks(g)>=2)??[];
  const pastA=formerA.length>0||priorAFromCurrent.length>0;
  const currentGrade=curr?.recorded_class??null;
  const programConflict=curr!==null&&currentGrade!==racer.program_class;
  const currentConfirmed=curr!==null&&curr.status!=="ANNOUNCED_PENDING";
  const futureA=next!==null&&ranks(next.recorded_class)>=2;
  const futureStatus=next===null?"UNAVAILABLE":
   next.status==="OFFICIALLY_CONFIRMED"?"OFFICIALLY_CONFIRMED":
   next.status==="ANNOUNCED_PENDING"?"ANNOUNCED_SUBJECT_TO_CONFIRMATION":
   "HOLD_UNEXPECTED_HISTORIC_STATUS";
  const grades=rows.map(x=>({term:x.term,applies_from:x.term_window.start,
   applies_through:x.term_window.end,grade:x.recorded_class,
   release_status:x.status,source_sha256:x.source_sha256,
   source_captured_at:x.captured_at,confirmed_at:x.confirmation_at}));
  grades.sort((a,b)=>a.term.localeCompare(b.term));
  const recent=recentForm(races.get(racer.racer_id));
  const gap=observedGap(races.get(racer.racer_id),now,cfg);
  const validCurrent=currentConfirmed&&!programConflict;
  const tags=[];
  if(!validCurrent)tags.push("HOLD_CURRENT_GRADE_UNVERIFIED_OR_CONFLICT");
  if(validCurrent&&currentGrade==="B1"&&futureA){
   tags.push(futureStatus==="OFFICIALLY_CONFIRMED"?
    "B1_TO_A_CLASS_OFFICIAL_FUTURE_GRADE":"B1_TO_A_CLASS_ANNOUNCED_NOT_FINAL");
  }
  if(validCurrent&&(currentGrade==="B1"||currentGrade==="B2")&&pastA){
   tags.push("FORMER_A_CURRENT_B_CLASS");
   tags.push(currentGrade==="B1"?"FORMER_A_CURRENT_B1":"FORMER_A_CURRENT_B2");
  }
  if(validCurrent&&(currentGrade==="B1"||currentGrade==="B2")&&pastA&&
    gap.status==="RECENT_RETURN_AFTER_OBSERVED_START_GAP")
   tags.push("FORMER_A_WITH_RECENT_OBSERVED_RACE_GAP");
  result.push({boat:racer.boat,racer_id:racer.racer_id,
   program_class:racer.program_class,official_current_grade:currentGrade,
   current_grade_status:!curr?"MISSING":programConflict?"CONFLICT_WITH_PROGRAM":
    curr.status==="ANNOUNCED_PENDING"?"HOLD_UNCONFIRMED":"SOURCE_CLAIM_CONFIRMED",
   next_official_announcement_grade:next?.recorded_class??null,
   next_grade_publication_status:futureStatus,
   highest_previous_official_grade:
    formerA.some(x=>x.recorded_class==="A1")||priorAFromCurrent.includes("A1")?
    "A1":pastA?"A2":null,
   historical_A_terms:formerA.map(x=>x.term),
   current_term_previous_class_indications:priorAFromCurrent,
   current_term_previous_class_term_mapping_proven:false,
   classes_by_application_period:grades,
   observed_recent_form:recent,observed_start_gap:gap,
   research_tags:tags,
   grade_is_not_skill_strength:true,
   gap_is_not_confirmed_reason_for_demoting:true,
   coefficient_or_prior_probability_changed:false});
 }
 return {schema:SCHEMA,race_id:input.race_id,as_of:input.as_of,
  current_application_term:current,next_application_term:upcoming,
  source_claims_require_independent_Actions_readback:true,
  current_period:termWindow(current),next_period:termWindow(upcoming),
  current_future_classes_not_automatically_skill_scores:true,
  production_model_changed:false,all_six:result.sort((a,b)=>a.boat-b.boat)};
}
module.exports={SCHEMA,currentTerm,termWindow,nextTerm,summarize};
