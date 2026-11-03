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
async function keys() {
  const now=Date.now();
  if(jwkCache.keys.length && now-jwkCache.loadedAt<300000) {
    return jwkCache.keys;
  }
  const conf = await fetch(ISS + '/.well-known/openid-configuration',
      {redirect:'error',headers:{accept:'application/json'}});
  if(!conf.ok) throw new Error('OIDC_ISSUER_UNAVAILABLE');
  const config=await conf.json();
  if(config.issuer!==ISS || config.jwks_uri!==ISS+'/.well-known/jwks') {
    throw new Error('OIDC_METADATA_MISMATCH');
  }
  const res=await fetch(config.jwks_uri, {redirect:'error',
      headers:{accept:'application/json'}});
  if(!res.ok) throw new Error('OIDC_JWKS_UNAVAILABLE');
  const jwks=await res.json();
  if(!Array.isArray(jwks.keys)) throw new Error('OIDC_JWKS_MALFORMED');
  jwkCache={loadedAt:now, keys:jwks.keys.filter(k=>k.kty==='RSA')};
  return jwkCache.keys;
}
async function verifyGithub(request) {
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
  const all=await keys();
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
    if(!['/v1/cohort','/v1/status'].includes(u.pathname)) {
      return json({error:'NOT_FOUND'},404);
    }
    let trusted=false;
    try {trusted=await verifyGithub(request);} catch {
      return json({error:'AUTH_SOURCE_UNAVAILABLE'},503);
    }
    if(!trusted) return json({error:'UNAUTHORIZED'},401);
    if(!env.OWNER_DB) return json({error:'DATABASE_UNBOUND'},503);
    try {
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
