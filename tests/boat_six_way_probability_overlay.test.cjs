"use strict";
/* Synthetic-only research regression. Never count as real race PDCA. */
const overlay=require("../race_ai/boat_six_way_probability_overlay.cjs");
function assert(ok,message){if(!ok)throw Error(message);}
function throws(fn,code){
 let msg="";try{fn();}catch(e){msg=String(e.message);}
 assert(msg.includes(code),"rejection missing: "+code+" / "+msg);
}
function fixture(index){
 const iso=new Date(Date.UTC(2026,5,1+index)).toISOString().slice(0,10);
 const rid=iso.replace(/-/g,"")+"-04-01",asof=iso+"T10:00:00+09:00";
 const styles=Object.fromEntries(overlay.STYLES.map((key,i)=>[
  key,Number((.12+((i*17+index*7)%55)/100).toFixed(2))]));
 const entries={},gaps={},standings=[];
 for(let c=1;c<=6;c++){
  const id=String(4100+c),tilt=c===5?2:c===6?3:0;
  entries[c]={frame:c,racer_id:id,tilt_deg:tilt,outer_high_tilt_marker:c>=5,
   historical_inward_move_win_rate:.32+c*.05,
   historical_outward_move_top3_rate:.3+c*.05,
   inner_pressure_kept_course_rate:.2+c*.08};
  gaps[id]=c-3;
  standings.push({racer_id:id,official_rank:c,eligibility:"ELIGIBLE",
   official_rate:10-c*.4});
 }
 const slow=index%2?4:3;
 return {stage:"P1",context:{schema:overlay.INPUT,race_id:rid,as_of:asof,
  formation:{slow_count:slow,kado_course:slow+1,kado_uke_course:slow},
  six_course_features:styles,entry_tilt_cross_features:entries,
  qualifying_rank_and_point_gaps:{
   border_status:"CURRENT_RANK_ONLY_NOT_FINAL",rate_gaps:gaps,standings},
  current_venue_rule_status:"CLAIMED_CURRENT_RECEIPT_REQUIRES_INDEPENDENT_AUTH"},
  cutoff_at:iso+"T10:30:00+09:00",
  baseline:{race_id:rid,as_of:asof,
   full_120:overlay.TICKETS.map(ticket=>({ticket,score:1/120}))}};
}
function test(){
 assert(overlay.TICKETS.length===120&&new Set(overlay.TICKETS).size===120,
  "distinct ordered top-three tickets");
 for(const course of [5,6])for(const method of ["makuri","makurizashi"])
  assert(overlay.FACTORS.includes(course+"_"+method),
   "outer attack channel "+course+"/"+method);
 const data=fixture(0),wire=JSON.stringify(data),base=overlay.predict(data);
 assert(base.all_120.length===120&&base.top8.length===8,"120 and top8");
 assert(Math.abs(base.sum_probability-1)<1e-12,"normalized 100%");
 assert(base.first_course_nige_probability===null,"outcome != nige method");
 assert(JSON.stringify(data)===wire,"immutable baseline and context");
 assert(base.source_independently_verified===false&&
  base.calibrated_probability===false,"no false real certification");
 const beta=Array(overlay.FACTORS.length).fill(0);
 beta[overlay.FACTORS.indexOf("winner_high_tilt")]=2.5;
 const frozen={schema:overlay.MODEL,frozen:true,stage:"P1",
  trained_through:"2025-12-31T00:00:00Z",
  training_ids:[],feature_names:[...overlay.FACTORS],coefficients:beta};
 const tilted=overlay.predict(data,frozen);
 assert(tilted.winner_by_actual_course[5]>base.winner_by_actual_course[5]&&
  tilted.winner_by_actual_course[6]>base.winner_by_actual_course[6],
  "5/6 high tilt must affect full 120 distribution");
 assert(Math.abs(tilted.sum_probability-1)<1e-12,"overlay sum100%");
 const kado=Array(overlay.FACTORS.length).fill(0);
 kado[overlay.FACTORS.indexOf("kado_winner")]=3;
 const model={...frozen,coefficients:kado};
 const slow3=overlay.predict(fixture(0),model);
 const slow4=overlay.predict(fixture(1),model);
 assert(slow3.winner_by_actual_course[4]>slow3.winner_by_actual_course[5],
  "3:3: kado at course 4");
 assert(slow4.winner_by_actual_course[5]>slow4.winner_by_actual_course[4],
  "4:2: kado at course 5");
 const missing=JSON.parse(JSON.stringify(data));
 missing.context.six_course_features["6_makurizashi"]=null;
 throws(()=>overlay.predict(missing),"STYLE_HOLD_6_makurizashi");
 const missingQual=JSON.parse(JSON.stringify(data));
 missingQual.context.qualifying_rank_and_point_gaps.rate_gaps["4102"]=null;
 throws(()=>overlay.predict(missingQual),"QUALIFYING_RATE_HOLD");
 const absentTilt=JSON.parse(JSON.stringify(data));
 absentTilt.context.entry_tilt_cross_features["5"].tilt_deg=null;
 throws(()=>overlay.predict(absentTilt),"TILT_UNKNOWN");
 const future=JSON.parse(JSON.stringify(data));
 future.cutoff_at="2026-05-01T11:00:00+09:00";
 throws(()=>overlay.predict(future),"PRE_CUTOFF_REQUIRED");
 const drift=JSON.parse(JSON.stringify(data));
 drift.context.formation.kado_uke_course=2;
 throws(()=>overlay.predict(drift),"DYNAMIC_KADO_INVALID");
 const wrongDay=JSON.parse(JSON.stringify(data));
 wrongDay.context.race_id="20260602-04-01";
 wrongDay.baseline.race_id="20260602-04-01";
 throws(()=>overlay.predict(wrongDay),"EVENT_DAY_CLOCK_MISMATCH");
 const wrongFactors={...frozen,feature_names:[...overlay.FACTORS].reverse()};
 throws(()=>overlay.predict(data,wrongFactors),"TRAINING_OR_CLOCK_LEAKAGE");
 const swapped=fixture(0);
 const first=swapped.context.entry_tilt_cross_features["1"];
 const sixth=swapped.context.entry_tilt_cross_features["6"];
 // Boat 6 takes actual course 1; boat 1 shifts to actual course 6.
 swapped.context.entry_tilt_cross_features["1"]={...sixth,frame:6,
   outer_high_tilt_marker:false};
 swapped.context.entry_tilt_cross_features["6"]={...first,frame:1,
   outer_high_tilt_marker:false};
 const escaping=Array(overlay.FACTORS.length).fill(0);
 escaping[overlay.FACTORS.indexOf("1_nige")]=3;
 const courseFavored=overlay.predict(swapped,{...frozen,coefficients:escaping});
 assert(courseFavored.winner_by_boat_number[6]>courseFavored.winner_by_boat_number[1],
   "boat 6 in course 1 receives inside advantage");
 assert(Math.abs(courseFavored.first_course_win_probability-
   courseFavored.winner_by_boat_number[6])<1e-12,
   "course win probability must correspond to boat 6");
 assert(Math.abs(courseFavored.first_boat_win_probability-
   courseFavored.winner_by_boat_number[1])<1e-12,
   "boat 1 win probability must not be confused with course 1");
 const duplicateFrame=fixture(0);
 duplicateFrame.context.entry_tilt_cross_features["6"].frame=1;
 throws(()=>overlay.predict(duplicateFrame),"FRAME_COURSE_NOT_BIJECTIVE");
 const bank=Array.from({length:70},(_,i)=>{
  const input=fixture(i),ticket=i%3===0?"5-6-1":i%3===1?"1-2-3":"6-5-4";
  return {input,result_ticket:ticket,
   result_captured_at:input.cutoff_at.replace("10:30","10:40"),
   result_source_sha256:"e".repeat(64)};
 });
 const out=overlay.fitChronological(bank,{epochs:12,learningRate:.3});
 assert(out.train_races>=40&&out.holdout_races>=10&&
  out.train_races+out.holdout_races===70,"full chronological partition");
 assert(out.holdout.races===out.holdout_races&&
  Number.isFinite(out.holdout.overlay.log_loss)&&
  out.holdout.real_data_verified===false,"research holdout valid");
 const newRace=overlay.predict(bank[69].input,out.frozen);
 assert(Math.abs(newRace.sum_probability-1)<1e-12,"frozen 120");
 throws(()=>overlay.predict(bank[0].input,out.frozen),"TRAINING_OR_CLOCK_LEAKAGE");
 throws(()=>overlay.fitChronological([...bank,bank[0]],{epochs:1}),
  "DUPLICATE_OR_BAD_RESULT");
 const badDate=bank.slice();badDate[0]={...badDate[0],
  result_captured_at:badDate[0].input.cutoff_at.replace("10:30","10:20")};
 throws(()=>overlay.fitChronological(badDate,{epochs:1}),
  "RESULT_CLOCK_OR_HASH_UNVERIFIED");
 assert(out.frozen.production_eligible===false&&
  out.future_performance_proven===false,"must not promote");
 return {test_cases:21,synthetic_train:out.train_races,
  synthetic_holdout:out.holdout_races,holdout_log_loss:out.holdout.overlay.log_loss,
  source_verified:false,production_promotion:false};
}
const result=test();
console.log("SIX_WAY_OVERLAY_SYNTHETIC_PASS",JSON.stringify(result));
