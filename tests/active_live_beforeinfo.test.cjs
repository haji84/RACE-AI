'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {activeFixture}=require('./active_live_beforeinfo_fixture.cjs');
function api(){
 const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
 const script=source.slice(source.indexOf('  function validBoatObservationContext('),source.indexOf('  function liveBeforeinfoPanel('));
 const scope={URL,knownParticipants:r=>Array.isArray(r?.participants)?r.participants:[],participantNumber:p=>p.number??p.lane,
  participantRegistration:p=>p.registration_no||p.registration_number||p.racer_registration_id};
 vm.createContext(scope);vm.runInContext(script+';globalThis.testAPI={liveBoatObservation,selectedBoatContext};',scope);
 return scope.testAPI;
}
const parsed=api();
for(const lanes of [[1,3,6],[1,2,4,6],[1,2,3,4,5],[1,2,3,4,5,6]])test('official program admits physical active lanes '+lanes,()=>{
 const row=activeFixture(lanes).records[0],original=JSON.stringify(row.prediction);
 assert.equal(parsed.liveBoatObservation(row)===row.live_boat_observation,true);
 assert.equal(parsed.selectedBoatContext(row)===row.live_boat_observation.context,true);
 assert.equal(JSON.stringify(row.prediction),original);
});
test('unbound six stays valid and an unbound five remains held',()=>{
 for(const lanes of [[1,2,3,4,5,6],[1,2,3,4,5]]){
  const row=activeFixture(lanes).records[0];delete row.live_boat_observation.context.program;
  assert.equal(parsed.liveBoatObservation(row)!==null,lanes.length===6);
 }
});
test('missing display remains a five-entrant partial observation',()=>{
 const row=activeFixture(undefined,{partial:true}).records[0];
 assert.equal(parsed.liveBoatObservation(row).state,'AWAITING_EXHIBITION');
 assert.equal(parsed.liveBoatObservation(row).context.beforeinfo.participants.length,5);
 assert.equal(parsed.liveBoatObservation(row).context.beforeinfo.participants[0].display_time,null);
});
test('explicit current withdrawals do not rewrite the saved six-person forecast',()=>{
 const row=activeFixture(undefined,{savedLanes:[1,2,3,4,5,6]}).records[0],before=JSON.stringify(row);
 assert.equal(parsed.liveBoatObservation(row),row.live_boat_observation);
 assert.equal(row.live_boat_observation.context.beforeinfo.participants.length,5);
 assert.equal(JSON.stringify(row),before);
 for(const mutate of [r=>r.live_boat_observation.context.program.boats[5].racer_registration_id='4999',
  r=>r.live_boat_observation.context.program.boats.pop(),r=>r.withdrawn_lanes=[1],
  r=>r.withdrawn_participants=[{number:6,registration_no:'4999'}]]){
  const wrong=structuredClone(row);mutate(wrong);assert.equal(parsed.liveBoatObservation(wrong),null);
 }
});
test('contradictory identities, counts and source clocks fail closed',()=>{
 const fixture=activeFixture();
 const cases=[r=>r.participants.pop(),r=>r.participants[1].number=1,r=>r.participants[0].number=true,
  r=>r.participants[1].registration_no='4001',r=>r.participants[0].registration_no='4999',
  r=>r.live_boat_observation.context.roster.pop(),r=>r.live_boat_observation.context.roster[0]=null,
  r=>r.live_boat_observation.context.program.active_entrant_count=4,
  r=>r.live_boat_observation.context.program.boats[5].entry_status='listed',
  r=>r.live_boat_observation.context.program.boats[0].racer_registration_id='4999',
  r=>r.live_boat_observation.context.program.race_id='20300401-12-11',
  r=>r.live_boat_observation.context.program.source.sha256='b'.repeat(64),
  r=>r.live_boat_observation.context.program.captured_at='2030-04-01T20:00:00+09:00',
  r=>r.live_boat_observation.context.program.closed_at='2030-04-01T20:31:00+09:00',
  r=>r.live_boat_observation.checked_at='2030-04-01T19:44:59+09:00',
  r=>r.live_boat_observation.checked_at='2030-04-01T20:00:00',
  r=>r.participants[0].active=false,r=>r.participants[0].withdrawn=true,
  r=>r.event_date_jst='2030-04-02',r=>r.race_no=11,
  r=>r.live_boat_observation.context.beforeinfo.source.source_url+='&token=x'];
 for(const mutate of cases){const row=structuredClone(fixture.records[0]);mutate(row);assert.equal(parsed.liveBoatObservation(row),null);}
});
