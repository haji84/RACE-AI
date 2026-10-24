"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const O=require("../web/full-odds-model.js");
const SOURCE="https://example.org/fictional-approved-source";
function fixture(sport,n){
 const numbers=Array.from({length:n},(_,i)=>i+1);
 const odds=O.allTickets(numbers).map((ticket,i)=>({
   ticket,decimal_odds:i%7===0?null:1+((i*7)%91)/10,
   status:i%7===0?"UNAVAILABLE":"QUOTED"
 }));
 return {schema:"RACE_AI_FULL_TRIFECTA_ODDS_V1",
   source_status:"SYNTHETIC_ONLY",sport,venue:"架空テスト競技場",race_no:3,
   race_id:sport+":2030-01-15:fictional:3",event_date_jst:"2030-01-15",
   cutoff_at:"2030-01-15T10:00:00+09:00",
   source_published_at:"2030-01-15T09:02:00+09:00",
   ingested_at:"2030-01-15T09:02:01+09:00",
   source_url:SOURCE,participants:numbers,sales_status:"OPEN_REPORTED",odds};
}
test("every valid trifecta, not only eight picks, for all four sports",()=>{
 for(const [sport,n] of [["boat",6],["keirin",7],["autorace",8],["horse",18]]){
   const f=O.parse(fixture(sport,n));
   assert.equal(f.odds.length,n*(n-1)*(n-2));
   assert.equal(O.select(f).length,f.odds.length);
   assert.equal(f.odds[0].decimal_odds,null);
 }
});
test("complete combinations are required even if quote unavailable",()=>{
 const missing=fixture("boat",6);
 missing.odds.pop();
 assert.throws(()=>O.parse(missing),/揃っていない/);
 const duplicate=fixture("boat",6);
 duplicate.odds[2].ticket=duplicate.odds[1].ticket;
 assert.throws(()=>O.parse(duplicate),/重複/);
 const unknown=fixture("boat",6);
 unknown.odds[2].ticket=[1,1,2];
 assert.throws(()=>O.parse(unknown),/不正な組合せ/);
});
test("missing quote must be explicitly null and cannot masquerade as price zero",()=>{
 const a=fixture("boat",6);
 a.odds[0].status="QUOTED";
 assert.throws(()=>O.parse(a),/オッズ値/);
 a.odds[0].decimal_odds=0;
 assert.throws(()=>O.parse(a),/オッズ値/);
 a.odds[0].status="UNAVAILABLE";a.odds[0].decimal_odds=12.3;
 assert.throws(()=>O.parse(a),/オッズ値/);
});
test("time ordering, cutoff day and source status cannot be forged as independently verified",()=>{
 const t=fixture("boat",6);
 t.source_published_at="2030-01-15T10:02:00+09:00";
 assert.throws(()=>O.parse(t),/受信時刻/);
 t.source_published_at="2030-01-15T09:02:00+09:00";
 t.source_status="INDEPENDENTLY_VERIFIED";
 assert.throws(()=>O.parse(t),/出典区分/);
 t.source_status="SYNTHETIC_ONLY";
 t.event_date_jst="2030-01-16";
 assert.throws(()=>O.parse(t),/開催日と締切/);
});
test("provider URL must be a valid HTTPS URL before it can appear as a source link",()=>{
 const broken=fixture("boat",6);
 broken.source_url="https://[]";
 assert.throws(()=>O.parse(broken),/出典URL/);
 broken.source_url="javascript:alert(1)";
 assert.throws(()=>O.parse(broken),/出典URL/);
 broken.source_url="https://user:password@example.org/a";
 assert.throws(()=>O.parse(broken),/出典URL/);
});
test("sort odds and filter first boat; unknown odds always sort last",()=>{
 const f=O.parse(fixture("boat",6));
 const first=O.select(f,{first:"2",order:"low"});
 assert.equal(first.length,5*4);
 assert.ok(first.every(x=>x.ticket[0]===2));
 assert.ok(first[first.length-1].status==="UNAVAILABLE");
 const most=O.select(f,{order:"high"});
 assert.ok(most[0].decimal_odds>=most[1].decimal_odds);
 const searched=O.select(f,{query:"1-2"});
 assert.equal(searched.length,4);
 assert.equal(O.select(f,{query:"<script>"}).length,0);
});
test("unknown official odds update time stays stale instead of inventing publish timestamp",()=>{
 const x=fixture("boat",6);x.source_published_at=null;
 const parsed=O.parse(x);
 assert.equal(parsed.source_published_at,null);
 const st=O.freshness(parsed,Date.parse("2030-01-15T09:02:40+09:00"));
 assert.equal(st.stale,true);
 assert.match(st.label,/更新時刻未確認/);
});
test("missing provider timestamp cannot be replaced by invalid text",()=>{
 const x=fixture("boat",6);x.source_published_at="unknown";
 assert.throws(()=>O.parse(x),/オッズ提供・受信時刻/);
});
test("provider-published timestamp can be stale even when site ingested it now",()=>{
 const t=fixture("boat",6);
 t.ingested_at="2030-01-15T09:04:59+09:00";
 const f=O.parse(t);
 const state=O.freshness(f,Date.parse("2030-01-15T09:05:00+09:00"));
 assert.equal(state.stale,true);
 assert.match(state.label,/提供元の更新遅延/);
});
test("read-only quote updates cannot alter frozen AI picks",()=>{
 const fixed=Object.freeze([[1,2,3],[1,3,2]]);
 const before=JSON.stringify(fixed);
 const newFeed=fixture("boat",6);
 const updated=fixture("boat",6);
 updated.odds[0].decimal_odds=99.8;
 updated.odds[0].status="QUOTED";
 assert.notDeepEqual(O.parse(newFeed).odds[0],O.parse(updated).odds[0]);
 assert.equal(JSON.stringify(fixed),before);
});
test("60-second update target still shows real age and never guarantees fresh data",()=>{
 const f=O.parse(fixture("boat",6));
 assert.equal(O.freshness(f,Date.parse("2030-01-15T09:02:25+09:00")).stale,false);
 assert.equal(O.freshness(f,Date.parse("2030-01-15T09:05:25+09:00")).stale,true);
 const closed=O.freshness(f,Date.parse("2030-01-15T10:00:01+09:00"));
 assert.equal(closed.stale,true);
 assert.match(closed.label,/締切後/);
});

