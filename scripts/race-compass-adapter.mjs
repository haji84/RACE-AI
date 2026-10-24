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
 exactKeys(s,['kind','version','repository','goalId','revision','previousDigest','observedHead','updatedAt','state','evidenceReferences','productPosition']);
 if(s.kind!=='race-compass-canonical'||s.version!==1||s.repository!==REPO||s.goalId!==GOAL||!Number.isSafeInteger(s.revision)||s.revision<1||!(/^[a-f0-9]{40}$/.test(s.observedHead))||!(s.previousDigest===null||/^[a-f0-9]{64}$/.test(s.previousDigest)))throw Error('SNAPSHOT_IDENTITY_INVALID');
 if((s.revision===1)!==(s.previousDigest===null))throw Error('REVISION_CHAIN_INVALID');
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
 if(s.productPosition!==undefined)validateProductPosition(s.productPosition);
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
 if(!/^pulls\/(65|69|71|72)$|^issues\/(67|68)$|^actions\/runs\?head_sha=[a-f0-9]{40}&per_page=100$|^actions\/runs\/\d+(\/jobs\?per_page=100)?$/.test(path))throw Error('API_PATH_NOT_ALLOWED');
 const response=await fetch('https://api.github.com/repos/'+REPO+'/'+path,{headers:{Accept:'application/vnd.github+json'},redirect:'error',signal:AbortSignal.timeout(15000)});
 if(!response.ok)throw Error('EVIDENCE_UNAVAILABLE_'+response.status);
 const text=await response.text();if(text.length>500000)throw Error('API_RESPONSE_TOO_LARGE');
 return JSON.parse(text);
}
export function verifyObservation(p,run,jobs,now){
 const t=Date.parse(run.updated_at),current=Date.parse(now);
 if(!Number.isFinite(t)||!Number.isFinite(current)||t>current)throw Error('EVIDENCE_TIME_INVALID_OR_FUTURE');
 if(run.id!==p.run||run.head_sha!==p.head||run.repository?.full_name!==REPO||run.head_branch!=='feat/completion-controller-pilot-20261016'||run.path!=='.github/workflows/completion-controller-pilot.yml'||run.event!=='pull_request'||run.run_attempt!==1||run.status!=='completed'||run.conclusion!=='success')throw Error('RUN_PROVENANCE_INVALID');
 const matching=jobs.jobs?.filter(j=>j.name===p.job);
 if(matching?.length!==1)throw Error('JOB_MISSING_OR_AMBIGUOUS');
 const job=matching[0],step=job.steps?.filter(s=>s.name===p.step);
 if(job.head_sha!==p.head||job.run_id!==p.run||job.status!=='completed'||job.conclusion!=='success'||step?.length!==1||step[0].status!=='completed'||step[0].conclusion!=='success')throw Error('REQUIRED_STEP_NOT_EXECUTED');
 const facts={repository:REPO,runId:p.run,attempt:1,head:p.head,workflow:run.path,jobId:job.id,step:p.step,conclusion:'success',updatedAt:run.updated_at};
 return {criterionId:p.id,issuer:ISSUER,verified:true,sourceRevision:p.head,artifactDigest:digest(facts),environment:'historical-github-actions',kind:'completed-required-step',recordedAt:run.updated_at,observedAt:now,reference:job.html_url,facts};
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

const PRODUCT_GOAL='haji84/RACE-AI:issue-67';
const PRODUCT_CHECKS=[{"number":69,"workflow":".github/workflows/four-sport-synthetic.yml","event":"pull_request","checks":[{"job":"Synthetic E2E (ubuntu-24.04)","steps":["Test odds isolation, deadlines and recovery (synthetic only)","Run four sport synthetic vertical E2E"]},{"job":"Synthetic E2E (windows-2022)","steps":["Test odds isolation, deadlines and recovery (synthetic only)","Run four sport synthetic vertical E2E"]}]},{"number":71,"workflow":".github/workflows/forecast-audit-ui.yml","event":"pull_request","checks":[{"job":"Viewer audit contract","steps":["Node contract and denominator tests","Python synthetic journal to viewer projection tests"]}]},{"number":72,"workflow":".github/workflows/offline-discovery-audit.yml","event":"pull_request","checks":[{"job":"offline_audit_tests","steps":["Offline regression suite","Cross-branch PR71 model-delivery to PR72 source binding (synthetic)"]}]}];
const FINAL_IDS=['all-races','future-98','pdca','honest-state','safety','ui','research-models'];
const MILESTONES=['M0','M1','M2','M3','M4'];
function same(a,b){return JSON.stringify(a)===JSON.stringify(b);}
function boundedList(x,max=32){if(!Array.isArray(x)||x.length>max)throw Error('PRODUCT_LIST_INVALID');}
function validTime(t){return typeof t==='string'&&Number.isFinite(Date.parse(t));}
function owners(x){boundedList(x,3);if(!x.length||new Set(x).size!==x.length||x.some(n=>![69,71,72].includes(n)))throw Error('PRODUCT_OWNER_INVALID');}
export function validateProductPosition(p){
 exactKeys(p,['goalId','sourceIssues','observedAt','mappingIdAuthority','acceptanceStatus','currentProductVerified','measuredHitAt8All','finalRequirements','milestones','pullRequests','nextActions','automaticWriteback']);
 if(p.goalId!==PRODUCT_GOAL||p.acceptanceStatus!=='BLOCKED'||p.currentProductVerified!==false||p.measuredHitAt8All!==null||p.automaticWriteback!==false||!validTime(p.observedAt))throw Error('PRODUCT_SELF_CERTIFICATION_REJECTED');
 safeText(p.mappingIdAuthority);
 for(const key of ['sourceIssues','finalRequirements','milestones','pullRequests','nextActions'])boundedList(p[key]);
 if(!same(p.sourceIssues.map(x=>x.number),[67,68])||!same(p.finalRequirements.map(x=>x.id),FINAL_IDS)||!same(p.milestones.map(x=>x.id),MILESTONES)||!same(p.pullRequests.map(x=>x.number),[69,71,72]))throw Error('PRODUCT_COVERAGE_CHANGED');
 for(const s of p.sourceIssues){exactKeys(s,['number','updatedAt','bodyDigest']);if(!validTime(s.updatedAt)||!/^[a-f0-9]{64}$/.test(s.bodyDigest))throw Error('SOURCE_PIN_INVALID');}
 for(const r of p.finalRequirements){exactKeys(r,['id','summary','status']);safeText(r.summary);if(r.status!=='UNVERIFIED')throw Error('PRODUCT_SELF_CERTIFICATION_REJECTED');}
 for(const m of p.milestones){
  exactKeys(m,['id','summary','acceptanceStatus','owners','files','gaps','dependsOn']);safeText(m.summary);owners(m.owners);
  if(m.acceptanceStatus!=='BLOCKED')throw Error('PRODUCT_SELF_CERTIFICATION_REJECTED');
  boundedList(m.files);boundedList(m.gaps);boundedList(m.dependsOn,5);
  if(!m.files.length||!m.gaps.length||m.dependsOn.some(id=>!MILESTONES.includes(id)||MILESTONES.indexOf(id)>=MILESTONES.indexOf(m.id)))throw Error('PRODUCT_DEPENDENCY_INVALID');
  m.gaps.forEach(safeText);
  for(const path of m.files)if(typeof path!=='string'||path.includes('..')||!/^([a-zA-Z0-9_.-]+\/)*[a-zA-Z0-9_.-]+$/.test(path))throw Error('PRODUCT_PATH_INVALID');
 }
 for(const pr of p.pullRequests){
  exactKeys(pr,['number','head','branch','base','baseHead','draft','state','runId','workflow','event','checks']);
  const expected=PRODUCT_CHECKS.find(x=>x.number===pr.number);
  if(!/^[a-f0-9]{40}$/.test(pr.head)||!/^[a-f0-9]{40}$/.test(pr.baseHead)||pr.draft!==true||pr.state!=='open'||!Number.isSafeInteger(pr.runId)||pr.runId<1||pr.workflow!==expected.workflow||pr.event!==expected.event||!same(pr.checks,expected.checks))throw Error('PRODUCT_CONTRACT_PIN_INVALID');
  [pr.branch,pr.base].forEach(safeText);
 }
 const seen=[];
 for(const a of p.nextActions){
  exactKeys(a,['id','owners','dependsOn','action']);[a.id,a.action].forEach(safeText);owners(a.owners);boundedList(a.dependsOn);
  if(seen.includes(a.id)||a.dependsOn.some(id=>!seen.includes(id)))throw Error('PRODUCT_ACTION_DAG_INVALID');seen.push(a.id);
 }
 if(!p.nextActions.length)throw Error('PRODUCT_NEXT_ACTION_MISSING');
 return p;
}
export async function assessProductPosition(position,{client=getPublic,now=new Date().toISOString()}={}){
 validateProductPosition(position);
 if(!validTime(now)||Date.parse(position.observedAt)>Date.parse(now))throw Error('PRODUCT_OBSERVATION_TIME_INVALID');
 const errors=[],observations=[],contractVerifiedPRs=[];
 let sourcesCurrent=true;
 for(const s of position.sourceIssues){
  try{
   const live=await client('issues/'+s.number);
   if(live.number!==s.number||live.html_url!=='https://github.com/'+REPO+'/issues/'+s.number||live.updated_at!==s.updatedAt||digest(live.body)!==s.bodyDigest)throw Error('SOURCE_CHANGED_REMAP_REQUIRED');
  }catch(e){sourcesCurrent=false;errors.push('issue'+s.number+':'+e.message);}
 }
 for(const p of position.pullRequests){
  try{
   const match=pr=>pr.number===p.number&&pr.head?.sha===p.head&&pr.head?.ref===p.branch&&pr.head?.repo?.full_name===REPO&&pr.base?.repo?.full_name===REPO&&pr.base?.ref===p.base&&pr.base?.sha===p.baseHead&&pr.state==='open'&&pr.draft===true&&pr.merged===false;
   if(!match(await client('pulls/'+p.number)))throw Error('PRODUCT_PR_CHANGED');
   const verifyLatest=async()=>{
   const listing=await client('actions/runs?head_sha='+p.head+'&per_page=100');
   if(!Array.isArray(listing.workflow_runs)||listing.total_count!==listing.workflow_runs.length||listing.total_count>100)throw Error('PRODUCT_RUN_LIST_INCOMPLETE');
   const latest=listing.workflow_runs.filter(r=>r.path===p.workflow&&r.head_sha===p.head).sort((a,b)=>b.id-a.id)[0];
   if(!latest||latest.id!==p.runId||latest.status!=='completed'||latest.conclusion!=='success'||latest.run_attempt!==1)throw Error('PRODUCT_LATEST_RUN_CHANGED');
   };
   await verifyLatest();
   const run=await client('actions/runs/'+p.runId),jobs=await client('actions/runs/'+p.runId+'/jobs?per_page=100');
   if(run.id!==p.runId||run.head_sha!==p.head||run.head_branch!==p.branch||run.repository?.full_name!==REPO||run.path!==p.workflow||run.event!==p.event||run.run_attempt!==1||run.status!=='completed'||run.conclusion!=='success')throw Error('PRODUCT_RUN_INVALID');
   if(!validTime(run.updated_at)||Date.parse(run.updated_at)>Date.parse(now))throw Error('PRODUCT_RUN_TIME_INVALID');
   if(!Array.isArray(jobs.jobs)||jobs.total_count!==jobs.jobs.length||jobs.total_count>100)throw Error('PRODUCT_JOBS_INCOMPLETE');
   const requiredJobs=[];
   for(const c of p.checks){
    const matches=jobs.jobs.filter(j=>j.name===c.job);if(matches.length!==1)throw Error('PRODUCT_JOB_MISSING');
    const job=matches[0];
    if(job.run_id!==p.runId||job.head_sha!==p.head||job.status!=='completed'||job.conclusion!=='success')throw Error('PRODUCT_JOB_NOT_SUCCESS');
    for(const name of c.steps){const steps=job.steps?.filter(s=>s.name===name);if(steps?.length!==1||steps[0].status!=='completed'||steps[0].conclusion!=='success')throw Error('PRODUCT_STEP_NOT_EXECUTED');}
    requiredJobs.push({jobId:job.id,name:job.name,steps:c.steps});
   }
   if(!match(await client('pulls/'+p.number)))throw Error('PRODUCT_PR_CHANGED');
   await verifyLatest(); // reject a newer failed/pending run even when head is unchanged
   const facts={repository:REPO,pr:p.number,head:p.head,baseHead:p.baseHead,runId:p.runId,workflow:p.workflow,requiredJobs,recordedAt:run.updated_at};
   observations.push({issuer:ISSUER,kind:'synthetic-contract-metadata',facts,digest:digest(facts),observedAt:now,artifactContentVerified:false});
   if(sourcesCurrent)contractVerifiedPRs.push(p.number);
  }catch(e){errors.push('PR'+p.number+':'+e.message);}
 }
 // Recheck source revisions after collecting PR receipts, too.
 for(const s of position.sourceIssues){try{const live=await client('issues/'+s.number);if(live.updated_at!==s.updatedAt||digest(live.body)!==s.bodyDigest)throw Error('SOURCE_CHANGED_REMAP_REQUIRED');}catch(e){sourcesCurrent=false;errors.push('issue'+s.number+':'+e.message);}}
 if(!sourcesCurrent)contractVerifiedPRs.length=0;
 // No accepted product evidence is generated from contract tests.
 return {goalId:PRODUCT_GOAL,sourceSnapshotDigest:digest(position),assessedAt:now,sourcesCurrent,contractVerifiedPRs,observations,errors,acceptanceStatus:'BLOCKED',currentProductVerified:false,measuredHitAt8All:null,executionAuthority:false,automaticWriteback:false,milestones:position.milestones.map(m=>({id:m.id,acceptanceStatus:'BLOCKED',implementationStatus:m.owners.every(n=>contractVerifiedPRs.includes(n))?'CONTRACT_VERIFIED':'UNVERIFIED',gaps:clone(m.gaps)})),nextActions:clone(position.nextActions)};
}

export async function importCanonical(dbPath,snapshot,{expectedDigest,expectedRevision,previousDigest=null,bootstrap=false}){
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
    if(old.raceCanonical.snapshot.productPosition&&!snapshot.productPosition)throw Error('PRODUCT_POSITION_LOSS');
    for(const d of old.state.decisions)if(!snapshot.state.decisions.some(x=>JSON.stringify(x)===JSON.stringify(d)))throw Error('DECISION_HISTORY_LOSS');
   } else if(previousDigest!==null || (snapshot.revision!==1 && !bootstrap))throw Error('EXPLICIT_TRUSTED_BOOTSTRAP_REQUIRED');
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
  const s=JSON.parse(readFileSync(path,'utf8'));await importCanonical(dbOrHead,s,{expectedDigest:digest(s),expectedRevision:s.revision,bootstrap:true});console.log('COMPASS_IMPORT_PASS');
 }else if(mode==='export'){const s=await exportCanonical(path);writeFileSync(dbOrHead,JSON.stringify(s,null,2)+'\n');console.log('COMPASS_EXPORT_PASS');
 }else if(mode==='assess'){
  const s=JSON.parse(readFileSync(path,'utf8')),a=await assess(s,{expectedHead:dbOrHead});writeFileSync(out,JSON.stringify(a,null,2)+'\n');
  console.log(JSON.stringify({status:a.status,historicalEvidenceStatus:a.errors.length?'BLOCKED':'VERIFIED_HISTORICAL_ONLY',historicalVerifiedCriteria:a.historicalVerifiedCriteria,errors:a.errors,currentProductVerified:false,automaticWriteback:false}));
  // Historical observation/network failures are an advisory BLOCKED result, not a reason to break unrelated future CI. Schema/head mismatches still throw.
 }else if(mode==='product'){
 const s=JSON.parse(readFileSync(path,'utf8'));validateSnapshot(s);const a=await assessProductPosition(s.productPosition);writeFileSync(dbOrHead,JSON.stringify(a,null,2)+'\n');console.log(JSON.stringify(a));
 }else throw Error('usage: import SNAPSHOT DB | export DB OUTPUT | assess SNAPSHOT EXPECTED_HEAD OUTPUT');
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))cli().catch(e=>{console.error(e.message);process.exitCode=1;});
