import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../.github/workflows/race-goriq-connect.yml',import.meta.url),'utf8');
test('connection is a bounded owner-only public standard-runner event, without writes or automatic repeats',()=>{
  assert.match(source,/types: \[opened, reopened\]/);
  assert.doesNotMatch(source,/\b(?:push|schedule|workflow_run|pull_request_target):|secrets\.|upload-artifact|actions\/cache|id-token:|:\s*write\b/);
  assert.match(source,/github\.actor == 'haji84'/);
  assert.match(source,/github\.event\.repository\.private == false/);
  assert.match(source,/head\.ref == 'codex\/goriq-review-reuse'/);
  assert.match(source,/runs-on: ubuntu-24\.04/);assert.match(source,/timeout-minutes: 70/);
  const permissions=source.match(/permissions:\n([\s\S]*?)\n\n/)[1].trim().split('\n');
  assert.equal(permissions.length,4);assert.ok(permissions.every(p=>p.trim().endsWith(': read')));
  assert.ok(source.indexOf('--preflight')<source.indexOf('curl --fail'));
  assert.match(source,/AI_ASSERTED\. GitHub approval: false\. Merge authorized: false/);
});
test('reviewer source is separately pinned and target PR69 request remains exact',async()=>{
  const request=JSON.parse(await readFile(new URL('../examples/ai09-pr69-request.json',import.meta.url),'utf8'));
  const pin=source.match(/TRUSTED_REVIEWER_SHA: ([a-f0-9]{40})/)[1];
  assert.notEqual(pin,request.headSha);assert.notEqual(pin,request.baseSha);
  assert.match(source,new RegExp('ref: '+pin));
  assert.match(source,/persist-credentials: false/);
  assert.equal(request.prNumber,69);assert.match(request.reviewPlanSha256,/^[a-f0-9]{64}$/);
  assert.match(source,/cf95886728959aa09910bb34de5cca1cc5a8f68003b5597197d3f2c2d57c0804/);
  assert.match(source,/ollama pull qwen2\.5-coder:3b/);
});
