import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {loadPinnedCore} from '../scripts/race-goriq-review.mjs';
import {buildReviewPlan, consolidateBatches, verifyEmptyContent} from '../scripts/race-goriq-plan.mjs';
const core=await loadPinnedCore();
const scope={headSha:'a'.repeat(40),baseSha:'b'.repeat(40)};
const empty='e69de29bb2d1d6434b8b29ae775ad8c2e48c5391';
const clean=async()=>'{"verdict":"NO_FINDINGS","findings":[]}';
function fixture(n=1){return {status:'ahead',ahead_by:1,total_commits:1,
  files:Array.from({length:n},(_,i)=>({filename:'src/f'+i+'.mjs',status:'added',sha:'c'.repeat(40),
    additions:1,deletions:0,changes:1,patch:'@@ -0,0 +1 @@\n+export const f'+i+' = 1;'}))};}
function emptyEntry(){return {filename:'tests/__init__.py',status:'added',sha:empty,additions:0,deletions:0,changes:0};}
test('28 text slices plus verified empty-file metadata are planned as 24+5, with all files retained',()=>{
  const c=fixture(28);c.files.push(emptyEntry());
  const plan=buildReviewPlan(c,scope,core,new Set(['tests/__init__.py']));
  assert.deepEqual(plan.batches.map(b=>b.chunks.length),[24,5]); assert.equal(plan.paths.length,29);
  assert.equal(plan.chunks.length,29);assert.deepEqual(plan.chunks.map(c=>c.sequence),Array.from({length:29},(_,i)=>i+1));
  assert.ok(plan.patch.includes('AI09_VERIFIED_EMPTY_FILE_ADDITION'));
  assert.ok(!plan.chunks.at(-1).patch.includes('@@'));
  assert.equal(plan.patchSha256,createHash('sha256').update(plan.patch).digest('hex'));
});
test('empty files require exact-head contents proof rather than statistics alone',()=>{
  const c=fixture();c.files.push(emptyEntry());
  assert.throws(()=>buildReviewPlan(c,scope,core,new Set()),/EMPTY.*UNVERIFIED/);
  const data={path:'tests/__init__.py',sha:empty,type:'file',size:0,encoding:'base64',content:''};
  assert.equal(verifyEmptyContent(data,c.files[1]),true);
  for(const bad of [{...data,size:1},{...data,sha:'c'.repeat(40)},{...data,type:'symlink'},
    {...data,path:'other.py'},{...data,content:'eA=='},{...data,encoding:'none'}])
    assert.throws(()=>verifyEmptyContent(bad,c.files[1]),/EMPTY/);
});
test('nonempty missing patches, binary files, renames and altered statistics cannot use empty-file admission',()=>{
  for(const change of [{status:'removed'},{status:'renamed'},{sha:'c'.repeat(40)},{changes:1},{additions:1},{patch:''}]){
    const c=fixture();c.files.push({...emptyEntry(),...change});
    assert.throws(()=>buildReviewPlan(c,scope,core,new Set(['tests/__init__.py'])));
  }
});
test('duplicate paths, unsafe metadata paths, truncated text, and total bytes still HOLD',()=>{
  const c=fixture(2);c.files[1].filename=c.files[0].filename;
  assert.throws(()=>buildReviewPlan(c,scope,core,new Set()),/PATH/);
  for(const path of ['../escape.py','/absolute.py','src/a\\b.py','src/.env','src/a\n.py']){
    const x=fixture();x.files.push({...emptyEntry(),filename:path});
    assert.throws(()=>buildReviewPlan(x,scope,core,new Set([path])));
  }
  const x=fixture();x.files[0].additions=2;assert.throws(()=>buildReviewPlan(x,scope,core,new Set()),/incomplete_github_patch/);
  const huge=fixture(30);for(const f of huge.files){f.patch='@@ -0,0 +1,80 @@\n'+Array.from({length:80},()=>'+const value = "'+'x'.repeat(60)+'";').join('\n');f.additions=80;}
  assert.throws(()=>buildReviewPlan(huge,scope,core,new Set()),/BUDGET/);
});
test('two batches use unchanged GORIQ consolidation and require every valid chunk',async()=>{
  const plan=buildReviewPlan(fixture(25),scope,core,new Set());
  const reports=[];
  for(const batch of plan.batches){const rows=[];for(const c of batch.chunks)
    rows.push(await core.reviewLocalPatch({...scope,makerRole:'Builder',paths:c.paths,patch:c.patch,infer:clean}));reports.push(rows);}
  assert.equal(consolidateBatches(plan,reports,scope,core).status,'NO_ACTIONABLE_FINDINGS');
  const missing=structuredClone(reports);missing[1]=[];
  assert.equal(consolidateBatches(plan,missing,scope,core).status,'BLOCKED');
  const duplicate=structuredClone(reports);duplicate[1][0]=duplicate[0][0];
  assert.equal(consolidateBatches(plan,duplicate,scope,core).status,'BLOCKED');
  assert.equal(consolidateBatches(plan,[reports[0]],scope,core).status,'BLOCKED');
  const forged=structuredClone(reports);forged[1][0].mergeAuthorized=true;
  assert.equal(consolidateBatches(plan,forged,scope,core).status,'BLOCKED');
});
test('more than 48 slices is rejected even below the whole-patch byte budget',()=>{
  const c=fixture(25);
  for(const f of c.files){f.patch='@@ -0,0 +1,55 @@\n'+Array.from({length:55},()=>'+const v = "'+'x'.repeat(65)+'";').join('\n');f.additions=55;}
  assert.throws(()=>buildReviewPlan(c,scope,core,new Set()),/TOTAL_BUDGET/);
});
test('plan digest binds source metadata and ordering',()=>{
  const c=fixture(2),plan=buildReviewPlan(c,scope,core,new Set());
  const reordered=structuredClone(c);reordered.files.reverse();
  assert.notEqual(plan.planSha256,buildReviewPlan(reordered,scope,core,new Set()).planSha256);
  c.files[0].sha='d'.repeat(40);
  assert.notEqual(plan.planSha256,buildReviewPlan(c,scope,core,new Set()).planSha256);
});
