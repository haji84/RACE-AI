'use strict';
// Invented fixtures only. These are not rider forecasts or evidence of accuracy.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const modulePath = path.join(__dirname, '../web/keirin-joint-forecast.js');
const J = fs.existsSync(modulePath) ? require(modulePath) : {};
const api = () => {
  assert.equal(typeof J.validateForecast, 'function', 'a forecast validator must be available');
  assert.equal(typeof J.renderForecast, 'function', 'a checked forecast renderer must be available');
  return J;
};
const RACE = '203001159801';
const SHA = 'a'.repeat(64);
const SOURCE_TIME = '2030-01-15T01:00:00.000001Z';

function tuples(cars, places) {
  const out = [];
  function visit(order) {
    if (order.length === places) { out.push(order); return; }
    for (const car of cars) if (!order.includes(car)) visit([...order, car]);
  }
  visit([]);
  return out;
}

function fixture({ cars = [1, 2, 3, 4], uniform = false } = {}) {
  // A hand-defined full-order law: 75% original order, 25% one-place rotation.
  // The 9-car stress fixture instead uses the uniform full-order law.
  const rotated = [...cars.slice(1), cars[0]];
  const probabilities = places => tuples(cars, places).map(order => ({ order,
    probability: uniform ? 1 / tuples(cars, places).length :
      (order.every((car, index) => car === cars[index]) ? .75 : 0) +
      (order.every((car, index) => car === rotated[index]) ? .25 : 0) }));
  return {
    schema: 'RACE_AI_KEIRIN_JOINT_FORECAST_V1', race_id: RACE,
    generated_at: '2030-01-15T01:01:00.000002Z',
    cutoff_at: '2030-01-15T03:00:00Z', source_as_of: SOURCE_TIME,
    source_forecast_generated_at: SOURCE_TIME,
    model_id: 'invented-comparison-B', model_version: 'fixture-only-v1',
    input_sha256: 'b'.repeat(64), source_packet_sha256: SHA,
    scope: 'PROSPECTIVE_RESEARCH', premise: 'ALL_FINISH_NO_TIES',
    calibration_status: 'UNVALIDATED', cars: cars.slice(),
    trifectas: probabilities(3), exactas: probabilities(2),
    riders: cars.map(car => {
      const ranks = cars.map((_, index) => uniform ? 1 / cars.length :
        (cars[index] === car ? .75 : 0) + (rotated[index] === car ? .25 : 0));
      return { car, name: '架空選手' + car, registration: car === cars[0] ? '999901' : null,
        rank_probabilities: ranks,
        top2_probability: ranks.slice(0, 2).reduce((sum, p) => sum + p, 0),
        top3_probability: ranks.slice(0, 3).reduce((sum, p) => sum + p, 0),
        outside_top3_probability: ranks.slice(3).reduce((sum, p) => sum + p, 0),
        most_likely_rank: uniform ? 1 : cars.indexOf(car) + 1,
        expected_rank: uniform ? (cars.length + 1) / 2 :
          .75 * (cars.indexOf(car) + 1) + .25 * (rotated.indexOf(car) + 1) };
    })
  };
}

function binding(value) {
  return { race_id: value.race_id, cars: value.cars.slice(),
    source_packet_sha256: value.source_packet_sha256,
    source_forecast_generated_at: value.source_forecast_generated_at,
    cutoff_at: value.cutoff_at, source_as_of: value.source_as_of };
}

function projection() {
  const value = fixture();
  const rank = rows => rows.filter(row => row.probability > 0).sort((a, b) => b.probability - a.probability);
  const projected = { ...value, schema: 'RACE_AI_KEIRIN_JOINT_PROJECTION_V1',
    source_joint_sha256: 'c'.repeat(64),
    ranked_markets: { '3t': rank(value.trifectas), '2t': rank(value.exactas) } };
  delete projected.trifectas;
  delete projected.exactas;
  return projected;
}

function rejected(change, value = fixture()) {
  const b = binding(value);
  change(value, b);
  assert.throws(() => api().validateForecast(value, b), /KEIRIN_JOINT_FORECAST_INVALID/);
}

