'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),cp=require('node:child_process');
const D=require('../web/product-data.js'),P=require('../web/saved-performance.js');
function fixture(kind='P0') {
 const run=cp.spawnSync('python',['-c',
  "import json;from tests.test_boat_saved_prediction_evidence import original_view;from race_ai.boat_saved_prediction_evidence import hydrate_prediction_evidence;v,_,r,m=original_view('"+kind+"');print(json.dumps(hydrate_prediction_evidence(v,[(r,m)])[0],ensure_ascii=False))"],{cwd:require('node:path').join(__dirname,'..'),encoding:'utf8'});
 assert.equal(run.status,0,run.stderr);return JSON.parse(run.stdout);
}
const raw=fixture();
test('authenticated native invocation evidence admits an omitted-clock plan without filling its original generation field',()=>{
 const view=D.parse(raw),r=view.records[0],p=r.prediction,g=D.modelGroups(view.records)[0];
 assert.equal(p.generated_at,null);assert.equal(p.model_version,null);
 const t=P.simulate(view.records,g,10000,{raceBudget:800});
 assert.equal(t.bought,1);assert.equal(t.spent,800);assert.equal(t.pendingStake,800);
 assert.equal(typeof D.effectivePredictionFacts,'function');
 const facts=D.effectivePredictionFacts(r,p);assert.equal(facts.model_version,'0.1.0-UNTRAINED');assert.equal(facts.generated_at,null);
 assert.equal(facts.clock_kind,'NATIVE_ASOF_AND_COMPLETION_UPPER_BOUND');
 assert.equal(p.generated_at,null);assert.equal(p.input_sha256,null);
 assert.equal(D.summary(view.records).overall.evaluable,0);
});
test('an unbound or changed original cannot inherit recovered clocks or input seals',()=>{
 for(const change of [v=>{v.records[0].prediction.calibrated=!v.records[0].prediction.calibrated;},
  v=>{Object.values(v.records[0].saved_prediction_evidence)[0].native.as_of='2030-04-01T01:44:00Z';},
  v=>{Object.values(v.records[0].saved_prediction_evidence)[0].artifact.head_sha='b'.repeat(40);},
  v=>{Object.values(v.records[0].saved_prediction_evidence)[0].native.generated_at='2030-04-01T02:00:00Z';}]) {
  const changed=structuredClone(raw);change(changed);assert.throws(()=>D.parse(changed));
 }
 const missing=structuredClone(raw);delete missing.records[0].saved_prediction_evidence;
 const parsed=D.parse(missing);assert.equal(P.simulate(parsed.records,D.modelGroups(parsed.records)[0],10000).bought,0);
});
test('native learned facts are recovered for comparison without changing original model groups',()=>{
 const v=D.parse(fixture('P1')),r=v.records[0],ps=D.candidates(r),learned=ps.filter(p=>p.variant==='LEARNED_SHADOW');
 assert.equal(learned.length,2);
 for(const p of learned){const b=ps.find(q=>q.prediction_sha256===p.baseline_model_sha256),a=D.effectivePredictionFacts(r,p),f=D.effectivePredictionFacts(r,b);assert.equal(a.input_sha256,f.input_sha256);assert.ok(a.model_version);assert.equal(p.input_sha256,null);}
 assert.equal(D.modelGroups(v.records).length,7);
 assert.equal(D.modelGroups(v.records).reduce((n,g)=>n+P.simulate(v.records,g,10000).bought,0),7);
});
test('recovered metadata cannot make 1000-yen allocation depend on outcomes or double count history siblings',()=>{
 const v=D.parse(raw),r=structuredClone(raw.records[0]),p=r.prediction;
 const before=P.allocate(r,p,1000);r.result={status:'final',winning_combinations:[[6,5,4]],payout_yen_per_100:999999};
 assert.deepEqual(P.allocate(r,p,1000),before);
 const only=structuredClone(raw.records[0]);only.comparison_predictions=[];
 only.saved_prediction_evidence=Object.fromEntries(Object.entries(only.saved_prediction_evidence).filter(([,e])=>e.saved_prediction_identity===D.savedPredictionIdentity(only.prediction)));
 const sibling=structuredClone(only.prediction);sibling.variant='HISTORY_ADDED';only.comparison_predictions=[sibling];
 // The sibling has no evidence of its own, and correlated variants add no family.
 assert.equal(P.allocate(only,only.prediction,1000).held,200);
});
test('removed evidence cannot remain trusted through a cached mutable prediction',()=>{
 const row=structuredClone(raw.records[0]),p=row.prediction;
 assert.equal(P.planReason(row,p),null);
 delete row.saved_prediction_evidence;
 assert.equal(P.planReason(row,p),'SAVE_CLOCK_UNKNOWN');
});
test('a frozen row can mix hydrated and untouched originals without rebinding browser-mutated bodies',()=>{
 const mixed=structuredClone(raw),p=structuredClone(mixed.records[0].prediction);
 p.model_id='uncovered-model';p.model_version='v-uncovered';p.generated_at=p.as_of;
 mixed.records[0].comparison_predictions.push(p);
 const v=D.parse(mixed),group=D.modelGroups(v.records).find(g=>g.model_id==='uncovered-model');
 assert.equal(P.simulate(v.records,group,10000).bought,1);
 assert.equal(D.effectivePredictionFacts(v.records[0],v.records[0].comparison_predictions.at(-1)).native_evidence,false);
});
test('content binding survives original JSON number spellings and Unicode without browser-only crypto',()=>{
 const source=cp.spawnSync('python',['-c',"import json;from tests.test_boat_saved_prediction_evidence import original_view;from race_ai.boat_saved_prediction_evidence import hydrate_prediction_evidence;v,_,r,m=original_view();v['records'][0]['prediction']['numeric_binding_fixture']={'根拠😀':[0.0,1e-20,1e20], '𐀀':'long unicode', '':'other unicode'};print(json.dumps(hydrate_prediction_evidence(v,[(r,m)])[0],ensure_ascii=False))"],{cwd:require('node:path').join(__dirname,'..'),encoding:'utf8'});
 assert.equal(source.status,0,source.stderr);
 const parsed=D.parse(source.stdout);assert.equal(P.simulate(parsed.records,D.modelGroups(parsed.records)[0],10000).bought,1);
 const changed=JSON.parse(source.stdout);changed.records[0].prediction.numeric_binding_fixture['根拠😀'][1]=1e-19;
 assert.throws(()=>D.parse(changed));
});
