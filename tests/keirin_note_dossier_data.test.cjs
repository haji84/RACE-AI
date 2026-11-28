'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { prepare } = require('../web/keirin-dossier-data.js');
const archived = require('../docs/evidence/keirin-rider-dossier-20261126.json');

const day = '2026-11-28';
const race = '202611283103';
const cutoffAt = `${day}T12:00:00+09:00`;
const published = `${day}T12:30:00+09:00`;
const at = `${day}T10:00:00+09:00`;
const savedAt = `${day}T11:59:59.000001+09:00`;
const sha = 'a'.repeat(64);
const ids = [1, 2, 3, 4, 5];
const riders = ids.map(number => ({number, name: `取込例${number}`, registration: `01481${number}`, style: '両'}));
const packet = (schema, row) => ({schema, day, published_at: published, races: [{race_id: race, ...row}]});

function fixtures() {
  const rank = packet('RACE_AI_KEIRIN_PUBLIC_RANK_DISTRIBUTION_V1', {
    cutoff_at: cutoffAt, source_as_of: at, generated_at: at, frozen_at: savedAt,
    witnessed_at: `${day}T11:59:59.000002+09:00`, source_joint_sha256: sha, model_sha256: sha,
    scope: 'PROSPECTIVE_RESEARCH', premise: 'ALL_FINISH_NO_TIES', calibration_status: 'UNVALIDATED',
    riders: riders.map(({number, name, registration}) => ({number, name, registration, probabilities: [.2,.2,.2,.2,.2]}))
  });
  const stats = {back_count: 7, competition_points: 85.93, difference_count: 7, escape_count: 3, home_count: 6,
    makuri_count: 3, mark_count: 0, win_rate_percent: 16.6};
  const contextRiders = riders.map(({number, registration}) => ({number, registration, stats: {...stats},
    comment: {state:'SUMMARIZED', code:'SELF_POWER', summary:'自分で仕掛ける方針。'},
    recent_results: [{day:'2026-11-20', counts:[0,1,0,1,0,0,0,0,0]}, {day:'2026-11-19', rank:3}]}));
  const official = packet('RACE_AI_KEIRIN_PUBLIC_DOSSIER_CONTEXT_V1', {
    cutoff_at: cutoffAt, card_at: at, comments_at: at, comments_updated_at: at,
    card_sha256: sha, comments_sha256: sha, riders: contextRiders
  });
  const secondary = packet('RACE_AI_KEIRIN_PUBLIC_DOSSIER_SECONDARY_V1', {
    cutoff_at: cutoffAt, source_cutoff_at: cutoffAt, source_sha256: sha, source_at: at,
    source_url: 'https://keirin.kdreams.jp/matsudo/racedetail/3120261128010003/',
    riders: contextRiders.map(({recent_results, ...rider}) => ({...rider, stats:{...rider.stats, home_count:null}}))
  });
  const conditions = {...packet('RACE_AI_KEIRIN_PUBLIC_DOSSIER_CONDITIONS_V1', {list_sha256: sha, source_at: at}),
    calendar_sha256: sha, history: {scope:'OFFICIAL_SP_RESULT_REPLAY', source_sha256s: [sha], start_day:'2025-10-01',
      end_day:'2026-11-27', numeric_finishes:5, condition_matched_finishes:5},
    riders: [{registration:'014811', cells:[{meeting_grade:null,round_stage:'SEMI_FINAL',wins:1,top2:2,top3:3,numeric_finishes:5}]}]};
  const details = packet('RACE_AI_KEIRIN_PUBLIC_FORECAST_DETAILS_V1', {saved_at: savedAt,
    b: {tickets: [[1,2,3]], reasons:['照合できた保存時の理由。'], scenarios:[{ticket:[1,2,3], orders:[ids, null, ids, ids, ids, ids]}]}});
  return {raceId: race, cutoffAt, publishedForecast: {savedAt,b:[[1,2,3]]}, packets:{
    starters:packet('RACE_AI_KEIRIN_PUBLIC_STARTERS_V1', {source_at: at, riders}), rank, official, secondary, conditions, details}};
}