test('a complete weighted joint law is admitted without changing the saved record or confidence', () => {
  const value = fixture(), before = JSON.stringify(value);
  value.evidence = { reference: 'future source evidence may be added' };
  const checked = api().validateForecast(value, binding(value));
  assert.equal(checked, value);
  assert.equal(checked.riders[0].top3_probability, .75);
  assert.equal(checked.riders[0].expected_rank, 1.75);
  delete value.evidence;
  assert.equal(JSON.stringify(value), before);
  assert.equal(Object.hasOwn(value, 'confidence'), false);
});

test('the source binding is mandatory and rejects another race, field, packet or source forecast time', () => {
  const value = fixture();
  assert.throws(() => api().validateForecast(value), /KEIRIN_JOINT_FORECAST_INVALID/);
  for (const [field, wrong] of [ ['race_id', '203001159802'], ['cars', [1, 2, 3]],
    ['source_packet_sha256', 'd'.repeat(64)], ['source_forecast_generated_at', '2030-01-15T01:00:00.000002Z'] ]) {
    assert.throws(() => api().validateForecast(value, { ...binding(value), [field]: wrong }), /KEIRIN_JOINT_FORECAST_INVALID/, field);
  }
  rejected((record, b) => { record.input_sha256 = 'not-a-hash'; });
  rejected((record, b) => { record.source_packet_sha256 = b.source_packet_sha256 = 'not-a-hash'; });
});

test('all distinct ordered triples and pairs are required including zero-probability events', () => {
  rejected(value => { value.trifectas.pop(); });
  rejected(value => { value.exactas.pop(); });
  rejected(value => { value.trifectas[1] = structuredClone(value.trifectas[0]); });
  rejected(value => { value.exactas[1] = structuredClone(value.exactas[0]); });
  rejected(value => { value.trifectas[0].order = [1, 1, 2]; });
  rejected(value => { value.exactas[0].order = [1, 9]; });
});

test('a changed pair law is rejected even when its total is still one', () => {
  rejected(value => { value.exactas.find(row => row.order.join() === '1,2').probability -= .1;
    value.exactas.find(row => row.order.join() === '1,3').probability += .1; });
});

test('first-three rider marginals must agree with the same full triple law', () => {
  rejected(value => {
    const a = value.riders[0], b = value.riders[1];
    for (const key of ['rank_probabilities', 'top2_probability', 'top3_probability',
      'outside_top3_probability', 'most_likely_rank', 'expected_rank']) {
      [a[key], b[key]] = [b[key], a[key]];
    }
  });
});

test('all rider rows and finishing-place columns must each sum to one', () => {
  rejected(value => { value.riders[0].rank_probabilities[3] += .01; });
  const value = fixture({ cars: [1, 2, 3, 4, 5] });
  rejected(record => { record.riders[0].rank_probabilities[3] += .1;
    record.riders[0].rank_probabilities[4] -= .1; }, value);
});

test('every rider summary agrees with the admitted rank probabilities', () => {
  for (const field of ['top2_probability', 'top3_probability', 'outside_top3_probability', 'expected_rank']) {
    rejected(value => { value.riders[0][field] += .1; });
  }
  rejected(value => { value.riders[0].most_likely_rank = 4; });
});

test('nonfinite, boolean, negative and excessive mass never reach the renderer', () => {
  for (const bad of [NaN, Infinity, -Infinity, true, -.01, 1.01, '0.75']) {
    rejected(value => { value.trifectas[0].probability = bad; });
    rejected(value => { value.riders[0].rank_probabilities[0] = bad; });
  }
  rejected(value => { value.trifectas.find(row => row.probability === .75).probability -= .1; });
});

test('duplicate or substituted riders and invalid registrations cannot borrow the field identity', () => {
  rejected(value => { value.cars[3] = value.cars[0]; });
  rejected(value => { value.riders[1].car = value.riders[0].car; });
  rejected(value => { value.riders[1].car = 9; });
  rejected(value => { value.riders[0].registration = 'provider-id'; });
  rejected(value => { value.riders[1].registration = value.riders[0].registration; });
});