test("mobile boat first display exposes all 120 tuples; larger sports stay paginated",()=>{
 assert.equal(O.initialRowLimit(O.parse(fixture("boat",6))),120);
 assert.equal(O.initialRowLimit(O.parse(fixture("horse",18))),80);
 const html=require("node:fs").readFileSync(require("node:path").resolve(__dirname,"../web/full-odds.html"),"utf8");
 assert.match(html,/id="refresh-evidence"/);
 assert.match(html,/id="refresh-history"/);
 assert.match(html,/id="copy-evidence"/);
});
test("client receipt, official-time and quote changes remain distinct",()=>{
 const a=O.parse(fixture("boat",6));
 assert.equal(O.readDifference(null,a).kind,"FIRST_READ");
 assert.deepEqual(O.readDifference(a,a),{kind:"UNCHANGED",changedQuotes:0});
 const receipt=fixture("boat",6);receipt.ingested_at="2030-01-15T09:02:25+09:00";
 assert.equal(O.readDifference(a,O.parse(receipt)).kind,"D1_RECEIPT_CHANGED");
 const published=fixture("boat",6);
 published.source_published_at="2030-01-15T09:02:30+09:00";
 published.ingested_at="2030-01-15T09:02:35+09:00";
 assert.equal(O.readDifference(a,O.parse(published)).kind,"SOURCE_TIME_CHANGED");
 const quote=fixture("boat",6);
 quote.odds[0].status="QUOTED";quote.odds[0].decimal_odds=15.2;
 assert.deepEqual(O.readDifference(a,O.parse(quote)),{kind:"QUOTE_CHANGED",changedQuotes:1});
});

