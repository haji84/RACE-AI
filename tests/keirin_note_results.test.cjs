'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {packet,source}=require('./keirin_note_model.test.cjs');
const M=require('../web/keirin-note-model.js'),F=require('../web/keirin-note-feed.js');
const DAY='2030-01-15',RACE='203001159801';
function pendingArms(overrides={}){return {...Object.fromEntries(['A','B','C','adjusted_A','adjusted_B'].map(name=>[name,{state:'pending',points:null,stake_yen:null,return_yen:null}])),...overrides};}
function update(overrides={}){return {race_id:RACE,revision:'b'.repeat(64),observed_at:DAY+'T04:00:00Z',authority:'official',order_status:'confirmed',payout_status:'pending',winning_triples:['3-1-2'],payouts_100yen:{},source_comparison:[{source_id:'keirin_jp',state:'matched'}],diagnostics:[],arms:pendingArms({A:{state:'hit',points:1,stake_yen:null,return_yen:null},B:{state:'miss',points:1,stake_yen:null,return_yen:null}}),...overrides};}
function resultPacket(row=update()){const p=packet();p.files={['data/'+DAY+'/result_updates.json']:source({schema:'RACE_AI_KEIRIN_RESULT_UPDATES_V1',observed_at:DAY+'T05:00:00Z',races:[row]})};p.imported_at=DAY+'T05:00:00Z';return p;}
test('result-only packets attach order-only A and B outcomes without hiding the preserved forecast or missing C',async()=>{
  const original=await M.openPacket(packet()),change=await M.openPacket(resultPacket()),data=F.merge([original,change]);
  const row=M.rows(data,DAY)[0];assert.ok(row.resultUpdate,'separate result overlay must reach the existing race');
  assert.equal(row.resultUpdate.payout_status,'pending');assert.equal(row.resultUpdate.arms.A.state,'hit');assert.equal(row.resultUpdate.arms.B.state,'miss');assert.equal(row.resultUpdate.arms.C.state,'pending');
  assert.equal(M.forecast(row,'3t','original').tickets[0].combo,'1-2-3');assert.equal(M.forecast(row,'3t','A').tickets[0].combo,'3-1-2');assert.equal(M.rows(change,DAY).length,0);
});
test('secondary consensus cannot carry official payout or hit/miss scoring',async()=>{
  await assert.rejects(()=>M.openPacket(resultPacket(update({authority:'secondary',payout_status:'confirmed',payouts_100yen:{'3-1-2':1200}}))));
  await assert.rejects(()=>M.openPacket(resultPacket(update({authority:'secondary'}))));
  const secondary=update({authority:'secondary',arms:pendingArms({A:{state:'pending',points:1,stake_yen:null,return_yen:null}})});
  const result=await M.openPacket(resultPacket(secondary));assert.equal(result.resultUpdates.get(DAY).get(RACE).authority,'secondary');
});
test('a result arriving before its card waits without inventing a race and attaches when the card arrives',async()=>{
  const change=await M.openPacket(resultPacket());assert.equal(M.rows(F.merge([change]),DAY).length,0);
  const data=F.merge([change,await M.openPacket(packet())]);assert.equal(M.rows(data,DAY)[0].resultUpdate.revision,'b'.repeat(64));
});
test('an older result cannot replace a newer revision and conflicting reuse of a revision is rejected',async()=>{
  const original=await M.openPacket(packet()),newer=await M.openPacket(resultPacket(update({revision:'c'.repeat(64),observed_at:DAY+'T04:30:00Z'}))),older=await M.openPacket(resultPacket());
  assert.equal(M.rows(F.merge([original,newer,older]),DAY)[0].resultUpdate.revision,'c'.repeat(64));
  const conflict=await M.openPacket(resultPacket(update({winning_triples:['1-2-3']})));
  assert.throws(()=>F.merge([original,older,conflict]));
});
test('the same semantic revision may be observed again without creating a conflict or duplicate history',async()=>{
  const original=await M.openPacket(packet()),first=await M.openPacket(resultPacket()),again=await M.openPacket(resultPacket(update({observed_at:DAY+'T04:30:00Z'})));
  const data=F.merge([original,first,again]),row=M.rows(data,DAY)[0];assert.equal(row.resultUpdate.observed_at,DAY+'T04:30:00Z');assert.equal(row.resultHistory.length,1);
});
test('payout updates require complete verified units and preserve the older order revision',async()=>{
  const original=await M.openPacket(packet()),order=await M.openPacket(resultPacket());
  const paid=update({revision:'d'.repeat(64),observed_at:DAY+'T04:30:00Z',payout_status:'confirmed',payouts_100yen:{'3-1-2':1200},arms:pendingArms({A:{state:'hit',points:1,stake_yen:100,return_yen:1200},B:{state:'miss',points:1,stake_yen:100,return_yen:0}})});
  const data=F.merge([original,order,await M.openPacket(resultPacket(paid))]),row=M.rows(data,DAY)[0];assert.equal(row.resultUpdate.payouts_100yen['3-1-2'],1200);assert.equal(row.resultHistory.length,2);
  await assert.rejects(()=>M.openPacket(resultPacket(update({payout_status:'confirmed',payouts_100yen:{'1-2-3':1200}}))));
  await assert.rejects(()=>M.openPacket(resultPacket(update({arms:pendingArms({A:{state:'hit',points:1,stake_yen:100,return_yen:1200}})}))));
});
test('matching input refresh copies the latest saved settlement without replacing authored picks',async()=>{
  const original=await M.openPacket(packet()),p=packet();p.files['data/'+DAY+'/settlement.json']=source([{race_id:RACE,status:'MISS',winning_combo:'2-3-1'}]);
  const data=F.merge([original,await M.openPacket(p)]),row=M.rows(data,DAY)[0];assert.equal(row.settlement?.status,'MISS');assert.equal(M.forecast(row,'3t','original').tickets[0].combo,'1-2-3');
});
test('diagnostic rows admit only registered routes and never accept query strings or arbitrary exception text',async()=>{
  const diagnostic={schema:'RACE_AI_KEIRIN_RESULT_DIAGNOSTIC_V1',purpose:'OFFICIAL_FINAL_RESULT',source_host:'keirin.jp',source_path:'/sp/race',method:'POST',stage:'HTTP_RESPONSE',reason:'HTTP_DENIED',http_status:403,observed_at:DAY+'T04:00:00+00:00'};
  const accepted=await M.openPacket(resultPacket(update({diagnostics:[diagnostic]})));assert.equal(accepted.resultUpdates.get(DAY).get(RACE).diagnostics[0].http_status,403);
  for(const changed of [{...diagnostic,source_path:'/sp/race?token=secret'},{...diagnostic,reason:'HTTP_DENIED secret'},{...diagnostic,request_headers:{Authorization:'secret'}},{...diagnostic,http_status:0}])await assert.rejects(()=>M.openPacket(resultPacket(update({diagnostics:[changed]}))));
});
test('all official JSON diagnostics use the same fixed query-free route with distinct purposes',async()=>{
  const diagnostics=['OFFICIAL_JSON_CALENDAR','OFFICIAL_JSON_DAY_LIST','OFFICIAL_JSON_RESULT_SUMMARY','OFFICIAL_JSON_HEADER','OFFICIAL_JSON_DETAIL'].map(purpose=>({schema:'RACE_AI_KEIRIN_RESULT_DIAGNOSTIC_V1',purpose,source_host:'keirin.jp',source_path:'/pc/json',method:'GET',stage:'HTTP_RESPONSE',reason:'SOURCE_ACCEPTED',http_status:200,observed_at:DAY+'T04:00:00Z'}));
  const accepted=await M.openPacket(resultPacket(update({diagnostics})));assert.equal(accepted.resultUpdates.get(DAY).get(RACE).diagnostics.length,5);
  await assert.rejects(()=>M.openPacket(resultPacket(update({diagnostics:[{...diagnostics[0],source_path:'/pc/json?type=057'}]}))));
});
test('result records require exact fields and five independent arm slots',async()=>{
  const invalidRows=[update({extra:'unregistered'}),update({arms:{A:update().arms.A}}),update({arms:pendingArms({A:{...update().arms.A,extra:'unregistered'}})}),update({arms:pendingArms({A:{state:'hit',points:1,stake_yen:null}})})];
  for(const row of invalidRows)await assert.rejects(()=>M.openPacket(resultPacket(row)));
  const p=resultPacket(),path='data/'+DAY+'/result_updates.json',doc=JSON.parse(p.files[path].text);doc.extra='unregistered';p.files[path]=source(doc);await assert.rejects(()=>M.openPacket(p));
});
test('pending and unverifiable arms never receive money even after the official payout is confirmed',async()=>{
  for(const state of ['pending','unverifiable']){
    const row=update({payout_status:'confirmed',payouts_100yen:{'3-1-2':1200},arms:pendingArms({A:{state,points:1,stake_yen:100,return_yen:1200}})});
    await assert.rejects(()=>M.openPacket(resultPacket(row)));
  }
  await assert.rejects(()=>M.openPacket(resultPacket(update({authority:'secondary',arms:pendingArms({A:{state:'void',points:null,stake_yen:null,return_yen:null}})}))));
});
test('result row count, point count and arm money use the producer bounds',async()=>{
  const p=resultPacket(),path='data/'+DAY+'/result_updates.json',doc=JSON.parse(p.files[path].text);doc.races=Array.from({length:301},(_,i)=>update({race_id:'20300115'+String(i+1).padStart(4,'0')}));p.files[path]=source(doc);await assert.rejects(()=>M.openPacket(p));
  for(const points of [0,505])await assert.rejects(()=>M.openPacket(resultPacket(update({arms:pendingArms({A:{...update().arms.A,points}})}))));
  await assert.rejects(()=>M.openPacket(resultPacket(update({payout_status:'confirmed',payouts_100yen:{'3-1-2':1200},arms:pendingArms({A:{state:'hit',points:1,stake_yen:100,return_yen:504000000001}})}))));
});
module.exports={update,resultPacket};
