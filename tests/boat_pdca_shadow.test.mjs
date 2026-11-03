import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {predict,freeze} from '../workers/boat_nonvercel_core.mjs';
import {buildChallenger,freezeChallenger,settleChallenger,MIN_HISTORY} from '../workers/boat_pdca_shadow.mjs';

const digest=s=>createHash('sha256').update(s).digest('hex');
const race='20301103-18-05',cutoff='2030-11-03T10:30:00+09:00';
const time=Date.parse('2030-11-03T10:15:00+09:00');
const facts=()=>({schema:'RACE_AI_BOAT_OBSERVATION_V1',phase:'post_exhibition',
 race_id:race,cutoff_at:cutoff,captured_at:'2030-11-03T10:14:50+09:00',
 source_url:'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=5&jcd=18&hd=20301103',
 source_sha256:'a'.repeat(64),program_sha256:'b'.repeat(64),rights_verified:true,
 license_purpose:'private_analysis',racers:Array.from({length:6},(_,i)=>({
 lane:i+1,registration_no:String(i+4201),national_win_rate:5.2+i*.2,exhibition_time_seconds:6.80+i*.01
 }))});
const official=()=>({phase:'official_result',race_id:race,source_url:'https://www.boatrace.jp/owpc/pc/race/raceresult?rno=5&jcd=18&hd=20301103',
 source_sha256:'d'.repeat(64),result_state:'confirmed',refund_boats:[],dead_heat:false,
 top3:[1,2,3],captured_at:'2030-11-03T10:35:00+09:00'});
