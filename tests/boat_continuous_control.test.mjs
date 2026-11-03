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
