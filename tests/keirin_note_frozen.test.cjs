'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {packet,source}=require('./keirin_note_model.test.cjs');
const {frozenRow}=require('./keirin_note_frozen_fixture.cjs');
const M=require('../web/keirin-note-model.js'),F=require('../web/keirin-note-feed.js');
const DAY='2030-01-15';
function frozenPacket(row=frozenRow()){const p=packet();p.files={['data/'+DAY+'/frozen_forecasts.json']:source({schema:'RACE_AI_KEIRIN_FROZEN_FORECASTS_V1',races:[row]})};return p;}
test('frozen originals attach separately and preserve every imported prediction',async()=>{
  const original=await M.openPacket(packet()),frozen=await M.openPacket(frozenPacket());
  const row=M.rows(F.merge([original,frozen]),DAY)[0];assert.ok(row.frozenForecast);
  assert.equal(M.forecast(row,'3t','A').tickets[0].combo,'3-1-2');
  assert.equal(M.forecast(row,'3t','original').tickets[0].combo,'1-2-3');
  assert.equal(M.frozenArm(row,'A').tickets.length,3);assert.equal(M.frozenArm(row,'B').tickets.length,1);
  assert.equal(M.frozenArm(row,'adjusted_B').tickets.length,2);assert.equal(M.frozenArm(row,'C'),null);
  assert.deepEqual(row.frozenForecast.baseline.B.six_phase_scenarios,frozenRow().baseline.B.six_phase_scenarios);
});
test('an original packet waits for a real card and cannot replace any frozen original',async()=>{
  const frozen=await M.openPacket(frozenPacket());assert.equal(M.rows(F.merge([frozen]),DAY).length,0);
  const original=await M.openPacket(packet());assert.ok(M.rows(F.merge([frozen,original]),DAY)[0].frozenForecast);
  const same=await M.openPacket(frozenPacket());assert.doesNotThrow(()=>F.merge([original,frozen,same]));
  const changed=frozenRow();changed.revision='9'.repeat(64);changed.baseline_cipher_sha256='8'.repeat(64);
  const other=await M.openPacket(frozenPacket(changed));assert.throws(()=>F.merge([original,frozen,other]));
});
test('invalid frozen identity, fabricated C, wrong sealing time and missing arms are rejected',async()=>{
  for(const change of [r=>{r.conditioned.baseline_prediction_sha256='0'.repeat(64);},r=>{r.baseline.C={ranked_tickets:[[1,2,3]]};},r=>{r.baseline_sealed_at=r.baseline.published_cutoff_at;},r=>{delete r.conditioned.B_research;},r=>{r.baseline.A.ranked_tickets.push([1,2,3]);}]){
    const row=frozenRow();change(row);await assert.rejects(()=>M.openPacket(frozenPacket(row)));
  }
});
test('frozen originals and official scores survive an independent reference-result disagreement',async()=>{
  const {observation,resultsPacket,RACE}=require('./keirin_note_result_fixtures.cjs');
  const matched=observation(),held=observation({state:'HOLD_SECONDARY_RESULT_DISAGREEMENT',previous:matched.observation_sha256,at:DAY+'T04:30:00Z'});
  const arms=Object.fromEntries(['A','B','C','adjusted_A','adjusted_B'].map(name=>[name,{state:'pending',points:null,stake_yen:null,return_yen:null}]));
  arms.A={state:'hit',points:3,stake_yen:null,return_yen:null};
  const official={race_id:RACE,revision:'b'.repeat(64),observed_at:DAY+'T04:00:00Z',authority:'official',order_status:'confirmed',payout_status:'pending',winning_triples:['1-2-3'],payouts_100yen:{},source_comparison:[],diagnostics:[],arms};
  const p=packet();p.files={['data/'+DAY+'/result_updates.json']:source({schema:'RACE_AI_KEIRIN_RESULT_UPDATES_V1',observed_at:official.observed_at,races:[official]})};
  const before=await Promise.all([M.openPacket(frozenPacket()),M.openPacket(resultsPacket([matched])),M.openPacket(p)]);
  assert.equal(M.rows(F.merge(before),DAY).length,0);
  const card=await M.openPacket(packet()),first=M.rows(F.merge([...before,card]),DAY)[0];
  assert.equal(M.compare(first,'3t','A').status,'RESEARCH_HIT');
  assert.equal(M.compare(first,'3t','A').ticketCount,1);
  assert.equal(M.frozenArm(first,'A').tickets.length,3);
  assert.deepEqual(first.resultUpdate.winning_triples,['1-2-3']);
  const delta=await M.openPacket(resultsPacket([held]));
  const data=F.merge([...before,card,delta],{resultChecks:{[RACE]:{checked_at:held.captured_at,digest:held.observation_sha256,status:'HOLD'}}});
  const row=M.rows(data,DAY)[0];
  assert.notEqual(M.compare(row,'3t','A').status,'RESEARCH_HIT');
  assert.equal(row.researchResultHistory.length,2);
  assert.equal(row.resultHistory.length,1);
  assert.deepEqual(row.resultUpdate,official);
  assert.deepEqual(row.frozenForecast,first.frozenForecast);
  assert.deepEqual(row.bindings.reference,first.bindings.reference);
  assert.equal(M.forecast(row,'3t','original').tickets[0].combo,'1-2-3');
});
module.exports={frozenPacket};
