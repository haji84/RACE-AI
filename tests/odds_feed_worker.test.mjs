import test from "node:test";
import assert from "node:assert/strict";
import worker,{payloadGuard} from "../workers/odds_feed_worker.mjs";

function fixture(){
 const people=[1,2,3,4,5,6],odds=[];
 for(const a of people)for(const b of people)for(const c of people)
   if(a!==b&&a!==c&&b!==c)
     odds.push({ticket:[a,b,c],status:"QUOTED",decimal_odds:1.2+odds.length/10});
 return {schema:"RACE_AI_FULL_TRIFECTA_ODDS_V1",
   source_status:"PROVIDER_REPORTED_UNVERIFIED",
   race_id:"20300115-01-01",sport:"boat",venue:"fictional",
   race_no:1,event_date_jst:"2030-01-15",
   cutoff_at:"2030-01-15T10:00:00+09:00",
   source_published_at:null,ingested_at:"2030-01-15T09:00:00+09:00",
   source_url:"https://www.boatrace.jp/owpc/pc/race/odds3t?hd=20300115&jcd=01&rno=1",
   sales_status:"UNKNOWN",participants:people,odds};
}

class FakeD1{
 constructor(){this.rows=new Map();}
 prepare(sql){
   return {first:async()=>{if(sql.startsWith('SELECT COUNT(*)'))return {records:this.rows.size};throw Error('unexpected direct first');},bind:(...params)=>({
     first:async()=>{
       if(sql.startsWith("SELECT COUNT(*)"))return {records:this.rows.size};
       if(!sql.startsWith("SELECT"))throw Error("bad SQL mock SELECT");
       const row=this.rows.get(params[0]);
       return row&&{payload_json:row.payload_json,sha256:row.sha256};
     },
     run:async()=>{
       if(!sql.startsWith("INSERT"))throw Error("bad SQL mock INSERT");
       this.rows.set(params[0],{payload_json:params[1],received_at:params[2],
                               sha256:params[3]});
       return {meta:{changes:1}};
     }
   })};
 }
}
function env(db=new FakeD1()){
 return {ODDS_DB:db,ODDS_PREVIEW_READ_ENABLED:"true",
         ODDS_PREVIEW_INGEST_ENABLED:"true",
         ODDS_PREVIEW_TOKEN:"synthetic-fake-preview-token-32-characters",
         ODDS_APPROVED_RIGHTS_REF:"fictional-review-only",
         ODDS_REQUIRE_ACCESS:"true",ODDS_ALLOWED_EMAIL:"synthetic-owner@example.invalid"};
}
const ACCESS={access:{getIdentity:async()=>({email:"synthetic-owner@example.invalid"})}};
function post(feed,ref="fictional-review-only",token="synthetic-fake-preview-token-32-characters"){
 return new Request("https://preview.invalid/internal/odds",{
   method:"POST",headers:{"Content-Type":"application/json",
     "Authorization":"Bearer "+token},
   body:JSON.stringify({feed,source_rights_review_ref:ref})
 });
}
function read(race="20300115-01-01"){
 return new Request("https://preview.invalid/data/odds/"+race+".json");
}

test("preview Worker defaults closed, even for read-only fetch",async()=>{
 const result=await worker.fetch(read(),{},ACCESS);
 assert.equal(result.status,403);
 assert.equal((await result.json()).reason,"OWNER_ONLY_ACCESS_REQUIRED");
 const ownerButNotEnabled=await worker.fetch(read(),{
   ODDS_REQUIRE_ACCESS:"true",ODDS_ALLOWED_EMAIL:"synthetic-owner@example.invalid"
 },ACCESS);
 assert.equal(ownerButNotEnabled.status,503);
 assert.equal((await ownerButNotEnabled.json()).reason,"PREVIEW_ODDS_READ_NOT_APPROVED");
});

