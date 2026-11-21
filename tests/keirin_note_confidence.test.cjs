'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const C = require('../web/confidence.js'), M = require('../web/keirin-note-model.js'), F = require('../web/keirin-note-feed.js');
const { frozenRow } = require('./keirin_note_frozen_fixture.cjs');
const { DAY, RACE, nationwideDoc, nationwidePacket } = require('./keirin_note_nationwide_fixture.cjs');
const sorted = value => Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
const sha = value => createHash('sha256').update(JSON.stringify(sorted(value))).digest('hex');
const source = value => { const text = JSON.stringify(value); return { text, bytes: Buffer.byteLength(text), sha256: createHash('sha256').update(text).digest('hex') }; };
const ticketHash = tickets => sha(tickets.map(ticket => Array.isArray(ticket) ? ticket : ticket.combo.split('-').map(Number)).sort((a, b) => a.join('-').localeCompare(b.join('-'))));
const ranks = { '未評価': 0, '低': 1, '中': 2, '高': 3, '激アツ': 4 };
function entry(universe, tickets, { grade = '高', market = '3t', strategy = 'normal' } = {}) {
  const unassessed = grade === '未評価';
  const share = [null, .2, .6, .8, .95][ranks[grade]], triple = [null, .2, .65, .85, .95][ranks[grade]];
  return { grade, rank: ranks[grade], market, strategy, tickets_sha256: ticketHash(tickets),
    metrics: { scenario_count: universe.scenarios.length, axis_cars: unassessed ? [] : [1], axis_top2_share: share, pair_top4_share: share, triple_top6_share: market === '2t' ? null : triple,
      scenario_coverage: share, major_uncovered_ids: [], evidence_kind: universe.evidence_kind, weight_basis: universe.evidence_kind === 'canonical_b_orders' ? 'canonical_relative_research' : 'equal_scenarios', late_phase_axis_presence: null },
    reasons: [{ code: 'SYNTHETIC_SAVED_REASON', message: '表示検証用の架空の保存評価です。', scenario_ids: universe.scenarios.map(scenario => scenario.id) }], limitations: ['的中率は未校正です。'] };
}
function baselineBundle(row, grades = { A: '高', B: '中' }) {
  const baseline = row.baseline, universe = C.universeFromBaseline(baseline, row.facts);
  return { schema: C.SCHEMA, rules_version: C.RULES, race_id: RACE, assessed_at: baseline.generated_at, cutoff: baseline.published_cutoff_at,
    source_prediction_sha256: baseline.prediction_sha256, source_facts_sha256: baseline.source_facts_sha256, scenario_universe_sha256: sha(universe),
    evaluations: Object.fromEntries(['A', 'B'].map(name => [name, entry(universe, baseline[name].ranked_tickets, { grade: grades[name] })])) };
}
function national(grades) {
  const doc = nationwideDoc({ conditioned: true });
  doc.races[0].original.confidence_assessment = baselineBundle(doc.races[0].original, grades);
  return doc;
}
function packet(files) {
  return { schema: M.SCHEMA, formal_model_admission: false, production_weight_switch: false, source_commit: 'a'.repeat(40), imported_at: DAY + 'T01:10:00Z', dates: [DAY], files: Object.fromEntries(Object.entries(files).map(([name, value]) => ['data/' + DAY + '/' + name, source(value)])) };
}
function roster() {
  return { races: [{ race_id: RACE, venue: '架空場', race_no: 1, deadline_time: '12:00', riders: [1, 2, 3, 4, 5].map(number => ({ number, name: '架空' + number })), lines: [[1, 2, 3], [4, 5]] }] };
}
function authoredUniverse() {
  return { schema: C.UNIVERSE_SCHEMA, race_id: RACE, source_as_of: DAY + 'T00:59:00Z', cutoff: DAY + 'T03:00:00Z', source_prediction_sha256: '3'.repeat(64), source_facts_sha256: '4'.repeat(64), cars: [1, 2, 3, 4, 5], evidence_kind: 'authored_goals', candidate_origin: 'independent_preselection_v1',
    source_status: { lineup: 'published_prediction', required_missing: [], conflicting_fields: [] },
    scenarios: [{ id: 'MAIN', role: 'main', counter_family: null, phases: ['初周の仮定', '打鐘の仮定', '最終ホームの仮定', '最終バックの仮定', '4コーナーの仮定', 'ゴールの仮定'], goal_candidates: { '3t': [[1, 2, 3]], '2t': [[1, 2]] }, research_weight: null },
      { id: 'COUNTER', role: 'counter', counter_family: 'counterattack', phases: ['初周の別展開', '打鐘の別展開', '最終ホームの別展開', '最終バックの別展開', '4コーナーの別展開', 'ゴールの別展開'], goal_candidates: { '3t': [[2, 1, 3]], '2t': [[2, 1]] }, research_weight: null }] };
}
function authored({ market = '3t', strategy = 'normal', grade = '高', rollover } = {}) {
  const universe = authoredUniverse(), tickets = [{ combo: market === '2t' ? '1-2' : '1-2-3', role: '本線' }];
  const raw = { race_id: RACE, analysis_created_at: DAY + 'T01:00:00Z', deadline_jst: universe.cutoff, market, strategy, headline: '架空の保存予想', reason: '架空の根拠', risk: '表示検証用', tickets,
    scenarios: universe.scenarios.map(scenario => ({ scenario_id: scenario.id, six_phases: scenario.phases })), confidence_universe: universe };
  if (strategy === 'rollover') raw.eligible = true;
  if (rollover) raw.rollover = rollover;
  const body = structuredClone(raw);if (body.rollover) delete body.rollover.confidence_assessment;
  raw.confidence_assessment = { schema: C.SCHEMA, rules_version: C.RULES, race_id: RACE, assessed_at: raw.analysis_created_at, cutoff: raw.deadline_jst,
    source_prediction_sha256: sha(body), source_facts_sha256: universe.source_facts_sha256, scenario_universe_sha256: sha(universe), evaluations: { selected: entry(universe, tickets, { grade, market, strategy }) } };
  return raw;
}

