const test=require('node:test'),assert=require('node:assert/strict');
const U=require('../web/ui-model.js'),C=require('../web/existing-model-catalog.js');
const A='boat-observed-pairwise-factor-v1',B='boat-observed-pairwise-start-v1';
const rows=[{sport:'boat',race_id:'one',prediction:{model_id:A},comparison_predictions:[{model_id:B},{model_id:A},{model_id:'seller-shadow-v1-20261104'}]},
  {sport:'boat',race_id:'two',prediction:{model_id:A},comparison_predictions:[]}];
test('model options count distinct saved races and include applicable missing models without reviving retired ones',()=>{
  assert.equal(typeof U.modelOptions,'function');const before=JSON.stringify(rows),out=U.modelOptions(rows,C,'boat');
  assert.equal(out.find(m=>m.model_id===A).races,2);assert.equal(out.find(m=>m.model_id===B).races,1);
  assert.equal(out.find(m=>m.model_id==='boat-comprehensive-v1').races,0);
  assert.ok(!out.some(m=>m.model_id==='seller-shadow-v1-20261104'||m.model_id==='autorace-personal-observed-baseline-v1'));
  assert.equal(JSON.stringify(rows),before);
});
test('selected model resolves only its own original while preserving a matching selected version',()=>{
  assert.equal(typeof U.modelPrediction,'function');const list=[{model_id:A,stage:'P0'},{model_id:B,stage:'P1'},{model_id:A,stage:'P1'}];
  assert.equal(U.modelPrediction(list,A,2),list[2]);assert.equal(U.modelPrediction(list,B,2),list[1]);
  assert.equal(U.modelPrediction(list,'missing',0),null);assert.equal(U.modelPrediction(list,null,1),list[1]);
});
