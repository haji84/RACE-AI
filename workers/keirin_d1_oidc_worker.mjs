// RACE-AI KEIRIN private state ingress. GitHub OIDC only; no unauthenticated reads.
// The existing Cloudflare D1 binding is not a source licence or model execution.
// This endpoint accepts public race identities, NOT raw forecast originals.
// No public forecast, result or odds data is returned or logged.
const AUD = 'race-ai-keirin-private-state-v1';
const ISS = 'https://token.actions.githubusercontent.com';
const OWNER_REPO = 'haji84/RACE-AI';
const REPO_ID = '1416489937';
const WFREF = OWNER_REPO + '/.github/workflows/keirin-d1-oidc-bridge.yml@refs/heads/main';
const MAX_BODY = 45000;
const DAY_ID = /^\d{4}-\d\d-\d\d$/;
const SHA = /^[a-f0-9]{64}$/;
const RACE = /^\d{12}$/;
const ALLOWED_EVENT = new Set(['push','schedule','workflow_dispatch']);
let jwkCache = {loadedAt:0,keys:[]};

function json(body, status=200) {
  return new Response(JSON.stringify(body), {
    status,
    headers:{'content-type':'application/json; charset=utf-8',
             'cache-control':'no-store',
             'x-content-type-options':'nosniff',
             'x-frame-options':'DENY'}
  });
}
function base64Url(bytes) {
  const normalized = bytes.replace(/-/g,'+').replace(/_/g,'/');
  const str = atob(normalized.padEnd(Math.ceil(normalized.length/4)*4,'='));
  return Uint8Array.from(str, x=>x.charCodeAt(0));
}
function utf8Json(value) {
  return JSON.parse(new TextDecoder().decode(base64Url(value)));
}
const PINNED_GITHUB_PUBLIC_JWKS = [{"alg":"RS256","e":"AQAB","kid":"cc413527-173f-5a05-976e-9c52b1d7b431","kty":"RSA","n":"w4M936N3ZxNaEblcUoBm-xu0-V9JxNx5S7TmF0M3SBK-2bmDyAeDdeIOTcIVZHG-ZX9N9W0u1yWafgWewHrsz66BkxXq3bscvQUTAw7W3s6TEeYY7o9shPkFfOiU3x_KYgOo06SpiFdymwJflRs9cnbaU88i5fZJmUepUHVllP2tpPWTi-7UA3AdP3cdcCs5bnFfTRKzH2W0xqKsY_jIG95aQJRBDpbiesefjuyxcQnOv88j9tCKWzHpJzRKYjAUM6OPgN4HYnaSWrPJj1v41eEkFM1kORuj-GSH2qMVD02VklcqaerhQHIqM-RjeHsN7G05YtwYzomE5G-fZuwgvQ","use":"sig"},{"alg":"RS256","e":"AQAB","kid":"38826b17-6a30-5f9b-b169-8beb8202f723","kty":"RSA","n":"5Manmy-zwsk3wEftXNdKFZec4rSWENW4jTGevlvAcU9z3bgLBogQVvqYLtu9baVm2B3rfe5onadobq8po5UakJ0YsTiiEfXWdST7YI2Sdkvv-hOYMcZKYZ4dFvuSO1vQ2DgEkw_OZNiYI1S518MWEcNxnPU5u67zkawAGsLlmXNbOylgVfBRJrG8gj6scr-sBs4LaCa3kg5IuaCHe1pB-nSYHovGV_z0egE83C098FfwO1dNZBWeo4Obhb5Z-ZYFLJcZfngMY0zJnCVNmpHQWOgxfGikh3cwi4MYrFrbB4NTlxbrQ3bL-rGKR5X318veyDlo8Dyz2KWMobT4wB9U1Q","use":"sig"},{"alg":"RS256","e":"AQAB","kid":"38E9B30B3A023A1B72309921A69A42FCC496C42C","kty":"RSA","n":"tEq2Fp9HcdT5MwMsB_UTm8j_woJJLi3sA-y0RX2tioTm581seyfvOH6lJ5JmHVtS-_fb8B2tRT1pznHQSNq14PsJdu9bp5egbWmIz-5RvhqoM-oKem_MJENCNFuqXijRLT47FRdfH3inqde1vJlA_JJHCqYMKIpHH7kqNFYcCpwr0vk80Hc2rTyL0uBXI7NqBZbtUgNoyucWO5O7QQrPNOmlr-GI8aFckFRfobCaCOiH9qW02FtkV74fwBGVCNhNf3a1CK81-O8xEGimvVydI_pQA5B8QqVuQjY_ntOu555HdirA0hKkY6fsE9eZCMFmWDHZ2kSWLjhabxWxIzSzXQ","use":"sig"},{"alg":"RS256","e":"AQAB","kid":"4F3E9AD8C9A6F5EB3173006F4FA630E28F43DCE9","kty":"RSA","n":"tGevqhkBGn8NB0dKxs8Ddxhn-xZPm55svcSlkJZEOwDOXDLl_0-iVOVKNJfcHHLHvMqa6zh2DDcpAWZi2FpeBAJupsrymqwzllxOODWKWoVIoaIjOO7h1JLiF9Knwuq-o6BPtKdwOT-bOrXRzChMtQsc5C1Auex-D0Z6loObBuK1Lkm0RK9ISQsLqBEwq8g0OOupI_shU1r2rT2G0nkZ0CvxVlQeUGShFi8Mdys2s5LPqBwjC4LKwjk8moWQV32KEccbTPKxnG_539DxRglHJgHPHisSVGsfZIUXi2chtXdQHZPdVve8ZRmknCykZtkJ6K87llSUXi7oyzhCIZdiUQ","use":"sig"}];
const PINNED_KEYS_FETCHED_AT = "2026-11-03T05:09:13.818922+00:00";
const MAX_JWKS_AGE_MS=7*86400000;
function trustedJwks(value) {
  if(!Array.isArray(value) || value.length<1 || value.length>20) return false;
  const seen=new Set();
  return value.every(k=>{
    if(!k || typeof k!=='object' || Array.isArray(k) ||
       k.kty!=='RSA' || k.alg!=='RS256' || k.use!=='sig' ||
       typeof k.kid!=='string' || !/^[A-Za-z0-9_-]{8,128}$/.test(k.kid) ||
       typeof k.n!=='string' || !/^[A-Za-z0-9_-]{250,900}$/.test(k.n) ||
       k.e!=='AQAB' || seen.has(k.kid)) return false;
    seen.add(k.kid);
    return true;
  });
}
function keyAgeValid(stamp,now,limit=MAX_JWKS_AGE_MS) {
  if(typeof stamp!=='string' || stamp.length>64) return false;
  const n=Date.parse(stamp);
  return Number.isFinite(n) && n<=now+60000 && now-n<limit;
}
async function keys(env) {
  const now=Date.now();
  if(jwkCache.keys.length && now-jwkCache.loadedAt<300000) {
    return jwkCache.keys;
  }
  // This account cannot fetch GitHub's OIDC discovery from the Worker.
  // Use public JWKs delivered by a GitHub-verified main-branch workflow.
  let trusted=null;
  if(env?.OWNER_DB) {
    try {
      const row=await env.OWNER_DB.prepare(
        'SELECT jwks_json,retrieved_at FROM keirin_trusted_oidc_keys WHERE slot=1'
      ).first();
      if(row && keyAgeValid(row.retrieved_at,now)) {
        const parsed=JSON.parse(row.jwks_json);
        if(trustedJwks(parsed)) trusted=parsed;
      }
    } catch {}
  }
  if(!trusted && keyAgeValid(PINNED_KEYS_FETCHED_AT,now) &&
     trustedJwks(PINNED_GITHUB_PUBLIC_JWKS)) {
    trusted=PINNED_GITHUB_PUBLIC_JWKS;
  }
  if(!trusted) throw new Error('OIDC_TRUSTED_KEYS_EXPIRED');
  jwkCache={loadedAt:now,keys:trusted};
  return trusted;
}
async function postJwksRefresh(request,env) {
  const data=await readBody(request);
  if(!data || typeof data!=='object' || Array.isArray(data) ||
     Object.keys(data).sort().join(',')!==
       'keys,retrieved_at,schema,source_sha256' ||
     data.schema!=='RACE_AI_GITHUB_OIDC_JWKS_REFRESH_V1' ||
     !SHA.test(data.source_sha256) ||
     !keyAgeValid(data.retrieved_at,Date.now(),2*3600000) ||
     !trustedJwks(data.keys)) {
    return json({error:'JWKS_REFRESH_PAYLOAD_INVALID'},422);
  }
  // An already-verified JWT may refresh the trust anchor only if its
  // signing key remains exactly identical in the new official key set.
  let currentKid;
  try {
    const token=(request.headers.get('authorization')||'').slice(7);
    currentKid=utf8Json(token.split('.')[0]).kid;
  } catch { return json({error:'JWKS_REFRESH_SIGNER_INVALID'},422); }
  const oldKeys=await keys(env);
  const old=oldKeys.find(k=>k.kid===currentKid);
  const matching=data.keys.find(k=>k.kid===currentKid);
  if(!old || !matching || old.n!==matching.n || old.e!==matching.e) {
    return json({error:'JWKS_SIGNER_CONTINUITY_REQUIRED'},422);
  }
  const previous=await env.OWNER_DB.prepare(
    'SELECT retrieved_at FROM keirin_trusted_oidc_keys WHERE slot=1'
  ).first();
  if(previous && Date.parse(previous.retrieved_at)>Date.parse(data.retrieved_at)){
    return json({error:'JWKS_REFRESH_TIME_REGRESSION'},409);
  }
  await env.OWNER_DB.prepare(
    'INSERT INTO keirin_trusted_oidc_keys '+
    '(slot,jwks_json,source_sha256,retrieved_at,stored_at) VALUES (1,?,?,?,?) '+
    'ON CONFLICT(slot) DO UPDATE SET jwks_json=excluded.jwks_json, '+
    'source_sha256=excluded.source_sha256, '+
    'retrieved_at=excluded.retrieved_at, stored_at=excluded.stored_at'
  ).bind(JSON.stringify(data.keys),data.source_sha256,
    data.retrieved_at,new Date().toISOString()).run();
  const check=await env.OWNER_DB.prepare(
    'SELECT retrieved_at,source_sha256 FROM keirin_trusted_oidc_keys WHERE slot=1'
  ).first();
  if(!check || check.source_sha256!==data.source_sha256 ||
     check.retrieved_at!==data.retrieved_at) {
    return json({error:'JWKS_REFRESH_READBACK_FAILED'},503);
  }
  jwkCache={loadedAt:0,keys:[]};
  return json({
    schema:'RACE_AI_GITHUB_OIDC_JWKS_REFRESH_ACK_V1',
    key_count:data.keys.length,source_sha256:data.source_sha256,
    retrieved_at:data.retrieved_at,
    authenticated_update:true,private_forecast_data_returned:false
  });
}
async function verifyGithub(request,env) {
  const header=request.headers.get('authorization')||'';
  if(!/^Bearer [A-Za-z0-9_.-]+$/.test(header) || header.length>10000) {
    return false;
  }
  const token=header.slice(7);
  const segments=token.split('.');
  if(segments.length!==3) return false;
  let h,p;
  try {
    h=utf8Json(segments[0]);
    p=utf8Json(segments[1]);
  } catch{return false;}
  if(h.alg!=='RS256' || typeof h.kid!=='string' ||
     p.iss!==ISS || p.aud!==AUD || p.repository!==OWNER_REPO ||
     String(p.repository_id)!==REPO_ID ||
     p.ref!=='refs/heads/main' || !ALLOWED_EVENT.has(p.event_name) ||
     p.workflow_ref!==WFREF) return false;
  // The signer is GitHub; branch/event/immutable repo identity must agree.
  const now=Math.floor(Date.now()/1000);
  if(!Number.isInteger(p.iat) || !Number.isInteger(p.nbf) ||
     !Number.isInteger(p.exp) ||
     p.iat>now+30 || p.nbf>now+30 || p.exp<now-30 ||
     p.exp-p.iat>1200 || p.exp<=p.iat || p.iat<now-1200) {
    return false;
  }
  if(typeof p.sub!=='string' || !p.sub.includes(':ref:refs/heads/main')) {
    return false;
  }
  const all=await keys(env);
  const jwk=all.find(k=>k.kid===h.kid && k.kty==='RSA' &&
                     (!k.alg || k.alg==='RS256') &&
                     (!k.use || k.use==='sig'));
  if(!jwk) return false;
  try {
    const publicKey=await crypto.subtle.importKey('jwk',jwk,
        {name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
    const signed=new TextEncoder().encode(segments[0]+'.'+segments[1]);
    return await crypto.subtle.verify(
        'RSASSA-PKCS1-v1_5',publicKey,base64Url(segments[2]),signed);
  } catch {return false;}
}
function validDay(value) {
  if(typeof value!=='string' || !DAY_ID.test(value)) return false;
  const d=new Date(value+'T00:00:00Z');
  return Number.isFinite(d.getTime()) && d.toISOString().slice(0,10)===value;
}
function validRace(r,day) {
  return r && typeof r==='object' &&
         Object.keys(r).sort().join(',')==='race_id,race_no,venue_code' &&
         typeof r.race_id==='string' && RACE.test(r.race_id) &&
         Number.isInteger(r.venue_code) && r.venue_code>=1 && r.venue_code<=99 &&
         Number.isInteger(r.race_no) && r.race_no>=1 && r.race_no<=12 &&
         r.race_id===day.replace(/-/g,'')+
           String(r.venue_code).padStart(2,'0')+
           String(r.race_no).padStart(2,'0');
}
async function readBody(request) {
  const declared=Number(request.headers.get('content-length')||0);
  if(declared>MAX_BODY) return null;
  const data=await request.text();
  if(data.length===0 || data.length>MAX_BODY) return null;
  try{return JSON.parse(data);}catch{return null;}
}
async function postCohort(request,env) {
  const data=await readBody(request);
  if(!data || typeof data!=='object' ||
      Object.keys(data).sort().join(',')!==
        'event_date_jst,races,schema,source_sha256' ||
      data.schema!=='RACE_AI_KEIRIN_PRIVATE_COHORT_SYNC_V1' ||
      !validDay(data.event_date_jst) ||
      !SHA.test(data.source_sha256) ||
      !Array.isArray(data.races) ||
      data.races.length<1 || data.races.length>200) {
    return json({error:'INVALID_COHORT_INPUT'},422);
  }
  const seen=new Set();
  for(const r of data.races) {
    if(!validRace(r,data.event_date_jst) || seen.has(r.race_id)) {
      return json({error:'RACE_IDENTITY_MISMATCH'},422);
    }
    seen.add(r.race_id);
  }
  const obs=new Date().toISOString();
  const prepared=data.races.map(r=>env.OWNER_DB.prepare(
     'INSERT OR IGNORE INTO keirin_cohort '+
     '(race_id,event_day,venue_code,race_no,source_sha256,observed_at) '+
     'VALUES (?,?,?,?,?,?)').bind(
       r.race_id,data.event_date_jst,r.venue_code,r.race_no,
       data.source_sha256,obs));
  const inserted=await env.OWNER_DB.batch(prepared);
  if(!Array.isArray(inserted)||!inserted.every(r=>r.success)) {
    return json({error:'PRIVATE_DB_BATCH_FAILED'},503);
  }
  const readback=await env.OWNER_DB.prepare(
    'SELECT COUNT(*) AS n FROM keirin_cohort WHERE event_day=?')
    .bind(data.event_date_jst).first();
  return json({schema:'RACE_AI_KEIRIN_PRIVATE_COHORT_ACK_V1',
               event_date_jst:data.event_date_jst,
               submitted_races: data.races.length,
               saved_races_for_day:readback?.n??null,
               private_forecasts_exposed:false,
               official_coverage_attested:false,
               formal_hit_at_8_all:null});
}
async function getStatus(request,env) {
  const u=new URL(request.url);
  const day=u.searchParams.get('day');
  if(!validDay(day)||[...u.searchParams].length!==1){
    return json({error:'DAY_REQUIRED'},422);
  }
  const row=await env.OWNER_DB.prepare(
      'SELECT COUNT(*) AS n,'+
      "SUM(CASE WHEN prediction_status='MISSING_UNVERIFIED' THEN 1 ELSE 0 END) AS missing "+
      'FROM keirin_cohort WHERE event_day=?'
  ).bind(day).first();
  return json({schema:'RACE_AI_KEIRIN_PRIVATE_STATUS_V1',
               day,races:row?.n||0,missing_forecasts:row?.missing||0,
               formal_hit_at_8_all:null,
               private_raw_forecasts_returned:false});
}
export default {
  async fetch(request, env) {
    const u=new URL(request.url);
    if(u.pathname==='/health'&&request.method==='GET') {
      return json({service:'RACE_AI_KEIRIN_PRIVATE_STATE_V1',
                   state:'HEALTHY_AUTH_REQUIRED_FOR_DATA'});
    }
    if(!['/v1/cohort','/v1/status','/v1/jwks-refresh'].includes(u.pathname)) {
      return json({error:'NOT_FOUND'},404);
    }
    let trusted=false;
    try {trusted=await verifyGithub(request,env);} catch {
      return json({error:'AUTH_SOURCE_UNAVAILABLE'},503);
    }
    if(!trusted) return json({error:'UNAUTHORIZED'},401);
    if(!env.OWNER_DB) return json({error:'DATABASE_UNBOUND'},503);
    try {
      if(u.pathname==='/v1/jwks-refresh'&&request.method==='POST')
        return await postJwksRefresh(request,env);
      if(u.pathname==='/v1/cohort'&&request.method==='POST')
        return await postCohort(request,env);
      if(u.pathname==='/v1/status'&&request.method==='GET')
        return await getStatus(request,env);
      return json({error:'METHOD_NOT_ALLOWED'},405);
    } catch {
      // Never return private data, provider bytes or token inspection detail.
      return json({error:'PRIVATE_STORAGE_UNAVAILABLE'},503);
    }
  }
};

export { validDay, validRace, trustedJwks, keyAgeValid };