test('binds all six packets to the established roster and separates each kind of evidence', () => {
  const input = fixtures();
  const card = prepare(input);
  assert.deepEqual(card.riders.map(rider=>rider.number), ids);
  const [first] = card.riders;
  assert.deepEqual(first.rank.probabilities, [.2,.2,.2,.2,.2]);
  assert.deepEqual(first.recent,[{day:'2026-11-20',counts:[0,1,0,1,0,0,0,0,0]}, {day:'2026-11-19',rank:3}]);
  assert.deepEqual(first.form,{numerator:2,denominator:3,startDay:'2026-11-19',endDay:'2026-11-20'});
  assert.deepEqual(first.semi,{numerator:3,denominator:5,startDay:'2025-10-01',endDay:'2026-11-27'});
  assert.equal(first.stats.source,'official');
  assert.equal(first.comment.summary,'自分で仕掛ける方針。');
  assert.deepEqual(first.tactics.positions,[[1,null,1,1,1,1]]);
  assert.equal(card.cutoffAt,cutoffAt);
});

test('a checked public roster supplies identities even when the preserved rank group has no registrations', () => {
  const input = fixtures();
  delete input.packets.starters;
  input.packets.rank.races[0].riders.forEach(row => { row.registration = null; });
  input.packets.referenceStarters = packet('RACE_AI_KEIRIN_PUBLIC_REFERENCE_STARTERS_V1', {
    source_url:'https://keirin.kdreams.jp/matsudo/racecard/31202611280100/',
    source_at:at, source_sha256:sha, riders,
  });
  const card = prepare(input);
  assert.equal(card.riders[0].registration, '014811');
  assert.equal(card.riders[0].stats.competition_points, 85.93);
  assert.deepEqual(card.riders[0].rank.probabilities, [.2,.2,.2,.2,.2]);
  assert.equal(card.rosterSource.url, input.packets.referenceStarters.races[0].source_url);
  input.packets.referenceStarters.races[0].source_url = 'https://keirin.kdreams.jp/matsudo/racecard/31202611270100/';
  assert.equal(prepare(input).riders[0].registration, null);
});

test('recovers the reviewed Seibuen starter order and published rates without generating a forecast', () => {
  const card = prepare({raceId:'202611252611', archived});
  const [first] = card.riders;
  assert.equal(card.riders.length, 7);
  assert.equal(first.name.replace(/\s/g, ''), '山本勝利');
  assert.deepEqual([first.semi.numerator, first.semi.denominator], [10,11]);
  assert.deepEqual([first.venue.numerator, first.venue.denominator], [9,13]);
  assert.equal(first.style, '逃');
  assert.deepEqual([first.stats.back_count, first.stats.makuri_count, first.stats.difference_count], [10,4,1]);
  assert.match(first.comment.summary, /単騎/);
  assert.ok(first.recent.every(row => row.day < '2026-11-25'));
  assert.equal(first.rank, null);
  const unboundArchive = structuredClone(archived);
  unboundArchive.races[0].stats_sha256 = '';
  assert.deepEqual(prepare({raceId:'202611252611', archived:unboundArchive}).riders, []);
});

test('only combines an independently dated performance receipt with an exact secondary roster', () => {
  const input = fixtures();
  const row = input.packets.secondary.races[0];
  row.performance = {
    source_url: row.source_url + '?pageType=yoso', source_at: published, source_sha256: sha,
    riders:riders.map(({number,registration}) => ({number,registration,semi:[3,2,5,1],venue:[2,2,5,4]})),
  };
  assert.deepEqual([prepare(input).riders[0].venue.numerator, prepare(input).riders[0].venue.denominator], [9,13]);
  row.performance.riders[1].registration = '099999';
  assert.equal(prepare(input).riders[0].venue, null);
});

