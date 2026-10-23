import { PREVIEW_ASSETS } from "./odds_preview_assets.mjs";
/** Cloudflare preview-only, same-origin odds delivery. No provider scraping.
 *
 * The ingestion endpoint accepts only a separately vetted, fully normalized
 * all-combinations JSON after an external review of collection/storage/display
 * rights. All toggles default closed; this code is NOT deployed by the repo.
 * Never shares quotes with the forecast engine or stores betting activity.
 */
const KEY_RE=/^[A-Za-z0-9:_-]{5,160}$/;
const URL_RE=/^\/data\/odds\/([A-Za-z0-9:_-]{5,160})\.json$/;

function reply(value,status=200){
  return new Response(typeof value==="string"?value:JSON.stringify(value),{
    status,headers:{"Content-Type":"application/json; charset=utf-8",
      "Cache-Control":"no-store, max-age=0","X-Content-Type-Options":"nosniff",
      "X-Frame-Options":"DENY","Referrer-Policy":"no-referrer"}
  });
}
function deny(reason,status=503){return reply({status:"DISABLED",reason},status);}
function validTime(value){return typeof value==="string"&&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)&&
  Number.isFinite(Date.parse(value));}
function payloadGuard(v){
  if(!v||v.schema!=="RACE_AI_FULL_TRIFECTA_ODDS_V1"||
    v.source_status!=="PROVIDER_REPORTED_UNVERIFIED"||
    !KEY_RE.test(v.race_id||"")||!["boat","keirin","autorace","horse"].includes(v.sport)||
    !Number.isInteger(v.race_no)||v.race_no<1||v.race_no>99||
    typeof v.venue!=="string"||!v.venue||v.venue.length>120||
    !/^\d{4}-\d\d-\d\d$/.test(v.event_date_jst||"")||
    typeof v.source_url!=="string"||!v.source_url.startsWith("https://")||
    !["OPEN_REPORTED","CLOSED_REPORTED","UNKNOWN"].includes(v.sales_status)||
    !validTime(v.cutoff_at)||!validTime(v.ingested_at)||
    (v.source_published_at!==null&&
      (!validTime(v.source_published_at)||Date.parse(v.source_published_at)>Date.parse(v.ingested_at)))||
    !Array.isArray(v.participants)||v.participants.length<3||v.participants.length>18||
    !Array.isArray(v.odds)||v.odds.length!==v.participants.length*(v.participants.length-1)*(v.participants.length-2)||
    "prediction" in v||"result" in v||"market_model_features" in v)
    throw new Error("PROVIDER_FEED_SCHEMA_NOT_ADMITTED");
  const cutoffDay=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Tokyo",year:"numeric",
    month:"2-digit",day:"2-digit"}).formatToParts(new Date(v.cutoff_at));
  const part=name=>cutoffDay.find(x=>x.type===name)?.value;
  if(v.event_date_jst!==part("year")+"-"+part("month")+"-"+part("day"))
    throw new Error("CUTOFF_DAY_MISMATCH");
  let source;
  try{source=new URL(v.source_url);}
  catch{throw new Error("PROVIDER_URL_INVALID");}
  if(source.protocol!=="https:"||!source.hostname||source.username||source.password)
    throw new Error("PROVIDER_URL_INVALID");
  if(v.sport==="boat"&&v.participants.length!==6)throw new Error("BOAT_PARTICIPANTS_INVALID");
  const numbers=new Set(v.participants);
  if(numbers.size!==v.participants.length||[...numbers].some(n=>!Number.isInteger(n)||n<1||n>99))
    throw new Error("PARTICIPANT_IDS_INVALID");
  const seen=new Set();
  for(const o of v.odds){
    if(!o||!Array.isArray(o.ticket)||o.ticket.length!==3||
       o.ticket.some(n=>!numbers.has(n))||new Set(o.ticket).size!==3)
      throw new Error("TRIFECTA_INVALID");
    const id=o.ticket.join("-");
    if(seen.has(id))throw new Error("DUPLICATE_TRIFECTA");
    seen.add(id);
    if(!["QUOTED","UNAVAILABLE"].includes(o.status)||
       (o.status==="QUOTED"&&
         (typeof o.decimal_odds!=="number"||!Number.isFinite(o.decimal_odds)||
          o.decimal_odds<1||o.decimal_odds>10000000))||
       (o.status==="UNAVAILABLE"&&o.decimal_odds!==null))
      throw new Error("ODDS_QUOTE_INVALID");
  }
}
async function sha(text){
  const bytes=new TextEncoder().encode(text);
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))]
    .map(x=>x.toString(16).padStart(2,"0")).join("");
}
async function accessAuthorized(ctx,env){
  // Never accept self-asserted headers. Cloudflare must have verified
  // Access and populated ctx.access before this Worker is called.
  if(env.ODDS_REQUIRE_ACCESS!=="true"||!ctx?.access||
     typeof ctx.access.getIdentity!=="function"||
     typeof env.ODDS_ALLOWED_EMAIL!=="string"||!env.ODDS_ALLOWED_EMAIL)
    return false;
  const identity=await ctx.access.getIdentity();
  return typeof identity?.email==="string"&&
    identity.email.toLowerCase()===env.ODDS_ALLOWED_EMAIL.toLowerCase();
}

