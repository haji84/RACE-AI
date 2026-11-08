'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),U=require('../web/ui-model.js');
const top=[[1,2,3],[1,3,2],[1,2,4],[1,4,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]];
const prediction=()=>({model_id:'boat-observed-pairwise-factor-v1',stage:'P0',ordered_top8:structuredClone(top)});
const race={sport:'boat',participants:[]};

test('saved ticket composition explains the main and alternative race developments',()=>{
 const p=prediction(),before=JSON.stringify(p),value=U.forecastExplanation(race,p);
 assert.match(value.rationale,/8点/);assert.match(value.rationale,/比較/);
 assert.match(value.outlook,/1号艇.*2号艇.*3号艇/);
 assert.match(value.alternative,/2号艇.*1号艇.*3号艇/);
 assert.match(value.basis,/保存.*買い目/);
 assert.equal(JSON.stringify(p),before);
});
test('stored rationale takes precedence and explanations never use post-race results',()=>{
 const p={...prediction(),rationale:'保存した理由をそのまま表示する。'};
 const before=U.forecastExplanation(race,p);
 assert.equal(before.rationale,p.rationale);
 assert.deepEqual(U.forecastExplanation({...race,result:{status:'final',winning_combinations:[[6,5,4]],payout_yen_per_100:999999}},p),before);
 assert.equal(U.forecastExplanation(race,{...p,ordered_top8:[]}),null);
});
test('an alternative that changes only third place remains visible',()=>{
 const value=U.forecastExplanation(race,{...prediction(),ordered_top8:[[1,2,3],[1,2,4]]});
 assert.ok(value.alternative?.includes('4号艇'),'a saved third-place alternative must not disappear');
});
