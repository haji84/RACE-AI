import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {claimResultPoll,resultChecked,rememberGate,runTick} from '../workers/boat_nonvercel_cron.mjs';

class RealSqliteD1 {
 constructor(){
  this.raw=new DatabaseSync(':memory:');
  this.raw.exec(readFileSync(new URL('../workers/boat_nonvercel_schema.sql',import.meta.url),'utf8'));
 }
 prepare(sql){
  const q=this.raw.prepare(sql);
  return {bind(...a){return {
   async first(){return q.get(...a)??null;},
   async run(){return q.run(...a);},
   async all(){return {results:q.all(...a)};}
  }}};
 }
 close(){this.raw.close();}
}
test('D1 migration builds all immutable forecast, outcome, stop-reason tables',()=>{
 const db=new RealSqliteD1();
 const names=db.raw.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(x=>x.name);
 for(const name of ['boat_exhibition_freezes','boat_exhibition_outcomes','boat_exhibition_shadow_freezes',
    'boat_exhibition_shadow_outcomes','boat_result_poll_state','boat_race_gate_reasons']){
  assert.ok(names.includes(name),name);
 }
 db.close();
});
test('atomic D1 result poll claim blocks immediate duplicate and persists safe retry',async()=>{
 const db=new RealSqliteD1(),rid='20301103-18-05';
 try{
  assert.equal(await claimResultPoll(db,rid),true);
  assert.equal(await claimResultPoll(db,rid),false);
  const row=db.raw.prepare('SELECT checks,next_check_at FROM boat_result_poll_state WHERE race_id=?').get(rid);
  assert.equal(row.checks,1);
  assert.ok(Date.parse(row.next_check_at)>Date.now());
  db.raw.prepare("UPDATE boat_result_poll_state SET next_check_at='2000-01-01T00:00:00Z' WHERE race_id=?").run(rid);
  assert.equal(await claimResultPoll(db,rid),true);
  assert.equal(db.raw.prepare('SELECT checks FROM boat_result_poll_state WHERE race_id=?').get(rid).checks,2);
  await resultChecked(db,rid,'f'.repeat(64));
  const verified=db.raw.prepare('SELECT next_check_at,last_verified_source_sha256 FROM boat_result_poll_state WHERE race_id=?').get(rid);
  assert.ok(Date.parse(verified.next_check_at)>Date.now()+5*60*60*1000);
  assert.equal(verified.last_verified_source_sha256,'f'.repeat(64));
  assert.equal(await claimResultPoll(db,rid),false);
 }finally{db.close();}
});
test('fail closed gate reasons are insert-only and deduplicated',async()=>{
 const db=new RealSqliteD1(),rid='20301103-18-05';
 try{
  await rememberGate(db,rid,'RESULT','OFFICIAL_RESULT_PENDING');
  await rememberGate(db,rid,'RESULT','OFFICIAL_RESULT_PENDING');
  await rememberGate(db,rid,'FORECAST','SOURCE_NOT_ADMITTED');
  const rows=db.raw.prepare('SELECT stage,reason FROM boat_race_gate_reasons WHERE race_id=? ORDER BY stage,reason').all(rid);
  assert.equal(rows.length,2);
  assert.throws(()=>db.raw.prepare('DELETE FROM boat_race_gate_reasons WHERE race_id=?').run(rid),/GATE_REASON_NOT_DELETABLE/);
 }finally{db.close();}
});
test('no Cron is activated by installing pure code, default remains off',async()=>{
 assert.deepEqual(await runTick({BOAT_AUTO_ENABLED:'false'}),{state:'DISABLED',calls:0});
});

test('end-to-end SQLite cycle: previous settled result becomes next-race shadow, primary never changes',async(t)=>{
 const {createHash}=await import('node:crypto');
 const {freeze,settle}=await import('../workers/boat_nonvercel_core.mjs');
 const {freezeChallenger}=await import('../workers/boat_pdca_shadow.mjs');
 const hash=s=>createHash('sha256').update(s).digest('hex');
 const day=(instant)=>{const f=Object.fromEntries(new Intl.DateTimeFormat('en-US',{
  timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'
 }).formatToParts(new Date(instant)).map(x=>[x.type,x.value]));
 return f.year+f.month+f.day;};
 const now=Date.now(),today=day(now),soon=now+10*60000;
 if(day(soon)!==today){t.skip('synthetic day boundary: avoid falsely crossing JST date');return;}
 const db=new RealSqliteD1();
 try{
  // 23 immutable *synthetic* earlier settled race reports.
  for(let i=0;i<23;i++){
   const x=Math.floor(i/12)+1;
   const d=new Date(now-x*86400000),id=day(d)+'-18-'+String(i%12+1).padStart(2,'0');
   const report={race_id:id,official_top3:[i%3+1,5,6],
     captured_at:new Date(d).toISOString(),source_sha256:hash(id)};
   const body=JSON.stringify(report);
   db.raw.prepare('INSERT INTO boat_exhibition_outcomes(race_id,result_sha256,report_json,report_sha256,db_saved_at) VALUES(?,?,?,?,?)')
    .run(id,report.source_sha256,body,hash(body),new Date(d.getTime()+60000).toISOString());
  }
  const oldRace=today+'-18-01',oldCutoff=new Date(now-12*60000).toISOString();
  const result={phase:'official_result',race_id:oldRace,
   source_url:'https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=18&hd='+today,
   source_sha256:'e'.repeat(64),result_state:'confirmed',refund_boats:[],dead_heat:false,
   top3:[1,3,5],captured_at:new Date(now-1000).toISOString(),payout_per_100_yen:2340};
  const first=await settle(db,{race_id:oldRace,cutoff_at:oldCutoff},result);
  assert.equal(first.hit8,0,'missing earlier forecast must count as zero');
  assert.equal(first.hypothetical_stake_yen,0);
  await new Promise(done=>setTimeout(done,30));
  const nextRace=today+'-18-02';
  const capturedAt=new Date().toISOString();
  const facts={schema:'RACE_AI_BOAT_OBSERVATION_V1',phase:'post_exhibition',
    race_id:nextRace,cutoff_at:new Date(soon).toISOString(),captured_at:capturedAt,
    source_url:'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=2&jcd=18&hd='+today,
    source_sha256:'a'.repeat(64),program_sha256:'b'.repeat(64),rights_verified:true,
    license_purpose:'private_analysis',racers:Array.from({length:6},(_,i)=>({
      lane:i+1,registration_no:String(4201+i),national_win_rate:5.4+i*.2,
      exhibition_time_seconds:6.75+i*.01
    }))};
  const primary=await freeze(db,facts);
  assert.equal(primary.status,'FROZEN_DB_READBACK_VERIFIED');
  assert.equal(primary.top8.length,8);
  const original=db.raw.prepare('SELECT body_json,payload_sha256 FROM boat_exhibition_freezes WHERE race_id=?').get(nextRace);
  const shadow=await freezeChallenger(db,facts);
  assert.equal(shadow.status,'PDCA_SHADOW_FROZEN_READBACK_VERIFIED');
  assert.equal(shadow.training_count,24);
  assert.equal(shadow.ordered_top8.length,8);
  const saved=db.raw.prepare('SELECT body_json,payload_sha256 FROM boat_exhibition_freezes WHERE race_id=?').get(nextRace);
  assert.deepEqual(saved,original,'primary was not replaced by shadow');
  const noAgain=await freezeChallenger(db,facts);
  assert.equal(noAgain.status,'PDCA_SHADOW_ALREADY_FROZEN');
  assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM boat_exhibition_shadow_freezes').get().n,1);
 }finally{db.close();}
});
