/* Shared money contract. Decimal arithmetic uses scaled BigInt, never binary floats.
 * Estimates are decimal strings; final official payouts and actual stakes are yen integers.
 * Source confirmation is the caller's responsibility. See docs/MONEY_ENGINE.md. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RaceMoney = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const MAX = 9007199254740991n;
  const SCALE = 1000000n;
  const SQUARED = SCALE * SCALE;
  const TYPES = Object.freeze({trifecta: [3, false], trio: [3, true], exacta: [2, false],
    quinella: [2, true], quinella_place: [2, true], win: [1, false], place: [1, false]});
  const REFUNDS = ['cancelled', 'no_contest', 'postponed'];
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

  class MoneyError extends Error {
    constructor(message) { super(message); this.name = 'MoneyError'; }
  }
  function integer(value, name, unit = 1, positive = false) {
    if (!Number.isSafeInteger(value) || value < (positive ? 1 : 0) || value % unit !== 0) {
      throw new MoneyError(`${name} must be a bounded nonnegative integer in ${unit}-yen units`);
    }
    return value;
  }
  function safe(value, name) {
    if (value < 0n || value > MAX) throw new MoneyError(`${name} exceeds integer range`);
    return Number(value);
  }
  function decimal(value, name) {
    if (!['string', 'number'].includes(typeof value)) throw new MoneyError(`${name} must be a fixed decimal`);
    const raw = String(value);
    if (!/^\d{1,16}(?:\.\d{1,6})?$/.test(raw)) {
      throw new MoneyError(`${name} must be a finite fixed decimal with at most six decimal places`);
    }
    const [whole, fraction = ''] = raw.split('.');
    return BigInt(whole) * SCALE + BigInt(fraction.padEnd(6, '0'));
  }
  function text(value, name) {
    if (typeof value !== 'string' || !/^[A-Za-z0-9_.:-]{1,128}$/.test(value)) throw new MoneyError(`invalid ${name}`);
    return value;
  }
  function fixed(value, digits) {
    const negative = value < 0n;
    let raw = (negative ? -value : value).toString().padStart(digits + 1, '0');
    if (digits) raw = `${raw.slice(0, -digits)}.${raw.slice(-digits)}`.replace(/0+$/, '').replace(/\.$/, '');
    return `${negative && raw !== '0' ? '-' : ''}${raw}`;
  }
  function ratio(numerator, denominator) {
    if (denominator === 0n) return null;
    const scaled = numerator * 100n * SCALE;
    return fixed(scaled / denominator + (scaled % denominator * 2n >= denominator ? 1n : 0n), 6);
  }
  function estimate_bet(stake_yen, probability, odds) {
    const stake = integer(stake_yen, 'stake_yen', 100);
    const p = decimal(probability, 'probability'), o = decimal(odds, 'odds');
    if (p > SCALE || o < SCALE || o > 1000000n * SCALE) throw new MoneyError('probability must be 0..1 and odds 1..1000000');
    const s = BigInt(stake), payout = o * s, expected = p * o * s;
    return {stake_yen: stake, probability: fixed(p, 6), odds: fixed(o, 6),
      payout_if_hit_yen: fixed(payout, 6), profit_if_hit_yen: fixed(payout - s * SCALE, 6),
      expected_payout_yen: fixed(expected, 12), expected_profit_yen: fixed(expected - s * SQUARED, 12),
      expected_roi_percent: stake ? fixed(p * o * 100n, 12) : null,
      expected_profit_percent: stake ? fixed((p * o - SQUARED) * 100n, 12) : null};
  }
  function combination(row) {
    if (!object(row) || typeof row.bet_type !== 'string' || !own(TYPES, row.bet_type)) throw new MoneyError('unsupported bet_type');
    const [size, unordered] = TYPES[row.bet_type];
    let value = row.combination;
    if (typeof value === 'string') {
      if (!/^[1-6](?:-[1-6])*$/.test(value)) throw new MoneyError('invalid combination');
      value = value.split('-').map(Number);
    }
    if (!Array.isArray(value) || value.length !== size || value.some(x => !Number.isInteger(x) || x < 1 || x > 6)
        || new Set(value).size !== size) throw new MoneyError('combination must contain distinct boat numbers 1..6');
    return unordered ? value.slice().sort((a, b) => a - b) : value.slice();
  }
  const key = row => `${row.bet_type}:${row.combination.join('-')}`;
  function bets(input) {
    if (!Array.isArray(input) || input.length > 120) throw new MoneyError('bets must be a list of at most 120 combinations');
    const normalized = [], seen = new Set(), probabilityTotals = new Map();
    let race = null;
    for (const row of input) {
      const combo = combination(row), race_id = text(row.race_id, 'race_id');
      if (race !== null && race_id !== race) throw new MoneyError('one purchase must refer to one race');
      race = race_id;
      const clean = {race_id, bet_type: row.bet_type, combination: combo, stake_yen: integer(row.stake_yen, 'stake_yen', 100, true)};
      if (seen.has(key(clean))) throw new MoneyError('duplicate combination');
      seen.add(key(clean));
      if (own(row, 'probability') || own(row, 'odds')) {
        const estimate = estimate_bet(clean.stake_yen, row.probability, row.odds);
        clean.probability = estimate.probability; clean.odds = estimate.odds;
        if (['trifecta', 'trio', 'exacta', 'quinella', 'win'].includes(clean.bet_type)) {
          const sum = (probabilityTotals.get(clean.bet_type) || 0n) + decimal(clean.probability, 'probability');
          if (sum > SCALE) throw new MoneyError('mutually exclusive ticket probabilities exceed one');
          probabilityTotals.set(clean.bet_type, sum);
        }
      }
      normalized.push(clean);
    }
    return normalized;
  }
  function limits(input) {
    if (!object(input)) throw new MoneyError('limits must be an object');
    const budget = integer(input.budget_yen, 'budget_yen', 100);
    const cap = own(input, 'max_bets') ? input.max_bets : 8;
    if (![8, 16, 24, 32].includes(cap)) throw new MoneyError('max_bets must be 8, 16, 24, or 32');
    return {budget_yen: budget, max_bets: cap,
      day_budget_yen: integer(own(input, 'day_budget_yen') ? input.day_budget_yen : budget, 'day_budget_yen', 100),
      day_spent_yen: integer(own(input, 'day_spent_yen') ? input.day_spent_yen : 0, 'day_spent_yen', 100),
      loss_limit_yen: integer(own(input, 'loss_limit_yen') ? input.loss_limit_yen : budget, 'loss_limit_yen'),
      loss_used_yen: integer(own(input, 'loss_used_yen') ? input.loss_used_yen : 0, 'loss_used_yen')};
  }
  const total = rows => safe(rows.reduce((sum, row) => sum + BigInt(row.stake_yen), 0n), 'total_stake_yen');
  function percentages(rows, spending) {
    if (!spending) return [];
    const denominator = BigInt(spending);
    const bases = rows.map(row => Number(BigInt(row.stake_yen) * 10000n / denominator));
    const order = rows.map((row, index) => ({index, remainder: BigInt(row.stake_yen) * 10000n % denominator}))
      .sort((a, b) => a.remainder === b.remainder ? a.index - b.index : (a.remainder > b.remainder ? -1 : 1));
    const missing = 10000 - bases.reduce((sum, value) => sum + value, 0);
    for (let i = 0; i < missing; i++) bases[order[i].index]++;
    return bases.map(value => `${Math.floor(value / 100)}.${String(value % 100).padStart(2, '0')}`);
  }
  function validate_purchase(input, configuration) {
    const rows = bets(input), policy = limits(configuration), spending = total(rows);
    if (rows.length > policy.max_bets) throw new MoneyError('maximum number of bets exceeded');
    if (spending > policy.budget_yen || BigInt(spending) + BigInt(policy.day_spent_yen) > BigInt(policy.day_budget_yen)
        || BigInt(spending) + BigInt(policy.loss_used_yen) > BigInt(policy.loss_limit_yen)) {
      throw new MoneyError('race, day, or loss budget exceeded');
    }
    const expected = rows.every(row => own(row, 'probability')) ? rows.reduce((sum, row) =>
      sum + decimal(row.probability, 'probability') * decimal(row.odds, 'odds') * BigInt(row.stake_yen), 0n) : null;
    return {bets: rows, total_stake_yen: spending, budget_yen: policy.budget_yen,
      remaining_budget_yen: policy.budget_yen - spending, allocation_percent: percentages(rows, spending),
      expected_payout_yen: expected === null ? null : fixed(expected, 12),
      expected_profit_yen: expected === null ? null : fixed(expected - BigInt(spending) * SQUARED, 12),
      expected_roi_percent: expected === null ? null : ratio(expected, BigInt(spending) * SQUARED)};
  }
  function settle_bets(input, official) {
    const rows = bets(input);
    if (!object(official) || official.confirmed !== true) throw new MoneyError('confirmed complete official result required');
    const race_id = text(official.race_id, 'race_id'), status = official.status;
    if (rows.some(row => row.race_id !== race_id)) throw new MoneyError('result and purchase race mismatch');
    if (own(official, 'verified_market_types')) {
      const markets = official.verified_market_types;
      if (!Array.isArray(markets) || markets.some(x => typeof x !== 'string' || !own(TYPES, x))
          || new Set(markets).size !== markets.length || rows.some(row => !markets.includes(row.bet_type))) {
        throw new MoneyError('purchased market has no complete verified official result');
      }
    }
    if (!['settled', 'dead_heat', 'special', ...REFUNDS].includes(status)) throw new MoneyError('result is not final');
    const payouts = official.payouts, refundRows = own(official, 'refunds') ? official.refunds : [],
      specials = own(official, 'special_payouts') ? official.special_payouts : [];
    if (![payouts, refundRows, specials].every(Array.isArray)) throw new MoneyError('explicit payouts list required');
    if (REFUNDS.includes(status) && (payouts.length || specials.length)) throw new MoneyError('cancelled result cannot also pay winnings');
    if (status === 'special' && !specials.length) throw new MoneyError('special payouts require explicit official values');
    if (status !== 'special' && specials.length) throw new MoneyError('special payouts require special status');
    const payoutMap = new Map(), refundMap = new Map(), specialMap = new Map();
    for (const entry of payouts) {
      const k = key({...entry, combination: combination(entry)});
      if (payoutMap.has(k)) throw new MoneyError('duplicate official payout');
      payoutMap.set(k, integer(entry.payout_per_100_yen, 'payout_per_100_yen', 1, true));
    }
    for (const entry of refundRows) {
      const k = key({...entry, combination: combination(entry)});
      if (refundMap.has(k)) throw new MoneyError('duplicate refund');
      refundMap.set(k, own(entry, 'refund_yen') ? integer(entry.refund_yen, 'refund_yen', 100, true) : null);
    }
    for (const entry of specials) {
      if (!object(entry) || typeof entry.bet_type !== 'string' || !own(TYPES, entry.bet_type)) throw new MoneyError('unsupported special bet_type');
      if (specialMap.has(entry.bet_type) || [...payoutMap.keys()].some(k => k.startsWith(`${entry.bet_type}:`))) {
        throw new MoneyError('duplicate or conflicting special payout');
      }
      specialMap.set(entry.bet_type, integer(entry.payout_per_100_yen, 'payout_per_100_yen', 1, true));
    }
    const settlements = rows.map(row => {
      const k = key(row), stake = row.stake_yen;
      const refund = REFUNDS.includes(status) ? stake :
        (refundMap.has(k) ? (refundMap.get(k) === null ? stake : refundMap.get(k)) : 0);
      if (refund > stake) throw new MoneyError('refund exceeds purchased amount');
      const effective = stake - refund, rate = payoutMap.has(k) ? payoutMap.get(k) : (specialMap.get(row.bet_type) || 0);
      const payout = safe(BigInt(effective) / 100n * BigInt(rate), 'payout_yen');
      return {...row, refund_yen: refund, effective_stake_yen: effective, payout_yen: payout, net_profit_yen: payout - effective};
    });
    const spending = total(rows), refund = safe(settlements.reduce((sum, row) => sum + BigInt(row.refund_yen), 0n), 'refund_yen'),
      payout = safe(settlements.reduce((sum, row) => sum + BigInt(row.payout_yen), 0n), 'payout_yen'), effective = spending - refund;
    return {race_id, status, total_stake_yen: spending, refund_yen: refund, effective_stake_yen: effective,
      payout_yen: payout, cash_return_yen: safe(BigInt(payout) + BigInt(refund), 'cash_return_yen'),
      net_profit_yen: payout - effective, actual_roi_percent: ratio(BigInt(payout), BigInt(effective)), rows: settlements};
  }
  function recommend_allocation(input, configuration, model) {
    const policy = limits(configuration);
    if (!object(model)) throw new MoneyError('model must be an object');
    const rows = bets(input), empty = validate_purchase([], {...policy, day_spent_yen: 0, loss_used_yen: 0});
    if (model.validated !== true || model.data_complete !== true) {
      return {...empty, status: 'skip', reason: 'model_unvalidated_or_data_incomplete'};
    }
    const available = Math.min(policy.budget_yen, Math.max(0, policy.day_budget_yen - policy.day_spent_yen),
      Math.max(0, policy.loss_limit_yen - policy.loss_used_yen), Math.floor(policy.budget_yen / 10));
    const eligible = rows.map((row, index) => ({row, index, edge: own(row, 'probability') ?
      decimal(row.probability, 'probability') * decimal(row.odds, 'odds') : 0n}))
      .filter(item => item.edge > SQUARED)
      .sort((a, b) => a.edge === b.edge ? a.index - b.index : (a.edge > b.edge ? -1 : 1));
    const chosen = [];
    for (const item of eligible) {
      if (chosen.length >= policy.max_bets || (chosen.length + 1) * 100 > available) break;
      chosen.push({...item.row, stake_yen: 100});
    }
    if (!chosen.length) return {...empty, status: 'skip', reason: 'insufficient_expected_value_or_risk_budget'};
    return {...validate_purchase(chosen, policy), status: 'recommended', reason: 'validated_positive_ev_one_unit'};
  }
  function record(input) {
    if (!object(input)) throw new MoneyError('purchase record must be an object');
    const id = text(input.id, 'id'), race_id = text(input.race_id, 'race_id'), stamp = input.purchased_at;
    const match = typeof stamp === 'string' && /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,3}))?(Z|[+-]\d{2}:\d{2})$/.exec(stamp);
    if (!match) throw new MoneyError('purchase timestamp requires an ISO timezone');
    const localText = `${match[1]}.${(match[2] || '').padEnd(3, '0')}Z`, local = new Date(localText), zone = match[3];
    if (!Number.isFinite(local.getTime()) || local.toISOString() !== localText || Number(stamp.slice(0, 4)) < 1) {
      throw new MoneyError('invalid purchase timestamp');
    }
    let offset = 0;
    if (zone !== 'Z') {
      const hours = Number(zone.slice(1, 3)), minutes = Number(zone.slice(4, 6));
      if (hours > 23 || minutes > 59) throw new MoneyError('invalid purchase timestamp');
      offset = (hours * 60 + minutes) * (zone[0] === '+' ? 1 : -1);
    }
    const dayDate = new Date(local.getTime() + (540 - offset) * 60000);
    if (dayDate.getUTCFullYear() < 1 || dayDate.getUTCFullYear() > 9999) throw new MoneyError('invalid purchase timestamp');
    const purchase_day = dayDate.toISOString().slice(0, 10), rows = bets(input.bets);
    if (!rows.length || rows.some(row => row.race_id !== race_id)) throw new MoneyError('record must contain purchases for its race');
    const clean = {id, race_id, purchased_at: stamp, purchase_day, source: 'manual', bets: rows};
    if (own(input, 'official_result')) {
      settle_bets(rows, input.official_result);
      clean.official_result = JSON.parse(JSON.stringify(input.official_result));
    }
    return clean;
  }
  function ledger(input) {
    if (!Array.isArray(input) || input.length > 10000) throw new MoneyError('ledger must contain at most 10000 purchase records');
    const records = [], ids = new Set(), keys = new Set();
    for (const raw of input) {
      const clean = record(raw);
      if (ids.has(clean.id)) throw new MoneyError('duplicate purchase id');
      ids.add(clean.id);
      for (const row of clean.bets) {
        const k = `${row.race_id}:${key(row)}`;
        if (keys.has(k)) throw new MoneyError('duplicate purchased combination');
        keys.add(k);
      }
      records.push(clean);
    }
    return records;
  }
  function append_purchase(input, purchase, configuration) {
    const records = ledger(input), next = record(purchase), policy = limits(configuration), combined = ledger([...records, next]);
    const sameRace = records.filter(item => item.race_id === next.race_id).flatMap(item => item.bets);
    const daySpent = records.filter(item => item.purchase_day === next.purchase_day)
      .reduce((sum, item) => sum + BigInt(total(item.bets)), 0n);
    const exposure = records.filter(item => item.purchase_day === next.purchase_day)
      .reduce((sum, item) => sum + BigInt(own(item, 'official_result') ?
        Math.max(0, -settle_bets(item.bets, item.official_result).net_profit_yen) : total(item.bets)), 0n);
    validate_purchase(next.bets, {...policy, day_spent_yen: safe(daySpent + BigInt(policy.day_spent_yen), 'day_spent_yen'),
      loss_used_yen: safe(exposure + BigInt(policy.loss_used_yen), 'loss_used_yen')});
    if (sameRace.length + next.bets.length > policy.max_bets || total([...sameRace, ...next.bets]) > policy.budget_yen) {
      throw new MoneyError('cumulative race purchase limit exceeded');
    }
    return combined;
  }
  function summarize_ledger(input) {
    const records = ledger(input);
    let spending = 0n, pending = 0n, effective = 0n, payout = 0n, refunds = 0n, settledCount = 0;
    for (const item of records) {
      const amount = BigInt(total(item.bets)); spending += amount;
      if (!own(item, 'official_result')) { pending += amount; continue; }
      const settled = settle_bets(item.bets, item.official_result);
      settledCount++; effective += BigInt(settled.effective_stake_yen);
      payout += BigInt(settled.payout_yen); refunds += BigInt(settled.refund_yen);
    }
    return {purchase_count: records.length, settled_count: settledCount, pending_count: records.length - settledCount,
      total_stake_yen: safe(spending, 'total_stake_yen'), pending_stake_yen: safe(pending, 'pending_stake_yen'),
      settled_effective_stake_yen: safe(effective, 'settled_effective_stake_yen'), payout_yen: safe(payout, 'payout_yen'),
      refund_yen: safe(refunds, 'refund_yen'), cash_return_yen: safe(payout + refunds, 'cash_return_yen'),
      net_profit_yen: Number(payout - effective), actual_roi_percent: ratio(payout, effective)};
  }
  return Object.freeze({MoneyError, estimate_bet, validate_purchase, settle_bets,
    recommend_allocation, append_purchase, summarize_ledger});
});
