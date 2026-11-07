'use strict';
// Invented UI/wire metadata only; no real source, browser, key or HTTP.
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../scripts/official_result_browser_capture.cjs');
const item={sport:'autorace',race_id:'autorace:2030-01-15:isesaki:1',expected_date:'2030-01-15',venue:'isesaki',race_no:1,place_code:3,ui_entry_url:'https://autorace.jp/race_info/Live/isesaki'};
function page(suffix=''){
 const events=[],ledger=[];let menu='result';
 const req={url:()=> 'https://autorace.jp/race_info/OtherRaceInfo',method:()=> 'POST',resourceType:()=> 'xhr',headers:()=>({'content-type':'application/json'}),postDataBuffer:()=>Buffer.from('{"placeCode":3,"raceDate":"2030-01-15","raceNo":"1"}')};
 const response={request:()=>req,url:()=>req.url(),status:()=>200,finished:async()=>{events.push('identity-finished');}};
 const p={url:()=>item.ui_entry_url+'/'+(menu==='result'?'RaceResult/2030-01-15_1'+suffix:'Program/2030-01-15_1/program'),waitForLoadState:async()=>{},waitForTimeout:async()=>{},waitForResponse:async predicate=>{assert.equal(predicate(response),true);return response;},locator(selector){const date=selector.includes('data-period-date'),race=selector.includes('data-raceno'),program=selector.includes('data-main-menu="program"');const node={last:()=>node,count:async()=>1,isVisible:async()=>true,waitFor:async()=>{},getAttribute:async k=>k==='class'?'liveTabMenu__item--current':'2030-01-15',innerText:async()=>date?'初日':race?'1R':program?'出走表':'レース結果',click:async()=>{events.push(date?'date':race?'race':program?'program':'result');if(program)menu='program';}};return node;}};return {p,events,ledger};
}
test('observed suffix-free and retained legacy Result URLs skip date and Program only for result intent',async()=>{
 for(const suffix of ['', '/result']){const f=page(suffix);await api.selectAutoCase(f.p,item,f.ledger);assert.deepEqual(f.events,['race','identity-finished','result']);assert.ok(f.ledger.some(e=>e.event==='ALREADY_SELECTED_UI_DATE'));}
});
test('future Program intent still switches a Result screen to Program before the race',async()=>{
 for(const suffix of ['', '/result']){const f=page(suffix);await api.selectAutoProgram(f.p,item,f.ledger);assert.deepEqual(f.events,['program','race','identity-finished']);}
});
function row(sequence,endpoint,at){return {sequence,url:'https://autorace.jp/race_info/'+endpoint,method:'POST',status:200,request_identity:{placeCode:3,raceDate:item.expected_date,raceNo:1},request_body_sha256:'b'.repeat(64),request_content_type:'application/json',source_sha256:(endpoint==='OtherRaceInfo'?'a':'c').repeat(64),byte_count:100,request_started_at:'2030-01-15T03:00:'+String(at).padStart(2,'0')+'Z',response_received_at:'2030-01-15T03:00:'+String(at+1).padStart(2,'0')+'Z'};}
test('all identical Results are retained and the earliest one after identity is selected',()=>{
 const rows=[row(1,'RaceResult',1),row(2,'OtherRaceInfo',3),row(3,'RaceResult',5)],before=structuredClone(rows);
 assert.deepEqual(api.caseResponses(item,rows),[{role:'identity',sequence:2},{role:'result',sequence:3}]);assert.deepEqual(rows,before);
 assert.deepEqual(api.caseResponses(item,[...rows].reverse()),[{role:'identity',sequence:2},{role:'result',sequence:3}]);
});
test('qualifying earliest and ordinary single Result behavior stays unchanged and no eligible Result holds',()=>{
 const identity=row(1,'OtherRaceInfo',1),first=row(2,'RaceResult',3),last=row(3,'RaceResult',5);
 assert.deepEqual(api.caseResponses(item,[identity,first,last]),[{role:'identity',sequence:1},{role:'result',sequence:2}]);
 assert.deepEqual(api.caseResponses(item,[identity,first]),[{role:'identity',sequence:1},{role:'result',sequence:2}]);
 assert.throws(()=>api.caseResponses(item,[row(1,'RaceResult',1),row(2,'OtherRaceInfo',9),row(3,'RaceResult',5)]),/CASE_RESPONSE_CLOCK/);
});
test('an eligible late Result never hides differing early source or request fingerprints',()=>{
 for(const change of [{url:'https://www.autorace.jp/race_info/RaceResult'},{source_sha256:'f'.repeat(64)},{byte_count:101},{request_body_sha256:'d'.repeat(64)},{request_content_type:'application/json;charset=UTF-8'},{method:'GET'}]){
  const rows=[{...row(1,'RaceResult',1),...change},row(2,'OtherRaceInfo',3),row(3,'RaceResult',5)];assert.throws(()=>api.caseResponses(item,rows),/CASE_RESPONSE_(?:CONFLICT|PROOF)/);
 }
 const wrong=row(3,'RaceResult',5);wrong.request_identity.raceNo=2;
 assert.throws(()=>api.caseResponses(item,[row(1,'RaceResult',1),row(2,'OtherRaceInfo',3),wrong,row(4,'OtherRaceInfo',7)]),/CASE_RESPONSE_CLOCK/);
});
