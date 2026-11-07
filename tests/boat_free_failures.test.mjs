import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {handleJob} from '../workers/boat_free_runtime.mjs';
test('failed official read records original reason and releases lease',async()=>{
 const raw=new DatabaseSync(':memory:');raw.exec(readFileSync(new URL('../workers/boat_free_state.sql',import.meta.url),'utf8'));
 const db={prepare(sql){const q=raw.prepare(sql);return {bind(...a){return {async first(){return q.get(...a)??null},async run(){return q.run(...a)}}}}}};
 const day=new Date(Date.now()+32400000).toISOString().slice(0,10).replaceAll('-',''),id=day+'-17-01',cut=Date.now()+600000;
 const cutoff=new Date(cut+32400000).toISOString().slice(0,-1)+'+09:00';
 raw.prepare('INSERT INTO live_races(race_id,day,venue,race_no,cutoff_at,cutoff_ms,schedule_sha) VALUES(?,?,?,?,?,?,?)').run(id,day,'17',1,cutoff,cut,'a'.repeat(64));
 const old=globalThis.fetch;globalThis.fetch=async()=>new Response('unavailable',{status:503});
 try{await assert.rejects(handleJob({BOAT_AUTO_ENABLED:'true',BOAT_DB:db},{kind:'RACE',race_id:id}),/OFFICIAL_HTTP_INVALID/);const saved=raw.prepare('SELECT lease_until,last_error FROM live_races WHERE race_id=?').get(id);assert.equal(saved.lease_until,0);assert.equal(saved.last_error,'OFFICIAL_HTTP_INVALID');assert.equal(raw.prepare('SELECT reason FROM live_events').get().reason,'OFFICIAL_HTTP_INVALID');}
 finally{globalThis.fetch=old;raw.close();}
});
