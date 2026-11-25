'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {webcrypto,createHash}=require('node:crypto');
const {packet,source}=require('./keirin_note_model.test.cjs');
const F=require('../web/keirin-note-feed.js');
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const b64=raw=>Buffer.from(raw).toString('base64url');
const enc=v=>Buffer.from(JSON.stringify(v));

async function fixture(){
  const c=webcrypto.subtle,owner=await c.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
  const ownerPublic=await c.exportKey('raw',owner.publicKey),recipient=sha(Buffer.from(ownerPublic));
  const key=b64(await c.exportKey('pkcs8',owner.privateKey));
  const wires=new Map();
  async function entry(value,stamp){
    const ephemeral=await c.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
    const shared=await c.deriveBits({name:'ECDH',public:owner.publicKey},ephemeral.privateKey,256);
    const material=await c.importKey('raw',shared,'HKDF',false,['deriveBits']);
    const salt=webcrypto.getRandomValues(new Uint8Array(32));
    // Same reviewed public-recipient wire protocol as the Python writer.
    const actual=await c.deriveBits({name:'HKDF',hash:'SHA-256',salt,info:new TextEncoder().encode('RACE_AI_KEIRIN_NOTE_FEED_V1:'+recipient)},material,256);
    const raw=enc(value);
    const plain=value.scope==='OWNER_MAC_SHADOW_VERIFICATION'?Buffer.concat([raw,Buffer.alloc(2048-raw.length,0x20)]):raw;
    const header={schema:'RACE_AI_SAVED_WEB_VIEW_V1',source_content_sha256:sha(plain)};
    const nonce=webcrypto.getRandomValues(new Uint8Array(12)),aesKey=await c.importKey('raw',actual,'AES-GCM',false,['encrypt']);
    const cipher=await c.encrypt({name:'AES-GCM',iv:nonce,additionalData:enc(header)},aesKey,plain);
    const wire=enc({header,nonce:Buffer.from(nonce).toString('base64'),ciphertext:Buffer.from(cipher).toString('base64')});
    const e={cipher_sha256:sha(wire),source_content_sha256:header.source_content_sha256,ephemeral_public_key:b64(await c.exportKey('raw',ephemeral.publicKey)),salt:b64(salt),created_at:stamp,days:value.dates,kind:'research',captured_race_ids:['203001159801'],priority_window_race_ids:[]};
    wires.set(e.cipher_sha256,wire);return e;
  }
  const a=await entry(packet(),'2030-01-15T00:00:00Z');
  const p=packet();p.imported_at='2030-01-15T01:00:00Z';
  const b=await entry(p,'2030-01-15T01:00:00Z');
  let index={schema:'RACE_AI_KEIRIN_NOTE_FEED_V1',repository:'haji84/RACE-AI',recipient_id:recipient,entries:[a],provider_denied:false,covered_race_ids:['203001159801'],priority_window_race_ids:[]};
  const requests=[];
  return {key,a,b,entry,setIndex:value=>{index=value;},index:()=>structuredClone(index),requests,
    fetcher:async(url,options)=>{
      requests.push(url);assert.equal(options.credentials,'omit');assert.equal(options.referrerPolicy,'no-referrer');assert.equal(options.redirect,'error');assert.ok(!url.includes(key));
      const raw=url.endsWith('/index.json')?enc(index):wires.get(url.split('/').at(-1).replace('.json',''));
      assert.ok(raw);return new Response(raw);
    }};
}

test('open-page refresh reads only the index until a new immutable snapshot appears',async()=>{
  assert.equal(typeof F.createSession,'function','a reusable verified feed session is required');
  const v=await fixture(),session=await F.createSession(v.key,{fetcher:v.fetcher});
  const first=await session.refresh();assert.equal(first.feed.entries,1);assert.equal(v.requests.length,2);
  const unchanged=await session.refresh();assert.equal(unchanged.feed.revision,first.feed.revision);assert.equal(v.requests.length,3);
  const next=v.index();next.entries.push(v.b);v.setIndex(next);
  const changed=await session.refresh();assert.equal(changed.feed.entries,2);assert.notEqual(changed.feed.revision,first.feed.revision);assert.equal(v.requests.length,5);assert.equal(changed.days.get('2030-01-15').length,1);
  session.close();await assert.rejects(()=>session.refresh());
});

test('refresh refuses a shortened feed or rewritten entry and never removes a denial latch',async()=>{
  assert.equal(typeof F.createSession,'function');
  for(const change of ['truncate','rewrite','unlatch']){
    const v=await fixture(),start=v.index();start.entries.push(v.b);start.provider_denied=true;v.setIndex(start);
    const session=await F.createSession(v.key,{fetcher:v.fetcher});await session.refresh();
    const next=v.index();if(change==='truncate')next.entries.pop();if(change==='rewrite')next.entries[0].kind='import';if(change==='unlatch')next.provider_denied=false;v.setIndex(next);
    await assert.rejects(()=>session.refresh());assert.equal(v.requests.length,4);session.close();
  }
});

