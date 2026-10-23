export const REPO='haji84/RACE-AI';
export const BRANCH='feat/completion-controller-pilot-20261016';
export const PATH='docs/CONTINUATION_TEST_RESULT_20261023.md';
export const MARKER='<!-- bounded-save-v1 -->';
export const ADDITION='\n'+MARKER+'\n## Automatically recorded technical verification\n\nHistorical cleanup checks passed on head `cf66a272a963ed418e94bdf409cea39ce21a5aba`: [bounded checks](https://github.com/haji84/RACE-AI/actions/runs/39948549502) and [Windows/Ubuntu regression](https://github.com/haji84/RACE-AI/actions/runs/39948549566). The regression used a PR merge-ref. This fixed technical note is not current product acceptance, generated-code adoption, deployment, or canonical-state writeback.\n';
const check=(v,m)=>{if(!v)throw Error(m);};
const sha=v=>typeof v==='string'&&/^[a-f0-9]{40}$/.test(v);
export function appendResult(old){
 check(typeof old==='string'&&Buffer.byteLength(old)<=16384,'DOCUMENT_INVALID');
 if(old.includes(MARKER)){check(old.endsWith(ADDITION)&&old.split(MARKER).length===2,'MARKER_CONFLICT');return old;}
 return old+ADDITION;
}
export function validateContext(c){
 check(c.repository===REPO&&c.branch===BRANCH&&c.actor==='haji84'&&c.event==='pull_request'&&c.action==='synchronize'&&c.pr==='65'&&c.attempt==='1'&&/^[1-9][0-9]{0,14}$/.test(c.run)&&/^[1-9][0-9]{0,6}$/.test(c.expectedRunNumber)&&c.runNumber===c.expectedRunNumber&&sha(c.head)&&sha(c.prepared),'SAVE_SCOPE_INVALID');
}
export async function verifyEvidence(api){
 const head='cf66a272a963ed418e94bdf409cea39ce21a5aba';
 const specs=[
  [39948549502,'.github/workflows/completion-controller-pilot.yml',{'pilot':['Verify isolated controller repair grammar and independent baseline regressions','Test deterministic controller and recovery'],'compass-adapter':['Verify original Compass pins, isolation and evidence rejection','Import canonical state, end process, reopen and export actual Compass SQLite']}],
  [39948549566,'.github/workflows/tests.yml',{'unit (windows-latest)':['Test full runtime, real signed JWTs and cross-language money parity','Validate browser code and state transitions'],'unit (ubuntu-latest)':['Test full runtime, real signed JWTs and cross-language money parity','Validate browser code and state transitions']}]
 ];
 for(const [id,path,expected] of specs){
  const r=await api.get('actions/runs/'+id);
  check(r.id===id&&r.head_sha===head&&r.head_branch===BRANCH&&r.repository?.full_name===REPO&&r.event==='pull_request'&&r.path===path&&r.run_attempt===1&&r.status==='completed'&&r.conclusion==='success','EVIDENCE_RUN_INVALID');
  const list=await api.get('actions/runs/'+id+'/jobs?per_page=100');
  check(list.total_count===list.jobs?.length&&list.total_count<=100,'EVIDENCE_JOBS_INCOMPLETE');
  for(const [name,steps] of Object.entries(expected)){
   const matches=list.jobs.filter(j=>j.name===name);
   check(matches.length===1&&matches[0].head_sha===head&&matches[0].status==='completed'&&matches[0].conclusion==='success','EVIDENCE_JOB_INVALID');
   for(const name of steps){const found=matches[0].steps?.filter(s=>s.name===name);check(found?.length===1&&found[0].status==='completed'&&found[0].conclusion==='success','EVIDENCE_STEP_INVALID');}
  }
 }
}
export async function saveOnce(c,api){
 validateContext(c);
 const refPath='git/ref/heads/'+BRANCH;
 const ref=await api.get(refPath),live=ref.object?.sha;
 check(sha(live),'REF_INVALID');
 const pr=await api.get('pulls/65');
 check(pr.state==='open'&&pr.head?.repo?.full_name===REPO&&pr.base?.repo?.full_name===REPO&&pr.head.ref===BRANCH&&pr.head.sha===live,'PR_CHANGED');
 const original=await api.get('git/commits/'+c.head);
 check(original.parents?.length===1&&original.parents[0].sha===c.prepared,'PREPARED_PARENT_MISMATCH');
 const file=await api.get('contents/'+PATH+'?ref='+live);
 check(file.type==='file'&&file.path===PATH&&file.encoding==='base64'&&file.size<=16384,'DOCUMENT_METADATA_INVALID');
 const old=Buffer.from(file.content,'base64').toString('utf8');
 const next=appendResult(old);
 if(next===old){
  const saved=await api.get('git/commits/'+live);
  check(saved.parents?.length===1&&saved.parents[0].sha===c.head&&saved.message==='docs: save bounded technical verification [save-v1]','NOOP_PROVENANCE_INVALID');
  const diff=await api.get('compare/'+c.head+'...'+live);
  check(diff.files?.length===1&&diff.files[0].filename===PATH&&diff.files[0].status==='modified','NOOP_DIFF_INVALID');
  return {status:'NOOP',head:live,path:PATH};
 }
 check(live===c.head,'BRANCH_CHANGED');
 // Only already-public, pinned historical receipts; no model output or arbitrary payload.
 await verifyEvidence(api);
 const blob=await api.post('git/blobs',{content:next,encoding:'utf-8'});
 check(sha(blob.sha),'BLOB_INVALID');
 const tree=await api.post('git/trees',{base_tree:original.tree.sha,tree:[{path:PATH,mode:'100644',type:'blob',sha:blob.sha}]});
 check(sha(tree.sha),'TREE_INVALID');
 const commit=await api.post('git/commits',{message:'docs: save bounded technical verification [save-v1]',tree:tree.sha,parents:[c.head]});
 check(sha(commit.sha)&&commit.parents?.length===1&&commit.parents[0].sha===c.head,'COMMIT_INVALID');
 const diff=await api.get('compare/'+c.head+'...'+commit.sha);
 check(diff.files?.length===1&&diff.files[0].filename===PATH&&diff.files[0].status==='modified','DIFF_ALLOWLIST_FAILED');
 check((await api.get(refPath)).object?.sha===c.head,'BRANCH_CHANGED_BEFORE_UPDATE');
 // Non-force, single-parent update rejects divergent concurrent advances; never retries.
 await api.patch('git/refs/heads/'+BRANCH,{sha:commit.sha,force:false});
 check((await api.get(refPath)).object?.sha===commit.sha,'REF_READBACK_UNCONFIRMED');
 const readback=await api.get('contents/'+PATH+'?ref='+commit.sha);
 check(readback.sha===blob.sha&&readback.encoding==='base64'&&Buffer.from(readback.content,'base64').toString('utf8')===next,'CONTENT_READBACK_UNCONFIRMED');
 return {status:'SAVED',head:commit.sha,parent:c.head,path:PATH,source_runs:[39948549502,39948549566]};
}
