"""Shared fixed-decimal money contract; see docs/MONEY_ENGINE.md.

This module calculates records. It neither places bets nor verifies a source's
authority. Settlements require a complete, confirmed official result supplied
by the caller; prediction odds never substitute for an official payout.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

MAX_INTEGER = 9007199254740991
BET_TYPES = {'trifecta': (3, False), 'trio': (3, True), 'exacta': (2, False),
             'quinella': (2, True), 'quinella_place': (2, True),
             'win': (1, False), 'place': (1, False)}
REFUND_STATUSES = ('cancelled', 'no_contest', 'postponed')


class MoneyError(ValueError):
    """Invalid or incomplete monetary input; never silently coerce it to zero."""


def _integer(value, name, *, unit=1, positive=False):
    if type(value) is float and math.isfinite(value) and value.is_integer():
        value = int(value)
    if (type(value) is not int or value < (1 if positive else 0)
            or value > MAX_INTEGER or value % unit):
        raise MoneyError(f'{name} must be a bounded nonnegative integer in {unit}-yen units')
    return value


def _decimal(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise MoneyError(f'{name} must be a fixed decimal')
    raw = value if isinstance(value, str) else format(Decimal(str(value)), 'f')
    if not isinstance(value, str) and re.fullmatch(r'-0(?:\.0+)?', raw):
        raw = '0'
    if not re.fullmatch(r'[0-9]{1,16}(?:\.[0-9]{1,6})?', raw):
        raise MoneyError(f'{name} must be a finite fixed decimal with at most six decimal places')
    try:
        parsed = Decimal(raw)
    except InvalidOperation as exc:
        raise MoneyError(f'invalid {name}') from exc
    return parsed


def _text(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        raise MoneyError(f'invalid {name}')
    return value


def _string(value):
    result = format(value, 'f')
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    return '0' if result in ('', '-0') else result


def _ratio(numerator, denominator):
    if not denominator:
        return None
    with localcontext() as ctx:
        ctx.prec = 64
        return _string((Decimal(numerator) / Decimal(denominator) * 100)
                       .quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP))


def estimate_bet(stake_yen, probability, odds):
    """Estimated returns as decimal strings; probability uses 0..1, not percent."""
    stake = _integer(stake_yen, 'stake_yen', unit=100)
    p, o = _decimal(probability, 'probability'), _decimal(odds, 'odds')
    if not 0 <= p <= 1 or not 1 <= o <= 1000000:
        raise MoneyError('probability must be 0..1 and odds 1..1000000')
    with localcontext() as ctx:
        ctx.prec = 64
        payout, expected = o * stake, p * o * stake
        return dict(stake_yen=stake, probability=_string(p), odds=_string(o),
                    payout_if_hit_yen=_string(payout), profit_if_hit_yen=_string(payout - stake),
                    expected_payout_yen=_string(expected), expected_profit_yen=_string(expected - stake),
                    expected_roi_percent=_string(p * o * 100) if stake else None,
                    expected_profit_percent=_string((p * o - 1) * 100) if stake else None)


def _combination(row):
    if (not isinstance(row, dict) or not isinstance(row.get('bet_type'), str)
            or row['bet_type'] not in BET_TYPES):
        raise MoneyError('unsupported bet_type')
    size, unordered = BET_TYPES[row['bet_type']]
    combination = row.get('combination')
    if isinstance(combination, str):
        if not re.fullmatch(r'[1-6](?:-[1-6])*', combination):
            raise MoneyError('invalid combination')
        combination = [int(x) for x in combination.split('-')]
    if not isinstance(combination, list) or len(combination) != size:
        raise MoneyError('combination must contain distinct boat numbers 1..6')
    combination = [_integer(x, 'boat_number') for x in combination]
    if any(x not in range(1, 7) for x in combination) or len(set(combination)) != size:
        raise MoneyError('combination must contain distinct boat numbers 1..6')
    return sorted(combination) if unordered else combination[:]


def _key(row):
    return row['bet_type'] + ':' + '-'.join(map(str, row['combination']))


def _bets(bets):
    if not isinstance(bets, list) or len(bets) > 120:
        raise MoneyError('bets must be a list of at most 120 combinations')
    normalized, seen, race, probability_totals = [], set(), None, {}
    for row in bets:
        combination = _combination(row)
        race_id = _text(row.get('race_id'), 'race_id')
        if race is not None and race_id != race:
            raise MoneyError('one purchase must refer to one race')
        race = race_id
        clean = dict(race_id=race_id, bet_type=row['bet_type'], combination=combination,
                     stake_yen=_integer(row.get('stake_yen'), 'stake_yen', unit=100, positive=True))
        key = _key(clean)
        if key in seen:
            raise MoneyError('duplicate combination')
        seen.add(key)
        if 'probability' in row or 'odds' in row:
            estimate = estimate_bet(clean['stake_yen'], row.get('probability'), row.get('odds'))
            clean.update(probability=estimate['probability'], odds=estimate['odds'])
            if clean['bet_type'] in ('trifecta', 'trio', 'exacta', 'quinella', 'win'):
                kind = clean['bet_type']
                probability_totals[kind] = probability_totals.get(kind, Decimal(0)) + Decimal(clean['probability'])
                if probability_totals[kind] > 1:
                    raise MoneyError('mutually exclusive ticket probabilities exceed one')
        normalized.append(clean)
    return normalized


def _limits(limits):
    if not isinstance(limits, dict):
        raise MoneyError('limits must be an object')
    budget = _integer(limits.get('budget_yen'), 'budget_yen', unit=100)
    cap = _integer(limits.get('max_bets', 8), 'max_bets')
    if cap not in (8, 16, 24, 32):
        raise MoneyError('max_bets must be 8, 16, 24, or 32')
    return dict(budget_yen=budget, max_bets=cap,
        day_budget_yen=_integer(limits.get('day_budget_yen', budget), 'day_budget_yen', unit=100),
        day_spent_yen=_integer(limits.get('day_spent_yen', 0), 'day_spent_yen', unit=100),
        loss_limit_yen=_integer(limits.get('loss_limit_yen', budget), 'loss_limit_yen'),
        loss_used_yen=_integer(limits.get('loss_used_yen', 0), 'loss_used_yen'))


def _total(bets):
    return _integer(sum(row['stake_yen'] for row in bets), 'total_stake_yen')


def _percentages(bets, total):
    if not total:
        return []
    bases = [row['stake_yen'] * 10000 // total for row in bets]
    order = sorted(range(len(bets)), key=lambda i: (-(bets[i]['stake_yen'] * 10000 % total), i))
    for i in order[:10000 - sum(bases)]:
        bases[i] += 1
    return [f'{value // 100}.{value % 100:02d}' for value in bases]


def validate_purchase(bets, limits):
    """Normalize an explicit manual purchase and enforce gross spending limits."""
    rows, policy = _bets(bets), _limits(limits)
    total = _total(rows)
    if len(rows) > policy['max_bets']:
        raise MoneyError('maximum number of bets exceeded')
    if (total > policy['budget_yen'] or total + policy['day_spent_yen'] > policy['day_budget_yen']
            or total + policy['loss_used_yen'] > policy['loss_limit_yen']):
        raise MoneyError('race, day, or loss budget exceeded')
    expected = profit = None
    if all('probability' in row for row in rows):
        with localcontext() as ctx:
            ctx.prec = 64
            expected = sum((Decimal(estimate_bet(row['stake_yen'], row['probability'], row['odds'])
                                    ['expected_payout_yen']) for row in rows), Decimal(0))
            profit = expected - total
    return dict(bets=rows, total_stake_yen=total, budget_yen=policy['budget_yen'],
                remaining_budget_yen=policy['budget_yen'] - total,
                allocation_percent=_percentages(rows, total),
                expected_payout_yen=_string(expected) if expected is not None else None,
                expected_profit_yen=_string(profit) if profit is not None else None,
                expected_roi_percent=_ratio(expected, total) if expected is not None else None)


def settle_bets(bets, official_result):
    """Apply complete official per-100 payouts and explicit refund instructions."""
    rows = _bets(bets)
    if not isinstance(official_result, dict) or official_result.get('confirmed') is not True:
        raise MoneyError('confirmed complete official result required')
    race = _text(official_result.get('race_id'), 'race_id')
    if any(row['race_id'] != race for row in rows):
        raise MoneyError('result and purchase race mismatch')
    if 'verified_market_types' in official_result:
        markets = official_result['verified_market_types']
        if (not isinstance(markets, list) or any(not isinstance(x, str) or x not in BET_TYPES for x in markets)
                or len(set(markets)) != len(markets)
                or any(row['bet_type'] not in markets for row in rows)):
            raise MoneyError('purchased market has no complete verified official result')
    status = official_result.get('status')
    if status not in ('settled', 'dead_heat', 'special') + REFUND_STATUSES:
        raise MoneyError('result is not final')
    payouts = official_result.get('payouts')
    refunds, specials = official_result.get('refunds', []), official_result.get('special_payouts', [])
    if not all(isinstance(value, list) for value in (payouts, refunds, specials)):
        raise MoneyError('explicit payouts list required')
    if status in REFUND_STATUSES and (payouts or specials):
        raise MoneyError('cancelled result cannot also pay winnings')
    if status == 'special' and not specials:
        raise MoneyError('special payouts require explicit official values')
    if status != 'special' and specials:
        raise MoneyError('special payouts require special status')
    payout_map, refund_map, special_map = {}, {}, {}
    for entry in payouts:
        combination = _combination(entry)
        key = _key(dict(entry, combination=combination))
        if key in payout_map:
            raise MoneyError('duplicate official payout')
        payout_map[key] = _integer(entry.get('payout_per_100_yen'), 'payout_per_100_yen', positive=True)
    for entry in refunds:
        combination = _combination(entry)
        key = _key(dict(entry, combination=combination))
        if key in refund_map:
            raise MoneyError('duplicate refund')
        refund_map[key] = (_integer(entry['refund_yen'], 'refund_yen', unit=100, positive=True)
                           if 'refund_yen' in entry else None)
    for entry in specials:
        if (not isinstance(entry, dict) or not isinstance(entry.get('bet_type'), str)
                or entry['bet_type'] not in BET_TYPES):
            raise MoneyError('unsupported special bet_type')
        kind = entry['bet_type']
        if kind in special_map or any(key.startswith(kind + ':') for key in payout_map):
            raise MoneyError('duplicate or conflicting special payout')
        special_map[kind] = _integer(entry.get('payout_per_100_yen'), 'payout_per_100_yen', positive=True)
    settlements = []
    for row in rows:
        key, stake = _key(row), row['stake_yen']
        refund = (stake if status in REFUND_STATUSES else
                  (stake if key in refund_map and refund_map[key] is None else refund_map.get(key, 0)))
        if refund > stake:
            raise MoneyError('refund exceeds purchased amount')
        effective = stake - refund
        rate = payout_map.get(key, special_map.get(row['bet_type'], 0))
        payout = _integer(effective // 100 * rate, 'payout_yen')
        settlements.append(dict(**row, refund_yen=refund, effective_stake_yen=effective,
                                payout_yen=payout, net_profit_yen=payout - effective))
    total = _total(rows)
    refund = _integer(sum(row['refund_yen'] for row in settlements), 'refund_yen')
    payout = _integer(sum(row['payout_yen'] for row in settlements), 'payout_yen')
    effective = total - refund
    return dict(race_id=race, status=status, total_stake_yen=total, refund_yen=refund,
                effective_stake_yen=effective, payout_yen=payout,
                cash_return_yen=_integer(payout + refund, 'cash_return_yen'),
                net_profit_yen=payout - effective, actual_roi_percent=_ratio(payout, effective), rows=settlements)


def recommend_allocation(candidates, limits, model):
    """Conservative one-unit selection; no Kelly or unverified probability stakes."""
    policy = _limits(limits)
    if not isinstance(model, dict):
        raise MoneyError('model must be an object')
    rows = _bets(candidates)
    empty = validate_purchase([], dict(policy, day_spent_yen=0, loss_used_yen=0))
    if model.get('validated') is not True or model.get('data_complete') is not True:
        return dict(empty, status='skip', reason='model_unvalidated_or_data_incomplete')
    available = min(policy['budget_yen'], max(0, policy['day_budget_yen'] - policy['day_spent_yen']),
                    max(0, policy['loss_limit_yen'] - policy['loss_used_yen']), policy['budget_yen'] // 10)
    chosen = []
    eligible = []
    for index, row in enumerate(rows):
        if 'probability' not in row:
            continue
        edge = Decimal(row['probability']) * Decimal(row['odds'])
        if edge > 1:
            eligible.append((edge, index, row))
    for _, _, row in sorted(eligible, key=lambda item: (-item[0], item[1])):
        if len(chosen) >= policy['max_bets'] or (len(chosen) + 1) * 100 > available:
            break
        chosen.append(dict(row, stake_yen=100))
    if not chosen:
        return dict(empty, status='skip', reason='insufficient_expected_value_or_risk_budget')
    return dict(validate_purchase(chosen, policy), status='recommended', reason='validated_positive_ev_one_unit')


def _record(record):
    if not isinstance(record, dict):
        raise MoneyError('purchase record must be an object')
    identifier, race = _text(record.get('id'), 'id'), _text(record.get('race_id'), 'race_id')
    stamp = record.get('purchased_at')
    if not isinstance(stamp, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', stamp):
        raise MoneyError('purchase timestamp requires an ISO timezone')
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        day = parsed.astimezone(timezone(timedelta(hours=9))).date().isoformat()
    except (ValueError, OverflowError) as exc:
        raise MoneyError('invalid purchase timestamp') from exc
    rows = _bets(record.get('bets'))
    if not rows or any(row['race_id'] != race for row in rows):
        raise MoneyError('record must contain purchases for its race')
    clean = dict(id=identifier, race_id=race, purchased_at=stamp, purchase_day=day, source='manual', bets=rows)
    if 'official_result' in record:
        settle_bets(rows, record['official_result'])
        clean['official_result'] = copy.deepcopy(record['official_result'])
    return clean


def _ledger(ledger):
    if not isinstance(ledger, list) or len(ledger) > 10000:
        raise MoneyError('ledger must contain at most 10000 purchase records')
    records, ids, keys = [], set(), set()
    for raw in ledger:
        record = _record(raw)
        if record['id'] in ids:
            raise MoneyError('duplicate purchase id')
        ids.add(record['id'])
        for row in record['bets']:
            key = row['race_id'] + ':' + _key(row)
            if key in keys:
                raise MoneyError('duplicate purchased combination')
            keys.add(key)
        records.append(record)
    return records


def append_purchase(ledger, record, limits):
    """Return a new manual ledger, validating existing and prospective records."""
    records, new, policy = _ledger(ledger), _record(record), _limits(limits)
    combined = _ledger(records + [new])
    same_race = [row for existing in records if existing['race_id'] == new['race_id'] for row in existing['bets']]
    day_spent = sum(_total(existing['bets']) for existing in records if existing['purchase_day'] == new['purchase_day'])
    exposure = sum((max(0, -settle_bets(existing['bets'], existing['official_result'])['net_profit_yen'])
                    if 'official_result' in existing else _total(existing['bets']))
                   for existing in records if existing['purchase_day'] == new['purchase_day'])
    # The explicit day_spent counter covers purchases outside this local ledger.
    next_policy = dict(policy, day_spent_yen=_integer(day_spent + policy['day_spent_yen'], 'day_spent_yen'),
                       loss_used_yen=_integer(exposure + policy['loss_used_yen'], 'loss_used_yen'))
    validate_purchase(new['bets'], next_policy)
    if len(same_race) + len(new['bets']) > policy['max_bets'] or _total(same_race + new['bets']) > policy['budget_yen']:
        raise MoneyError('cumulative race purchase limit exceeded')
    return combined


def summarize_ledger(ledger):
    """Separate pending purchases from confirmed settlement performance."""
    records = _ledger(ledger)
    total = pending = effective = payout = refunds = settled_count = 0
    for record in records:
        spending = _total(record['bets'])
        total += spending
        if 'official_result' not in record:
            pending += spending
            continue
        settled = settle_bets(record['bets'], record['official_result'])
        settled_count += 1
        effective += settled['effective_stake_yen']
        payout += settled['payout_yen']
        refunds += settled['refund_yen']
    for value in (total, pending, effective, payout, refunds, payout + refunds):
        _integer(value, 'ledger_total_yen')
    return dict(purchase_count=len(records), settled_count=settled_count,
                pending_count=len(records) - settled_count, total_stake_yen=total,
                pending_stake_yen=pending, settled_effective_stake_yen=effective,
                payout_yen=payout, refund_yen=refunds, cash_return_yen=payout + refunds,
                net_profit_yen=payout - effective, actual_roi_percent=_ratio(payout, effective))