async function fetchHandler(request,env){
  const u=new URL(request.url);
  if(request.method==="GET"&&Object.hasOwn(PREVIEW_ASSETS,u.pathname)){
    if(u.pathname!=="/full-odds.html"&&u.search)
      return deny("UNEXPECTED_ASSET_QUERY",404);
    const mime=u.pathname.endsWith(".html")?"text/html; charset=utf-8":
      u.pathname.endsWith(".css")?"text/css; charset=utf-8":
      "application/javascript; charset=utf-8";
    return new Response(PREVIEW_ASSETS[u.pathname],{
      status:200,
      headers:{"Content-Type":mime,"Cache-Control":"no-store, max-age=0",
        "X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY"}
    });
  }
  if(request.method==="GET"&&u.pathname==="/health"&&!u.search){
    if(env.ODDS_PREVIEW_READ_ENABLED!=="true"||!env.ODDS_DB)
      return deny("PREVIEW_ODDS_READ_NOT_APPROVED");
    const row=await env.ODDS_DB.prepare(
      "SELECT COUNT(*) AS records FROM odds_latest"
    ).first();
    const count=row?.records;
    if(!Number.isSafeInteger(count)||count<0)return deny("ODDS_DB_HEALTH_UNVERIFIED");
    return reply({
      schema:"RACE_AI_PRIVATE_ODDS_PREVIEW_HEALTH_V1",
      status:count===0?"EMPTY_WAITING_FOR_APPROVED_ODDS":"PRIVATE_ODDS_DATA_PRESENT",
      stored_races:count,
      owner_access_required:true,
      publisher_automatic_fetch_enabled:false,
      minute_by_minute_real_odds_verified:false,
      last_checked_at:new Date().toISOString()
    });
  }
  if(request.method==="GET"){
    const match=u.pathname.match(URL_RE);
    if(!match||u.search)return deny("UNKNOWN_ROUTE",404);
    if(env.ODDS_PREVIEW_READ_ENABLED!=="true"||!env.ODDS_DB)
      return deny("PREVIEW_ODDS_READ_NOT_APPROVED");
    const stored=await env.ODDS_DB.prepare(
      "SELECT payload_json FROM odds_latest WHERE race_id = ? LIMIT 1"
    ).bind(match[1]).first();
    if(!stored)return deny("NO_VERIFIED_FEED_FOR_RACE",404);
    const feed=JSON.parse(stored.payload_json);
    if(feed.race_id!==match[1])return deny("STORED_ODDS_IDENTITY_MISMATCH",500);
    return reply(feed);
  }
  if(request.method==="POST"&&u.pathname==="/internal/odds"){
    if(env.ODDS_PREVIEW_INGEST_ENABLED!=="true"||
       !env.ODDS_PREVIEW_TOKEN||!env.ODDS_DB||
       !env.ODDS_APPROVED_RIGHTS_REF)
      return deny("PUBLISHER_NOT_CONFIGURED");
    if(request.headers.get("Authorization")!=="Bearer "+env.ODDS_PREVIEW_TOKEN)
      return deny("AUTHORIZED_OPERATOR_REQUIRED",401);
    if(Number(request.headers.get("Content-Length")||0)>2_000_000)
      return deny("BODY_TOO_LARGE",413);
    let raw=await request.text();
    if(new TextEncoder().encode(raw).length>2_000_000)
      return deny("BODY_TOO_LARGE",413);
    let envelope;
    try{envelope=JSON.parse(raw);}catch{return deny("INVALID_JSON",400);}
    if(!envelope||Object.keys(envelope).sort().join(",")!=="feed,source_rights_review_ref"||
       envelope.source_rights_review_ref!==env.ODDS_APPROVED_RIGHTS_REF)
      return deny("RIGHTS_REVIEW_REFERENCE_NOT_MATCHED",403);
    const payload=envelope.feed;
    try{payloadGuard(payload);}catch(e){return deny(String(e.message),422);}
    // Do not trust a caller's receipt time. GitHub external freeze is independent.
    const received=new Date().toISOString();
    if(payload.source_published_at&&
       Date.parse(payload.source_published_at)>Date.parse(received))
      return deny("SOURCE_PUBLISHED_IN_FUTURE",422);
    const normalized={...payload,ingested_at:received};
    const bytes=JSON.stringify(normalized),fingerprint=await sha(bytes);
    const update=await env.ODDS_DB.prepare(
      "INSERT INTO odds_latest(race_id,payload_json,received_at,sha256) VALUES (?,?,?,?) "+
      "ON CONFLICT(race_id) DO UPDATE SET payload_json=excluded.payload_json, "+
      "received_at=excluded.received_at,sha256=excluded.sha256 "+
      "WHERE odds_latest.received_at < excluded.received_at"
    ).bind(payload.race_id,bytes,received,fingerprint).run();
    const saved=await env.ODDS_DB.prepare(
      "SELECT payload_json, sha256 FROM odds_latest WHERE race_id = ? LIMIT 1"
    ).bind(payload.race_id).first();
    if(!saved||saved.sha256!==fingerprint||saved.payload_json!==bytes)
      return deny("READBACK_HASH_MISMATCH",503);
    return reply({status:"PRIVATE_PREVIEW_STORED_NOT_PUBLICLY_DEPLOYED",
      race_id:payload.race_id,received_at:received,
      sha256:fingerprint,rows_written:update?.meta?.changes??null},201);
  }
  return deny("UNKNOWN_ROUTE",404);
}

export {payloadGuard,fetchHandler};
export default {
  async fetch(request,env,ctx){
    try{
      if(!(await accessAuthorized(ctx,env)))
        return deny("OWNER_ONLY_ACCESS_REQUIRED",403);
      return await fetchHandler(request,env);
    }catch{return deny("ACCESS_OR_ODDS_PREVIEW_UNAVAILABLE",503);}
  }
};
