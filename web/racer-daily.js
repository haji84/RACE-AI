/* Daily official-source descriptive aggregates. Never changes saved forecasts. */
'use strict';
(()=>{
 const embedded = null;
 const official=typeof module==='object'&&module.exports?require('./racer-profiles.js'):globalThis.RaceRacerProfiles;
 const need=ok=>{if(!ok)throw new Error('DAILY_REFERENCE_INVALID');};
 const freeze=v=>{if(v&&typeof v==='object'&&!Object.isFrozen(v)){Object.values(v).forEach(freeze);Object.freeze(v);}return v;};
 const day=v=>typeof v==='string'&&/^\d{4}-\d\d-\d\d$/.test(v)&&Number.isFinite(Date.parse(v+'T00:00:00Z'))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
 const time=v=>typeof v==='string'&&/T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v));
 const n=v=>Number.isSafeInteger(v)&&v>=0&&v<=1000000;
 function metric(r){
  need(r&&['starts','wins','seconds','thirds','st_samples','confirmed_absences','unknown_course_starts'].every(k=>n(r[k])));
  need(r.wins+r.seconds+r.thirds<=r.starts&&r.st_samples<=r.starts&&r.unknown_course_starts<=r.starts);
  for(const [field,count] of [['win_percent',r.wins],['top2_percent',r.wins+r.seconds],['top3_percent',r.wins+r.seconds+r.thirds]])need(r.starts?Number.isFinite(r[field])&&Math.abs(r[field]-count/r.starts*100)<1e-6:r[field]===null);
  need(r.st_samples?Number.isFinite(r.average_st)&&r.average_st>=0&&r.average_st<=2:r.average_st===null);
  need(r.dispositions&&typeof r.dispositions==='object'&&!Array.isArray(r.dispositions)&&Object.entries(r.dispositions).every(([k,v])=>k.length<=24&&n(v)));
 }
 function parse(raw){
  need(raw?.schema==='RACE_AI_RACER_DAILY_V1');
  if(raw.status==='UNAVAILABLE'){need(Array.isArray(raw.people)&&!raw.people.length);return null;}
  need(raw.status==='READY'&&raw.model_inputs_changed===false&&time(raw.generated_at)&&time(raw.last_source_at)&&Date.parse(raw.last_source_at)<=Date.parse(raw.generated_at));
  const p=raw.period;need(p&&p.days===90&&day(p.start)&&day(p.end));
  const generatedDay=new Date(Date.parse(raw.generated_at)+9*3600000).toISOString().slice(0,10);
  need(Date.parse(p.end+'T00:00:00Z')-Date.parse(p.start+'T00:00:00Z')===89*86400000&&new Date(Date.parse(generatedDay+'T00:00:00Z')-86400000).toISOString().slice(0,10)===p.end);
  const c=raw.coverage;need(c&&n(c.parsed_days)&&n(c.missing_days_count)&&c.parsed_days+c.missing_days_count===90&&Array.isArray(c.missing_days)&&c.missing_days.length===c.missing_days_count&&new Set(c.missing_days).size===c.missing_days.length);
  need(c.missing_days.every(d=>day(d)&&d>=p.start&&d<=p.end)&&Array.isArray(c.partial_days)&&c.partial_days.length<=c.parsed_days&&typeof c.complete==='boolean'&&c.complete===(!c.missing_days_count&&!c.partial_days.length));
  const source=raw.source;need(source?.url==='https://www1.mbrace.or.jp/od2/K/dmenu.html'&&/^[a-f0-9]{64}$/.test(source.sha256)&&Array.isArray(source.receipts)&&source.receipts.length===c.parsed_days);
  const present=new Set();for(const r of source.receipts){need(day(r.day)&&r.day>=p.start&&r.day<=p.end&&!present.has(r.day)&&!c.missing_days.includes(r.day)&&/^[a-f0-9]{64}$/.test(r.sha256)&&time(r.captured_at)&&Date.parse(r.captured_at)<=Date.parse(raw.generated_at));need(r.url==='https://www1.mbrace.or.jp/od2/K/'+r.day.slice(0,7).replace('-','')+'/k'+r.day.slice(2).replaceAll('-','')+'.lzh');present.add(r.day);}
  need(c.partial_days.every(r=>present.has(r.day)&&Array.isArray(r.venues)&&r.venues.length<=24&&new Set(r.venues).size===r.venues.length&&r.venues.every(v=>typeof v==='string'&&/^(0[1-9]|1[0-9]|2[0-4])$/.test(v))));
  need(Array.isArray(raw.cohort_top2_percent)&&raw.cohort_top2_percent.length===6&&raw.cohort_top2_percent.every(v=>v===null||Number.isFinite(v)&&v>=0&&v<=100));
  need(Array.isArray(raw.people)&&raw.people.length>0&&raw.people.length<=10000);
  const refs=new Map((official?.all||[]).map(r=>[r.registration,r])),by=new Map();
  for(const r of raw.people){
   need(/^[0-9]{4}$/.test(r.registration)&&!by.has(r.registration)&&typeof r.name==='string'&&r.name.length>0&&r.name.length<=128);metric(r.summary);
   need(Array.isArray(r.courses)&&r.courses.length===6&&r.courses.every((v,i)=>v.course===i+1));r.courses.forEach(metric);
   for(const k of ['starts','wins','seconds','thirds','st_samples'])need(r.courses.reduce((s,v)=>s+v[k],0)<=r.summary[k]);
   const ref=refs.get(r.registration);by.set(r.registration,ref&&ref.name===r.name?freeze({...ref,daily:r,term:{...r.summary,courses:r.courses}}):null);
  }
  freeze(raw);return Object.freeze({data:raw,period:raw.period,source:raw.source,baselines:raw.cohort_top2_percent,capturedAt:raw.generated_at,
   get(race,person){const identity=official?.get(race,person);return identity?by.get(identity.registration)||null:null;}});
 }
 let current=null,inflight=null,state='LOADING',lastAttempt=0;
 async function read(response){
  need(response.ok);const reader=response.body.getReader(),chunks=[];let total=0;
  try{for(;;){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;need(total<=4*1024*1024);chunks.push(value);}}catch(e){await reader.cancel().catch(()=>{});throw e;}
  const raw=new Uint8Array(total);let at=0;for(const v of chunks){raw.set(v,at);at+=v.byteLength;}return JSON.parse(new TextDecoder().decode(raw));
 }
 function load({refresh=false}={}){
  if(inflight)return inflight;
  if(!refresh&&state!=='LOADING')return Promise.resolve(current);
  lastAttempt=Date.now();inflight=(async()=>{
   try{const next=parse(embedded!==null?embedded:await read(await fetch('./data/racer-daily.json',{credentials:'same-origin',cache:'no-store'})));if(next)current=next;state=next?'READY':'UNAVAILABLE';}
   catch{state=current?'STALE':'UNAVAILABLE';}
   finally{inflight=null;if(typeof window!=='undefined')window.dispatchEvent(new Event('race-ai-daily-updated'));}
   return current;
  })();return inflight;
 }
 const api=Object.freeze({parse,load,get:(race,person)=>current?.get(race,person)||null,get data(){return current?.data||null;},get period(){return current?.period;},get baselines(){return current?.baselines;},get source(){return current?.source;},get capturedAt(){return current?.capturedAt;},get status(){return state;},offline:embedded!==null});
 if(typeof module==='object'&&module.exports)module.exports=api;
 else{globalThis.RaceRacerDaily=api;const refresh=()=>{if(!document.hidden&&embedded===null&&Date.now()-lastAttempt>30*60000)load({refresh:true});};document.addEventListener('visibilitychange',refresh);setInterval(refresh,30*60000);}
})();
