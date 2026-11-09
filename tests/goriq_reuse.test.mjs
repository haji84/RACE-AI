import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, cp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { loadPinnedCore, preflightRace, reviewRace, makeGithubGet, loopbackInfer } from '../scripts/race-goriq-review.mjs';

const head = 'a'.repeat(40), base = 'b'.repeat(40);
const request = {repository:'haji84/RACE-AI',prNumber:69,headSha:head,baseSha:base,ciRunId:100};
const names = ['Synthetic E2E (ubuntu-24.04)','Synthetic E2E (windows-2022)','unit'];
function fixture() {
  const repo = {id:1416489937,full_name:request.repository};
  return {
    pr:{number:69,state:'open',merged:false,changed_files:1,head:{sha:head,repo},base:{sha:base,ref:'main',repo}},
    run:{id:100,name:'Four sport synthetic E2E',path:'.github/workflows/four-sport-synthetic.yml',
      event:'pull_request',status:'completed',conclusion:'success',head_sha:head,run_attempt:1,
      repository:repo,check_suite_id:1000,pull_requests:[{number:69,head:{sha:head,repo},base:{sha:base,repo}}]},
    checks:{total_count:3,check_runs:names.map((name,i)=>({id:10+i,name,head_sha:head,
      app:{id:15368,slug:'github-actions'},check_suite:{id:1000},status:'completed',conclusion:'success',
      details_url:'https://github.com/haji84/RACE-AI/actions/runs/100/job/'+(10+i)}))},
    compare:{status:'ahead',ahead_by:1,total_commits:1,base_commit:{sha:base},merge_base_commit:{sha:base},
      commits:[{sha:head}],files:[{filename:'src/sample.mjs',additions:1,deletions:0,
        patch:'@@ -0,0 +1 @@\n+export const sample = 42;'}]},
  };
}
function apiFor(data, mutateSecond) {
  const calls=[], counts={};
  const api=async path=>{
    calls.push(path); counts[path]=(counts[path]||0)+1;
    const key=path.startsWith('/pulls/')?'pr':path.startsWith('/actions/runs/')?'run':
      path.startsWith('/commits/')?'checks':path.startsWith('/compare/')?'compare':path.startsWith('/contents/')?'contents':null;
    assert.ok(key,'unexpected API request');
    const value=structuredClone(data[key]);
    if(counts[path]===2)mutateSecond?.(key,value);
    return value;
  };
  return {api,calls};
}
const clean = async ()=>JSON.stringify({verdict:'NO_FINDINGS',findings:[]});
const core = await loadPinnedCore();