test("Safari acceptance requires three ~60s automatic browser reads, not manual reads",()=>{
 const initial={ok:true,trigger:"initial",browser_at:"2030-01-15T00:00:00Z",gap_seconds:null};
 const auto=n=>({ok:true,trigger:"timer",browser_at:new Date(Date.parse(initial.browser_at)+n*60000).toISOString(),gap_seconds:60});
 assert.deepEqual(O.safariAcceptance([initial,auto(1),auto(2)]),{confirmedIntervals:2,passed:false});
 assert.deepEqual(O.safariAcceptance([initial,auto(1),auto(2),auto(3)]),{confirmedIntervals:3,passed:true});
 assert.equal(O.safariAcceptance([initial,{...auto(1),trigger:"manual"},auto(2)]).passed,false);
 assert.equal(O.safariAcceptance([initial,{...auto(1),gap_seconds:350},auto(2)]).passed,false);
 assert.equal(O.safariAcceptance([initial,auto(1),{ok:false,trigger:"timer"},auto(3)]).passed,false);
});
test("Safari receipt UI includes visible progress, fallback selection and no odds export",()=>{
 const fs=require("node:fs"),p=require("node:path");
 const html=fs.readFileSync(p.resolve(__dirname,"../web/full-odds.html"),"utf8");
 const js=fs.readFileSync(p.resolve(__dirname,"../web/full-odds.js"),"utf8");
 for(const id of ["refresh-progress","refresh-next","select-evidence","evidence-text","copy-status"])
   assert.ok(html.includes('id="'+id+'"'),"missing "+id);
 assert.ok(js.includes("document.execCommand"));
 assert.ok(js.includes('refresh("timer")'));
 assert.ok(js.includes("RACE_AI_SAFARI_READ_RECEIPTS_V2"));
 assert.ok(!js.includes("odds:state.feed?.odds"));
});

