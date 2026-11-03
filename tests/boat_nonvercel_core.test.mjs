
import test from 'node:test';
import assert from 'node:assert/strict';
import {assertFacts,predict,freeze,settle} from '../workers/boat_nonvercel_core.mjs';
const now=Date.parse('2030-11-03T10:15:00+09:00'),cutoff='2030-11-03T10:30:00+09:00';
const race='20301103-18-05',source='https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=5&jcd=18&hd=20301103';
const facts=()=>({schema:'RACE_AI_BOAT_OBSERVATION_V1',phase:'post_exhibition',race_id:race,cutoff_at:cutoff,
 captured_at:'2030-11-03T10:14:50+09:00',source_url:source,source_sha256:'a'.repeat(64),program_sha256:'c'.repeat(64),
 rights_verified:true,license_purpose:'private_analysis',racers:[1,2,3,4,5,6].map(lane=>({
 lane,registration_no:String(4200+lane),national_win_rate:5+lane*.2,exhibition_time_seconds:6.8+lane*.01}))});
const result=()=>({phase:'official_result',race_id:race,source_url:source.replace('/beforeinfo?','/raceresult?'),
 source_sha256:'b'.repeat(64),result_state:'confirmed',refund_boats:[],dead_heat:false,top3:[1,2,3],
 captured_at:'2030-11-03T10:35:00+09:00'});
class FakeD1{
 constructor(){this.frozen=null;this.results=new Map();}
 prepare(sql){const x=this;return{bind(...a){return{
  async first(){
   if(sql.includes('INSERT INTO boat_exhibition_freezes')){
    if(x.frozen)return null;
    x.frozen={race_id:a[0],model_id:a[1],source_sha256:a[2],cutoff_at:a[3],body_json:a[4],
     payload_sha256:a[5],db_stored_at:'2030-11-03T01:15:00.500Z'};return {db_stored_at:x.frozen.db_stored_at};
   }
   if(sql.includes('FROM boat_exhibition_freezes'))return x.frozen;
   if(sql.includes('FROM boat_exhibition_outcomes'))return x.results.get(a[0]+':'+a[1]);
   throw Error('Unexpected SELECT');
  },
  async run(){
   if(!sql.includes('INSERT INTO boat_exhibition_outcomes'))throw Error('Unexpected INSERT');
   const k=a[0]+':'+a[1];if(!x.results.has(k))x.results.set(k,{report_json:a[2],report_sha256:a[3],
    db_saved_at:'2030-11-03T01:35:01.500Z'});return{success:true};
  }
 };}};}
}
test('120 valid outcomes and 8 unique uncalibrated tickets',()=>{
 const out=predict(facts());assert.equal(out.all120.length,120);assert.equal(out.top8.length,8);
 assert.equal(new Set(out.all120.map(x=>x.ticket.join('-'))).size,120);
 assert.ok(Math.abs(out.all120.reduce((n,x)=>n+x.score,0)-1)<1e-10);
 assert.equal(out.calibrated,false);assert.equal(out.odds_used,false);
});
test('private D1 insert-only freeze/readback and result PDCA idempotent',async()=>{
 const db=new FakeD1();const a=await freeze(db,facts(),{now:()=>now});
 assert.equal(a.status,'FROZEN_DB_READBACK_VERIFIED');assert.equal(a.top8.length,8);
 const b=await freeze(db,facts(),{now:()=>now+1000});
 assert.equal(b.status,'ALREADY_FROZEN_DO_NOT_REPOST');
 const c=await settle(db,facts(),result(),{now:()=>now+20*60000});
 assert.equal(c.status,'RESULT_PDCA_DB_VERIFIED');
 assert.equal(c.hit8,Number(predict(facts()).top8.some(x=>x.join('-')==='1-2-3')));
 const d=await settle(db,facts(),result(),{now:()=>now+20*60000});
 assert.equal(db.results.size,1);assert.equal(c.report_sha256,d.report_sha256);
});
test('missing forecast stays a miss, never backfilled after finish',async()=>{
 const db=new FakeD1();const r=await settle(db,facts(),result(),{now:()=>now+20*60000});
 assert.equal(r.hit1,0);assert.equal(r.hit8,0);assert.equal(r.freeze_sha256,null);
});
test('wrong race, missing exhibition, rights and late time are refused',async()=>{
 for(const mutate of [x=>x.race_id='20301103-17-05',
  x=>x.source_url=source.replace('jcd=18','jcd=17'),x=>x.racers[0].exhibition_time_seconds=null,
  x=>x.rights_verified=false,x=>x.captured_at='2030-11-03T10:31:00+09:00']){
  const f=facts();mutate(f);assert.throws(()=>assertFacts(f,now));
 }
 await assert.rejects(()=>freeze(new FakeD1(),facts(),{now:()=>Date.parse(cutoff)-1000}));
 const altered=result();altered.source_url=source;
 await assert.rejects(()=>settle(new FakeD1(),facts(),altered,{now:()=>now+20*60000}));
});

test('actual payout is only admitted after result and never improves historical predictor',async()=>{
 const db=new FakeD1();const f=facts();const baseline=predict(f);
 await freeze(db,f,{now:()=>now});
 const res=result();res.payout_per_100_yen=1280;
 const score=await settle(db,f,res,{now:()=>now+20*60000});
 assert.equal(score.official_trifecta_payout_per_100_yen,1280);
 assert.equal(score.hypothetical_stake_yen,800);
 assert.equal(score.hypothetical_return_yen,score.hit8?1280:0);
 assert.deepEqual(predict(f).top8,baseline.top8);
 const invalid=result();invalid.payout_per_100_yen=-1;
 await assert.rejects(()=>settle(db,f,invalid,{now:()=>now+20*60000}),/RESULT_UNADMITTED/);
});
