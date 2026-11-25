/* Checked comparison-B probabilities. This module never changes saved tickets or grades. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RaceKeirinJointForecast = factory();
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';

  const FULL = 'RACE_AI_KEIRIN_JOINT_FORECAST_V1';
  const PROJECTION = 'RACE_AI_KEIRIN_JOINT_PROJECTION_V1';
  const TOLERANCE = 1e-8;
  const checked = new WeakMap();
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const need = condition => { if (!condition) throw new Error('KEIRIN_JOINT_FORECAST_INVALID'); };
  const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const text = (value, max) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
  const probability = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  const close = (a, b) => Math.abs(a - b) <= TOLERANCE;
  const sum = values => values.reduce((total, value) => total + value, 0);
  const field = cars => Array.isArray(cars) && cars.length >= 3 && cars.length <= 9 &&
    new Set(cars).size === cars.length && cars.every(car => Number.isInteger(car) && car >= 1 && car <= 9);
  const sameField = (a, b) => field(a) && field(b) && a.length === b.length && a.every(car => b.includes(car));
  const escape = value => String(value).replace(/[&<>"']/g, character =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);

  function timestamp(value) {
    if (typeof value !== 'string') return null;
    const parts = /^(\d{4}-\d{2}-\d{2})T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?(Z|[+-]\d\d:\d\d)$/.exec(value);
    if (!parts || Number(parts[2]) > 23 || Number(parts[3]) > 59 || Number(parts[4]) > 59) return null;
    const midnight = Date.parse(parts[1] + 'T00:00:00Z'), milliseconds = Date.parse(value);
    if (!Number.isFinite(midnight) || !Number.isFinite(milliseconds) ||
      new Date(midnight).toISOString().slice(0, 10) !== parts[1]) return null;
    // Preserve Python's six-digit clocks at the cutoff; Date.parse alone drops microseconds.
    return BigInt(milliseconds) * 1000n + BigInt((parts[5] || '').padEnd(6, '0').slice(3));
  }

  function events(rows, places, cars, maximum, complete) {
    need(Array.isArray(rows) && rows.length <= maximum && (!complete || rows.length === maximum));
    const seen = new Set();
    for (const row of rows) {
      need(object(row) && Array.isArray(row.order) && row.order.length === places &&
        new Set(row.order).size === places && row.order.every(car => Number.isInteger(car) && cars.includes(car)) &&
        probability(row.probability));
      const key = row.order.join('-');
      need(!seen.has(key));
      seen.add(key);
    }
    if (complete) need(close(sum(rows.map(row => row.probability)), 1));
    return rows;
  }

  function riders(record) {
    const cars = record.cars, n = cars.length;
    need(Array.isArray(record.riders) && record.riders.length === n);
    const byCar = new Map(), registrations = new Set();
    for (const rider of record.riders) {
      need(object(rider) && Number.isInteger(rider.car) && cars.includes(rider.car) && !byCar.has(rider.car) &&
        text(rider.name, 200) && (rider.registration === null ||
          typeof rider.registration === 'string' && /^\d{6}$/.test(rider.registration)));
      if (rider.registration !== null) {
        need(!registrations.has(rider.registration));
        registrations.add(rider.registration);
      }
      const ranks = rider.rank_probabilities;
      need(Array.isArray(ranks) && ranks.length === n && ranks.every(probability) && close(sum(ranks), 1));
      for (const name of ['top2_probability', 'top3_probability', 'outside_top3_probability']) need(probability(rider[name]));
      need(close(rider.top2_probability, sum(ranks.slice(0, 2))) &&
        close(rider.top3_probability, sum(ranks.slice(0, 3))) &&
        close(rider.outside_top3_probability, sum(ranks.slice(3))));
      const mode = ranks.reduce((best, p, index) => p > ranks[best] ? index : best, 0) + 1;
      need(Number.isInteger(rider.most_likely_rank) && rider.most_likely_rank === mode &&
        typeof rider.expected_rank === 'number' && Number.isFinite(rider.expected_rank) &&
        rider.expected_rank >= 1 && rider.expected_rank <= n &&
        close(rider.expected_rank, sum(ranks.map((p, index) => p * (index + 1)))));
      byCar.set(rider.car, rider);
    }
    for (let place = 0; place < n; place++) need(close(sum(record.riders.map(rider => rider.rank_probabilities[place])), 1));
    return byCar;
  }

  function completeLaw(record, byCar) {
    const n = record.cars.length;
    const triples = events(record.trifectas, 3, record.cars, n * (n - 1) * (n - 2), true);
    const pairs = events(record.exactas, 2, record.cars, n * (n - 1), true);
    const mass = new Map(record.cars.map(car => [car, [0, 0, 0]])), pairMass = new Map();
    for (const row of triples) {
      row.order.forEach((car, place) => { mass.get(car)[place] += row.probability; });
      const key = row.order.slice(0, 2).join('-');
      pairMass.set(key, (pairMass.get(key) || 0) + row.probability);
    }
    for (const row of pairs) need(close(row.probability, pairMass.get(row.order.join('-'))));
    for (const car of record.cars) for (let place = 0; place < 3; place++) {
      need(close(byCar.get(car).rank_probabilities[place], mass.get(car)[place]));
    }
  }

  function projectionLaw(record, byCar) {
    need(hash(record.source_joint_sha256) && !Object.hasOwn(record, 'trifectas') &&
      !Object.hasOwn(record, 'exactas') && object(record.ranked_markets));
    for (const [market, places, maximum] of [['3t', 3, 8], ['2t', 2, 4]]) {
      const rows = events(record.ranked_markets[market], places, record.cars, maximum, false);
      need(sum(rows.map(row => row.probability)) <= 1 + TOLERANCE);
      const mass = new Map(record.cars.map(car => [car, Array(places).fill(0)]));
      rows.forEach((row, index) => {
        if (index) need(row.probability <= rows[index - 1].probability);
        row.order.forEach((car, place) => {
          need(row.probability <= byCar.get(car).rank_probabilities[place] + TOLERANCE);
          mass.get(car)[place] += row.probability;
        });
      });
      // Selected events are disjoint. Their partial mass must also fit each marginal.
      for (const car of record.cars) {
        const selected = mass.get(car), rider = byCar.get(car);
        selected.forEach((p, place) => need(p <= rider.rank_probabilities[place] + TOLERANCE));
        need(sum(selected.slice(0, 2)) <= rider.top2_probability + TOLERANCE &&
          sum(selected) <= rider.top3_probability + TOLERANCE);
      }
    }
    const selectedTriples=new Map();
    for(const row of record.ranked_markets['3t']){
      const key=row.order.slice(0,2).join('-');
      selectedTriples.set(key,(selectedTriples.get(key)||0)+row.probability);
    }
    for(const row of record.ranked_markets['2t'])need(row.probability+TOLERANCE>=(selectedTriples.get(row.order.join('-'))||0));
  }

  function validateForecast(record, binding) {
    need(object(record));
    checked.delete(record);
    need([FULL, PROJECTION].includes(record.schema) && object(binding) &&
      typeof record.race_id === 'string' && /^20\d{10}$/.test(record.race_id) &&
      record.race_id === binding.race_id && sameField(record.cars, binding.cars) &&
      hash(record.input_sha256) && hash(record.source_packet_sha256) &&
      record.source_packet_sha256 === binding.source_packet_sha256 &&
      record.source_forecast_generated_at === binding.source_forecast_generated_at &&
      text(record.model_id, 200) && text(record.model_version, 200) &&
      ['PROSPECTIVE_RESEARCH', 'RETROSPECTIVE_RESEARCH'].includes(record.scope) &&
      record.premise === 'ALL_FINISH_NO_TIES' && record.calibration_status === 'UNVALIDATED');
    const generated = timestamp(record.generated_at), cutoff = timestamp(record.cutoff_at);
    const asOf = timestamp(record.source_as_of), sourceGenerated = timestamp(record.source_forecast_generated_at);
    need(generated !== null && cutoff !== null && asOf !== null && sourceGenerated !== null &&
      record.cutoff_at===binding.cutoff_at && record.source_as_of===binding.source_as_of &&
      asOf <= sourceGenerated && sourceGenerated <= generated);
    const raceDate=record.race_id.slice(0,4)+'-'+record.race_id.slice(4,6)+'-'+record.race_id.slice(6,8);
    const raceDay=Date.parse(raceDate+'T00:00:00Z');
    need(Number.isFinite(raceDay)&&new Date(raceDay).toISOString().slice(0,10)===raceDate);
    const cutoffDay=Date.parse(new Date(Number(cutoff/1000n)+9*3600000).toISOString().slice(0,10)+'T00:00:00Z');
    need(cutoffDay>=raceDay&&cutoffDay<=raceDay+86400000);
    need(record.scope === (generated < cutoff ? 'PROSPECTIVE_RESEARCH' : 'RETROSPECTIVE_RESEARCH'));
    if (record.scope === 'PROSPECTIVE_RESEARCH') need(generated < cutoff && asOf < cutoff && sourceGenerated < cutoff);
    const byCar = riders(record);
    if (record.schema === FULL) completeLaw(record, byCar);
    else projectionLaw(record, byCar);
    // Keep only checked display fields in private memory. Caller-owned source bytes stay untouched.
    const snapshot = {};
    for (const key of ['schema', 'race_id', 'model_id', 'model_version', 'scope', 'generated_at',
      'cutoff_at', 'source_as_of', 'source_forecast_generated_at', 'input_sha256',
      'source_packet_sha256', 'source_joint_sha256']) snapshot[key] = record[key];
    snapshot.riders = new Map([...byCar].map(([car, rider]) => [car, {
      car, name: rider.name, registration: rider.registration, rank_probabilities: rider.rank_probabilities.slice(),
      top2_probability: rider.top2_probability, top3_probability: rider.top3_probability,
      outside_top3_probability: rider.outside_top3_probability,
      most_likely_rank: rider.most_likely_rank, expected_rank: rider.expected_rank
    }]));
    checked.set(record, snapshot);
    return record;
  }

  function renderForecast(record, car) {
    const snapshot = checked.get(record), rider = snapshot?.riders.get(car);
    need(snapshot && Number.isInteger(car) && rider);
    const percent = p => (p * 100).toFixed(1) + '%';
    const clock = (label, value) => '<p>' + label + ' <time datetime="' + escape(value) + '">' + escape(value) + '</time></p>';
    const summary = [
      ['2着以内', percent(rider.top2_probability)], ['3着以内', percent(rider.top3_probability)],
      ['着外（4着以下）', percent(rider.outside_top3_probability)],
      ['最頻着順', rider.most_likely_rank + '着'], ['期待着順', rider.expected_rank.toFixed(2)],
      ['登録番号', rider.registration || '未取得']
    ];
    const projection = snapshot.schema === PROJECTION;
    return '<section class="kn-joint-forecast" aria-label="' +
      escape(car + '番の比較B・着順確率') + '" data-joint-race="' + escape(snapshot.race_id) + '">' +
      '<h3>' + escape(car + '番 ' + rider.name) + ' · 比較Bの着順確率</h3>' +
      '<p class="kn-joint-scope">' + (snapshot.scope === 'PROSPECTIVE_RESEARCH' ?
        '締切前に生成した研究予測' : '締切後の参考解析・事後研究') + ' · 確率は未校正</p>' +
      '<p>全員完走・同着なしを条件とする確率です。欠場・失格・落車・同着を含む無条件の確率ではありません。</p>' +
      '<p>比較Bの新しい解析です。保存済みの旧買い目とは別です。信頼度の格上げには使用していません。</p>' +
      '<ol class="kn-joint-ranks">' + rider.rank_probabilities.map((p, index) =>
        '<li><span>' + (index + 1) + '着</span><meter min="0" max="1" value="' + p +
        '" aria-label="' + (index + 1) + '着の予測確率">' + percent(p) + '</meter><span>' + percent(p) + '</span></li>').join('') +
      '</ol><dl class="kn-joint-summary">' +
      summary.map(([label, value]) => '<div><dt>' + label + '</dt><dd>' + escape(value) + '</dd></div>').join('') + '</dl>' +
      '<details class="kn-joint-source"><summary>モデル・出典・予想時点</summary><p>モデル ' + escape(snapshot.model_id) +
      ' · 版 ' + escape(snapshot.model_version) + '</p>' + clock('比較Bの生成', snapshot.generated_at) +
      clock('資料の基準', snapshot.source_as_of) + clock('元資料の予想時点', snapshot.source_forecast_generated_at) +
      clock('掲載締切', snapshot.cutoff_at) + '<p>元資料SHA256 ' + escape(snapshot.source_packet_sha256) +
      '</p><p>比較B入力SHA256 ' + escape(snapshot.input_sha256) + '</p>' + (projection ?
        '<p>元同時分布SHA256 ' + escape(snapshot.source_joint_sha256) + '</p><p>同時分布の出典ハッシュに結んだ派生表示です。' +
        'この画面は予想原本を独立認証しません。選択した上位買い目を100%へ正規化していません。</p>' :
        '<p>全三連単・二車単・上位3着の周辺確率を同じ分布として検査しました。出典資料の真正性の独立認証は別途必要です。</p>') +
      '</details></section>';
  }

  return { validateForecast, renderForecast };
});