test('prospective data cannot use future sources or reach the cutoff including microseconds', () => {
  rejected(value => { value.source_as_of = '2030-01-15T01:01:00.000003Z'; });
  rejected(value => { value.cutoff_at = value.generated_at; });
  rejected((value, b) => { value.source_forecast_generated_at = b.source_forecast_generated_at = '2030-01-15T04:00:00Z'; });
  rejected(value => { value.generated_at = '2030-02-30T01:00:00Z'; });
  rejected(value => { value.scope = 'PRODUCTION'; });
  rejected(value => { value.scope = 'RETROSPECTIVE_RESEARCH'; });
  rejected(value => { value.calibration_status = 'CALIBRATED'; });
  rejected(value => { value.premise = 'UNCONDITIONAL'; });
  const value = fixture();
  value.cutoff_at = '2030-01-15T01:01:00.000003Z';
  assert.equal(api().validateForecast(value, binding(value)), value);
});

test('cutoff and source clocks must match authoritative bindings and the race day', () => {
  for (const key of ['cutoff_at', 'source_as_of']) rejected((value, b) => { delete b[key]; });
  rejected(value => { value.cutoff_at = '2031-01-15T03:00:00Z'; });
  rejected(value => { value.source_as_of = '2030-01-15T00:59:00Z'; });
  rejected((value, b) => { value.cutoff_at = b.cutoff_at = '2031-01-15T03:00:00Z'; });
  rejected((value, b) => { value.source_as_of = b.source_as_of = '2030-01-15T01:00:00.000002Z'; });
  const nextDay = fixture(); nextDay.cutoff_at = '2030-01-16T03:00:00Z';
  assert.equal(api().validateForecast(nextDay, binding(nextDay)), nextDay);
});

test('a nine-car field retains all 504 triples, 72 pairs and nine places without inflating ties', () => {
  const value = fixture({ cars: [1, 2, 3, 4, 5, 6, 7, 8, 9], uniform: true });
  assert.equal(value.trifectas.length, 504);
  assert.equal(value.exactas.length, 72);
  api().validateForecast(value, binding(value));
  const html = api().renderForecast(value, 9);
  assert.equal((html.match(/<meter\b/g) || []).length, 9);
  assert.match(html, /9着/);
  assert.match(html, /11\.1%/);
  assert.match(html, /5\.00/);
});

test('rendering requires an admitted source and shows all ranks, summaries and the conditional premise', () => {
  const value = fixture();
  assert.throws(() => api().renderForecast(value, 1), /KEIRIN_JOINT_FORECAST_INVALID/);
  api().validateForecast(value, binding(value));
  const html = api().renderForecast(value, 1);
  assert.equal((html.match(/<meter\b/g) || []).length, 4);
  assert.match(html, /75\.0%/);
  assert.match(html, /25\.0%/);
  assert.match(html, /1\.75/);
  assert.match(html, /2着以内/);
  assert.match(html, /3着以内/);
  assert.match(html, /着外/);
  assert.match(html, /全員完走/);
  assert.match(html, /同着なし/);
  assert.match(html, /未校正/);
  assert.match(html, /比較B/);
  assert.match(html, /999901/);
  assert.match(api().renderForecast(value, 2), /登録番号[^<]*未取得|登録番号[\s\S]*未取得/);
  assert.throws(() => api().renderForecast(value, 9), /KEIRIN_JOINT_FORECAST_INVALID/);
});

test('retrospective rendering clearly separates the new comparison from saved old tickets', () => {
  const value = fixture();
  value.scope = 'RETROSPECTIVE_RESEARCH';
  value.generated_at = '2030-01-16T03:00:00Z';
  api().validateForecast(value, binding(value));
  const html = api().renderForecast(value, 1);
  assert.match(html, /締切後.*参考解析/);
  assert.match(html, /保存済み.*旧.*買い目.*別/);
  assert.match(html, /2030-01-16T03:00:00Z/);
  assert.match(html, /fixture-only-v1/);
});