// Exercise the shipped UI at its DOM/network boundaries; no provider or
// Cloudflare calls are made. Removing event race identity must break linkage
// to the independent audit contract, even when the screen reports 3/3 reads.
const RECEIPT_RACE="20300115-01-03";
const RECEIPT_START=Date.parse("2030-01-15T00:40:00Z");
async function receiptBrowser({initialStatus=200,holdInitialRead=false}={}){
 const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
 let clock=RECEIPT_START,copied,upcoming,generated=0,firstRequest=true,releaseInitial;
 const initialRead=holdInitialRead?new Promise(resolve=>{releaseInitial=resolve;}):null;
 const elements=new Map(),timers=[];
 const element=id=>{
   if(!elements.has(id))elements.set(id,{
     value:"all",hidden:false,textContent:"",listeners:{},
     classList:{toggle(){},add(){}},replaceChildren(){},append(){},
     focus(){},select(){},setSelectionRange(){},
     addEventListener(name,handler){this.listeners[name]=handler;}
   });
   return elements.get(id);
 };
 class BrowserDate extends Date{
   constructor(...args){super(...(args.length?args:[clock]));}
   static now(){return clock;}
 }
 function currentFeed(){
   const feed=fixture("boat",6);
   return {...feed,race_id:RECEIPT_RACE,
     cutoff_at:"2030-01-15T01:30:00Z",
     source_published_at:new Date(clock-10000).toISOString(),
     ingested_at:new Date(clock-1000).toISOString(),
     odds:feed.odds.map((quote,index)=>({...quote,status:"QUOTED",decimal_odds:10+index/10}))};
 }
 upcoming={status:initialStatus,feed:currentFeed()};
 const context={RaceFullOdds:O,URL,URLSearchParams,Intl,Date:BrowserDate,
   location:{search:"?race_id="+RECEIPT_RACE,origin:"https://preview.invalid"},
   document:{hidden:false,getElementById:element,
     createElement:()=>element("generated-"+generated++),addEventListener(){}},
   window:{addEventListener(){}},
   navigator:{clipboard:{writeText:async text=>{copied=text;}}},
   setInterval(handler,delay){timers.push({handler,delay});},
   fetch:async(url,options)=>{
     assert.equal(url,"./data/odds/"+RECEIPT_RACE+".json");
     assert.equal(options.credentials,"same-origin");
     const response=upcoming,wait=firstRequest?initialRead:null;firstRequest=false;
     return {ok:response.status===200,status:response.status,redirected:false,
       headers:{get:()=>"application/json"},json:async()=>{if(wait)await wait;return response.feed;}};
   }
 };
 vm.createContext(context);
 vm.runInContext(fs.readFileSync(path.resolve(__dirname,"../web/full-odds.js"),"utf8"),context);
 const settle=()=>new Promise(resolve=>setImmediate(resolve));
 await settle();
 return {
   changePageUrl(race){context.location.search="?race_id="+race;},
   async releaseInitialRead(){releaseInitial();await settle();},
   async minute({status=200,race=RECEIPT_RACE}={}){
     clock+=60000;upcoming={status,feed:{...currentFeed(),race_id:race}};
     timers.find(x=>x.delay===60000).handler();await settle();
   },
   async diagnostic(){
     await element("copy-evidence").listeners.click();
     return JSON.parse(copied);
   }
 };
}
function syntheticCycleAudit(receipts){
 const hash="b".repeat(64);
 return {schema:"RACE_AI_ODDS_THREE_CYCLE_AUDIT_V1",race_id:RECEIPT_RACE,
   cutoff_at:"2030-01-15T01:30:00Z",official_cutoff_verified:true,
   rights_confirmed:true,rights_evidence_ref:"synthetic-contract-only",
   shared_free_quota_verified:true,safari_receipts:receipts,
   source_attempts:[1,2,3].map(minute=>{
     const clock=RECEIPT_START+minute*60000;
     return {race_id:RECEIPT_RACE,attempt_at:new Date(clock-2000).toISOString(),
       finished_at:new Date(clock-500).toISOString(),
       server_received_at:new Date(clock-1000).toISOString(),
       source_published_at:new Date(clock-10000).toISOString(),
       snapshot_sha256:hash,d1_readback_sha256:hash,
       quoted_count:120,ticket_count:120,status:"D1_SAVED_SHA_VERIFIED"};
   })};
}
test("copied UI receipts link three automatic reads to the same-race audit without rewriting",async()=>{
 const {auditThreeCycles}=await import("../race_ai/odds_three_cycle_audit.mjs");
 const browser=await receiptBrowser();
 for(let i=0;i<3;i++)await browser.minute();
 const diagnostic=await browser.diagnostic();
 assert.deepEqual(diagnostic.safari_auto_acceptance,{confirmedIntervals:3,passed:true});
 const verdict=auditThreeCycles(syntheticCycleAudit(diagnostic.events));
 assert.equal(verdict.status,"METADATA_CONTRACT_PASS_NEEDS_INDEPENDENT_ATTESTATION");
 assert.deepEqual(verdict.observed,{source_cycles:3,saved_cycles:3,browser_linked_cycles:3});
 assert.ok(diagnostic.events.every(event=>event.race_id===RECEIPT_RACE));
 // Exact allowlists prevent prices, source payloads or credentials escaping
 // through this metadata-only copy action.
 assert.deepEqual(Object.keys(diagnostic).sort(),[
   "schema","caveat","race_id","manual_file_mode","read_successes",
   "read_failures","received_rows","safari_auto_acceptance","events"
 ].sort());
 for(const event of diagnostic.events)assert.deepEqual(Object.keys(event).sort(),[
   "race_id","browser_at","trigger","ok","gap_seconds","change_kind",
   "changed_quotes","ingested_at","source_published_at"
 ].sort());
});
test("mixed-race, wrong-race or missing-race copied receipts cannot satisfy same-race D1 linkage",async()=>{
 const {auditThreeCycles}=await import("../race_ai/odds_three_cycle_audit.mjs");
 const browser=await receiptBrowser();
 for(let i=0;i<3;i++)await browser.minute();
 const receipts=(await browser.diagnostic()).events.filter(event=>event.trigger==="timer");
 for(const wrongIndexes of [[1],[0,1,2]]){
   const mixed=receipts.map((event,index)=>wrongIndexes.includes(index)?
     {...event,race_id:"20300115-02-03"}:event);
   const verdict=auditThreeCycles(syntheticCycleAudit(mixed));
   assert.equal(verdict.status,"HOLD");
   assert.equal(verdict.observed.browser_linked_cycles,3-wrongIndexes.length);
   assert.ok(verdict.blockers.includes("THREE_SAFARI_D1_LINKED_RECEIPTS_NOT_PROVEN"));
 }
 const missing=receipts.map(event=>({...event}));delete missing[1].race_id;
 const unknown=auditThreeCycles(syntheticCycleAudit(missing));
 assert.equal(unknown.status,"HOLD");
 assert.equal(unknown.observed.browser_linked_cycles,2);
 assert.ok(unknown.blockers.includes("THREE_SAFARI_D1_LINKED_RECEIPTS_NOT_PROVEN"));
});
test("an in-flight response keeps its original request race after the page URL changes",async()=>{
 const browser=await receiptBrowser({holdInitialRead:true});
 browser.changePageUrl("20300115-02-03");
 await browser.releaseInitialRead();
 const diagnostic=await browser.diagnostic();
 assert.equal(diagnostic.read_successes,1);
 assert.equal(diagnostic.events[0].ok,true);
 assert.equal(diagnostic.events[0].race_id,RECEIPT_RACE);
});
test("failed UI reads retain the requested race and never inherit stale feed receipt times",async()=>{
 const browser=await receiptBrowser();
 await browser.minute({race:"20300115-02-03"});
 const diagnostic=await browser.diagnostic();
 assert.equal(diagnostic.read_successes,1);
 assert.equal(diagnostic.read_failures,1);
 assert.equal(diagnostic.events[0].race_id,RECEIPT_RACE);
 const failed=diagnostic.events.at(-1);
 assert.equal(failed.ok,false);
 assert.equal(failed.race_id,RECEIPT_RACE);
 assert.equal(failed.ingested_at,null);
 assert.equal(failed.source_published_at,null);
 assert.equal(failed.changed_quotes,null);
 await browser.minute({race:null});
 const missingSource=(await browser.diagnostic()).events.at(-1);
 assert.equal(missingSource.ok,false);
 assert.equal(missingSource.race_id,RECEIPT_RACE);
 assert.equal(missingSource.ingested_at,null);
 assert.equal(missingSource.source_published_at,null);
 const denied=await receiptBrowser({initialStatus:403});
 const firstFailure=(await denied.diagnostic()).events[0];
 assert.equal(firstFailure.ok,false);
 assert.equal(firstFailure.race_id,RECEIPT_RACE);
 assert.equal(firstFailure.ingested_at,null);
});
test("owner-only embedded UI exactly matches the standalone browser assets",async()=>{
 const {PREVIEW_ASSETS}=await import("../workers/odds_preview_assets.mjs");
 const fs=require("node:fs"),path=require("node:path");
 for(const name of ["full-odds.html","full-odds.js","full-odds-model.js","full-odds.css"]){
   const source=fs.readFileSync(path.resolve(__dirname,"../web/"+name),"utf8").replace(/\r\n/g,"\n");
   assert.equal(PREVIEW_ASSETS["/"+name],source,"embedded asset drift: "+name);
 }
});
