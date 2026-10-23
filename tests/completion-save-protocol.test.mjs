import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
let m={};try{m=await import('../scripts/completion-save-protocol.mjs');}catch(e){if(e.code!=='ERR_MODULE_NOT_FOUND')throw e;}
test('fixed technical save protocol exists',()=>assert.equal(typeof m.saveOnce,'function','FIXED_TECHNICAL_SAVE_NOT_IMPLEMENTED'));
test('fixed append preserves prior bytes and is idempotent',()=>{
 assert.equal(m.appendResult('prior\n').startsWith('prior\n'),true);
 assert.equal(m.appendResult(m.appendResult('prior\n')),m.appendResult('prior\n'));
 assert.throws(()=>m.appendResult('x'.repeat(20000)),/DOCUMENT/);
 assert.throws(()=>m.appendResult('<!-- bounded-save-v1 -->bad'),/MARKER/);
});
test('scope rejects other repo branch actor event attempt run and malformed parent',()=>{
 const c={repository:m.REPO,branch:m.BRANCH,actor:'haji84',event:'pull_request',action:'synchronize',pr:'65',attempt:'1',run:'123',runNumber:'44',expectedRunNumber:'44',head:'a'.repeat(40),prepared:'b'.repeat(40)};
 assert.doesNotThrow(()=>m.validateContext(c));
 for(const [k,v] of Object.entries({repository:'other/repo',branch:'main',actor:'someone',event:'workflow_dispatch',action:'opened',pr:'72',attempt:'2',run:'bad',runNumber:'45',head:'x',prepared:'x'}))assert.throws(()=>m.validateContext({...c,[k]:v}));
});
test('privileged inline protocol exactly matches tested module; no checkout or model in save job',()=>{
 const wf=readFileSync('.github/workflows/completion-controller-pilot.yml','utf8');
 const module=readFileSync('scripts/completion-save-protocol.mjs','utf8').replace(/^export /gm,'').trim();
 assert.equal(wf.split('// BEGIN TESTED SAVE PROTOCOL\n')[1].split('// END TESTED SAVE PROTOCOL')[0].split('\n').map(l=>l.slice(10)).join('\n').trim(),module);
 const job=wf.split('\n  save-technical-result:\n')[1];
 assert.ok(job);assert.doesNotMatch(job,/uses:|checkout|ollama|actions: write/);
});

