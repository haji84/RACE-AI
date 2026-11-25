'use strict';
// Invented fields. These tests never load production data or a display key.
const test=require('node:test'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const M=require('../web/keirin-note-model.js'),F=require('../web/keirin-note-feed.js');
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const sourceRaw=text=>({text,bytes:Buffer.byteLength(text),sha256:sha(text)});
const source=value=>sourceRaw(JSON.stringify(value));
const date='2030-01-15',id='203001159801',prefix='data/'+date+'/';
function fixture({generated='2030-01-15T01:00:00Z',model='invented-B',withJoint=true}={}){
  const cars=[1,2,3],roster=cars.map(car=>({car,name:'架空'+car,registration:null}));
  const r={race_id:id,venue:'架空場',race_no:1,cutoff:'2030-01-15T03:00:00Z',riders:roster.map(p=>({number:p.car,name:p.name})),lines:[[1,2],[3]]};
  const inputs={schema:'RACE_AI_KEIRIN_COMPARISON_INPUTS_V1',races:[{race_id:id,cutoff_at:r.cutoff,source_as_of:'2030-01-15T00:00:00Z',forecast_generated_at:generated,roster,input:{race_id:id,riders:cars.map(car=>({car,competition_points:80})),line_groups:r.lines}}]};
  const files={};files[prefix+'races.json']=source({races:[r]});files[prefix+'comparison_inputs.json']=source(inputs);
  const triples=cars.flatMap(a=>cars.filter(b=>a!==b).flatMap(b=>cars.filter(c=>c!==a&&c!==b).map(c=>({order:[a,b,c],probability:1/6}))));
  const record={schema:'RACE_AI_KEIRIN_JOINT_PROJECTION_V1',race_id:id,generated_at:generated,cutoff_at:r.cutoff,source_as_of:inputs.races[0].source_as_of,source_forecast_generated_at:generated,
    model_id:model,model_version:'fixture-v1',input_sha256:sha(JSON.stringify(inputs.races[0].input)),source_packet_sha256:files[prefix+'comparison_inputs.json'].sha256,source_joint_sha256:'b'.repeat(64),scope:'PROSPECTIVE_RESEARCH',premise:'ALL_FINISH_NO_TIES',calibration_status:'UNVALIDATED',cars,
    riders:roster.map(p=>({...p,rank_probabilities:[1/3,1/3,1/3],top2_probability:2/3,top3_probability:1,outside_top3_probability:0,most_likely_rank:1,expected_rank:2})),ranked_markets:{'3t':triples,'2t':triples.slice(0,4).map(row=>({order:row.order.slice(0,2),probability:1/6}))}};
  if(withJoint)files[prefix+'joint_forecasts.json']=source({schema:'RACE_AI_KEIRIN_JOINT_FORECASTS_V1',races:[record]});
  return {packet:{schema:M.SCHEMA,formal_model_admission:false,production_weight_switch:false,source_commit:'c'.repeat(40),imported_at:generated,dates:[date],files},record,inputs};
}
function replace(v,name,value){v.packet.files[prefix+name]=source(value);}
function registered(v,registration){
  v.inputs.races[0].roster[0].registration=registration;replace(v,'comparison_inputs.json',v.inputs);
  v.record.source_packet_sha256=v.packet.files[prefix+'comparison_inputs.json'].sha256;v.record.riders[0].registration=registration;
  replace(v,'joint_forecasts.json',{schema:'RACE_AI_KEIRIN_JOINT_FORECASTS_V1',races:[v.record]});
  const races=JSON.parse(v.packet.files[prefix+'races.json'].text);races.races[0].riders[0].registration=registration;replace(v,'races.json',races);return v;
}
test('identity-bound supplement attaches while keeping original tickets separate',async()=>{
  const v=fixture();replace(v,'forecasts.json',[{race_id:id,tickets:[{combo:'3-2-1'}]}]);
  const row=M.rows(await M.openPacket(v.packet),date)[0];
  assert.equal(row.jointForecast.model_id,'invented-B');
  assert.equal(row.jointForecastBindings.source_packet_sha256,v.packet.files[prefix+'comparison_inputs.json'].sha256);
  assert.equal(row.jointForecastBindings.cutoff_at,v.inputs.races[0].cutoff_at);
  assert.equal(M.forecast(row,'3t','original').tickets[0].combo,'3-2-1');
});
test('a substitute source packet, rider identity or cutoff cannot acquire probabilities',async()=>{
  for(const change of [v=>{v.inputs.races[0].input.riders[0].competition_points=99;replace(v,'comparison_inputs.json',v.inputs);},v=>{v.record.riders[0].name='別人';replace(v,'joint_forecasts.json',{schema:'RACE_AI_KEIRIN_JOINT_FORECASTS_V1',races:[v.record]});},v=>{const p=JSON.parse(v.packet.files[prefix+'races.json'].text);p.races[0].cutoff='2030-01-15T04:00:00Z';replace(v,'races.json',p);},v=>{delete v.packet.files[prefix+'comparison_inputs.json'];}]){
    const v=fixture();change(v);await assert.rejects(()=>M.openPacket(v.packet));
  }
});
test('later display snapshot refreshes comparison probabilities and retains both versions',async()=>{
  const old=fixture({withJoint:false});replace(old,'forecasts.json',[{race_id:id,tickets:[{combo:'3-2-1'}]}]);
  const one=fixture(),two=fixture({generated:'2030-01-15T02:00:00Z',model:'invented-B-later'});
  const data=F.merge(await Promise.all([old.packet,one.packet,two.packet].map(p=>M.openPacket(p))));
  const row=M.rows(data,date)[0];assert.equal(row.jointForecast.model_id,'invented-B-later');
  assert.equal(row.jointForecastHistory.length,1);assert.equal(row.jointForecastHistory[0].forecast.model_id,'invented-B');
  assert.equal(row.original.tickets[0].combo,'3-2-1');
});
test('absent supplement remains unavailable and never fabricates rank probabilities',async()=>{
  const row=M.rows(await M.openPacket(fixture({withJoint:false}).packet),date)[0];assert.ok(!row.jointForecast);
});
test('a changed comparison at the same generation time cannot replace the saved version',async()=>{
  const one=fixture(),two=fixture({model:'invented-conflict'});
  const parts=await Promise.all([one.packet,two.packet].map(p=>M.openPacket(p)));
  assert.throws(()=>F.merge(parts),/KEIRIN_NOTE/);
});
test('a comparison-only roster stays fixed when another snapshot changes the rider identity',async()=>{
  const one=fixture(),two=fixture({withJoint:false}),r=JSON.parse(two.packet.files[prefix+'races.json'].text);
  r.races[0].riders[0].name='別人';replace(two,'races.json',r);
  const data=F.merge(await Promise.all([one.packet,two.packet].map(p=>M.openPacket(p))));
  assert.equal(M.rows(data,date)[0].riders[0].name,'架空1');
  assert.equal(data.refreshHolds[0].reason,'HOLD_RESEARCH_REFRESH_SOURCE_CONTEXT_CHANGED');
});
test('an invented per-race digest is rejected even when the source file digest matches',async()=>{
  const v=fixture();v.record.input_sha256='d'.repeat(64);replace(v,'joint_forecasts.json',{schema:'RACE_AI_KEIRIN_JOINT_FORECASTS_V1',races:[v.record]});
  await assert.rejects(()=>M.openPacket(v.packet));
});
test('input hashing preserves Python decimal bytes rather than reserializing browser numbers',async()=>{
  const v=fixture(),raw=JSON.stringify(v.inputs.races[0].input).replaceAll('"competition_points":80','"competition_points":80.0');
  const entry=sourceRaw(v.packet.files[prefix+'comparison_inputs.json'].text.replace(JSON.stringify(v.inputs.races[0].input),raw));
  v.packet.files[prefix+'comparison_inputs.json']=entry;v.record.source_packet_sha256=entry.sha256;v.record.input_sha256=sha(raw);
  replace(v,'joint_forecasts.json',{schema:'RACE_AI_KEIRIN_JOINT_FORECASTS_V1',races:[v.record]});
  assert.equal(M.rows(await M.openPacket(v.packet),date)[0].jointForecast.input_sha256,sha(raw));
});
test('a roster-only prior cannot attach another rider\'s first comparison',async()=>{
  const one=fixture({withJoint:false}),two=fixture(),roster=JSON.parse(one.packet.files[prefix+'races.json'].text);
  roster.races[0].riders[0].name='同じ車番の別選手';replace(one,'races.json',roster);
  const data=F.merge(await Promise.all([one.packet,two.packet].map(p=>M.openPacket(p))));
  const row=M.rows(data,date)[0];assert.ok(!row.jointForecast);assert.equal(data.refreshHolds.length,1);
});
test('known conflicting registration IDs cannot replace a same-name rider',async()=>{
  const one=registered(fixture(),'111111'),two=registered(fixture({generated:'2030-01-15T02:00:00Z'}),'222222');
  const data=F.merge(await Promise.all([one.packet,two.packet].map(p=>M.openPacket(p))));
  const row=M.rows(data,date)[0];assert.equal(row.jointForecast.riders[0].registration,'111111');assert.equal(data.refreshHolds.length,1);
  const v=registered(fixture(),'222222'),races=JSON.parse(v.packet.files[prefix+'races.json'].text);races.races[0].riders[0].registration='111111';replace(v,'races.json',races);
  await assert.rejects(()=>M.openPacket(v.packet));
});
