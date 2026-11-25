'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../web/keirin-note-model.js');
const F = require('../web/keirin-note-feed.js');
const {date,prefix,file,fixture}=require('./keirin_rider_history_fixture.cjs');
async function open(v) { v.packet.files[prefix+'rider_histories.json']=file(v.raw);return M.openPacket(v.packet); }
test('history attaches to its actual roster without modifying forecast identities or tickets', async()=>{
  const v=fixture(), row=M.rows(await open(v),date)[0];
  assert.equal(row.riders[0].registration,undefined);
  assert.equal(row.jointForecast,undefined);
  assert.equal(row.riderHistory.riders[0].history.periods.all.observed_count,2);
  const H=require('../web/keirin-rider-history.js');
  const output=H.render(row,1);
  for(const token of ['直近5','直近30','3年','1着','2着以内','3着以内','50.0%','100.0%','資料','2030-02-01','締切後'])assert.ok(output.includes(token),token);
  assert.match(H.render(row,2),/観測0走|0走/);
  assert.doesNotMatch(H.render(row,2),/0\.0%/);
});
test('wrong roster, identity, clocks, window dates, counts and empirical rates are rejected',async()=>{
  for(const change of [
    v=>v.raw.source_roster_sha256='f'.repeat(64),v=>v.raw.races[0].riders.pop(),
    v=>v.raw.races[0].riders[0].name='別選手',v=>v.raw.races[0].riders[0].history.registration='999999',
    v=>v.raw.knowledge_as_of='2030-02-01T00:00:00.000002Z',v=>v.raw.predictive_model_changed=true,
    v=>v.raw.knowledge_as_of='2029-12-31T00:00:00Z',
    v=>v.raw.races[0].riders[0].history.periods.all.finish_rates[1]=0.3,
    v=>v.raw.races[0].riders[0].history.periods.all.observed_count=3,
    v=>v.raw.races[0].riders[0].history.periods.all.latest_observed_day=date,
    v=>v.raw.races[0].riders[0].history.periods['4_months'].start_day_inclusive='2029-10-01',
    v=>v.raw.races[0].riders[1].history.periods.all.missing_finish_count=0,
    v=>v.raw.races[0].riders[0].history.last_starts[5].unfilled_slots=1,
    v=>v.raw.races[0].riders[0].history.ability_score=99,
    v=>{v.roster.riders[0].registration='999999';const saved=file({races:[v.roster]});
      v.packet.files[prefix+'races.json']=saved;v.raw.source_roster_sha256=saved.sha256;}
  ]){const v=fixture();change(v);await assert.rejects(open(v));}
});
test('same-clock changes fail and later validated versions retain the previous history',async()=>{
  const one=fixture(),two=fixture();two.raw.registry_sha256='d'.repeat(64);
  const prior=await open(one);
  const conflicting=await open(two);assert.throws(()=>F.merge([prior,conflicting]));
  two.raw.generated_at='2030-02-01T00:00:00.000002Z';
  const updated=M.rows(F.merge([prior,await open(two)]),date)[0];
  assert.equal(updated.riderHistory.registry_sha256,two.raw.registry_sha256);
  assert.equal(updated.riderHistoryVersions[0].registry_sha256,one.raw.registry_sha256);
  const wrong=fixture(),person=wrong.raw.races[0].riders[0];
  person.registration=person.history.registration='999998';
  wrong.raw.generated_at=two.raw.generated_at;
  const held=F.merge([prior,await open(wrong)]);
  assert.equal(held.refreshHolds.length,1);
  assert.equal(M.rows(held,date)[0].riderHistory.riders[0].registration,'000001');
});