test('labels and rated filters keep historical aliases without inventing unknown ratings', () => {
  for (const [raw, label, rank] of [['高い', '高', 3], ['高め', '高', 3], ['中位', '中', 2], ['低め', '低', 1], ['控えめ', '低', 1], ['激アツ', '激アツ', 4], [null, '未評価', 0], ['constructor', '未評価', 0]]) assert.deepEqual(C.normalize(raw), { label, rank });
  assert.equal(C.displayLabel('激アツ'), '激アツ🔥');
  for (const filter of ['high_plus', 'hot', 'high', 'medium', 'low', 'unrated']) assert.equal(C.predictionMatches({ confidence: '激アツ', tickets: [] }, filter), false);
  assert.equal(C.predictionMatches({ confidence: '高', tickets: [{}] }, 'high_plus'), true);
  assert.equal(C.predictionMatches({ confidence: '中', tickets: [{}] }, 'high_plus'), false);
  assert.equal(C.matches('高', 'hot'), false);
  assert.equal(C.matches(null, 'unrated'), true);
});
test('saved baseline grades remain independent and only matching frozen arms pass the high-plus filter', async () => {
  const doc = national(), before = JSON.stringify(doc), data = await M.openPacket(nationwidePacket(doc)), row = M.rows(data, DAY)[0];
  assert.equal(M.frozenArm(row, 'A').confidence, '高');assert.equal(M.frozenArm(row, 'B').confidence, '中');
  const displayed = ['A', 'B', 'adjusted_A', 'adjusted_B'].map(name => M.frozenArm(row, name)).filter(value => C.predictionMatches(value, 'high_plus'));
  assert.deepEqual(displayed.map(value => value.name), ['A']);
  assert.equal(M.frozenArm(row, 'adjusted_A').confidence, null);assert.equal(M.frozenArm(row, 'adjusted_B').confidence, null);
  assert.equal(M.frozenArm(row, 'A').confidenceAssessment.reasons[0].message, '表示検証用の架空の保存評価です。');
  assert.equal(M.forecast(row, '2t', 'A').confidence, null);
  assert.equal(JSON.stringify(doc), before);
});
test('validated assessments are immutable without freezing their surrounding race rows', async () => {
  const data = await M.openPacket(nationwidePacket(national())), row = M.rows(data, DAY)[0];
  const bundle = row.frozenForecast.confidence_assessment, before = JSON.stringify(bundle), saved = M.frozenArm(row, 'A');
  assert.equal(Object.isFrozen(row), false);assert.equal(Object.isFrozen(row.frozenForecast), false);
  for (const value of [bundle, bundle.evaluations, saved.confidenceAssessment, saved.confidenceAssessment.metrics, saved.confidenceAssessment.metrics.axis_cars, saved.confidenceAssessment.reasons, saved.confidenceAssessment.reasons[0], saved.confidenceAssessment.reasons[0].scenario_ids, saved.confidenceAssessment.limitations]) assert.equal(Object.isFrozen(value), true);
  assert.throws(() => { bundle.evaluations.A.grade = '激アツ'; }, TypeError);
  assert.throws(() => { saved.confidenceAssessment.rank = 4; }, TypeError);
  assert.equal(M.frozenArm(row, 'A').confidence, '高');assert.equal(C.selected(bundle, 'A').confidenceAssessment.rank, 3);
  assert.equal(JSON.stringify(bundle), before);
});
test('reference envelopes carry saved A/B ratings without applying them to 2t, C or other tickets', async () => {
  const original = frozenRow(), envelope = { input: original.facts, output: original.baseline, confidence_assessment: baselineBundle(original, { A: '激アツ', B: '低' }) };
  const data = await M.openPacket(packet({ 'races.json': roster(), 'reference_AB.json': [envelope] })), row = M.rows(data, DAY)[0];
  assert.equal(M.forecast(row, '3t', 'A').confidence, '激アツ');assert.equal(M.forecast(row, '3t', 'B').confidence, '低');
  assert.equal(M.forecast(row, '2t', 'A').confidence, null);assert.equal(M.forecast(row, '3t', 'C').confidence, null);
  assert.equal(M.forecast(row, '3t', 'original').confidence, '');
});
test('wrong hashes, scope, rank, source facts and pre-cutoff time bindings reject the whole new packet', async () => {
  const changes = [
    r => { r.confidence_assessment.evaluations.A.rank = 4; }, r => { r.confidence_assessment.evaluations.A.grade = '高め'; },
    r => { r.confidence_assessment.evaluations.A.grade = '激アツ';r.confidence_assessment.evaluations.A.rank = 4; },
    r => { r.confidence_assessment.evaluations.A.market = '2t'; }, r => { r.confidence_assessment.evaluations.A.strategy = 'rollover'; },
    r => { r.confidence_assessment.evaluations.A.tickets_sha256 = '0'.repeat(64); }, r => { r.confidence_assessment.source_prediction_sha256 = '0'.repeat(64); },
    r => { r.confidence_assessment.source_facts_sha256 = '0'.repeat(64); }, r => { r.confidence_assessment.scenario_universe_sha256 = '0'.repeat(64); },
    r => { r.confidence_assessment.assessed_at = DAY + 'T00:59:59Z'; }, r => { r.confidence_assessment.assessed_at = DAY + 'T01:00:02Z'; },
    r => { r.confidence_assessment.cutoff = DAY + 'T01:01:04Z'; }, r => { r.facts.riders[0].style = 'UNKNOWN'; },
    r => { r.confidence_assessment.evaluations.A.metrics.axis_top2_share = 1.1; }, r => { r.confidence_assessment.evaluations.A.reasons[0].scenario_ids = ['NOT_SAVED']; },
    r => { r.confidence_assessment.extra = true; }, r => { r.confidence_assessment = null; },
  ];
  for (const change of changes) { const doc = national();change(doc.races[0].original);await assert.rejects(() => M.openPacket(nationwidePacket(doc))); }
});
test('positive saved grades reject unknown, missing or conflicting source fields even with matching updated hashes', async () => {
  for (const status of [{ lineup: 'unknown', required_missing: [], conflicting_fields: [] }, { lineup: 'published_prediction', required_missing: ['riders.1.style'], conflicting_fields: [] }, { lineup: 'published_prediction', required_missing: [], conflicting_fields: ['lineup'] }]) {
    const raw = authored();raw.confidence_universe.source_status = status;
    raw.confidence_assessment.scenario_universe_sha256 = sha(raw.confidence_universe);
    raw.confidence_assessment.source_prediction_sha256 = sha(C.authoredPredictionBody(raw));
    await assert.rejects(() => M.openPacket(packet({ 'forecasts.json': [raw] })));
  }
});
test('old originals stay unrated and refresh cannot add or rewrite a baseline sidecar', async () => {
  const old = await M.openPacket(nationwidePacket()), fresh = await M.openPacket(nationwidePacket(national()));
  assert.equal(M.frozenArm(M.rows(old, DAY)[0], 'A').confidence, null);
  assert.throws(() => F.merge([old, fresh]));
  const changed = national({ A: '激アツ', B: '中' });changed.revision = '2'.repeat(64);changed.observed_at = DAY + 'T05:00:00Z';
  assert.throws(() => F.merge([fresh, { ...fresh, nationwide: new Map([[DAY, changed]]) }]));
});
test('mixed imported and frozen cards expose the same high-grade candidates without treating 3t baselines as 2t or rollover', async () => {
  const imported = await M.openPacket(packet({ 'races.json': roster(), 'forecasts.json': [{ race_id: RACE, confidence: '中位', tickets: [{ combo: '1-2-3', role: '本線' }] }],
    'two_car_forecasts.json': [{ race_id: RACE, confidence: '低め', tickets: [{ combo: '1-2', role: '本線' }], rollover: { eligible: true, confidence: '低め', tickets: [{ combo: '1-2', role: '本線' }] } }] }));
  const nationalData = await M.openPacket(nationwidePacket(national())), row = M.rows(F.merge([imported, nationalData]), DAY)[0];
  assert.equal(row.nationwideOnly, undefined);assert.equal(M.forecast(row, '3t', 'original').confidence, '中位');
  const high = M.displayedPredictions(row, '3t', 'original').filter(value => C.predictionMatches(value, 'high_plus'));
  assert.deepEqual(high.map(value => value.name), ['A']);
  assert.equal(M.displayedPredictions(row, '2t', 'original').some(value => C.predictionMatches(value, 'high_plus')), false);
  assert.equal(M.displayedPredictions(row, '2t', 'rollover').some(value => C.predictionMatches(value, 'high_plus')), false);
  assert.equal(M.displayedPredictions(row, '3t', 'rollover').some(value => C.predictionMatches(value, 'high_plus')), false);
});
test('authored normal, 2t and rollover assessments bind their own raw records and never inherit grades', async () => {
  const child = authored({ market: '2t', strategy: 'rollover', grade: '低' }), two = authored({ market: '2t', grade: '高', rollover: child }), three = authored({ grade: '激アツ' }), roll = authored({ strategy: 'rollover', grade: '中' });
  const p = packet({ 'races.json': roster(), 'forecasts.json': [three], 'two_car_forecasts.json': [two], 'three_car_rollover_forecasts.json': [roll],
    'flexible_forecasts.json': { races: [{ race_id: RACE, markets: { '3t': { tickets: [{ combo: '2-1-3', role: '本線' }] } } }] } });
  const before = JSON.stringify(p), row = M.rows(await M.openPacket(p), DAY)[0];
  assert.equal(M.forecast(row, '3t', 'original').confidence, '激アツ');assert.equal(M.forecast(row, '2t', 'original').confidence, '高');
  assert.equal(M.forecast(row, '3t', 'rollover').confidence, '中');assert.equal(M.forecast(row, '2t', 'rollover').confidence, '低');
  assert.equal(M.forecast(row, '3t', 'flexible').confidence, '');
  assert.equal(C.matches(M.forecast(row, '2t', 'rollover').confidence, 'high_plus'), false);
  assert.equal(JSON.stringify(p), before);
});
test('selected authored invalid data cannot fall back to an older label and child tampering is rejected', async () => {
  const invalid = authored();invalid.confidence = '激アツ';invalid.confidence_assessment.evaluations.selected.rank = 1;
  await assert.rejects(() => M.openPacket(packet({ 'forecasts.json': [invalid] })));
  const child = authored({ market: '2t', strategy: 'rollover' }), two = authored({ market: '2t', rollover: child });
  two.rollover.confidence_assessment.evaluations.selected.tickets_sha256 = '0'.repeat(64);
  await assert.rejects(() => M.openPacket(packet({ 'two_car_forecasts.json': [two] })));
});
test('historical 2t rollover uses only eligible child tickets and does not create candidates for other races', async () => {
  const data = await M.openPacket(packet({ 'two_car_forecasts.json': [{ race_id: RACE, confidence: '中位', tickets: [{ combo: '1-2', role: '本線' }], rollover: { eligible: true, tickets: [{ combo: '2-1', role: '本線' }] } }] })), row = M.rows(data, DAY)[0];
  assert.equal(M.forecast(row, '2t', 'rollover').confidence, '中位');assert.equal(M.forecast(row, '2t', 'rollover').tickets[0].combo, '2-1');
  assert.equal(M.forecast(row, '3t', 'rollover').tickets.length, 0);
  assert.equal(M.forecast({ ...row, two: { ...row.two, rollover: { eligible: false } } }, '2t', 'rollover').tickets.length, 0);
});

module.exports = { authored, authoredUniverse, baselineBundle, entry, packet, roster };
