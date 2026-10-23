import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {DatabaseSync} from 'node:sqlite';
import {GOAL,PROBES,digest,validateSnapshot,loadCore,verifyObservation,assess,importCanonical,exportCanonical} from '../scripts/race-compass-adapter.mjs';
const snapshot=()=>{const s=JSON.parse(readFileSync('docs/state/race-compass-state.json','utf8'));s.revision=1;s.previousDigest=null;return s;};
const canonical=()=>JSON.parse(readFileSync('docs/state/race-compass-state.json','utf8'));
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
test('observation verification rejects future, wrong repo/head, failure, skipped steps and reruns',()=>{
 const p=PROBES[0];
 for(const mutate of [
  f=>f.run.head_sha='b'.repeat(40),f=>f.run.repository.full_name='haji84/AI-',
  f=>f.run.run_attempt=2,f=>f.run.conclusion='failure',f=>f.run.status='in_progress',
  f=>f.run.updated_at='2026-10-24T09:00:00Z',
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
  db.updateActive(active=>[...active,{kind:'jarvis-owner-requirements',id:'reserved'}]);
  assert.equal(db.getState().active.some(x=>x.kind==='jarvis-owner-requirements'),true);
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

test('old historical completion is freshly reobserved without changing original time or product state',async()=>{
 const s=snapshot(),before=JSON.stringify(s),future='2026-10-25T10:00:00Z';
 const a=await assess(s,{expectedHead:head,client,now:future});
 assert.deepEqual(a.historicalVerifiedCriteria,PROBES.map(p=>p.id));
 assert.equal(a.errors.length,0);assert.equal(a.currentProductVerified,false);
 assert.equal(a.observations[0].recordedAt,'2026-10-23T09:09:35Z');
 assert.equal(a.observations[0].observedAt,future);assert.equal(JSON.stringify(s),before);
});
test('revision2 canonical restores into a fresh database only with explicit trusted bootstrap',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'race-compass-bootstrap-')),path=join(dir,'race-compass.sqlite'),s=snapshot();
 const latest=structuredClone(s);latest.revision=2;latest.previousDigest=digest(s);latest.state.currentState='A later durable checkpoint.';
 try{
  await assert.rejects(()=>importCanonical(path,latest,{expectedDigest:digest(latest),expectedRevision:2}),/EXPLICIT_TRUSTED_BOOTSTRAP_REQUIRED/);
  await importCanonical(path,latest,{expectedDigest:digest(latest),expectedRevision:2,bootstrap:true});
  assert.deepEqual(await exportCanonical(path),latest);
  await assert.rejects(()=>importCanonical(path,s,{expectedDigest:digest(s),expectedRevision:1,bootstrap:true}),/STALE_CANONICAL_UPDATE/);
 }finally{rmSync(dir,{recursive:true,force:true});}
});

test('committed latest canonical revision can bootstrap and roundtrip with its actual hash',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'race-compass-canonical-')),path=join(dir,'race-compass.sqlite'),s=canonical();
 try{validateSnapshot(s);await importCanonical(path,s,{expectedDigest:digest(s),expectedRevision:s.revision,bootstrap:true});assert.deepEqual(await exportCanonical(path),s);}
 finally{rmSync(dir,{recursive:true,force:true});}
});

import * as adapter from '../scripts/race-compass-adapter.mjs';
test('whole product position validation is implemented separately from historical probes',()=>{
 assert.equal(typeof adapter.validateProductPosition,'function');
 assert.equal(typeof adapter.assessProductPosition,'function');
});

