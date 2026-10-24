// Pure bounded protocol. API is injected; importing this file never sends a request.
export const REPOSITORY='haji84/RACE-AI';
export const BRANCH='feat/completion-controller-pilot-20261016';
export const WORKFLOW='.github/workflows/completion-controller-pilot.yml';
const sha=x=>typeof x==='string'&&/^[a-f0-9]{40}$/.test(x);
const id=x=>typeof x==='string'&&/^[1-9][0-9]{0,14}$/.test(x);
const hash=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
const check=(ok,error)=>{if(!ok)throw Error(error);};
export function validateArtifact(a,c){
 check(a.id===Number(c.artifactId)&&a.name==='one-hop-checkpoint-'+c.runId&&!a.expired&&a.size_in_bytes>0&&a.size_in_bytes<=16384&&a.workflow_run?.id===Number(c.runId)&&a.workflow_run?.head_sha===c.head&&a.digest==='sha256:'+c.artifactDigest,'ARTIFACT_BINDING_INVALID');
}
function validateSource(run,c,finished){
 check(run.id===Number(c.runId)&&run.repository?.full_name===REPOSITORY&&run.head_sha===c.head&&run.head_branch===BRANCH&&run.path===WORKFLOW&&run.event==='pull_request'&&run.run_attempt===1&&run.actor?.login==='haji84','SOURCE_RUN_INVALID');
 if(finished)check(run.status==='completed'&&run.conclusion==='success','SOURCE_NOT_SUCCESS');
}
export async function dispatchOnce(c,api){
 check(c.repository===REPOSITORY&&c.branch===BRANCH&&c.event==='pull_request'&&c.action==='synchronize'&&c.actor==='haji84'&&c.prNumber==='65'&&c.headRepository===REPOSITORY&&c.baseRepository===REPOSITORY&&c.attempt==='1'&&id(c.runId)&&id(c.runNumber)&&c.runNumber===c.expectedRunNumber&&sha(c.head)&&sha(c.preparedParent)&&id(c.artifactId)&&hash(c.artifactDigest),'DISPATCH_SCOPE_INVALID');
 const run=await api.get('actions/runs/'+c.runId);validateSource(run,c,false);
 check(String(run.run_number)===c.expectedRunNumber&&run.status==='in_progress','SOURCE_ATTEMPT_INVALID');
 const commit=await api.get('commits/'+c.head);
 check(commit.sha===c.head&&commit.parents?.length===1&&commit.parents[0].sha===c.preparedParent,'PREPARED_PARENT_CHANGED');
 validateArtifact(await api.get('actions/artifacts/'+c.artifactId),c);
 const chain='race-one-hop-'+c.runId;
 const prior=await api.get('actions/workflows/completion-controller-pilot.yml/runs?event=workflow_dispatch&per_page=100');
 check(Array.isArray(prior.workflow_runs)&&prior.total_count===prior.workflow_runs.length&&prior.total_count<=100,'DISPATCH_HISTORY_INCOMPLETE');
 check(!prior.workflow_runs.some(r=>r.display_title===chain),'CHAIN_ALREADY_DISPATCHED');
 const ref=await api.get('git/ref/heads/'+BRANCH);
 check(ref.object?.sha===c.head,'BRANCH_HEAD_CHANGED');
 const body={ref:BRANCH,inputs:{chain_id:chain,source_run_id:c.runId,source_head:c.head,artifact_id:c.artifactId,artifact_digest:c.artifactDigest,remaining_hops:'0'}};
 // Exactly one attempt. Timeout/unknown response is NOT safe to repeat.
 let response;try{response=await api.post('actions/workflows/completion-controller-pilot.yml/dispatches',body);}catch{throw Error('DISPATCH_UNCONFIRMED_STOP_NO_RETRY');}
 let childRunId=null;
 if(response.status===200){
  const b=response.body;
  check(Number.isSafeInteger(b?.workflow_run_id)&&b.workflow_run_id>0&&b.run_url==='https://api.github.com/repos/'+REPOSITORY+'/actions/runs/'+b.workflow_run_id&&b.html_url==='https://github.com/'+REPOSITORY+'/actions/runs/'+b.workflow_run_id,'DISPATCH_RECEIPT_UNCONFIRMED_STOP_NO_RETRY');
  childRunId=b.workflow_run_id;
 }else check(response.status===204,'DISPATCH_REJECTED_OR_UNCONFIRMED_'+response.status);
 return {status:'DISPATCH_ACCEPTED',childRunId,chainId:chain,sourceRun:c.runId,sourceHead:c.head,maxChildren:1,remainingHops:0,childSuccess:false};
}
export function validateReceiver(c,source,artifact){
 check(c.repository===REPOSITORY&&c.event==='workflow_dispatch'&&c.branch===BRANCH&&c.attempt==='1'&&id(c.runId)&&id(c.sourceRunId)&&c.runId!==c.sourceRunId&&sha(c.sourceHead)&&c.head===c.sourceHead&&c.chainId==='race-one-hop-'+c.sourceRunId&&c.remainingHops==='0'&&id(c.artifactId)&&hash(c.artifactDigest),'RECEIVER_SCOPE_INVALID');
 const original={runId:c.sourceRunId,head:c.sourceHead,artifactId:c.artifactId,artifactDigest:c.artifactDigest};
 validateSource(source,original,true);validateArtifact(artifact,original);
 return {chainId:c.chainId,sourceRun:c.sourceRunId,destinationRun:c.runId,sourceHead:c.sourceHead,remainingHops:0,mayDispatch:false};
}
