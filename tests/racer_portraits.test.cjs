'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const filename = path.resolve(__dirname, '../web/racer-portraits.js');
const R = fs.existsSync(filename) ? require(filename) : {all: [], get: () => null};
const race = {sport: 'boat', scope: 'research'};

test('the initial six athletes resolve to their own official-profile illustration', () => {
  assert.ok(R.all.length >= 6);
  for (const [registration, name] of [['3415','松井繁'],['3897','白井英治'],['3941','池田浩二'],['4238','毒島誠'],['4320','峰竜太'],['4444','桐生順平']]) {
    const portrait = R.get(race, {registration_no: registration, name});
    assert.equal(portrait?.registration, registration);
    assert.equal(portrait?.name, name);
    assert.equal(portrait?.src, './assets/racer-portraits/boat-' + registration + '.webp');
    assert.equal(portrait?.sourceUrl, 'https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=' + registration);
  }
});

test('spaced official names and matching registration aliases retain identity', () => {
  assert.equal(R.get(race, {registration_no:'4238', racer_id:'4238', name:'毒島　　誠'})?.name, '毒島誠');
  assert.equal(R.get(race, {registration_number:'4320', name:'峰 竜太'})?.name, '峰竜太');
  assert.equal(R.get(race, {participant_id:'4238', name:'毒島誠'})?.registration, '4238');
  assert.equal(R.get(race, {registration_no:'4238', participant_id:'4238'})?.registration, '4238');
});

test('official program spellings resolve to the same portraits as full profile names', () => {
  // Exact registration/name pairs observed in retained official B archives.
  for (const [registration, programName, fullName] of [
    ['3556','田中信一','田中信一郎'], ['4503','上野真之','上野真之介'],
    ['4246','喜多那由','喜多那由夏'], ['4632','長尾京志','長尾京志郎'],
    ['3645','淺田千亜','淺田千亜希'], ['4304','藤崎小百','藤崎小百合']
  ]) {
    const full=R.get(race,{registration_no:registration,name:fullName});
    assert.ok(full,fullName);
    assert.equal(R.get(race,{registration_no:registration,name:programName}),full,programName);
  }
  assert.equal(R.get(race,{registration_no:'4503',name:'上野真'}),null);
  assert.equal(R.get(race,{registration_no:'3556',name:'上野真之'}),null);
  const proof=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../docs/evidence/2026-11-07/racer-portrait-official-name-aliases.json')));
  for(const fact of proof.entries){
    const found=R.get(race,{registration_no:fact.registration,name:fact.name});
    assert.equal(found?.registration,fact.registration,fact.name);
    assert.equal(found?.name,fact.canonical_name,fact.name);
  }
});

test('every official roster name retains its registered portrait', () => {
  const roster=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../docs/evidence/2026-11-07/racer-portrait-roster.json')));
  for(const person of roster.members){
    const name=person.current_name||person.term_name;
    assert.equal(R.get(race,{registration_no:person.registration,name})?.registration,person.registration,name);
  }
});

test('missing, conflicting, malformed and unknown registrations never choose a face', () => {
  for (const person of [{}, {number:4238}, {registration_no:'9999'}, {registration_no:'../4238'},
    {registration_no:4238}, {registration_no:'4238', racer_id:'4320'},
    {registration_no:'4238', participant_id:'4320'},
    {registration_no:null, racer_id:'4238'}, {registration_no:'4238', name:'峰竜太'},
    {registration_no:'4238', name:12}, {registration_no:'4238', placeholder:true}]) {
    assert.equal(R.get(race, person), null, JSON.stringify(person));
  }
});

test('other sports and synthetic records do not receive a real boat athlete portrait', () => {
  for (const r of [{sport:'keirin'}, {sport:'autorace'}, {sport:'horse'}, {sport:'boat',scope:'synthetic'}, {sport:'boat',synthetic:true}, null]) {
    assert.equal(R.get(r, {registration_no:'4238'}), null);
  }
});

test('each entry has a real WebP asset and immutable local metadata', () => {
  assert.ok(R.all.length >= 6);
  assert.equal(Object.isFrozen(R.all), true);
  const checked = new Set();
  for (const item of R.all) {
    assert.equal(Object.isFrozen(item), true);
    const src = item.src.split('?')[0];
    if (checked.has(src)) continue;
    checked.add(src);
    const bytes = fs.readFileSync(path.resolve(__dirname, '../web', src));
    assert.equal(bytes.subarray(0, 4).toString(), 'RIFF');
    assert.equal(bytes.subarray(8, 12).toString(), 'WEBP');
    assert.ok(bytes.length > 1000 && bytes.length < 4*1024*1024);
  }
});
