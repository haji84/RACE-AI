#!/usr/bin/env node
// RACE-specific transport/preflight only. The review engine is unchanged GORIQ.
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { performance } from 'node:perf_hooks';
import {buildReviewPlan, consolidateBatches, isEmptyAddition, safeReviewPath, verifyEmptyContent} from './race-goriq-plan.mjs';

const UPSTREAM = 'accf8294ff936b73b93e21667d92bc1b52aa8428';
const LOCK_DIGEST = '651b0e7a4ee1b1e5f6bd584b789e81569c6fda7a6e9e687191af9edd651916c6';
const REPO = 'haji84/RACE-AI', REPO_ID = 1416489937;
const SHA = /^[a-f0-9]{40}$/;
const NAMES = ['Synthetic E2E (ubuntu-24.04)','Synthetic E2E (windows-2022)','unit'];
const WORKFLOW = '.github/workflows/four-sport-synthetic.yml';
const BODY_LIMIT = 2 * 1024 * 1024;
const fail = code => {throw Error(code);};
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

export async function loadPinnedCore(root=fileURLToPath(new URL('../vendor/goriq-ai09/',import.meta.url))) {
  const bytes = await readFile(join(root,'UPSTREAM.json'));
  if (digest(bytes) !== LOCK_DIGEST) fail('GORIQ_LOCK_INTEGRITY');
  const lock=JSON.parse(bytes);
  if (lock.repository !== 'haji84/AI-' || lock.commit !== UPSTREAM || lock.files.length !== 4)
    fail('GORIQ_LOCK_INTEGRITY');
  const modules=[];
  // All bytes are verified before evaluating any module. Data imports use the
  // verified snapshot, avoiding a second filesystem read between hash/import.
  for (const entry of lock.files) {
    const source=await readFile(join(root,entry.path));
    const blob=createHash('sha1').update('blob '+source.length+'\0').update(source).digest('hex');
    if(source.length !== entry.bytes || digest(source) !== entry.sha256 || blob !== entry.gitBlob)
      fail('GORIQ_SOURCE_INTEGRITY');
    modules.push(source);
  }
  const loaded=await Promise.all(modules.map(bytes=>import('data:text/javascript;base64,'+bytes.toString('base64'))));
  return Object.freeze(Object.assign({},...loaded,{upstreamSha:UPSTREAM}));
}

