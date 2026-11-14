/** Prospective BOAT PDCA challenger. Never rewrites the frozen primary model.
 * Uses only earlier, already-settled private D1 outcome reports. This is a
 * research shadow, NOT a calibrated probability or automatic model promotion.
 */
import {assertFacts,assertResult,predict,refundAccounting} from './boat_nonvercel_core.mjs';

const MODEL='boat-pdca-lane-shadow-v1';
const MIN_HISTORY=24, MAX_HISTORY=240, HEX=/^[a-f0-9]{64}$/;
const enc=new TextEncoder();
async function sha(s){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',enc.encode(s)))].map(n=>n.toString(16).padStart(2,'0')).join('');}
function stamp(s){
 if(typeof s!=='string'||!/T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(s))throw Error('PDCA_CLOCK_INVALID');
 const n=Date.parse(s);if(!Number.isFinite(n))throw Error('PDCA_CLOCK_INVALID');return n;
}
function isResult(r){return r&&typeof r.race_id==='string'&&/^\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$/.test(r.race_id)
 && Array.isArray(r.official_top3)&&r.official_top3.length===3&&new Set(r.official_top3).size===3
 && r.official_top3.every(n=>Number.isInteger(n)&&n>=1&&n<=6)&&HEX.test(r.source_sha256||'');
}
async function historyBefore(rows, facts){
 if(!Array.isArray(rows)||rows.length>MAX_HISTORY)throw Error('PDCA_HISTORY_UNBOUNDED');
 const asOf=stamp(facts.captured_at), date=facts.race_id.slice(0,8), venue=facts.race_id.slice(9,11);
 const byRace=new Map();
 for(const row of rows){
  if(!row||typeof row.report_json!=='string'||row.report_json.length>5000
    ||!HEX.test(row.report_sha256||'')||!Number.isFinite(stamp(row.db_saved_at)))
    throw Error('PDCA_HISTORY_INVALID');
  if(await sha(row.report_json)!==row.report_sha256)throw Error('PDCA_HISTORY_SHA_MISMATCH');
  let report;try{report=JSON.parse(row.report_json)}catch{throw Error('PDCA_HISTORY_INVALID_JSON');}
  if(!isResult(report)||report.race_id===facts.race_id||report.race_id.slice(9,11)!==venue
    ||report.race_id.slice(0,8)>date||stamp(row.db_saved_at)>=asOf||stamp(report.captured_at)>=asOf)
    throw Error('PDCA_FUTURE_OR_WRONG_VENUE');
  const prior=byRace.get(report.race_id);
  if(!prior||stamp(row.db_saved_at)>stamp(prior.db_saved_at)){
   byRace.set(report.race_id,{...row,report});
  }else if(stamp(row.db_saved_at)===stamp(prior.db_saved_at)&&row.report_sha256!==prior.report_sha256){
   throw Error('PDCA_AMBIGUOUS_REVISION');
  }
 }
 // Filter AFTER selecting each latest revision. Otherwise an amended refund
 // could incorrectly resurrect an earlier ordinary result as training data.
 return [...byRace.values()].filter(x=>x.report.eligible_normal_accuracy!==false
   && !(x.report.refund_boats?.length)).sort((a,b)=>a.report.race_id.localeCompare(b.report.race_id));
}
function researchPseudocount(parameters){
 if(parameters===undefined)return 12;
 if(!parameters||typeof parameters!=='object'||Array.isArray(parameters)
   ||Object.keys(parameters).some(key=>key!=='lane_pseudocount'))throw Error('PDCA_PARAMETERS_INVALID');
 const value=Object.hasOwn(parameters,'lane_pseudocount')?parameters.lane_pseudocount:12;
 if(typeof value!=='number'||!Number.isFinite(value)||value<1||value>48)throw Error('PDCA_PARAMETERS_INVALID');
 return value;
}
async function buildChallenger(facts,rows,parameters=undefined){
 const pseudocount=researchPseudocount(parameters);
 const history=await historyBefore(rows,facts);
 if(history.length<MIN_HISTORY)return {status:'PDCA_NOT_ENOUGH_EARLIER_RESULTS',count:history.length};
 const laneCounts=[0,0,0,0,0,0];
 for(const h of history)laneCounts[h.report.official_top3[0]-1]++;
 const n=history.length;
 // Laplace-smoothed, capped lane-prior research hypothesis, not a fitted model.
 const factors=laneCounts.map(c=>Math.min(1.30,Math.max(0.70,(c+pseudocount)/(n/6+pseudocount))));
 const raw=predict(facts),entries=raw.all120.map(x=>({ticket:x.ticket,score:x.score*factors[x.ticket[0]-1]}));
 const total=entries.reduce((s,x)=>s+x.score,0);
 for(const x of entries)x.score/=total;
 entries.sort((a,b)=>b.score-a.score||a.ticket.join('-').localeCompare(b.ticket.join('-')));
 const activeCount=facts.racers.length;
 if(entries.length!==activeCount*(activeCount-1)*(activeCount-2)||Math.abs(entries.reduce((s,x)=>s+x.score,0)-1)>1e-9)throw Error('PDCA_PROBABILITY_MASS');
 const input=history.map(h=>({race_id:h.report.race_id,result_source_sha256:h.report.source_sha256,report_sha256:h.report_sha256,db_saved_at:h.db_saved_at}));
 const training_digest=await sha(JSON.stringify(input));
 return {status:'PDCA_CHALLENGER_READY',candidate:{
  schema:'RACE_AI_BOAT_PDCA_SHADOW_V1',race_id:facts.race_id,
  source_sha256:facts.source_sha256,cutoff_at:facts.cutoff_at,
  model_id:MODEL,phase:'post_exhibition',as_of:facts.captured_at,
  trained_until:history.reduce((a,b)=>stamp(a)>stamp(b.db_saved_at)?a:b.db_saved_at,history[0].db_saved_at),
  training_digest,training_count:n,lane_winner_counts:laneCounts,
  lane_prior_factors:factors,ordered_top8:entries.slice(0,8).map(x=>x.ticket),
  all120:entries,probabilities_calibrated:false,odds_used:false,
  auto_promoted:false,rationale:'Research only: shrinkage lane-winner prior from previously saved confirmed outcomes, capped; no future result used.'
 }};
}
async function freezeChallenger(db,facts,{now=()=>Date.now()}={}){
 assertFacts(facts,now());
 const existing=await db.prepare('SELECT body_json,payload_sha256,db_stored_at FROM boat_exhibition_shadow_freezes WHERE race_id=?').bind(facts.race_id).first();
 if(existing){
  if(await sha(existing.body_json)!==existing.payload_sha256)throw Error('PDCA_EXISTING_FREEZE_TAMPERED');
  return {status:'PDCA_SHADOW_ALREADY_FROZEN',race_id:facts.race_id,payload_sha256:existing.payload_sha256};
 }
 const primary=await db.prepare('SELECT body_json,payload_sha256,db_stored_at,cutoff_at FROM boat_exhibition_freezes WHERE race_id=?').bind(facts.race_id).first();
 if(!primary)return {status:'PDCA_PRIMARY_NOT_FROZEN',race_id:facts.race_id};
 if(await sha(primary.body_json)!==primary.payload_sha256)throw Error('PDCA_PRIMARY_TAMPERED');
 let main;try{main=JSON.parse(primary.body_json)}catch{throw Error('PDCA_PRIMARY_INVALID');}
 if(main.race_id!==facts.race_id||main.cutoff_at!==facts.cutoff_at
    ||main.source_sha256!==facts.source_sha256||main.as_of!==facts.captured_at
    ||primary.cutoff_at!==facts.cutoff_at||stamp(primary.db_stored_at)>=stamp(facts.cutoff_at))
    throw Error('PDCA_PRIMARY_SOURCE_OR_TIME_MISMATCH');
 const history=await db.prepare('SELECT report_json,report_sha256,db_saved_at FROM boat_exhibition_outcomes WHERE race_id LIKE ? AND db_saved_at < ? ORDER BY db_saved_at DESC LIMIT ?')
   .bind('%-'+facts.race_id.slice(9,11)+'-%',facts.captured_at,MAX_HISTORY).all();
 if(!Array.isArray(history?.results))throw Error('PDCA_HISTORY_READ_UNVERIFIED');
 const computed=await buildChallenger(facts,history.results);
 if(!computed.candidate)return {status:computed.status,race_id:facts.race_id,training_count:computed.count};
 const item={...computed.candidate,primary_sha256:primary.payload_sha256};
 const body=JSON.stringify(item),digest=await sha(body);
 const committed=await db.prepare("INSERT INTO boat_exhibition_shadow_freezes(race_id,model_id,primary_sha256,cutoff_at,body_json,payload_sha256,db_stored_at) "+
  "SELECT ?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE unixepoch('now')*1000 < ? "+
  "ON CONFLICT(race_id) DO NOTHING RETURNING db_stored_at")
  .bind(facts.race_id,MODEL,primary.payload_sha256,facts.cutoff_at,body,digest,stamp(facts.cutoff_at)-120000).first();
 const saved=await db.prepare('SELECT body_json,payload_sha256,db_stored_at FROM boat_exhibition_shadow_freezes WHERE race_id=?').bind(facts.race_id).first();
 if(!committed)return {status:'PDCA_SHADOW_NOT_CREATED_NO_RETRY',race_id:facts.race_id};
 if(!saved||saved.body_json!==body||saved.payload_sha256!==digest||stamp(saved.db_stored_at)>=stamp(facts.cutoff_at))
  throw Error('PDCA_SHADOW_READBACK_UNVERIFIED');
 return {status:'PDCA_SHADOW_FROZEN_READBACK_VERIFIED',race_id:facts.race_id,
    payload_sha256:digest,stored_at:saved.db_stored_at,training_count:item.training_count,model_id:MODEL,
    ordered_top8:item.ordered_top8,probabilities_calibrated:false};
}
async function settleChallenger(db,race,result,{now=()=>Date.now()}={}){
 assertResult(race,result,now());
 const frozen=await db.prepare('SELECT body_json,payload_sha256,db_stored_at FROM boat_exhibition_shadow_freezes WHERE race_id=?').bind(race.race_id).first();
 let forecast=null;
 if(frozen){
  if(await sha(frozen.body_json)!==frozen.payload_sha256||stamp(frozen.db_stored_at)>=stamp(race.cutoff_at))throw Error('PDCA_SHADOW_TAMPERED');
  try{forecast=JSON.parse(frozen.body_json)}catch{throw Error('PDCA_SHADOW_INVALID');}
  if(forecast.race_id!==race.race_id||forecast.cutoff_at!==race.cutoff_at||forecast.model_id!==MODEL
   ||forecast.probabilities_calibrated!==false||forecast.ordered_top8.length!==8)throw Error('PDCA_SHADOW_IDENTITY_MISMATCH');
 }
 const win=result.top3.join('-');
 const report={race_id:race.race_id,source_sha256:result.source_sha256,official_top3:result.top3,
  captured_at:result.captured_at,candidate_frozen:!!forecast,model_id:forecast?.model_id??null,
  candidate_sha256:frozen?.payload_sha256??null,training_digest:forecast?.training_digest??null,
  hit1:Number(!!forecast&&forecast.ordered_top8[0].join('-')===win),
  hit8:Number(!!forecast&&forecast.ordered_top8.some(x=>x.join('-')===win)),
  calibrated:false,auto_promoted:false};
 if(result.refund_boats.length)Object.assign(report,refundAccounting(forecast?.ordered_top8??[],result));
 const body=JSON.stringify(report),digest=await sha(body);
 await db.prepare("INSERT INTO boat_exhibition_shadow_outcomes(race_id,result_sha256,report_json,report_sha256,db_saved_at) "+
  "VALUES(?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(race_id,result_sha256) DO NOTHING")
  .bind(race.race_id,result.source_sha256,body,digest).run();
 const saved=await db.prepare('SELECT report_json,report_sha256,db_saved_at FROM boat_exhibition_shadow_outcomes WHERE race_id=? AND result_sha256=?')
  .bind(race.race_id,result.source_sha256).first();
 if(!saved||await sha(saved.report_json)!==saved.report_sha256)throw Error('PDCA_SHADOW_SCORE_READBACK_MISMATCH');
 let prior;try{prior=JSON.parse(saved.report_json)}catch{throw Error('PDCA_SHADOW_INVALID_SAVED_JSON');}
 const stable=x=>JSON.stringify({...x,captured_at:null});
 if(stable(prior)!==stable(report))throw Error('PDCA_SHADOW_REPLAY_CONFLICT');
 return {status:saved.report_json===body?'PDCA_SHADOW_SCORED':'PDCA_SHADOW_ALREADY_SCORED',
  ...prior,report_sha256:saved.report_sha256,db_saved_at:saved.db_saved_at};
}
export {MODEL,MIN_HISTORY,buildChallenger,freezeChallenger,settleChallenger};
