// RACE-only adapter; canonical Git JSON is durable, SQLite is a derived copy.
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {basename,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const ROOT=new URL('../',import.meta.url);
export const GOAL='haji84/RACE-AI:pr65-development-context';
const REPO='haji84/RACE-AI',ISSUER='github-actions-public-api';
export const PROBES=[
 {id:'mock-continuation',run:39929792420,head:'68d59fe6c755a89d23efaefa2a2864a8dc5ba36a',job:'pilot',step:'Test bounded offline mock continuation and restart'},
 {id:'real-model-probe',run:39929456215,head:'86f1be3c96e3a7e7dc529eb6c55748a827eb7779',job:'constrained-ai-trial',step:'Generate and independently verify two constrained functions'},
 {id:'cross-run-probe',run:39929456215,head:'86f1be3c96e3a7e7dc529eb6c55748a827eb7779',job:'checkpoint-consumer',step:'Verify all transferred files before resuming trusted current runner'}
];
export const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const clone=x=>structuredClone(x);
function exactKeys(obj,keys){if(!obj||typeof obj!=='object'||Array.isArray(obj)||Object.keys(obj).some(k=>!keys.includes(k)))throw Error('SCHEMA_KEYS_REJECTED');}
function safeText(s){if(typeof s!=='string'||s.length>2000||/[\x00-\x08]|sk-[A-Za-z0-9]{12}|github_pat_|ghp_|-----BEGIN|(?:user|assistant|system)\s*:/i.test(s)||/[^\s]+@[^\s]+\./.test(s))throw Error('UNSAFE_TEXT');}
export function validateSnapshot(s){
 exactKeys(s,['kind','version','repository','goalId','revision','previousDigest','observedHead','updatedAt','state','evidenceReferences']);
 if(s.kind!=='race-compass-canonical'||s.version!==1||s.repository!==REPO||s.goalId!==GOAL||!Number.isSafeInteger(s.revision)||s.revision<1||!(/^[a-f0-9]{40}$/.test(s.observedHead))||!(s.previousDigest===null||/^[a-f0-9]{64}$/.test(s.previousDigest)))throw Error('SNAPSHOT_IDENTITY_INVALID');
 const w=s.state;
 exactKeys(w,['goalId','objective','definitionOfDone','currentState','status','riskClass','constraints','decisions','artifacts','verificationResults','childWorkItems','blockers','nextAction','updatedAt']);
 if(w.goalId!==GOAL||w.status!=='BLOCKED'||w.riskClass!=='R1'||w.verificationResults?.length!==0||w.childWorkItems?.length!==0||!w.blockers?.length)throw Error('SELF_ASSERTED_STATE_REJECTED');
 for(const list of [w.definitionOfDone,w.constraints,w.decisions,w.artifacts,w.blockers,s.evidenceReferences])if(!Array.isArray(list)||list.length>64)throw Error('CAPACITY_INVALID');
 if(JSON.stringify(w.definitionOfDone.map(x=>x.id))!==JSON.stringify([...PROBES.map(x=>x.id),'race-product']))throw Error('CHECKPOINT_CRITERIA_CHANGED');
 for(const c of w.definitionOfDone){exactKeys(c,['id','description','required']);if(c.required!==true)throw Error('CRITERION_WAIVER_REJECTED');safeText(c.description);}
 for(const d of w.decisions){exactKeys(d,['id','summary','rationale','at']);[d.id,d.summary,d.rationale].forEach(safeText);if(!Number.isFinite(Date.parse(d.at)))throw Error('INVALID_DECISION_DATE');}
 for(const a of w.artifacts){exactKeys(a,['id','uri','kind']);[a.id,a.kind].forEach(safeText);if(!/^https:\/\/github.com\/haji84\/RACE-AI\/(issues|pull|actions\/runs)\/\d+$/.test(a.uri))throw Error('ARTIFACT_LINK_REJECTED');}
 for(const p of PROBES){const r=s.evidenceReferences.find(x=>x.criterionId===p.id);if(!r||Object.keys(r).length!==3||r.runId!==p.run||r.head!==p.head)throw Error('EVIDENCE_REFERENCE_CHANGED');}
 if(s.evidenceReferences.length!==PROBES.length)throw Error('EVIDENCE_REFERENCE_CHANGED');
 [w.objective,w.currentState,w.nextAction,...w.constraints,...w.blockers].forEach(safeText);
 for(const t of [s.updatedAt,w.updatedAt])if(!Number.isFinite(Date.parse(t)))throw Error('INVALID_DATE');
 if(JSON.stringify(s).length>32000)throw Error('SNAPSHOT_TOO_LARGE');
 return s;
}
export async function loadCore(){
 const manifest=JSON.parse(readFileSync(new URL('vendor/compass/PIN.json',ROOT),'utf8'));
 if(manifest.repository!=='haji84/AI-'||manifest.commit!=='a500c70dd3585aeb83596f7d85cf7ee2975dbe2a'||manifest.files.length!==6)throw Error('UPSTREAM_PIN_INVALID');
 for(const p of manifest.files){
  if(!/^src\/(compass|orchestrator)\/[a-z-]+\.ts$/.test(p.path))throw Error('PIN_PATH_INVALID');
  const bytes=readFileSync(new URL('vendor/compass/'+p.path,ROOT));
  const sha=createHash('sha1').update('blob '+bytes.length+'\0').update(bytes).digest('hex');
  if(sha!==p.sha)throw Error('UPSTREAM_BYTES_CHANGED');
 }
 return { ...(await import('../vendor/compass/src/compass/store.ts')),...(await import('../vendor/compass/src/orchestrator/completion-path.ts')) };
}
export async function getPublic(path){
 if(!/^pulls\/65$|^actions\/runs\/\d+(\/jobs\?per_page=100)?$/.test(path))throw Error('API_PATH_NOT_ALLOWED');
 const response=await fetch('https://api.github.com/repos/'+REPO+'/'+path,{headers:{Accept:'application/vnd.github+json'},redirect:'error',signal:AbortSignal.timeout(15000)});
 if(!response.ok)throw Error('EVIDENCE_UNAVAILABLE_'+response.status);
 const text=await response.text();if(text.length>500000)throw Error('API_RESPONSE_TOO_LARGE');
 return JSON.parse(text);
}
export function verifyObservation(p,run,jobs,now){
 const t=Date.parse(run.updated_at),current=Date.parse(now);
 if(!Number.isFinite(t)||!Number.isFinite(current)||t>current||current-t>86400000)throw Error('EVIDENCE_STALE_OR_FUTURE');
 if(run.id!==p.run||run.head_sha!==p.head||run.repository?.full_name!==REPO||run.head_branch!=='feat/completion-controller-pilot-20261016'||run.path!=='.github/workflows/completion-controller-pilot.yml'||run.event!=='pull_request'||run.run_attempt!==1||run.status!=='completed'||run.conclusion!=='success')throw Error('RUN_PROVENANCE_INVALID');
 const matching=jobs.jobs?.filter(j=>j.name===p.job);
 if(matching?.length!==1)throw Error('JOB_MISSING_OR_AMBIGUOUS');
 const job=matching[0],step=job.steps?.filter(s=>s.name===p.step);
 if(job.head_sha!==p.head||job.run_id!==p.run||job.status!=='completed'||job.conclusion!=='success'||step?.length!==1||step[0].status!=='completed'||step[0].conclusion!=='success')throw Error('REQUIRED_STEP_NOT_EXECUTED');
 const facts={repository:REPO,runId:p.run,attempt:1,head:p.head,workflow:run.path,jobId:job.id,step:p.step,conclusion:'success',updatedAt:run.updated_at};
 return {criterionId:p.id,issuer:ISSUER,verified:true,sourceRevision:p.head,artifactDigest:digest(facts),environment:'historical-github-actions',kind:'completed-required-step',recordedAt:run.updated_at,reference:job.html_url,facts};
}
export async function assess(snapshot,{expectedHead,client=getPublic,now=new Date().toISOString()}){
 validateSnapshot(snapshot);
 if(!/^[a-f0-9]{40}$/.test(expectedHead))throw Error('EXECUTION_HEAD_REQUIRED');
 const pr=await client('pulls/65');
 if(pr.head?.sha!==expectedHead||pr.head?.repo?.full_name!==REPO||pr.base?.repo?.full_name!==REPO)throw Error('EXECUTION_HEAD_CHANGED');
 const observations=[],errors=[],cache=new Map();
 for(const p of PROBES){
  try{
   if(!cache.has(p.run))cache.set(p.run,[await client('actions/runs/'+p.run),await client('actions/runs/'+p.run+'/jobs?per_page=100')]);
   observations.push(verifyObservation(p,...cache.get(p.run),now));
  }catch(e){errors.push(p.id+':'+e.message);}
 }
 const {assessCompletionPath}=await loadCore();
 const state=clone(snapshot.state);
 state.verificationResults=[]; // imported labels never become evidence
 const requirements=observations.map(e=>({criterionId:e.criterionId,weight:1,evidence:[{kind:e.kind,environment:e.environment,sourceRevision:e.sourceRevision,artifactDigest:e.artifactDigest,trustedIssuers:[ISSUER]}]}));
 const cycle=assessCompletionPath(state,{goalId:GOAL,cycleId:'race-checkpoint-'+digest({expectedHead,now,observations}),at:now,requirements,evidence:observations,candidates:[],capabilities:{},completedWorkItems:[],deliveries:[],responses:[]},[]);
 if(cycle.executionAuthority!==false||cycle.readyForCompletionReview)throw Error('UNSAFE_COMPLETION_CLAIM');
 const finalPr=await client('pulls/65');
 if(finalPr.head?.sha!==expectedHead)throw Error('EXECUTION_HEAD_CHANGED');
 return {kind:'race-compass-assessment',sourceSnapshotDigest:digest(snapshot),executionHead:expectedHead,assessedAt:now,status:'BLOCKED',historicalVerifiedCriteria:cycle.verifiedCriteria,currentProductVerified:false,artifactContentVerified:false,errors,observations,cycle,automaticWriteback:false};
}
export async function importCanonical(dbPath,snapshot,{expectedDigest,expectedRevision,previousDigest=null}){
 validateSnapshot(snapshot);
 if(basename(dbPath)!=='race-compass.sqlite'||dbPath===':memory:')throw Error('DEDICATED_RACE_DB_REQUIRED');
 if(expectedDigest!==digest(snapshot)||expectedRevision!==snapshot.revision)throw Error('SNAPSHOT_CAS_MISMATCH');
 const {CompassStore}=await loadCore();const db=new CompassStore(dbPath);
 try{
  const goal=db.getGoal();if(goal&&goal.title!==GOAL)throw Error('FOREIGN_DATABASE');
  db.updateActive(active=>{
   if(active.some(x=>x?.kind==='gai-work-state'&&x.goalId!==GOAL))throw Error('FOREIGN_WORKSTATE');
   const owned=active.filter(x=>x?.kind==='gai-work-state'&&x.goalId===GOAL);
   if(owned.length>1)throw Error('DUPLICATE_ENVELOPE');
   const old=owned[0];
   if(old){
    if(old.raceCanonical?.digest===expectedDigest)return active;
    if(previousDigest!==old.raceCanonical?.digest||snapshot.previousDigest!==previousDigest||snapshot.revision!==old.raceCanonical.snapshot.revision+1)throw Error('STALE_CANONICAL_UPDATE');
    for(const d of old.state.decisions)if(!snapshot.state.decisions.some(x=>JSON.stringify(x)===JSON.stringify(d)))throw Error('DECISION_HISTORY_LOSS');
   } else if(previousDigest!==null||snapshot.previousDigest!==null||snapshot.revision!==1)throw Error('MISSING_PREVIOUS_CANONICAL');
   const envelope={kind:'gai-work-state',version:1,goalId:GOAL,state:clone(snapshot.state),events:[...(old?.events??[]),{id:'snapshot-'+expectedDigest,at:snapshot.updatedAt,type:'canonical-import',summary:'Imported sanitized RACE canonical revision '+snapshot.revision}],completionAdvisory:[],raceCanonical:{digest:expectedDigest,snapshot:clone(snapshot)}};
   return [...active.filter(x=>x!==old),envelope];
  });
 }finally{db.close();}
}
export async function exportCanonical(dbPath){
 if(basename(dbPath)!=='race-compass.sqlite')throw Error('DEDICATED_RACE_DB_REQUIRED');
 const {CompassStore}=await loadCore();const db=new CompassStore(dbPath);
 try{
  const entries=db.getState().active.filter(x=>x?.kind==='gai-work-state'&&x.goalId===GOAL);
  if(entries.length!==1)throw Error('CANONICAL_ENVELOPE_MISSING');
  const e=entries[0];validateSnapshot(e.raceCanonical.snapshot);
  if(digest(e.raceCanonical.snapshot)!==e.raceCanonical.digest||JSON.stringify(e.state)!==JSON.stringify(e.raceCanonical.snapshot.state))throw Error('DERIVED_STATE_CHANGED');
  return clone(e.raceCanonical.snapshot);
 }finally{db.close();}
}
async function cli(){
 const [mode,path,dbOrHead,out]=process.argv.slice(2);
 if(mode==='import'){
  const s=JSON.parse(readFileSync(path,'utf8'));await importCanonical(dbOrHead,s,{expectedDigest:digest(s),expectedRevision:s.revision});console.log('COMPASS_IMPORT_PASS');
 }else if(mode==='export'){const s=await exportCanonical(path);writeFileSync(dbOrHead,JSON.stringify(s,null,2)+'\n');console.log('COMPASS_EXPORT_PASS');
 }else if(mode==='assess'){
  const s=JSON.parse(readFileSync(path,'utf8')),a=await assess(s,{expectedHead:dbOrHead});writeFileSync(out,JSON.stringify(a,null,2)+'\n');
  console.log(JSON.stringify({status:a.status,historicalVerifiedCriteria:a.historicalVerifiedCriteria,errors:a.errors,currentProductVerified:false,automaticWriteback:false}));
  if(a.errors.length)process.exitCode=1;
 }else throw Error('usage: import SNAPSHOT DB | export DB OUTPUT | assess SNAPSHOT EXPECTED_HEAD OUTPUT');
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))cli().catch(e=>{console.error(e.message);process.exitCode=1;});
