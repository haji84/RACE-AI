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
