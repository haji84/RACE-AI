import test from 'node:test';
import assert from 'node:assert/strict';
import {createHandoff} from '../scripts/ai09-review-handoff.mjs';
const repo='haji84/RACE-AI',a='a'.repeat(40),b='b'.repeat(40);
const pr={number:65,state:'open',head:{sha:b,repo:{full_name:repo}},base:{sha:a,repo:{full_name:repo}}};
const checks=['unit (ubuntu-latest)','unit (windows-latest)','pilot'].map((name,i)=>({id:i+1,name,head_sha:b,status:'completed',conclusion:'success',app:{slug:'github-actions'}}));
const fixture=()=>({repository:repo,pr,checkRuns:checks});
test('passed checks request AI-09 but never self-approve',()=>{
 const r=createHandoff(fixture());
 assert.equal(r.nextAction,'REQUEST_AI09');
 assert.equal(r.ciReady,true);
 assert.equal(r.independentReviewVerified,false);
 assert.equal(r.mergeAuthorized,false);
});
test('pending/failed/missing/duplicate CI blocks review readiness',()=>{
 for(const altered of [[...checks.slice(1)], [...checks,{...checks[0]}],
  [{...checks[0],status:'in_progress'},...checks.slice(1)],
  [{...checks[0],conclusion:'failure'},...checks.slice(1)],
  [{...checks[0],head_sha:a},...checks.slice(1)]]){
  assert.equal(createHandoff({...fixture(),checkRuns:altered}).nextAction,'WAIT_FOR_EXACT_HEAD_CI');
 }
});
test('review assertion is advice only, Builder/Debugger must verify',()=>{
 const r=createHandoff({...fixture(),claimedReview:{headSha:b,baseSha:a,status:'CHANGES_REQUESTED'}});
 assert.equal(r.nextAction,'REQUEST_BUILDER_DEBUGGER_TRIAGE');
 assert.equal(r.correctionTask.id,'ai09:pr:65:'+b);
 assert.equal(r.correctionTask.authorizedToModifyCode,false);
 assert.equal(r.mergeAuthorized,false);
});
test('clean claim never becomes formal approval',()=>{
 const r=createHandoff({...fixture(),claimedReview:{headSha:b,baseSha:a,status:'NO_ACTIONABLE_FINDINGS'}});
 assert.equal(r.nextAction,'REQUIRE_INDEPENDENT_GATE_VERIFICATION');
 assert.equal(r.githubApprovalSatisfied,false);
});
test('stale review is ignored and re-review requested',()=>{
 const r=createHandoff({...fixture(),claimedReview:{headSha:a,baseSha:a,status:'CHANGES_REQUESTED'}});
 assert.equal(r.nextAction,'REQUEST_AI09');
});
test('untrusted repository and fork refused',()=>{
 assert.throws(()=>createHandoff({...fixture(),repository:'other/name'}),/UNTRUSTED/);
 assert.throws(()=>createHandoff({...fixture(),pr:{...pr,head:{...pr.head,repo:{full_name:'fork/name'}}}}),/UNTRUSTED/);
});