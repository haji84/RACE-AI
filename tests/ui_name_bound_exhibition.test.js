const test=require('node:test'),assert=require('node:assert/strict'),fixture=require('./ui_name_bound_exhibition_fixture.json');
let api;try{api=require('../web/name-bound-exhibition.js');}catch{}
const clone=()=>structuredClone(fixture.envelope),now=Date.parse(fixture.now);
test('new independently pinned comparison module exists',()=>assert.equal(typeof api?.validateNameBoundComparison,'function'));
test('valid complete synthetic envelope replays both models',()=>assert.equal(api.validateNameBoundComparison(fixture.envelope,fixture.race,now),fixture.envelope));
const cases={
 'invalid name category':v=>v.name_binding.receipt.snapshot.bindings[0].verified_full_name+='\uE000',
 'forecast fractional schema':v=>v.receipt.schema_version=1.1,
 'name source available mismatch':v=>v.name_binding.receipt.snapshot.source.available_at=v.inputs.generated_at,
 'boolean contribution':v=>v.receipt.snapshot.boats[0].contributions.lap_s.delta_seconds=true,
 'microsecond backwards clock':v=>{v.receipt.snapshot.parents_resolved_at='2026-10-14T22:33:00.000001+00:00';},
 'negative probability':v=>v.receipt.snapshot.models[0].triples[0].probability=-1e-15,
 'numeric string':v=>v.receipt.snapshot.boats[0].display_time_s='6.92',
 'tampered triple':v=>v.receipt.snapshot.models[0].triples[0].probability+=2e-12,
 'tampered marginal':v=>v.receipt.snapshot.models[1].marginals[0].sixth_probability+=2e-12,
 'tampered delta':v=>v.receipt.snapshot.deltas[0].triples[0].delta_probability+=2e-12,
 'tampered contribution':v=>v.receipt.snapshot.boats[0].contributions.lap_s.log_strength_contribution+=2e-12,
 'bad hash format':v=>v.inputs.snapshot_id='g'.repeat(64),
 'wrong pin':v=>v.finalization.snapshot_id='0'.repeat(64),
 'wrong baseline pin':v=>v.receipt.snapshot.baseline_link.request_id='999-1',
 'wrong source':v=>v.inputs.original_observation.sources[0].source_url+='?x=1',
 'wrong full name':v=>v.inputs.original_observation.boats[0].name='松田大志',
 'cutoff memory save':v=>v.inputs.beforeinfo_record.saved_at=fixture.race.closed_at,
 'reversed parent clock':v=>v.inputs.parents_read_at=v.inputs.generated_at,
 'physical claim':v=>v.receipt.snapshot.physical_exhibition_timing_verified=true,
 'extra field':v=>v.receipt.snapshot.extra=true,
 'duplicate lane':v=>v.receipt.snapshot.boats[1].lane=1,
 'used weather':v=>v.receipt.snapshot.feature_status.weather.used=true,
};
for(const [name,mutate] of Object.entries(cases))test('rejects '+name,()=>{api.validateNameBoundComparison(fixture.envelope,fixture.race,now);const v=clone();mutate(v);assert.throws(()=>api.validateNameBoundComparison(v,fixture.race,now));});
test('rejects another selected race and stale JST day',()=>{assert.throws(()=>api.validateNameBoundComparison(clone(),{...fixture.race,race_id:'20261015-18-02'},now));assert.throws(()=>api.validateNameBoundComparison(clone(),fixture.race,now+86400000));});
test('renderer includes complete evidence,120 changes per model, six inputs and limits',()=>{const html=api.renderNameBoundComparison(clone(),fixture.race,now);for(const label of ['B情報のみ比較元','通常展示反映','オリジナル展示反映','UNVALIDATED','skip','[]','物理的な展示前','展示ST','天候','映像','メモリ保存'])assert.ok(html.includes(label),label);assert.equal((html.match(/class="nb-probability"/g)||[]).length,240);assert.equal((html.match(/class="nb-input"/g)||[]).length,6);});
test('renderer escapes all text from a validated envelope',()=>{const v=clone(),race=structuredClone(fixture.race),attack='<img src=x onerror=alert(1)>';race.boats[0].name=attack;v.baseline.snapshot.program_boats[0].name=attack;const binding=v.name_binding.receipt.snapshot.bindings[0];binding.program_name=attack;binding.verified_full_name=attack;binding.name_relation='EXACT_CANONICAL_NAME';v.name_binding.receipt.snapshot.source.observed_racers[0].name=attack;v.inputs.beforeinfo_record.data.boats[0].name=attack;v.inputs.original_observation.boats[0].name=attack;v.receipt.snapshot.boats[0].program_name=attack;v.receipt.snapshot.boats[0].verified_full_name=attack;const html=api.renderNameBoundComparison(v,race,now);assert.ok(!html.includes(attack));assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));});

test('retains independently saved baseline even if unrelated latest changes',()=>{const latest=structuredClone(fixture.envelope.baseline);latest.request_id='888-1';assert.equal(api.validateNameBoundComparison(clone(),fixture.race,now).baseline.request_id,'123455-1');});

test('shows saved forecast request to distinguish immutable versions',()=>assert.ok(api.renderNameBoundComparison(clone(),fixture.race,now).includes(fixture.envelope.receipt.request_id)));