function scopeOf(value) {
  const x=structuredClone(value);
  if(x?.repository !== REPO || !Number.isSafeInteger(x.prNumber) || x.prNumber<1 ||
    !SHA.test(x.headSha??'') || !SHA.test(x.baseSha??'') || x.headSha===x.baseSha ||
    !Number.isSafeInteger(x.ciRunId) || x.ciRunId<1) fail('RACE_INVALID_SCOPE');
  if(x.reviewPlanSha256!==undefined && !/^[a-f0-9]{64}$/.test(x.reviewPlanSha256))fail('RACE_INVALID_PLAN_PIN');
  return {repository:REPO,prNumber:x.prNumber,headSha:x.headSha,baseSha:x.baseSha,ciRunId:x.ciRunId};
}
function ownRepo(x) {return x?.full_name===REPO && x.id===REPO_ID;}
function evidence(scope,pr,run,checks) {
  const {prNumber,headSha,baseSha,ciRunId}=scope;
  if(pr?.number!==prNumber || pr.state!=='open' || pr.merged!==false ||
    pr.head?.sha!==headSha || pr.base?.sha!==baseSha || pr.base?.ref!=='main' ||
    !ownRepo(pr.head.repo) || !ownRepo(pr.base.repo) ||
    !Number.isSafeInteger(pr.changed_files) || pr.changed_files<1 || pr.changed_files>30)
    fail('RACE_PR_SCOPE_CHANGED');
  if(run?.id!==ciRunId || run.name!=='Four sport synthetic E2E' || run.path!==WORKFLOW ||
    run.event!=='pull_request' || run.status!=='completed' || run.conclusion!=='success' ||
    run.head_sha!==headSha || !ownRepo(run.repository) || !Number.isSafeInteger(run.run_attempt) || run.run_attempt<1 ||
    !Number.isSafeInteger(run.check_suite_id) || !Array.isArray(run.pull_requests) ||
    !run.pull_requests.some(p=>p.number===prNumber && p.head?.sha===headSha && p.base?.sha===baseSha &&
      p.head.repo?.id===REPO_ID && p.base.repo?.id===REPO_ID)) fail('RACE_CI_PROVENANCE_INVALID');
  if(!Number.isSafeInteger(checks?.total_count) || checks.total_count>100 ||
    !Array.isArray(checks.check_runs) || checks.total_count!==checks.check_runs.length)
    fail('RACE_CHECKS_INCOMPLETE');
  const required=NAMES.map(name=>{
    const same=checks.check_runs.filter(c=>c?.name===name);
    if(same.length!==1) fail('RACE_CI_REQUIRED_CHECK_INVALID');
    const c=same[0];
    if(c.head_sha!==headSha || c.app?.id!==15368 || c.app.slug!=='github-actions' ||
      c.status!=='completed' || c.conclusion!=='success' || c.check_suite?.id!==run.check_suite_id ||
      !Number.isSafeInteger(c.id) || !new RegExp('^https://github\\.com/haji84/RACE-AI/actions/runs/'+ciRunId+'/job/[0-9]+$').test(c.details_url??''))
      fail('RACE_CI_REQUIRED_CHECK_INVALID');
    return {name,id:c.id,url:c.details_url};
  });
  if(new Set(required.map(c=>c.id)).size!==NAMES.length) fail('RACE_CI_REQUIRED_CHECK_INVALID');
  return JSON.stringify({headSha,baseSha,changedFiles:pr.changed_files,attempt:run.run_attempt,suite:run.check_suite_id,required});
}
async function readEvidence(scope,api) {
  const pr=structuredClone(await api('/pulls/'+scope.prNumber));
  const run=structuredClone(await api('/actions/runs/'+scope.ciRunId));
  const checks=structuredClone(await api('/commits/'+scope.headSha+'/check-runs?per_page=100'));
  return {pr,fingerprint:evidence(scope,pr,run,checks)};
}
async function prepare(request,{api,core}) {
  const expectedPlan=structuredClone(request)?.reviewPlanSha256;
  const scope=scopeOf(request);
  if(typeof api!=='function') fail('RACE_API_REQUIRED');
  const first=await readEvidence(scope,api);
  const compare=structuredClone(await api('/compare/'+scope.baseSha+'...'+scope.headSha));
  if(compare?.status!=='ahead' || compare.base_commit?.sha!==scope.baseSha ||
    compare.merge_base_commit?.sha!==scope.baseSha || compare.commits?.at(-1)?.sha!==scope.headSha ||
    !Number.isSafeInteger(compare.total_commits) || compare.total_commits<1 || compare.total_commits>250 ||
    compare.commits.length!==compare.total_commits || compare.files?.length!==first.pr.changed_files)
    fail('RACE_COMPARE_INCOMPLETE_OR_CHANGED');
  const verifiedEmpty=new Set();
  for(const file of compare.files)if(file?.patch===undefined) {
    if(!isEmptyAddition(file))fail('RACE_EMPTY_FILE_UNVERIFIED');
    const content=await api('/contents/'+file.filename+'?ref='+scope.headSha);
    verifyEmptyContent(content,file);verifiedEmpty.add(file.filename);
  }
  const prepared=buildReviewPlan(compare,scope,core,verifiedEmpty);
  if(expectedPlan!==undefined && expectedPlan!==prepared.planSha256)fail('RACE_REVIEW_PLAN_CHANGED');
  return {scope,first,prepared};
}
export async function preflightRace(request,{api,core}) {
  const {scope,prepared}=await prepare(request,{api,core});
  return {contract:'RACE_GORIQ_BATCHED_V2',...scope,upstreamSha:UPSTREAM,
    changedFiles:prepared.paths.length,patchSha256:prepared.patchSha256,
    reviewPlanSha256:prepared.planSha256,batchCount:prepared.batches.length,emptyFiles:prepared.emptyFiles,
    chunkCount:prepared.chunks.length,modelInvoked:false,githubApprovalSatisfied:false,mergeAuthorized:false};
}
export async function reviewRace(request,{api,core,infer,onProgress=()=>{}}) {
  if(typeof infer!=='function') fail('RACE_LOOPBACK_MODEL_REQUIRED');
  const {scope,first,prepared}=await prepare(request,{api,core});
  const reports=[];let reviewedChunks=0;
  outer:for(const batch of prepared.batches) {
    const rows=[];reports.push(rows);
    for(const chunk of batch.chunks) {
      const started=performance.now();
      const report=await core.reviewLocalPatch({headSha:scope.headSha,baseSha:scope.baseSha,
        paths:chunk.paths,patch:chunk.patch,makerRole:'Builder',infer});
      rows.push(report);reviewedChunks++;
      onProgress({chunk:reviewedChunks,of:prepared.chunks.length,
        status:['NO_ACTIONABLE_FINDINGS','CHANGES_REQUESTED','INCONCLUSIVE','BLOCKED'].includes(report.status)?report.status:'BLOCKED',
        durationMs:Math.round(performance.now()-started)});
      if(report.status==='BLOCKED')break outer;
    }
  }
  const result=consolidateBatches(prepared,reports,{headSha:scope.headSha,baseSha:scope.baseSha},core);
  const last=await readEvidence(scope,api);
  if(first.fingerprint!==last.fingerprint) fail('RACE_EVIDENCE_CHANGED_DURING_REVIEW');
  const expected={...scope,trustedSha:UPSTREAM};
  const receipt=core.reviewReceipt({...expected,ciConclusion:'success',result});
  if(!core.validateReviewReceipt(receipt,expected))fail('RACE_UNPUBLISHABLE_RECEIPT');
  return {...receipt,contract:'RACE_GORIQ_BATCHED_V2',chunkCount:prepared.chunks.length,
    reviewedChunks,batchCount:prepared.batches.length,reviewPlanSha256:prepared.planSha256,
    emptyFiles:prepared.emptyFiles,adapterPolicy:'four-sport-synthetic-v2'};
}