const product=()=>structuredClone(canonical().productPosition);
const productClient=async path=>{
 if(path.startsWith('issues/')){const s=product().sourceIssues.find(x=>path==='issues/'+x.number);return {number:s.number,html_url:'https://github.com/haji84/RACE-AI/issues/'+s.number,updated_at:s.updatedAt,body:'fixture-'+s.number};}
 if(path.startsWith('pulls/')){const p=product().pullRequests.find(x=>path==='pulls/'+x.number);return {number:p.number,head:{sha:p.head,ref:p.branch,repo:{full_name:'haji84/RACE-AI'}},base:{ref:p.base,sha:p.baseHead,repo:{full_name:'haji84/RACE-AI'}},state:p.state,draft:p.draft,merged:false};}
 if(path.startsWith('actions/runs?')){const p=product().pullRequests.find(x=>path.includes(x.head));return {total_count:1,workflow_runs:[{id:p.runId,head_sha:p.head,path:p.workflow,status:'completed',conclusion:'success',run_attempt:1}]};}
 const p=product().pullRequests.find(x=>path.startsWith('actions/runs/'+x.runId));
 if(path.includes('/jobs'))return {total_count:p.checks.length,jobs:p.checks.map((check,i)=>({id:p.runId+i,run_id:p.runId,head_sha:p.head,name:check.job,status:'completed',conclusion:'success',steps:check.steps.map(name=>({name,status:'completed',conclusion:'success'}))}))};
 return {id:p.runId,head_sha:p.head,head_branch:p.branch,repository:{full_name:'haji84/RACE-AI'},path:p.workflow,event:p.event,run_attempt:1,status:'completed',conclusion:'success',updated_at:'2026-10-23T09:00:00Z'};
};
const productFixture=()=>{const p=product();for(const s of p.sourceIssues)s.bodyDigest=digest('fixture-'+s.number);return p;};
test('product map covers source milestones and full goal without self certifying acceptance',()=>{
 const p=productFixture();adapter.validateProductPosition(p);
 assert.deepEqual(p.milestones.map(x=>x.id),['M0','M1','M2','M3','M4']);
 for(const mutate of [p=>p.goalId='haji84/AI-:other',p=>p.milestones.pop(),p=>p.finalRequirements.pop(),p=>p.acceptanceStatus='PASS',p=>p.measuredHitAt8All=.98,p=>p.milestones[0].acceptanceStatus='PASS',p=>p.automaticWriteback=true,p=>p.pullRequests[0].checks[0].steps=['Checkout'],p=>p.milestones[0].gaps=['user: raw transcript'],p=>p.nextActions[0].dependsOn=['future-evaluation']]){
  const bad=structuredClone(p);mutate(bad);assert.throws(()=>adapter.validateProductPosition(bad));
 }
});
test('exact current PR contract observations never become product acceptance or mutate canonical',async()=>{
 const p=productFixture(),before=JSON.stringify(p),a=await adapter.assessProductPosition(p,{client:productClient,now});
 assert.equal(a.errors.length,0);assert.deepEqual(a.contractVerifiedPRs,[69,71,72]);assert.equal(a.acceptanceStatus,'BLOCKED');assert.equal(a.currentProductVerified,false);assert.equal(a.automaticWriteback,false);assert.equal(a.executionAuthority,false);
 assert.equal(a.milestones.every(x=>x.acceptanceStatus==='BLOCKED'),true);assert.equal(JSON.stringify(p),before);
});
test('source edits, current head/base drift, skipped steps and unavailable evidence block fresh contract claims',async()=>{
 for(const mutate of [
  (path,v)=>{if(path==='issues/67')v.body+='changed';},
  (path,v)=>{if(path==='issues/68')v.updated_at='2026-10-23T09:59:00Z';},
  (path,v)=>{if(path==='pulls/71')v.head.sha='d'.repeat(40);},
  (path,v)=>{if(path==='pulls/72')v.base.sha='d'.repeat(40);},
  (path,v)=>{if(path.includes('/jobs'))v.jobs[0].steps[0].conclusion='skipped';},
  (path,v)=>{if(path.includes('/jobs'))v.total_count=101;},
  (path,v)=>{if(path.startsWith('actions/runs?'))v.workflow_runs[0].conclusion='failure';},
  (path,v)=>{if(path.startsWith('actions/')&&!path.includes('/jobs'))v.updated_at='2026-10-24T10:00:00Z';}
 ]){
  const p=productFixture();const a=await adapter.assessProductPosition(p,{now,client:async path=>{const v=await productClient(path);mutate(path,v);return v;}});
  assert.equal(a.acceptanceStatus,'BLOCKED');assert.ok(a.errors.length>0);assert.equal(a.currentProductVerified,false);
 }
 const a=await adapter.assessProductPosition(productFixture(),{now,client:async()=>{throw Error('API_UNAVAILABLE');}});
 assert.equal(a.contractVerifiedPRs.length,0);assert.ok(a.errors.length);
});
test('product PR head changing during observation invalidates its contract receipt',async()=>{
 let reads=0;
 const a=await adapter.assessProductPosition(productFixture(),{now,client:async path=>{const v=await productClient(path);if(path==='pulls/69'&&++reads===2)v.head.sha='f'.repeat(40);return v;}});
 assert.equal(a.contractVerifiedPRs.includes(69),false);assert.ok(a.errors.some(x=>x.includes('69')));
});
