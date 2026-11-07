'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../scripts/official_result_browser_capture.cjs');
const item={sport:'autorace',race_id:'autorace:2030-01-01:isesaki:1',expected_date:'2030-01-01',venue:'isesaki',race_no:1,ui_entry_url:'https://autorace.jp/race_info/Live/isesaki',place_code:3};
function page({url='https://autorace.jp/race_info/Live/isesaki/Program/2030-01-01_12/program',current=true,domDate='2030-01-01',visible=true,count=1}={}){
 const calls=[],ledger=[];const target={url:()=>url,waitForLoadState:async()=>{},waitForTimeout:async()=>{},locator(selector){
  const isDate=selector.includes('data-period-date'),isRace=selector.includes('data-raceno'),anchor=selector.endsWith(' a');
  const node={count:async()=>isDate?count:1,isVisible:async()=>isDate?visible:true,waitFor:async()=>{},
   getAttribute:async name=>name==='class'?(current?'liveTabMenu__item liveTabMenu__item--current':'liveTabMenu__item'):name==='data-period-date'?domDate:null,
   innerText:async()=>isDate?'初日':isRace?'1R':'レース結果',click:async()=>calls.push(isDate?'date':isRace?'race':'result'),last:()=>node};return node;
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
