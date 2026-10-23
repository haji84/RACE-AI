import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {DatabaseSync} from 'node:sqlite';
import {GOAL,PROBES,digest,validateSnapshot,loadCore,verifyObservation,assess,importCanonical,exportCanonical} from '../scripts/race-compass-adapter.mjs';
const snapshot=()=>JSON.parse(readFileSync('docs/state/race-compass-state.json','utf8'));
const now='2026-10-23T10:00:00Z',head='a'.repeat(40);
function fixture(p){
 const run={id:p.run,head_sha:p.head,repository:{full_name:'haji84/RACE-AI'},head_branch:'feat/completion-controller-pilot-20261016',path:'.github/workflows/completion-controller-pilot.yml',event:'pull_request',run_attempt:1,status:'completed',conclusion:'success',updated_at:'2026-10-23T09:09:35Z'};
 const jobs={jobs:PROBES.filter(x=>x.run===p.run).map((x,i)=>({id:100+i,name:x.job,run_id:x.run,head_sha:x.head,status:'completed',conclusion:'success',html_url:'https://github.com/haji84/RACE-AI/actions/runs/'+x.run+'/job/'+(100+i),steps:[{name:x.step,status:'completed',conclusion:'success'}]}))};
 return {run,jobs};
}
const client=async path=>{
 if(path==='pulls/65')return {head:{sha:head,repo:{full_name:'haji84/RACE-AI'}},base:{repo:{full_name:'haji84/RACE-AI'}}};
 const id=Number(path.match(/runs\/(\d+)/)[1]),p=PROBES.find(x=>x.run===id),f=fixture(p);
 return path.includes('/jobs')?f.jobs:f.run;
};
test('pinned original Compass code loads and accepts genuine WorkState advisory',async()=>{
 const core=await loadCore();assert.equal(typeof core.CompassStore,'function');
 const a=await assess(snapshot(),{expectedHead:head,client,now});
 assert.deepEqual(a.historicalVerifiedCriteria,PROBES.map(p=>p.id));
 assert.equal(a.cycle.executionAuthority,false);assert.equal(a.currentProductVerified,false);assert.equal(a.cycle.readyForCompletionReview,false);assert.equal(a.status,'BLOCKED');
});
test('canonical schema rejects other project, self PASS, raw chat and credentials',()=>{
 for(const mutate of [
  s=>s.repository='another/project',s=>s.state.goalId='other',
  s=>s.state.verificationResults=[{itemId:'race-product',passed:true}],
  s=>s.state.status='COMPLETED',s=>s.transcript='User: secret',
  s=>s.state.decisions[0].summary='user: raw transcript',
  s=>s.state.decisions[0].summary='github_pat_supersecret123',
  s=>s.state.artifacts[0].uri='https://other.example/private'
 ]){
  const s=snapshot();mutate(s);assert.throws(()=>validateSnapshot(s));
 }
});
test('observation verification rejects stale/future, wrong repo/head, failure, skipped steps and reruns',()=>{
 const p=PROBES[0];
 for(const mutate of [
  f=>f.run.head_sha='b'.repeat(40),f=>f.run.repository.full_name='haji84/AI-',
  f=>f.run.run_attempt=2,f=>f.run.conclusion='failure',f=>f.run.status='in_progress',
  f=>f.run.updated_at='2026-10-21T09:00:00Z',f=>f.run.updated_at='2026-10-24T09:00:00Z',
  f=>f.jobs.jobs[0].conclusion='skipped',f=>f.jobs.jobs[0].steps[0].conclusion='skipped',
  f=>f.jobs.jobs=[]
 ]){
  const f=fixture(p);mutate(f);assert.throws(()=>verifyObservation(p,f.run,f.jobs,now));
 }
 const f=fixture(p);f.run.issuer='evil';const e=verifyObservation(p,f.run,f.jobs,now);
 assert.equal(e.issuer,'github-actions-public-api');assert.equal(e.artifactDigest.length,64);
});
test('current head change aborts and unavailable evidence remains BLOCKED without changing canonical',async()=>{
 const s=snapshot(),before=JSON.stringify(s);
 await assert.rejects(()=>assess(s,{expectedHead:'b'.repeat(40),client,now}),/EXECUTION_HEAD_CHANGED/);
 const offline=async p=>p==='pulls/65'?client(p):Promise.reject(Error('API_UNAVAILABLE'));
 const a=await assess(s,{expectedHead:head,client:offline,now});
 assert.equal(a.status,'BLOCKED');assert.equal(a.historicalVerifiedCriteria.length,0);assert.equal(a.errors.length,3);assert.equal(JSON.stringify(s),before);
 let reads=0;
 await assert.rejects(()=>assess(s,{expectedHead:head,now,client:async p=>{
  if(p==='pulls/65'&&++reads===2)return {head:{sha:'c'.repeat(40)}};
  return client(p);
 }}),/EXECUTION_HEAD_CHANGED/);
});
test('real SQLite close/reopen preserves canonical and unrelated state/history',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'race-compass-')),path=join(dir,'race-compass.sqlite'),s=snapshot();
 try{
  const {CompassStore}=await loadCore();const db=new CompassStore(path);
  db.updateState({active:[{kind:'unrelated',id:'keep-me'},{kind:'jarvis-owner-requirements',id:'reserved'}],decisions:[{id:'untouched'}],completed:['old']});
  for(let i=0;i<105;i++)db.writeBack({status:'BLOCKED',summary:'existing-'+i,verification:{status:'FAIL',summary:'existing verification '+i}});
  db.close();
  const raw=new DatabaseSync(path);const history=JSON.stringify(raw.prepare('SELECT * FROM history ORDER BY id').all()),verification=JSON.stringify(raw.prepare('SELECT * FROM verification ORDER BY id').all());raw.close();
  await importCanonical(path,s,{expectedDigest:digest(s),expectedRevision:1});
  assert.deepEqual(await exportCanonical(path),s);
  await importCanonical(path,s,{expectedDigest:digest(s),expectedRevision:1}); // idempotent
  const reopened=new CompassStore(path),state=reopened.getState();
  assert.deepEqual(state.active.filter(x=>x.kind!=='gai-work-state'),[{kind:'unrelated',id:'keep-me'},{kind:'jarvis-owner-requirements',id:'reserved'}]);
  assert.deepEqual(state.decisions,[{id:'untouched'}]);assert.deepEqual(state.completed,['old']);
  reopened.close();
  const after=new DatabaseSync(path);assert.equal(JSON.stringify(after.prepare('SELECT * FROM history ORDER BY id').all()),history);assert.equal(JSON.stringify(after.prepare('SELECT * FROM verification ORDER BY id').all()),verification);after.close();
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('stale snapshot digest/revision and foreign database never replace records',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'race-compass-cas-')),path=join(dir,'race-compass.sqlite'),s=snapshot();
 try{
  await assert.rejects(()=>importCanonical(path,s,{expectedDigest:'0'.repeat(64),expectedRevision:1}),/SNAPSHOT_CAS_MISMATCH/);
  await importCanonical(path,s,{expectedDigest:digest(s),expectedRevision:1});
  const next=structuredClone(s);next.state.currentState='A changed technical checkpoint.';
  await assert.rejects(()=>importCanonical(path,next,{expectedDigest:digest(next),expectedRevision:1}),/STALE_CANONICAL_UPDATE/);
  assert.deepEqual(await exportCanonical(path),s);
  const {CompassStore}=await loadCore();const db=new CompassStore(path);
  db.updateActive(active=>[...active,{kind:'gai-work-state',goalId:'other-project'}]);db.close();
  await assert.rejects(()=>importCanonical(path,s,{expectedDigest:digest(s),expectedRevision:1}),/FOREIGN_WORKSTATE/);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
