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
 assert.equal(wf.split('# BEGIN TESTED SAVE PROTOCOL\n')[1].split('# END TESTED SAVE PROTOCOL')[0].split('\n').map(l=>l.slice(10)).join('\n').trim(),module);
 const job=wf.split('\n  save-technical-result:\n')[1];
 assert.ok(job);assert.doesNotMatch(job,/uses:|checkout|ollama|actions: write/);
});