const H='a'.repeat(40),P='b'.repeat(40),S='c'.repeat(40),B='d'.repeat(40),T='e'.repeat(40);
function fixture(overrides={}){
 let live=H,content='prior\n',writes=[];
 const c={repository:m.REPO,branch:m.BRANCH,actor:'haji84',event:'pull_request',action:'synchronize',pr:'65',attempt:'1',run:'123',runNumber:'44',expectedRunNumber:'44',head:H,prepared:P};
 const names={'pilot':['Verify isolated controller repair grammar and independent baseline regressions','Test deterministic controller and recovery'],'compass-adapter':['Verify original Compass pins, isolation and evidence rejection','Import canonical state, end process, reopen and export actual Compass SQLite'],'unit (windows-latest)':['Test full runtime, real signed JWTs and cross-language money parity','Validate browser code and state transitions'],'unit (ubuntu-latest)':['Test full runtime, real signed JWTs and cross-language money parity','Validate browser code and state transitions']};
 const api={
  async get(p){
   if(overrides.get){const r=overrides.get(p);if(r!==undefined)return r;}
   if(p.startsWith('git/ref/'))return {object:{sha:live}};
   if(p==='pulls/65')return {state:'open',head:{repo:{full_name:m.REPO},ref:m.BRANCH,sha:live},base:{repo:{full_name:m.REPO}}};
   if(p==='git/commits/'+H)return {parents:[{sha:P}],tree:{sha:T}};
   if(p==='git/commits/'+S)return {parents:[{sha:H}],message:'docs: save bounded technical verification [save-v1]'};
   if(p==='contents/'+m.PATH+'?ref='+H)return {type:'file',path:m.PATH,encoding:'base64',size:6,content:Buffer.from('prior\n').toString('base64'),sha:B};
   if(p.startsWith('contents/'))return {type:'file',path:m.PATH,encoding:'base64',size:Buffer.byteLength(content),content:Buffer.from(content).toString('base64'),sha:B};
   if(p.startsWith('compare/'))return {status:'ahead',behind_by:0,files:[{filename:m.PATH,status:'modified'}]};
   if(p.startsWith('actions/runs/')){
    const regression=p.includes('39948549566'),id=regression?39948549566:39948549502,head='cf66a272a963ed418e94bdf409cea39ce21a5aba';
    if(p.includes('/jobs')){const chosen=Object.entries(names).filter(([n])=>n.startsWith('unit')===regression);return {total_count:2,jobs:chosen.map(([name,ss])=>({name,head_sha:head,status:'completed',conclusion:'success',steps:ss.map(name=>({name,status:'completed',conclusion:'success'}))}))};}
    return {id,head_sha:head,head_branch:m.BRANCH,repository:{full_name:m.REPO},event:'pull_request',path:regression?'.github/workflows/tests.yml':'.github/workflows/completion-controller-pilot.yml',run_attempt:1,status:'completed',conclusion:'success'};
   }throw Error('UNEXPECTED_GET_'+p);
  },
  async post(p,b){writes.push([p,b]);if(p==='git/blobs'){content=b.content;return {sha:B};}if(p==='git/trees')return {sha:T};if(p==='git/commits')return {sha:S,parents:[{sha:H}]};throw Error('UNEXPECTED_POST');},
  async patch(p,b){writes.push([p,b]);if(overrides.patch)throw Error('CONCURRENT_ADVANCE_422');assert.equal(p,'git/refs/heads/'+m.BRANCH);assert.deepEqual(b,{sha:S,force:false});live=S;return {};}
 };return {c,api,writes};
}
test('single fixed-file update preserves prior bytes then repeats with zero additional writes',async()=>{
 const f=fixture();const a=await m.saveOnce(f.c,f.api);assert.equal(a.status,'SAVED');assert.equal(a.head,S);
 assert.equal(f.writes.length,4);assert.deepEqual(f.writes[1][1].tree,[{path:m.PATH,mode:'100644',type:'blob',sha:B}]);assert.deepEqual(f.writes[2][1].parents,[H]);
 assert.equal(f.writes[0][1].content,'prior\n'+m.ADDITION);
 assert.equal((await m.saveOnce(f.c,f.api)).status,'NOOP');assert.equal(f.writes.length,4);
});
test('failed or skipped evidence causes zero writes',async()=>{
 const f=fixture({get:p=>p==='actions/runs/39948549502'?{conclusion:'failure'}:undefined});
 await assert.rejects(m.saveOnce(f.c,f.api),/EVIDENCE_RUN_INVALID/);assert.equal(f.writes.length,0);
 const g=fixture({get:p=>p.includes('/jobs')?{total_count:0,jobs:[]}:undefined});
 await assert.rejects(m.saveOnce(g.c,g.api),/EVIDENCE_JOB_INVALID/);assert.equal(g.writes.length,0);
});
test('unexpected file delta and branch movement stop before ref update',async()=>{
 const f=fixture({get:p=>p.startsWith('compare/')?{files:[{filename:'src/evil',status:'modified'}]}:undefined});
 await assert.rejects(m.saveOnce(f.c,f.api),/DIFF_ALLOWLIST_FAILED/);assert.equal(f.writes.filter(([p])=>p.startsWith('git/refs/')).length,0);
 const g=fixture({get:p=>p.startsWith('git/ref/')?{object:{sha:S}}:undefined});
 await assert.rejects(m.saveOnce(g.c,g.api),/PR_CHANGED|BRANCH_CHANGED/);assert.equal(g.writes.length,0);
});
test('non-fast-forward update failure is not retried',async()=>{
 const f=fixture({patch:true});await assert.rejects(m.saveOnce(f.c,f.api),/CONCURRENT_ADVANCE/);assert.equal(f.writes.filter(([p])=>p.startsWith('git/refs/')).length,1);
});

test('PR metadata lag cannot turn an already verified save into a duplicate write',async()=>{
 const f=fixture();await m.saveOnce(f.c,f.api);
 const get=f.api.get;f.api.get=async p=>{const r=await get(p);if(p==='pulls/65')r.head.sha=H;return r;};
 assert.equal((await m.saveOnce(f.c,f.api)).status,'NOOP');assert.equal(f.writes.length,4);
});

test('known saved receipt reconciliation cannot write when content is absent',async()=>{
 const f=fixture();await assert.rejects(m.saveOnce(f.c,f.api,S),/READONLY_RECONCILIATION/);assert.equal(f.writes.length,0);
});
test('saved receipt remains a no-op after unrelated branch advance',async()=>{
 const f=fixture();await m.saveOnce(f.c,f.api);
 const get=f.api.get,U='f'.repeat(40);
 f.api.get=async p=>p.startsWith('git/ref/')?{object:{sha:U}}:get(p);
 const r=await m.saveOnce(f.c,f.api,S);assert.equal(r.status,'NOOP');assert.equal(r.head,U);assert.equal(r.savedHead,S);assert.equal(f.writes.length,4);
});
test('changed saved content and non-descendant branch fail closed without writes',async()=>{
 for(const mode of ['content','ancestry']){
  const f=fixture();await m.saveOnce(f.c,f.api);const get=f.api.get;let seen=0;
  f.api.get=async p=>{const r=await get(p);if(mode==='content'&&p==='contents/'+m.PATH+'?ref='+S&&++seen===2)return {...r,sha:'f'.repeat(40)};
   if(mode==='ancestry'&&p==='compare/'+S+'...'+S)return {...r,status:'diverged',behind_by:1};return r;};
  await assert.rejects(m.saveOnce(f.c,f.api,S),/SAVED_CONTENT_CHANGED|SAVED_ANCESTRY_INVALID/);assert.equal(f.writes.length,4);
 }
});
