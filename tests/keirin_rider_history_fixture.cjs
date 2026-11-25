'use strict';
const {createHash} = require('node:crypto');
const M = require('../web/keirin-note-model.js');
const date = '2030-01-31', race = '203001319801', prefix = 'data/' + date + '/';
const asOf = '2030-02-01T00:00:00.000001Z';
function file(value) {
  const text = JSON.stringify(value);
  return {text, bytes: Buffer.byteLength(text), sha256: createHash('sha256').update(text).digest('hex')};
}
function fixture() {
  const roster = {race_id: race, cutoff: '2030-01-31T03:00:00Z', riders: [1,2,3].map(number => ({number, name: '架空'+number}))};
  const saved = file({races: [roster]});
  const raw = {schema: 'RACE_AI_KEIRIN_RIDER_HISTORY_SUPPLEMENT_V1', generated_at: asOf,
    knowledge_as_of: asOf, source_roster_sha256: saved.sha256, registry_sha256: 'a'.repeat(64),
    archive_sha256s: ['b'.repeat(64), 'c'.repeat(64)], predictive_model_changed: false, races: []};
  const people = roster.riders.map(({number: car, name}) => {
    const registration = '00000'+car, n = car === 1 ? 2 : 0;
    const counts = Object.fromEntries(Array.from({length:9},(_,i)=>[i+1, i < 2 ? n/2 : 0]));
    const summary = {observed_count:n, missing_finish_count:null, finish_counts:counts,
      finish_rates:n ? Object.fromEntries(Object.entries(counts).map(([k,v])=>[k,v/n])) : null,
      first_observed_day:n?'2030-01-15':null,latest_observed_day:n?'2030-01-30':null};
    const starts = {all:null,'3_years':'2027-01-31','1_year':'2029-01-31','6_months':'2029-07-31',
      '4_months':'2029-09-30','3_months':'2029-10-31','1_month':'2029-12-31'};
    return {car,name,registration,history:{registration,as_of_exclusive:date,
      periods:Object.fromEntries(Object.entries(starts).map(([key,start])=>[key,{...summary,start_day_inclusive:start}])),
      last_starts:Object.fromEntries([30,20,10,5].map(k=>[k,{...summary,unfilled_slots:k-n,tied_boundary_observations:0}]))}};
  });
  raw.races.push({race_id:race,riders:people});
  return {roster,raw,packet:{schema:M.SCHEMA,formal_model_admission:false,production_weight_switch:false,
    source_commit:'a'.repeat(40),imported_at:asOf,dates:[date],files:{[prefix+'races.json']:saved}}};
}
module.exports={date,race,prefix,file,fixture};
