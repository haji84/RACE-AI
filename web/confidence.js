/* Presentation and validation of saved assessments. This module never assigns a grade. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RaceKeirinConfidence = factory();
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';

  const SCHEMA = 'RACE_AI_KEIRIN_CONFIDENCE_ASSESSMENT_V1';
  const RULES = 'research-coherence-v1';
  const UNIVERSE_SCHEMA = 'RACE_AI_KEIRIN_CONFIDENCE_UNIVERSE_V1';
  const PHASES = ['INITIAL', 'BELL', 'FINAL_HOME', 'FINAL_BACK', 'FOURTH_CORNER', 'GOAL'];
  // Immutable research-coherence-v1 acceptance constraints. These only reject
  // contradictory saved metrics/grades; they never create or change a rating.
  const V1_GRADE_CONSTRAINTS = [[4, .85, .85, .90, .90], [3, .70, .70, .80, .80], [2, .50, .50, .60, .50]];
  const GRADES = new Map([['未評価', 0], ['低', 1], ['中', 2], ['高', 3], ['激アツ', 4]]);
  const verified = new WeakSet();
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const exact = (value, names) => record(value) && Object.keys(value).sort().join(',') === names.slice().sort().join(',');
  const need = condition => { if (!condition) throw new Error('KEIRIN_CONFIDENCE_INVALID'); };
  const hex = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const bounded = (value, max) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
  const ratio = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  const unique = values => new Set(values).size === values.length;
  const canonical = value => JSON.stringify(value && typeof value === 'object'
    ? Array.isArray(value) ? value.map(item => JSON.parse(canonical(item)))
      : Object.fromEntries(Object.keys(value).sort().map(key => [key, JSON.parse(canonical(value[key]))]))
    : value);
  function timestamp(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value)) return null;
    const time = Date.parse(value), date = value.slice(0, 10), midnight = Date.parse(date + 'T00:00:00Z');
    if (!Number.isFinite(time) || !Number.isFinite(midnight) || new Date(midnight).toISOString().slice(0, 10) !== date || Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59) return null;
    return time;
  }
  function timestampMicros(value) {
    const milliseconds = timestamp(value);if (milliseconds === null) return null;
    const fraction = /\.(\d{1,6})(?:Z|[+-]\d\d:\d\d)$/.exec(value)?.[1] || '';
    return BigInt(milliseconds) * 1000n + BigInt(fraction.padEnd(6, '0').slice(3));
  }
  async function digest(value) {
    const crypto = globalThis.crypto?.subtle ? globalThis.crypto : require('node:crypto').webcrypto;
    const bytes = new TextEncoder().encode(canonical(value));
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
  }

  function normalize(raw) {
    switch (typeof raw === 'string' ? raw.trim() : null) {
      case '激アツ':
      case '激アツ🔥': return { label: '激アツ', rank: 4 };
      case '高':
      case '高い':
      case '高め': return { label: '高', rank: 3 };
      case '中':
      case '中位': return { label: '中', rank: 2 };
      case '低':
      case '低め':
      case '控えめ': return { label: '低', rank: 1 };
      default: return { label: '未評価', rank: 0 };
    }
  }
  function displayLabel(raw) {
    const value = normalize(raw);
    return value.rank === 4 ? '激アツ🔥' : value.label;
  }
  function matches(raw, filter = 'all') {
    const { rank } = normalize(raw);
    switch (filter) {
      case 'all': return true;
      case 'high_plus': return rank >= 3;
      case 'hot': return rank === 4;
      case 'high': return rank === 3;
      case 'medium': return rank === 2;
      case 'low': return rank === 1;
      case 'unrated': return rank === 0;
      default: return false;
    }
  }
  function predictionMatches(prediction, filter = 'all') {
    return filter === 'all' || Boolean(prediction?.tickets?.length && matches(prediction.confidence, filter));
  }
  function selected(bundle, name) {
    if (bundle == null) return { confidence: null, confidenceAssessment: null, confidenceBundle: null };
    need(verified.has(bundle));
    const entry = bundle.evaluations[name];
    return { confidence: entry?.grade ?? null, confidenceAssessment: entry || null, confidenceBundle: entry ? bundle : null };
  }

  function ticketArrays(values, market, cars) {
    const places = market === '2t' ? 2 : 3;
    need(Array.isArray(values) && values.length <= 504);
    const tuples = values.map(value => {
      const tuple = Array.isArray(value) ? value : typeof value?.combo === 'string' && new RegExp('^[1-9](?:-[1-9]){' + (places - 1) + '}$').test(value.combo) ? value.combo.split('-').map(Number) : null;
      need(Array.isArray(tuple) && tuple.length === places && unique(tuple) && tuple.every(car => Number.isInteger(car) && car >= 1 && car <= 9 && (!cars || cars.includes(car))));
      return tuple.slice();
    });
    need(unique(tuples.map(tuple => tuple.join('-'))));
    return tuples.sort((a, b) => a.join('-').localeCompare(b.join('-')));
  }
  function checkedUniverse(universe) {
    need(exact(universe, ['schema', 'race_id', 'source_as_of', 'cutoff', 'source_prediction_sha256', 'source_facts_sha256', 'cars', 'evidence_kind', 'candidate_origin', 'source_status', 'scenarios']));
    need(universe.schema === UNIVERSE_SCHEMA && /^20\d{10}$/.test(universe.race_id) && timestamp(universe.source_as_of) !== null && timestamp(universe.cutoff) !== null);
    need(hex(universe.source_prediction_sha256) && hex(universe.source_facts_sha256));
    need(Array.isArray(universe.cars) && universe.cars.length >= 5 && universe.cars.length <= 9 && unique(universe.cars) && universe.cars.every((car, index) => Number.isInteger(car) && car >= 1 && car <= 9 && (!index || universe.cars[index - 1] < car)));
    need(['canonical_b_orders', 'authored_goals'].includes(universe.evidence_kind) && ['canonical_projection_v1', 'independent_preselection_v1', 'legacy_ticket_links'].includes(universe.candidate_origin));
    const status = universe.source_status;
    need(exact(status, ['lineup', 'required_missing', 'conflicting_fields']) && ['published_prediction', 'not_applicable_girls', 'unknown'].includes(status.lineup));
    for (const key of ['required_missing', 'conflicting_fields']) need(Array.isArray(status[key]) && status[key].length <= 128 && unique(status[key]) && status[key].every(value => bounded(value, 200)));
    need(Array.isArray(universe.scenarios) && universe.scenarios.length > 0 && universe.scenarios.length <= 128);
    const ids = new Set();
    for (const scenario of universe.scenarios) {
      need(exact(scenario, ['id', 'role', 'counter_family', 'phases', 'goal_candidates', 'research_weight']) && bounded(scenario.id, 120) && !ids.has(scenario.id));
      ids.add(scenario.id);
      need(['main', 'counter'].includes(scenario.role) && (scenario.role === 'main' ? scenario.counter_family === null : ['counterattack', 'follower_sashi', 'late_sprint', 'pace_fade', 'other'].includes(scenario.counter_family)));
      need(Array.isArray(scenario.phases) && scenario.phases.length <= 128);
      const prose = scenario.phases.every(phase => bounded(phase, 2000));
      if (!prose) scenario.phases.forEach(phase => {
        need(exact(phase, ['phase', 'projected_order', 'projected_top3', 'hypothesis_actions', 'actual_rider_position_video_verified']) && PHASES.includes(phase.phase) && phase.actual_rider_position_video_verified === false);
        need(Array.isArray(phase.projected_order) && phase.projected_order.length === universe.cars.length && unique(phase.projected_order) && phase.projected_order.every(car => universe.cars.includes(car)));
        need(canonical(phase.projected_top3) === canonical(phase.projected_order.slice(0, 3)) && Array.isArray(phase.hypothesis_actions) && phase.hypothesis_actions.length > 0 && phase.hypothesis_actions.length <= 32 && phase.hypothesis_actions.every(action => bounded(action, 120) && /^[A-Z][A-Z0-9_]*$/.test(action)));
      });
      need(record(scenario.goal_candidates) && Object.keys(scenario.goal_candidates).length > 0 && Object.keys(scenario.goal_candidates).every(market => ['3t', '2t'].includes(market)));
      for (const [market, candidates] of Object.entries(scenario.goal_candidates)) {
        need(ticketArrays(candidates, market, universe.cars).length > 0);
        const goal = scenario.phases.find(phase => record(phase) && phase.phase === 'GOAL');
        if (goal) need(candidates.some(candidate => canonical(candidate) === canonical(goal.projected_order.slice(0, market === '2t' ? 2 : 3))));
      }
      if (universe.evidence_kind === 'canonical_b_orders') need(!prose && typeof scenario.research_weight === 'string' && /^(?:0\.\d{12}|1\.000000000000)$/.test(scenario.research_weight) && Number(scenario.research_weight) > 0);
      else need(scenario.research_weight === null);
    }
    if (universe.evidence_kind === 'canonical_b_orders') need(Math.abs(universe.scenarios.reduce((sum, scenario) => sum + Number(scenario.research_weight), 0) - 1) <= 1e-8);
    return ids;
  }
  function universeFromBaseline(baseline, source) {
    need(record(baseline) && record(source) && Array.isArray(source.riders) && Array.isArray(baseline.B?.six_phase_scenarios));
    const riders = source.riders.slice().sort((a, b) => a.car - b.car), missing = [];
    for (const rider of riders) {
      if (rider.competition_points <= 0) missing.push('riders.' + rider.car + '.competition_points');
      if (rider.style === 'UNKNOWN') missing.push('riders.' + rider.car + '.style');
    }
    const families = [
      ['pace_fade', ['FRONT_LEADER_PACE_FADE']], ['late_sprint', ['LATE_SPRINT_OVERTAKE']],
      ['follower_sashi', ['FOLLOWER_SASHI_SCENARIO']], ['counterattack', ['CHALLENGER_EARLY_COUNTER', 'CHALLENGER_MAKURI']],
    ];
    return {
      schema: UNIVERSE_SCHEMA, race_id: baseline.race_id, source_as_of: baseline.source_as_of, cutoff: baseline.published_cutoff_at,
      source_prediction_sha256: baseline.prediction_sha256, source_facts_sha256: baseline.source_facts_sha256,
      cars: riders.map(rider => rider.car), evidence_kind: 'canonical_b_orders', candidate_origin: 'canonical_projection_v1',
      source_status: { lineup: source.competition === 'GIRLS' ? 'not_applicable_girls' : 'published_prediction', required_missing: missing, conflicting_fields: [] },
      scenarios: baseline.B.six_phase_scenarios.map(scenario => {
        const actions = scenario.six_phases.flatMap(phase => phase.hypothesis_actions);
        const family = families.find(([, labels]) => labels.some(label => actions.includes(label)))?.[0] || null;
        return { id: scenario.scenario_id, role: family ? 'counter' : 'main', counter_family: family, phases: scenario.six_phases,
          goal_candidates: { '3t': [scenario.projected_3ren_tan], '2t': [scenario.projected_3ren_tan.slice(0, 2)] }, research_weight: scenario.relative_research_weight.toFixed(12) };
      }),
    };
  }
  function authoredPredictionBody(raw) {
    const value = Object.fromEntries(Object.entries(raw).filter(([key]) => key !== 'confidence_assessment'));
    if (Object.hasOwn(value, 'rollover')) value.rollover = authoredPredictionBody(value.rollover);
    return value;
  }
  function freezeAssessment(value) {
    if (value !== null && typeof value === 'object') {
      for (const child of Object.values(value)) freezeAssessment(child);
      Object.freeze(value);
    }
    return value;
  }
  async function validate(bundle, context) {
    need(exact(bundle, ['schema', 'rules_version', 'race_id', 'assessed_at', 'cutoff', 'source_prediction_sha256', 'source_facts_sha256', 'scenario_universe_sha256', 'evaluations']));
    need(bundle.schema === SCHEMA && bundle.rules_version === RULES && bundle.race_id === context.raceId && bundle.cutoff === context.cutoff);
    const assessed = timestampMicros(bundle.assessed_at), generated = timestampMicros(context.generatedAt), cutoff = timestampMicros(bundle.cutoff), sourceAt = timestampMicros(context.universe.source_as_of);
    need(assessed !== null && generated !== null && cutoff !== null && sourceAt !== null && sourceAt <= generated && generated <= assessed && cutoff - assessed >= 65000000n);
    if (context.sealedAt !== undefined) {
      const sealed = timestampMicros(context.sealedAt);need(sealed !== null && assessed <= sealed && cutoff - sealed >= 65000000n);
    }
    for (const name of ['source_prediction_sha256', 'source_facts_sha256', 'scenario_universe_sha256']) need(hex(bundle[name]));
    need(bundle.source_prediction_sha256 === context.predictionSha256 && bundle.source_facts_sha256 === context.universe.source_facts_sha256);
    const ids = checkedUniverse(context.universe);
    need(context.universe.race_id === bundle.race_id && context.universe.cutoff === bundle.cutoff && await digest(context.universe) === bundle.scenario_universe_sha256);
    need(exact(bundle.evaluations, Object.keys(context.evaluations)));
    for (const [name, expected] of Object.entries(context.evaluations)) {
      const entry = bundle.evaluations[name];
      need(exact(entry, ['grade', 'rank', 'market', 'strategy', 'tickets_sha256', 'metrics', 'reasons', 'limitations']) && GRADES.has(entry.grade) && entry.rank === GRADES.get(entry.grade));
      need(entry.market === expected.market && entry.strategy === expected.strategy && hex(entry.tickets_sha256));
      need(await digest(ticketArrays(expected.tickets, entry.market, context.universe.cars)) === entry.tickets_sha256);
      const metrics = entry.metrics;
      need(exact(metrics, ['scenario_count', 'axis_cars', 'axis_top2_share', 'pair_top4_share', 'triple_top6_share', 'scenario_coverage', 'major_uncovered_ids', 'evidence_kind', 'weight_basis', 'late_phase_axis_presence']));
      need(Number.isInteger(metrics.scenario_count) && metrics.scenario_count === ids.size && metrics.scenario_count <= 128 && Array.isArray(metrics.axis_cars) && metrics.axis_cars.length <= 2 && unique(metrics.axis_cars) && metrics.axis_cars.every(car => context.universe.cars.includes(car)));
      for (const key of ['axis_top2_share', 'pair_top4_share', 'triple_top6_share', 'scenario_coverage', 'late_phase_axis_presence']) need(metrics[key] === null || ratio(metrics[key]));
      if (entry.rank === 0) need(metrics.axis_cars.length === 0 && ['axis_top2_share', 'pair_top4_share', 'triple_top6_share', 'scenario_coverage', 'late_phase_axis_presence'].every(key => metrics[key] === null) && Array.isArray(metrics.major_uncovered_ids) && metrics.major_uncovered_ids.length === 0);
      else {
        need(['axis_top2_share', 'pair_top4_share', 'scenario_coverage'].every(key => metrics[key] !== null) && (entry.market !== '3t' || metrics.triple_top6_share !== null));
        need(context.universe.scenarios.every(scenario => scenario.phases.length === 6 && (typeof scenario.phases[0] === 'string' || scenario.phases.every((phase, index) => phase.phase === PHASES[index])) && Object.hasOwn(scenario.goal_candidates, entry.market)));
        const status = context.universe.source_status;
        need(status.lineup !== 'unknown' && status.required_missing.length === 0 && status.conflicting_fields.length === 0);
      }
      if (entry.market === '2t') need(metrics.triple_top6_share === null);
      need(Array.isArray(metrics.major_uncovered_ids) && unique(metrics.major_uncovered_ids) && metrics.major_uncovered_ids.every(id => ids.has(id)));
      if (entry.rank > 0) {
        const accepted = V1_GRADE_CONSTRAINTS.find(([rank, axis, pair, triple, coverage]) => metrics.axis_top2_share >= axis && metrics.pair_top4_share >= pair && (entry.market === '2t' || metrics.triple_top6_share >= triple) && metrics.scenario_coverage >= coverage && (rank < 3 || metrics.major_uncovered_ids.length === 0));
        need(entry.rank === (accepted ? accepted[0] : 1));
      }
      need(metrics.evidence_kind === context.universe.evidence_kind && metrics.weight_basis === (context.universe.evidence_kind === 'canonical_b_orders' ? 'canonical_relative_research' : 'equal_scenarios'));
      need(Array.isArray(entry.reasons) && entry.reasons.length > 0 && entry.reasons.length <= 128);
      for (const reason of entry.reasons) need(exact(reason, ['code', 'message', 'scenario_ids']) && bounded(reason.code, 120) && /^[A-Z][A-Z0-9_]*$/.test(reason.code) && bounded(reason.message, 2000) && Array.isArray(reason.scenario_ids) && unique(reason.scenario_ids) && reason.scenario_ids.every(id => ids.has(id)));
      need(Array.isArray(entry.limitations) && entry.limitations.length > 0 && entry.limitations.length <= 32 && entry.limitations.every(value => bounded(value, 2000)));
      if (context.universe.candidate_origin === 'legacy_ticket_links') need(entry.rank === 0);
    }
    freezeAssessment(bundle);
    verified.add(bundle);
    return bundle;
  }
  async function validateBaseline(bundle, baseline, { source, sealedAt, raceId = baseline?.race_id } = {}) {
    need(record(baseline) && baseline.schema === 'RACE_AI_KEIRIN_AUTOMATIC_MARKS_AND_SIX_PHASE_V1' && baseline.race_id === raceId && hex(baseline.prediction_sha256) && hex(baseline.source_facts_sha256));
    const universe = universeFromBaseline(baseline, source);
    return validate(bundle, { raceId, cutoff: baseline.published_cutoff_at, generatedAt: baseline.generated_at, sealedAt, predictionSha256: baseline.prediction_sha256, universe,
      evaluations: Object.fromEntries(['A', 'B'].map(name => [name, { market: '3t', strategy: 'normal', tickets: baseline[name]?.ranked_tickets }])) });
  }
  async function validateAuthored(raw, { raceId, market, strategy }) {
    const keys = ['race_id', 'analysis_created_at', 'deadline_jst', 'market', 'strategy', 'headline', 'reason', 'risk', 'tickets', 'scenarios', 'confidence_universe', 'confidence_assessment'];
    if (strategy === 'rollover') { keys.push('eligible');need(raw.eligible === true); }
    if (Object.hasOwn(raw, 'rollover')) { keys.push('rollover');need(market === '2t' && strategy === 'normal'); }
    need(exact(raw, keys) && raw.race_id === raceId && raw.market === market && raw.strategy === strategy);
    for (const field of ['headline', 'reason', 'risk']) need(bounded(raw[field], 2000));
    need(Array.isArray(raw.tickets) && raw.tickets.length > 0 && raw.tickets.every(ticket => exact(ticket, ['combo', 'role']) && bounded(ticket.role, 30)));
    const universe = raw.confidence_universe;
    need(record(universe) && universe.evidence_kind === 'authored_goals' && universe.candidate_origin === 'independent_preselection_v1');
    checkedUniverse(universe);
    need(raw.confidence_assessment?.assessed_at === raw.analysis_created_at && canonical(raw.scenarios) === canonical(universe.scenarios.map(scenario => ({ scenario_id: scenario.id, six_phases: scenario.phases }))));
    if (Object.hasOwn(raw, 'rollover')) {
      await validateAuthored(raw.rollover, { raceId, market: '2t', strategy: 'rollover' });
      need(canonical(raw.rollover.confidence_universe) === canonical(universe) && timestampMicros(raw.rollover.analysis_created_at) <= timestampMicros(raw.analysis_created_at));
    }
    return validate(raw.confidence_assessment, { raceId, cutoff: raw.deadline_jst, generatedAt: raw.analysis_created_at, predictionSha256: await digest(authoredPredictionBody(raw)), universe,
      evaluations: { selected: { market, strategy, tickets: raw.tickets } } });
  }

  return { normalize, displayLabel, matches, predictionMatches, selected, validate, validateBaseline, validateAuthored, universeFromBaseline, authoredPredictionBody, canonical, digest, timestamp, SCHEMA, RULES, UNIVERSE_SCHEMA };
});