async function boundedJson(response,max=BODY_LIMIT) {
  if(!response.ok)fail('RACE_GITHUB_GET_FAILED');
  const reader=response.body?.getReader(); if(!reader)fail('RACE_BODY_INVALID');
  const parts=[];let length=0;
  try {
    for(;;){const {done,value}=await reader.read(); if(done)break; length+=value.length;
      if(length>max)fail('RACE_BODY_LIMIT'); parts.push(Buffer.from(value));}
  } finally {await reader.cancel();}
  try{return JSON.parse(Buffer.concat(parts).toString('utf8'));}catch{fail('RACE_BODY_INVALID');}
}
export function makeGithubGet(fetcher=fetch,token='') {
  return async path=>{
    const content=typeof path==='string'?/^\/contents\/(.+)\?ref=([a-f0-9]{40})$/.exec(path):null;
    if(typeof path!=='string' || !(content && safeReviewPath(content[1])) &&
      !/^(?:\/pulls\/[1-9][0-9]*|\/actions\/runs\/[1-9][0-9]*|\/commits\/[a-f0-9]{40}\/check-runs\?per_page=100|\/compare\/[a-f0-9]{40}\.\.\.[a-f0-9]{40})$/.test(path))
      fail('RACE_API_PATH_INVALID');
    const headers={Accept:'application/vnd.github+json','User-Agent':'RACE-GORIQ-readonly'};
    if(token)headers.Authorization='Bearer '+token;
    const response=await fetcher('https://api.github.com/repos/'+REPO+path,{method:'GET',headers,
      redirect:'error',signal:AbortSignal.timeout(15000)});
    return boundedJson(response);
  };
}
export function loopbackInfer(fetcher=fetch,deadline=performance.now()+50*60*1000) {
  return async prompt=>{
    if(typeof prompt!=='string' || Buffer.byteLength(prompt)>10000)fail('RACE_MODEL_INPUT_INVALID');
    const remaining=Math.floor(deadline-performance.now());
    if(remaining<=0)fail('RACE_MODEL_TOTAL_BUDGET');
    const response=await fetcher('http://127.0.0.1:11434/api/chat',{method:'POST',redirect:'error',
      headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(Math.min(150000,remaining)),body:JSON.stringify({
        model:'qwen2.5-coder:3b',stream:false,format:'json',options:{temperature:0,num_ctx:8192,num_predict:768},
        messages:[{role:'user',content:prompt}]})});
    const payload=await boundedJson(response,65536);
    if(typeof payload?.message?.content!=='string')fail('RACE_MODEL_OUTPUT_INVALID');
    return payload.message.content;
  };
}
async function main() {
  const [mode,path,...rest]=process.argv.slice(2);
  if(!['--preflight','--review'].includes(mode) || !path || rest.length)fail('RACE_USAGE_INVALID');
  const bytes=await readFile(path);if(bytes.length>4096)fail('RACE_SCOPE_FILE_LIMIT');
  const request=JSON.parse(bytes), core=await loadPinnedCore();
  if(mode==='--review' && !/^[a-f0-9]{64}$/.test(request.reviewPlanSha256??''))fail('RACE_REVIEW_PLAN_PIN_REQUIRED');
  const api=makeGithubGet(fetch,process.env.GITHUB_TOKEN??'');
  const result=mode==='--preflight'?await preflightRace(request,{api,core}):
    await reviewRace(request,{api,core,infer:loopbackInfer(),onProgress:row=>process.stderr.write('AI09_PROGRESS='+JSON.stringify(row)+'\n')});
  process.stdout.write(JSON.stringify(result,null,2)+'\n');
  if(mode==='--review' && result.reviewerResult.status!=='NO_ACTIONABLE_FINDINGS')process.exitCode=2;
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href)
  main().catch(error=>{
    const upstreamCodes=new Set(['diff_exceeds_local_review_budget','review_chunk_budget_exhausted',
      'unreviewable_oversized_line','incomplete_github_patch','unverifiable_patch_statistics',
      'missing_comparison_files','invalid_or_oversized_comparison','unsafe_or_unreviewable_patch',
      'duplicate_changed_path','review_source_line_coverage_mismatch','review_chunk_coverage_mismatch']);
    const code=/^(?:RACE_|GORIQ_)[A-Z0-9_]{1,64}$/.test(error?.message??'') || upstreamCodes.has(error?.message)
      ? error.message : 'PREREQUISITES_OR_REVIEW_UNAVAILABLE';
    process.stderr.write('RACE_GORIQ_HOLD: '+code+'; no approval granted.\n');process.exitCode=2;
  });
