"use strict";
/* Pure offline overlay of the existing BOAT P1 120-ticket distribution.
   Research probabilities are not independently calibrated or source-verified.
   No network, Git operations, production coefficients or original mutation. */
const SCHEMA="RACE_AI_BOAT_SIXWAY_OVERLAY_V1";
const MODEL="RACE_AI_BOAT_SIXWAY_OVERLAY_FROZEN_V1";
const INPUT="RACE_AI_BOAT_SIX_WAY_INTERACTIONS_V1";
const STYLES=["1_nige","1_loss_makuri","1_loss_sashi","1_loss_makurizashi",
 "2_nigashi","2_sashi","2_makuri","3_kado_4_makuri_won"];
for(const c of [3,4,5,6])for(const m of ["sashi","makuri","makurizashi"])STYLES.push(c+"_"+m);
const FACTORS=[...STYLES,"winner_tilt","winner_high_tilt","winner_tilt_makuri",
 "winner_tilt_makurizashi","outside_tilt_threat_vs_inside","kado_winner",
 "kado_uke_winner","kado_second","kado_uke_second","first_inward_win",
 "first_outward_top3","first_pressure_resistance","second_inward_win",
 "second_pressure_resistance","third_outward_top3","qual_gap_first",
 "qual_gap_second","qual_rank_first","qual_rank_second","second_attack",
 "third_attack","second_high_tilt","one_two_nigashi","center_outer_pair"];
const TICKETS=[];
for(let i=1;i<=6;i++)for(let j=1;j<=6;j++)for(let k=1;k<=6;k++)
 if(i!==j&&i!==k&&j!==k)TICKETS.push(i+"-"+j+"-"+k);
