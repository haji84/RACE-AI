/**
 * Private D1 BOAT exhibition persistence. No Vercel, provider calls or wagers.
 * Callers must independently validate six actual boats, source rights, clock
 * and the official race identity. All predicted scores are UNCALIBRATED.
 */
const SCHEMA='RACE_AI_BOAT_OBSERVATION_V1',MODEL='pr64-official-beforeinfo-display-pl-v1-nonvercel';
const HEX=/^[a-f0-9]{64}$/,ID=/^(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$/;
const HOST='https://www.boatrace.jp',ENC=new TextEncoder();
const clock=s=>{if(typeof s!=='string'||!/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(s))throw Error('INVALID_CLOCK');let n=Date.parse(s);if(!Number.isFinite(n))throw Error('INVALID_CLOCK');return n;};
const day=n=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(n));
async function digest(raw){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',ENC.encode(raw))),b=>b.toString(16).padStart(2,'0')).join('');}
const triples=[];for(let a=1;a<=6;a++)for(let b=1;b<=6;b++)for(let c=1;c<=6;c++)if(a!==b&&a!==c&&b!==c)triples.push([a,b,c]);
function sourceUrl(url,kind,rid){
 const m=ID.exec(rid);if(!m||typeof url!=='string')throw Error('INVALID_RACE');
 const u=new URL(url);if(u.origin!==HOST||u.pathname!='/owpc/pc/race/'+kind||u.searchParams.size!==3
  ||u.searchParams.get('hd')!==m[1]||u.searchParams.get('jcd')!==m[2]
  ||Number(u.searchParams.get('rno'))!==Number(m[3])||u.username||u.password||u.hash)throw Error('SOURCE_RACE_MISMATCH');
}
function assertFacts(f,now){
 if(!f||f.schema!==SCHEMA||f.phase!=='post_exhibition'||!ID.test(f.race_id)
  ||!HEX.test(f.source_sha256||'')||f.rights_verified!==true
  ||f.license_purpose!=='private_analysis'||!HEX.test(f.program_sha256||'')||!Array.isArray(f.racers)||f.racers.length!==6)throw Error('FACTS_UNADMITTED');
 sourceUrl(f.source_url,'beforeinfo',f.race_id);
 let cutoff=clock(f.cutoff_at),capture=clock(f.captured_at),m=ID.exec(f.race_id);
 if(day(cutoff)!==m[1].slice(0,4)+'-'+m[1].slice(4,6)+'-'+m[1].slice(6,8)
    ||day(capture)!==day(cutoff)||capture>now||capture>=cutoff||cutoff-now<=120000)throw Error('NOT_BEFORE_SAFE_CUTOFF');
 let lanes=new Set(),racers=new Set();
 for(const r of f.racers){
  if(!r||!Number.isInteger(r.lane)||r.lane<1||r.lane>6||lanes.has(r.lane)||!/^\d{4}$/.test(r.registration_no)
   ||racers.has(r.registration_no)||typeof r.exhibition_time_seconds!=='number'
   ||!Number.isFinite(r.exhibition_time_seconds)||r.exhibition_time_seconds<4||r.exhibition_time_seconds>12
   ||(r.national_win_rate!==null&&(!Number.isFinite(r.national_win_rate)||r.national_win_rate<0||r.national_win_rate>10)))
   throw Error('INVALID_SIX_BOATS');
  lanes.add(r.lane);racers.add(r.registration_no);
 }
 if(lanes.size!==6||racers.size!==6)throw Error('BOAT_IDENTITY_INCOMPLETE');
}
function predict(f){
 let r=[...f.racers].sort((a,b)=>a.lane-b.lane);
 const mean=r.reduce((a,x)=>a+x.exhibition_time_seconds,0)/6;
 const strengths=r.map(x=>Math.exp(Math.max(-20,Math.min(20,
  Math.log(Math.max(x.national_win_rate??1,.01))+mean-x.exhibition_time_seconds))));
 const total=strengths.reduce((a,b)=>a+b,0);
 const all120=triples.map(t=>{
  let [a,b,c]=t.map(n=>strengths[n-1]);
  return {ticket:t,score:a/total*b/(total-a)*c/(total-a-b)};
 }).sort((a,b)=>b.score-a.score||a.ticket.join('').localeCompare(b.ticket.join('')));
 if(all120.length!==120||Math.abs(all120.reduce((a,b)=>a+b.score,0)-1)>1e-9)throw Error('MODEL_MASS');
 return {phase:'post_exhibition',race_id:f.race_id,cutoff_at:f.cutoff_at,as_of:f.captured_at,
  model_id:MODEL,calibrated:false,odds_used:false,source_sha256:f.source_sha256,program_sha256:f.program_sha256,
  top8:all120.slice(0,8).map(x=>x.ticket),all120,
  base_rating_missing:r.filter(x=>x.national_win_rate===null).map(x=>x.lane),
  rationale:'PR64 untrained PL: official national win-rate baseline and six measured exhibition times; uncalibrated.'};
}
async function freeze(db,f,{now=()=>Date.now()}={}){
 assertFacts(f,now());let value=predict(f),body=JSON.stringify(value),sha=await digest(body);
 const sql="INSERT INTO boat_exhibition_freezes(race_id,model_id,source_sha256,cutoff_at,body_json,payload_sha256,db_stored_at) "+
  "SELECT ?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE unixepoch('now')*1000 < ? "+
  "ON CONFLICT(race_id) DO NOTHING RETURNING db_stored_at";
 const written=await db.prepare(sql).bind(f.race_id,MODEL,f.source_sha256,f.cutoff_at,body,sha,clock(f.cutoff_at)-120000).first();
 const stored=await db.prepare('SELECT body_json,payload_sha256,db_stored_at,model_id,cutoff_at FROM boat_exhibition_freezes WHERE race_id=?').bind(f.race_id).first();
 if(!stored)return {race_id:f.race_id,status:'CUTOFF_OR_WRITE_NOT_ACCEPTED'};
 if(!written)return {race_id:f.race_id,status:'ALREADY_FROZEN_DO_NOT_REPOST',stored_at:stored.db_stored_at};
 if(stored.body_json!==body||stored.payload_sha256!==sha||stored.model_id!==MODEL||stored.cutoff_at!==f.cutoff_at
  ||clock(stored.db_stored_at)>=clock(f.cutoff_at))throw Error('DB_READBACK_MISMATCH');
 return {race_id:f.race_id,status:'FROZEN_DB_READBACK_VERIFIED',stored_at:stored.db_stored_at,
         payload_sha256:sha,top8:value.top8,probabilities_calibrated:false};
}
function assertResult(race,res,now){
 if(!race||!ID.test(race.race_id)||!res||res.phase!=='official_result'||res.race_id!==race.race_id
  ||!HEX.test(res.source_sha256||'')||res.result_state!=='confirmed'||res.dead_heat!==false
  ||!Array.isArray(res.refund_boats)||res.refund_boats.length||!Array.isArray(res.top3)||res.top3.length!==3
  ||new Set(res.top3).size!==3||res.top3.some(n=>!Number.isInteger(n)||n<1||n>6)
  ||clock(res.captured_at)>now||clock(res.captured_at)<clock(race.cutoff_at)
  ||(res.payout_per_100_yen!=null&&(!Number.isSafeInteger(res.payout_per_100_yen)||res.payout_per_100_yen<100)))
  throw Error('RESULT_UNADMITTED');
 sourceUrl(res.source_url,'raceresult',race.race_id);
}
async function settle(db,race,res,{now=()=>Date.now()}={}){
 assertResult(race,res,now());
 const old=await db.prepare('SELECT body_json,payload_sha256 FROM boat_exhibition_freezes WHERE race_id=?').bind(race.race_id).first();
 let p=null;if(old){if(await digest(old.body_json)!==old.payload_sha256)throw Error('FORECAST_TAMPERED');p=JSON.parse(old.body_json);}
 const report={race_id:race.race_id,official_top3:res.top3,source_sha256:res.source_sha256,
  captured_at:res.captured_at,freeze_sha256:old?.payload_sha256??null,
  hit1:Number(!!p&&p.top8[0].join('-')===res.top3.join('-')),
  hit8:Number(!!p&&p.top8.some(t=>t.join('-')===res.top3.join('-'))),
  official_trifecta_payout_per_100_yen:res.payout_per_100_yen??null,
  hypothetical_stake_yen:p?800:0,
  hypothetical_return_yen:res.payout_per_100_yen==null?null:
   (p&&p.top8.some(t=>t.join('-')===res.top3.join('-'))?res.payout_per_100_yen:0),
  model_calibrated:false,retroactive_edit:false};
 const raw=JSON.stringify(report),sha=await digest(raw);
 await db.prepare("INSERT INTO boat_exhibition_outcomes(race_id,result_sha256,report_json,report_sha256,db_saved_at) "+
  "VALUES(?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(race_id,result_sha256) DO NOTHING")
  .bind(race.race_id,res.source_sha256,raw,sha).run();
 const saved=await db.prepare('SELECT report_json,report_sha256,db_saved_at FROM boat_exhibition_outcomes WHERE race_id=? AND result_sha256=?')
  .bind(race.race_id,res.source_sha256).first();
 if(!saved||await digest(saved.report_json)!==saved.report_sha256)throw Error('RESULT_READBACK_MISMATCH');
 let prior;try{prior=JSON.parse(saved.report_json)}catch{throw Error('RESULT_READBACK_INVALID_JSON');}
 // The same official HTML may be observed again with a later acquisition
 // timestamp. Preserve the ORIGINAL audit report, not an updated copy.
 const stable=x=>JSON.stringify({...x,captured_at:null});
 if(stable(prior)!==stable(report))throw Error('RESULT_REPLAY_CONFLICT');
 return {status:saved.report_json===raw?'RESULT_PDCA_DB_VERIFIED':'RESULT_PDCA_ALREADY_SCORED',
  ...prior,report_sha256:saved.report_sha256,db_saved_at:saved.db_saved_at};
}
export {assertFacts,assertResult,predict,freeze,settle,MODEL,SCHEMA};