test("unprotected Worker, wrong identity and caller-supplied headers cannot read or write",async()=>{
 const e=env();
 const unauth=await worker.fetch(read(),e);
 assert.equal(unauth.status,403);
 assert.equal((await unauth.json()).reason,"OWNER_ONLY_ACCESS_REQUIRED");
 const fakeHeaders=new Request(read(),{headers:{"Cf-Access-Jwt-Assertion":"forged"}});
 assert.equal((await worker.fetch(fakeHeaders,e)).status,403);
 const wrong={access:{getIdentity:async()=>({email:"attacker@example.invalid"})}};
 assert.equal((await worker.fetch(post(fixture()),e,wrong)).status,403);
 assert.equal(e.ODDS_DB.rows.size,0);
 const fakeEnv=env();fakeEnv.ODDS_REQUIRE_ACCESS="false";
 assert.equal((await worker.fetch(read(),fakeEnv,ACCESS)).status,403);
});
test("private health proves D1 binding but reports zero real races when empty",async()=>{
 const e=env();
 const response=await worker.fetch(
   new Request("https://preview.invalid/health"),e,ACCESS);
 assert.equal(response.status,200);
 const payload=await response.json();
 assert.equal(payload.schema,"RACE_AI_PRIVATE_ODDS_PREVIEW_HEALTH_V1");
 assert.equal(payload.stored_races,0);
 assert.equal(payload.status,"EMPTY_WAITING_FOR_APPROVED_ODDS");
 assert.equal(payload.minute_by_minute_real_odds_verified,false);
 assert.equal(payload.owner_access_required,true);
 const unauth=await worker.fetch(
   new Request("https://preview.invalid/health"),e);
 assert.equal(unauth.status,403);
});
test("existing full-market iPhone viewer and CSS are served only to Access owner",async()=>{
 const e=env();
 const url="https://preview.invalid/full-odds.html?race_id=20300115-01-01";
 const anon=await worker.fetch(new Request(url),e);
 assert.equal(anon.status,403);
 const html=await worker.fetch(new Request(url),e,ACCESS);
 assert.equal(html.status,200);
 assert.match(html.headers.get("content-type"),/text\/html/);
 const markup=await html.text();
 assert.match(markup,/全3連単オッズ/);
 assert.match(markup,/full-odds-model\.js/);
 assert.match(markup,/full-odds\.js/);
 const model=await worker.fetch(new Request("https://preview.invalid/full-odds-model.js"),e,ACCESS);
 assert.equal(model.status,200);
 assert.match(await model.text(),/RACE_AI_FULL_TRIFECTA_ODDS_V1/);
 const css=await worker.fetch(new Request("https://preview.invalid/full-odds.css"),e,ACCESS);
 assert.equal(css.status,200);
 assert.match(css.headers.get("content-type"),/text\/css/);
 assert.equal((await worker.fetch(new Request("https://preview.invalid/full-odds.js?bad=1"),e,ACCESS)).status,404);
});
test("private source approval ref and secret must both match",async()=>{
 const e=env();
 const noRights=await worker.fetch(post(fixture(),"wrong"),e,ACCESS);
 assert.equal(noRights.status,403);
 const noToken=await worker.fetch(post(fixture(),"fictional-review-only","bad"),e,ACCESS);
 assert.equal(noToken.status,401);
 assert.equal(e.ODDS_DB.rows.size,0);
});

test("all 120 quotes stored and read back, no AI forecasts mutated",async()=>{
 const database=new FakeD1(),e=env(database),feed=fixture();
 const stored=await worker.fetch(post(feed),e,ACCESS);
 assert.equal(stored.status,201);
 const report=await stored.json();
 assert.equal(report.race_id,feed.race_id);
 assert.match(report.sha256,/^[a-f0-9]{64}$/);
 const res=await worker.fetch(read(),e,ACCESS);
 assert.equal(res.status,200);
 const view=await res.json();
 assert.equal(view.odds.length,120);
 assert.equal(view.source_published_at,null);
 assert.notEqual(view.ingested_at,feed.ingested_at);
 assert.equal(view.odds[4].ticket.join("-"),feed.odds[4].ticket.join("-"));
 assert.equal(Object.prototype.hasOwnProperty.call(view,"prediction"),false);
 assert.equal(Object.prototype.hasOwnProperty.call(view,"result"),false);
});

test("invalid quote corpus blocked before D1 write",async()=>{
 const e=env();
 const x=fixture();x.odds.pop();
 const res=await worker.fetch(post(x),e,ACCESS);
 assert.equal(res.status,422);
 assert.equal(e.ODDS_DB.rows.size,0);
 const y=fixture();y.odds[1].ticket=y.odds[0].ticket;
 assert.equal((await worker.fetch(post(y),e,ACCESS)).status,422);
});

test("price and provider time validity cannot be bypassed",async()=>{
 const x=fixture();x.odds[3].decimal_odds=0;
 assert.throws(()=>payloadGuard(x),/ODDS_QUOTE_INVALID/);
 const y=fixture();y.source_published_at="2030-01-15T09:20:00+09:00";
 y.ingested_at="2030-01-15T09:15:00+09:00";
 assert.throws(()=>payloadGuard(y),/PROVIDER_FEED_SCHEMA/);
});

test("worker will not accept guessed forecast or result data in odds envelope",()=>{
 const x=fixture();x.prediction={ordered_top8:[[1,2,3]]};
 assert.throws(()=>payloadGuard(x),/PROVIDER_FEED_SCHEMA/);
 const y=fixture();y.result={winning_combinations:[[1,2,3]]};
 assert.throws(()=>payloadGuard(y),/PROVIDER_FEED_SCHEMA/);
});
