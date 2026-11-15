'use strict';
// Authored visible controls only. No browser, provider, key or source bytes.
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../scripts/official_result_browser_capture.cjs');
const item={sport:'keirin',race_id:'keirin:2030-01-15:keirin-jyo-48:2',expected_date:'2030-01-15',venue:'keirin-jyo-48',race_no:2,ui_entry_url:'https://keirin.jp/pc/top'};
function fixture({venue='48',day='20300115',detailVenue='48',detailDay='20300115',heading='2R 創作競走',dateWorks=true}={}){
 const calls=[],ledger=[];let popupListener;const detail={url:()=> 'https://keirin.jp/pc/racelive',waitForLoadState:async()=>{},locator(selector){const node={inputValue:async()=>selector==='#hhSelJ'?detailVenue:detailDay,innerText:async()=>selector==='#hhLblRaceDtl'?heading:'競走結果',count:async()=>1,isVisible:async()=>true,click:async()=>{assert.equal(selector,'#rcbtn8');calls.push('result');}};return node;}};
 const page={url:()=> 'https://keirin.jp/pc/racelist',on:(_event,listener)=>{popupListener=listener;},off:()=>{},waitForLoadState:async()=>{},waitForTimeout:async()=>{},locator(selector){
  assert.notEqual(selector,'#hhbtnResultList','unneeded result-list helper must not be selected');
  if(selector==='#hhSelJ'||selector==='#hhSelK')return {inputValue:async()=>selector==='#hhSelJ'?venue:day};
  const node={filter:()=>node,count:async()=>1,isVisible:async()=>true,innerText:async()=>selector.includes('hhlnkRaceDate')?'1/15':'2R',click:async()=>{if(selector.includes('hhlnkRaceDate')){calls.push('date');if(dateWorks)day='20300115';}else{assert.equal(selector,'#hhRaceBtn2');calls.push('card');popupListener(detail);}}};return node;
 }};return {page,detail,calls,ledger};
}
test('result mode reuses the exact normal card then result tab without selecting result list',async()=>{
 const f=fixture(),before=structuredClone(item);assert.equal(await api.selectKeirinCase(f.page,item,f.ledger),f.detail);
 assert.deepEqual(f.calls,['card','result']);assert.deepEqual(f.ledger.map(e=>e.label),['2R','競走結果']);assert.deepEqual(item,before);
 assert.ok(f.ledger.every(e=>e.event==='NORMAL_SEMANTIC_UI_CLICK'));
});
test('the shared card selector still verifies full date venue and race before result',async()=>{
 const f=fixture({day:'20300116'});await api.selectKeirinCase(f.page,item,f.ledger);assert.deepEqual(f.calls,['date','card','result']);
 for(const options of [{venue:'47'},{day:'20300116',dateWorks:false},{detailVenue:'47'},{detailDay:'20300116'},{heading:'3R 創作競走'}]){
  const bad=fixture(options);await assert.rejects(api.selectKeirinCase(bad.page,item,bad.ledger));assert.equal(bad.calls.includes('result'),false);
 }
});
test('future card intent never selects the result tab and retains result transport guards',async()=>{
 const f=fixture();assert.equal(await api.selectKeirinCard(f.page,item,f.ledger),f.detail);assert.deepEqual(f.calls,['card']);
 const future={cases:[item],intent:'CAPTURE_FRESH_NATIVE_FUTURE_CARDS'};
 for(const kind of ['JSJ012','JSJ048'])assert.equal(api.futureRoutePolicy({url:'https://keirin.jp/pc/json?encp=authored&type='+kind,method:'GET',resource_type:'xhr',headers:{},body:Buffer.alloc(0)},future).allow,false);
});
