"""Numeric DT-R1 features with strictly earlier-day, unresolved-identity history.

Same-race outcomes, archived weather and collection clocks never enter features.
Rest/starts are calendar proxies, not physiological fatigue measurements. Source
``agari`` is final HALF-lap time and is the active timing feature. Full final
lap columns are retired compatibility slots; they never receive measurements.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from hashlib import sha256
from itertools import groupby
import json
import math

import numpy as np


CURRENT_FEATURES = (
    'points', 'points_relative', 'points_gap_to_best', 'points_rank_fraction', 'points_missing',
    'win_rate', 'win_rate_relative', 'win_rate_missing',
    'top2_rate', 'top2_rate_relative', 'top2_rate_missing',
    'top3_rate', 'top3_rate_relative', 'top3_rate_missing',
    'age', 'age_relative', 'age_missing', 'gear_ratio', 'gear_missing',
    'style_nige', 'style_ryo', 'style_oi', 'style_makuri', 'style_sashi', 'style_jizai', 'style_unknown',
    'class_s', 'class_a12', 'class_a3', 'class_l1', 'class_unknown', 'field_fraction',
    'line_known', 'line_unknown', 'line_not_applicable', 'line_contested',
    'line_size_fraction', 'line_position_fraction', 'line_count_fraction',
    'line_leader', 'line_second', 'line_tail', 'line_strength_gap',
    'line_leader_points_gap', 'line_predecessor_points_gap', 'line_successor_points_gap',
    'line_points_missing', 'line_neighbor_points_missing',
    'line_role_attack', 'line_role_follow', 'line_role_flexible', 'line_role_unknown',
)
HISTORY_FEATURES = (
    'history_entries_log', 'history_starts_log', 'history_numeric_log',
    'history_missing', 'history_identity_unknown', 'history_numeric_fraction',
    'history_rest_days_log', 'history_rest_missing', 'history_starts_7d', 'history_starts_30d',
    *(name for n in (5, 10, 20, 30) for name in
      (f'history_form_last{n}', f'history_win_last{n}', f'history_top2_last{n}',
       f'history_top3_last{n}', f'history_count_last{n}')),
    'history_form_relative', 'history_same_class_form', 'history_same_class_log',
    'history_same_class_missing', 'history_same_venue_form', 'history_same_venue_log',
    'history_same_venue_missing', 'history_incident_rate', 'history_incident_missing',
    'history_half_lap_mean', 'history_half_lap_log', 'history_half_lap_missing',
    'history_venue_half_lap_mean', 'history_venue_half_lap_log', 'history_venue_half_lap_missing',
    'history_final_lap_mean', 'history_final_lap_log', 'history_final_lap_missing',
    'history_venue_final_lap_mean', 'history_venue_final_lap_log', 'history_venue_final_lap_missing',
    'history_s_rate', 'history_b_rate', 'history_sb_missing',
)
FEATURE_NAMES = CURRENT_FEATURES + HISTORY_FEATURES
FEATURE_VERSION = 'CHAT_DT_R1_STRICT_PRIOR_DAY_FEATURES_V1'
FEATURE_INDEX = {name: i for i, name in enumerate(FEATURE_NAMES)}


def retired_timing_feature(name):
    """Keep the frozen 106/224-column schema without learning full-lap data."""
    return name.startswith(('history_final_lap_', 'history_venue_final_lap_',
                            'history_observed_full_last_lap_seconds_'))


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _bind_feature_input(output):
    """Bind the actual numeric input and selected prior evidence, never targets."""
    output['feature_input_sha256'] = _digest({
        'binding_schema': 'dt-r1-feature-input-v2',
        'input_sha256': output.get('input_sha256'),
        'record_context': {key: output.get(key) for key in (
            'race_id', 'day', 'venue_code', 'race_class', 'cohort', 'cutoff_at',
            'published_cutoff_at', 'available_at', 'source_attestation_sha256', 'pre_cutoff_authenticated')},
        # Pair scores and output labels read these fields outside the numeric
        # matrix. Bind their ordered values so rebinding is never implicit.
        'rider_pair_inputs': [{'car': rider.get('car'), 'competition_points': rider.get('competition_points')}
                              for rider in output.get('riders', [])],
        'line_pair_inputs': {'groups': output.get('line_groups', []),
                             'known': output.get('lines_known', False),
                             'applicable': output.get('lines_applicable', True)},
        'feature_version': output['feature_version'],
        'feature_names': output['feature_names'],
        'features': output['features'].tolist(),
        'history_evidence': output['history_evidence'],
        'feature_status': output['feature_status'],
        'feature_scope': output['feature_scope'],
    })
    return output


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _mean(values, default=0.0):
    return math.fsum(values) / len(values) if values else default


def _log_count(count, scale=1000):
    return math.log1p(count) / math.log1p(scale)


def _valid_day(value):
    try:
        day = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError('FEATURE_DAY_INVALID') from None
    if day.isoformat() != value:
        raise ValueError('FEATURE_DAY_INVALID')
    return day


def _history_key(rider):
    key = rider.get('identity_key')
    return key if isinstance(key, str) and key and rider.get('identity_usable', False) else None


def _supported(record):
    riders = record.get('riders', [])
    cars = [r.get('car') for r in riders]
    return (record.get('field_supported', True) and 3 <= len(riders) <= 9 and
            all(type(car) is int and 1 <= car <= 9 for car in cars) and len(set(cars)) == len(cars))


def _history_summary(past, rider, record, target_day):
    numeric = [r for r in past if r['rank'] is not None]
    starts = [r for r in past if r['started']]
    values = {
        'history_entries_log': _log_count(len(past)),
        'history_starts_log': _log_count(len(starts)),
        'history_numeric_log': _log_count(len(numeric)),
        'history_missing': float(not numeric),
        'history_identity_unknown': float(_history_key(rider) is None),
        'history_numeric_fraction': len(numeric) / len(past) if past else 0.0,
        'history_rest_days_log': 0.0,
        'history_rest_missing': float(not starts),
        'history_starts_7d': sum((target_day - r['date']).days <= 7 for r in starts) / 10.0,
        'history_starts_30d': sum((target_day - r['date']).days <= 30 for r in starts) / 30.0,
    }
    if starts:
        values['history_rest_days_log'] = math.log1p(min(365, (target_day - starts[-1]['date']).days)) / math.log1p(365)
    for n in (5, 10, 20, 30):
        recent = numeric[-n:]
        values[f'history_form_last{n}'] = _mean([r['form'] for r in recent])
        values[f'history_win_last{n}'] = _mean([float(r['rank'] == 1) for r in recent])
        values[f'history_top2_last{n}'] = _mean([float(r['rank'] <= 2) for r in recent])
        values[f'history_top3_last{n}'] = _mean([float(r['rank'] <= 3) for r in recent])
        values[f'history_count_last{n}'] = len(recent) / n
    # Five pseudo-observations shrink a small context sample toward this rider's
    # own earlier observed form. A no-history 0.5 prior is marked by missing flags.
    prior = _mean([r['form'] for r in numeric], 0.5)
    for label, matches in (
        ('same_class', [r for r in numeric if r['race_class'] == record.get('race_class')]),
        ('same_venue', [r for r in numeric if r['venue_code'] == record.get('venue_code')]),
    ):
        values[f'history_{label}_form'] = (math.fsum(r['form'] for r in matches) + 5 * prior) / (len(matches) + 5)
        values[f'history_{label}_log'] = _log_count(len(matches), 100)
        values[f'history_{label}_missing'] = float(not matches)
    recent_starts = starts[-30:]
    values['history_incident_rate'] = _mean([float(r['incident']) for r in recent_starts])
    values['history_incident_missing'] = float(not recent_starts)
    timing_counts = {}
    for kind, scale in (('half_lap', 20.0),):
        timed = [r for r in starts if r[kind + '_seconds'] is not None]
        for prefix, observations in ((kind, timed), ('venue_' + kind, [r for r in timed if r['venue_code'] == record.get('venue_code')])):
            observations = observations[-20:]
            values[f'history_{prefix}_mean'] = _mean([r[kind + '_seconds'] for r in observations]) / scale
            values[f'history_{prefix}_log'] = _log_count(len(observations), 20)
            values[f'history_{prefix}_missing'] = float(not observations)
            timing_counts[prefix] = len(observations)
    # Reserved columns stay at the exact missing-value encoding of the old archive.
    for prefix in ('final_lap', 'venue_final_lap'):
        values[f'history_{prefix}_mean'] = 0.0
        values[f'history_{prefix}_log'] = 0.0
        values[f'history_{prefix}_missing'] = 1.0
        timing_counts[prefix] = 0
    marked = [r for r in starts if r['sb_mark'] is not None][-30:]
    values['history_s_rate'] = _mean([float('S' in r['sb_mark']) for r in marked])
    values['history_b_rate'] = _mean([float('B' in r['sb_mark']) for r in marked])
    values['history_sb_missing'] = float(not marked)
    evidence = dict(
        entries=len(past), confirmed_start_proxy=len(starts), numeric_finishes=len(numeric),
        latest_day=past[-1]['day'] if past else None,
        history_input_sha256=_digest([r['event_sha256'] for r in past]),
        identity_status=rider.get('identity_status', 'UNRESOLVED_SOURCE_COMPOSITE'),
        official_identity_verified=False, timing_counts=timing_counts,
    )
    return values, evidence


class FeatureBuilder:
    """Stateful chronology adapter; call transform for a day, then update_day.

    A defensive ``event.day < target.day`` filter applies even if a caller has
    already inserted same-day or later data. Consequently streaming misuse cannot
    make future outcomes enter a feature vector. Duplicate updates are rejected.
    """

    feature_names = FEATURE_NAMES

    def __init__(self):
        self.history = defaultdict(list)
        self._seen_races = set()

    def transform(self, record):
        target_day = _valid_day(record['day'])
        riders = record.get('riders', [])
        matrix = np.zeros((len(riders), len(FEATURE_NAMES)), dtype=np.float64)
        evidence = dict(
            scope='STRICTLY_EARLIER_RACE_DAYS_RETROSPECTIVE_SOURCE',
            latest_history_day=None, rider_evidence={},
            publication_time_authenticated=False,
            identities_are_unresolved=True,
            rest_and_starts_are_proxies=True,
            agari_is_half_lap=True, archived_weather_used=False,
        )
        output = dict(record, features=matrix, feature_names=FEATURE_NAMES,
                      feature_version=FEATURE_VERSION, history_evidence=evidence,
                      feature_availability_authenticated=False,
                      feature_scope=('PROSPECTIVE_SHADOW_UNATTESTED'
                                     if record.get('cohort') == 'prospective' else 'RETROSPECTIVE_RESEARCH'))
        if not _supported(record):
            output['feature_status'] = 'HOLD_UNSUPPORTED_ROSTER'
            return _bind_feature_input(output)
        values_by_field = {
            field: [_finite(r.get(field)) for r in riders]
            for field in ('competition_points', 'win_rate', 'top2_rate', 'top3_rate', 'age', 'gear_ratio')
        }
        means = {field: _mean([v for v in values if v is not None]) for field, values in values_by_field.items()}
        points = values_by_field['competition_points']
        known_points = [p for p in points if p is not None]
        best_points = max(known_points) if known_points else 0.0
        point_by_car = {r['car']: p for r, p in zip(riders, points)}
        groups = record.get('line_groups') or []
        flat = [car for group in groups for car in group]
        lines_known = (record.get('lines_known') is True and record.get('lines_applicable', True) is True
                       and bool(groups) and all(groups) and len(flat) == len(set(flat))
                       and set(flat) == set(point_by_car))
        membership = {car: (group, position) for group in groups for position, car in enumerate(group)} if lines_known else {}
        history_rows = []
        for i, rider in enumerate(riders):
            car, point = rider['car'], points[i]
            row = {
                'points': point / 120 if point is not None else 0.0,
                'points_relative': (point - means['competition_points']) / 10 if point is not None else 0.0,
                'points_gap_to_best': (point - best_points) / 10 if point is not None else 0.0,
                'points_rank_fraction': (1 - sum(p > point for p in known_points) / max(1, len(known_points) - 1)) if point is not None else 0.0,
                'points_missing': float(point is None),
                'age': 0.0, 'age_relative': 0.0,
                'age_missing': float(values_by_field['age'][i] is None),
                'gear_ratio': values_by_field['gear_ratio'][i] / 4 if values_by_field['gear_ratio'][i] is not None else 0.0,
                'gear_missing': float(values_by_field['gear_ratio'][i] is None),
                'class_s': float(record.get('race_class') == 'S'),
                'class_a12': float(record.get('race_class') == 'A12'),
                'class_a3': float(record.get('race_class') == 'A3'),
                'class_l1': float(record.get('race_class') == 'L1'),
                'class_unknown': float(record.get('race_class') not in ('S', 'A12', 'A3', 'L1')),
                'field_fraction': len(riders) / 9,
                'line_known': float(lines_known), 'line_unknown': float(not lines_known),
                'line_not_applicable': float(record.get('lines_applicable') is False),
                'line_contested': float(record.get('line_status') == 'CONTESTED'),
                'line_points_missing': 1.0, 'line_neighbor_points_missing': 1.0,
                'line_role_unknown': 1.0,
            }
            age = values_by_field['age'][i]
            if age is not None:
                row.update(age=age / 60, age_relative=(age - means['age']) / 20)
            for field in ('win_rate', 'top2_rate', 'top3_rate'):
                value = values_by_field[field][i]
                row[field] = value if value is not None else 0.0
                row[field + '_relative'] = (value - means[field]) / 0.25 if value is not None else 0.0
                row[field + '_missing'] = float(value is None)
            style = rider.get('style', 'UNKNOWN')
            for label in ('NIGE', 'RYO', 'OI', 'MAKURI', 'SASHI', 'JIZAI'):
                row['style_' + label.lower()] = float(style == label)
            row['style_unknown'] = float(style not in ('NIGE', 'RYO', 'OI', 'MAKURI', 'SASHI', 'JIZAI'))
            if lines_known:
                group, position = membership[car]
                line_points = [point_by_car[c] for c in group if point_by_car[c] is not None]
                leader = point_by_car[group[0]]
                preceding = point_by_car[group[position - 1]] if position else None
                following = point_by_car[group[position + 1]] if position + 1 < len(group) else None
                row.update(
                    line_size_fraction=len(group) / len(riders), line_position_fraction=position / 8,
                    line_count_fraction=len(groups) / len(riders), line_leader=float(position == 0),
                    line_second=float(position == 1), line_tail=float(position == len(group) - 1),
                    line_strength_gap=(_mean(line_points) - means['competition_points']) / 10 if line_points else 0.0,
                    line_leader_points_gap=(leader - point) / 10 if leader is not None and point is not None else 0.0,
                    line_predecessor_points_gap=(preceding - point) / 10 if preceding is not None and point is not None else 0.0,
                    line_successor_points_gap=(following - point) / 10 if following is not None and point is not None else 0.0,
                    line_points_missing=float(len(line_points) != len(group)),
                    line_neighbor_points_missing=float(point is None or (position > 0 and preceding is None)
                                                       or (position + 1 < len(group) and following is None)),
                )
                role = rider.get('published_line_role')
                row['line_role_attack'] = float(role in ('先行', '押え先', 'カマシ', 'まくり'))
                row['line_role_follow'] = float(role == '追込')
                row['line_role_flexible'] = float(role in ('自在', 'イン切', 'イン待', '追上'))
                row['line_role_unknown'] = float(role not in ('先行', '押え先', 'カマシ', 'まくり', '追込', '自在', 'イン切', 'イン待', '追上'))
            identity = _history_key(rider)
            past = sorted((h for h in self.history.get(identity, ()) if h['day'] < record['day']),
                          key=lambda h: (h['day'], h['race_id'])) if identity else []
            history, rider_evidence = _history_summary(past, rider, record, target_day)
            history_rows.append(history)
            row.update(history)
            evidence['rider_evidence'][str(car)] = rider_evidence
            latest = rider_evidence['latest_day']
            if latest and (evidence['latest_history_day'] is None or latest > evidence['latest_history_day']):
                evidence['latest_history_day'] = latest
            matrix[i] = [row.get(name, 0.0) for name in FEATURE_NAMES]
        observed_forms = [row['history_form_last10'] for row in history_rows if not row['history_missing']]
        average_form = _mean(observed_forms)
        for i, history in enumerate(history_rows):
            matrix[i, FEATURE_INDEX['history_form_relative']] = (history['history_form_last10'] - average_form) if not history['history_missing'] else 0.0
        if not np.isfinite(matrix).all():
            output['features'] = np.zeros_like(matrix)
            output['feature_status'] = 'HOLD_NONFINITE_FEATURE'
            return _bind_feature_input(output)
        output['feature_status'] = 'READY'
        return _bind_feature_input(output)

    def update_day(self, records):
        records = list(records)
        if not records:
            return
        if len({r['day'] for r in records}) != 1:
            raise ValueError('HISTORY_UPDATE_SINGLE_DAY_REQUIRED')
        target_day = _valid_day(records[0]['day'])
        ids = [r['race_id'] for r in records]
        if len(ids) != len(set(ids)) or any(rid in self._seen_races for rid in ids):
            raise ValueError('DUPLICATE_HISTORY_RACE')
        for record in sorted(records, key=lambda r: r['race_id']):
            outcomes = {r['car']: r for r in record.get('result_rows', [])}
            size = len(record.get('riders', []))
            for rider in record.get('riders', []):
                identity = _history_key(rider)
                if identity is None:
                    continue
                result = outcomes.get(rider.get('car'), {})
                rank = result.get('rank')
                if type(rank) is not int or not 1 <= rank <= size:
                    rank = None
                cancelled, absent = bool(result.get('cancelled')), bool(result.get('absence'))
                started = not cancelled and not absent and (rank is not None or bool(result.get('incident')))
                half = _finite(result.get('half_lap_seconds'))
                event = dict(
                    day=record['day'], date=target_day, race_id=record['race_id'],
                    venue_code=record.get('venue_code'), race_class=record.get('race_class'),
                    rank=rank, form=1 - (rank - 1) / max(1, size - 1) if rank is not None else None,
                    started=started, incident=bool(result.get('incident')),
                    half_lap_seconds=half if half is not None and half > 0 else None,
                    final_lap_seconds=None,  # Retired input, never learned or inferred from agari.
                    sb_mark=result.get('sb_mark'),
                )
                event['event_sha256'] = _digest({key: value for key, value in event.items() if key != 'date'})
                self.history[identity].append(event)
        self._seen_races.update(ids)


def require_history_available(records, at):
    """Prospective history requires both source and outcome availability clocks.

    An earlier event day does not establish when a corrected/result record was
    actually available. Retrospective archive studies do not call this helper;
    their unknown historic availability remains explicitly disclosed.
    """
    from .policy import clock
    cutoff = clock(at)
    for row in records:
        available = row.get('available_at')
        if available is None:
            raise ValueError('HISTORY_SOURCE_AVAILABILITY_REQUIRED')
        if clock(available) > cutoff:
            raise ValueError('HISTORY_SOURCE_AFTER_PREDICTION')
        if row.get('result_rows') or row.get('top3') or row.get('finish'):
            result_at = row.get('result_at')
            if result_at is None:
                raise ValueError('HISTORY_RESULT_AVAILABILITY_REQUIRED')
            if clock(result_at) > cutoff:
                raise ValueError('HISTORY_RESULT_AFTER_PREDICTION')


def build_features(records):
    """Sort records, transform a whole day, then reveal that day's outcomes."""
    ordered = sorted(records, key=lambda r: (r['day'], r['race_id']))
    if len({r['race_id'] for r in ordered}) != len(ordered):
        raise ValueError('DUPLICATE_FEATURE_RACE')
    builder = FeatureBuilder()
    output = []
    for _, group in groupby(ordered, key=lambda r: r['day']):
        day_records = list(group)
        output.extend(builder.transform(record) for record in day_records)
        builder.update_day(day_records)
    return output
