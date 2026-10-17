#!/usr/bin/env node
// Read-only RACE AI -> GORIQ AI-09 request manifest. No model, GitHub writes or merge.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const SHA = /^[a-f0-9]{40}$/;
const REPO = 'haji84/RACE-AI';
const CHECKS = ['unit (ubuntu-latest)', 'unit (windows-latest)', 'pilot'];

export function createHandoff({ repository, pr, checkRuns, claimedReview = null }) {
  if (repository !== REPO || !Number.isSafeInteger(pr?.number) || pr.number < 1 ||
      pr.state !== 'open' || !SHA.test(pr.head?.sha ?? '') ||
      !SHA.test(pr.base?.sha ?? '') ||
      pr.head.sha === pr.base.sha ||
      pr.head.repo?.full_name !== REPO || pr.base.repo?.full_name !== REPO ||
      !Array.isArray(checkRuns)) throw Error('UNTRUSTED_PR_SCOPE');
  const checks = CHECKS.map(name => {
    const matches = checkRuns.filter(c => c.name === name && c.head_sha === pr.head.sha && c.app?.slug === 'github-actions');
    return { name, passed:matches.length === 1 && matches[0].status === 'completed' && matches[0].conclusion === 'success' };
  });
  const allPassed = checks.every(c => c.passed);
  // A comment/JSON claiming to be AI-09 is not an authenticated Reviewer receipt.
  // This interface never upgrades an assertion to GitHub approval.
  const headMatches = claimedReview?.headSha === pr.head.sha && claimedReview?.baseSha === pr.base.sha;
  const advisory = headMatches && ['CHANGES_REQUESTED','NO_ACTIONABLE_FINDINGS','BLOCKED','INCONCLUSIVE'].includes(claimedReview?.status)
    ? claimedReview.status : null;
  return {
    schemaVersion:1, contract:'GORIQ_AI09_ADVISORY_REQUEST_V1', repository,
    prNumber:pr.number, headSha:pr.head.sha, baseSha:pr.base.sha,
    requiredChecks:checks, ciReady:allPassed,
    recipient:'GORIQ/AI-09', reviewerMustDifferFromBuilder:true,
    expectedModel:'local-only', sourceModelCredentialsPermitted:false,
    advisoryReceivedButUnverified:advisory,
    nextAction: !allPassed ? 'WAIT_FOR_EXACT_HEAD_CI' :
      advisory === 'CHANGES_REQUESTED' ? 'REQUEST_BUILDER_DEBUGGER_TRIAGE' :
      advisory === 'BLOCKED' || advisory === 'INCONCLUSIVE' ? 'HOLD_REVIEW' :
      advisory === 'NO_ACTIONABLE_FINDINGS' ? 'REQUIRE_INDEPENDENT_GATE_VERIFICATION' : 'REQUEST_AI09',
    correctionTask:allPassed && advisory === 'CHANGES_REQUESTED' ? {
      id:'ai09:pr:'+pr.number+':'+pr.head.sha, target:'Builder/Debugger',
      authorizedToModifyCode:false, requiresFreshHeadAndCi:true
    } : null,
    independentReviewVerified:false, githubApprovalSatisfied:false, mergeAuthorized:false,
    gitHubWritePerformed:false
  };
}

async function githubSnapshot(number, token) {
  if (!Number.isSafeInteger(number) || number < 1 || number > 1000000000) throw Error('BAD_PR_NUMBER');
  const headers = {Accept:'application/vnd.github+json', 'User-Agent':'race-ai-ai09-handoff'};
  if(token)headers.Authorization='Bearer '+token;
  async function get(url) {
    const response=await fetch('https://api.github.com/repos/'+REPO+url,{headers, signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error('GITHUB_READ_FAILED_'+response.status);
    return response.json();
  }
  const pr=await get('/pulls/'+number);
  // Scope is verified before reading the changed commit.
  createHandoff({repository:REPO,pr,checkRuns:[]});
  const checks=await get('/commits/'+pr.head.sha+'/check-runs?per_page=100');
  if(!Array.isArray(checks.check_runs) || checks.total_count !== checks.check_runs.length || checks.total_count > 100)
    throw Error('INCOMPLETE_CHECK_RUNS');
  const after=await get('/pulls/'+number);
  if(after.state !== 'open' || after.head.sha !== pr.head.sha || after.base.sha !== pr.base.sha)
    throw Error('PR_CHANGED_DURING_READ');
  return {repository:REPO,pr,checkRuns:checks.check_runs};
}

async function main() {
  const a=process.argv.slice(2);
  const snapshot=a.length===2 && a[0]==='--snapshot'
    ? JSON.parse(readFileSync(a[1],'utf8'))
    : a.length===2 && a[0]==='--pr' ? await githubSnapshot(Number(a[1]),process.env.GITHUB_TOKEN)
    : null;
  if(!snapshot)throw Error('USAGE: --pr NUMBER | --snapshot FILE');
  process.stdout.write(JSON.stringify(createHandoff(snapshot),null,2)+'\n');
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href){
  main().catch(e=>{process.stderr.write(e.message+'\n');process.exitCode=2;});
}