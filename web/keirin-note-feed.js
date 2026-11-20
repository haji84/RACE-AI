/* Independent display capability. Its private key never enters a request URL. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./keirin-note-model.js'));
  else root.RaceKeirinNoteFeed=factory(root.RaceKeirinNote);
})(typeof window==='object'?window:globalThis,function(M){
  'use strict';
  const BASE='https://raw.githubusercontent.com/haji84/RACE-AI/state/keirin-note-view/';
  const INFO='RACE_AI_KEIRIN_NOTE_FEED_V1:',encoder=new TextEncoder(),MAX=90*1024*1024;
  const need=v=>{if(!v)throw Error('KEIRIN_NOTE_FEED_INVALID');};
  const cryptoApi=()=>globalThis.crypto?.subtle?globalThis.crypto:require('node:crypto').webcrypto;
  const hex=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  const record=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const sameKeys=(v,keys)=>record(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
  const encode=raw=>btoa(String.fromCharCode(...new Uint8Array(raw))).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
  function decode(value){need(typeof value==='string'&&/^[A-Za-z0-9_-]+$/.test(value));const raw=Uint8Array.from(atob(value.replaceAll('-','+').replaceAll('_','/')+'='.repeat((-value.length%4+4)%4)),c=>c.charCodeAt(0));need(encode(raw)===value);return raw;}
  const ids=v=>Array.isArray(v)&&new Set(v).size===v.length&&v.every(n=>typeof n==='string'&&/^20[0-9]{10}$/.test(n));
  function checkIndex(index,recipient){
    const fields='schema,repository,recipient_id,entries,provider_denied,covered_race_ids,priority_window_race_ids';
    need((sameKeys(index,fields)||sameKeys(index,fields+',result_checks'))&&index.schema==='RACE_AI_KEIRIN_NOTE_FEED_V1'&&index.repository==='haji84/RACE-AI'&&index.recipient_id===recipient&&typeof index.provider_denied==='boolean'&&Array.isArray(index.entries)&&ids(index.covered_race_ids)&&ids(index.priority_window_race_ids));
    const hashes=new Set(),covered=new Set(),priority=new Set();
    for(const e of index.entries){
      need(sameKeys(e,'cipher_sha256,source_content_sha256,ephemeral_public_key,salt,created_at,days,kind,captured_race_ids,priority_window_race_ids')&&hex(e.cipher_sha256)&&hex(e.source_content_sha256)&&!hashes.has(e.cipher_sha256)&&['import','research','archive','results'].includes(e.kind));
      need(decode(e.ephemeral_public_key).length===65&&decode(e.salt).length===32&&Array.isArray(e.days)&&e.days.length&&new Set(e.days).size===e.days.length&&e.days.every(M.day)&&Number.isFinite(Date.parse(e.created_at))&&ids(e.captured_race_ids)&&ids(e.priority_window_race_ids));
      need(e.captured_race_ids.every(id=>e.days.some(d=>id.startsWith(d.replaceAll('-',''))))&&(e.kind!=='results'||e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0));
      need(e.priority_window_race_ids.every(id=>e.captured_race_ids.includes(id)));hashes.add(e.cipher_sha256);e.captured_race_ids.forEach(id=>covered.add(id));e.priority_window_race_ids.forEach(id=>priority.add(id));
    }
    need(index.covered_race_ids.length===covered.size&&index.covered_race_ids.every(id=>covered.has(id))&&index.priority_window_race_ids.length===priority.size&&index.priority_window_race_ids.every(id=>priority.has(id)));
    if(Object.hasOwn(index,'result_checks')){
      need(record(index.result_checks));
      for(const [id,check] of Object.entries(index.result_checks))need(ids([id])&&M.day(id.slice(0,4)+'-'+id.slice(4,6)+'-'+id.slice(6,8))&&index.entries.some(e=>e.days.some(d=>id.startsWith(d.replaceAll('-',''))))&&sameKeys(check,'checked_at,digest,status')&&M.utc(check.checked_at)&&(check.digest===null||hex(check.digest))&&['MATCHED','HOLD','PENDING'].includes(check.status)&&(check.status!=='MATCHED'||check.digest!==null));
    }
    return index;
  }
  async function capability(value){
    need(typeof value==='string'&&value.length>=150&&value.length<=400);
    const c=cryptoApi(),privateKey=await c.subtle.importKey('pkcs8',decode(value),{name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
    const jwk=await c.subtle.exportKey('jwk',privateKey),raw=new Uint8Array(65);raw[0]=4;raw.set(decode(jwk.x),1);raw.set(decode(jwk.y),33);
    return {privateKey,recipient:await M.digest(raw)};
  }
  async function openEntry(bytes,e,cap){
    const c=cryptoApi(),ephemeral=await c.subtle.importKey('raw',decode(e.ephemeral_public_key),{name:'ECDH',namedCurve:'P-256'},false,[]);
    const shared=await c.subtle.deriveBits({name:'ECDH',public:ephemeral},cap.privateKey,256),material=await c.subtle.importKey('raw',shared,'HKDF',false,['deriveBits']);
    const key=await c.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt:decode(e.salt),info:encoder.encode(INFO+cap.recipient)},material,256);
    need(await M.digest(bytes)===e.cipher_sha256);const h=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)).header;need(h?.source_content_sha256===e.source_content_sha256);
    const data=await M.openCipher(bytes,{cipherSha:e.cipher_sha256,key:encode(key)});
    need(data.dates.slice().sort().join(',')===e.days.slice().sort().join(','));
    if(e.kind==='results')need(e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&[...data.files.keys()].every(path=>/^data\/\d{4}-\d{2}-\d{2}\/research_results\.json$/.test(path))&&data.dates.every(date=>M.rows(data,date).length===0));
    return data;
  }
  function merge(parts,{resultChecks={}}={}){
    need(Array.isArray(parts)&&parts.length>0);
    const days=new Map(),files=new Map(),fileShas=new Map(),results=new Map(),refreshHolds=[];let importedAt=parts[0].importedAt;
    const roster=row=>row.riders.map(p=>p.number+':'+p.name.replace(/\s/g,'')).sort().join('|');
    for(const part of parts){
      for(const [path,value] of part.files)files.set(path,value);
      for(const [path,value] of part.fileShas||[])fileShas.set(path,value);
      importedAt=part.importedAt;
      for(const date of part.dates){
        const byId=new Map((days.get(date)||[]).map(row=>[row.id,row]));
        for(const row of M.rows(part,date)){
          const prior=byId.get(row.id);if(!prior){byId.set(row.id,{...row,referenceHistory:[...(row.referenceHistory||[])],resultHistory:[],latestResult:null});continue;}
          // Immutable snapshots keep every version. An input refresh does not
          // replace the authored originals imported from the owner's Site.
          const authored=(prior.original.tickets||[]).length>0;
          const predicted=authored||Object.keys(prior.reference||{}).length>0||(prior.two.tickets||[]).length>0||Object.keys(prior.flexible?.markets||{}).length>0;
          const sameCutoff=prior.cutoff===row.cutoff||prior.cutoff&&row.cutoff&&Date.parse(prior.cutoff)===Date.parse(row.cutoff);
          if(predicted&&(roster(prior)!==roster(row)||!sameCutoff)){
            refreshHolds.push({raceId:row.id,reason:'HOLD_RESEARCH_REFRESH_SOURCE_CONTEXT_CHANGED'});continue;
          }
          const combined={...prior,bindings:{...prior.bindings}};
          for(const name of ['original','two','flexible','rollover','settlement']){
            const old=prior[name],fresh=row[name];
            if((!old||record(old)&&!Object.keys(old).length)&&fresh){combined[name]=fresh;if(row.bindings?.[name])combined.bindings[name]=row.bindings[name];}
          }
          combined.referenceHistory=[...(prior.referenceHistory||[])];
          if(Object.keys(row.reference||{}).length){
            if(Object.keys(prior.reference||{}).length&&JSON.stringify(prior.bindings?.reference)!==JSON.stringify(row.bindings?.reference))combined.referenceHistory.push({reference:prior.reference,envelope:prior.referenceEnvelope,binding:prior.bindings?.reference||null});
            combined.reference=row.reference;combined.referenceEnvelope=row.referenceEnvelope;combined.bindings.reference=row.bindings?.reference||null;
          }
          byId.set(row.id,combined);
        }
        days.set(date,[...byId.values()].sort((a,b)=>(Date.parse(a.cutoff)||Infinity)-(Date.parse(b.cutoff)||Infinity)||a.id.localeCompare(b.id)));
      }
      for(const [id,observations] of part.results||[]){
        const history=results.get(id)||[];
        for(const saved of observations){
          const o=saved.observation,last=history.at(-1)?.observation;
          need(last?o.previous_observation_sha256===last.observation_sha256&&o.observation_sha256!==last.observation_sha256&&Date.parse(o.captured_at)>=Date.parse(last.captured_at):o.previous_observation_sha256===null);
          history.push(saved);
        }
        results.set(id,history);
      }
    }
    for(const [date,list] of days)days.set(date,list.map(row=>{
      const history=results.get(row.id)||[];
      need(history.every(saved=>saved.observation.winning_triple===null||!row.cars.size||saved.observation.winning_triple.every(n=>row.cars.has(n))));
      return {...row,resultHistory:[...history],latestResult:history.at(-1)||null};
    }));
    const checks=new Map(Object.entries(resultChecks));
    for(const [id,check] of checks){
      const latest=results.get(id)?.at(-1)?.observation;
      if(check.digest!==null)need(latest&&latest.observation_sha256===check.digest&&Date.parse(check.checked_at)>=Date.parse(latest.captured_at)&&check.status===(latest.state==='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL'?'MATCHED':latest.state.startsWith('PENDING_')?'PENDING':'HOLD'));
      else need(!latest&&check.status!=='MATCHED');
    }
    return {schema:M.SCHEMA,dates:[...days.keys()].sort(),days,files,fileShas,results,resultChecks:checks,cipherSha:null,formal:false,importedAt,sourceCommit:parts[0].sourceCommit,refreshHolds};
  }
  async function bytes(response,signal){
    need(response.ok);const length=response.headers?.get('content-length');need(length==null||/^\d+$/.test(length)&&Number(length)<=MAX);
    const reader=response.body?.getReader();need(reader);const parts=[];let size=0;
    try{for(;;){need(!signal?.aborted);const {value,done}=await reader.read();if(done)break;size+=value.byteLength;need(size<=MAX);parts.push(value);}}catch(e){await reader.cancel().catch(()=>{});throw e;}
    const result=new Uint8Array(size);let offset=0;for(const p of parts){result.set(p,offset);offset+=p.length;}return result;
  }
  async function open(key,{signal,onStatus,fetcher=globalThis.fetch}={}){
    const cap=await capability(key),options={credentials:'omit',referrerPolicy:'no-referrer',cache:'no-store',signal};
    const index=checkIndex(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(await bytes(await fetcher(BASE+'index.json',options),signal))),cap.recipient);
    const parts=[],display=index.entries.filter(e=>e.kind!=='archive');
    for(const entry of display){
      need(!signal?.aborted);onStatus?.('暗号化した保存履歴を確認しています。 '+(parts.length+1)+' / '+display.length);
      const wire=await bytes(await fetcher(BASE+'views/'+entry.cipher_sha256+'.json',options),signal);parts.push(await openEntry(wire,entry,cap));
    }
    need(!signal?.aborted);const data=merge(parts,{resultChecks:index.result_checks||{}});data.feed={entries:index.entries.length,providerDenied:index.provider_denied};return data;
  }
  return {open,openEntry,capability,checkIndex,merge,BASE};
});
