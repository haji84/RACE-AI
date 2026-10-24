import test from "node:test";
import assert from "node:assert/strict";
import {runAuthorizedMinute} from "../workers/odds_auto_source_cron.mjs";
import {payloadGuard} from "../workers/odds_feed_worker.mjs";

function feed(){
 const tickets=[];
 for(let a=1;a<=6;a++)for(let b=1;b<=6;b++)for(let c=1;c<=6;c++)
   if(a!==b&&a!==c&&b!==c)tickets.push({ticket:[a,b,c],status:"QUOTED",decimal_odds:17});
 return {schema:"RACE_AI_FULL_TRIFECTA_ODDS_V1",source_status:"PROVIDER_REPORTED_UNVERIFIED",
 sport:"boat",race_id:"20300115-01-01",venue:"架空",race_no:1,
 event_date_jst:"2030-01-15",cutoff_at:"2030-01-15T10:30:00+09:00",
 source_url:"https://example.com/fictional-official",source_published_at:"2030-01-15T09:45:00+09:00",
 ingested_at:"2030-01-15T09:45:00+09:00",sales_status:"OPEN_REPORTED",
 participants:[1,2,3,4,5,6],odds:tickets};
}
class FakeD1{
 constructor(){this.calls=[],this.attempts=[],this.quota=0;this.latest=null;}
 prepare(sql){
   const owner=this;
   return {bind(...args){
     return {
       async first(){
         if(sql.includes("INSERT INTO odds_auto_source_attempts")){
           const t=Date.parse(args[1]);
           if(owner.attempts.some(x=>x.race_id===args[0]&&
                (t-Date.parse(x.attempt_at)<60000||x.blocked_until&&Date.parse(x.blocked_until)>t)))
             return null;
           const id=owner.attempts.length+1;
           owner.attempts.push({id,race_id:args[0],attempt_at:args[1],status:"CLAIMED"});
           return {id};
         }
         if(sql.includes("INSERT INTO odds_ingest_quota")){
           if(owner.quota>=args[1])return null;
           return {attempts_used:++owner.quota};
         }
         if(sql.startsWith("SELECT payload_json"))return owner.latest;
         return null;
       },
       async run(){
         if(sql.startsWith("UPDATE odds_auto_source_attempts")){
           const last=owner.attempts.find(x=>x.id===args[9]);
           assert.ok(last,"receipt update must identify the claimed attempt");
           Object.assign(last,{status:args[0],finished_at:args[1],source_published_at:args[2],
             server_received_at:args[3],snapshot_sha256:args[4],quoted_count:args[5],
             changed_count:args[6],http_status:args[7],blocked_until:args[8]});
         }else if(sql.includes("INSERT INTO odds_latest")){
           owner.latest={payload_json:args[1],sha256:args[3]};
         }else throw Error("Unexpected SQL: "+sql);
         return {success:true};
       }
     };
   }};
 }
}
const hash=async text=>"1".repeat(64);
const base={
 ODDS_AUTO_SOURCE_ENABLED:"true",ODDS_REQUIRE_ACCESS:"true",
 ODDS_PREVIEW_INGEST_ENABLED:"true",ODDS_AUTO_SOURCE_RIGHTS_REVIEWED:"true",
 ODDS_APPROVED_RIGHTS_REF:"synthetic-only-authority",
 ODDS_PILOT_RACE_ID:"20300115-01-01",ODDS_PILOT_MAX_UPDATES_PER_DAY:"3",
 ODDS_AUTO_SOURCE_FEED_URL:"https://feed.example.com/pilot.json",
 ODDS_AUTO_SOURCE_HOST:"feed.example.com",
 ODDS_AUTO_SOURCE_PAGE_URL:"https://example.com/fictional-official",
 ODDS_PILOT_CUTOFF_AT:"2030-01-15T10:30:00+09:00"
};
function options(db,now,data=feed()){
 return {at:new Date(now),validate:payloadGuard,hash,
  fetcher:async()=>new Response(JSON.stringify(data),
   {status:200,headers:{"Content-Type":"application/json"}})};
}
test("zero-default and rights guards forbid any network or D1 writes",async()=>{
 let touched=0;const fetcher=async()=>{touched++;throw Error("unexpected source request");};
 const a=await runAuthorizedMinute({ODDS_AUTO_SOURCE_ENABLED:"false"},
   {fetcher,validate:payloadGuard,hash});
 assert.equal(a.status,"DISABLED_NO_SOURCE_TRAFFIC");assert.equal(touched,0);
 const b=await runAuthorizedMinute({...base,ODDS_DB:new FakeD1(),ODDS_AUTO_SOURCE_RIGHTS_REVIEWED:"false"},
   {fetcher,validate:payloadGuard,hash});
 assert.equal(b.status,"DENIED_MISSING_APPROVAL_OR_GUARD");assert.equal(touched,0);
});
test("60s sustained single-race snapshots are measurable but not real provider proof",async()=>{
 const db=new FakeD1(),env={...base,ODDS_DB:db};
 const clock=["2030-01-15T00:50:00Z","2030-01-15T00:51:01Z","2030-01-15T00:52:02Z"];
 const results=[];
 for(let i=0;i<clock.length;i++){
   const data=feed();data.source_published_at=new Date(Date.parse(clock[i])-6000).toISOString();
   data.odds[0].decimal_odds=17+i;
   results.push(await runAuthorizedMinute(env,options(db,clock[i],data)));
 }
 assert.deepEqual(results.map(x=>x.status),Array(3).fill("D1_SAVED_SHA_VERIFIED"));
 assert.equal(db.quota,3);assert.equal(db.attempts.length,3);
 assert.equal(db.attempts[0].changed_count,120);
 assert.equal(db.attempts[1].changed_count,1);
 assert.equal(db.attempts[2].changed_count,1);
 assert.ok(db.attempts.every(x=>x.quoted_count===120&&x.snapshot_sha256));
 const limited=await runAuthorizedMinute(env,options(db,"2030-01-15T00:53:03Z"));
 assert.equal(limited.status,"DAILY_QUOTA_EXHAUSTED");
});
test("identical prices/published time preserve latest D1 entry but retain receipt",async()=>{
 const db=new FakeD1(),env={...base,ODDS_DB:db};
 const first=feed();first.source_published_at="2030-01-15T00:49:00Z";
 assert.equal((await runAuthorizedMinute(env,options(db,"2030-01-15T00:50:00Z",first))).status,"D1_SAVED_SHA_VERIFIED");
 const prev=db.latest.payload_json;
 assert.equal((await runAuthorizedMinute(env,options(db,"2030-01-15T00:51:01Z",first))).status,"SOURCE_UNCHANGED");
 assert.equal(db.latest.payload_json,prev);assert.equal(db.quota,2);
});
test("403/429 stops same race and no backoff circumvention",async()=>{
 const db=new FakeD1(),env={...base,ODDS_DB:db};let calls=0;
 const rejected=await runAuthorizedMinute(env,{
   at:new Date("2030-01-15T00:50:00Z"),validate:payloadGuard,hash,
   fetcher:async()=>{calls++;return new Response("rate limit",{status:429});}});
 assert.equal(rejected.status,"PROVIDER_DENIED_OR_RATE_LIMITED");
 const stopped=await runAuthorizedMinute(env,{
   at:new Date("2030-01-15T00:51:01Z"),validate:payloadGuard,hash,
   fetcher:async()=>{calls++;throw Error("must not run");}});
 assert.equal(stopped.status,"COOLDOWN_OR_BACKOFF");
 assert.equal(calls,1);assert.equal(db.quota,1);
});
test("T-60 and HTTPS exact-host gate do not call provider",async()=>{
 const db=new FakeD1();let calls=0;const fetcher=async()=>{calls++;throw Error("not authorized");};
 assert.equal((await runAuthorizedMinute({...base,ODDS_DB:db},{
   at:new Date("2030-01-15T00:20:00Z"),validate:payloadGuard,hash,fetcher})).status,
   "OUTSIDE_T_MINUS_60_WINDOW");
 assert.equal((await runAuthorizedMinute({...base,ODDS_DB:db,ODDS_AUTO_SOURCE_FEED_URL:"http://feed.example.com/pilot.json"},{
   at:new Date("2030-01-15T00:50:00Z"),validate:payloadGuard,hash,fetcher})).status,
   "DENIED_SOURCE_URL");
 assert.equal(calls,0);
});
