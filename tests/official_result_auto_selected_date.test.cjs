'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../scripts/official_result_browser_capture.cjs');
const item={sport:'autorace',race_id:'autorace:2030-01-01:isesaki:1',expected_date:'2030-01-01',venue:'isesaki',race_no:1,ui_entry_url:'https://autorace.jp/race_info/Live/isesaki',place_code:3};
function page({url='https://autorace.jp/race_info/Live/isesaki/Program/2030-01-01_12/program',current=true,domDate='2030-01-01',visible=true,count=1}={}){
 const req={url:()=> 'https://autorace.jp/race_info/OtherRaceInfo',method:()=> 'POST',resourceType:()=> 'xhr',postDataBuffer:()=>Buffer.from(JSON.stringify({placeCode:3,raceDate:item.expected_date,raceNo:1})),headers:()=>({'content-type':'application/json'})};
 const response={request:()=>req,url:()=>req.url(),status:()=>200,finished:async()=>{}};
 const calls=[],ledger=[];const target={url:()=>url,waitForResponse:async predicate=>{assert.equal(predicate(response),true);return response;},waitForLoadState:async()=>{},waitForTimeout:async()=>{},locator(selector){
  const isDate=selector.includes('data-period-date'),isRace=selector.includes('data-raceno'),anchor=selector.endsWith(' a');
  const node={count:async()=>isDate?count:1,isVisible:async()=>isDate?visible:true,waitFor:async()=>{},
   getAttribute:async name=>name==='class'?(current?'liveTabMenu__item liveTabMenu__item--current':'liveTabMenu__item'):name==='data-period-date'?domDate:null,
   innerText:async()=>isDate?'初日':isRace?'1R':selector.includes('data-main-menu="program"')?'出走表':'レース結果',click:async()=>calls.push(isDate?'date':isRace?'race':selector.includes('data-main-menu="program"')?'program':'result'),last:()=>node};return node;
 }};return {target,calls,ledger};
}
test('already selected published day avoids refresh while still selecting target race and result by visible UI',async()=>{
 const f=page();await api.selectAutoCase(f.target,item,f.ledger);
 assert.deepEqual(f.calls,['race','result']);assert.equal(f.ledger.filter(e=>e.event==='NORMAL_SEMANTIC_UI_CLICK').length,2);
 assert.equal(f.ledger.filter(e=>e.event==='ALREADY_SELECTED_UI_DATE').length,1);
});
test('URL and visible current DOM must independently agree before skipping the date control',async()=>{
 for(const change of [{current:false},{domDate:'2029-12-31'},{visible:false},{count:2},
  {url:'https://autorace.jp/race_info/Live/isesaki/Program/2029-12-31_12/program'},
  {url:'https://autorace.jp/race_info/Live/kawaguchi/Program/2030-01-01_12/program'},
  {url:'https://www.autorace.jp/race_info/Live/isesaki/Program/2030-01-01_12/program'},
  {url:'https://foreign.invalid/race_info/Live/isesaki/Program/2030-01-01_12/program'},
  {url:'https://autorace.jp/race_info/Live/isesaki'},
  {url:'https://autorace.jp/race_info/Live/isesaki/Program/2030-01-01_12/program?token=forbidden'},
  {url:'https://autorace.jp/race_info/Live/isesaki/Program/2030-01-01_12/result'}]){
  const f=page(change);
  if(change.visible===false||change.count===2){await assert.rejects(api.selectAutoCase(f.target,item,f.ledger));assert.deepEqual(f.calls,[]);}
  else{await api.selectAutoCase(f.target,item,f.ledger);assert.deepEqual(f.calls,['date','race','result']);}
 }
});
test('a current result day also skips date refresh when choosing the next explicit race',async()=>{
 const f=page({url:'https://autorace.jp/race_info/Live/isesaki/RaceResult/2030-01-01_12/result'});
 await api.selectAutoCase(f.target,item,f.ledger);assert.deepEqual(f.calls,['race','result']);
});
test('day idempotence never grants mismatched read identities or alters literal POST bytes',()=>{
 const body=Buffer.from(JSON.stringify({placeCode:3,raceDate:'2030-01-01',raceNo:12})),before=Buffer.from(body);
 const policy=api.routePolicy({url:'https://autorace.jp/race_info/Program',method:'POST',resource_type:'xhr',body,content_type:'application/json',headers:{}},{cases:[item]});
 assert.equal(policy.allow,false);assert.equal(policy.reason,'OFFICIAL_BROWSER_NORMAL_READ_IDENTITY');assert.deepEqual(body,before);
});
test('SPA target identity response completes before the result click changes menus',async()=>{
 let resolveIdentity,identityComplete=false,registered=false;const f=page();const baseLocator=f.target.locator;
 const req={url:()=> 'https://autorace.jp/race_info/OtherRaceInfo',method:()=> 'POST',resourceType:()=> 'xhr',postDataBuffer:()=>Buffer.from('{"placeCode":3,"raceDate":"2030-01-01","raceNo":"1"}'),headers:()=>({'content-type':'application/json'})};
 const response={url:()=>req.url(),request:()=>req,status:()=>200,finished:async()=>{identityComplete=true;}};
 f.target.waitForResponse=(predicate,options)=>{registered=true;assert.equal(options.timeout,12000);assert.equal(predicate({...response,request:()=>({...req,postDataBuffer:()=>Buffer.from('{"placeCode":3,"raceDate":"2030-01-01","raceNo":12}')})}),false);assert.equal(predicate({...response,request:()=>({...req,headers:()=>({'content-type':'application/json',authorization:'synthetic-private-header'})})}),false);assert.equal(predicate(response),true);return new Promise(resolve=>{resolveIdentity=()=>resolve(response);});};
 f.target.locator=selector=>{const node=baseLocator(selector),old=node.click;node.click=async()=>{if(selector.includes('data-raceno')){assert.equal(registered,true);queueMicrotask(resolveIdentity);}if(selector.includes('data-main-menu'))assert.equal(identityComplete,true);await old();};return node;};
 await api.selectAutoCase(f.target,item,f.ledger);assert.equal(identityComplete,true);assert.deepEqual(f.calls,['race','result']);
});
test('Program intent in Result menu returns through visible Program before waiting for its identity',async()=>{
 const next={...item,race_no:2,race_id:'autorace:2030-01-01:isesaki:2'};
 let menu='result',resolveIdentity,complete=false;const calls=[];const req={url:()=> 'https://autorace.jp/race_info/OtherRaceInfo',method:()=> 'POST',resourceType:()=> 'xhr',postDataBuffer:()=>Buffer.from('{"placeCode":3,"raceDate":"2030-01-01","raceNo":"2"}'),headers:()=>({'content-type':'application/json'})};
 const response={request:()=>req,url:()=>req.url(),status:()=>200,finished:async()=>{complete=true;}};
 const target={url:()=> 'https://autorace.jp/race_info/Live/isesaki/'+(menu==='result'?'RaceResult/2030-01-01_1/result':'Program/2030-01-01_1/program'),
  waitForLoadState:async()=>{},waitForResponse:predicate=>new Promise((resolve,reject)=>{resolveIdentity=()=>{if(menu!=='program')reject(Error('result menu produces Result instead of Other'));else if(predicate(response))resolve(response);else reject(Error('target identity mismatch'));};}),locator(selector){
   const program=selector.includes('data-main-menu="program"'),result=selector.includes('data-main-menu="result"'),race=selector.includes('data-raceno'),date=selector.includes('data-period-date');
   const node={last:()=>node,count:async()=>1,isVisible:async()=>true,waitFor:async()=>{},getAttribute:async k=>k==='class'?'liveTabMenu__item--current':'2030-01-01',innerText:async()=>program?'出走表':result?'レース結果':race?'2R':'初日',click:async()=>{if(program){menu='program';calls.push('program');}else if(race){calls.push('race');queueMicrotask(resolveIdentity);}else if(result){assert.equal(complete,true);menu='result';calls.push('result');}else if(date)calls.push('date');}};return node;
  }};
 await api.selectAutoProgram(target,next,[]);assert.deepEqual(calls,['program','race']);assert.equal(complete,true);
});

test('a failed identity response body holds before any result menu action',async()=>{
 const f=page(),req={url:()=> 'https://autorace.jp/race_info/OtherRaceInfo',method:()=> 'POST',resourceType:()=> 'xhr',postDataBuffer:()=>Buffer.from('{"placeCode":3,"raceDate":"2030-01-01","raceNo":1}'),headers:()=>({'content-type':'application/json'})};
 f.target.waitForResponse=async predicate=>{const response={request:()=>req,url:()=>req.url(),status:()=>200,finished:async()=>Error('invented incomplete body')};assert.equal(predicate(response),true);return response;};
 await assert.rejects(api.selectAutoCase(f.target,item,f.ledger),/IDENTITY_RESPONSE_INCOMPLETE/);assert.deepEqual(f.calls,['race']);
});
