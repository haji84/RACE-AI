/** Cloudflare cron-only private BOAT pilot. No public HTTP endpoint, Vercel, or wagers. */
import {freeze,settle,SCHEMA} from './boat_nonvercel_core.mjs';
import {freezeChallenger,settleChallenger} from './boat_pdca_shadow.mjs';
import {parseSchedule,parseRacelist,parseExhibition,parseResult} from './boat_official_html.mjs';
const HOST='https://www.boatrace.jp',DAY_LIMIT=120,BYTES=900000;
function jstDay(d){const t=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d).map(p=>[p.type,p.value]));return t.year+t.month+t.day;}
function url(kind,day,venue,race){return HOST+'/owpc/pc/race/'+kind+'?rno='+race+'&jcd='+venue+'&hd='+day;}
async function quota(db,day,venue,limit){
 const row=await db.prepare("INSERT INTO boat_source_budget(day_jst,venue,attempts) VALUES(?,?,1) " +
  "ON CONFLICT(day_jst,venue) DO UPDATE SET attempts=attempts+1 WHERE attempts < ? " +
  "AND (blocked_until IS NULL OR julianday(blocked_until)<=julianday('now')) RETURNING attempts")
  .bind(day,venue,limit).first();
 return !!row?.attempts;
}
async function fetchBounded(db,day,venue,kind,race,{fetcher=fetch,limit=DAY_LIMIT,budgetDay=day}={}){
 // Old race revisions consume TODAY's traffic budget, not yesterday's.
 if(!await quota(db,budgetDay,venue,limit))throw Error('OFFICIAL_DAILY_REQUEST_BUDGET_EXHAUSTED');
 const target=url(kind,day,venue,race);
 const response=await fetcher(target,{method:'GET',redirect:'manual',headers:{Accept:'text/html','Cache-Control':'no-store'}});
 if(response.status===429||response.status===403){
  await db.prepare('UPDATE boat_source_budget SET blocked_until=? WHERE day_jst=? AND venue=?')
   .bind(day.slice(0,4)+'-'+day.slice(4,6)+'-'+day.slice(6,8)+'T23:59:59+09:00',day,venue).run();
  throw Error('OFFICIAL_PROVIDER_BLOCKED_STOP');
 }
 if(response.status!==200||response.url!==target||!response.headers.get('Content-Type')?.toLowerCase().startsWith('text/html'))throw Error('OFFICIAL_UNEXPECTED_HTTP');
 if(!response.body?.getReader)throw Error('OFFICIAL_BODY_STREAM_REQUIRED');
 const reader=response.body.getReader();let total=0,parts=[];
 for(;;){const {done,value}=await reader.read();if(done)break;total+=value.length;
  if(total>BYTES){await reader.cancel();throw Error('OFFICIAL_HTML_TOO_LARGE');}parts.push(value);}
 const bytes=new Uint8Array(total);let offset=0;for(const p of parts){bytes.set(p,offset);offset+=p.length;}
 const sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
 return {html:new TextDecoder('utf-8',{fatal:true}).decode(bytes),
  sha256,captured_at:new Date().toISOString(),source_url:target};
}
async function claimResultPoll(db,raceId){
 // Atomic lease is durable across concurrent cron invocations; no flood on
 // pending pages. Each successful result is revisited at six-hour intervals.
 const sql="INSERT INTO boat_result_poll_state(race_id,next_check_at,checks) "+
  "VALUES(?,strftime('%Y-%m-%dT%H:%M:%fZ','now','+5 minutes'),1) "+
  "ON CONFLICT(race_id) DO UPDATE SET "+
  "next_check_at=strftime('%Y-%m-%dT%H:%M:%fZ','now','+5 minutes'),checks=checks+1 "+
  "WHERE boat_result_poll_state.next_check_at <= strftime('%Y-%m-%dT%H:%M:%fZ','now') RETURNING checks";
 return !!(await db.prepare(sql).bind(raceId).first());
}
async function resultChecked(db,raceId,sourceSha){
 await db.prepare("UPDATE boat_result_poll_state SET "+
  "next_check_at=strftime('%Y-%m-%dT%H:%M:%fZ','now','+6 hours'),last_verified_source_sha256=? WHERE race_id=?")
  .bind(sourceSha,raceId).run();
}
async function rememberGate(db,raceId,stage,reason){
 if(!/^[A-Z0-9_]{3,100}$/.test(reason))reason='UNKNOWN_SAFE_STOP';
 await db.prepare("INSERT INTO boat_race_gate_reasons(race_id,stage,reason,first_seen_at) "+
  "VALUES(?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(race_id,stage,reason) DO NOTHING")
  .bind(raceId,stage,reason).run();
}
async function runTick(env,{now=new Date(),fetcher=fetch}={}){
 if(env?.BOAT_AUTO_ENABLED!=='true')return {state:'DISABLED',calls:0};
 if(env.BOAT_RIGHTS_REVIEWED!=='true'||typeof env.BOAT_RIGHTS_REFERENCE!=='string'||env.BOAT_RIGHTS_REFERENCE.length<10
   ||!env.BOAT_DB||!/^(0[1-9]|1[0-9]|2[0-4])$/.test(env.BOAT_PILOT_VENUE||''))return {state:'RIGHTS_OR_DB_NOT_READY'};
 const db=env.BOAT_DB,day=jstDay(now),venue=env.BOAT_PILOT_VENUE,nowMs=now.getTime(),max=Number(env.BOAT_MAX_REQUESTS_PER_DAY);
 if(!Number.isInteger(max)||max<1||max>DAY_LIMIT)return {state:'BUDGET_NOT_CONFIGURED'};
 let schedule=await db.prepare('SELECT race_id,race_no,cutoff_at FROM boat_race_schedule WHERE date_jst=? AND venue=? ORDER BY race_no').bind(day,venue).all();
 let discovered=false;
 if(!schedule.results?.length){
  const fetched=await fetchBounded(db,day,venue,'racelist',1,{fetcher,limit:max}),rows=parseSchedule(fetched.html,day,venue);
  if(rows.length!==12)throw Error('OFFICIAL_SCHEDULE_12_REQUIRED');
  for(const r of rows)await db.prepare('INSERT INTO boat_race_schedule(race_id,date_jst,venue,race_no,cutoff_at) VALUES(?,?,?,?,?) ON CONFLICT(race_id) DO NOTHING')
    .bind(r.race_id,day,venue,r.race_no,r.cutoff_at).run();
  schedule=await db.prepare('SELECT race_id,race_no,cutoff_at FROM boat_race_schedule WHERE date_jst=? AND venue=? ORDER BY race_no').bind(day,venue).all();
  discovered=true;
 }
 if(schedule.results?.length!==12)throw Error('SCHEDULE_NOT_DURABLE_COMPLETE');
 const outcomes=[],forecasts=[];
 const yesterday=jstDay(new Date(nowMs-86400000));
 const prior=await db.prepare('SELECT race_id,race_no,cutoff_at FROM boat_race_schedule WHERE date_jst=? AND venue=? ORDER BY race_no')
  .bind(yesterday,venue).all();
 // Only previously discovered and persisted earlier races are eligible;
 // missing yesterday coverage is NOT fabricated or called complete.
 const finished=[...(prior.results||[]),...schedule.results]
  .filter(r=>Date.parse(r.cutoff_at)+180000<nowMs)
  .sort((a,b)=>Date.parse(a.cutoff_at)-Date.parse(b.cutoff_at));
 for(const r of finished){
  if(!await claimResultPoll(db,r.race_id))continue;
  const resultDay=r.race_id.slice(0,8);
  try{
   const original=await fetchBounded(db,resultDay,venue,'racelist',r.race_no,{fetcher,limit:max,budgetDay:day});
   const fresh=parseSchedule(original.html,resultDay,venue)[r.race_no-1];
   if(fresh.cutoff_at!==r.cutoff_at)throw Error('RESULT_CUTOFF_REVISION');
   const verifiedRoster=parseRacelist(original.html,resultDay,venue,r.race_no);
   const raw=await fetchBounded(db,resultDay,venue,'raceresult',r.race_no,{fetcher,limit:max,budgetDay:day});
   const top3=parseResult(raw.html,resultDay,venue,r.race_no,verifiedRoster);
   const fact={phase:'official_result',race_id:r.race_id,source_url:raw.source_url,source_sha256:raw.sha256,
     captured_at:raw.captured_at,result_state:'confirmed',refund_boats:[],dead_heat:false,top3};
   const scored=await settle(db,{race_id:r.race_id,cutoff_at:r.cutoff_at},fact);
   let challenger;
   try{challenger=await settleChallenger(db,{race_id:r.race_id,cutoff_at:r.cutoff_at},fact);}
   catch(e){challenger={status:'SHADOW_SCORE_REQUIRES_REVIEW',reason:String(e.message).slice(0,85)};}
   await resultChecked(db,r.race_id,raw.sha256);
   outcomes.push({race_id:r.race_id,status:scored.status,hit8:scored.hit8,
     freeze_sha256:scored.freeze_sha256,shadow_status:challenger.status,
     shadow_hit8:challenger.hit8??null,shadow_reason:challenger.reason??null});
  }catch(e){
   const reason=String(e.message||'UNKNOWN').replace(/[^A-Z0-9_]/g,'_').slice(0,100);
   await rememberGate(db,r.race_id,'RESULT',reason);
   outcomes.push({race_id:r.race_id,status:'RESULT_PENDING_OR_REJECTED',reason});
  }
  break;
 }
 const upcoming=schedule.results.filter(r=>{const t=Date.parse(r.cutoff_at)-nowMs;return t>120000&&t<=720000;})
    .sort((a,b)=>Date.parse(a.cutoff_at)-Date.parse(b.cutoff_at));
 for(const r of upcoming){
  const prior=await db.prepare('SELECT payload_sha256 FROM boat_exhibition_freezes WHERE race_id=?').bind(r.race_id).first();
  if(prior)continue;
  try{
   const list=await fetchBounded(db,day,venue,'racelist',r.race_no,{fetcher,limit:max});
   const updated=parseSchedule(list.html,day,venue)[r.race_no-1];
   if(updated.race_id!==r.race_id||updated.cutoff_at!==r.cutoff_at)throw Error('OFFICIAL_CUTOFF_CHANGED');
   const roster=parseRacelist(list.html,day,venue,r.race_no);
   const before=await fetchBounded(db,day,venue,'beforeinfo',r.race_no,{fetcher,limit:max});
   const racers=parseExhibition(before.html,day,venue,r.race_no,roster);
   const facts={schema:SCHEMA,phase:'post_exhibition',race_id:r.race_id,cutoff_at:r.cutoff_at,
    captured_at:before.captured_at,source_url:before.source_url,source_sha256:before.sha256,program_sha256:list.sha256,
    rights_verified:true,license_purpose:'private_analysis',racers};
   const frozen=await freeze(db,facts);
   let shadow={status:'PDCA_PRIMARY_NOT_FROZEN'};
   if(frozen.status==='FROZEN_DB_READBACK_VERIFIED'){
    try{shadow=await freezeChallenger(db,facts);}
    catch(e){shadow={status:'PDCA_SHADOW_REQUIRES_REVIEW',reason:String(e.message).slice(0,85)};}
   }
   forecasts.push({race_id:r.race_id,status:frozen.status,stored_at:frozen.stored_at??null,
    shadow_status:shadow.status,shadow_training_count:shadow.training_count??null,
    shadow_reason:shadow.reason??null});
  }catch(e){
   const reason=String(e.message||'UNKNOWN').replace(/[^A-Z0-9_]/g,'_').slice(0,100);
   await rememberGate(db,r.race_id,'FORECAST',reason);
   forecasts.push({race_id:r.race_id,status:'EXHIBITION_PENDING_OR_REJECTED',reason});
  }
  break;
 }
 return {state:'TICK_COMPLETE',date_jst:day,venue,discovered,forecast_status:forecasts,result_status:outcomes,
  previous_day_discovered_rows:prior.results?.length??0,
  predictor_calibrated:false,continuous_live_verified:false};
}
export {runTick,claimResultPoll,resultChecked,rememberGate};
export default {
 async fetch(){return new Response('Not Found',{status:404,headers:{'Cache-Control':'no-store'}});},
 async scheduled(event,env,ctx){ctx.waitUntil(runTick(env).then(x=>console.log(JSON.stringify(x))).catch(e=>console.error('BOAT_TICK_SAFE_STOP',String(e.message).slice(0,100))));}
};
