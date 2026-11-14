/* Invented daily statistics; named identities only exercise binding, not real performance. */
'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
let D;try{D=require('../web/racer-daily.js');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
const {fixture}=require('./racer_daily_fixture.cjs');
test('daily reference is identity-bound and separates measured rates from term point rating',()=>{
 assert.ok(D,'daily public aggregates must reach athlete cards');const api=D.parse(fixture()),race={sport:'boat',scope:'research',event_date_jst:'2026-11-07'},p={registration_no:'4320',name:'峰竜太',number:1};
 assert.equal(api.get(race,p).daily.summary.win_percent,40);assert.equal(api.get(race,p).term.win_rate,undefined);
 assert.equal(api.get({...race,scope:'synthetic'},p),null);assert.equal(api.get(race,{...p,name:'別人'}),null);
 assert.equal(Object.isFrozen(api.get(race,p).daily.courses[0]),true);
});
test('malformed or contradictory daily rates and periods never become player information',()=>{
 assert.ok(D);for(const mutate of [d=>d.people[0].courses[0].top2_percent=100,d=>d.period.end='2026-11-07',d=>d.people.push(d.people[0]),d=>d.people[0].courses[0].st_samples=21,d=>d.people[0].courses[0].average_st=null,d=>d.model_inputs_changed=true]){const d=fixture();mutate(d);assert.throws(()=>D.parse(d));}
 assert.equal(D.parse({schema:'RACE_AI_RACER_DAILY_V1',status:'UNAVAILABLE',people:[]}),null);
});
test('daily course scenarios use daily samples and keep the historical cutoff',()=>{
 assert.ok(D);const api=D.parse(fixture()),P=require('../web/racer-profiles.js'),race={sport:'boat',scope:'research',event_date_jst:'2026-11-07',participants:[]},p={registration_no:'4320',name:'峰竜太',number:1};
 assert.equal(P.scenario(race,p,1,{referenceApi:api}).stats.starts,20);
 assert.equal(P.scenario({...race,event_date_jst:'2026-11-06'},p,1,{referenceApi:api}).status,'HISTORICAL_REFERENCE');
 assert.equal(P.preferredCourses(api.get(race,p),{baselines:api.baselines}).courses[0].course,6);
});
test('published daily data uses the existing GitHub delivery path and never includes private link fragments',()=>{
 assert.equal(typeof D.endpoint,'function');
 const target=D.endpoint({origin:'https://haji84.github.io',pathname:'/RACE-AI/',hash:'#saved=PRIVATE_LINK'});
 assert.equal(target,'https://raw.githubusercontent.com/haji84/RACE-AI/gh-pages/data/racer-daily.json');assert.doesNotMatch(target,/PRIVATE_LINK/);
 assert.equal(D.endpoint({origin:'http://127.0.0.1:3000',pathname:'/'}),'./data/racer-daily.json');
});
test('same-day result updates use explicit course statistics and are usable only before the later race cutoff',()=>{
 const raw=require('./racer_daily_fixture.cjs').liveFixture();let api;try{api=D.parse(raw);}catch{}
 assert.ok(api,'per-race catalogue must reach the next same-day athlete card');
 const P=require('../web/racer-profiles.js'),p={registration_no:'4320',name:'峰竜太',number:1},race={sport:'boat',scope:'research',event_date_jst:'2026-11-07',cutoff_at:'2026-11-07T12:00:00+09:00',participants:[]};
 assert.equal(api.get(race,p).daily.summary.starts,121);assert.equal(api.get(race,p).daily.courses[1].starts,21);
 assert.equal(P.scenario(race,p,2,{referenceApi:api}).stats.starts,21);
 assert.equal(P.scenario({...race,cutoff_at:'2026-11-07T10:00:00+09:00'},p,2,{referenceApi:api}).status,'HISTORICAL_REFERENCE');
 assert.equal(P.scenario({...race,cutoff_at:null},p,2,{referenceApi:api}).status,'CUTOFF_UNKNOWN');
});
test('live coverage and row provenance contradictions are rejected',()=>{
 const {liveFixture}=require('./racer_daily_fixture.cjs');
 for(const mutate of [d=>d.today.confirmed_races=13,d=>d.people[0].today_races[0].race_id='20261108-01-01',d=>d.today.source_receipts[0].url='https://outside.invalid/private',d=>d.people[0].today_stats.starts=2]){const d=liveFixture();mutate(d);assert.throws(()=>D.parse(d));}
});
test('small status checks avoid unchanged full downloads and reject a mismatched aggregate hash',async t=>{
 const entry=require.resolve('../web/racer-daily.js');delete require.cache[entry];const api=require(entry),{createHash}=require('node:crypto');
 let data=require('./racer_daily_fixture.cjs').liveFixture(),text=JSON.stringify(data)+'\n',hash=createHash('sha256').update(text).digest('hex'),calls=[];
 let pointer={schema:'RACE_AI_RACER_STATISTICS_STATUS_V1',catalogue_sha256:hash,catalogue_generated_at:data.generated_at,checked_at:data.generated_at,state:'READY'};
 t.mock.method(globalThis,'fetch',async url=>{calls.push(String(url));return new Response(String(url).includes('racer-live-status')?JSON.stringify(pointer):text);});
 await api.load();assert.equal(api.data?.schema,'RACE_AI_RACER_DAILY_V2');
 await api.load({refresh:true});assert.equal(calls.filter(v=>v.includes('racer-daily.json')).length,1,'unchanged status must not redownload all profiles');
 pointer={...pointer,catalogue_sha256:'0'.repeat(64)};await api.load({refresh:true});
 assert.equal(api.status,'STALE');assert.equal(api.data.people[0].summary.starts,121,'mismatched public delivery keeps the last good card');
});
test('an unavailable legacy response preserves the last good data as stale',async t=>{
 const entry=require.resolve('../web/racer-daily.js');delete require.cache[entry];const api=require(entry);
 let data=fixture();t.mock.method(globalThis,'fetch',async url=>String(url).includes('racer-live-status')?new Response('',{status:404}):new Response(JSON.stringify(data)));
 await api.load();assert.equal(api.status,'READY');
 data={schema:'RACE_AI_RACER_DAILY_V1',status:'UNAVAILABLE',people:[]};await api.load({refresh:true});
 assert.equal(api.status,'STALE');assert.equal(api.data.people[0].summary.starts,120);
});
test('an older valid public pointer cannot replace a newer card or heartbeat',async t=>{
 const entry=require.resolve('../web/racer-daily.js');delete require.cache[entry];const api=require(entry),{createHash}=require('node:crypto');
 let data=require('./racer_daily_fixture.cjs').liveFixture(),text=JSON.stringify(data),pointer={schema:'RACE_AI_RACER_STATISTICS_STATUS_V1',catalogue_sha256:createHash('sha256').update(text).digest('hex'),catalogue_generated_at:data.generated_at,checked_at:data.generated_at,state:'READY'},fullCalls=0;
 t.mock.method(globalThis,'fetch',async url=>{if(String(url).includes('racer-live-status'))return new Response(JSON.stringify(pointer));fullCalls++;return new Response(text);});
 await api.load();const first=api.data,original=pointer;
 data=fixture();data.generated_at='2026-11-07T01:59:00Z';text=JSON.stringify(data);pointer={...pointer,catalogue_sha256:createHash('sha256').update(text).digest('hex'),catalogue_generated_at:data.generated_at};
 await api.load({refresh:true});assert.equal(api.status,'STALE');assert.equal(api.data,first);assert.equal(fullCalls,1);
 pointer={...original,checked_at:'2026-11-07T02:10:00Z'};await api.load({refresh:true});assert.equal(api.status,'READY');
 pointer=original;await api.load({refresh:true});assert.equal(api.status,'STALE');assert.equal(api.heartbeat.checked_at,'2026-11-07T02:10:00Z');
});
test('result sync counts from the small pointer are validated before the normal screen can show them',async t=>{
 const entry=require.resolve('../web/racer-daily.js');delete require.cache[entry];const api=require(entry),{createHash}=require('node:crypto');
 const data=require('./racer_daily_fixture.cjs').liveFixture(),text=JSON.stringify(data),sync={schema:'RACE_AI_RESULT_SYNC_V1',state:'READY',checked_at:data.generated_at,races:1,confirmed:1,pending:0,held:0,changed_races:1};
 let pointer={schema:'RACE_AI_RACER_STATISTICS_STATUS_V1',catalogue_sha256:createHash('sha256').update(text).digest('hex'),catalogue_generated_at:data.generated_at,checked_at:data.generated_at,state:'READY',result_sync:sync};
 t.mock.method(globalThis,'fetch',async url=>new Response(String(url).includes('racer-live-status')?JSON.stringify(pointer):text));await api.load();assert.equal(api.heartbeat.result_sync.confirmed,1);
 pointer={...pointer,result_sync:{...sync,confirmed:2}};await api.load({refresh:true});assert.equal(api.status,'STALE');assert.equal(api.heartbeat.result_sync.confirmed,1);
});
