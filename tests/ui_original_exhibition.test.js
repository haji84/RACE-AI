/* Independent synthetic math/receipt regressions, never real performance. */
const {test}=require('node:test'),assert=require('node:assert/strict');
let O={};try{O=require('../web/original-exhibition.js');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
test('inventory keeps original-enhanced forecast distinct and never claims video was used',()=>{
 assert.equal(typeof O.phaseStatus,'function');assert.match(O.phaseStatus({}),/展示前.*未確認.*展示後.*未確認.*オリジナル反映.*未確認.*映像.*未使用/);
 assert.match(O.phaseStatus({baseline:'ready',post:'ready',original:'error'}),/展示前.*保存済み.*展示後.*保存済み.*オリジナル反映.*取得失敗/);
 assert.doesNotMatch(O.phaseStatus({original:'error'}),/オリジナル反映.*保存済み/);
});
const equal=require('./ui_original_exhibition_fixture.json'),unequal=require('./ui_original_exhibition_unequal_fixture.json'),clone=v=>structuredClone(v);
const options=()=>({race:clone(equal.race),dateJst:'2026-10-15',now:Date.parse('2026-10-15T10:00:00+09:00'),baselineReceipt:clone(equal.baseline_receipt),programIdentitySha256:equal.post_receipt.program_identity_sha256});
function checked(value=clone(equal.post_receipt),opts=options()){assert.equal(typeof O.validateReceipt,'function','original variant replay must exist');return O.validateReceipt(value,opts);}
test('equal original metrics preserve baseline120 and allsix ranks without mutation',()=>{
 const raw=clone(equal.post_receipt),before=clone(raw),base=clone(equal.baseline_receipt);checked(raw,{...options(),baselineReceipt:base});assert.deepEqual(raw,before);assert.deepEqual(base,equal.baseline_receipt);assert.equal(raw.snapshot.model.triples.length,120);assert.ok(raw.snapshot.deltas.triples.every(r=>Math.abs(r.delta_probability)<1e-12));
});
test('hand-computed lap contribution changes probability through fixedfour-coefficient model',()=>{
 const value=checked(clone(unequal.post_receipt)),boat=value.snapshot.boats[0];assert.ok(Math.abs(boat.contributions.lap_s.delta_seconds-5/6)<1e-12);assert.ok(Math.abs(boat.contributions.lap_s.log_strength_contribution-1/24)<1e-12);assert.ok(Math.abs(boat.adjusted_strength-6*Math.exp(1/24))<1e-12);assert.ok(Math.abs(value.snapshot.deltas.marginals[0].first.delta_probability-0.010312423552944705)<1e-12);
 assert.ok(Math.abs(value.snapshot.model.triples.reduce((s,r)=>s+r.probability,0)-1)<1e-10);assert.ok(Math.abs(value.snapshot.deltas.triples.reduce((s,r)=>s+r.delta_probability,0))<1e-10);
});
test('identity/baseline/variant/proof clocks are bound independently of mutable latest data',()=>{
 checked();for(const mutate of [v=>v.snapshot.variant='display-v1',v=>v.snapshot.race_id='20261015-18-02',v=>v.snapshot.program_identity_sha256='f'.repeat(64),v=>v.snapshot.b_program_sha256='f'.repeat(64),v=>v.snapshot.baseline_link.request_id='998877-1',v=>v.snapshot.original_link.request_id='0-1',v=>v.snapshot.original_link.runner_saved_at='2026-10-15T07:33:02+09:00',v=>v.snapshot.original_link.cloud_saved_at='2026-10-15T07:35:00+09:00',v=>v.cloud_saved_at=v.snapshot.closed_at,v=>v.snapshot.closed_at='2026-10-15T08:44:00+09:00',v=>v.snapshot.generated_at='2026-10-16T00:00:00+09:00']){const raw=clone(equal.post_receipt);mutate(raw);assert.throws(()=>checked(raw));}
 assert.throws(()=>checked(undefined,{...options(),now:Date.parse('2026-10-16T00:01:00+09:00')}));
});
test('original source requires exactpaddedBOATCASTpair without queries, aliases or invented timestamps',()=>{
 checked();for(const mutate of [v=>v.snapshot.original_link.sources[0].source_url+='?token=synthetic',v=>v.snapshot.original_link.sources[0].source_url=v.snapshot.original_link.sources[0].source_url.replace('race.boatcast.jp','evil.example'),v=>v.snapshot.original_link.sources[0].source_url=v.snapshot.original_link.sources[0].source_url.replace('_01.txt','_1.txt'),v=>v.snapshot.original_link.sources[0].source_url=v.snapshot.original_link.sources[0].source_url.replace('_18_','_14_'),v=>v.snapshot.original_link.sources.pop(),v=>v.snapshot.original_link.sources[1].component='original',v=>v.snapshot.original_link.sources[0].available_at='2026-10-15T07:35:00+09:00',v=>v.snapshot.original_link.sources[0].upstream_published_at='2026-10-15T07:00:00+09:00']){const raw=clone(equal.post_receipt);mutate(raw);assert.throws(()=>checked(raw));}
});
test('all24metrics/fourcontributions/deltas must replay, with videoSTweather unused',()=>{
 checked();for(const mutate of [v=>v.snapshot.boats[0].original_times.lap_s=null,v=>v.snapshot.boats[0].original_times.turn_s=0,v=>v.snapshot.boats[0].original_times.straight_s=Infinity,v=>v.snapshot.boats[0].contributions.lap_s.coefficient_per_second=0.1,v=>v.snapshot.boats[0].contributions.turn_s.delta_seconds=1,v=>v.snapshot.boats[0].contributions.straight_s.log_strength_contribution=1,v=>v.snapshot.boats[0].total_log_strength_delta=1,v=>v.snapshot.model.parameters.straight_coefficient_per_second=1,v=>v.snapshot.boats[0].adjusted_strength=99,v=>v.snapshot.model.triples[0].probability=0.9,v=>v.snapshot.model.triples[0].combination[0]='1',v=>v.snapshot.model.marginals[0].sixth_probability=0.9,v=>v.snapshot.deltas.triples[0].delta_probability=1,v=>v.snapshot.deltas.marginals[0].first.post_probability=0.9,v=>v.snapshot.feature_status.exhibition_video.used=true,v=>v.snapshot.feature_status.preview_st.used=true,v=>v.snapshot.feature_status.weather.used=true,v=>v.snapshot.validation_status='VALIDATED',v=>v.snapshot.purchase_recommendations=[{stake_yen:100}],v=>v.snapshot.boats[0].video_speed=10]){const raw=clone(equal.post_receipt);mutate(raw);assert.throws(()=>checked(raw));}
});
test('original savedmodel is readable beforefuturecutoff andafterclose oncurrentday',()=>{
 const before={...options(),now:Date.parse('2026-10-15T07:34:01+09:00')};checked(undefined,before);checked();assert.equal(equal.post_receipt.snapshot.feature_status.original_exhibition.used,true);assert.equal(equal.post_receipt.snapshot.feature_status.exhibition_video.used,false);
});
test('actual savedtimes cannot be future and microsecond source save order is preserved',()=>{
 assert.throws(()=>checked(undefined,{...options(),now:Date.parse(equal.now)-1}));
 const receipt=clone(equal.post_receipt);receipt.snapshot.original_link.runner_saved_at='2026-10-15T07:33:05.000001+09:00';receipt.snapshot.original_link.cloud_saved_at='2026-10-15T07:33:05.000000+09:00';assert.throws(()=>checked(receipt));
});
