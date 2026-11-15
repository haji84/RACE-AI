// Invented data only. Exercise the existing pure PDCA algorithm, never D1.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {buildChallenger} from '../workers/boat_pdca_shadow.mjs';
const script=fileURLToPath(new URL('../scripts/existing_pdca_offline.mjs',import.meta.url));
const hash=s=>createHash('sha256').update(s).digest('hex');
const now='2030-11-03T10:15:00+09:00';
function input(){
 const facts={schema:'RACE_AI_BOAT_OBSERVATION_V1',phase:'post_exhibition',race_id:'20301103-18-05',
  cutoff_at:'2030-11-03T10:30:00+09:00',captured_at:'2030-11-03T10:14:50+09:00',
  source_url:'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=5&jcd=18&hd=20301103',
  source_sha256:'a'.repeat(64),program_sha256:'b'.repeat(64),rights_verified:true,license_purpose:'private_analysis',
  racers:Array.from({length:6},(_,i)=>({lane:i+1,registration_no:String(i+4201),national_win_rate:5.2+i*.2,exhibition_time_seconds:6.8+i*.01}))};
 const rows=Array.from({length:24},(_,i)=>{
  const race_id=`2030110${i<12?1:2}-18-${String(i%12+1).padStart(2,'0')}`;
  const report_json=JSON.stringify({race_id,official_top3:[1,2,3],source_sha256:'c'.repeat(64),captured_at:'2030-11-02T18:00:00+09:00'});
  return {report_json,report_sha256:hash(report_json),db_saved_at:'2030-11-02T18:01:00+09:00'};
 });
 return {facts,rows,now};
}
function run(data){
 assert.ok(existsSync(script),'offline access to the existing sixteenth model must exist');
 return spawnSync(process.execPath,[script],{input:typeof data==='string'?data:JSON.stringify(data),encoding:'utf8',maxBuffer:1024*1024,timeout:10000});
}
test('offline wrapper preserves exact native PDCA candidate and training digest',async()=>{
 const data=input(),before=JSON.stringify(data),child=run(data);
 assert.equal(child.status,0,child.stderr);assert.equal(child.error,undefined);
 const got=JSON.parse(child.stdout),native=await buildChallenger(data.facts,data.rows);
 assert.deepEqual(got,native);assert.equal(got.candidate.model_id,'boat-pdca-lane-shadow-v1');
 assert.equal(got.candidate.ordered_top8.length,8);assert.equal(got.candidate.training_count,24);
 assert.equal(got.candidate.auto_promoted,false);assert.equal(JSON.stringify(data),before);
});
test('insufficient earlier history remains missing input rather than fake forecast',()=>{
 const data=input();data.rows.pop();const r=run(data);assert.equal(r.status,0);
 assert.equal(JSON.parse(r.stdout).status,'PDCA_NOT_ENOUGH_EARLIER_RESULTS');
 assert.equal(JSON.parse(r.stdout).candidate,undefined);
});
test('bad clock, future/tampered history and extra commands fail without raw data or stack',()=>{
 const cases=[{...input(),now:'2030-11-03T10:29:00+09:00'}, {...input(),now:'2030-11-03T10:15:00'}, {...input(),command:'publish'},'{invalid'];
 const tampered=input();tampered.rows[0].report_json+=' ';cases.push(tampered);
 const future=input();future.rows[0].db_saved_at='2030-11-04T00:00:00+09:00';cases.push(future);
 for(const value of cases){const r=run(value);assert.equal(r.status,2);assert.deepEqual(JSON.parse(r.stdout),{status:'PDCA_OFFLINE_REJECTED'});assert.equal(r.stderr,'');}
});
