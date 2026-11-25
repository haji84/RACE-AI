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
      const keys='cipher_sha256,source_content_sha256,ephemeral_public_key,salt,created_at,days,kind,captured_race_ids,priority_window_race_ids'+(e?.kind==='result'?',result_revisions':e?.kind==='canary-original'?',original_revisions':e?.kind==='nationwide'?',day_revision,original_revisions,registered_race_ids':'');
      need(sameKeys(e,keys)&&hex(e.cipher_sha256)&&hex(e.source_content_sha256)&&!hashes.has(e.cipher_sha256)&&['import','research','archive','result','results','canary-original','nationwide'].includes(e.kind));
      need(decode(e.ephemeral_public_key).length===65&&decode(e.salt).length===32&&Array.isArray(e.days)&&e.days.length&&new Set(e.days).size===e.days.length&&e.days.every(M.day)&&Number.isFinite(Date.parse(e.created_at))&&ids(e.captured_race_ids)&&ids(e.priority_window_race_ids));
      need(e.captured_race_ids.every(id=>e.days.some(d=>id.startsWith(d.replaceAll('-',''))))&&(e.kind!=='results'||e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0));
      need(e.priority_window_race_ids.every(id=>e.captured_race_ids.includes(id)));hashes.add(e.cipher_sha256);e.captured_race_ids.forEach(id=>covered.add(id));e.priority_window_race_ids.forEach(id=>priority.add(id));
      if(e.kind==='result')need(e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&record(e.result_revisions)&&Object.keys(e.result_revisions).length>0&&Object.keys(e.result_revisions).length<=300&&ids(Object.keys(e.result_revisions))&&Object.values(e.result_revisions).every(hex));
      if(e.kind==='canary-original')need(e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&record(e.original_revisions)&&Object.keys(e.original_revisions).length>0&&Object.keys(e.original_revisions).length<=300&&ids(Object.keys(e.original_revisions))&&Object.values(e.original_revisions).every(hex));
      if(e.kind==='nationwide'){
        need(e.days.length===1&&e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&hex(e.day_revision)&&ids(e.registered_race_ids)&&e.registered_race_ids.length<=600&&e.registered_race_ids.every(id=>id.startsWith(e.days[0].replaceAll('-',''))&&Number(id.slice(-2))>=1&&Number(id.slice(-2))<=12));
        need(record(e.original_revisions)&&Object.keys(e.original_revisions).every(id=>e.registered_race_ids.includes(id))&&Object.values(e.original_revisions).every(v=>sameKeys(v,'baseline,conditioned')&&hex(v.baseline)&&(v.conditioned===null||hex(v.conditioned))));
      }
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
  async function openEntry(bytes,e,cap,{onSource}={}){
    const c=cryptoApi(),ephemeral=await c.subtle.importKey('raw',decode(e.ephemeral_public_key),{name:'ECDH',namedCurve:'P-256'},false,[]);
    const shared=await c.subtle.deriveBits({name:'ECDH',public:ephemeral},cap.privateKey,256),material=await c.subtle.importKey('raw',shared,'HKDF',false,['deriveBits']);
    const key=await c.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt:decode(e.salt),info:encoder.encode(INFO+cap.recipient)},material,256);
    need(await M.digest(bytes)===e.cipher_sha256);const h=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)).header;need(h?.source_content_sha256===e.source_content_sha256);
    const data=await M.openCipher(bytes,{cipherSha:e.cipher_sha256,key:encode(key),onSource});
    need(data.dates.slice().sort().join(',')===e.days.slice().sort().join(','));
    if(e.kind==='results')need(e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&[...data.files.keys()].every(path=>/^data\/\d{4}-\d{2}-\d{2}\/research_results\.json$/.test(path))&&data.dates.every(date=>M.rows(data,date).length===0));
    if(e.kind==='result'){
      need([...data.files.keys()].every(path=>/^data\/\d{4}-\d{2}-\d{2}\/result_updates\.json$/.test(path))&&data.resultUpdates.size===data.dates.length);
      const revisions=Object.fromEntries([...data.resultUpdates.values()].flatMap(rows=>[...rows.values()].map(row=>[row.race_id,row.revision])));
      need(Object.keys(revisions).sort().join(',')===Object.keys(e.result_revisions).sort().join(',')&&Object.entries(revisions).every(([id,revision])=>e.result_revisions[id]===revision));
    }
    if(e.kind==='canary-original'){
      need([...data.files.keys()].every(path=>/^data\/\d{4}-\d{2}-\d{2}\/frozen_forecasts\.json$/.test(path))&&data.frozenForecasts.size===data.dates.length);
      const revisions=Object.fromEntries([...data.frozenForecasts.values()].flatMap(rows=>[...rows.values()].map(row=>[row.race_id,row.revision])));
      need(Object.keys(revisions).sort().join(',')===Object.keys(e.original_revisions).sort().join(',')&&Object.entries(revisions).every(([id,revision])=>e.original_revisions[id]===revision));
    }
    if(e.kind==='nationwide'){
      need(data.dates.length===1&&data.nationwide.size===1&&[...data.files.keys()].join(',')==='data/'+data.dates[0]+'/nationwide_forecasts.json');
      const doc=data.nationwide.get(data.dates[0]),revisions=Object.fromEntries(doc.races.filter(row=>row.original_identity!==null).map(row=>[row.race_id,row.original_identity]));
      need(doc.revision===e.day_revision&&doc.races.map(r=>r.race_id).sort().join(',')===e.registered_race_ids.slice().sort().join(',')&&Object.keys(revisions).sort().join(',')===Object.keys(e.original_revisions).sort().join(','));
      need(Object.entries(revisions).every(([id,v])=>v.baseline===e.original_revisions[id].baseline&&v.conditioned===e.original_revisions[id].conditioned));
    }
    return data;
  }
  function merge(parts,{resultChecks={}}={}){
    need(Array.isArray(parts)&&parts.length>0);
    const days=new Map(),files=new Map(),fileShas=new Map(),results=new Map(),refreshHolds=[],updates=new Map(),histories=new Map(),frozen=new Map(),nationwide=new Map(),nationwideHistory=new Map();let importedAt=parts[0].importedAt;
    const stable=v=>Array.isArray(v)?'['+v.map(stable).join(',')+']':record(v)?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stable(v[k])).join(',')+'}':JSON.stringify(v);
    const semantic=result=>Object.fromEntries(Object.entries(result).filter(([key])=>key!=='observed_at'));

    const roster=row=>row.riders.map(p=>p.number+':'+p.name.replace(/\s/g,'')).sort().join('|');
    const registrations=row=>{
      const result=new Map();
      for(const p of [...row.riders,...(row.jointForecast?.riders||[]),...(row.riderHistory?.riders||[])])if(typeof p.registration==='string'&&/^[0-9]{6}$/.test(p.registration)){
        const car=p.number??p.car;need(!result.has(car)||result.get(car)===p.registration);result.set(car,p.registration);
      }
      return result;
    };
    for(const part of parts){
      for(const [path,value] of part.files)files.set(path,value);
      for(const [path,value] of part.fileShas||[])fileShas.set(path,value);
      importedAt=part.importedAt;
      for(const date of part.dates){
        const national=part.nationwide?.get(date);
        if(national){
          const history=nationwideHistory.get(date)||new Map(),seen=history.get(national.revision);
          need(!seen||stable(M.nationwideSemantic(seen))===stable(M.nationwideSemantic(national)));
          if(!seen||Date.parse(national.observed_at)>=Date.parse(seen.observed_at))history.set(national.revision,national);
          nationwideHistory.set(date,history);nationwide.set(date,M.mergeNationwide(nationwide.get(date),national));
        }
        if(!frozen.has(date))frozen.set(date,new Map());
        for(const [id,original] of part.frozenForecasts?.get(date)||[]){const prior=frozen.get(date).get(id);need(!prior||stable(prior)===stable(original));frozen.get(date).set(id,original);}
        if(!updates.has(date))updates.set(date,new Map());
        for(const [id,result] of part.resultUpdates?.get(date)||[]){
          const history=histories.get(id)||new Map(),seen=history.get(result.revision);
          need(!seen||stable(semantic(seen))===stable(semantic(result)));
          if(!seen||Date.parse(result.observed_at)>=Date.parse(seen.observed_at))history.set(result.revision,result);
          histories.set(id,history);
          const prior=updates.get(date).get(id);
          if(!prior||Date.parse(result.observed_at)>=Date.parse(prior.observed_at))updates.get(date).set(id,result);
        }

        const byId=new Map((days.get(date)||[]).map(row=>[row.id,row]));
        for(const row of M.rows(part,date)){
          if(row.nationwideOnly)continue;
          const prior=byId.get(row.id);if(!prior){byId.set(row.id,{...row,referenceHistory:[...(row.referenceHistory||[])],researchResultHistory:[],latestResearchResult:null,resultHistory:[],resultUpdate:null});continue;}
          // Immutable snapshots keep every version. An input refresh does not
          // replace the authored originals imported from the owner's Site.
          const authored=(prior.original.tickets||[]).length>0;
          const predicted=authored||Boolean(prior.jointForecast)||Object.keys(prior.reference||{}).length>0||(prior.two.tickets||[]).length>0||Object.keys(prior.flexible?.markets||{}).length>0;
          const sameCutoff=prior.cutoff===row.cutoff||M.sameClock(prior.cutoff,row.cutoff);
          const oldIds=registrations(prior),newIds=registrations(row),identityConflict=[...oldIds].some(([car,id])=>newIds.has(car)&&newIds.get(car)!==id);
          if((predicted||row.jointForecast||prior.riderHistory||row.riderHistory)&&(roster(prior)!==roster(row)||!sameCutoff||identityConflict)){
            refreshHolds.push({raceId:row.id,reason:'HOLD_RESEARCH_REFRESH_SOURCE_CONTEXT_CHANGED'});continue;
          }
          const combined={...prior,bindings:{...prior.bindings}};
          if(row.riderHistory){
            const priorHistory=prior.riderHistory, incoming=row.riderHistory;
            const versions=[...(prior.riderHistoryVersions||[])];
            if(priorHistory&&stable(priorHistory)!==stable(incoming)){
              need(M.instantMicros(incoming.generated_at)>M.instantMicros(priorHistory.generated_at));
              need(M.instantMicros(incoming.knowledge_as_of)>=M.instantMicros(priorHistory.knowledge_as_of));
              versions.push(priorHistory);
            }
            combined.riderHistory=incoming;combined.riderHistoryVersions=versions;
          }
          if(row.jointForecast){
            const history=[...(prior.jointForecastHistory||[])];
            if(prior.jointForecast&&stable(prior.jointForecast)!==stable(row.jointForecast)){
              need(M.instantMicros(row.jointForecast.generated_at)>M.instantMicros(prior.jointForecast.generated_at));
              history.push({forecast:prior.jointForecast,binding:prior.jointForecastBindings});
            }
            combined.jointForecast=row.jointForecast;combined.jointForecastBindings=row.jointForecastBindings;combined.jointForecastHistory=history;combined.comparisonRiders=row.comparisonRiders;
          }
          for(const name of ['original','two','flexible','rollover','settlement']){
            const old=prior[name],fresh=row[name];
            if(name==='settlement'&&fresh&&(!record(fresh)||Object.keys(fresh).length))combined[name]=fresh;
            else if((!old||record(old)&&!Object.keys(old).length)&&fresh){combined[name]=fresh;if(row.bindings?.[name])combined.bindings[name]=row.bindings[name];}
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
    M.attachNationwide(days,nationwide);
    for(const [date,list] of days)days.set(date,list.map(row=>{
      const history=results.get(row.id)||[];
      need(history.every(saved=>saved.observation.winning_triple===null||!row.cars.size||saved.observation.winning_triple.every(n=>row.cars.has(n))));
      return {...row,researchResultHistory:[...history],latestResearchResult:history.at(-1)||null};
    }));
    for(const [date,rows] of days)days.set(date,rows.map(row=>{
      const result=updates.get(date)?.get(row.id),original=frozen.get(date)?.get(row.id);if(!result&&!original)return row;
      return {...row,...(result?{resultUpdate:result,resultHistory:[...histories.get(row.id).values()]}:{}),...(original?{frozenForecast:M.combineFrozen(row.frozenForecast,original)}:{})};
    }));
    const checks=new Map(Object.entries(resultChecks));
    for(const [id,check] of checks){
      const latest=results.get(id)?.at(-1)?.observation;
      if(check.digest!==null)need(latest&&latest.observation_sha256===check.digest&&Date.parse(check.checked_at)>=Date.parse(latest.captured_at)&&check.status===(latest.state==='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL'?'MATCHED':latest.state.startsWith('PENDING_')?'PENDING':'HOLD'));
      else need(!latest&&check.status!=='MATCHED');
    }
    return {schema:M.SCHEMA,dates:[...days.keys()].sort(),days,files,fileShas,results,resultUpdates:updates,frozenForecasts:frozen,nationwide,nationwideHistory,resultChecks:checks,cipherSha:null,formal:false,importedAt,sourceCommit:parts[0].sourceCommit,refreshHolds};
  }
  async function bytes(response,signal){
    need(response.ok);const length=response.headers?.get('content-length');need(length==null||/^\d+$/.test(length)&&Number(length)<=MAX);
    const reader=response.body?.getReader();need(reader);const parts=[];let size=0;
    try{for(;;){need(!signal?.aborted);const {value,done}=await reader.read();if(done)break;size+=value.byteLength;need(size<=MAX);parts.push(value);}}catch(e){await reader.cancel().catch(()=>{});throw e;}
    const result=new Uint8Array(size);let offset=0;for(const p of parts){result.set(p,offset);offset+=p.length;}return result;
  }
  async function createSession(key,{fetcher=globalThis.fetch}={}){
    let cap=await capability(key),previous=null,busy=false,closed=false;
    const cache=new Map();
    const sameEntry=(a,b)=>Object.keys(a).sort().every(name=>JSON.stringify(a[name])===JSON.stringify(b[name]));
    async function refresh({signal,onStatus}={}){
      need(!closed&&!busy&&!signal?.aborted);busy=true;
      try{
        const options={credentials:'omit',referrerPolicy:'no-referrer',cache:'no-store',redirect:'error',signal};
        const wire=await bytes(await fetcher(BASE+'index.json',options),signal);
        const index=checkIndex(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(wire)),cap.recipient);
        if(previous){
          need(index.entries.length>=previous.entries.length&&(!previous.provider_denied||index.provider_denied));
          previous.entries.forEach((entry,i)=>need(sameEntry(entry,index.entries[i])));
          for(const [id,check] of Object.entries(previous.result_checks||{})){const fresh=index.result_checks?.[id];need(fresh&&Date.parse(fresh.checked_at)>=Date.parse(check.checked_at));}
        }
        const parts=[],display=index.entries.filter(e=>e.kind!=='archive');
        for(const entry of display){
          need(!closed&&!signal?.aborted);
          if(!cache.has(entry.cipher_sha256)){
            onStatus?.('暗号化した保存履歴を確認しています。 '+(parts.length+1)+' / '+display.length);
            const body=await bytes(await fetcher(BASE+'views/'+entry.cipher_sha256+'.json',options),signal);
            const part=await openEntry(body,entry,cap);need(!closed&&!signal?.aborted);cache.set(entry.cipher_sha256,part);
          }
          parts.push(cache.get(entry.cipher_sha256));
        }
        need(!closed&&!signal?.aborted);
        const data=merge(parts,{resultChecks:index.result_checks||{}});
        data.feed={entries:index.entries.length,providerDenied:index.provider_denied,revision:await M.digest(wire),checkedAt:new Date().toISOString()};
        need(!closed&&!signal?.aborted);previous=index;return data;
      }finally{busy=false;}
    }
    return {refresh,close(){closed=true;cap=null;previous=null;cache.clear();}};
  }
  async function open(key,{signal,onStatus,fetcher=globalThis.fetch}={}){
    const session=await createSession(key,{fetcher});
    try{return await session.refresh({signal,onStatus});}finally{session.close();}
  }
  function watchSession(session,{onUpdate,onError=()=>{},isActive=()=>true,setTimer=globalThis.setTimeout,clearTimer=globalThis.clearTimeout}={}){
    need(typeof session?.refresh==='function'&&typeof onUpdate==='function');
    let closed=false,busy=false,timer=null,timeout=null,abort=null;
    async function check(){
      if(timer!==null){clearTimer(timer);timer=null;}
      if(closed||busy||!isActive())return;
      busy=true;abort=new AbortController();timeout=setTimer(()=>abort?.abort(),120000);
      try{const value=await session.refresh({signal:abort.signal});if(!closed&&!abort.signal.aborted)await onUpdate(value);}
      catch{if(!closed)onError();}
      finally{clearTimer(timeout);timeout=null;abort=null;busy=false;if(!closed&&isActive())timer=setTimer(check,30000);}
    }
    function stop(){if(closed)return;closed=true;if(timer!==null)clearTimer(timer);if(timeout!==null)clearTimer(timeout);timer=timeout=null;abort?.abort();session.close();}
    return {check,stop};
  }
  return {open,createSession,watchSession,openEntry,capability,checkIndex,merge,BASE};
});
