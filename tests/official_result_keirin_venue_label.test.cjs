'use strict';
// Invented DOM labels only; no browser, actual source, owner key, or HTTP.
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../scripts/official_result_browser_capture.cjs');
const item={sport:'keirin',race_id:'keirin:2030-01-01:keirin-jyo-48:2',expected_date:'2030-01-01',venue:'keirin-jyo-48',race_no:2,ui_venue_name:'四日市競輪場',ui_entry_url:'https://keirin.jp/pc/top'};
function fixture(labels){
 const calls=[],before=structuredClone(labels),page={url:()=>item.ui_entry_url,on(){},off(){},waitForLoadState:async()=>{},waitForTimeout:async()=>{},locator(selector){
  if(selector==='.kaisaichi'||selector==='.kaisaichi:visible')return {filter:({hasText})=>{
   const matched=labels.filter(label=>(selector!=='.kaisaichi:visible'||label.visible!==false)&&hasText.test(label.text));
   return {matched,count:async()=>matched.length};
  }};
  assert.equal(selector,'#kaisaiInfoTable tr');return {filter:({has})=>({waitFor:async()=>{if(has.matched.length!==1)throw Error('invented venue missing or ambiguous');},getByRole:(_role,{name})=>({count:async()=>has.matched.length,isVisible:async()=>true,innerText:async()=>'出走表一覧',click:async()=>{assert.ok(name.test('出走表一覧'));calls.push(has.matched[0].text);}})})};
 }};return {page,calls,before};
}
test('a signed full venue label selects the exact visible published suffix-free label without changing the item',async()=>{
 for(const text of ['四日市','四日市競輪場']){const labels=[{text}],f=fixture(labels),before=structuredClone(item),ledger=[];assert.equal(await api.openKeirinList(f.page,item,ledger),f.page);assert.deepEqual(f.calls,[text]);assert.deepEqual(item,before);assert.deepEqual(labels,f.before);assert.equal(ledger[0].event,'NORMAL_SEMANTIC_UI_CLICK');}
});
test('venue label matching rejects prefixes substrings additional text empty labels and ambiguous candidates',async()=>{
 for(const labels of [[{text:'新四日市'}],[{text:'四日市競輪場追加'}],[{text:'四日市競輪'}],[{text:''}],[{text:'四日市'},{text:'四日市競輪場'}],[{text:'四日市'},{text:'四日市'}]]){const f=fixture(labels);await assert.rejects(api.openKeirinList(f.page,item,[]));assert.deepEqual(f.calls,[]);}
 for(const name of ['', '競輪場','四日市競輪場競輪場']){const f=fixture([{text:'四日市競輪場'}]);await assert.rejects(api.openKeirinList(f.page,{...item,ui_venue_name:name},[]));assert.deepEqual(f.calls,[]);}
});
test('hidden duplicate labels are excluded and labels without the exact suffix receive no alias',async()=>{
 const f=fixture([{text:'四日市',visible:true},{text:'四日市競輪場',visible:false}]);await api.openKeirinList(f.page,item,[]);assert.deepEqual(f.calls,['四日市']);
 const invented=fixture([{text:'四日市'}]);await assert.rejects(api.openKeirinList(invented.page,{...item,ui_venue_name:'四日市開催'},[]));assert.deepEqual(invented.calls,[]);
});
test('the existing stable venue code gate still rejects before a result action',async()=>{
 let clicks=0;const page={locator:selector=>{assert.equal(selector,'#hhSelJ');return {inputValue:async()=>'47',click:async()=>{clicks++;}};}};
 await assert.rejects(api.selectKeirinCase(page,item,[]),/VISIBLE_VENUE_IDENTITY/);assert.equal(clicks,0);
});