test('shows sparse archived finishes and only appends separately verified earlier race days', () => {
  const input = fixtures();
  input.packets.archive = {
    schema:'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_ARCHIVE_V1', start_day:'2023-11-29', end_day:'2026-11-22',
    source_sha256s:[sha], numeric_finishes:1,
    riders:[{registration:'014811', counts:[0,0,1,0,0,0,0,0,0], venues:{31:[1,1]}}],
  };
  const dayPacket = (day, id) => ({
    schema:'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_DAY_V1', day, source_sha256:sha,
    archive_races:1, verified_races:1, riders:[{registration:id, finish_counts:[0,1,0,0,0,0,0,0,0]}],
  });
  input.packets.recentDays = [dayPacket('2026-11-22','014811'), dayPacket('2026-11-27','014812'),
    dayPacket(day,'014811')];
  const [first, second] = prepare(input).riders;
  assert.deepEqual(first.history, {counts:[0,0,1,0,0,0,0,0,0], startDay:'2023-11-29', endDay:'2026-11-22'});
  assert.deepEqual(first.venue, {numerator:1,denominator:1,startDay:'2023-11-29',endDay:'2026-11-22'});
  assert.deepEqual(second.history, {counts:[0,1,0,0,0,0,0,0,0], startDay:'2026-11-27', endDay:'2026-11-27'});
  input.packets.archive.end_day = day;
  assert.equal(prepare(input).riders[0].venue, null);
  input.packets.archive.venue_start_day = '2023-11-29';
  input.packets.archive.venue_end_day = '2025-09-30';
  input.packets.recentDays = [];
  const earlierRace = prepare(input).riders[0];
  assert.equal(earlierRace.history, null);
  assert.equal(earlierRace.venue.denominator, 1);
});

test('holds mismatched contexts and never replaces the official names with a conflicting rank packet', () => {
  const input = fixtures();
  input.packets.official.races[0].riders[0].registration = '099999';
  input.packets.rank.races[0].riders[0].name = '別の選手';
  input.packets.details.races[0].saved_at = `${day}T11:59:59.000002+09:00`;
  const [first] = prepare(input).riders;
  assert.equal(first.style,'両');
  assert.equal(first.stats.source,'secondary');
  assert.deepEqual(first.recent,[]);
  assert.equal(first.rank,null);
  assert.equal(first.tactics,null);
});

test('admits the whole independently witnessed rank distribution or none of it', () => {
  const input = fixtures();
  delete input.packets.starters;
  assert.equal(prepare(input).riders.length,5);
  const participant = input.packets.rank.races[0].riders[0];
  participant.probabilities = [.3,.1,.2,.2,.2];
  assert.deepEqual(prepare(input).riders,[]);
  participant.probabilities = [.2,.2,.2,.2,.2];
  input.packets.rank.races[0].witnessed_at = cutoffAt;
  assert.deepEqual(prepare(input).riders,[]);
});

test('holds a rank packet that conflicts with a cutoff independently recovered from the current official card', () => {
  const input = fixtures();
  input.cutoffAt = null;
  input.packets.rank.races[0].cutoff_at = `${day}T12:02:00+09:00`;
  const view = prepare(input);
  assert.equal(view.cutoffAt,cutoffAt);
  assert.equal(view.riders[0].rank,null);
});

test('keeps unrelated day inputs and unconfirmed rank labels out of the dossier', () => {
  const input = fixtures();
  input.packets.official.day = '2026-11-27';
  input.packets.secondary.races[0].riders[0].comment.summary = '確認されていない文言';
  input.packets.conditions.history.end_day = day;
  input.packets.details.races[0].b.scenarios[0].orders[5] = [1,2,3,4,9];
  const [first] = prepare(input).riders;
  assert.equal(first.stats.source, 'secondary');
  assert.equal(first.comment,null);
  assert.equal(first.semi,null);
  assert.equal(first.tactics,null);
});

test('adds verified earlier daily finishes without inventing an order for same-day finishes', () => {
  const input = fixtures();
  const dayPacket = (day, finish_counts) => ({schema:'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_DAY_V1', day,
    source_sha256:sha, archive_races:4, verified_races:1, riders:[{registration:'014811', finish_counts}]});
  input.packets.recentDays = [dayPacket('2026-11-27',[0,0,0,0,1,0,0,0,0]),
    dayPacket('2026-11-28',[1,0,0,0,0,0,0,0,0]), dayPacket('2026-11-19',[0,1,0,0,0,0,0,0,0])];
  const [{recent}] = prepare(input).riders;
  assert.deepEqual(recent,[{day:'2026-11-27',rank:5}, {day:'2026-11-20',counts:[0,1,0,1,0,0,0,0,0]},
    {day:'2026-11-19',rank:3}]);
});
