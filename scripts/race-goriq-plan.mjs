// RACE evidence planning only; inference, chunk validation and consolidation
// remain the pinned, unchanged GORIQ implementation.
import {createHash} from 'node:crypto';
const EMPTY='e69de29bb2d1d6434b8b29ae775ad8c2e48c5391';
const hash=x=>createHash('sha256').update(x).digest('hex');
const fail=code=>{throw Error(code);};
export function safeReviewPath(path) {
  return typeof path==='string' && path.length>0 && path.length<=250 &&
    /^[A-Za-z0-9_./-]+$/.test(path) && !path.startsWith('/') && !path.startsWith('-') &&
    path.split('/').every(p=>p && p!=='.' && p!=='..');
}
export function isEmptyAddition(file) {
  return file?.status==='added' && file.sha===EMPTY && file.additions===0 && file.deletions===0 &&
    file.changes===0 && file.patch===undefined && safeReviewPath(file.filename) &&
    !/(^|\/)(\.env(\.|$)|.*\.dpapi$|.*\.pem$|.*\.key$|id_rsa$)/i.test(file.filename);
}
export function verifyEmptyContent(content,file) {
  if(!isEmptyAddition(file) || content?.path!==file.filename || content.sha!==EMPTY ||
    content.type!=='file' || content.size!==0 || content.encoding!=='base64' || content.content!=='')
    fail('RACE_EMPTY_CONTENT_UNVERIFIED');
  return true;
}
export function buildReviewPlan(compare,scope,core,verifiedEmptyFiles=new Set()) {
  if(!Array.isArray(compare?.files) || !compare.files.length || compare.files.length>30)
    fail('RACE_PLAN_FILE_BUDGET');
  const paths=compare.files.map(f=>f?.filename);
  if(paths.some(p=>!safeReviewPath(p)) || new Set(paths).size!==paths.length)fail('RACE_PLAN_PATH_INVALID');
  const parts=[],chunks=[],emptyFiles=[];
  for(const [fileIndex,file] of compare.files.entries()) {
    if(file.patch===undefined) {
      if(!isEmptyAddition(file) || !verifiedEmptyFiles.has(file.filename))fail('RACE_EMPTY_FILE_UNVERIFIED');
      // Actual verified file-addition metadata; no fabricated textual hunk.
      // Filename existence can affect imports even though there are no bytes.
      const patch='diff --git a/'+file.filename+' b/'+file.filename+'\n# AI09_VERIFIED_EMPTY_FILE_ADDITION '+
        JSON.stringify({path:file.filename,status:'added',sha:EMPTY,bytes:0,contentsVerified:true});
      parts.push(patch);emptyFiles.push(file.filename);
      chunks.push({paths:[file.filename],patch,source:patch,fileIndex,metadataOnly:true});
    } else {
      const one={...compare,files:[file]}; core.assertCompleteComparison(one);
      const part=core.compareToReviewChunks(one,scope.baseSha,scope.headSha);
      parts.push(part.patch);
      for(const chunk of part.chunks)chunks.push({...chunk,fileIndex,metadataOnly:false});
      if(part.chunks.map(c=>c.source).join('\n')!==file.patch)fail('RACE_PLAN_SOURCE_COVERAGE');
    }
  }
  const patch=parts.join('\n');
  // The previous whole-patch/file/per-slice limits remain; at most TWO
  // sequential batches of <=24 are admitted, never unlimited retries.
  if(Buffer.byteLength(patch)>120*1024 || chunks.length>48 ||
    chunks.some(c=>Buffer.byteLength(c.patch)>4096))fail('RACE_PLAN_TOTAL_BUDGET');
  chunks.forEach((c,i)=>{c.sequence=i+1;});
  const batches=[];
  for(let i=0;i<chunks.length;i+=24) {
    const selected=chunks.slice(i,i+24);
    batches.push({paths:[...new Set(selected.flatMap(c=>c.paths))],
      patch:selected.map(c=>c.patch).join('\n'),chunks:selected});
  }
  const planSha256=hash(JSON.stringify({contract:'RACE_GORIQ_BATCHED_V2',...scope,
    files:compare.files.map(f=>({path:f.filename,status:f.status??null,sha:f.sha??null,
      additions:f.additions,deletions:f.deletions,changes:f.changes??null,patch:f.patch??null})),
    batches:batches.map(b=>b.chunks.map(c=>({sequence:c.sequence,sha256:hash(c.patch)})))}));
  return {paths,patch,patchSha256:hash(patch),planSha256,chunks,batches,emptyFiles};
}
export function consolidateBatches(plan,reports,scope,core) {
  const wholeScope={...scope,paths:plan.paths,patchSha256:plan.patchSha256};
  if(!Array.isArray(reports) || reports.length!==plan.batches.length)
    return core.makeBlockedReview(wholeScope,'incomplete_model_review');
  const batchReports=plan.batches.map((batch,i)=>core.consolidateChunkReviews(reports[i],
    {...scope,paths:batch.paths,patchSha256:hash(batch.patch)},batch.chunks));
  const blocked=batchReports.find(r=>r.status==='BLOCKED');
  if(blocked)return core.makeBlockedReview(wholeScope,blocked.blockers[0]);
  return core.holdUngroundedAdvisory(core.consolidateChunkReviews(batchReports,wholeScope,plan.batches),plan.patch);
}
