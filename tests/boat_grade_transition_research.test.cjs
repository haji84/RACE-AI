"use strict";
/* Synthetic-only unit tests of grade alerts, NEVER actual racer names or history. */
const grade=require("../race_ai/boat_grade_transition_research.cjs");
function check(ok,reason){if(!ok)throw Error(reason);}
function reject(fn,part){let message="";try{fn()}catch(e){message=String(e.message)}
 check(message.includes(part),"expected HOLD "+part+" / "+message);}
const ASOF="2026-11-09T07:00:00+09:00";
function term(racer,period,value,status="HISTORIC_OFFICIAL"){
 const next=period==="2027-1";
 return {racer_id:racer,term:period,recorded_class:value,status,
  captured_at:next?"2026-11-09T05:00:00+09:00":"2026-07-01T02:00:00+09:00",
  published_at:next?"2026-11-01T10:00:00+09:00":"2026-06-01T10:00:00+09:00",
  confirmation_at:status==="OFFICIALLY_CONFIRMED"?"2026-11-08T16:00:00+09:00":null,
  source_sha256:"a".repeat(64)};
}
function start(racer,day,finish=1,started=true) {
 return {racer_id:racer,race_id:day.replace(/-/g,"")+"-04-01",
  raced_at:day+"T12:15:00+09:00",result_captured_at:day+"T12:35:00+09:00",
  finish,started,source_sha256:"b".repeat(64)};
}
function fixture(){
 const roster=Array.from({length:6},(_,i)=>({boat:i+1,racer_id:String(4101+i),
  program_class:i===3?"A1":i===4?"B2":"B1"}));
 const records=roster.map(r=>term(r.racer_id,"2026-2",r.program_class));
 records.push(term("4101","2027-1","A2","ANNOUNCED_PENDING"));
 records.push(term("4102","2027-1","A1","OFFICIALLY_CONFIRMED"));
 records.push(term("4102","2026-1","A1"));
 records.push(term("4103","2026-1","A2"));
 records.push(term("4104","2027-1","B1","ANNOUNCED_PENDING"));
 const starts=[start("4102","2026-05-10"),start("4102","2026-08-25"),
  start("4102","2026-09-03",3),start("4102","2026-10-28",2),
  start("4103","2026-01-01",1),start("4103","2026-06-01",2),
  start("4101","2026-11-05",null,true)];
 return {schema:grade.SCHEMA,race_id:"20261109-04-01",as_of:ASOF,
  roster,term_records:records,start_records:starts};
}
function tests(){
 check(grade.termWindow("2026-2").start==="2026-07-01","current application");
 check(grade.termWindow("2027-1").start==="2027-01-01","next application");
 check(grade.currentTerm(Date.parse(ASOF))==="2026-2"&&
  grade.nextTerm("2026-2")==="2027-1","correct half-year boundaries");
 const source=fixture(),before=JSON.stringify(source),out=grade.summarize(source);
 check(out.all_six.length===6&&JSON.stringify(source)===before,"no input mutation");
 const [a,b,c,d,e,f]=out.all_six;
 check(a.research_tags.includes("B1_TO_A_CLASS_ANNOUNCED_NOT_FINAL")&&
  a.next_grade_publication_status==="ANNOUNCED_SUBJECT_TO_CONFIRMATION"&&
  !a.research_tags.includes("B1_TO_A_CLASS_OFFICIAL_FUTURE_GRADE"),
  "announced never final");
 check(b.research_tags.includes("B1_TO_A_CLASS_OFFICIAL_FUTURE_GRADE")&&
  b.research_tags.includes("FORMER_A_CURRENT_B1"),"confirmed from published source claim");
 check(b.research_tags.includes("FORMER_A_WITH_RECENT_OBSERVED_RACE_GAP")&&
  b.observed_start_gap.return_candidate.gap_days>=60&&
  b.observed_start_gap.return_candidate.absence_reason==="UNKNOWN"&&
  b.observed_start_gap.return_candidate.independently_verified_complete_coverage===false,
  "gap is not proven medical/personal hiatus");
 check(c.research_tags.includes("FORMER_A_CURRENT_B1")&&
  !c.research_tags.includes("FORMER_A_WITH_RECENT_OBSERVED_RACE_GAP"),
  "old A classification independent of recent comeback");
 check(d.program_class==="A1"&&!d.research_tags.some(x=>x.startsWith("B1_TO_A")),
  "A1 is not B1 upgrade");
 check(e.program_class==="B2"&&!e.research_tags.some(x=>x.startsWith("B1_TO_A")),
  "B2 is not automatically treated as B1");
 check(f.observed_recent_form.win_rate===null&&
  f.highest_previous_official_grade===null,"no history must be null");
 check(a.observed_recent_form.numeric_finish_samples===0&&
  a.observed_recent_form.win_rate===null,"abnormal numeric finishes excluded");
 check(out.production_model_changed===false&&
  out.source_claims_require_independent_Actions_readback===true,
  "no fake current performance promotion");
 const b2=fixture();
 b2.term_records.find(x=>x.racer_id==="4105"&&x.term==="2026-2").previous_classes=["A1","",""];
 const newB2=grade.summarize(b2).all_six[4];
 check(newB2.research_tags.includes("FORMER_A_CURRENT_B2")&&
   newB2.highest_previous_official_grade==="A1"&&
   newB2.current_term_previous_class_term_mapping_proven===false,
   "former A grade recorded within the existing fan term must flag B2");
 const fromPrev=fixture();
 fromPrev.term_records=fromPrev.term_records.filter(x=>!(x.racer_id==="4103"&&x.term==="2026-1"));
 fromPrev.term_records.find(x=>x.racer_id==="4103"&&x.term==="2026-2").previous_classes=["","A2",""];
 const previousOnly=grade.summarize(fromPrev).all_six[2];
 check(previousOnly.research_tags.includes("FORMER_A_CURRENT_B1")&&
   previousOnly.historical_A_terms.length===0,
   "source-reported past A catches omissions of earlier term objects");
 const badPrevious=fixture();
 badPrevious.term_records[0].previous_classes=["A1","A1"];
 reject(()=>grade.summarize(badPrevious),"PREVIOUS_CLASS_VALUES_INVALID");
 const confirmedTooEarly=fixture();
 confirmedTooEarly.term_records.find(x=>x.racer_id==="4102"&&x.term==="2027-1").captured_at="2026-11-01T12:00:00+09:00";
 reject(()=>grade.summarize(confirmedTooEarly),"CONFIRMATION_REQUIRED");
 const wrong=fixture();wrong.term_records.find(x=>x.racer_id==="4101"&&x.term==="2027-1").captured_at=
   "2026-11-10T08:00:00+09:00";
 reject(()=>grade.summarize(wrong),"POST_ASOF");
 const backtest=fixture();backtest.as_of="2026-10-15T07:00:00+09:00";backtest.race_id="20261015-04-01";
 reject(()=>grade.summarize(backtest),"POST_ASOF");
 const mismatch=fixture();mismatch.roster[0].program_class="A1";
 const hold=grade.summarize(mismatch);
 check(hold.all_six[0].research_tags.includes("HOLD_CURRENT_GRADE_UNVERIFIED_OR_CONFLICT")&&
  !hold.all_six[0].research_tags.some(x=>x.startsWith("B1_TO_A")),
  "conflicting grade must not create boost");
 const duplicate=fixture();duplicate.term_records.push({...duplicate.term_records[0]});
 reject(()=>grade.summarize(duplicate),"DUPLICATE_PERIOD");
 const forged=fixture();
 forged.term_records.find(x=>x.racer_id==="4102"&&x.term==="2027-1").confirmation_at=null;
 reject(()=>grade.summarize(forged),"CONFIRMATION_REQUIRED");
 const afterResult=fixture();afterResult.start_records[0].result_captured_at="2026-11-12T10:00:00+09:00";
 reject(()=>grade.summarize(afterResult),"FUTURE_OR_RACE_DAY");
 const absent=fixture();
 absent.start_records.push(start("4101","2026-11-04",1,false));
 reject(()=>grade.summarize(absent),"ABSENT_CANNOT_HAVE_FINISH");
 const wrongDay=fixture();wrongDay.race_id="20261110-04-01";
 reject(()=>grade.summarize(wrongDay),"EVENT_DAY_MISMATCH");
 return {synthetic_cases:23,grades_processed:out.all_six.length,
  pending_promotions:out.all_six.filter(x=>x.research_tags.includes("B1_TO_A_CLASS_ANNOUNCED_NOT_FINAL")).length,
  announced_and_official_flags_separate:true,missing_grade_is_hold:true,
  actual_race_data_verified:false,production_modified:false};
}
const report=tests();console.log("GRADE_TRANSITION_RESEARCH_SYNTHETIC_PASS",JSON.stringify(report));
