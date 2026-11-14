'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const data=require('../web/racer-profiles-data.js');
let P;try{P=require('../web/racer-profiles.js');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
const entries=[['4320','峰竜太'],['3415','松井繁'],['3897','白井英治'],['3941','池田浩二'],['4238','毒島誠'],['4444','桐生順平']];
const race=()=>({sport:'boat',scope:'research',event_date_jst:'2030-01-01',participants:entries.map(([registration_no,name],i)=>({number:i+1,registration_no,name}))});
test('a name-and-registration-only participant receives actual official six-course data',()=>{
  assert.ok(P,'the official athlete reference API must be connected');
  const r=race(),before=JSON.stringify(r),profile=P.get(r,r.participants[0]);
  assert.equal(profile.term.win_rate,8.05);assert.equal(profile.term.starts,105);assert.equal(profile.term.courses.length,6);
  assert.equal(profile.term.courses[3].starts,19);assert.ok(Math.abs(profile.term.courses[3].top3_percent-84.21052631578947)<1e-8);
  assert.equal(JSON.stringify(r),before);assert.equal(Object.isFrozen(profile.term.courses[0]),true);
  for(const p of data.people)assert.equal(P.get(r,{registration_no:p.registration,name:p.name}).registration,p.registration);
});
test('reference profiles preserve portrait identity and synthetic/other-sport isolation',()=>{
  const r=race(),p=r.participants[0];
  for(const [row,person] of [[{...r,scope:'synthetic'},p],[{...r,sport:'horse'},p],[r,{...p,name:'別の選手'}],[r,{...p,racer_id:'3415'}]])assert.equal(P.get(row,person),null);
});
test('preferred courses require samples and compare against the same-course cohort',()=>{
  const profile={term:{courses:[{course:1,starts:20,top2_percent:70},{course:2,starts:20,top2_percent:70},{course:3,starts:1,top2_percent:100}]}};
  const preferred=P.preferredCourses(profile);assert.equal(preferred.basis,'COHORT_ADJUSTED');
  assert.equal(preferred.courses[0].course,2);assert.equal(preferred.courses.some(c=>c.course===3),false);
  assert.deepEqual(P.preferredCourses({term:null}).courses,[]);
});
test('course scenarios use measured values and named adjacent opponents without changing originals',()=>{
  const r=race(),before=JSON.stringify(r),s=P.scenario(r,r.participants[0],1);
  assert.equal(s.status,'READY');assert.equal(s.basis,'FRAME_ASSUMPTION');assert.equal(s.stats.starts,26);
  assert.ok(s.path.includes('逃げ'));assert.ok(s.comparisons.some(p=>p.registration==='3415'&&p.course===2));
  assert.equal(Object.hasOwn(s,'probability'),false);assert.equal(Object.hasOwn(s,'ordered_top8'),false);assert.equal(JSON.stringify(r),before);
  const alternate=P.scenario(r,r.participants[0],4);assert.equal(alternate.basis,'HYPOTHETICAL');assert.deepEqual(alternate.comparisons,[]);
  const shown=P.scenario(r,r.participants[0],2,{entryMap:{1:2,2:1,3:3,4:4,5:5,6:6}});
  assert.equal(shown.basis,'EXHIBITION');assert.ok(shown.comparisons.some(p=>p.registration==='3415'&&p.course===1));
});
test('scenarios reject entry conflicts and unavailable samples and avoid hindsight forecasts',()=>{
  const r=race(),p=r.participants[0];
  assert.equal(P.scenario(r,p,1,{entryMap:{1:1,2:1,3:3,4:4,5:5,6:6}}).status,'ENTRY_CONFLICT');
  assert.equal(P.scenario({...r,event_date_jst:'2026-01-01'},p,1).status,'HISTORICAL_REFERENCE');
  assert.equal(P.scenario(r,{registration_no:'5497',name:'藤山芽依',number:6},6).status,'NO_TERM');
  assert.equal(P.scenario(r,{...p,entry_status:'withdrawn'},1).status,'WITHDRAWN');
  assert.deepEqual(P.scenario({...r,participants:r.participants.slice(0,2)},p,1).comparisons,[]);
});
test('partial entry evidence never invents named neighbors and keeps the selected course explanation',()=>{
  const r=race(),p=r.participants[0];r.participants[1].preview_course=3;
  for(const options of [undefined,{entryMap:{2:3}}]){
    const result=P.scenario(r,p,1,options);
    assert.equal(result.status,'READY');assert.equal(result.entryStatus,'PARTIAL');
    assert.equal(result.basis,'HYPOTHETICAL');assert.deepEqual(result.comparisons,[]);
    assert.match(result.path,/逃げ/);assert.equal(result.stats.starts,26);assert.match(result.entryMessage,/一部/);
  }
  const conflict=P.scenario(r,p,1,{entryMap:{1:1,2:1,3:3,4:4,5:5,6:6}});
  assert.equal(conflict.status,'ENTRY_CONFLICT');assert.equal(conflict.entryStatus,'CONFLICT');
  assert.deepEqual(conflict.comparisons,[]);assert.match(conflict.path,/逃げ/);assert.equal(conflict.stats.starts,26);
});
