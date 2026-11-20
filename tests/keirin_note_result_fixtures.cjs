'use strict';
const {createHash}=require('node:crypto');
const DAY='2030-01-15',RACE='203001159801';
const canonical=v=>JSON.stringify(v&&typeof v==='object'?Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))])):v);
const sha=v=>createHash('sha256').update(typeof v==='string'?v:canonical(v)).digest('hex');
function observation({state='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL',previous=null,at='2030-01-15T03:10:00Z',triple=[3,1,2],payout=5300,race=RACE,providers=['Kdreams','netkeirin']}={}){
  const matched=state==='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL';
  const value={schema:'RACE_AI_KEIRIN_INDEPENDENT_SECONDARY_RESULT_MATCH_V1',race_id:race,state,
    winning_triple:matched?triple:null,payout_per_100yen:matched?payout:null,
    provider_receipts:providers.map((provider,i)=>({provider,source_bytes_sha256:String(i+1).repeat(64),observed_at:at,
      source_url:provider==='netkeirin'?'https://keirin.netkeiba.com/race/result/?race_id='+race:'https://keirin.kdreams.jp/fixture/racedetail/98203001150100'+race.slice(-2)+'/?pageType=result'})),
    official_primary_result_authenticated:false,actual_organizer_cutoff_authenticated:false,qualifies_for_formal_settlement:false};
  const fact={...value,provider_receipts:value.provider_receipts.map(({provider,source_url})=>({provider,source_url}))};
  return {...value,captured_at:at,observation_sha256:sha(fact),previous_observation_sha256:previous};
}
function resultsPacket(observations){
  const value={schema:'RACE_AI_KEIRIN_NOTE_RESEARCH_RESULTS_V1',day_jst:DAY,observations};
  const text=JSON.stringify(value);
  return {schema:'RACE_AI_KEIRIN_NOTE_VIEW_V1',formal_model_admission:false,production_weight_switch:false,
    source_commit:'a'.repeat(40),imported_at:observations.at(-1)?.captured_at||'2030-01-15T03:10:00Z',dates:[DAY],
    files:{['data/'+DAY+'/research_results.json']:{text,sha256:sha(text),bytes:Buffer.byteLength(text)}}};
}
function index(kind='import'){
  return {schema:'RACE_AI_KEIRIN_NOTE_FEED_V1',repository:'haji84/RACE-AI',recipient_id:'a'.repeat(64),provider_denied:false,
    covered_race_ids:kind==='results'?[]:[RACE],priority_window_race_ids:[],entries:[{cipher_sha256:'b'.repeat(64),source_content_sha256:'c'.repeat(64),
      ephemeral_public_key:Buffer.alloc(65,4).toString('base64url'),salt:Buffer.alloc(32,2).toString('base64url'),created_at:'2030-01-15T03:10:00Z',days:[DAY],kind,
      captured_race_ids:kind==='results'?[]:[RACE],priority_window_race_ids:[]}]};
}
module.exports={DAY,RACE,canonical,sha,observation,resultsPacket,index};

// Real fixture ECDH/HKDF/AES; all keys are random, test-only and kept in memory.
module.exports.encryptedEntry=async function(packet,kind='import'){
  const {webcrypto:c}=require('node:crypto'),F=require('../web/keirin-note-feed.js'),encoder=new TextEncoder();
  const owner=await c.subtle.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
  const key=Buffer.from(await c.subtle.exportKey('pkcs8',owner.privateKey)).toString('base64url'),cap=await F.capability(key);
  const ephemeral=await c.subtle.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']),salt=c.getRandomValues(new Uint8Array(32));
  const shared=await c.subtle.deriveBits({name:'ECDH',public:owner.publicKey},ephemeral.privateKey,256),material=await c.subtle.importKey('raw',shared,'HKDF',false,['deriveBits']);
  const raw=await c.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt,info:encoder.encode('RACE_AI_KEIRIN_NOTE_FEED_V1:'+cap.recipient)},material,256);
  const aes=await c.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['encrypt']),plain=encoder.encode(JSON.stringify(packet));
  const header={schema:'RACE_AI_SAVED_WEB_VIEW_V1',source_content_sha256:sha(Buffer.from(plain).toString())},nonce=c.getRandomValues(new Uint8Array(12));
  const ciphertext=await c.subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:encoder.encode(JSON.stringify(header)),tagLength:128},aes,plain);
  const wire=encoder.encode(JSON.stringify({header,nonce:Buffer.from(nonce).toString('base64'),ciphertext:Buffer.from(ciphertext).toString('base64')}));
  return {wire,cap,entry:{cipher_sha256:sha(Buffer.from(wire).toString()),source_content_sha256:header.source_content_sha256,ephemeral_public_key:Buffer.from(await c.subtle.exportKey('raw',ephemeral.publicKey)).toString('base64url'),salt:Buffer.from(salt).toString('base64url'),created_at:'2030-01-15T03:10:00Z',days:[DAY],kind,captured_race_ids:kind==='results'?[]:[RACE],priority_window_race_ids:[]}};
};