function priorHistory(count=MIN_HISTORY){
 return Array.from({length:count},(_,i)=>{
  const day=String(1+Math.floor(i/12)).padStart(2,'0');
  const no=String(1+i%12).padStart(2,'0');
  const d='2030-11-'+day;
  const report={race_id:'203011'+day+'-18-'+no,official_top3:[i<18?1:2,3,4],
   captured_at:d+'T11:00:00+09:00',source_sha256:digest(String(i))};
  const report_json=JSON.stringify(report);
  return {report_json,report_sha256:digest(report_json),db_saved_at:d+'T11:05:00+09:00'};
 });
}
class FakeD1 {
 constructor(rows=[]){this.history=rows;this.primary=null;this.shadow=null;this.shadowScores=new Map();this.shadowInserts=0;}
 prepare(sql){
  const db=this;
  return {bind(...a){return {
   async first(){
    if(sql.startsWith('INSERT INTO boat_exhibition_freezes')){
     if(db.primary)return null;
     db.primary={race_id:a[0],model_id:a[1],source_sha256:a[2],cutoff_at:a[3],body_json:a[4],payload_sha256:a[5],db_stored_at:'2030-11-03T01:15:00.500Z'};
     return {db_stored_at:db.primary.db_stored_at};
    }
    if(sql.startsWith('INSERT INTO boat_exhibition_shadow_freezes')){
     if(db.shadow)return null;
     db.shadowInserts++;
     db.shadow={race_id:a[0],model_id:a[1],primary_sha256:a[2],cutoff_at:a[3],body_json:a[4],payload_sha256:a[5],db_stored_at:'2030-11-03T01:15:01.500Z'};
     return {db_stored_at:db.shadow.db_stored_at};
    }
    if(sql.includes('FROM boat_exhibition_shadow_freezes'))return db.shadow;
    if(sql.includes('FROM boat_exhibition_freezes'))return db.primary;
    if(sql.includes('FROM boat_exhibition_shadow_outcomes'))return db.shadowScores.get(a[0]+':'+a[1])??null;
    throw Error('Unknown select: '+sql);
   },
   async run(){
    if(sql.startsWith('INSERT INTO boat_exhibition_shadow_outcomes')){
     const key=a[0]+':'+a[1];
     if(!db.shadowScores.has(key))db.shadowScores.set(key,{report_json:a[2],report_sha256:a[3],db_saved_at:'2030-11-03T01:35:01.000Z'});
     return {success:true};
    }
    throw Error('Unknown insert: '+sql);
   },
   async all(){
    if(!sql.includes('FROM boat_exhibition_outcomes'))throw Error('Unknown history');
    const asOf=Date.parse(a[1]);
    return {results:db.history.filter(x=>Date.parse(x.db_saved_at)<asOf)
      .sort((x,y)=>Date.parse(y.db_saved_at)-Date.parse(x.db_saved_at)).slice(0,a[2])};
   }
  };}};
 }
}
test('only earlier settled history produces separate probability mass and eight tickets',async()=>{
 const candidate=await buildChallenger(facts(),priorHistory());
 assert.equal(candidate.status,'PDCA_CHALLENGER_READY');
 const x=candidate.candidate;
 assert.equal(x.training_count,24);
 assert.ok(x.lane_prior_factors[0]>x.lane_prior_factors[1]);
 assert.equal(x.all120.length,120);
 assert.equal(new Set(x.ordered_top8.map(t=>t.join('-'))).size,8);
 assert.ok(Math.abs(x.all120.reduce((s,a)=>s+a.score,0)-1)<1e-10);
 assert.equal(x.probabilities_calibrated,false);
 assert.equal(x.auto_promoted,false);
 assert.notDeepEqual(x.all120,predict(facts()).all120);
});
test('future result, tampered SHA, wrong venue, or duplicate identity rejected',async()=>{
 const a=priorHistory();
 const future=structuredClone(a);
 future[0].db_saved_at='2030-11-03T10:16:00+09:00';
 await assert.rejects(()=>buildChallenger(facts(),future),/PDCA_FUTURE_OR_WRONG_VENUE/);
 const tampered=structuredClone(a);tampered[0].report_sha256='0'.repeat(64);
 await assert.rejects(()=>buildChallenger(facts(),tampered),/PDCA_HISTORY_SHA_MISMATCH/);
 const other=structuredClone(a);
 const d=JSON.parse(other[0].report_json);d.race_id='20301101-17-01';
 other[0].report_json=JSON.stringify(d);other[0].report_sha256=digest(other[0].report_json);
 await assert.rejects(()=>buildChallenger(facts(),other),/PDCA_FUTURE_OR_WRONG_VENUE/);
 const same=structuredClone(a);
 same[1].report_json=same[0].report_json;same[1].report_sha256=same[0].report_sha256;
 const x=await buildChallenger(facts(),same);
 assert.equal(x.status,'PDCA_NOT_ENOUGH_EARLIER_RESULTS');
 assert.equal(x.count,23);
});
test('no forecast candidate created with insufficient settled history',async()=>{
 const db=new FakeD1(priorHistory(5)),f=facts();
 await freeze(db,f,{now:()=>time});
 const out=await freezeChallenger(db,f,{now:()=>time});
 assert.equal(out.status,'PDCA_NOT_ENOUGH_EARLIER_RESULTS');
 assert.equal(out.training_count,5);
 assert.equal(db.shadowInserts,0);
});
test('primary is never edited; once frozen shadow cannot update after later PDCA',async()=>{
 const f=facts(),db=new FakeD1(priorHistory());
 const original=await freeze(db,f,{now:()=>time});
 assert.equal(original.status,'FROZEN_DB_READBACK_VERIFIED');
 const primaryHash=db.primary.payload_sha256,primaryJSON=db.primary.body_json;
 const first=await freezeChallenger(db,f,{now:()=>time});
 assert.equal(first.status,'PDCA_SHADOW_FROZEN_READBACK_VERIFIED');
 assert.equal(first.training_count,MIN_HISTORY);
 assert.equal(first.ordered_top8.length,8);
 db.history=priorHistory().map(x=>({...x}));
 const second=await freezeChallenger(db,f,{now:()=>time+1000});
 assert.equal(second.status,'PDCA_SHADOW_ALREADY_FROZEN');
 assert.equal(db.shadowInserts,1);
 assert.equal(db.primary.payload_sha256,primaryHash);
 assert.equal(db.primary.body_json,primaryJSON);
 const score=await settleChallenger(db,{race_id:race,cutoff_at:cutoff},official(),{now:()=>time+20*60_000});
 assert.equal(score.status,'PDCA_SHADOW_SCORED');
 assert.equal(score.candidate_frozen,true);
 assert.equal(score.hit8,Number(first.ordered_top8.some(x=>x.join('-')==='1-2-3')));
 assert.equal(db.shadowScores.size,1);
 const repeated=await settleChallenger(db,{race_id:race,cutoff_at:cutoff},official(),{now:()=>time+20*60_000});
 assert.equal(repeated.report_sha256,score.report_sha256);
 assert.equal(db.shadowScores.size,1);
});
test('missing candidate is kept in denominator, and late result cannot be seen before race',async()=>{
 const db=new FakeD1();
 const scored=await settleChallenger(db,{race_id:race,cutoff_at:cutoff},official(),{now:()=>time+20*60_000});
 assert.equal(scored.candidate_frozen,false);assert.equal(scored.hit1,0);assert.equal(scored.hit8,0);
 await assert.rejects(()=>settleChallenger(db,{race_id:race,cutoff_at:cutoff},official(),{now:()=>time}),/RESULT_UNADMITTED/);
});
