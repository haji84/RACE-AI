'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../web/keirin-note-model.js'),F=require('../web/keirin-note-feed.js');
const {DAY,RACE,nationwideDoc,nationwidePacket}=require('./keirin_note_nationwide_fixture.cjs');
const {packet,source}=require('./keirin_note_model.test.cjs');
const {observation,resultsPacket}=require('./keirin_note_result_fixtures.cjs');
test('national A and B render from their registered originals without an imported roster or conditioned arms',async()=>{
  const data=await M.openPacket(nationwidePacket()),rows=M.rows(data,DAY);
  assert.equal(rows.length,3);assert.equal(rows[0].venue,'開催コード 98');
  assert.equal(M.frozenArm(rows[0],'A').tickets.length,3);assert.equal(M.frozenArm(rows[0],'B').tickets.length,1);
  assert.equal(M.frozenArm(rows[0],'adjusted_A'),null);assert.equal(M.frozenArm(rows[0],'adjusted_B'),null);assert.equal(M.frozenArm(rows[0],'C'),null);
  assert.equal(rows[1].nationwideStatus.state,'UNSUPPORTED_CLASS_OR_ROUND');assert.equal(rows[1].frozenForecast,undefined);
  assert.equal(rows[2].nationwideStatus.state,'WAITING_SOURCE_CAPTURE');assert.deepEqual(rows[2].original,{});
});
test('registered cards preserve imported reference originals and independent secondary histories',async()=>{
  const national=await M.openPacket(nationwidePacket()),imported=await M.openPacket(packet()),secondary=await M.openPacket(resultsPacket([observation()]));
  for(const parts of [[national,imported,secondary],[imported,secondary,national]]){
    const data=F.merge(parts),row=M.rows(data,DAY).find(r=>r.id===RACE);
    assert.equal(M.rows(data,DAY).length,3);assert.equal(row.nationwideOnly,undefined);
    assert.equal(row.venue,M.rows(imported,DAY)[0].venue);assert.equal(M.forecast(row,'3t','A').tickets.length,1);
    assert.equal(M.frozenArm(row,'A').tickets.length,3);assert.equal(M.compare(row,'3t','A').status,'RESEARCH_HIT');
    assert.equal(row.researchResultHistory.length,1);assert.deepEqual(row.bindings.reference,M.rows(imported,DAY)[0].bindings.reference);
  }
});
test('later authenticated condition arms extend baseline without replacing it or losing prior condition originals',async()=>{
  const base=await M.openPacket(nationwidePacket()),full=await M.openPacket(nationwidePacket(nationwideDoc({conditioned:true,revision:'2',observed_at:DAY+'T05:00:00Z'})));
  const unavailable=await M.openPacket(nationwidePacket(nationwideDoc({revision:'3',observed_at:DAY+'T06:00:00Z'})));
  const data=F.merge([base,full,unavailable]),row=M.rows(data,DAY)[0];
  assert.equal(M.frozenArm(row,'A').tickets.length,3);assert.equal(M.frozenArm(row,'adjusted_B').tickets.length,2);
  assert.equal(data.nationwideHistory.get(DAY).size,3);assert.equal(row.nationwideStatus.condition_state,'HISTORY_SOURCE_UNAVAILABLE');
  const older=await M.openPacket(nationwidePacket(nationwideDoc({revision:'4',observed_at:DAY+'T03:30:00Z'})));
  const again=F.merge([base,full,unavailable,older]);
  assert.equal(again.nationwide.get(DAY).observed_at,DAY+'T06:00:00Z');
  assert.equal(M.frozenArm(M.rows(again,DAY)[0],'adjusted_B').tickets.length,2);
});
test('a newer national snapshot cannot shrink the denominator or rewrite authenticated original facts',async()=>{
  const base=await M.openPacket(nationwidePacket());
  const changed=nationwideDoc({revision:'2',observed_at:DAY+'T05:00:00Z'});changed.races[0].original.baseline.A.ranked_tickets.reverse();
  const altered=await M.openPacket(nationwidePacket(changed));assert.throws(()=>F.merge([base,altered]));
  const shrunk=nationwideDoc({revision:'3',observed_at:DAY+'T06:00:00Z'});shrunk.races.pop();
  assert.throws(()=>F.merge([base,{...base,nationwide:new Map([[DAY,shrunk]])}]));
  const conflict=nationwideDoc();conflict.races[1].state='WAITING_SOURCE_CAPTURE';
  assert.throws(()=>F.merge([base,{...base,nationwide:new Map([[DAY,conflict]])}]));
});
test('bounded deltas reference retained originals and allow a genuine state reversion without repeating tickets',async()=>{
  const first=await M.openPacket(nationwidePacket());
  const delta=nationwideDoc({revision:'2',observed_at:DAY+'T05:00:00Z'});delta.races[0].original=null;delta.races[1].state='SOURCE_CAPTURE_BUDGET_PENDING';
  const isolated=await M.openPacket(nationwidePacket(delta));
  assert.equal(M.rows(isolated,DAY)[0].frozenForecast,undefined);
  assert.ok(M.rows(isolated,DAY)[0].nationwideStatus.original_identity);
  const reverted=nationwideDoc({observed_at:DAY+'T06:00:00Z'});reverted.races[0].original=null;
  const data=F.merge([first,isolated,await M.openPacket(nationwidePacket(reverted))]),row=M.rows(data,DAY)[0];
  assert.equal(M.frozenArm(row,'A').tickets.length,3);assert.equal(M.frozenArm(row,'B').tickets.length,1);
  assert.equal(M.rows(data,DAY)[1].nationwideStatus.state,'UNSUPPORTED_CLASS_OR_ROUND');
  assert.equal(data.nationwideHistory.get(DAY).size,2);assert.equal(data.nationwide.get(DAY).revision,'1'.repeat(64));
});
test('only the new nationwide file may exceed twelve MiB and it still stops at thirty-two MiB',async()=>{
  const {createHash}=require('node:crypto'),p=nationwidePacket(),path='data/'+DAY+'/nationwide_forecasts.json';
  const withBytes=size=>{const value=structuredClone(p),text=p.files[path].text.padEnd(size,' '),raw=Buffer.from(text);value.files[path]={text,bytes:raw.length,sha256:createHash('sha256').update(raw).digest('hex')};return value;};
  const accepted=await M.openPacket(withBytes(13*1024*1024));assert.equal(M.rows(accepted,DAY).length,3);
  await assert.rejects(()=>M.openPacket(withBytes(32*1024*1024+1)));
  const legacy=withBytes(13*1024*1024);legacy.files['data/'+DAY+'/reference_AB.json']=legacy.files[path];delete legacy.files[path];
  await assert.rejects(()=>M.openPacket(legacy));
});
test('official order arriving before the national card attaches to the independently stored arm scores',async()=>{
  const arms=Object.fromEntries(['A','B','C','adjusted_A','adjusted_B'].map(name=>[name,{state:'pending',points:null,stake_yen:null,return_yen:null}]));
  arms.A={state:'hit',points:3,stake_yen:null,return_yen:null};arms.B={state:'miss',points:1,stake_yen:null,return_yen:null};
  const result={race_id:RACE,revision:'c'.repeat(64),observed_at:DAY+'T04:00:00Z',authority:'official',order_status:'confirmed',payout_status:'pending',winning_triples:['1-2-3'],payouts_100yen:{},source_comparison:[],diagnostics:[],arms};
  const p=nationwidePacket();p.files={['data/'+DAY+'/result_updates.json']:source({schema:'RACE_AI_KEIRIN_RESULT_UPDATES_V1',observed_at:result.observed_at,races:[result]})};
  const update=await M.openPacket(p);assert.equal(M.rows(update,DAY).length,0);
  const row=M.rows(F.merge([update,await M.openPacket(nationwidePacket())]),DAY)[0];
  assert.equal(row.resultUpdate.arms.A.state,'hit');assert.equal(row.resultUpdate.arms.adjusted_A.state,'pending');assert.equal(M.frozenArm(row,'A').tickets.length,3);
});
test('pending originals cannot fabricate C, exceed twelve points or relax the old canary schema',async()=>{
  const base=nationwideDoc();
  for(const change of [d=>{d.races[0].original.baseline.C={ranked_tickets:[[1,2,3]]};},d=>{d.races[0].original.baseline.A.ranked_tickets=Array(13).fill([1,2,3]);},d=>{d.races[0].original_identity.conditioned='d'.repeat(64);},d=>{d.races[1].state='A_B_AUTHENTICATED_PRE_CUTOFF';}]){
    const doc=structuredClone(base);change(doc);await assert.rejects(()=>M.openPacket(nationwidePacket(doc)));
  }
  const p=nationwidePacket();p.files={['data/'+DAY+'/frozen_forecasts.json']:source({schema:'RACE_AI_KEIRIN_FROZEN_FORECASTS_V1',races:[base.races[0].original]})};
  await assert.rejects(()=>M.openPacket(p));
});
