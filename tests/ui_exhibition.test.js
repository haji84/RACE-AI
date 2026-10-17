/* Synthetic frozen evidence only. No source requests or live purchases. */
const {test}=require('node:test'),assert=require('node:assert/strict');
let E={};try{E=require('../web/exhibition.js');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
test('race inventory distinguishes unchecked, saved, absent and failed phases without claiming a calculated update',()=>{
 assert.equal(typeof E.phaseStatus,'function');assert.match(E.phaseStatus({}),/展示前.*未確認.*展示後.*未確認/);
 assert.match(E.phaseStatus({baseline:'ready',post:'unobtained'}),/展示前.*保存済み.*展示後.*未保存/);
 assert.match(E.phaseStatus({baseline:'ready',post:'error'}),/展示後.*取得失敗/);
 assert.doesNotMatch(E.phaseStatus({baseline:'ready',post:'error'}),/展示後.*保存済み|更新済み/);
});
const fixture=require('./ui_exhibition_fixture.json'),clone=v=>structuredClone(v);
const options=()=>({race:clone(fixture.race),dateJst:'2026-10-15',now:Date.parse('2026-10-15T10:00:00+09:00'),baselineReceipt:clone(fixture.baseline_receipt),programIdentitySha256:fixture.post_receipt.program_identity_sha256});
function checked(value=clone(fixture.post_receipt),opts=options()){assert.equal(typeof E.validateReceipt,'function','post receipt replay must exist');return E.validateReceipt(value,opts);}
test('backend-emitted saved post receipt replays against pinned baseline without mutating either',()=>{
 const raw=clone(fixture.post_receipt),base=clone(fixture.baseline_receipt),before=clone(raw);checked(raw,{...options(),baselineReceipt:base});assert.deepEqual(raw,before);assert.deepEqual(base,fixture.baseline_receipt);
 assert.equal(raw.snapshot.model.triples.length,120);assert.equal(raw.snapshot.deltas.triples.length,120);assert.ok(raw.snapshot.deltas.triples.every(r=>Math.abs(r.delta_probability)<1e-12),'equal display times preserve the baseline');
});
test('post receipt rejects wrong identity, cutoff, day, baseline links and post-close/future clocks',()=>{
 checked();for(const mutate of [v=>v.snapshot.race_id='20261015-18-02',v=>v.snapshot.closed_at='2026-10-15T08:44:00+09:00',v=>v.snapshot.date_jst='2026-10-14',v=>v.snapshot.baseline_link.request_id='987654-1',v=>v.snapshot.baseline_link.snapshot_id='f'.repeat(64),v=>v.snapshot.baseline_link.cloud_saved_at='2026-10-15T07:32:00+09:00',v=>v.snapshot.b_program_sha256='f'.repeat(64),v=>v.snapshot.program_identity_sha256='f'.repeat(64),v=>v.cloud_saved_at='2026-10-15T08:43:00+09:00',v=>v.snapshot.generated_at='2026-10-15T10:01:00+09:00',v=>v.snapshot.beforeinfo_link.cloud_saved_at='2026-10-15T07:35:00+09:00',v=>v.snapshot.beforeinfo_link.runner_saved_at='2026-10-15T07:32:00+09:00',v=>v.snapshot.beforeinfo_link.source_url+='&rno=1']){const raw=clone(fixture.post_receipt);mutate(raw);assert.throws(()=>checked(raw));}
 assert.throws(()=>checked(undefined,{...options(),dateJst:'2026-10-16'}));
});
test('post receipt rejects altered display contribution, probabilities, deltas and unsafe research claims',()=>{
 checked();
 for(const mutate of [v=>v.snapshot.boats[0].display_time_seconds=null,v=>v.snapshot.boats[0].racer_registration_id='9999',v=>v.snapshot.boats[0].base_strength=99,v=>v.snapshot.boats[0].display_delta_seconds=1,v=>v.snapshot.boats[0].adjusted_strength=8,v=>v.snapshot.model.parameters.display_coefficient_per_second=2,v=>v.snapshot.model.triples[0].probability+=0.1,v=>v.snapshot.model.marginals[0].sixth_probability+=0.1,v=>v.snapshot.deltas.triples[0].delta_probability=0.5,v=>v.snapshot.deltas.marginals[0].first.baseline_probability=0.9,v=>v.snapshot.feature_status.exhibition_video.used=true,v=>v.snapshot.feature_status.weather.reason=null,v=>v.snapshot.purchase_recommendations=[{combination:[1,2,3]}],v=>v.snapshot.validation_status='VALIDATED',v=>v.snapshot.extra_wind=3]){const raw=clone(fixture.post_receipt);mutate(raw);assert.throws(()=>checked(raw));}
});
test('actual unequal display inputs replay nonzero changes rather than inventing updated probabilities',()=>{
 const f=require('./ui_exhibition_unequal_fixture.json'),value=checked(clone(f.post_receipt));assert.ok(Math.abs(value.snapshot.deltas.marginals[0].first.delta_probability-0.09674593001477488)<1e-12);assert.equal(value.snapshot.boats[0].display_time_seconds,6);assert.equal(value.snapshot.boats[0].display_delta_seconds,0.5);
 assert.ok(Math.abs(value.snapshot.deltas.triples.reduce((sum,r)=>sum+r.delta_probability,0))<1e-10);assert.ok(Math.abs(value.snapshot.model.triples.reduce((sum,r)=>sum+r.probability,0)-1)<1e-10);
});
test('post combinations retain integer boat identities rather than string aliases',()=>{
 const model=clone(fixture.post_receipt);model.snapshot.model.triples[0].combination[0]='1';assert.throws(()=>checked(model));
 const delta=clone(fixture.post_receipt);delta.snapshot.deltas.triples[0].combination[0]='1';assert.throws(()=>checked(delta));
});
test('saved post remains readable after close; unavailable original/video/ST/weather remain explicitly unused',()=>{
 const raw=checked();assert.equal(raw.snapshot.feature_status.display_time.used,true);for(const key of ['preview_st','weather','original_exhibition','exhibition_video'])assert.equal(raw.snapshot.feature_status[key].used,false);
 assert.equal(raw.snapshot.feature_status.original_exhibition.status,'MISSING');assert.equal(raw.snapshot.feature_status.exhibition_video.status,'MISSING');
 const before=options();before.now=Date.parse('2026-10-15T07:34:01+09:00');checked(undefined,before);before.now=Date.parse('2026-10-15T07:30:00+09:00');assert.throws(()=>checked(undefined,before));
});