test('an aborted refresh cannot replace the last verified snapshot',async()=>{
  assert.equal(typeof F.createSession,'function');
  const v=await fixture(),session=await F.createSession(v.key,{fetcher:v.fetcher});
  const first=await session.refresh(),abort=new AbortController();abort.abort();
  await assert.rejects(()=>session.refresh({signal:abort.signal}));assert.equal(v.requests.length,2);
  const fresh=await session.refresh();assert.equal(fresh.feed.revision,first.feed.revision);session.close();
});

test('public result revision metadata must match the decrypted result-only packet',async()=>{
  const v=await fixture(),note=packet(),day='2030-01-15',rid='203001159801';
  const row={race_id:rid,revision:'c'.repeat(64),observed_at:day+'T04:00:00Z',authority:'secondary',order_status:'confirmed',payout_status:'held',winning_triples:['1-2-3'],payouts_100yen:{},source_comparison:[],diagnostics:[],arms:Object.fromEntries(['A','B','C','adjusted_A','adjusted_B'].map(name=>[name,{state:'pending',points:null,stake_yen:null,return_yen:null}]))};
  note.files={['data/'+day+'/result_updates.json']:source({schema:'RACE_AI_KEIRIN_RESULT_UPDATES_V1',observed_at:day+'T04:00:00Z',races:[row]})};
  const result=await v.entry(note,day+'T04:00:00Z');result.kind='result';result.captured_race_ids=[];result.result_revisions={[rid]:row.revision};
  const index=v.index();index.entries.push(result);v.setIndex(index);
  const session=await F.createSession(v.key,{fetcher:v.fetcher});
  const data=await session.refresh();assert.equal(data.days.get(day)[0].resultUpdate.revision,row.revision);session.close();
  index.entries[1].result_revisions[rid]='d'.repeat(64);v.setIndex(index);
  const wrong=await F.createSession(v.key,{fetcher:v.fetcher});await assert.rejects(()=>wrong.refresh());wrong.close();
  const publicIndex=v.index();publicIndex.entries[1].result_revisions={secret:'c'.repeat(64)};assert.throws(()=>F.checkIndex(publicIndex,publicIndex.recipient_id));
});

const shadowDay='2030-01-15',shadowRace='203001159801',shadowKind='shadow-verification';
const clock=hm=>shadowDay+'T'+hm+':00Z';

function shadowNote(archive,change=value=>value){
  const observation=change({
    schema:'RACE_AI_KEIRIN_SHADOW_VERIFICATION_V1',day_jst:shadowDay,race_id:shadowRace,
    verified_at:clock('01:00'),start_at:clock('00:45'),
    original:{sha256:'a'.repeat(64),archive_cipher_sha256:archive.cipher_sha256,
      generated_at:clock('00:05'),cutoff_at:clock('00:40')},
    result:{evidence_sha256:'b'.repeat(64),observed_at:clock('00:50'),scope:'TWO_SOURCE_MATCHED_PODIUM_ONLY'},
    scores:{trifecta:{points:4,saved_hit:false,challenger_hit:true},exacta:{points:2,saved_hit:true,challenger_hit:false}},
    tracking_learning:'HELD',production_weights_promoted:false
  });
  return {
    schema:'RACE_AI_KEIRIN_NOTE_VIEW_V1',scope:'OWNER_MAC_SHADOW_VERIFICATION',source_site:null,
    source_commit:'e'.repeat(40),imported_at:observation.verified_at,dates:[shadowDay],
    formal_model_admission:false,production_weight_switch:false,wagers_placed:false,
    shadow_verification_private_nonce:b64(new Uint8Array(32).fill(93)),
    files:{['data/'+shadowDay+'/shadow_verification.json']:source(observation)}
  };
}

async function metadataEntry(v,value,stamp,kind){
  const e=await v.entry(value,stamp);
  return {...e,kind,captured_race_ids:[],priority_window_race_ids:[]};
}

test('the owner feed binds a private shadow verification without fetching the frozen archive',async()=>{
  const v=await fixture();
  const archive=await metadataEntry(v,{...packet(),files:{}},clock('00:06'),'archive');
  const verifier=await metadataEntry(v,shadowNote(archive),clock('01:02'),shadowKind);
  const index=v.index();index.entries.push(archive,verifier);v.setIndex(index);
  const verified=await F.open(v.key,{fetcher:v.fetcher});
  assert.equal(verified.shadowVerifications.size,1);
  const receipt=verified.shadowVerifications.get(shadowRace);
  assert.equal(receipt.result.scope,'TWO_SOURCE_MATCHED_PODIUM_ONLY');
  assert.deepEqual(receipt.scores,{trifecta:{points:4,saved_hit:false,challenger_hit:true},
    exacta:{points:2,saved_hit:true,challenger_hit:false}});
  assert.equal(verified.results.size,0);
  assert.equal(verified.resultUpdates.get(shadowDay).size,0);
  assert.equal(verified.days.get(shadowDay).length,1);
  assert.equal(verified.files.has('data/'+shadowDay+'/shadow_verification.json'),false);
  assert.equal(v.requests.some(url=>url.includes(archive.cipher_sha256)),false);
});

