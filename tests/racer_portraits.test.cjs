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
