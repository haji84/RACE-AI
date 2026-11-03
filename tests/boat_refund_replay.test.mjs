/** Fictional fixtures only. A simulated next-day clock is NOT a live D+1 pass. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {readFileSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {parseResult,parseResultDetails} from '../workers/boat_official_html.mjs';
import {settle} from '../workers/boat_nonvercel_core.mjs';
import {runTick} from '../workers/boat_nonvercel_cron.mjs';
import {buildChallenger} from '../workers/boat_pdca_shadow.mjs';

const hash=s=>createHash('sha256').update(s).digest('hex');
const key=d=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(d).replaceAll('-','');
const iso=d=>d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6,8);
const links=(kind,day)=>Array.from({length:12},(_,i)=>`<a href="/owpc/pc/race/${kind}?rno=${i+1}&jcd=17&hd=${day}">${i+1}R</a>`).join('');
const table=(heads,rows)=>'<table><thead><tr>'+heads.map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+x+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
const roster=Array.from({length:6},(_,i)=>({lane:i+1,registration_no:String(4201+i)}));
const tickets=[[1,2,3],[1,2,5],[1,5,2],[5,1,2],[1,3,2],[2,1,3],[2,3,1],[3,1,2]];
function resultHtml(day,refund='5'){
 return links('raceresult',day)+table(['着','枠','ボートレーサー','レースタイム'],roster.map(r=>[r.lane===5&&refund?'F':String(r.lane),String(r.lane),r.registration_no+' Sample','1.50.0']))+
 table(['勝式','組番','払戻金'],[['3連単','1-2-3','980']])+table(['返還'],[[refund]]);
}
function programHtml(day){
 return links('racelist',day)+table(['R'],[['締切予定時刻',...Array.from({length:12},(_,i)=>'08:'+String(i).padStart(2,'0'))]])+
 table(['枠','写真','ボートレーサー','ST','全国','当地','モーター','ボート'],roster.map(r=>[String(r.lane),'',`<a href="/x?toban=${r.registration_no}">${r.registration_no} / Sample</a>`,'0.15','5.00','5.00','1','1']));
}
class DB{
 constructor(path=':memory:'){
  this.raw=new DatabaseSync(path);
  this.raw.exec(readFileSync(new URL('../workers/boat_nonvercel_schema.sql',import.meta.url),'utf8'));
 }
 prepare(sql){const q=this.raw.prepare(sql);return {bind(...a){return {async first(){return q.get(...a)??null;},async run(){return q.run(...a);},async all(){return {results:q.all(...a)};}}}};}
 close(){this.raw.close();}
}
function seed(db,id,cutoff){
 const body=JSON.stringify({race_id:id,cutoff_at:cutoff,model_id:'pr64-official-beforeinfo-display-pl-v1-nonvercel',top8:tickets});
 const saved=new Date(Date.parse(cutoff)-300000).toISOString();
 db.raw.prepare('INSERT INTO boat_exhibition_freezes VALUES(?,?,?,?,?,?,?)').run(id,'pr64-official-beforeinfo-display-pl-v1-nonvercel','a'.repeat(64),cutoff,body,hash(body),saved);
 return body;
}
function fact(day,refund=[5]){
 return {race_id:day+'-17-01',phase:'official_result',result_state:'confirmed',dead_heat:false,
 source_url:`https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=17&hd=${day}`,
 source_sha256:'e'.repeat(64),captured_at:iso(day)+'T09:00:00+09:00',top3:[1,2,3],refund_boats:refund,payout_per_100_yen:980};
}
test('verified refund is terminal detail; old top3-only consumer still refuses it',()=>{
 const d='20301103',out=parseResultDetails(resultHtml(d),d,'17',1,roster);
 assert.deepEqual(out.top3,[1,2,3]);
 assert.deepEqual(out.refund_boats,[5]);
 assert.equal(out.result_class,'SETTLED_WITH_REFUND');
 assert.equal(out.payout_per_100_yen,980);
 assert.throws(()=>parseResult(resultHtml(d),d,'17',1,roster),/REFUND/);
 assert.throws(()=>parseResultDetails(resultHtml(d,'5 確認中'),d,'17',1,roster),/REFUND/);
 assert.throws(()=>parseResultDetails(resultHtml(d,'1'),d,'17',1,roster),/REFUND/);
 assert.throws(()=>parseResultDetails(resultHtml(d,'5 5'),d,'17',1,roster),/REFUND/);
});
test('refund settlement preserves picks; reopen in fresh process reproduces identical report',async()=>{
 const root=mkdtempSync(join(tmpdir(),'boat-refund-')),path=join(root,'state.sqlite');
 const day='20301103',res=fact(day),race={race_id:res.race_id,cutoff_at:iso(day)+'T08:00:00+09:00'};
 let db=new DB(path);
 try{
  const original=seed(db,race.race_id,race.cutoff_at);
  const out=await settle(db,race,res,{now:()=>Date.parse(iso(day)+'T10:00:00+09:00')});
  assert.equal(out.result_class,'SETTLED_WITH_REFUND');
  assert.equal(out.eligible_normal_accuracy,false);
  assert.equal(out.hit1,null);assert.equal(out.hit8,null);
  assert.equal(out.refunded_ticket_count,3);
  assert.equal(out.hypothetical_refund_yen,300);
  assert.equal(out.hypothetical_net_stake_yen,500);
  assert.equal(out.hypothetical_winnings_yen,980);
  assert.equal(out.hypothetical_return_yen,1280);
  const saved=db.raw.prepare('SELECT * FROM boat_exhibition_outcomes').get();
  assert.equal(db.raw.prepare('SELECT body_json FROM boat_exhibition_freezes').get().body_json,original);
  assert.throws(()=>db.raw.exec("DELETE FROM boat_exhibition_outcomes"),/IMMUTABLE/);
  db.close();db=null;
  const script=`import {DatabaseSync} from 'node:sqlite';import {settle} from ${JSON.stringify(new URL('../workers/boat_nonvercel_core.mjs',import.meta.url).href)};
let s='';for await(const c of process.stdin)s+=c;const p=JSON.parse(s),raw=new DatabaseSync(p.path);
const db={prepare(sql){const q=raw.prepare(sql);return {bind(...a){return {async first(){return q.get(...a)??null;},async run(){return q.run(...a)}}}}}};
await settle(db,p.race,{...p.res,captured_at:'2030-11-04T09:00:00+09:00'},{now:()=>Date.parse('2030-11-04T10:00:00+09:00')});
console.log(JSON.stringify(raw.prepare('SELECT * FROM boat_exhibition_outcomes').get()));raw.close();`;
  const child=spawnSync(process.execPath,['--input-type=module','-e',script],{input:JSON.stringify({path,race,res}),encoding:'utf8'});
  assert.equal(child.status,0,child.stderr);
  assert.deepEqual(JSON.parse(child.stdout),JSON.parse(JSON.stringify(saved)));
 }finally{db?.close();rmSync(root,{recursive:true,force:true});}
});
test('bad refund identities cannot be turned into a normal miss',async()=>{
 const db=new DB(),d='20301103',res=fact(d),race={race_id:res.race_id,cutoff_at:iso(d)+'T08:00:00+09:00'};
 try{
  for(const refund of [[1],[5,5],[7],['5'],null]){
   await assert.rejects(settle(db,race,{...res,refund_boats:refund},{now:()=>Date.parse('2030-11-04T10:00:00+09:00')}));
  }
  assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM boat_exhibition_outcomes').get().n,0);
 }finally{db.close();}
});
test('scheduled control records refunded race then reaches final race without manual reset',async()=>{
 const db=new DB(),today=key(new Date()),prior=key(new Date(Date.now()-86400000));let calls=0;
 const env={BOAT_AUTO_ENABLED:'true',BOAT_RIGHTS_REVIEWED:'true',BOAT_RIGHTS_REFERENCE:'SYNTHETIC_OFFLINE_TEST',BOAT_DB:db,BOAT_PILOT_VENUE:'17',BOAT_MAX_REQUESTS_PER_DAY:'120'};
 try{
  for(const d of [prior,today])for(let n=1;n<=12;n++){
   const cutoff=iso(d)+'T08:'+String(n-1).padStart(2,'0')+':00+09:00';
   db.raw.prepare('INSERT INTO boat_race_schedule VALUES(?,?,?,?,?)').run(`${d}-17-${String(n).padStart(2,'0')}`,d,'17',n,cutoff);
   if(d===today||(n!==1&&n!==12))db.raw.prepare('INSERT INTO boat_result_poll_state(race_id,next_check_at,checks) VALUES(?,?,?)').run(`${d}-17-${String(n).padStart(2,'0')}`,'2099-01-01T00:00:00Z',1);
  }
  for(const n of [1,12])seed(db,`${prior}-17-${String(n).padStart(2,'0')}`,iso(prior)+`T08:${String(n-1).padStart(2,'0')}:00+09:00`);
  const fetcher=async url=>{calls++;const u=new URL(url),d=u.searchParams.get('hd'),n=Number(u.searchParams.get('rno'));
   const html=u.pathname.endsWith('racelist')?programHtml(d):resultHtml(d,n===1?'5':'');
   const r=new Response(html,{headers:{'Content-Type':'text/html'}});Object.defineProperty(r,'url',{value:url});return r;};
  const first=await runTick(env,{fetcher});
  assert.equal(first.result_status[0].race_id,prior+'-17-01');
  assert.equal(first.result_status[0].status,'RESULT_PDCA_DB_VERIFIED');
  assert.equal(first.result_status[0].result_class,'SETTLED_WITH_REFUND');
  const second=await runTick(env,{fetcher});
  assert.equal(second.result_status[0].race_id,prior+'-17-12');
  assert.equal(second.result_status[0].status,'RESULT_PDCA_DB_VERIFIED');
  assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM boat_exhibition_outcomes').get().n,2);
  assert.equal(calls,4);
 }finally{db.close();}
});
test('refund outcome is excluded from normal shadow training',async()=>{
 const day='20301103',db=new DB(),res=fact(day),race={race_id:res.race_id,cutoff_at:iso(day)+'T08:00:00+09:00'};
 try{
  await settle(db,race,res,{now:()=>Date.parse('2030-11-04T10:00:00+09:00')});
  const rows=db.raw.prepare('SELECT report_json,report_sha256,db_saved_at FROM boat_exhibition_outcomes').all();
  const x=await buildChallenger({race_id:'20301104-17-01',captured_at:'2030-11-04T10:00:00+09:00'},rows);
  assert.equal(x.status,'PDCA_NOT_ENOUGH_EARLIER_RESULTS');assert.equal(x.count,0);
 }finally{db.close();}
});
