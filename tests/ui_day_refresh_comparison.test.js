const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
// Execute the actual day transport and report-selection handlers; render/network are doubles.
function harness(){
 const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
 const handlers=source.slice(source.indexOf('  function clearReport(){'),source.indexOf('  async function saveSettings('));
 const clear=source.match(/  function clearNameBound\(\)[^\n]+/)[0];
 const identities=source.slice(source.indexOf('  function programIdentity('),source.indexOf('  function clearEvaluation('));
 const select=source.match(/  function selectRace\(id\)[^\n]+/)[0];
 const dayCheck=source.slice(source.indexOf('  let lastDay=today();function checkDay(){'),source.indexOf('  setInterval(checkDay,'));
 const race={race_id:'20261016-14-02',venue:'14',closed_at:'2026-10-16T09:01:00+09:00',boats:Array.from({length:6},(_,i)=>({lane:i+1,racer_registration_id:String(5000+i),name:'Racer'+i,national_win_rate:5+i/10}))};
 const initial={date_jst:'2026-10-16',venues:[{races:[race,{...structuredClone(race),race_id:'20261016-14-03'}]}]},envelope={immutable:true},evaluation={frozen:true},pending=[],timers=[];
 const elements={'race-date':{value:initial.date_jst},'refresh-feed':{disabled:false,classList:{remove(){}}}};
 const context=vm.createContext({AbortController,TextEncoder,JSON,Date,initial,envelope,evaluation,elements,
  setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},
  fetch:(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,reject,resolve:(data=initial,status=200)=>resolve({status,ok:status===200,text:async()=>JSON.stringify(data)}),resolveRaw:(body,status=200)=>resolve({status,ok:status===200,text:async()=>body})})),
  UI:{parseRoute:hash=>({raceId:hash.split('/detail/')[1]}),validateReport:data=>{if(data.invalid)throw Error('rejected');return data;}},
  location:{hash:'#/detail/'+race.race_id},status(){},refreshRaceSelect(){},renderSource(){},renderAll(){},loadSettlements(){},
  clearSettlements(){},renderMoney(){},renderDetailTab(){},renderRaces(){},renderDetail(){},renderDraft(){},loadRaceUpdates(){},loadPrediction(){},setMessage(){},
  clearExhibition(){},clearOriginal(){},clearNameBoundEvaluation:()=>{},});
 vm.runInContext(`let page='detail',tab='prediction',report=initial,selectedId=initial.venues[0].races[0].race_id;
  let controller=null,requestSerial=0,feedMessage='',clockDay=initial.date_jst;const $=id=>elements[id],today=()=>clockDay;
  const all=()=>report?.venues.flatMap(v=>v.races)||[],current=()=>all().find(r=>r.race_id===selectedId);
  let nbEnvelope=envelope,nbState='ready',nbMessage='saved',nbRaceId=selectedId,nbSerial=0,nbController=null,nbEvaluation=evaluation;
  const phaseInventory=new Map();function clearNameBoundEvaluation(){nbEvaluation=null;}
  ${clear}\n${identities}
  function clearRaceUpdates(){clearNameBound();}
  function clearPrediction(){clearNameBound();}
  const drafts=new Map(),knownRaceStops=new Map();${handlers}\n${select}\n${dayCheck}
  globalThis.app={load:loadAuthorizedDayFeed,state:()=>({report,selectedId,nbEnvelope,nbEvaluation,nbState}),date:value=>elements['race-date'].value=value,
   select:id=>{location.hash='#/detail/'+id;selectRace(id);},rollDay:value=>{clockDay=value;checkDay();}};`,context);
 return{app:context.app,pending,timers,initial,envelope,evaluation};
}
test('unchanged automatic day refresh preserves the loaded immutable comparison and evaluation',async()=>{
 const h=harness(),work=h.app.load();assert.equal(h.pending.length,1);assert.equal(h.pending[0].url,'./api/today');
 assert.equal(h.app.state().nbEnvelope,h.envelope);assert.equal(h.app.state().nbEvaluation,h.evaluation);
 h.pending[0].resolve(structuredClone(h.initial));await work;
 assert.equal(h.app.state().nbEnvelope,h.envelope);assert.equal(h.app.state().nbEvaluation,h.evaluation);assert.equal(h.app.state().nbState,'ready');
});
test('changed race, cutoff, lane registration, name or research inputs clear the prior comparison',async()=>{
 for(const change of [r=>r.race_id='20261016-14-04',r=>r.closed_at='2026-10-16T09:02:00+09:00',r=>r.boats[0].racer_registration_id='5999',r=>r.boats[0].name='Changed',r=>r.boats[0].national_win_rate=9]){
  const h=harness(),work=h.app.load(),data=structuredClone(h.initial);change(data.venues[0].races[0]);h.pending[0].resolve(data);await work;
  assert.equal(h.app.state().nbEnvelope,null);assert.equal(h.app.state().nbEvaluation,null);
 }
});
test('unavailable, rejected, non-JSON and transport-failed refreshes clear the comparison',async()=>{
 for(const [data,status]of [[{error:'FEED_NOT_SAVED'},404],[{error:'FEED_STORE_UNAVAILABLE'},503],[{invalid:true},200],[{},502]]){
  const h=harness(),work=h.app.load();h.pending[0].resolve(data,status);await work;assert.equal(h.app.state().nbEnvelope,null);assert.equal(h.app.state().report,null);
 }
 const h=harness(),work=h.app.load();h.pending[0].reject(Error('transport'));await work;assert.equal(h.app.state().nbEnvelope,null);
 const h2=harness(),work2=h2.app.load();h2.pending[0].resolveRaw('<html>not JSON</html>');await work2;assert.equal(h2.app.state().nbEnvelope,null);
});
test('date changes clear the comparison and stale requests cannot restore it',async()=>{
 const h=harness(),old=h.app.load();h.app.date('2026-10-15');await h.app.load();assert.equal(h.pending.length,1);
 assert.equal(h.app.state().nbEnvelope,null);assert.equal(h.pending[0].options.signal.aborted,true);
 h.pending[0].resolve();await old;assert.equal(h.app.state().nbEnvelope,null);assert.equal(h.app.state().report,null);
});
test('superseded refresh cannot clear or replace the comparison after a newer matching response',async()=>{
 const h=harness(),old=h.app.load(),latest=h.app.load();assert.equal(h.pending[0].options.signal.aborted,true);
 h.pending[1].resolve(structuredClone(h.initial));await latest;assert.equal(h.app.state().nbEnvelope,h.envelope);
 h.pending[0].resolve({error:'FEED_STORE_UNAVAILABLE'},503);await old;assert.equal(h.app.state().nbEnvelope,h.envelope);
});
test('selecting another race during refresh clears the old comparison and keeps the new selection',async()=>{
 const h=harness(),work=h.app.load();h.app.select('20261016-14-03');assert.equal(h.app.state().nbEnvelope,null);
 h.pending[0].resolve(structuredClone(h.initial));await work;
 assert.equal(h.app.state().selectedId,'20261016-14-03');assert.equal(h.app.state().nbEnvelope,null);assert.equal(h.app.state().nbEvaluation,null);
});
test('actual day rollover clears the old comparison and stale day response cannot revive it',async()=>{
 const h=harness(),old=h.app.load();h.app.rollDay('2026-10-17');assert.equal(h.pending.length,2);
 assert.equal(h.pending[0].options.signal.aborted,true);assert.equal(h.app.state().nbEnvelope,null);
 h.pending[0].resolve(structuredClone(h.initial));await old;assert.equal(h.app.state().report,null);assert.equal(h.app.state().nbEnvelope,null);
});
test('refresh timeout aborts its request and clears comparison on the actual abort rejection',async()=>{
 const h=harness(),work=h.app.load();h.timers[0]();assert.equal(h.pending[0].options.signal.aborted,true);
 const error=Error('aborted');error.name='AbortError';h.pending[0].reject(error);await work;assert.equal(h.app.state().nbEnvelope,null);assert.equal(h.app.state().nbEvaluation,null);
});
