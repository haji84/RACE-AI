// Fictional sources; only pure inference and the bounded local wrapper run.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {assertFacts,predict} from '../workers/boat_nonvercel_core.mjs';
import {buildChallenger} from '../workers/boat_pdca_shadow.mjs';

const now='2030-11-03T10:15:00+09:00';
const hash=s=>createHash('sha256').update(s).digest('hex');
const script=fileURLToPath(new URL('../scripts/existing_pdca_offline.mjs',import.meta.url));
function input(lanes){
 const facts={schema:'RACE_AI_BOAT_OBSERVATION_V1',phase:'post_exhibition',race_id:'20301103-18-05',
  cutoff_at:'2030-11-03T10:30:00+09:00',captured_at:'2030-11-03T10:14:50+09:00',
  source_url:'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=5&jcd=18&hd=20301103',
  source_sha256:'a'.repeat(64),program_sha256:'b'.repeat(64),rights_verified:true,license_purpose:'private_analysis',
  racers:lanes.map(lane=>({lane,registration_no:String(4200+lane),national_win_rate:5+lane*.2,exhibition_time_seconds:6.8+lane*.01}))};
 const rows=Array.from({length:24},(_,i)=>{
  const race_id=`2030110${i<12?1:2}-18-${String(i%12+1).padStart(2,'0')}`;
  const report_json=JSON.stringify({race_id,official_top3:[1,2,3],source_sha256:'c'.repeat(64),captured_at:'2030-11-02T18:00:00+09:00'});
  return {report_json,report_sha256:hash(report_json),db_saved_at:'2030-11-02T18:01:00+09:00'};
 });
 return {facts,rows,now};
}
function checkDistribution(entries,lanes){
 const expected=[];
 for(const a of lanes)for(const b of lanes)for(const c of lanes)if(a!==b&&a!==c&&b!==c)expected.push([a,b,c].join('-'));
 assert.deepEqual(new Set(entries.map(x=>x.ticket.join('-'))),new Set(expected));
 assert.equal(entries.length,lanes.length*(lanes.length-1)*(lanes.length-2));
 assert.ok(entries.every(x=>Number.isFinite(x.score)&&x.score>=0));
 assert.ok(Math.abs(entries.reduce((n,x)=>n+x.score,0)-1)<1e-9);
}

for(const lanes of [[1,3,6],[1,2,4,6],[1,3,4,5,6],[1,2,3,4,5,6]]){
 test(`local PDCA enumerates physical active lanes ${lanes.join(',')}`,async()=>{
  const data=input(lanes),before=structuredClone(data);
  assert.doesNotThrow(()=>assertFacts(data.facts,Date.parse(now)));
  const baseline=predict(data.facts);checkDistribution(baseline.all120,lanes);
  assert.equal(baseline.top8.length,Math.min(8,baseline.all120.length));
  const pure=await buildChallenger(data.facts,data.rows);
  checkDistribution(pure.candidate.all120,lanes);
  assert.equal(pure.candidate.ordered_top8.length,Math.min(8,pure.candidate.all120.length));
  assert.equal(pure.candidate.model_id,'boat-pdca-lane-shadow-v1');
  assert.equal(pure.candidate.probabilities_calibrated,false);
  const child=spawnSync(process.execPath,[script],{input:JSON.stringify(data),encoding:'utf8',timeout:10000});
  assert.equal(child.status,0,child.stdout);assert.equal(child.stderr,'');
  assert.deepEqual(JSON.parse(child.stdout),pure);
  assert.deepEqual(data,before);
 });
}

test('active roster failures stay fail closed without inventing missing exhibitions',()=>{
 for(const mutate of [f=>f.racers.pop(),f=>f.racers[1].lane=1,f=>f.racers[1].exhibition_time_seconds=null,
  f=>f.racers[1].registration_no=f.racers[0].registration_no,f=>f.racers[1].lane=true,
  f=>f.captured_at='2030-11-03T10:16:00+09:00']){
  const {facts}=input([1,3,6]);mutate(facts);assert.throws(()=>assertFacts(facts,Date.parse(now)));
 }
});

test('three extreme valid strengths keep finite probability mass',async()=>{
 const {facts,rows}=input([1,3,6]);
 for(const row of facts.racers){row.national_win_rate=row.lane===1?10:0;row.exhibition_time_seconds=row.lane===1?4:12;}
 checkDistribution(predict(facts).all120,[1,3,6]);
 checkDistribution((await buildChallenger(facts,rows)).candidate.all120,[1,3,6]);
});
