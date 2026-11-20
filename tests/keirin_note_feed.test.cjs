'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {packet,source}=require('./keirin_note_model.test.cjs');
const M=require('../web/keirin-note-model.js'),F=require('../web/keirin-note-feed.js');
function freshPacket(changed=false){const p=packet();delete p.files['data/2030-01-15/forecasts.json'];delete p.files['data/2030-01-15/flexible_forecasts.json'];const name='data/2030-01-15/races.json',roster=JSON.parse(p.files[name].text);roster.races[0].riders.forEach(r=>r.score=95);if(changed){roster.races[0].riders[2].number=4;roster.races[0].riders[2].name='別の架空選手';}p.files[name]=source(roster);const refs=JSON.parse(p.files['data/2030-01-15/reference_AB.json'].text);refs[0].output.A.ranked_tickets=[[2,changed?4:3,1]];refs[0].output.B.ranked_tickets=[[2,changed?4:3,1]];p.files['data/2030-01-15/reference_AB.json']=source(refs);return p;}
test('a changed research roster cannot invalidate preserved authored tickets',async()=>{const original=await M.openPacket(packet()),fresh=await M.openPacket(freshPacket(true));const data=F.merge([original,fresh]),row=M.rows(data,'2030-01-15')[0];assert.equal(M.forecast(row,'3t','original').tickets[0].combo,'1-2-3');assert.equal(row.riders[2].number,3);assert.equal(data.refreshHolds.length,1);});
test('matching reference refreshes retain the authored source context',async()=>{const original=await M.openPacket(packet()),fresh=await M.openPacket(freshPacket());const data=F.merge([original,fresh]),row=M.rows(data,'2030-01-15')[0];assert.equal(row.riders[0].score,80);assert.equal(M.forecast(row,'3t','A').tickets[0].combo,'2-3-1');assert.equal(M.forecast(row,'3t','original').tickets[0].combo,'1-2-3');assert.equal(row.referenceHistory.length,1);});