function check(ok,msg){if(!ok)throw Error(msg);}
function rate(v){return typeof v==="number"&&Number.isFinite(v)&&v>=0&&v<=1;}
function date(s){
 check(typeof s==="string"&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(s),"SIXWAY_CLOCK_REQUIRED");
 const n=Date.parse(s);check(Number.isFinite(n),"SIXWAY_CLOCK_INVALID");return n;
}
function fields(obj,names){
 check(obj&&typeof obj==="object"&&!Array.isArray(obj)&&names.every(k=>Object.hasOwn(obj,k)),"SIXWAY_REQUIRED_FIELD_MISSING");
}
function prepare(record){
 check(record?.stage==="P1"&&record?.context?.schema===INPUT,"SIXWAY_P1_CONTEXT_REQUIRED");
 const x=record.context,b=record.baseline;
 check(/^\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$/.test(x.race_id),"SIXWAY_RACE_ID_INVALID");
 check(b&&b.race_id===x.race_id&&date(b.as_of)<=date(x.as_of),"SIXWAY_BASELINE_ID_CLOCK_MISMATCH");
 const asof=date(x.as_of),cutoff=date(record.cutoff_at);
 check(asof<cutoff,"SIXWAY_PRE_CUTOFF_REQUIRED");
 const eventDay=x.race_id.slice(0,8);
 const jstDay=t=>new Date(t+9*60*60*1000).toISOString().slice(0,10).replace(/-/g,"");
 check(jstDay(asof)===eventDay&&jstDay(cutoff)===eventDay,"SIXWAY_EVENT_DAY_CLOCK_MISMATCH");
 fields(x,["six_course_features","formation","entry_tilt_cross_features",
  "qualifying_rank_and_point_gaps","current_venue_rule_status"]);
 check(x.current_venue_rule_status==="CLAIMED_CURRENT_RECEIPT_REQUIRES_INDEPENDENT_AUTH","SIXWAY_CURRENT_TILT_RULE_HOLD");
 const f=x.formation;
 check(Number.isInteger(f?.slow_count)&&f.slow_count>=1&&f.slow_count<=5&&
  f.kado_course===f.slow_count+1&&f.kado_uke_course===f.slow_count,
  "SIXWAY_DYNAMIC_KADO_INVALID");
 const s=x.six_course_features;fields(s,STYLES);
 for(const key of STYLES)check(rate(s[key]),"SIXWAY_STYLE_HOLD_"+key);
 const entries=x.entry_tilt_cross_features,seen=new Set(),seenFrames=new Set(),courseByFrame={};
 for(let c=1;c<=6;c++){
  const e=entries?.[String(c)];
  fields(e,["frame","racer_id","tilt_deg","outer_high_tilt_marker",
   "historical_inward_move_win_rate","historical_outward_move_top3_rate",
   "inner_pressure_kept_course_rate"]);
  check(/^\d{4}$/.test(e.racer_id)&&!seen.has(e.racer_id),"SIXWAY_RACER_ID_DUPLICATE");
  seen.add(e.racer_id);
  check(Number.isInteger(e.frame)&&e.frame>=1&&e.frame<=6&&
   !seenFrames.has(e.frame),"SIXWAY_FRAME_COURSE_NOT_BIJECTIVE");
  seenFrames.add(e.frame);courseByFrame[e.frame]=c;
  check(typeof e.tilt_deg==="number"&&Number.isFinite(e.tilt_deg)&&e.tilt_deg>=-.5&&
   e.tilt_deg<=3&&e.tilt_deg*2===Math.round(e.tilt_deg*2),"SIXWAY_TILT_UNKNOWN");
  check(e.outer_high_tilt_marker===(e.tilt_deg>=1.5&&(c>=4||c===f.kado_course)),
   "SIXWAY_TILT_MARKER_CONFLICT");
  for(const k of ["historical_inward_move_win_rate","historical_outward_move_top3_rate",
   "inner_pressure_kept_course_rate"])check(rate(e[k]),"SIXWAY_ENTRY_HOLD_"+c+"_"+k);
 }
 const q=x.qualifying_rank_and_point_gaps;
 fields(q,["border_status","rate_gaps","standings"]);
 check(q.border_status==="CURRENT_RANK_ONLY_NOT_FINAL"&&Array.isArray(q.standings)&&
  q.standings.length>=6,"SIXWAY_QUALIFYING_HOLD");
 const board=new Map(q.standings.map(row=>[row.racer_id,row]));
 check(board.size===q.standings.length,"SIXWAY_BOARD_DUPLICATE");
 const quality={};
 for(let c=1;c<=6;c++){
  const id=entries[String(c)].racer_id,row=board.get(id),gap=q.rate_gaps?.[id];
  check(row&&Number.isInteger(row.official_rank)&&row.official_rank>=1&&
   row.eligibility==="ELIGIBLE"&&typeof row.official_rate==="number"&&rate(row.official_rate/20)&&
   typeof gap==="number"&&Number.isFinite(gap),"SIXWAY_QUALIFYING_RATE_HOLD");
  quality[c]={gap:Math.tanh(gap/2),rank:1-row.official_rank/q.standings.length};
 }
 check(Array.isArray(b.full_120)&&b.full_120.length===120,"SIXWAY_BASELINE120_MISSING");
 const scores=new Map();
 for(const row of b.full_120){
  check(row&&TICKETS.includes(row.ticket)&&!scores.has(row.ticket)&&
   typeof row.score==="number"&&Number.isFinite(row.score)&&row.score>0,
   "SIXWAY_BASELINE_TICKET_INVALID");
  scores.set(row.ticket,row.score);
 }
 const prior=TICKETS.map(ticket=>scores.get(ticket));
 check(Math.abs(prior.reduce((sum,v)=>sum+v,0)-1)<1e-7,"SIXWAY_BASELINE_NOT_NORMALIZED");
 return {race:x.race_id,asof,cutoff,prior,
  frameByCourse:Object.fromEntries([1,2,3,4,5,6].map(c=>[c,entries[String(c)].frame])),
  vectors:TICKETS.map(t=>vector(t,s,entries,quality,f,courseByFrame))};
}
function vector(ticket,s,e,q,f,courseByFrame){
 // Official 3T ticket numbers are BOAT/FRAME numbers, not entry courses.
 const [a,b,c]=ticket.split("-").map(n=>courseByFrame[Number(n)]);
 const out=Object.fromEntries(FACTORS.map(k=>[k,0]));
 const attack=n=>n===1?s["1_nige"]:n===2?s["2_sashi"]+s["2_makuri"]:
  s[n+"_sashi"]+s[n+"_makuri"]+s[n+"_makurizashi"];
 for(const key of STYLES){
  if(key==="1_nige"||key.startsWith("1_loss_"))out[key]=a===1?s[key]:0;
  else if(key==="2_nigashi")out[key]=a===1?s[key]:0;
  else if(key==="3_kado_4_makuri_won")out[key]=a===4?s[key]:a===1?-s[key]:0;
  else out[key]=a===Number(key[0])?s[key]:0;
 }
 const first=e[a],second=e[b],third=e[c],outer=[3,4,5,6].reduce(
  (z,n)=>z+(e[n].outer_high_tilt_marker?attack(n):0),0)/4;
 out.winner_tilt=first.tilt_deg/3;
 out.winner_high_tilt=first.outer_high_tilt_marker?1:0;
 out.winner_tilt_makuri=a>=2?first.tilt_deg*s[a+"_makuri"]/3:0;
 out.winner_tilt_makurizashi=a>=3?first.tilt_deg*s[a+"_makurizashi"]/3:0;
 out.outside_tilt_threat_vs_inside=a===1?-outer:outer;
 out.kado_winner=a===f.kado_course?1:0;
 out.kado_uke_winner=a===f.kado_uke_course?1:0;
 out.kado_second=b===f.kado_course?1:0;
 out.kado_uke_second=b===f.kado_uke_course?1:0;
 out.first_inward_win=first.historical_inward_move_win_rate;
 out.first_outward_top3=first.historical_outward_move_top3_rate;
 out.first_pressure_resistance=first.inner_pressure_kept_course_rate;
 out.second_inward_win=second.historical_inward_move_win_rate;
 out.second_pressure_resistance=second.inner_pressure_kept_course_rate;
 out.third_outward_top3=third.historical_outward_move_top3_rate;
 out.qual_gap_first=q[a].gap;out.qual_gap_second=q[b].gap;
 out.qual_rank_first=q[a].rank;out.qual_rank_second=q[b].rank;
 out.second_attack=attack(b)/3;out.third_attack=attack(c)/3;
 out.second_high_tilt=second.outer_high_tilt_marker?1:0;
 out.one_two_nigashi=a===1&&b===2?s["2_nigashi"]:0;
 out.center_outer_pair=a>=3&&b>a?attack(a)/3:0;
 return FACTORS.map(k=>out[k]);
}
function softmax(input,coeff){
 check(Array.isArray(coeff)&&coeff.length===FACTORS.length&&
  coeff.every(w=>typeof w==="number"&&Number.isFinite(w)&&Math.abs(w)<=20),
  "SIXWAY_COEFFICIENTS_INVALID");
 const logits=input.prior.map((p,i)=>Math.log(p)+input.vectors[i].reduce(
  (v,x,j)=>v+coeff[j]*x,0));
 const max=Math.max(...logits),powers=logits.map(v=>Math.exp(v-max));
 const sum=powers.reduce((a,b)=>a+b,0);
 check(sum>0&&Number.isFinite(sum),"SIXWAY_SOFTMAX_FAILED");
 return powers.map(v=>v/sum);
}
function predict(record,model=null){
 const p=prepare(record),coeff=model===null?Array(FACTORS.length).fill(0):model.coefficients;
 if(model!==null)check(model.schema===MODEL&&model.frozen===true&&
  model.stage==="P1"&&Array.isArray(model.training_ids)&&
  date(model.trained_through)<p.asof&&!model.training_ids.includes(p.race)&&
  Array.isArray(model.feature_names)&&model.feature_names.length===FACTORS.length&&
  model.feature_names.every((name,i)=>name===FACTORS[i]),
  "SIXWAY_TRAINING_OR_CLOCK_LEAKAGE");
 const result=softmax(p,coeff);
 const all=TICKETS.map((ticket,i)=>({ticket,probability:result[i]}))
  .sort((a,b)=>b.probability-a.probability||(a.ticket<b.ticket?-1:a.ticket>b.ticket?1:0));
 const byBoat={},byCourse={};
 for(let boat=1;boat<=6;boat++)byBoat[boat]=TICKETS.reduce((v,t,i)=>v+(t.startsWith(boat+"-")?result[i]:0),0);
 for(let c=1;c<=6;c++)byCourse[c]=byBoat[p.frameByCourse[c]];
 return {schema:SCHEMA,race_id:p.race,all_120:all,top8:all.slice(0,8),
  winner_by_boat_number:byBoat,winner_by_actual_course:byCourse,
  first_boat_win_probability:byBoat[1],first_course_win_probability:byCourse[1],
  first_course_nige_probability:null,sum_probability:result.reduce((a,b)=>a+b,0),
  research_mode:model===null?"UNCHANGED_BASELINE":"EXPERIMENTAL_OVERLAY",
  source_independently_verified:false,calibrated_probability:false,
  future_accuracy_proven:false,production_model_changed:false};
}
function historical(records){
 check(Array.isArray(records)&&records.length>=50&&records.length<=2500,
  "SIXWAY_HISTORY_SAMPLE_INSUFFICIENT");
 const seen=new Set(),out=[];
 for(const row of records){
  fields(row,["input","result_ticket","result_captured_at","result_source_sha256"]);
  const p=prepare(row.input),observed=date(row.result_captured_at);
  check(!seen.has(p.race)&&TICKETS.includes(row.result_ticket),
   "SIXWAY_DUPLICATE_OR_BAD_RESULT");
  seen.add(p.race);
  check(observed>p.cutoff&&/^[a-f0-9]{64}$/.test(row.result_source_sha256),
   "SIXWAY_RESULT_CLOCK_OR_HASH_UNVERIFIED");
  out.push({...p,observed,outcome:TICKETS.indexOf(row.result_ticket),day:p.race.slice(0,8)});
 }
 out.sort((a,b)=>a.asof-b.asof||(a.race<b.race?-1:1));return out;
}
function split(rows,fraction){
 check(typeof fraction==="number"&&fraction>=.1&&fraction<=.4,
  "SIXWAY_HOLDOUT_RATIO_INVALID");
 const target=Math.floor(rows.length*(1-fraction));
 let n=target;while(n<rows.length&&rows[n].day===rows[n-1].day)n++;
 if(rows.length-n<10){n=target;while(n>40&&rows[n].day===rows[n-1].day)n--;}
 check(n>=40&&rows.length-n>=10,"SIXWAY_HOLDOUT_DAYS_NOT_ENOUGH");
 const train=rows.slice(0,n),test=rows.slice(n);
 const through=Math.max(...train.map(x=>x.observed));
 check(through<Math.min(...test.map(x=>x.asof)),"SIXWAY_HOLDOUT_INFORMATION_LEAKAGE");
 return {train,test,through};
}
function optimize(train,epochs,lr,penalty){
 check(Number.isInteger(epochs)&&epochs>=1&&epochs<=150&&
  typeof lr==="number"&&lr>=.001&&lr<=1&&
  typeof penalty==="number"&&penalty>=.05&&penalty<=30,
  "SIXWAY_OPTIMIZER_INVALID");
 let beta=Array(FACTORS.length).fill(0);
 for(let ep=0;ep<epochs;ep++){
  const gradient=beta.map(w=>penalty*w/train.length);
  for(const row of train){
   const probabilities=softmax(row,beta);
   for(let j=0;j<FACTORS.length;j++){
    let avg=0;
    for(let i=0;i<120;i++)avg+=probabilities[i]*row.vectors[i][j];
    gradient[j]+=(avg-row.vectors[row.outcome][j])/train.length;
   }
  }
  const step=lr/Math.sqrt(1+ep/8);
  beta=beta.map((w,j)=>Math.max(-6,Math.min(6,w-step*gradient[j])));
 }
 return beta;
}
function compare(test,beta){
 let originalLog=0,newLog=0,originalBrier=0,newBrier=0,oldHits=0,newHits=0;
 for(const r of test){
  const old=r.prior,updated=softmax(r,beta),pos=r.outcome;
  originalLog-=Math.log(old[pos]);newLog-=Math.log(updated[pos]);
  for(let i=0;i<120;i++){
   const truth=i===pos?1:0;
   originalBrier+=(old[i]-truth)**2;newBrier+=(updated[i]-truth)**2;
  }
  const hit=v=>[...v.keys()].sort((i,j)=>v[j]-v[i]||i-j).slice(0,8).includes(pos);
  oldHits+=Number(hit(old));newHits+=Number(hit(updated));
 }
 const n=test.length;
 return {races:n,baseline:{log_loss:originalLog/n,brier_120:originalBrier/n,
   hit_at_8:oldHits,hit_at_8_rate:oldHits/n},
  overlay:{log_loss:newLog/n,brier_120:newBrier/n,
   hit_at_8:newHits,hit_at_8_rate:newHits/n},
  delta:{log_loss:(newLog-originalLog)/n,brier_120:(newBrier-originalBrier)/n,
   hit_at_8_rate:(newHits-oldHits)/n},real_data_verified:false,
  future_improvement_proven:false,high_payout_capture_tested:false,
  ROI_tested:false};
}
function fitChronological(records,options={}){
 const recordsSorted=historical(records);
 const parts=split(recordsSorted,options.holdoutFraction??.25);
 const coefficients=optimize(parts.train,options.epochs??55,
  options.learningRate??.35,options.regularization??1.5);
 const frozen={schema:MODEL,stage:"P1",frozen:true,coefficients,
  trained_through:new Date(parts.through).toISOString(),
  training_ids:parts.train.map(x=>x.race),feature_names:[...FACTORS],
  originals_unchanged:true,production_eligible:false};
 return {frozen,train_races:parts.train.length,holdout_races:parts.test.length,
  holdout_ids:parts.test.map(x=>x.race),holdout:compare(parts.test,coefficients),
  source_authenticity_proven:false,future_performance_proven:false};
}
module.exports={SCHEMA,MODEL,INPUT,STYLES,FACTORS,TICKETS,prepare,
 predict,fitChronological,compare};
