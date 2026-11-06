/* Display capability only. The GitHub live feed contains ciphertext only. */
(() => {
  "use strict";
  const LIMIT=8*1024*1024,PLAIN=5*1024*1024,SCHEMA="RACE_AI_SAVED_WEB_VIEW_V1";
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
  const FEED="RACE_AI_SAVED_WEB_VIEW_V3",BASE="https://raw.githubusercontent.com/haji84/RACE-AI/state/boat-saved-view/";
  const hex=v=>typeof v==="string"&&/^[a-f0-9]{64}$/.test(v);
  const canonical=h=>JSON.stringify(Object.fromEntries(Object.keys(h).sort().map(k=>[k,h[k]])));
  function feedHeader(h) {
    if(!fields(h,["forecast_sha256","generation","previous_cipher_sha256","schema","source_content_sha256","view_id"]) || h.schema!==FEED ||
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
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),n=>n.toString(16).padStart(2,"0")).join("");
      if(hash!==ident)fail();
      const envelope=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));
      if(!fields(envelope,["header","nonce","ciphertext"]))fail();
      const h=envelope.header;
      const feed=h?.schema===FEED;
      const updated=h?.schema==="RACE_AI_SAVED_WEB_VIEW_V2";
      if(feed) {if(!live)fail();feedHeader(h);if(h.view_id!==m[1])fail();}
      else if(!fields(h,updated?["schema","source_content_sha256","view_id"]:["schema","source_content_sha256"]) ||
         (updated?h.view_id!==m[1]:h.schema!==SCHEMA||ident!==m[1]) || !hex(h.source_content_sha256))fail();
      const nonce=base64(envelope.nonce,16),cipher=base64(envelope.ciphertext,LIMIT);
      if(nonce.length!==12 || cipher.length<16 || cipher.length>PLAIN+16)fail();
      const aad=new TextEncoder().encode(canonical(h));
      const plain=await crypto.subtle.decrypt({name:"AES-GCM",iv:nonce,additionalData:aad,tagLength:128},key,cipher);
      if(plain.byteLength>PLAIN)fail();
      return {view:JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(plain)),header:h};
    } catch {fail();}
    finally {if(keyBytes)keyBytes.fill(0);}
  }
  async function read(path,fragment) {
    const target=/^\.\/views\/([a-f0-9]{64})\.json$/.exec(path);if(!target)fail();
    const url=new URL(path,location.href);if(url.origin!==location.origin)fail();
    return (await decode(await fetched(url),target[1],fragment)).view;
  }
  async function readLive(fragment,previous) {
    const m=/^#saved=([a-f0-9]{64})\.([A-Za-z0-9_-]{43})$/.exec(fragment);if(!m||!hex(previous.forecastSha))fail();
    const url=new URL(BASE+"latest.json");url.searchParams.set("check",String(Date.now()));
    const latest=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(await fetched(url,4096)));
    if(!fields(latest,["header","cipher_sha256"])||!hex(latest.cipher_sha256))fail();
    const h=latest.header;feedHeader(h);
    if(h.view_id!==m[1]||h.forecast_sha256!==previous.forecastSha||h.generation<previous.generation)fail();
    if(h.generation===previous.generation){if(latest.cipher_sha256!==previous.cipherSha)fail();return null;}
    if(h.generation===previous.generation+1&&h.previous_cipher_sha256!==previous.cipherSha)fail();
    const result=await decode(await fetched(new URL(BASE+"views/"+latest.cipher_sha256+".json")),latest.cipher_sha256,fragment,true);
    if(canonical(result.header)!==canonical(h))fail();
    return {...result,cipherSha:latest.cipher_sha256};
  }
  window.SavedViewCrypto=Object.freeze({read,readLive});
})();
