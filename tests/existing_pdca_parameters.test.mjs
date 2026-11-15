// Invented fixtures only; the parameterized native kernel stays entirely offline.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {buildChallenger} from '../workers/boat_pdca_shadow.mjs';

const hash=s=>createHash('sha256').update(s).digest('hex');
const script=fileURLToPath(new URL('../scripts/existing_pdca_offline.mjs',import.meta.url));
function input(){
 const facts={schema:'RACE_AI_BOAT_OBSERVATION_V1',phase:'post_exhibition',race_id:'20301103-18-05',
  cutoff_at:'2030-11-03T10:30:00+09:00',captured_at:'2030-11-03T10:14:50+09:00',
  source_url:'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=5&jcd=18&hd=20301103',
  source_sha256:'a'.repeat(64),program_sha256:'b'.repeat(64),rights_verified:true,license_purpose:'private_analysis',
  racers:Array.from({length:6},(_,i)=>({lane:i+1,registration_no:String(i+4201),national_win_rate:5.2+i*.2,exhibition_time_seconds:6.8+i*.01}))};
 const winners=[1,1,1,1,1,1,2,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,6,6];
 const rows=winners.map((winner,i)=>{
  const report_json=JSON.stringify({race_id:`2030110${i<12?1:2}-18-${String(i%12+1).padStart(2,'0')}`,
   official_top3:[winner,...[1,2,3,4,5,6].filter(n=>n!==winner).slice(0,2)],
   source_sha256:'c'.repeat(64),captured_at:'2030-11-02T18:00:00+09:00'});
  return {report_json,report_sha256:hash(report_json),db_saved_at:'2030-11-02T18:01:00+09:00'};
 });
 return {facts,rows,now:'2030-11-03T10:15:00+09:00'};
}
function run(data){return spawnSync(process.execPath,[script],{input:JSON.stringify(data),encoding:'utf8',timeout:10000});}

test('omitted and default research pseudocount preserve native candidate bytes and inputs',async()=>{
 const data=input(),before=JSON.stringify(data),legacy=await buildChallenger(data.facts,data.rows);
 assert.equal(hash(JSON.stringify(legacy)),'48cc7c3531f6f7cff2ee9193ecde55da5be26fb939313fa7df1cfa590c0b9f72');
 assert.equal(JSON.stringify(await buildChallenger(data.facts,data.rows,{lane_pseudocount:12})),JSON.stringify(legacy));
 assert.equal(JSON.stringify(await buildChallenger(data.facts,data.rows,{})),JSON.stringify(legacy));
 assert.equal(JSON.stringify(data),before);
});

test('research pseudocount changes native lane kernel while preserving clips, mass and baseline',async()=>{
 const data=input(),original=await buildChallenger(data.facts,data.rows);
 const fitted=await buildChallenger(data.facts,data.rows,{lane_pseudocount:1});
 assert.notDeepEqual(fitted.candidate.all120,original.candidate.all120);
 assert.deepEqual(fitted.candidate.lane_winner_counts,[6,5,4,4,3,2]);
 assert.deepEqual(fitted.candidate.lane_prior_factors,[1.3,1.2,1,1,.8,.7]);
 assert.ok(Math.abs(fitted.candidate.all120.reduce((n,row)=>n+row.score,0)-1)<1e-12);
 assert.equal(fitted.candidate.ordered_top8.length,8);
 assert.equal(fitted.candidate.training_digest,original.candidate.training_digest);
 assert.equal(fitted.candidate.auto_promoted,false);
 assert.deepEqual(await buildChallenger(data.facts,data.rows),original);
});

test('offline wrapper accepts parameters as its only optional key and retains original contract',async()=>{
 const data=input(),old=run(data),configured=run({...data,parameters:{lane_pseudocount:1}});
 assert.equal(old.status,0);assert.equal(configured.status,0);
 assert.deepEqual(JSON.parse(old.stdout),await buildChallenger(data.facts,data.rows));
 assert.deepEqual(JSON.parse(configured.stdout),await buildChallenger(data.facts,data.rows,{lane_pseudocount:1}));
 assert.equal(old.stderr,'');assert.equal(configured.stderr,'');
});

test('invalid research parameters fail closed without exposing source records',async()=>{
 const data=input();
 for(const parameters of [null,[],1,{other:12},{lane_pseudocount:'12'},{lane_pseudocount:true},
  {lane_pseudocount:0},{lane_pseudocount:49},{lane_pseudocount:NaN},{lane_pseudocount:Infinity}]){
  await assert.rejects(()=>buildChallenger(data.facts,data.rows,parameters),/PDCA_PARAMETERS_INVALID/);
  const out=run({...data,parameters});
  assert.equal(out.status,2);assert.deepEqual(JSON.parse(out.stdout),{status:'PDCA_OFFLINE_REJECTED'});assert.equal(out.stderr,'');
 }
 const out=run({...data,parameters:{lane_pseudocount:1},command:'publish'});
 assert.equal(out.status,2);assert.deepEqual(JSON.parse(out.stdout),{status:'PDCA_OFFLINE_REJECTED'});assert.equal(out.stderr,'');
});

test('parameterized history still selects latest revision before excluding amended refunds',async()=>{
 const data=input(),revision=JSON.parse(data.rows[0].report_json);
 revision.refund_boats=[1];
 const report_json=JSON.stringify(revision);
 data.rows.push({report_json,report_sha256:hash(report_json),db_saved_at:'2030-11-02T18:02:00+09:00'});
 assert.deepEqual(await buildChallenger(data.facts,data.rows,{lane_pseudocount:1}),
  {status:'PDCA_NOT_ENOUGH_EARLIER_RESULTS',count:23});
});
