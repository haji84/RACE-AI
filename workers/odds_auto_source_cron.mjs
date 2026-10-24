/** Disabled-by-default, single-race permissioned normalized JSON source trial.
 * No HTML scraping. No source rights are granted by environment flags.
 * Requires a separately reviewed provider agreement before deployment.
 * The scheduled event is internal; no HTTP endpoint or public publisher.
 */
const ID=/^[A-Za-z0-9:_-]{5,160}$/;
const MAX_BYTES=150_000;
const DAY=86400000;
function fail(code){throw new Error(code);}
function absolute(value){const n=Date.parse(value||"");return Number.isFinite(n)?n:null;}
async function boundedJson(res){
  if(!res||res.status!==200||!res.headers?.get("content-type")?.toLowerCase().startsWith("application/json"))
    fail("UPSTREAM_STATUS_OR_CONTENT_TYPE");
  const size=Number(res.headers.get("content-length"));
  if(Number.isFinite(size)&&size>MAX_BYTES)fail("UPSTREAM_BODY_TOO_LARGE");
  if(!res.body?.getReader)fail("UPSTREAM_BODY_STREAM_REQUIRED");
  const reader=res.body.getReader();let sizeRead=0;const chunks=[];
  for(;;){
    const {done,value}=await reader.read();
    if(done)break;
    sizeRead+=value.byteLength;
    if(sizeRead>MAX_BYTES){await reader.cancel();fail("UPSTREAM_BODY_TOO_LARGE");}
    chunks.push(value);
  }
  const bytes=new Uint8Array(sizeRead);let cursor=0;
  for(const part of chunks){bytes.set(part,cursor);cursor+=part.length;}
  try{return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));}
  catch{fail("UPSTREAM_JSON_INVALID");}
}
async function runAuthorizedMinute(env,{at=new Date(),completedClock=()=>new Date(),fetcher=fetch,validate,hash}={}){
  // Configuration is inactive until the user has authorized each outside
  // provider rights, rate, storage, display, account-budget and deployment gate.
  if(env?.ODDS_AUTO_SOURCE_ENABLED!=="true")
    return {status:"DISABLED_NO_SOURCE_TRAFFIC"};
  if(env.ODDS_REQUIRE_ACCESS!=="true"||env.ODDS_PREVIEW_INGEST_ENABLED!=="true"||
     env.ODDS_AUTO_SOURCE_RIGHTS_REVIEWED!=="true"||
     typeof env.ODDS_APPROVED_RIGHTS_REF!=="string"||
     env.ODDS_APPROVED_RIGHTS_REF.length<8||!env.ODDS_DB||
     typeof validate!=="function"||typeof hash!=="function")
    return {status:"DENIED_MISSING_APPROVAL_OR_GUARD"};
  const raceId=env.ODDS_PILOT_RACE_ID;
  const limit=Number(env.ODDS_PILOT_MAX_UPDATES_PER_DAY);
  if(!ID.test(raceId||"")||!Number.isSafeInteger(limit)||limit<1||limit>10)
    return {status:"DENIED_RACE_OR_QUOTA"};
  let uri;
  try{uri=new URL(env.ODDS_AUTO_SOURCE_FEED_URL);}
  catch{return {status:"DENIED_SOURCE_URL"};}
  if(uri.protocol!=="https:"||uri.hostname!==env.ODDS_AUTO_SOURCE_HOST||
     !uri.hostname.includes(".")||uri.username||uri.password||uri.port||
     uri.hash||uri.href!==env.ODDS_AUTO_SOURCE_FEED_URL||
     typeof env.ODDS_AUTO_SOURCE_PAGE_URL!=="string"||
     !env.ODDS_AUTO_SOURCE_PAGE_URL.startsWith("https://"))
    return {status:"DENIED_SOURCE_URL"};
  const now=at instanceof Date?at.getTime():NaN;
  const cutoff=absolute(env.ODDS_PILOT_CUTOFF_AT);
  if(!Number.isFinite(now)||cutoff===null)
    return {status:"DENIED_TIME_CONFIGURATION"};
  if(cutoff<=now||cutoff-now>3600000)
    return {status:"OUTSIDE_T_MINUS_60_WINDOW"};
  const issued=new Date(now).toISOString();
  const day=issued.slice(0,10);
  const db=env.ODDS_DB;
  // D1 insert is a durable per-race >=60s lease and blocks after a provider
  // refusal; it is not a new counter reset each Cron invocation.
  const claim=await db.prepare(
    "INSERT INTO odds_auto_source_attempts(race_id,attempt_at,status) "+
    "SELECT ?,?,'CLAIMED' WHERE NOT EXISTS ("+
    "SELECT 1 FROM odds_auto_source_attempts WHERE race_id=? "+
    "AND (julianday(attempt_at)>julianday(?) - 60.0/86400.0 "+
    "OR (blocked_until IS NOT NULL AND julianday(blocked_until)>julianday(?)))) "+
    "RETURNING id"
  ).bind(raceId,issued,raceId,issued,issued).first();
  if(!claim?.id)return {status:"COOLDOWN_OR_BACKOFF"};
  const finish=async(status,extras={})=>{
    await db.prepare(
      "UPDATE odds_auto_source_attempts SET status=?,finished_at=?, "+
      "source_published_at=?,server_received_at=?,snapshot_sha256=?, "+
      "quoted_count=?,changed_count=?,http_status=?,blocked_until=? WHERE id=?"
    ).bind(status,completedClock().toISOString(),extras.source_published_at??null,
      extras.server_received_at??null,extras.sha256??null,extras.quoted_count??null,
      extras.changed_count??null,extras.http_status??null,
      extras.blocked_until??null,claim.id).run();
    return {status,race_id:raceId,attempt_at:issued};
  };
  // This cap covers failed requests too, including cancelled responses.
  const counted=await db.prepare(
    "INSERT INTO odds_ingest_quota(utc_day,attempts_used) VALUES (?,1) "+
    "ON CONFLICT(utc_day) DO UPDATE SET attempts_used=attempts_used+1 "+
    "WHERE attempts_used < ? RETURNING attempts_used"
  ).bind(day,limit).first();
  if(!counted?.attempts_used)return finish("DAILY_QUOTA_EXHAUSTED");
  let response;
  try{
    response=await fetcher(uri.href,{method:"GET",redirect:"manual",
      headers:{"Accept":"application/json","Cache-Control":"no-store"}});
  }catch{return finish("PROVIDER_FETCH_FAILED",{blocked_until:env.ODDS_PILOT_CUTOFF_AT});}
  if(response.status===403||response.status===429)
    return finish("PROVIDER_DENIED_OR_RATE_LIMITED",{http_status:response.status,
      blocked_until:env.ODDS_PILOT_CUTOFF_AT});
  let raw;
  try{raw=await boundedJson(response);}
  catch{return finish("PROVIDER_INVALID_RESPONSE",{http_status:response.status,
    blocked_until:env.ODDS_PILOT_CUTOFF_AT});}
  const arrival=completedClock().toISOString();
  const feed={...raw,ingested_at:arrival};
  try{
    validate(feed);
    if(feed.sport!=="boat"||feed.race_id!==raceId||
       feed.source_url!==env.ODDS_AUTO_SOURCE_PAGE_URL||
       absolute(feed.cutoff_at)!==cutoff||
       feed.odds.length!==120||
       feed.source_published_at===null||
       absolute(feed.source_published_at)>Date.parse(arrival))fail("PROVIDER_IDENTITY_OR_TIME");
  }catch{return finish("PROVIDER_FEED_NOT_ADMITTED",{http_status:response.status,
    blocked_until:env.ODDS_PILOT_CUTOFF_AT});}
  const previous=await db.prepare(
    "SELECT payload_json,sha256 FROM odds_latest WHERE race_id=? LIMIT 1"
  ).bind(raceId).first();
  let changed=feed.odds.length;
  if(previous){
    const older=JSON.parse(previous.payload_json);
    const old=new Map(older.odds.map(q=>[q.ticket.join("-"),q.status+":"+q.decimal_odds]));
    changed=feed.odds.filter(q=>old.get(q.ticket.join("-"))!==q.status+":"+q.decimal_odds).length;
    if(changed===0&&older.source_published_at===feed.source_published_at)
      return finish("SOURCE_UNCHANGED",{http_status:200,quoted_count:feed.odds.filter(q=>q.status==="QUOTED").length,
        changed_count:0,source_published_at:feed.source_published_at,
        server_received_at:arrival,sha256:previous.sha256});
  }
  const json=JSON.stringify(feed),digest=await hash(json);
  if(!/^[0-9a-f]{64}$/.test(digest))fail("SHA_HASH_NOT_AVAILABLE");
  await db.prepare(
    "INSERT INTO odds_latest(race_id,payload_json,received_at,sha256) VALUES (?,?,?,?) "+
    "ON CONFLICT(race_id) DO UPDATE SET payload_json=excluded.payload_json,"+
    "received_at=excluded.received_at,sha256=excluded.sha256 "+
    "WHERE odds_latest.received_at < excluded.received_at"
  ).bind(raceId,json,arrival,digest).run();
  const verified=await db.prepare(
    "SELECT payload_json,sha256 FROM odds_latest WHERE race_id=? LIMIT 1"
  ).bind(raceId).first();
  if(verified?.sha256!==digest||verified?.payload_json!==json)
    return finish("D1_READBACK_MISMATCH",{blocked_until:env.ODDS_PILOT_CUTOFF_AT});
  return finish("D1_SAVED_SHA_VERIFIED",{http_status:200,
    quoted_count:feed.odds.filter(q=>q.status==="QUOTED").length,
    changed_count:changed,source_published_at:feed.source_published_at,
    server_received_at:arrival,sha256:digest});
}
export {runAuthorizedMinute};
