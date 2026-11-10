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
  const HISTORY="RACE_AI_SAVED_WEB_HISTORY_V5",INDEX="RACE_AI_SAVED_WEB_HISTORY_INDEX_V1",CATALOG="RACE_AI_SAVED_WEB_HISTORY_CATALOG_V1",DAY="RACE_AI_SAVED_WEB_HISTORY_DAY_V1";
  const REPO="https://raw.githubusercontent.com/haji84/RACE-AI/",INDEX_PLAIN=512*1024,INDEX_WIRE=768*1024,CHUNK_PLAIN=8*1024*1024,CHUNK_WIRE=12*1024*1024,HOPS=1200;
  const hex=v=>typeof v==="string"&&/^[a-f0-9]{64}$/.test(v);
  const canonical=h=>JSON.stringify(Object.fromEntries(Object.keys(h).sort().map(k=>[k,h[k]])));
  const snapshots=new Map(),encoder=new TextEncoder();
  const MUTABLE=new Set(["result","result_revisions","result_observations","result_observation_rejections","missing_reasons","live_boat_observation"]);
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
    const values=Object.create(null),byDay=Object.create(null),races=new Set();let count=0,batch=[];
    const flush=async()=>{for(const [identity,content] of await Promise.all(batch)){if(Object.hasOwn(values,identity)&&values[identity]!==content)fail();values[identity]=content;}batch=[];};
    for(const row of view.records) {
      if(!row||typeof row.race_id!=="string"||races.has(row.race_id)||!Array.isArray(row.comparison_predictions||[]))fail();races.add(row.race_id);
      const predictions=[row.prediction,...(row.comparison_predictions||[])].filter(p=>p!=null);
      if(predictions.length>128||(count+=predictions.length)>32768)fail();
      for(const p of predictions) {
        if(!p||typeof p!=="object"||Array.isArray(p))fail();
        const binding="["+JSON.stringify(row.race_id)+","+JSON.stringify(savedIdentity(p,numbers))+"]";
        batch.push(Promise.all([hash(binding),hash(stable(p,numbers))]).then(pair=>{const day=dayValue(row.event_date_jst),entries=byDay[day]||(byDay[day]=Object.create(null));if(Object.hasOwn(entries,pair[0])&&entries[pair[0]]!==pair[1])fail();entries[pair[0]]=pair[1];return pair;}));if(batch.length===128)await flush();
      }
    }
    await flush();return {values,byDay,digest:await hash(JSON.stringify(Object.fromEntries(Object.keys(values).sort().map(k=>[k,values[k]]))))};
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
    if(h?.schema===HISTORY)names.push("history_index_sha256");
    if(!fields(h,names) || ![FEED,APPEND_FEED,HISTORY].includes(h.schema) || h.schema===APPEND_FEED&&!hex(h.forecast_inventory_sha256) || h.schema===HISTORY&&!hex(h.history_index_sha256) ||
       !Number.isSafeInteger(h.generation) || h.generation<1 || h.generation>999999 ||
       ![h.forecast_sha256,h.previous_cipher_sha256,h.source_content_sha256,h.view_id].every(hex))fail();
  }
  function dayValue(value) {
    if(typeof value!=="string"||!/^\d{4}-\d{2}-\d{2}$/.test(value))fail();
    const parsed=new Date(value+"T00:00:00Z");if(!Number.isFinite(parsed.getTime())||parsed.toISOString().slice(0,10)!==value)fail();return value;
  }
  function locator(value) {
    if(!fields(value,["commit","cipher_sha256"])||typeof value.commit!=="string"||!/^[a-f0-9]{40}$/.test(value.commit)||!hex(value.cipher_sha256))fail();return value;
  }
  function descriptor(value) {
    if(!fields(value,["day","chunks","races","forecasts","plain_bytes","view_sha256","forecast_inventory_sha256"]))fail();
    dayValue(value.day);
    if(!Number.isSafeInteger(value.races)||value.races<1||value.races>288||!Number.isSafeInteger(value.forecasts)||value.forecasts<0||value.forecasts>32768||
       !Number.isSafeInteger(value.plain_bytes)||value.plain_bytes<1||value.plain_bytes>PLAIN||!hex(value.view_sha256)||!hex(value.forecast_inventory_sha256)||
       !Array.isArray(value.chunks)||!value.chunks.length||value.chunks.length>64)fail();
    value.chunks.forEach(locator);if(new Set(value.chunks.map(row=>row.cipher_sha256)).size!==value.chunks.length)fail();return value;
  }
  function historyIndex(value) {
    if(!fields(value,["schema","current_month","days","previous_catalog","forecast_base_sha256"])||value.schema!==INDEX||!hex(value.forecast_base_sha256)||
       typeof value.current_month!=="string"||!/^\d{4}-\d{2}$/.test(value.current_month))fail();
    dayValue(value.current_month+"-01");
    if(!value.days||typeof value.days!=="object"||Array.isArray(value.days)||!Object.keys(value.days).length||Object.keys(value.days).length>31)fail();
    for(const [day,entry] of Object.entries(value.days)){dayValue(day);if(day.slice(0,7)!==value.current_month||descriptor(entry).day!==day)fail();}
    if(value.previous_catalog!==null)locator(value.previous_catalog);return value;
  }
  function childHeader(h) {
    const names=["schema","view_id","forecast_sha256"];
    if(h?.schema===CATALOG) {names.push("history_index_sha256");if(!hex(h.history_index_sha256))fail();}
    else {if(h?.schema!==DAY)fail();names.push("day","part","forecast_inventory_sha256");dayValue(h.day);if(!Number.isSafeInteger(h.part)||h.part<0||h.part>=64||!hex(h.forecast_inventory_sha256))fail();}
    if(!fields(h,names)||!hex(h.view_id)||!hex(h.forecast_sha256))fail();
  }
  async function fetched(url,limit=LIMIT) {
    // Initial encrypted views and dated history chunks can exceed 12 MB.
    // Keep the small latest-manifest poll responsive without timing out a slow mobile download.
    const timeout=limit>=CHUNK_WIRE?60000:15000;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
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
      const feed=[FEED,APPEND_FEED,HISTORY].includes(h?.schema),child=[CATALOG,DAY].includes(h?.schema);
      const updated=h?.schema==="RACE_AI_SAVED_WEB_VIEW_V2";
      if(feed) {if(!live)fail();feedHeader(h);if(h.view_id!==m[1])fail();}
      else if(child){if(!live)fail();childHeader(h);if(h.view_id!==m[1])fail();}
      else if(!fields(h,updated?["schema","source_content_sha256","view_id"]:["schema","source_content_sha256"]) ||
         (updated?h.view_id!==m[1]:h.schema!==SCHEMA||ident!==m[1]) || !hex(h.source_content_sha256))fail();
      const nonce=base64(envelope.nonce,16),cipher=base64(envelope.ciphertext,LIMIT);
      const plainLimit=h.schema===DAY?CHUNK_PLAIN:[HISTORY,CATALOG].includes(h.schema)?INDEX_PLAIN:PLAIN;
      if(nonce.length!==12 || cipher.length<16 || cipher.length>plainLimit+16)fail();
      const aad=new TextEncoder().encode(canonical(h));
      const plain=await crypto.subtle.decrypt({name:"AES-GCM",iv:nonce,additionalData:aad,tagLength:128},key,cipher);
      if(plain.byteLength>plainLimit)fail();
      const {view,numbers}=lossless(new TextDecoder("utf-8",{fatal:true}).decode(plain));
      let saved;
      if([HISTORY,CATALOG].includes(h.schema)) {
        historyIndex(view);if(view.forecast_base_sha256!==h.forecast_sha256||await hash(stable(view,numbers))!==h.history_index_sha256)fail();
        saved={history:view,anchor:h.forecast_sha256,digest:h.history_index_sha256,header:h};
      } else if(h.schema===DAY) {
        saved=await inventory(view,numbers);if(view.forecast_base_sha256!==h.forecast_sha256||saved.digest!==h.forecast_inventory_sha256||view.records.some(row=>row.event_date_jst!==h.day))fail();saved.anchor=h.forecast_sha256;
      } else saved=await snapshot(view,numbers,h,feed);
      return {view,header:h,snapshot:saved,numbers,plainBytes:plain.byteLength};
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
  const equal=(left,right)=>JSON.stringify(left)===JSON.stringify(right);
  const includesInventory=(before,after)=>!Object.keys(before).some(key=>after[key]!==before[key]);
  function archiveURL(value) {locator(value);return new URL(REPO+value.commit+"/views/"+value.cipher_sha256+".json");}
  async function catalog(value,fragment,anchor,newerMonth) {
    const result=await decode(await fetched(archiveURL(value),INDEX_WIRE),value.cipher_sha256,fragment,true);
    if(result.header.schema!==CATALOG||result.snapshot.anchor!==anchor||result.view.current_month>=newerMonth)fail();return result.view;
  }
  async function dateDescriptor(index,day,fragment) {
    dayValue(day);let current=historyIndex(index);const seen=new Set();
    for(let step=0;step<=HOPS;step++) {
      if(Object.hasOwn(current.days,day))return current.days[day];
      if(day.slice(0,7)>=current.current_month||current.previous_catalog===null||step===HOPS)fail();
      const marker=canonical(current.previous_catalog);if(seen.has(marker))fail();seen.add(marker);
      current=await catalog(current.previous_catalog,fragment,index.forecast_base_sha256,current.current_month);
    }
    fail();
  }
  async function historyDay(entry,fragment,anchor) {
    descriptor(entry);const records=[],numberMaps=[],rootNumbers=new WeakMap();let full=null,metadata=null,plainBytes=0;
    for(let part=0;part<entry.chunks.length;part++) {
      const value=entry.chunks[part],result=await decode(await fetched(archiveURL(value),CHUNK_WIRE),value.cipher_sha256,fragment,true),h=result.header;
      if(h.schema!==DAY||h.forecast_sha256!==anchor||h.day!==entry.day||h.part!==part)fail();
      const currentMetadata=stable(result.view,result.numbers,null,null,new Set(["records"]));
      if(full===null){full={...result.view,records};metadata=currentMetadata;const tokens=result.numbers.get(result.view);if(tokens)rootNumbers.set(full,tokens);}else if(metadata!==currentMetadata)fail();
      records.push(...result.view.records);numberMaps.push(result.numbers);plainBytes+=result.plainBytes;
      if(plainBytes>PLAIN||records.length>288)fail();
    }
    const numbers={get:object=>{const root=rootNumbers.get(object);if(root)return root;for(const map of numberMaps){const found=map.get(object);if(found)return found;}}};
    // The new records array has no numeric scalar fields; original child objects
    // retain their lossless Python number tokens through the joined weak maps.
    const saved=await inventory(full,numbers);
    if(full.records.length!==entry.races||Object.keys(saved.values).length!==entry.forecasts||plainBytes!==entry.plain_bytes||
       saved.digest!==entry.forecast_inventory_sha256||await hash(stable(full,numbers))!==entry.view_sha256)fail();
    saved.anchor=anchor;return {view:full,snapshot:saved};
  }
  async function historyContinuation(before,current,fragment,loadDay) {
    if(before.anchor!==current.forecast_base_sha256)fail();
    if(!before.history) {
      for(const [day,values] of Object.entries(before.byDay)) {
        const entry=await dateDescriptor(current,day,fragment),result=await loadDay(entry);
        if(!includesInventory(values,result.snapshot.values))fail();
      }
      return;
    }
    const old=before.history;if(current.current_month<old.current_month)fail();
    const indexes=[current],oldIndexes=[old],seen=[new Set(),new Set()];let left=old,right=current;
    async function older(index,side) {
      if(index.previous_catalog===null||seen[side].size>=HOPS)fail();
      const marker=canonical(index.previous_catalog);if(seen[side].has(marker))fail();seen[side].add(marker);
      return catalog(index.previous_catalog,fragment,before.anchor,index.current_month);
    }
    while(!equal(left.previous_catalog,right.previous_catalog)) {
      if(left.previous_catalog===null){right=await older(right,1);indexes.push(right);}
      else if(right.previous_catalog===null)fail();
      else if(left.current_month<right.current_month){right=await older(right,1);indexes.push(right);}
      else if(left.current_month>right.current_month){left=await older(left,0);oldIndexes.push(left);}
      else {left=await older(left,0);oldIndexes.push(left);right=await older(right,1);indexes.push(right);}
    }
    for(const [day,entry] of oldIndexes.flatMap(index=>Object.entries(index.days))) {
      const next=indexes.find(item=>Object.hasOwn(item.days,day))?.days[day];if(!next)fail();
      if(equal(entry,next))continue;
      const prior=await loadDay(entry),after=await loadDay(next);if(!includesInventory(prior.snapshot.values,after.snapshot.values))fail();
    }
  }
  async function readLive(fragment,previous,options={}) {
    if(options.preferredDay!==undefined)dayValue(options.preferredDay);
    const m=/^#saved=([a-f0-9]{64})\.([A-Za-z0-9_-]{43})$/.exec(fragment);if(!m||!hex(previous.forecastSha))fail();
    const before=snapshots.get(previous.cipherSha);if(!before||before.anchor!==previous.forecastSha)fail();
    const url=new URL(BASE+"latest.json");url.searchParams.set("check",String(Date.now()));
    const latest=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(await fetched(url,4096)));
    if(!fields(latest,["header","cipher_sha256"])||!hex(latest.cipher_sha256))fail();
    const h=latest.header;feedHeader(h);
    if(h.view_id!==m[1]||h.forecast_sha256!==previous.forecastSha||h.generation<previous.generation)fail();
    if(h.generation===previous.generation){
      if(latest.cipher_sha256!==previous.cipherSha||h.schema===APPEND_FEED&&h.forecast_inventory_sha256!==before.digest||h.schema===HISTORY&&h.history_index_sha256!==before.digest)fail();
      if(before.history&&options.preferredDay!==options.day&&Object.hasOwn(before.history.days,options.preferredDay))return readDay(fragment,previous,options.preferredDay);
      return null;
    }
    if(h.generation===previous.generation+1&&h.previous_cipher_sha256!==previous.cipherSha)fail();
    const result=await decode(await fetched(new URL(BASE+"views/"+latest.cipher_sha256+".json"),h.schema===HISTORY?INDEX_WIRE:LIMIT),latest.cipher_sha256,fragment,true);
    if(canonical(result.header)!==canonical(h))fail();
    if(h.schema===HISTORY) {
      // A saved link can outlive the latest saved race day. Do not request a
       // future date that has no encrypted day descriptor; retain older history.
       const latestDay=Object.keys(result.view.days).sort().at(-1);
       const requestedDay=options.preferredDay??options.day??latestDay;
       const day=requestedDay>latestDay?latestDay:requestedDay;
      // Retain at most the selected date while comparing other dates in turn.
      // A transition must not rebuild the whole historical view in memory.
      let selectedMarker=null,selectedValue=null;
      const loadDay=async entry=>{const marker=JSON.stringify(entry);if(marker===selectedMarker)return selectedValue;const value=await historyDay(entry,fragment,before.anchor);if(entry.day===day){selectedMarker=marker;selectedValue=value;}return value;};
      await historyContinuation(before,result.view,fragment,loadDay);
      const entry=await dateDescriptor(result.view,day,fragment),selected=await loadDay(entry);
      remember(latest.cipher_sha256,result.snapshot,previous.cipherSha);
      return {view:selected.view,header:h,cipherSha:latest.cipher_sha256,history:{day,currentMonth:result.view.current_month}};
    }
    if(before.history)fail();
    if(result.snapshot.anchor!==before.anchor||Object.keys(before.values).some(k=>result.snapshot.values[k]!==before.values[k]))fail();
    remember(latest.cipher_sha256,result.snapshot,previous.cipherSha);
    return {view:result.view,header:result.header,cipherSha:latest.cipher_sha256};
  }
  async function readDay(fragment,previous,day) {
    const before=snapshots.get(previous.cipherSha);if(!before?.history||before.anchor!==previous.forecastSha||before.header.generation!==previous.generation)fail();
    const entry=await dateDescriptor(before.history,day,fragment),selected=await historyDay(entry,fragment,before.anchor);
    return {view:selected.view,header:before.header,cipherSha:previous.cipherSha,history:{day,currentMonth:before.history.current_month}};
  }
  window.SavedViewCrypto=Object.freeze({read,readLive,readDay});
})();
