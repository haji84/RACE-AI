import test from 'node:test';
import assert from 'node:assert/strict';
import * as protocol from '../scripts/completion-dispatch-protocol.mjs';
test('bounded one-hop dispatch protocol is implemented',()=>{
 assert.equal(typeof protocol.dispatchOnce,'function');
 assert.equal(typeof protocol.validateReceiver,'function');
});

import {readFileSync} from 'node:fs';
const c=()=>({repository:protocol.REPOSITORY,branch:protocol.BRANCH,event:'pull_request',action:'synchronize',actor:'haji84',prNumber:'65',headRepository:protocol.REPOSITORY,baseRepository:protocol.REPOSITORY,attempt:'1',runId:'123',runNumber:'27',expectedRunNumber:'27',head:'a'.repeat(40),preparedParent:'b'.repeat(40),artifactId:'456',artifactDigest:'c'.repeat(64)});
function fake(ctx=c()){
 const run={id:123,repository:{full_name:protocol.REPOSITORY},head_sha:ctx.head,head_branch:protocol.BRANCH,path:protocol.WORKFLOW,event:'pull_request',run_attempt:1,actor:{login:'haji84'},run_number:27,status:'in_progress'};
 const artifact={id:456,name:'one-hop-checkpoint-123',expired:false,size_in_bytes:1024,workflow_run:{id:123,head_sha:ctx.head},digest:'sha256:'+ctx.artifactDigest};
 const records={'actions/runs/123':run,['commits/'+ctx.head]:{sha:ctx.head,parents:[{sha:ctx.preparedParent}]},'actions/artifacts/456':artifact,'actions/workflows/completion-controller-pilot.yml/runs?event=workflow_dispatch&per_page=100':{total_count:0,workflow_runs:[]},['git/ref/heads/'+protocol.BRANCH]:{object:{sha:ctx.head}}};
 const writes=[];
 return {records,run,artifact,writes,api:{get:async p=>structuredClone(records[p]),post:async(p,b)=>{writes.push({path:p,body:b});return {status:204};}}};
}
test('trusted source makes exactly one fixed same-workflow zero-hop child request',async()=>{
 const f=fake(),r=await protocol.dispatchOnce(c(),f.api);
 assert.equal(f.writes.length,1);assert.equal(r.childSuccess,false);assert.equal(r.maxChildren,1);
 assert.equal(f.writes[0].body.inputs.remaining_hops,'0');assert.equal(f.writes[0].path,'actions/workflows/completion-controller-pilot.yml/dispatches');
});
test('scope, rerun, unexpected parent, artifact, duplicate chain and branch drift stop before POST',async()=>{
 for(const mutate of [
  (x,f)=>x.attempt='2',(x,f)=>x.runNumber='28',(x,f)=>x.actor='other',(x,f)=>x.prNumber='66',(x,f)=>x.headRepository='other/repo',
  (x,f)=>f.run.head_sha='d'.repeat(40),(x,f)=>f.run.status='completed',
  (x,f)=>f.records['commits/'+x.head].parents[0].sha='d'.repeat(40),
  (x,f)=>f.artifact.expired=true,(x,f)=>f.artifact.digest='sha256:'+'d'.repeat(64),
  (x,f)=>f.records['git/ref/heads/'+protocol.BRANCH].object.sha='d'.repeat(40),
  (x,f)=>{const a=f.records['actions/workflows/completion-controller-pilot.yml/runs?event=workflow_dispatch&per_page=100'];a.total_count=1;a.workflow_runs=[{display_title:'race-one-hop-123'}];}
 ]){
  const x=c(),f=fake(x);mutate(x,f);await assert.rejects(()=>protocol.dispatchOnce(x,f.api));assert.equal(f.writes.length,0);
 }
});
test('ambiguous POST gets one attempt and no retry or child success claim',async()=>{
 const f=fake();let n=0;f.api.post=async()=>{n++;throw Error('timeout');};
 await assert.rejects(()=>protocol.dispatchOnce(c(),f.api),/UNCONFIRMED_STOP_NO_RETRY/);assert.equal(n,1);
});
test('receiver requires successful different source run and zero remaining hops',()=>{
 const x=c(),f=fake(x);f.run.status='completed';f.run.conclusion='success';
 const receiver={repository:protocol.REPOSITORY,event:'workflow_dispatch',branch:protocol.BRANCH,attempt:'1',runId:'789',sourceRunId:'123',sourceHead:x.head,head:x.head,chainId:'race-one-hop-123',remainingHops:'0',artifactId:x.artifactId,artifactDigest:x.artifactDigest};
 assert.equal(protocol.validateReceiver(receiver,f.run,f.artifact).mayDispatch,false);
 for(const mutate of [r=>r.remainingHops='1',r=>r.runId='123',r=>r.attempt='2',r=>r.head='d'.repeat(40),r=>r.chainId='race-one-hop-999']){const r=structuredClone(receiver);mutate(r);assert.throws(()=>protocol.validateReceiver(r,f.run,f.artifact));}
 f.run.conclusion='failure';assert.throws(()=>protocol.validateReceiver(receiver,f.run,f.artifact));
});
test('privileged workflow embeds exactly the tested protocol, with no repository-code checkout',()=>{
 const source=readFileSync('scripts/completion-dispatch-protocol.mjs','utf8').replaceAll('export ','').trim();
 const workflow=readFileSync('.github/workflows/completion-controller-pilot.yml','utf8');
 const inline=workflow.split('// BEGIN TESTED DISPATCH PROTOCOL\n')[1]?.split('// END TESTED DISPATCH PROTOCOL')[0].split('\n').map(x=>x.startsWith('          ')?x.slice(10):x).join('\n').trim();
 assert.equal(inline,source);
 const job=workflow.split('  dispatch-next-trial:')[1].split('  dispatch-receiver:')[0];
 assert.equal(job.includes('actions/checkout'),false);assert.equal(job.includes('contents: write'),false);
});