test('rendered strings are escaped and later mutations cannot change checked display values', () => {
  const value = fixture();
  value.riders[0].name = '<img src=x onerror="alert(1)">';
  value.model_id = '<svg onload="alert(2)">';
  value.model_version = "v1' onclick='bad";
  api().validateForecast(value, binding(value));
  const html = api().renderForecast(value, 1);
  assert.doesNotMatch(html, /<img|<svg|["'] onclick=/);
  assert.match(html, /&lt;img/);
  assert.match(html, /&quot;/);
  assert.match(html, /&#39;/);
  value.riders[0].rank_probabilities[0] = NaN;
  value.riders[0].name = 'changed after validation';
  assert.equal(api().renderForecast(value, 1), html);
});

test('the shared renderer supports the host self-only style policy without inline styles', () => {
  const value = fixture();
  api().validateForecast(value, binding(value));
  const html = api().renderForecast(value, 1);
  assert.doesNotMatch(html, /<style\b|\sstyle=/i);
  assert.match(html, /class="kn-joint-ranks"/);
  assert.match(html, /class="kn-joint-summary"/);
});

test('a bounded projection preserves probabilities and declares that it is derived evidence', () => {
  const value = projection();
  value.ranked_markets['3t'] = value.ranked_markets['3t'].slice(0, 1);
  value.ranked_markets['2t'] = value.ranked_markets['2t'].slice(0, 1);
  api().validateForecast(value, binding(value));
  const html = api().renderForecast(value, 1);
  assert.match(html, /派生/);
  assert.match(html, /原本.*認証|認証.*原本/);
  assert.match(html, new RegExp('c'.repeat(64)));
  assert.match(html, /75\.0%/);
  assert.equal(value.ranked_markets['3t'][0].probability, .75);
  assert.equal(Object.hasOwn(value, 'trifectas'), false);
});

test('a projection rejects invalid, duplicate, unsorted or overfull selected market events', () => {
  rejected(value => { value.source_joint_sha256 = ''; }, projection());
  rejected(value => { value.trifectas = []; }, projection());
  rejected(value => { value.ranked_markets['3t'][0].order = [1, 1, 2]; }, projection());
  rejected(value => { value.ranked_markets['2t'][1] = structuredClone(value.ranked_markets['2t'][0]); }, projection());
  rejected(value => { value.ranked_markets['3t'].reverse(); }, projection());
  rejected(value => { value.ranked_markets['3t'][0].probability = .8; }, projection());
  rejected(value => { value.ranked_markets['2t'][0].probability = 1.1; }, projection());
  rejected(value => { value.ranked_markets['3t'] = tuples(value.cars, 3).slice(0, 9).map(order => ({ order, probability: 0 })); }, projection());
});

test('selected projection mass cannot exceed rank and top-two/top-three marginal bounds', () => {
  const value = projection();
  value.ranked_markets['3t'] = [{ order: [1, 2, 3], probability: .6 }, { order: [1, 2, 4], probability: .2 }];
  rejected(() => {}, value);
  rejected(record => { record.riders[0].top3_probability = 1; }, projection());
});

test('selected ranks remain nonincreasing even when an inversion is smaller than the sum tolerance', () => {
  rejected(value => {
    value.ranked_markets['2t'][0].probability = .25;
    value.ranked_markets['2t'][1].probability = .250000000001;
  }, projection());
});

test('a displayed exacta must include the mass of its displayed trifecta prefixes', () => {
  rejected(value => { value.ranked_markets['2t'].forEach(row => { row.probability = 0; }); }, projection());
});

test('the browser global exposes the same validation and rendering behavior without CommonJS', () => {
  const context = {};
  vm.runInNewContext(fs.existsSync(modulePath) ? fs.readFileSync(modulePath, 'utf8') : '', context);
  assert.equal(typeof context.RaceKeirinJointForecast?.validateForecast, 'function');
  const value = fixture();
  context.RaceKeirinJointForecast.validateForecast(value, binding(value));
  assert.match(context.RaceKeirinJointForecast.renderForecast(value, 1), /75\.0%/);
});
