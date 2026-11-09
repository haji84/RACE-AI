"""Observed EX action counts for the existing PR71 attack-success source field.

No new prediction algorithm, model coefficients, physical acceleration, source
permission, or calibrated probability. Counts describe attempted actions, not
unique races: their denominator must never be labelled a race count.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from hashlib import sha256
import math
import re

FORMULA_VERSION = 'winticket-recorded-front-actions-success-ratio-v1-20261110'
DEFINITION_URL = 'https://www.winticket.jp/keirin/column/ex_data'
FIELDS = ('exSpurt', 'exThrust')
MAX_COUNT = 10_000_000


class ExSourceError(ValueError):
    pass


def _require(ok, code):
    if not ok:
        raise ExSourceError(code)


def _percentage(value):
    if type(value) is str:
        if re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,8})?', value) is None:
            return None
        value = float(value)
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value) if 0 <= value <= 100 else None


def _matches_display(success, total, raw):
    parsed = _percentage(raw)
    if parsed is None:
        return False
    if not total:
        return parsed == 0
    # Match the precision actually encoded by the source. Rounding/truncation
    # is only a consistency check; the value always comes from exact counts.
    shown = Decimal(str(raw)).normalize()
    exponent = min(0, shown.as_tuple().exponent)
    quantum = Decimal(1).scaleb(exponent)
    exact = Decimal(success) * 100 / Decimal(total)
    return shown in (exact.quantize(quantum, rounding=ROUND_DOWN),
                     exact.quantize(quantum, rounding=ROUND_HALF_UP))


def attack_success_from_record(record):
    """Use actual kamashi/tsuppari successes per actual attempted action.

    Both components must be observed. A measured zero-attempt component adds
    no sample, while an absent component stays unknown. This pooled historical
    action ratio is NOT acceleration, stamina, future winning odds, or a
    causal measure of athletic ability.
    """
    missing = {
        'value': None, 'sample_n': 0, 'successful_actions': None,
        'status': 'UNAVAILABLE_ACTION_EVIDENCE',
        'calibrated_race_win_probability': False,
        'formula_version': FORMULA_VERSION,
        'sample_unit': 'recorded_actions_not_unique_races',
        'reason': None,
    }
    if type(record) is not dict:
        return {**missing, 'reason': 'RECORD_NOT_OBJECT'}
    observed = {}
    for name in FIELDS:
        row = record.get(name)
        if type(row) is not dict or not {'succeeded', 'total', 'percentage'} <= set(row):
            return {**missing, 'reason': 'ACTION_COMPONENT_UNOBSERVED'}
        success, total = row['succeeded'], row['total']
        if (type(success) is not int or type(total) is not int or
                not 0 <= success <= total <= MAX_COUNT):
            return {**missing, 'reason': 'ACTION_COUNTS_INCONSISTENT'}
        percent = _percentage(row['percentage'])
        if percent is None or (total == 0 and percent != 0):
            return {**missing, 'reason': 'ACTION_PERCENTAGE_INVALID'}
        if total and not _matches_display(success, total, row['percentage']):
            return {**missing, 'reason': 'ACTION_PERCENTAGE_COUNT_MISMATCH'}
        observed[name] = {'succeeded': success, 'total': total,
                          'reported_percentage': row['percentage']}
    successes = sum(row['succeeded'] for row in observed.values())
    samples = sum(row['total'] for row in observed.values())
    if not samples:
        return {**missing, 'successful_actions': 0,
                'reason': 'NO_OBSERVED_ACTION_ATTEMPTS',
                'observed_components': observed}
    return {
        **missing, 'value': successes / samples, 'sample_n': samples,
        'successful_actions': successes, 'status': 'OBSERVED_ACTION_RATIO',
        'reason': None, 'observed_components': observed,
    }


def attach_observed_attack_counts(packet, html):
    """Join an unchanged verified racecard to EX counts from the SAME bytes.

    Private return value includes source counts. Existing public summary and
    347/437 audit helpers remain the permitted log representation.
    """
    from .keirin_winticket_embedded_racecard import (
        racecard_from_public_html as base_parse,
    )
    from .keirin_winticket_embedded_odds import read_preloaded_json
    from .keirin_preflight import expected_keys
    from .keirin_result_delivery import canonical

    _require(type(packet) is dict and type(html) is bytes and
             packet.get('html_sha256') == sha256(html).hexdigest(),
             'EX_ORIGINAL_RACECARD_BYTES_REQUIRED')
    expected_cutoff = packet.get('direct_verified_fields', {}).get(
        'race/official_sales_cutoff')
    original = base_parse(html, url=packet['source_url'],
                          race_id=packet['race_id'],
                          captured_at=packet['source_capture_at_utc'],
                          expected_cutoff_at=expected_cutoff)
    _require(packet == original, 'EX_RACECARD_CHANGED_FROM_SOURCE')
    riders = packet['riders']
    ids = {row['source_player_id'] for row in riders}
    choices = {}
    state = read_preloaded_json(html)
    for query in state['tanStackQuery']['queries']:
        if type(query) is not dict or type(query.get('state')) is not dict:
            continue
        data = query['state'].get('data')
        rows = data.get('records') if type(data) is dict else None
        if type(rows) is not list or len(rows) != len(ids):
            continue
        if not all(type(row) is dict and row.get('playerId') is not None
                   for row in rows):
            continue
        index = {str(row['playerId']): row for row in rows}
        if len(index) == len(ids) and set(index) == ids:
            choices[sha256(canonical(index)).hexdigest()] = index
    _require(len(choices) == 1, 'EX_SOURCE_ROSTER_ABSENT_OR_CONFLICTING')
    records = next(iter(choices.values()))
    enriched = deepcopy(packet)
    lineage, unavailable = {}, {}
    for rider in riders:
        number = rider['car_number']
        signal = attack_success_from_record(records[rider['source_player_id']])
        key = f'rider/{number}/lead_attempt_and_success'
        if signal['value'] is None:
            unavailable[key] = signal['reason']
            continue
        _require(key not in enriched['direct_verified_fields'],
                 'EX_EXISTING_SOURCE_FIELD_OVERWRITE_FORBIDDEN')
        enriched['direct_verified_fields'][key] = signal['value']
        lineage[key] = {
            **signal, 'source_url': packet['source_url'],
            'original_html_sha256': packet['html_sha256'],
            'captured_at': packet['source_capture_at_utc'],
            'source_published_at': None,
            'source_definition_url': DEFINITION_URL,
            'independent_source_time_verified': False,
            'independent_source_rights_verified': False,
            'approved_for_pr71_input': False,
        }
    # Structural field names, not athlete data, aid subsequent source joins.
    shapes = {}
    for field in ('exLeftBehind', 'exSplitLine', 'exSnatch', 'exCompete',
                  'linePositionFirst', 'linePositionSecond',
                  'linePositionThird', 'lineSingleHorseman'):
        keys = set()
        for record in records.values():
            value = record.get(field)
            if type(value) is dict:
                keys.update(k for k in value if type(k) is str and
                            re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}', k))
        shapes[field] = sorted(keys)
    registry = set(expected_keys([r['car_number'] for r in riders]))
    observed = set(enriched['direct_verified_fields'])
    _require(observed <= registry, 'EX_UNREGISTERED_SOURCE_FIELD')
    enriched.update({
        'verified_registry_keys': sorted(observed),
        'unavailable_registry_keys': sorted(registry - observed),
        'registry_verified_count': len(observed),
        'registry_unavailable_count': len(registry - observed),
        'full_347_or_437_verified': observed == registry,
        'ex_action_ratio_evidence': lineage,
        'ex_action_ratio_unavailable_reasons': unavailable,
        'ex_action_ratio_transform': FORMULA_VERSION,
        'ex_nested_source_key_names_only': shapes,
    })
    return enriched


def racecard_with_observed_ex(html, **kwargs):
    """Drop-in source adapter; the existing four-model gate is unchanged."""
    from .keirin_winticket_embedded_racecard import racecard_from_public_html
    return attach_observed_attack_counts(racecard_from_public_html(html, **kwargs), html)
