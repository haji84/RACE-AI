'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),U=require('../web/ui-model.js');
const now=Date.parse('2030-01-01T01:00:00Z');
const row=(id,cutoff,extra={})=>({race_id:id,sport:'boat',venue:'江戸川',event_date_jst:'2030-01-01',cutoff_at:cutoff,...extra});
test('prediction closes at the cutoff, without inferring an official result',()=>{
  const r=row('next','2030-01-01T10:01:00+09:00');
  assert.equal(U.racePhase(r,{now}),'upcoming');assert.equal(U.racePhase(r,{now:now+60000}),'results');assert.equal(r.result,undefined);
});
test('confirmed/cancelled results close immediately; unverified results follow the known deadline',()=>{
  for(const status of ['final','void'])assert.equal(U.racePhase(row(status,'2030-01-01T11:00:00+09:00',{result:{status}}),{now}),'results');
  assert.equal(U.racePhase(row('held-future','2030-01-01T11:00:00+09:00',{result:{status:'unsupported'}}),{now}),'upcoming');
  assert.equal(U.racePhase(row('held-past','2030-01-01T09:00:00+09:00',{result:{status:'unsupported'}}),{now}),'results');
  assert.equal(U.racePhase(row('pending','2030-01-01T11:00:00+09:00',{result:{status:'pending'}}),{now}),'upcoming');
});
test('unknown current/future cutoffs remain unknown; past-day records are accessible in results',()=>{
  for(const day of ['2030-01-01','2030-01-02'])assert.equal(U.racePhase(row(day,null,{event_date_jst:day}),{now}),'unknown');
  assert.equal(U.racePhase(row('old',null,{event_date_jst:'2029-12-31'}),{now}),'results');
  assert.equal(U.racePhase(row('bad','not a clock'),{now}),'unknown');
});
test('conflicting saved clocks use the earliest known cutoff and do not depend on the selected model',()=>{
  const r=row('variants',null,{saved_cutoff_variants:['2030-01-01T10:05:00+09:00','2030-01-01T09:59:00+09:00'],prediction:{cutoff_at:'2030-01-01T10:10:00+09:00'}}),before=JSON.stringify(r);
  assert.equal(U.raceDeadline(r),'2030-01-01T09:59:00+09:00');assert.equal(U.racePhase(r,{now}),'results');assert.equal(JSON.stringify(r),before);
});
test('upcoming is ordered by cutoff and results newest first, without rewriting originals',()=>{
  const rows=[row('past1','2030-01-01T09:40:00+09:00'),row('late','2030-01-01T10:30:00+09:00'),row('past2','2030-01-01T09:55:00+09:00'),row('next','2030-01-01T10:02:00+09:00'),row('unknown',null)];
  const before=JSON.stringify(rows),out=U.raceLists(rows,{now});assert.deepEqual(out.upcoming.map(r=>r.race_id),['next','late']);assert.deepEqual(out.results.map(r=>r.race_id),['past2','past1']);assert.deepEqual(out.unknown.map(r=>r.race_id),['unknown']);assert.equal(JSON.stringify(rows),before);
});
test('venue counts separate predictions, settled results, waits and unknown cutoffs',()=>{
  const rows=[row('old','2030-01-01T09:40:00+09:00',{result:{status:'final'}}),row('waiting','2030-01-01T09:55:00+09:00'),row('next','2030-01-01T10:02:00+09:00'),row('unknown',null)];
  const v=U.venueOverview(rows,{sport:'boat',now}).find(v=>v.venue==='江戸川');assert.equal(v.upcomingCount,1);assert.equal(v.resultCount,2);assert.equal(v.settledCount,1);assert.equal(v.pendingResultCount,1);assert.equal(v.unknownCount,1);assert.equal(v.nextRace.race_id,'next');
});
