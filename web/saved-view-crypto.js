/* Display capability only. The GitHub live feed contains ciphertext only. */
(() => {
  "use strict";
  const LIMIT=90*1024*1024,PLAIN=64*1024*1024,SCHEMA="RACE_AI_SAVED_WEB_VIEW_V1";
  const fail=()=>{throw new Error("PRIVATE_VIEW_UNAVAILABLE");};
  function base64(value,max) {
    if(typeof value!=="string" || !value.length || value.length>max || value.length%4 || /[^A-Za-z0-9+/=]/.test(value)) fail();
    let binary;try{binary=atob(value);}catch{fail();}
    if(btoa(binary)!==value)fail();
    return Uint8Array.from(binary,c=>c.charCodeAt(0));
  }
  function fields(value,names) {
    return value && typeof value==="object" && !Array.isArray(value) && Object.keys(value).length===names.length && names.every(k=>Object.hasOwn(value,k));
  }
  async function bounded(response,limit=LIMIT) {
    const length=response.headers.get("content-length");
    if(length!==null && (!/^[0-9]+$/.test(length) || Number(length)>limit))fail();
    if(!response.body)fail();
    const reader=response.body.getReader(),parts=[];let size=0;
    try {
      for(;;){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>limit)fail();parts.push(value);}
    } catch {await reader.cancel().catch(()=>{});fail();}
    if(!size)fail();
    const bytes=new Uint8Array(size);let offset=0;for(const p of parts){bytes.set(p,offset);offset+=p.length;}return bytes;
  }
  const FEED="RACE_AI_SAVED_WEB_VIEW_V3",APPEND_FEED="RACE_AI_SAVED_WEB_VIEW_V4",BASE="https://raw.githubusercontent.com/haji84/RACE-AI/state/boat-saved-view/";
  const hex=v=>typeof v==="string"&&/^[a-f0-9]{64}$/.test(v);
  const canonical=h=>JSON.stringify(Object.fromEntries(Object.keys(h).sort().map(k=>[k,h[k]])));
  const snapshots=new Map(),encoder=new TextEncoder();
  const MUTABLE=new Set(["result","result_revisions","result_observations","result_observation_rejections","missing_reasons"]);
  const IDENTITY=["stage","native_stage","model_id","model_version","variant","source_code_commit","as_of","cutoff_at",
    "input_sha256","source_sha256","source_captured_at","source_provenance","artifact_id","original_json_sha256",
    "physical_receipt_sha256","pair_sha256","persisted_at","server_saved_at","training_sha256","training_artifact_id","training_receipt_digest"];
  const OMIT_REFERENCE=new Set(["prediction_sha256","output_sha256","model_sha256"]);
  const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",typeof value==="string"?encoder.encode(value):value)),n=>n.toString(16).padStart(2,"0")).join("");
  // Python's canonical wire keeps 1.0, -0.0 and exponent spellings. Record those
  // tokens without JSON.parse's recent reviver context API (absent on Safari).
  function lossless(source) {
    const view=JSON.parse(source),numbers=new WeakMap();let at=0;
    const space=()=>{while(/[\x20\t\r\n]/.test(source[at]||"\0"))at++;};
    function string() {
      const begin=at++;while(at<source.length){const c=source[at++];if(c==='"')return source.slice(begin,at);if(c==="\\")at++;}fail();
    }
    function scan(value,parent,key,depth) {
      if(depth>64)fail();space();const c=source[at];
      if(c==="{") {
        if(!value||typeof value!=="object"||Array.isArray(value))fail();at++;space();const seen=new Set();
        if(source[at]!=="}")for(;;){if(source[at]!=='"')fail();const name=JSON.parse(string());if(seen.has(name)||!Object.hasOwn(value,name))fail();seen.add(name);space();if(source[at++]!==":")fail();scan(value[name],value,name,depth+1);space();if(source[at]!==",")break;at++;space();}
        if(source[at++]!=="}"||seen.size!==Object.keys(value).length)fail();
      } else if(c==="[") {
        if(!Array.isArray(value))fail();at++;space();let i=0;
        if(source[at]!=="]")for(;;){scan(value[i],value,String(i),depth+1);i++;space();if(source[at]!==",")break;at++;space();}
        if(source[at++]!=="]"||i!==value.length)fail();
      } else if(c==='"') {if(typeof value!=="string")fail();string();}
      else if(c==="-"||c>="0"&&c<="9") {
        const begin=at;while(at<source.length&&/[0-9eE+.\-]/.test(source[at]))at++;const token=source.slice(begin,at);
        if(typeof value!=="number"||!Number.isFinite(value)||!Object.is(Number(token),value))fail();
        if(parent){let fields=numbers.get(parent);if(!fields){fields=new Map();numbers.set(parent,fields);}fields.set(String(key),token);}
      } else {const literal=value===null?"null":value===true?"true":value===false?"false":null;if(!literal||source.slice(at,at+literal.length)!==literal)fail();at+=literal.length;}
    }
    scan(view,null,null,0);space();if(at!==source.length)fail();return {view,numbers};
  }
  // Unicode scalar ordering matches Python sort_keys, including supplementary
  // characters. Saved source values are serialized with their original tokens.
  function compare(a,b) {
    let i=0,j=0;while(i<a.length&&j<b.length){const x=a.codePointAt(i),y=b.codePointAt(j);if(x!==y)return x-y;i+=x>65535?2:1;j+=y>65535?2:1;}return a.length-b.length;
  }
  function stable(value,numbers,parent=null,key=null,omit=null) {
    if(value===null)return "null";
    if(typeof value==="number"){const token=parent&&numbers.get(parent)?.get(String(key));if(!token||!Number.isFinite(value))fail();return token;}
    if(typeof value==="string"||typeof value==="boolean")return JSON.stringify(value);
    if(Array.isArray(value))return "["+value.map((v,i)=>stable(v,numbers,value,String(i))).join(",")+"]";
    if(value&&typeof value==="object")return "{"+Object.keys(value).filter(k=>!omit?.has(k)).sort(compare).map(k=>JSON.stringify(k)+":"+stable(value[k],numbers,value,k)).join(",")+"}";
    fail();
  }
  function savedIdentity(p,numbers) {
    const ref=p.native_source_reference;
    return "["+IDENTITY.map(k=>p[k]==null?"null":stable(p[k],numbers,p,k)).concat(ref==null?"null":stable(ref,numbers,p,"native_source_reference",ref&&typeof ref==="object"&&!Array.isArray(ref)?OMIT_REFERENCE:null)).join(",")+"]";
  }
  async function inventory(view,numbers) {
    if(view?.schema!=="RACE_AI_PRIVATE_CYCLE_VIEW_V1"||!Array.isArray(view.records)||!view.records.length||view.records.length>5000)fail();
    const values=Object.create(null),races=new Set();let count=0,batch=[];
    const flush=async()=>{for(const [identity,content] of await Promise.all(batch)){if(Object.hasOwn(values,identity)&&values[identity]!==content)fail();values[identity]=content;}batch=[];};
    for(const row of view.records) {
      if(!row||typeof row.race_id!=="string"||races.has(row.race_id)||!Array.isArray(row.comparison_predictions||[]))fail();races.add(row.race_id);
      const predictions=[row.prediction,...(row.comparison_predictions||[])].filter(p=>p!=null);
      if(predictions.length>128||(count+=predictions.length)>32768)fail();
      for(const p of predictions) {
        if(!p||typeof p!=="object"||Array.isArray(p))fail();
        const binding="["+JSON.stringify(row.race_id)+","+JSON.stringify(savedIdentity(p,numbers))+"]";
        batch.push(Promise.all([hash(binding),hash(stable(p,numbers))]));if(batch.length===128)await flush();
      }
    }
    await flush();return {values,digest:await hash(JSON.stringify(Object.fromEntries(Object.keys(values).sort().map(k=>[k,values[k]]))))};
  }
  async function snapshot(view,numbers,header,feed) {
    const result=await inventory(view,numbers);
    if(header.schema===APPEND_FEED) {
      if(view.forecast_base_sha256!==header.forecast_sha256||result.digest!==header.forecast_inventory_sha256)fail();
      result.anchor=header.forecast_sha256;
    } else {
      const original=await hash("["+view.records.map(row=>stable(row,numbers,null,null,MUTABLE)).join(",")+"]");
      if(feed&&original!==header.forecast_sha256)fail();
      result.anchor=view.forecast_base_sha256??original;if(!hex(result.anchor))fail();
    }
    return result;
  }
  function remember(ident,value,previous=null) {
    const retained=previous&&snapshots.get(previous);snapshots.clear();if(retained)snapshots.set(previous,retained);snapshots.set(ident,value);
  }
  function feedHeader(h) {
    const names=["forecast_sha256","generation","previous_cipher_sha256","schema","source_content_sha256","view_id"];
    if(h?.schema===APPEND_FEED)names.push("forecast_inventory_sha256");
    if(!fields(h,names) || ![FEED,APPEND_FEED].includes(h.schema) || h.schema===APPEND_FEED&&!hex(h.forecast_inventory_sha256) ||
       !Number.isSafeInteger(h.generation) || h.generation<1 || h.generation>999999 ||
       ![h.forecast_sha256,h.previous_cipher_sha256,h.source_content_sha256,h.view_id].every(hex))fail();
  }
  async function fetched(url,limit=LIMIT) {
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await fetch(url,{credentials:"omit",cache:"no-store",redirect:"error",referrerPolicy:"no-referrer",signal:controller.signal});
      if(!response.ok || response.url!==url.href)fail();return await bounded(response,limit);
    } finally {clearTimeout(timer);}
  }
  async function decode(bytes,ident,fragment,live=false) {
    let keyBytes;
    try {
      if(typeof fragment!=="string" || fragment.length!==115)fail();
      const m=/^#saved=([a-f0-9]{64})\.([A-Za-z0-9_-]{43})$/.exec(fragment);if(!m)fail();
      if(!hex(ident))fail();
      keyBytes=base64(m[2].replace(/-/g,"+").replace(/_/g,"/")+"=",44);if(keyBytes.length!==32)fail();
      const key=await crypto.subtle.importKey("raw",keyBytes,"AES-GCM",false,["decrypt"]);keyBytes.fill(0);
      if(await hash(bytes)!==ident)fail();
      const envelope=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));
      if(!fields(envelope,["header","nonce","ciphertext"]))fail();
      const h=envelope.header;
      const feed=[FEED,APPEND_FEED].includes(h?.schema);
      const updated=h?.schema==="RACE_AI_SAVED_WEB_VIEW_V2";
      if(feed) {if(!live)fail();feedHeader(h);if(h.view_id!==m[1])fail();}
      else if(!fields(h,updated?["schema","source_content_sha256","view_id"]:["schema","source_content_sha256"]) ||
         (updated?h.view_id!==m[1]:h.schema!==SCHEMA||ident!==m[1]) || !hex(h.source_content_sha256))fail();
      const nonce=base64(envelope.nonce,16),cipher=base64(envelope.ciphertext,LIMIT);
      if(nonce.length!==12 || cipher.length<16 || cipher.length>PLAIN+16)fail();
      const aad=new TextEncoder().encode(canonical(h));
      const plain=await crypto.subtle.decrypt({name:"AES-GCM",iv:nonce,additionalData:aad,tagLength:128},key,cipher);
      if(plain.byteLength>PLAIN)fail();
      const {view,numbers}=lossless(new TextDecoder("utf-8",{fatal:true}).decode(plain));
      return {view,header:h,snapshot:await snapshot(view,numbers,h,feed)};
    } catch {fail();}
    finally {if(keyBytes)keyBytes.fill(0);}
  }
  async function read(path,fragment) {
    const target=/^\.\/views\/([a-f0-9]{64})\.json$/.exec(path);if(!target)fail();
    const url=new URL(path,location.href);if(url.origin!==location.origin)fail();
    const result=await decode(await fetched(url),target[1],fragment);
    const expected=document.querySelector('meta[name="race-ai-saved-view-forecast-sha"]')?.content;
    if(expected&&result.snapshot.anchor!==expected)fail();remember(target[1],result.snapshot);return result.view;
  }
  async function readLive(fragment,previous) {
    const m=/^#saved=([a-f0-9]{64})\.([A-Za-z0-9_-]{43})$/.exec(fragment);if(!m||!hex(previous.forecastSha))fail();
    const before=snapshots.get(previous.cipherSha);if(!before||before.anchor!==previous.forecastSha)fail();
    const url=new URL(BASE+"latest.json");url.searchParams.set("check",String(Date.now()));
    const latest=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(await fetched(url,4096)));
    if(!fields(latest,["header","cipher_sha256"])||!hex(latest.cipher_sha256))fail();
    const h=latest.header;feedHeader(h);
    if(h.view_id!==m[1]||h.forecast_sha256!==previous.forecastSha||h.generation<previous.generation)fail();
    if(h.generation===previous.generation){if(latest.cipher_sha256!==previous.cipherSha||h.schema===APPEND_FEED&&h.forecast_inventory_sha256!==before.digest)fail();return null;}
    if(h.generation===previous.generation+1&&h.previous_cipher_sha256!==previous.cipherSha)fail();
    const result=await decode(await fetched(new URL(BASE+"views/"+latest.cipher_sha256+".json")),latest.cipher_sha256,fragment,true);
    if(canonical(result.header)!==canonical(h))fail();
    if(result.snapshot.anchor!==before.anchor||Object.keys(before.values).some(k=>result.snapshot.values[k]!==before.values[k]))fail();
    remember(latest.cipher_sha256,result.snapshot,previous.cipherSha);
    return {view:result.view,header:result.header,cipherSha:latest.cipher_sha256};
  }
  window.SavedViewCrypto=Object.freeze({read,readLive});
})();
