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
