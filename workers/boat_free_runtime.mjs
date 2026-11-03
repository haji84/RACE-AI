/** Owner-only Cloudflare Free connection: one official page per leased job. */
import {parseSchedule,parseRacelist,parseExhibition,parseResultDetails} from './boat_official_html.mjs';
import {buildPair,scorePair,parseDay,parseProgram,jstDay} from './boat_free_model.mjs';
const HOST='https://www.boatrace.jp',MAX_HTML=900000,MAX_JOBS=4,MAX_GETS=5000;
const read=(db,sql,...args)=>db.prepare(sql).bind(...args).first();
const write=(db,sql,...args)=>db.prepare(sql).bind(...args).run();
const rows=async(db,sql,...args)=>(await db.prepare(sql).bind(...args).all()).results||[];
const iso=()=>new Date().toISOString();
const need=(v,m)=>{if(!v)throw Error(m);};
const sha=async s=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',typeof s==='string'?new TextEncoder().encode(s):s)),b=>b.toString(16).padStart(2,'0')).join('');
const url=(kind,day,venue,n)=>`${HOST}/owpc/pc/race/${kind}?rno=${n}&jcd=${venue}&hd=${day}`;
const event=(db,id,stage,reason)=>write(db,'INSERT OR IGNORE INTO live_events(race_id,stage,reason) VALUES(?,?,?)',id,stage,/^[A-Z0-9_]{2,100}$/.test(reason)?reason:'UNCLASSIFIED_SAFE_STOP');
export async function takeBudget(db,utcDay,limit=MAX_GETS){need(Number.isInteger(limit)&&limit>0&&limit<=MAX_GETS,'BUDGET_INVALID');return !!await read(db,"INSERT INTO live_budget(utc_day,requests) VALUES(?,1) ON CONFLICT(utc_day) DO UPDATE SET requests=requests+1 WHERE requests<? AND blocked_until<=unixepoch('now')*1000 RETURNING requests",utcDay,limit);}
export async function leaseRace(db,id){return !!await read(db,"UPDATE live_races SET lease_until=unixepoch('now')*1000+90000,attempts=attempts+1 WHERE race_id=? AND lease_until<=unixepoch('now')*1000 RETURNING race_id",id);}
async function capacity(db,bytes){need(Number.isInteger(bytes)&&bytes>0&&bytes<120000,'PAYLOAD_SIZE');need(await read(db,'UPDATE live_capacity SET allocated_bytes=allocated_bytes+? WHERE id=1 AND allocated_bytes+?<300000000 RETURNING allocated_bytes',bytes,bytes),'STORAGE_SOFT_LIMIT');}
export async function persistPair(db,race,pair){
 const body=JSON.stringify(pair),digest=await sha(body);let existing=await read(db,'SELECT * FROM live_freezes WHERE race_id=?',race.race_id);
 if(existing){need(existing.sha256===digest&&existing.body_json===body,'EXISTING_FORECAST_CONFLICT');return existing;}
 need(pair.race_id===race.race_id&&pair.cutoff_at===race.cutoff_at&&Date.parse(pair.generated_at)+120000<race.cutoff_ms,'FORECAST_ID_OR_TIME');
 await capacity(db,new TextEncoder().encode(body).length+2000);
 await write(db,"INSERT INTO live_freezes(race_id,body_json,sha256) SELECT race_id,?,? FROM live_races WHERE race_id=? AND cutoff_ms>unixepoch('now')*1000+120000 ON CONFLICT(race_id) DO NOTHING",body,digest,race.race_id);
 existing=await read(db,'SELECT * FROM live_freezes WHERE race_id=?',race.race_id);
 need(existing&&existing.sha256===digest&&existing.body_json===body&&Date.parse(existing.db_saved_at)<race.cutoff_ms,'DB_FREEZE_READBACK_FAILED_OR_LATE');return existing;
}
export async function persistResult(db,race,fact){
 need(Date.now()>race.cutoff_ms&&Date.parse(fact.captured_at)>=race.cutoff_ms&&Date.parse(fact.captured_at)<=Date.now(),'RESULT_REQUIRES_CLOSED_RACE');need(/^[a-f0-9]{64}$/.test(fact.source_sha),'RESULT_SHA_INVALID');
 const frozen=await read(db,'SELECT * FROM live_freezes WHERE race_id=?',race.race_id);let pair=null;
 if(frozen){need(await sha(frozen.body_json)===frozen.sha256&&Date.parse(frozen.db_saved_at)<race.cutoff_ms,'FROZEN_ORIGINAL_INVALID');pair=JSON.parse(frozen.body_json);}
 const report=scorePair(pair,fact.detail),reportJson=JSON.stringify(report),digest=await sha(reportJson),prior=await read(db,'SELECT * FROM live_results WHERE race_id=? AND source_sha=?',race.race_id,fact.source_sha);
 if(!prior){await capacity(db,reportJson.length+JSON.stringify(fact).length+1500);await write(db,'INSERT OR IGNORE INTO live_results(race_id,source_sha,fact_json,report_json,report_sha) VALUES(?,?,?,?,?)',race.race_id,fact.source_sha,JSON.stringify(fact),reportJson,digest);}
 const saved=await read(db,'SELECT * FROM live_results WHERE race_id=? AND source_sha=?',race.race_id,fact.source_sha);need(saved?.report_sha===digest&&saved.report_json===reportJson,'RESULT_READBACK_MISMATCH');
 await write(db,'UPDATE live_races SET stage=?,result_sha=?,lease_until=0,next_at=? WHERE race_id=?','DONE',fact.source_sha,Date.now()+21600000,race.race_id);return saved;
}
export async function replayOne(db,raceId,realDay=jstDay(new Date())){
 need(realDay===jstDay(new Date())&&raceId.slice(0,8)<realDay,'REPLAY_REQUIRES_REAL_NEXT_DAY');const r=await read(db,'SELECT * FROM live_races WHERE race_id=?',raceId);need(r?.stage==='DONE'&&r.result_sha,'REPLAY_RESULT_NOT_FINAL');
 const result=await read(db,'SELECT * FROM live_results WHERE race_id=? AND source_sha=?',raceId,r.result_sha),f=await read(db,'SELECT * FROM live_freezes WHERE race_id=?',raceId);
 need(result&&await sha(result.report_json)===result.report_sha,'REPLAY_REPORT_HASH');if(f)need(await sha(f.body_json)===f.sha256&&Date.parse(f.db_saved_at)<r.cutoff_ms,'REPLAY_FORECAST_HASH');
 const recomputed=JSON.stringify(scorePair(f?JSON.parse(f.body_json):null,JSON.parse(result.fact_json).detail));need(recomputed===result.report_json,'REPLAY_OUTPUT_MISMATCH');
 await write(db,'INSERT OR IGNORE INTO live_replays(race_id,source_sha,replay_day,report_sha) VALUES(?,?,?,?)',raceId,r.result_sha,realDay,result.report_sha);return {race_id:raceId,report_sha:result.report_sha,state:'D_PLUS_1_REPLAY_MATCH',forecast_present:!!f};
}
export async function chooseTasks(db,day){
 const now=Date.now(),prior=jstDay(new Date(now-86400000));
 const upcoming=await rows(db,"SELECT * FROM live_races WHERE day=? AND stage IN ('PROGRAM','EXHIBITION') AND next_at<=? AND lease_until<=? AND cutoff_ms>? AND cutoff_ms<? ORDER BY cutoff_ms,race_id LIMIT 4",day,now,now,now+120000,now+1200000);
 const closed=await rows(db,"SELECT * FROM live_races WHERE day>=? AND stage!='DONE' AND next_at<=? AND lease_until<=? AND cutoff_ms<? ORDER BY cutoff_ms,race_id LIMIT 4",prior,now,now,now-180000);
 const due=[...upcoming.slice(0,2),...closed.slice(0,2)];for(const r of [...upcoming,...closed])if(due.length<MAX_JOBS&&!due.some(x=>x.race_id===r.race_id))due.push(r);return due;
}
async function getPage(db,target){
 const utc=iso().slice(0,10);need(target.startsWith(HOST+'/owpc/pc/race/'),'HOST_NOT_ALLOWED');need(await takeBudget(db,utc),'OFFICIAL_BUDGET_OR_BACKOFF');
 const response=await fetch(target,{redirect:'manual',headers:{Accept:'text/html'},signal:AbortSignal.timeout(12000)});
 if(response.status===403||response.status===429){await write(db,'UPDATE live_budget SET blocked_until=? WHERE utc_day=?',Date.now()+3600000,utc);throw Error('PROVIDER_BLOCKED_BACKOFF');}
 need(response.status===200&&response.url===target&&response.headers.get('content-type')?.includes('text/html'),'OFFICIAL_HTTP_INVALID');
 const reader=response.body.getReader(),chunks=[];let total=0;while(true){const {done,value}=await reader.read();if(done)break;total+=value.length;if(total>MAX_HTML){await reader.cancel();throw Error('OFFICIAL_HTML_TOO_LARGE');}chunks.push(value);}
 const bytes=new Uint8Array(total);let pos=0;for(const b of chunks){bytes.set(b,pos);pos+=b.length;}return {html:new TextDecoder('utf-8',{fatal:true}).decode(bytes),sha:await sha(bytes),captured_at:iso(),url:target};
}
async function finishStage(db,id,stage,delay=0){await write(db,'UPDATE live_races SET stage=?,lease_until=0,next_at=?,last_error=NULL WHERE race_id=?',stage,Date.now()+delay,id);}
export async function handleJob(env,job){
 const db=env.BOAT_DB;need(env.BOAT_AUTO_ENABLED==='true'&&db,'DISABLED');need(job&&['INDEX','VENUE','RACE','REPLAY'].includes(job.kind),'TASK_INVALID');
 const day=jstDay(new Date());
 if(job.kind==='INDEX'){
  need(job.day===day,'INDEX_WRONG_DAY');if(await read(db,'SELECT day FROM live_days WHERE day=?',day))return {state:'ALREADY_DISCOVERED'};
  const p=await getPage(db,`${HOST}/owpc/pc/race/index?hd=${day}`),venues=parseDay(p.html,day);
  await write(db,'INSERT OR IGNORE INTO live_days(day,venues_json,source_sha,captured_at) VALUES(?,?,?,?)',day,JSON.stringify(venues),p.sha,p.captured_at);
  await db.batch(venues.map(v=>db.prepare('INSERT OR IGNORE INTO live_venues(day,venue) VALUES(?,?)').bind(day,v)));return {state:'INDEX_SAVED',venues:venues.length};
 }
 if(job.kind==='VENUE'){
  need(job.day===day&&/^(0[1-9]|1\d|2[0-4])$/.test(job.venue),'VENUE_ID_INVALID');const claim=await read(db,"UPDATE live_venues SET lease_until=unixepoch('now')*1000+90000 WHERE day=? AND venue=? AND state!='DONE' AND lease_until<=unixepoch('now')*1000 RETURNING venue",day,job.venue);if(!claim)return {state:'VENUE_RESERVED_OR_DONE'};
  try{const p=await getPage(db,url('racelist',day,job.venue,1)),list=parseSchedule(p.html,day,job.venue);need(list.length===12,'VENUE_SCHEDULE_INCOMPLETE');
   await db.batch(list.map(r=>db.prepare('INSERT OR IGNORE INTO live_races(race_id,day,venue,race_no,cutoff_at,cutoff_ms,schedule_sha) VALUES(?,?,?,?,?,?,?)').bind(r.race_id,day,job.venue,r.race_no,r.cutoff_at,Date.parse(r.cutoff_at),p.sha)));
   await write(db,"UPDATE live_venues SET state='DONE',lease_until=0 WHERE day=? AND venue=?",day,job.venue);return {state:'VENUE_SCHEDULE_SAVED'};
  }catch(e){await write(db,'UPDATE live_venues SET lease_until=0,next_at=? WHERE day=? AND venue=?',Date.now()+300000,day,job.venue);throw e;}
 }
 if(job.kind==='REPLAY')return replayOne(db,job.race_id);
 need(/^\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$/.test(job.race_id),'RACE_ID_INVALID');if(!await leaseRace(db,job.race_id))return {state:'LEASE_HELD'};
 const race=await read(db,'SELECT * FROM live_races WHERE race_id=?',job.race_id),now=Date.now();
 try{
  const frozen=await read(db,'SELECT sha256 FROM live_freezes WHERE race_id=?',race.race_id),closed=now>race.cutoff_ms+180000;
  if(now+120000>=race.cutoff_ms&&!closed){await event(db,race.race_id,'FORECAST',frozen?'FROZEN_WAITING_RESULT':'DEADLINE_REACHED_WITHOUT_FREEZE');await finishStage(db,race.race_id,'RESULT',Math.max(1000,race.cutoff_ms+180000-now));return {state:'WAITING_RESULT'};}
  if(!race.program_json){
   const p=await getPage(db,url('racelist',race.day,race.venue,race.race_no));const current=parseSchedule(p.html,race.day,race.venue)[race.race_no-1];need(current.cutoff_at===race.cutoff_at,'OFFICIAL_CUTOFF_CHANGED');
   const roster=parseProgram(p.html,parseRacelist(p.html,race.day,race.venue,race.race_no));await write(db,'UPDATE live_races SET program_json=?,program_sha=?,program_captured_at=? WHERE race_id=?',JSON.stringify(roster),p.sha,p.captured_at,race.race_id);
   if(closed&&!frozen)await event(db,race.race_id,'FORECAST','STARTED_AFTER_CUTOFF_NO_BACKFILL');await finishStage(db,race.race_id,closed?'RESULT':'EXHIBITION');return {state:'PROGRAM_SAVED'};
  }
  if(closed){const p=await getPage(db,url('raceresult',race.day,race.venue,race.race_no));const detail=parseResultDetails(p.html,race.day,race.venue,race.race_no,JSON.parse(race.program_json));const fact={source_sha:p.sha,source_url:p.url,captured_at:p.captured_at,detail};const saved=await persistResult(db,race,fact);return {state:'RESULT_DB_VERIFIED',race_id:race.race_id,report_sha:saved.report_sha};}
  if(frozen){await finishStage(db,race.race_id,'RESULT',Math.max(1000,race.cutoff_ms+180000-now));return {state:'PREVIOUS_FREEZE_PRESERVED'};}
  need(now+120000<race.cutoff_ms,'CUTOFF_EXPIRED');
  const p=await getPage(db,url('beforeinfo',race.day,race.venue,race.race_no)),six=parseExhibition(p.html,race.day,race.venue,race.race_no,JSON.parse(race.program_json));
  const input={race_id:race.race_id,cutoff_at:race.cutoff_at,captured_at:p.captured_at,program_source_sha256:race.program_sha,beforeinfo_source_sha256:p.sha,boats:six.map(b=>({lane:b.lane,racer_id:b.registration_no,national_win_rate:b.national_win_rate,exhibition_time_seconds:b.exhibition_time_seconds,motor_two_place_rate_percent:b.motor_two_place_rate_percent}))};
  const computed=buildPair(input,iso()),saved=await persistPair(db,race,computed);await finishStage(db,race.race_id,'RESULT',Math.max(1000,race.cutoff_ms+180000-Date.now()));return {state:'AB_DB_FROZEN',race_id:race.race_id,saved_at:saved.db_saved_at};
 }catch(e){const reason=String(e.message||'UNKNOWN').replace(/[^A-Z0-9_]/g,'_').slice(0,100);await event(db,race.race_id,closed?'RESULT':race.stage,reason);await write(db,'UPDATE live_races SET lease_until=0,next_at=?,last_error=? WHERE race_id=?',Date.now()+(closed?180000:60000),reason,race.race_id);throw Error(reason);}
}
export async function runClock(env){
 if(env.BOAT_AUTO_ENABLED!=='true')return {state:'DISABLED'};need(env.BOAT_DB&&env.JOB&&env.INTERNAL_KEY,'BINDINGS_REQUIRED');const db=env.BOAT_DB,now=Date.now(),day=jstDay(new Date()),slot=Math.floor(now/60000);
 const mark=await read(db,"INSERT OR IGNORE INTO live_clock(slot,state) VALUES(?,'STARTED') RETURNING slot",slot);if(!mark)return {state:'DUPLICATE_TICK'};
 const send=async task=>{const r=await env.JOB.fetch('https://boat-internal/job',{method:'POST',headers:{'Content-Type':'application/json','X-RaceAI-Internal':env.INTERNAL_KEY},body:JSON.stringify(task)});need(r.ok,'JOB_FAILED');return r.json();};
 try{
  let tasks=[];const known=await read(db,'SELECT * FROM live_days WHERE day=?',day);
  if(!known){const hour=new Date(now+32400000).getUTCHours();if(hour>=5)tasks=[{kind:'INDEX',day}];}
  else{
   const pending=await rows(db,"SELECT venue FROM live_venues WHERE day=? AND state!='DONE' AND next_at<=? AND lease_until<=? ORDER BY venue LIMIT 4",day,now,now);
   const raceJobs=await chooseTasks(db,day);tasks=raceJobs.slice(0,pending.length?2:4).map(r=>({kind:'RACE',race_id:r.race_id}));
   for(const x of pending){if(tasks.length>=4)break;tasks.push({kind:'VENUE',day,venue:x.venue});}
   for(const r of raceJobs){if(tasks.length>=4)break;if(!tasks.some(t=>t.race_id===r.race_id))tasks.push({kind:'RACE',race_id:r.race_id});}
   if(tasks.length<4){const old=await rows(db,"SELECT r.race_id FROM live_races r WHERE r.day<? AND r.stage='DONE' AND NOT EXISTS(SELECT 1 FROM live_replays p WHERE p.race_id=r.race_id AND p.source_sha=r.result_sha AND p.replay_day=?) ORDER BY r.cutoff_ms LIMIT 4",day,day);for(const r of old){if(tasks.length>=4)break;tasks.push({kind:'REPLAY',race_id:r.race_id});}}
  }
  const result=await Promise.allSettled(tasks.slice(0,MAX_JOBS).map(send)),failed=result.filter(x=>x.status==='rejected').length;
  await write(db,"UPDATE live_clock SET completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),state=? WHERE slot=?",failed?'TASK_ERRORS':'OK',slot);return {state:failed?'TASK_ERRORS':'OK',task_count:tasks.length,failed};
 }catch(e){await write(db,"UPDATE live_clock SET completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),state='CLOCK_ERROR' WHERE slot=?",slot);await event(db,day,'CLOCK',String(e.message));throw e;}
}
export default {
 async fetch(request,env){if(env.ROLE!=='JOB'||request.method!=='POST'||new URL(request.url).pathname!=='/job'||!env.INTERNAL_KEY||request.headers.get('X-RaceAI-Internal')!==env.INTERNAL_KEY)return new Response('Not Found',{status:404});try{need(Number(request.headers.get('Content-Length')||0)<1024,'TASK_TOO_LARGE');const body=await request.text();need(body.length<1024,'TASK_TOO_LARGE');const result=await handleJob(env,JSON.parse(body));return Response.json(result,{headers:{'Cache-Control':'no-store'}});}catch(e){return Response.json({state:'SAFE_STOP',reason:String(e.message).slice(0,100)},{status:503,headers:{'Cache-Control':'no-store'}});}},
 async scheduled(event,env,ctx){if(env.ROLE!=='CLOCK')return;ctx.waitUntil(runClock(env).then(r=>console.log(JSON.stringify(r))).catch(e=>console.error('BOAT_RUNTIME_SAFE_STOP',String(e.message).slice(0,100))));}
};