test('an official complete finish keeps its own research scope',async()=>{
  const v=await fixture();
  const archive=await metadataEntry(v,{...packet(),files:{}},clock('00:06'),'archive');
  const verifier=await metadataEntry(v,shadowNote(archive,value=>{
    value.result.scope='OFFICIAL_COMPLETE_FINISH_RESEARCH';
    return value;
  }),clock('01:02'),shadowKind);
  const index=v.index();index.entries.push(archive,verifier);v.setIndex(index);
  const verified=await F.open(v.key,{fetcher:v.fetcher});
  assert.equal(verified.shadowVerifications.get(shadowRace).result.scope,'OFFICIAL_COMPLETE_FINISH_RESEARCH');
  assert.equal(verified.resultUpdates.get(shadowDay).size,0);
});

test('shadow verification never admits a late or undisclosed archive or a premature outcome',async()=>{
  for(const invalid of ['absent','late','later-entry','prestart','kind','coverage','source-document']){
    const v=await fixture();
    const archive=await metadataEntry(v,{...packet(),files:{}},
      clock(invalid==='late'?'00:41':'00:06'),invalid==='kind'?'research':'archive');
    const note=shadowNote(archive,record=>{
      if(invalid==='prestart')record.result.observed_at=clock('00:44');
      if(invalid==='source-document')record.result.raw='fixture-private-source';
      return record;
    });
    const verifier=await metadataEntry(v,note,clock('01:02'),shadowKind);
    if(invalid==='coverage')verifier.captured_race_ids=[shadowRace];
    const index=v.index();
    if(invalid==='absent')index.entries.push(verifier);
    else if(invalid==='later-entry')index.entries.push(verifier,archive);
    else index.entries.push(archive,verifier);
    v.setIndex(index);
    await assert.rejects(()=>F.open(v.key,{fetcher:v.fetcher}),undefined,invalid);
  }
});

test('equivalent checks count once and a different same-race score cannot supersede the first',async()=>{
  const v=await fixture();
  const archive=await metadataEntry(v,{...packet(),files:{}},clock('00:06'),'archive');
  const first=await metadataEntry(v,shadowNote(archive),clock('01:02'),shadowKind);
  const retry=await metadataEntry(v,shadowNote(archive,value=>({...value,verified_at:clock('01:03'),
    result:{...value.result,observed_at:clock('00:51')}})),clock('01:04'),shadowKind);
  const conflict=await metadataEntry(v,shadowNote(archive,value=>{
    value.result.scope='OFFICIAL_COMPLETE_FINISH_RESEARCH';
    value.result.evidence_sha256='c'.repeat(64);
    value.scores.trifecta.challenger_hit=false;
    value.verified_at=clock('01:05');
    return value;
  }),clock('01:06'),shadowKind);
  const index=v.index();index.entries.push(archive,first,retry);v.setIndex(index);
  const session=await F.createSession(v.key,{fetcher:v.fetcher});
  try{
    const initial=await session.refresh();
    assert.equal(initial.shadowVerifications.size,1);
    assert.equal(initial.shadowVerificationHolds.size,0);
    index.entries.push(conflict);v.setIndex(index);
    const final=await session.refresh();
    assert.equal(final.shadowVerifications.size,1);
    assert.deepEqual(final.shadowVerifications.get(shadowRace),initial.shadowVerifications.get(shadowRace));
    assert.deepEqual([...final.shadowVerificationHolds],[shadowRace]);
    assert.equal(final.days.get(shadowDay).length,1);
  }finally{session.close();}
});

test('the visible-page watcher updates immediately, waits thirty seconds and stops on clear',async()=>{
  assert.equal(typeof F.watchSession,'function');
  const timers=new Map(),updates=[];let id=0,calls=0,closed=0,active=true;
  const watcher=F.watchSession({refresh:async()=>({revision:++calls}),close:()=>closed++},{
    onUpdate:value=>updates.push(value.revision),isActive:()=>active,
    setTimer:(fn,ms)=>{timers.set(++id,{fn,ms});return id;},clearTimer:id=>timers.delete(id)});
  await watcher.check();assert.deepEqual(updates,[1]);assert.equal([...timers.values()][0].ms,30000);
  active=false;await [...timers.values()][0].fn();assert.equal(calls,1);
  active=true;await watcher.check();assert.deepEqual(updates,[1,2]);
  watcher.stop();await watcher.check();assert.equal(calls,2);assert.equal(closed,1);assert.equal(timers.size,0);
});

test('a late refresh after clear cannot call the display or start another timer',async()=>{
  assert.equal(typeof F.watchSession,'function');
  let release,updated=0,closed=0;const timers=new Map();let id=0;
  const watcher=F.watchSession({refresh:()=>new Promise(resolve=>{release=resolve;}),close:()=>closed++},{
    onUpdate:()=>updated++,setTimer:(fn,ms)=>{timers.set(++id,{fn,ms});return id;},clearTimer:id=>timers.delete(id)});
  const pending=watcher.check();watcher.stop();release({});await pending;
  assert.equal(updated,0);assert.equal(closed,1);assert.equal(timers.size,0);
});
