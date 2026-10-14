const {test} = require('node:test');
const assert = require('node:assert/strict');
const UI = require('../web/ui-core.js');
const snapshot = () => ({date_jst:'2026-10-15', first_observed_at:'2026-10-15T00:00:00+09:00',source_url:'https://example.org/approved',source_sha256:'a'.repeat(64),redistribution_authorized:true,venues:[{venue:'18',races:[{race_id:'20261015-18-01',closed_at:'2026-10-15T15:30:00+09:00',boats:[{lane:1,racer_registration_id:'1234',name:'照合選手',motor_no:21}]}]}]});
test('rejects stale or unapproved automatic data rather than displaying it as today',()=>{
  assert.equal(UI.validateReport(snapshot(),{today:'2026-10-15',automatic:true,now:Date.parse('2026-10-15T08:00:00+09:00')}).races,1);
  assert.throws(()=>UI.validateReport({...snapshot(),date_jst:'2026-10-14'},{today:'2026-10-15',automatic:true}),/対象日/);
  assert.throws(()=>UI.validateReport({...snapshot(),redistribution_authorized:false},{today:'2026-10-15',automatic:true}),/配信/);
});
test('rejects duplicate boat identities and race/day identity mismatches',()=>{
  const data=snapshot();data.venues[0].races[0].boats.push({...data.venues[0].races[0].boats[0]});
  assert.throws(()=>UI.validateReport(data),/艇/);
  const bad=snapshot();bad.venues[0].races[0].race_id='20261014-18-01';
  assert.throws(()=>UI.validateReport(bad),/レース/);
});
test('distinguishes confirmed no event from missing data',()=>{
  assert.throws(()=>UI.validateReport({...snapshot(),venues:[]}),/開催/);
  assert.throws(()=>UI.validateReport({...snapshot(),venues:[],status:'NO_EVENT'}),/開催/);
  assert.equal(UI.venueState(null,'18'),'unobtained');
  assert.equal(UI.venueState({venues:[],status:'NO_EVENT'},'18'),'unobtained');
  assert.equal(UI.venueState(snapshot(),'18'),'ready');
});
test('empty venue schedule states require matching same-day source proof',()=>{
  const data=snapshot(), source={source_url:data.source_url,source_sha256:data.source_sha256,first_observed_at:data.first_observed_at};
  data.sources=[source];
  data.venues.push({venue:'01',races:[],status:'NO_EVENT',no_event:true,schedule_basis:'NOT_LISTED_IN_COMPLETE_DAY_INDEX',schedule_verified:true,schedule_source_url:source.source_url,schedule_source_sha256:source.source_sha256,schedule_observed_at:source.first_observed_at});
  data.venues.push({...data.venues[1],venue:'02',status:'ERROR',no_event:false,schedule_basis:'LISTED_IN_COMPLETE_DAY_INDEX'});
  assert.equal(UI.validateReport(data).races,1);
  assert.equal(UI.venueState(data,'01'),'no-event');
  assert.equal(UI.venueState(data,'02'),'error');
  assert.equal(UI.venueState(data,'03'),'unobtained');
  data.venues[1].schedule_observed_at='2026-10-14T23:59:00+09:00';
  assert.throws(()=>UI.validateReport(data),/開催/);
});
test('a fully empty day requires a verified complete-day schedule and no active venues',()=>{
  const data=snapshot(),source={source_url:data.source_url,source_sha256:data.source_sha256,first_observed_at:data.first_observed_at};
  Object.assign(data,{venues:[],status:'NO_EVENT',no_event:true,active_venues:[],schedule_verified:true,sources:[source],schedule_source_url:source.source_url,schedule_source_sha256:source.source_sha256,schedule_observed_at:source.first_observed_at});
  assert.equal(UI.validateReport(data).races,0);
  assert.equal(UI.venueState(data,'18'),'no-event');
  data.active_venues=['18'];
  assert.throws(()=>UI.validateReport(data),/開催/);
});
test('searches names and registration numbers while preserving venue and race filters',()=>{
  const data=snapshot();data.venues[0].races.push({...data.venues[0].races[0],race_id:'20261015-18-02'});
  assert.equal(UI.filterRaces(data,{query:'照合',venue:'18',number:'2'}).length,1);
  assert.equal(UI.filterRaces(data,{query:'1234',venue:'18'}).length,2);
  assert.equal(UI.filterRaces(data,{query:'1234',venue:'01'}).length,0);
});
test('unknown, elapsed and ambiguous cutoffs block new local purchase records',()=>{
  const race=snapshot().venues[0].races[0];
  assert.equal(UI.purchaseAvailability(race,'2026-10-15',Date.parse('2026-10-15T15:00:00+09:00')).allowed,true);
  assert.equal(UI.purchaseAvailability(race,'2026-10-15',Date.parse('2026-10-15T15:30:00+09:00')).allowed,false);
  assert.equal(UI.purchaseAvailability({...race,closed_at:null},'2026-10-15',0).allowed,false);
  assert.equal(UI.purchaseAvailability({...race,closed_at:'15:30'},'2026-10-15',0).allowed,true);
  assert.equal(UI.purchaseAvailability({...race,closed_at:'2026-10-16T15:30:00+09:00'},'2026-10-15',0).allowed,false);
});
test('malformed routes cannot select an unknown page',()=>{
  assert.equal(UI.parseRoute('#/research').page,'research');
  assert.equal(UI.parseRoute('#/detail/20261015-18-01').raceId,'20261015-18-01');
  assert.equal(UI.parseRoute('#/oops').page,'home');
});