const RF=require('./keirin_note_result_fixtures.cjs');
test('old indexes remain valid and optional result checks do not increase forecast coverage',()=>{
 const old=RF.index();assert.equal(F.checkIndex(old,'a'.repeat(64)),old);
 const fresh=RF.index('results');fresh.result_checks={[RF.RACE]:{checked_at:'2030-01-15T03:10:00Z',digest:RF.observation().observation_sha256,status:'MATCHED'}};
 assert.equal(F.checkIndex(fresh,'a'.repeat(64)),fresh);assert.deepEqual(fresh.covered_race_ids,[]);
 for(const change of [i=>i.result_checks[RF.RACE].extra=true,i=>i.result_checks[RF.RACE].digest='bad',i=>i.result_checks[RF.RACE].digest=null,i=>i.result_checks[RF.RACE].status='OFFICIAL',i=>i.result_checks[RF.RACE].checked_at='2030-01-15T12:10:00+09:00',i=>i.entries[0].captured_race_ids=[RF.RACE]]){const i=structuredClone(fresh);change(i);assert.throws(()=>F.checkIndex(i,'a'.repeat(64)));}
});
test('latest disagreement overrides a match without replacing original forecasts or losing bound reference revisions',async()=>{
 const original=await M.openPacket(packet()),refresh=await M.openPacket(freshPacket()),matched=RF.observation();
 const held=RF.observation({state:'HOLD_SECONDARY_RESULT_DISAGREEMENT',previous:matched.observation_sha256,at:'2030-01-15T03:20:00Z'});
 const data=F.merge([original,refresh,await M.openPacket(RF.resultsPacket([matched])),await M.openPacket(RF.resultsPacket([held]))]),row=M.rows(data,RF.DAY)[0];
 assert.equal(row.latestResult.observation.state,'HOLD_SECONDARY_RESULT_DISAGREEMENT');assert.equal(row.resultHistory.length,2);assert.equal(M.compare(row,'3t','A').status,'RESEARCH_UNKNOWN');
 assert.deepEqual(row.original,M.rows(original,RF.DAY)[0].original);assert.deepEqual(row.flexible,M.rows(original,RF.DAY)[0].flexible);
 assert.equal(row.referenceHistory.length,1);assert.deepEqual(row.referenceHistory[0].binding,M.rows(original,RF.DAY)[0].bindings.reference);
 assert.equal(row.bindings.reference.fileSha256,freshPacket().files['data/'+RF.DAY+'/reference_AB.json'].sha256);
 assert.equal(row.bindings.original.fileSha256,packet().files['data/'+RF.DAY+'/forecasts.json'].sha256);
 assert.equal(M.rows(original,RF.DAY)[0].resultHistory.length,0);
});
test('revision chain rejects missing or reversed predecessors and preserves a genuine fact reversion',async()=>{
 const first=RF.observation(),held=RF.observation({state:'HOLD_SECONDARY_RESULT_DISAGREEMENT',previous:first.observation_sha256,at:'2030-01-15T03:20:00Z'}),again=RF.observation({previous:held.observation_sha256,at:'2030-01-15T03:30:00Z'});
 const parts=await Promise.all([packet(),RF.resultsPacket([first]),RF.resultsPacket([held]),RF.resultsPacket([again])].map(p=>M.openPacket(p)));
 const row=M.rows(F.merge(parts),RF.DAY)[0];assert.equal(row.resultHistory.length,3);assert.equal(M.compare(row,'3t','A').status,'RESEARCH_HIT');
 assert.throws(()=>F.merge([parts[0],parts[2]]));assert.throws(()=>F.merge([parts[0],parts[2],parts[1]]));
 const wrong=RF.observation({triple:[3,1,4]});assert.throws(()=>F.merge([parts[0],parts[1],{...parts[1],results:new Map([[RF.RACE,[{observation:wrong,binding:{}}]]])}]));
});
test('aggregate comparison pairs only the same races and keeps unknowns outside the scored denominator',async()=>{
 const first=RF.observation(),base=await M.openPacket(packet()),data=F.merge([base,await M.openPacket(RF.resultsPacket([first]))]);
 const summary=M.summarize(M.rows(data,RF.DAY),'3t');
 assert.equal(summary.raceCount,1);assert.equal(summary.pairedRaceCount,1);assert.equal(summary.A.evaluableRaces,1);assert.equal(summary.B.evaluableRaces,1);assert.equal(summary.A.hitRaces,1);assert.equal(summary.B.hitRaces,0);assert.equal(summary.formal,false);assert.equal(summary.improvementProven,false);
 const held=RF.observation({state:'HOLD_SECONDARY_RESULT_DISAGREEMENT',previous:first.observation_sha256,at:'2030-01-15T03:20:00Z'}),row=M.rows(F.merge([base,await M.openPacket(RF.resultsPacket([first,held]))]),RF.DAY)[0];
 const next=M.summarize([row],'3t');assert.equal(next.pairedRaceCount,0);assert.equal(next.A.unknownRaces,1);assert.equal(next.A.evaluableRaces,0);
});
test('paired A/B totals use exactly the common evaluated race set even when one reference is missing',async()=>{
 const p=packet(),second='203001159802',roster=JSON.parse(p.files['data/'+RF.DAY+'/races.json'].text),refs=JSON.parse(p.files['data/'+RF.DAY+'/reference_AB.json'].text);
 roster.races.push({...roster.races[0],race_id:second,race_no:2});refs.push({input:{race_id:second},output:{race_id:second,A:{ranked_tickets:[[3,1,2]]}}});p.files['data/'+RF.DAY+'/races.json']=source(roster);p.files['data/'+RF.DAY+'/reference_AB.json']=source(refs);
 const data=F.merge([await M.openPacket(p),await M.openPacket(RF.resultsPacket([RF.observation(),RF.observation({race:second})]))]),s=M.summarize(M.rows(data,RF.DAY));
 assert.equal(s.A.evaluableRaces,2);assert.equal(s.B.evaluableRaces,1);assert.equal(s.pairedRaceCount,1);assert.equal(s.paired.A.evaluableRaces,1);assert.equal(s.paired.A.hitRaces,1);assert.equal(s.paired.B.hitRaces,0);
});
test('a results-kind entry cannot smuggle forecast files under zero forecast coverage',async()=>{
 const wrong=await RF.encryptedEntry(packet(),'results');await assert.rejects(()=>F.openEntry(wrong.wire,wrong.entry,wrong.cap));
 const good=await RF.encryptedEntry(RF.resultsPacket([RF.observation()]),'results'),data=await F.openEntry(good.wire,good.entry,good.cap);
 assert.equal(M.rows(data,RF.DAY).length,0);assert.equal(data.results.get(RF.RACE).length,1);assert.equal(data.cipherSha,good.entry.cipher_sha256);
 const wrongSource={...good.entry,source_content_sha256:'0'.repeat(64)};await assert.rejects(()=>F.openEntry(good.wire,wrongSource,good.cap));
});
