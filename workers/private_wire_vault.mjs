// Storage-only local candidate. No authority, clock, receipt, network or model.
import {OBJECTS,CHUNKS,CLASSIFY,INITIALIZE,guard} from './private_wire_vault_schema.mjs';
const CHUNK=524288,MAX=4194304,SCHEMA='RACE_AI_LOCAL_PRIVATE_WIRE_CLAIM_V1';
const fields=['schema','destination_contract','destination_ref','owner_ref','request_sha256','wire_sha256','delivery_sha256','model_source_sha40','retention_request_sha256','reservation_sha256','reservation_row_sha256','reservation_commit_guard_at','retain_until','protection_policy','wire_bytes','chunk_sha256'];
const encoder=new TextEncoder(),hex=/^[0-9a-f]{64}$/;
function fail(){throw Error('LOCAL_PRIVATE_WIRE_REJECTED');}
const sha=async raw=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),v=>v.toString(16).padStart(2,'0')).join('');
function timestamp(value){
  if(typeof value!=='string'||value.length>32)fail();
  const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
  if(!m)fail();
  const [y,mo,d,h,mi,s]=m.slice(1,7).map(Number),leap=y%4===0&&(y%100!==0||y%400===0);
  if(y<1||mo<1||mo>12||d<1||d>[31,leap?29:28,31,30,31,30,31,31,30,31,30,31][mo-1]||h>23||mi>59||s>59)fail();
  return BigInt(Date.parse(value.slice(0,19)+'Z'))*1000n+BigInt((m[7]??'').padEnd(6,'0'));
}
function claimCopy(input){
  if(!input||Object.getPrototypeOf(input)!==Object.prototype)fail();
  const keys=Reflect.ownKeys(input);
  if(keys.length!==fields.length||keys.some(k=>typeof k!=='string'||!fields.includes(k)))fail();
  const out={};
  for(const key of fields){
    const descriptor=Object.getOwnPropertyDescriptor(input,key);
    if(!descriptor||!('value'in descriptor))fail();
    const v=descriptor.value;
    if(key==='chunk_sha256'){
      if(!Array.isArray(v)||Object.getPrototypeOf(v)!==Array.prototype||v.length<1||v.length>8||Reflect.ownKeys(v).length!==v.length+1)fail();
      out[key]=[];
      for(let i=0;i<v.length;i++){const d=Object.getOwnPropertyDescriptor(v,String(i));if(!d||!('value'in d)||typeof d.value!=='string'||!hex.test(d.value))fail();out[key].push(d.value);}
    }else if(key==='wire_bytes'){if(!Number.isSafeInteger(v)||v<1||v>MAX)fail();out[key]=v;}
    else{if(typeof v!=='string'||v.length>128)fail();out[key]=v;}
  }
  if(out.schema!==SCHEMA||out.destination_contract!=='LOCAL_SQLITE_D1_BATCH_CANDIDATE_V1'||!/^local-private-vault-[a-z0-9-]{1,64}$/.test(out.destination_ref)||!(/^[\x20-\x7e]{1,128}$/).test(out.owner_ref)||out.owner_ref.trim()!==out.owner_ref||out.protection_policy!=='LOCAL_INSERT_ONLY_SQL_V1'||out.chunk_sha256.length!==Math.ceil(out.wire_bytes/CHUNK))fail();
  for(const key of ['request_sha256','wire_sha256','delivery_sha256','retention_request_sha256','reservation_sha256','reservation_row_sha256'])if(!hex.test(out[key]))fail();
  if(!/^[0-9a-f]{40}$/.test(out.model_source_sha40)||timestamp(out.retain_until)<=timestamp(out.reservation_commit_guard_at))fail();
  if(encoder.encode(canonical(out)).length>8192)fail();
  return out;
}
function canonical(claim){return JSON.stringify(Object.fromEntries(Object.keys(claim).sort().map(key=>[key,claim[key]])));}
function rawCopy(value,expected){
  const proto=Object.getPrototypeOf(Uint8Array.prototype),size=Object.getOwnPropertyDescriptor(proto,'byteLength').get.call(value);
  if(!(value instanceof Uint8Array)||size<1||size>MAX||size!==expected)fail();
  return new Uint8Array(value);
}
async function admit(callback,claim){
  if(typeof callback!=='function')fail();
  const owned=claimCopy(claim),before=canonical(owned);
  if(await callback(owned)!==true||canonical(claimCopy(owned))!==before)fail();
}
function statement(binding,sql,...args){return binding.prepare(sql).bind(...args);}
function results(value,count){
  if(!Array.isArray(value)||value.length!==count||value.some(v=>v?.success!==true||!Array.isArray(v.results)||!Number.isSafeInteger(v.meta?.changes)||v.meta.changes<0))fail();
  return value;
}
function admitted(result,key){
  if(result.meta.changes!==0||result.results.length!==1||Object.keys(result.results[0]).length!==1||result.results[0][key]!==1)fail();
}
async function classify(binding){
  try{const result=results(await binding.batch([statement(binding,CLASSIFY)]),1)[0],value=result.results;if(result.meta.changes!==0||value.length!==1||Object.keys(value[0]).length!==1||!['known','empty','foreign'].includes(value[0].state))fail();return value[0].state;}
  catch{return 'unavailable';}
}
async function load(binding,c,locator){
  const safe="typeof(claim_json)='text' AND length(CAST(claim_json AS BLOB)) BETWEEN 1 AND 8192 AND typeof(wire_sha256)='text' AND length(wire_sha256)=64 AND typeof(wire_bytes)='integer' AND wire_bytes BETWEEN 1 AND 4194304 AND typeof(chunk_count)='integer' AND chunk_count BETWEEN 1 AND 8";
  const queries=[statement(binding,guard(false)),statement(binding,`SELECT CASE WHEN ${safe} THEN claim_json END AS claim_json,CASE WHEN ${safe} THEN wire_sha256 END AS wire_sha256,CASE WHEN ${safe} THEN wire_bytes END AS wire_bytes,CASE WHEN ${safe} THEN chunk_count END AS chunk_count FROM ${OBJECTS} WHERE locator=?`,locator),
    statement(binding,`SELECT CASE WHEN typeof(ordinal)='integer' AND ordinal BETWEEN 0 AND 7 THEN ordinal END AS ordinal,CASE WHEN typeof(chunk_sha256)='text' AND length(chunk_sha256)=64 THEN chunk_sha256 END AS chunk_sha256,typeof(body) AS body_type,length(body) AS body_bytes FROM ${CHUNKS} WHERE locator=? ORDER BY ordinal LIMIT 9`,locator)];
  const patterns=[],checks=[locator,locator,locator,canonical(c),c.wire_sha256,c.wire_bytes,c.chunk_sha256.length,locator,c.chunk_sha256.length,locator];
  for(let i=0;i<c.chunk_sha256.length;i++){
    patterns.push("(typeof(ordinal)='integer' AND ordinal=? AND typeof(chunk_sha256)='text' AND chunk_sha256=? AND typeof(body)='blob' AND length(body)=?)");
    checks.push(i,c.chunk_sha256[i],Math.min(CHUNK,c.wire_bytes-i*CHUNK));
  }
  // This statement must abort the SAME read batch before any body SELECT.
  queries.push(statement(binding,`SELECT CASE WHEN (NOT EXISTS(SELECT 1 FROM ${OBJECTS} WHERE locator=?) AND NOT EXISTS(SELECT 1 FROM ${CHUNKS} WHERE locator=?)) OR ((SELECT count(*) FROM ${OBJECTS} WHERE locator=? AND claim_json=? AND wire_sha256=? AND wire_bytes=? AND chunk_count=? AND ${safe})=1 AND (SELECT count(*) FROM ${CHUNKS} WHERE locator=?)=? AND NOT EXISTS(SELECT 1 FROM ${CHUNKS} WHERE locator=? AND NOT (${patterns.join(' OR ')}))) THEN 1 ELSE abs(-9223372036854775808) END AS preflight`,...checks));
  for(let i=0;i<c.chunk_sha256.length;i++)queries.push(statement(binding,`SELECT body FROM ${CHUNKS} WHERE locator=? AND ordinal=? AND typeof(body)='blob' AND length(body)=? AND typeof(chunk_sha256)='text' AND chunk_sha256=?`,locator,i,Math.min(CHUNK,c.wire_bytes-i*CHUNK),c.chunk_sha256[i]));
  const all=results(await binding.batch(queries),queries.length);
  if(all.some(r=>r.meta.changes!==0))fail();
  admitted(all[0],'admitted');admitted(all[3],'preflight');
  const meta=all[1].results,parts=all[2].results;
  if(!meta.length&&!parts.length)return null;
  if(meta.length!==1||meta[0].claim_json!==canonical(c)||meta[0].wire_sha256!==c.wire_sha256||meta[0].wire_bytes!==c.wire_bytes||meta[0].chunk_count!==c.chunk_sha256.length||parts.length!==c.chunk_sha256.length)fail();
  const output=new Uint8Array(c.wire_bytes);
  for(let i=0;i<parts.length;i++){
    const p=parts[i],size=Math.min(CHUNK,c.wire_bytes-i*CHUNK),rows=all[i+4].results;
    if(p.ordinal!==i||p.chunk_sha256!==c.chunk_sha256[i]||p.body_type!=='blob'||p.body_bytes!==size||rows.length!==1)fail();
    const source=rows[0].body;
    if(!(source instanceof Uint8Array)&&!(Array.isArray(source)&&source.length===size&&source.every(n=>Number.isInteger(n)&&n>=0&&n<=255)))fail();
    if(source.length!==size)fail();
    const bytes=new Uint8Array(source);
    if(await sha(bytes)!==c.chunk_sha256[i])fail();
    output.set(bytes,i*CHUNK);
  }
  if(await sha(output)!==c.wire_sha256)fail();
  return output;
}
function response(c,locator,wire,status){
  return {schema:'RACE_AI_LOCAL_PRIVATE_WIRE_RESULT_V1',status,scope:'LOCAL_ONLY',locator,claim:claimCopy(c),wire,
    wire_sha256:c.wire_sha256,wire_bytes:c.wire_bytes,chunk_count:c.chunk_sha256.length,retention_status:'RETENTION_UNVERIFIED',
    ...Object.fromEntries(['independent_retention_proof','full_private_payload_retention_verified','source_rights_verified','producer_execution_authenticated','coordinator_authenticated','global_exactly_once_verified','cloned_store_protection_verified','official_prediction','eligible_for_hit_at_8'].map(k=>[k,false]))};
}
async function identity(c){return sha(encoder.encode('RACE_AI_LOCAL_PRIVATE_WIRE_LOCATOR_V1\0'+canonical(c)));}
export async function readLocalPrivateWire(binding,expectedClaim,admitRead){
  let c,locator;
  try{c=claimCopy(expectedClaim);await admit(admitRead,c);locator=await identity(c);}catch{fail();}
  try{
    if(await classify(binding)!=='known')return response(c,locator,null,'UNRESOLVED');
    const wire=await load(binding,c,locator);
    return response(c,locator,wire,wire?'LOCAL_READBACK':'UNRESOLVED');
  }catch{return response(c,locator,null,'UNRESOLVED');}
}
export async function createLocalPrivateWire(binding,expectedClaim,originalWire,admitWrite){
  let c,wire,locator;
  try{
    c=claimCopy(expectedClaim);wire=rawCopy(originalWire,c.wire_bytes);
    if(await sha(wire)!==c.wire_sha256)fail();
    for(let i=0;i<c.chunk_sha256.length;i++)if(await sha(wire.subarray(i*CHUNK,(i+1)*CHUNK))!==c.chunk_sha256[i])fail();
    await admit(admitWrite,c);locator=await identity(c);
  }catch{fail();}
  try{
    const state=await classify(binding);
    if(state==='foreign')fail();
    if(state==='known'){
      const old=await load(binding,c,locator);
      if(old){if(old.some((v,i)=>v!==wire[i]))fail();return response(c,locator,old,'LOCAL_READBACK');}
    }
    const init=state==='known'?[]:INITIALIZE;
    const write=[statement(binding,guard(state!=='known')),...init.map(sql=>statement(binding,sql)),
      statement(binding,`INSERT INTO ${OBJECTS}(locator,claim_json,wire_sha256,wire_bytes,chunk_count) VALUES(?,?,?,?,?) ON CONFLICT(locator) DO NOTHING`,locator,canonical(c),c.wire_sha256,c.wire_bytes,c.chunk_sha256.length)];
    const chunks=[],args=[];
    for(let i=0;i<c.chunk_sha256.length;i++){chunks.push('SELECT ?,?,?,? WHERE changes()=1');args.push(locator,i,c.chunk_sha256[i],wire.slice(i*CHUNK,(i+1)*CHUNK));}
    write.push(statement(binding,`INSERT INTO ${CHUNKS}(locator,ordinal,chunk_sha256,body) ${chunks.join(' UNION ALL ')}`,...args));
    const all=results(await binding.batch(write),write.length),created=all.at(-2).meta.changes;
    admitted(all[0],'admitted');
    if(all.slice(1,-2).some(r=>r.meta.changes!==0||r.results.length)||all.at(-2).results.length||all.at(-1).results.length)fail();
    if(![0,1].includes(created)||all.at(-1).meta.changes!==(created?c.chunk_sha256.length:0))fail();
    const readback=await load(binding,c,locator);
    if(!readback||readback.some((v,i)=>v!==wire[i]))fail();
    return response(c,locator,readback,created?'LOCAL_CREATED':'LOCAL_READBACK');
  }catch{throw Error('LOCAL_PRIVATE_WIRE_WRITE_UNCERTAIN_READ_ONLY');}
}
