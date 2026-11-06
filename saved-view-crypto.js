/* View-only capability: no root key, persistence, POST or external fetch. */
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
  async function bounded(response) {
    const length=response.headers.get("content-length");
    if(length!==null && (!/^[0-9]+$/.test(length) || Number(length)>LIMIT))fail();
    if(!response.body)fail();
    const reader=response.body.getReader(),parts=[];let size=0;
    try {
      for(;;){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>LIMIT)fail();parts.push(value);}
    } catch {await reader.cancel().catch(()=>{});fail();}
    if(!size)fail();
    const bytes=new Uint8Array(size);let offset=0;for(const p of parts){bytes.set(p,offset);offset+=p.length;}return bytes;
  }
  async function read(path,fragment) {
    let keyBytes;
    try {
      if(typeof fragment!=="string" || fragment.length!==115)fail();
      const m=/^#saved=([a-f0-9]{64})\.([A-Za-z0-9_-]{43})$/.exec(fragment);if(!m)fail();
      if(path!=="./views/"+m[1]+".json")fail();
      const url=new URL(path,location.href);if(url.origin!==location.origin)fail();
      keyBytes=base64(m[2].replace(/-/g,"+").replace(/_/g,"/")+"=",44);if(keyBytes.length!==32)fail();
      const key=await crypto.subtle.importKey("raw",keyBytes,"AES-GCM",false,["decrypt"]);keyBytes.fill(0);
      const response=await fetch(url,{credentials:"omit",cache:"no-store",redirect:"error",referrerPolicy:"no-referrer"});
      if(!response.ok || response.url!==url.href)fail();
      const bytes=await bounded(response),hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),n=>n.toString(16).padStart(2,"0")).join("");
      if(hash!==m[1])fail();
      const envelope=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));
      if(!fields(envelope,["header","nonce","ciphertext"]))fail();
      const h=envelope.header;
      if(!fields(h,["schema","source_content_sha256"]) || h.schema!==SCHEMA || typeof h.source_content_sha256!=="string" || !/^[a-f0-9]{64}$/.test(h.source_content_sha256))fail();
      const nonce=base64(envelope.nonce,16),cipher=base64(envelope.ciphertext,LIMIT);
      if(nonce.length!==12 || cipher.length<16 || cipher.length>PLAIN+16)fail();
      const aad=new TextEncoder().encode(JSON.stringify({schema:h.schema,source_content_sha256:h.source_content_sha256}));
      const plain=await crypto.subtle.decrypt({name:"AES-GCM",iv:nonce,additionalData:aad,tagLength:128},key,cipher);
      if(plain.byteLength>PLAIN)fail();
      return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(plain));
    } catch {fail();}
    finally {if(keyBytes)keyBytes.fill(0);}
  }
  window.SavedViewCrypto=Object.freeze({read});
})();