test('loads unchanged pinned GORIQ modules and retains their actual limits',()=>{
  assert.equal(core.upstreamSha,'accf8294ff936b73b93e21667d92bc1b52aa8428');
  assert.equal(typeof core.reviewLocalPatch,'function');
  const f=fixture(); f.compare.files[0].patch+='\n+'+'x'.repeat(5000); f.compare.files[0].additions++;
  assert.throws(()=>core.compareToReviewChunks(f.compare,base,head),/oversized/);
});
test('preflight is read only and never invokes inference',async()=>{
  const {api,calls}=apiFor(fixture());
  const ready=await preflightRace(request,{api,core});
  assert.equal(ready.chunkCount,1); assert.equal(ready.modelInvoked,false);
  assert.equal(ready.mergeAuthorized,false); assert.equal(calls.length,4);
});
test('real GORIQ engine accepts fixture inference without claiming formal approval',async()=>{
  const {api,calls}=apiFor(fixture()); let models=0;
  const receipt=await reviewRace(request,{api,core,infer:async prompt=>{
    models++; assert.ok(prompt.includes('BEGIN_UNTRUSTED_PATCH')); assert.ok(prompt.includes('sample = 42'));
    assert.ok(!prompt.includes('GITHUB_TOKEN')); return clean();
  }});
  assert.equal(models,1); assert.equal(calls.length,7);
  assert.equal(receipt.reviewerResult.status,'NO_ACTIONABLE_FINDINGS');
  assert.equal(receipt.reviewerResult.githubApprovalSatisfied,false);
  assert.equal(receipt.reviewerResult.mergeAuthorized,false);
  assert.equal(receipt.reviewerResult.independentGitHubAccountVerified,false);
});
const invalid = [
  ['foreign PR',f=>f.pr.head.repo={id:22,full_name:'attacker/fork'}],
  ['wrong repository id',f=>{f.pr.head.repo.id=9;}],
  ['moved head',f=>f.pr.head.sha='c'.repeat(40)],
  ['moved base',f=>f.pr.base.sha='c'.repeat(40)],
  ['closed PR',f=>f.pr.state='closed'],
  ['wrong base branch',f=>f.pr.base.ref='development'],
  ['failed CI',f=>f.run.conclusion='failure'],
  ['wrong workflow',f=>f.run.path='.github/workflows/attacker.yml'],
  ['wrong event',f=>f.run.event='workflow_dispatch'],
  ['wrong linked base',f=>f.run.pull_requests[0].base.sha='c'.repeat(40)],
  ['wrong suite',f=>f.checks.check_runs[0].check_suite.id=123],
  ['wrong app',f=>f.checks.check_runs[0].app.id=12],
  ['wrong run URL',f=>f.checks.check_runs[0].details_url='https://github.com/haji84/RACE-AI/actions/runs/101/job/10'],
  ['skipped required check',f=>f.checks.check_runs[0].conclusion='skipped'],
  ['duplicate check',f=>{f.checks.check_runs.push({...f.checks.check_runs[0]}); f.checks.total_count++;}],
  ['pagination incomplete',f=>f.checks.total_count=101],
  ['missing file',f=>f.pr.changed_files=2],
  ['truncated hunk',f=>f.compare.files[0].additions=2],
  ['wrong compare head',f=>f.compare.commits[0].sha='c'.repeat(40)],
  ['wrong merge base',f=>f.compare.merge_base_commit.sha='c'.repeat(40)],
];
for(const [label,mutate] of invalid)test('rejects '+label+' before model',async()=>{
  const f=fixture(); mutate(f); const {api}=apiFor(f); let models=0;
  await assert.rejects(reviewRace(request,{api,core,infer:async()=>{models++; return clean();}}));
  assert.equal(models,0);
});
for(const field of ['pr','run','checks'])test('rechecks '+field+' after model',async()=>{
  const {api}=apiFor(fixture(),(key,x)=>{
    if(key===field){if(key==='pr')x.head.sha='c'.repeat(40);if(key==='run')x.run_attempt++;if(key==='checks')x.check_runs[0].id++;}
  });
  await assert.rejects(reviewRace(request,{api,core,infer:clean}));
});
test('partial or invalid model output is HOLD, never a clean receipt',async()=>{
  const {api}=apiFor(fixture());
  const receipt=await reviewRace(request,{api,core,infer:async()=>'{bad'});
  assert.equal(receipt.reviewerResult.status,'BLOCKED');
});
test('ungrounded finding stays inconclusive',async()=>{
  const {api}=apiFor(fixture());
  const receipt=await reviewRace(request,{api,core,infer:async()=>JSON.stringify({verdict:'CHANGES_REQUESTED',
    findings:[{path:'src/sample.mjs',line:999,severity:'high',summary:'Claim',evidence:'Unverified assumption',proposedFix:'Investigate'}]})});
  assert.equal(receipt.reviewerResult.status,'INCONCLUSIVE');
});
test('rejects secret-like model text before producing publishable receipt',async()=>{
  const {api}=apiFor(fixture());
  await assert.rejects(reviewRace(request,{api,core,infer:async()=>JSON.stringify({verdict:'CHANGES_REQUESTED',
    findings:[{path:'src/sample.mjs',line:1,severity:'high',summary:'github_pat_'+'a'.repeat(30),
      evidence:'`export const sample = 42;`',proposedFix:'Investigate'}]})}),/RECEIPT/);
});
test('mutated upstream code is rejected before module evaluation',async()=>{
  const root=await mkdtemp(join(tmpdir(),'race-goriq-test-'));
  try {
    await cp(fileURLToPath(new URL('../vendor/goriq-ai09/',import.meta.url)),root,{recursive:true});
    const file=join(root,'src/orchestrator/ai09-local-reviewer.mjs');
    await writeFile(file,(await readFile(file))+'\nthrow new Error("MUTATION_EXECUTED");');
    await assert.rejects(loadPinnedCore(root),/GORIQ_SOURCE_INTEGRITY/);
  } finally {await rm(root,{recursive:true,force:true});}
});
test('GitHub transport has fixed GET origin, redirect error, no retries, and bounded JSON',async()=>{
  let count=0;
  const api=makeGithubGet(async(url,options)=>{
    count++; assert.ok(url.startsWith('https://api.github.com/repos/haji84/RACE-AI/'));
    assert.equal(options.method,'GET'); assert.equal(options.redirect,'error');
    assert.equal(options.headers.Authorization,undefined); return new Response('{"ok":true}');
  });
  assert.deepEqual(await api('/pulls/69'),{ok:true});
  for(const path of ['https://evil.test','/issues/69/comments','/pulls/69?redirect=evil','/../secrets'])
    await assert.rejects(api(path));
  assert.equal(count,1);
  const fail=makeGithubGet(async()=>{count++;return new Response('',{status:403});});
  await assert.rejects(fail('/pulls/69'),/GITHUB_GET_FAILED/); assert.equal(count,2);
  await assert.rejects(makeGithubGet(async()=>new Response('x'.repeat(2*1024*1024+1)))('/pulls/69'),/BODY/);
});
test('loopback inference reuses model and never accepts remote fallback or redirects',async()=>{
  let count=0;
  const infer=loopbackInfer(async(url,options)=>{
    count++; assert.equal(url,'http://127.0.0.1:11434/api/chat'); assert.equal(options.redirect,'error');
    assert.equal(options.headers.Authorization,undefined); const body=JSON.parse(options.body);
    assert.equal(body.model,'qwen2.5-coder:3b'); assert.equal(body.stream,false);
    return Response.json({message:{content:'{"verdict":"NO_FINDINGS","findings":[]}'}});
  });
  assert.equal(typeof await infer('safe fixture'), 'string'); assert.equal(count,1);
});
test('unproven added empty files remain HOLD before model',async()=>{
  const f=fixture(); Object.assign(f.compare.files[0],{patch:undefined,sha:'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
    additions:0,deletions:0,changes:0,status:'added'});
  let models=0; const {api}=apiFor(f);
  await assert.rejects(reviewRace(request,{api,core,infer:async()=>{models++;return clean();}}));
  assert.equal(models,0);
});
test('25 chunks require two complete upstream-limited batches',async()=>{
  const f=fixture(); f.pr.changed_files=25;
  f.compare.files=Array.from({length:25},(_,i)=>({...f.compare.files[0],filename:'src/file'+i+'.mjs'}));
  let models=0; const {api}=apiFor(f);
  const receipt=await reviewRace(request,{api,core,infer:async()=>{models++;return clean();}});
  assert.equal(models,25);assert.equal(receipt.batchCount,2);
  assert.equal(receipt.reviewedChunks,25);assert.equal(receipt.reviewerResult.status,'NO_ACTIONABLE_FINDINGS');
});
test('empty metadata requires contents from the exact reviewed head, before model',async()=>{
  const f=fixture();f.pr.changed_files=2;
  f.compare.files.push({filename:'tests/__init__.py',status:'added',sha:'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
    additions:0,deletions:0,changes:0});
  f.contents={path:'tests/__init__.py',type:'file',size:0,sha:f.compare.files[1].sha,encoding:'base64',content:''};
  const {api,calls}=apiFor(f);let models=0;
  const receipt=await reviewRace(request,{api,core,infer:async prompt=>{
    if(++models===2)assert.match(prompt,/AI09_VERIFIED_EMPTY_FILE_ADDITION/);return clean();}});
  assert.ok(calls.includes('/contents/tests/__init__.py?ref='+head));
  assert.equal(models,2);assert.equal(receipt.reviewerResult.status,'NO_ACTIONABLE_FINDINGS');
});
test('multiple chunks with a later model failure never produce a clean receipt',async()=>{
  const f=fixture(); const lines=Array.from({length:120},(_,i)=>'export const value'+i+' = "'+'x'.repeat(36)+'";');
  f.compare.files[0].patch='@@ -0,0 +1,120 @@\n'+lines.map(l=>'+'+l).join('\n'); f.compare.files[0].additions=120;
  let calls=0; const {api}=apiFor(f);
  const receipt=await reviewRace(request,{api,core,infer:async()=>++calls===1?clean():'invalid'});
  assert.ok(calls>=2); assert.equal(receipt.reviewerResult.status,'BLOCKED');
});
test('an anchored finding is advisory and cannot authorize a merge',async()=>{
  const {api}=apiFor(fixture());
  const receipt=await reviewRace(request,{api,core,infer:async()=>JSON.stringify({verdict:'CHANGES_REQUESTED',
    findings:[{path:'src/sample.mjs',line:1,severity:'medium',summary:'Review claim',
      evidence:'`export const sample = 42;`',proposedFix:'Check intended behavior'}]})});
  assert.equal(receipt.reviewerResult.status,'CHANGES_REQUESTED'); assert.equal(receipt.reviewerResult.mergeAuthorized,false);
});
test('known direct credential logging cannot be marked clean by the model',async()=>{
  const f=fixture();f.compare.files[0].patch='@@ -0,0 +1 @@\n+console.log(req.headers.authorization);';
  const {api}=apiFor(f); const receipt=await reviewRace(request,{api,core,infer:clean});
  assert.equal(receipt.reviewerResult.status,'BLOCKED');
  assert.deepEqual(receipt.reviewerResult.blockers,['deterministic_sensitive_logging_risk']);
});
test('invalid request fails before any API call',async()=>{
  for(const input of [{...request,repository:'haji84/AI-'},{...request,headSha:base},{...request,ciRunId:0}]) {
    let calls=0; await assert.rejects(preflightRace(input,{core,api:async()=>{calls++;}}),/SCOPE/);assert.equal(calls,0);
  }
});
test('changed plan pin rejects before inference',async()=>{
  const {api}=apiFor(fixture());let models=0;
  await assert.rejects(reviewRace({...request,reviewPlanSha256:'0'.repeat(64)},
    {api,core,infer:async()=>{models++;return clean();}}),/PLAN_CHANGED/);
  assert.equal(models,0);
});
test('global model budget forbids further inference calls',async()=>{
  let calls=0;const infer=loopbackInfer(async()=>{calls++;return Response.json({});},0);
  await assert.rejects(infer('fixture'),/TOTAL_BUDGET/);assert.equal(calls,0);
});
test('candidate is inactive, manual, read only, and preflights before any model download',async()=>{
  const source=await readFile(new URL('../docs/workflow-templates/race-goriq-readonly.yml.template',import.meta.url),'utf8');
  assert.match(source,/workflow_dispatch:/);assert.doesNotMatch(source,/\bwrite\b|schedule:|workflow_run:|pull_request_target:|secrets\./);
  assert.match(source,/RACE_AI09_READONLY_ENABLED/);assert.match(source,/timeout-minutes: 70/);
  assert.ok(source.indexOf('--preflight')<source.indexOf('curl --fail'));
  assert.doesNotMatch(source,/upload-artifact|repository_dispatch|OPENAI|ANTHROPIC/);
  await assert.rejects(readFile(new URL('../.github/workflows/race-goriq-readonly.yml',import.meta.url)),{code:'ENOENT'});
});
test('CLI default failure discloses neither a local path nor raw errors',()=>{
  const cli=fileURLToPath(new URL('../scripts/race-goriq-review.mjs',import.meta.url));
  const result=spawnSync(process.execPath,[cli,'--invalid-mode'],{encoding:'utf8'});
  assert.equal(result.status,2);assert.equal(result.stdout,'');
  assert.match(result.stderr,/HOLD: RACE_USAGE_INVALID/);assert.ok(!result.stderr.includes(cli));
});
