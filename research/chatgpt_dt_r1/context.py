"""Connect evidenced venue, past timing and available weather to the learned model.

Geometry interactions let race-constant physical data influence rider-specific
scores. Current geometry applied to historical races needs an explicit recorded
assumption. Measured timing features never use AI/user estimates or the target
race. Missing values have their own indicators. All extra inputs are hashed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from math import cos, isfinite, log1p, radians, sin
import re
from zoneinfo import ZoneInfo

import numpy as np

from .features import _bind_feature_input
from .model import digest
from .observations import TIMINGS, TimingBook, day, utc
from .venues import GEOMETRY_FIELDS

GEOMETRY_SCALES = {'circumference_m': 400., 'straight_m': 100., 'cant_deg': 45.,
                   'straight_cant_deg': 5., 'home_width_m': 20., 'back_width_m': 20.,
                   'center_width_m': 20., 'curve_radius_m': 100., 'indoor': 1.,
                   'home_bearing_deg': 360., 'back_bearing_deg': 360.}
WEATHER_SCALES = {'wind_speed_m_s': 10., 'gust_m_s': 10., 'temperature_c': 40.,
                  'humidity_percent': 100., 'precipitation_mm': 20.}
TIMING_STATS = ('count', 'min', 'mean', 'recent', 'variance', 'uncertainty_mean')
# Keep historical column indices for frozen artifacts. Only the verified half-lap
# (agari) and independent segment measurements are active; full-lap is retired.
ACTIVE_TIMINGS = tuple(metric for metric in TIMINGS if metric != 'full_last_lap_seconds')
EXTRA_NAMES = tuple(
    [name for k in GEOMETRY_FIELDS for name in ('context_venue_' + k, 'context_venue_' + k + '_missing')]
    + ['context_geometry_present', 'context_current_geometry_assumption']
    + [f'context_{g}_x_{s}' for g in ('circumference', 'straight', 'cant') for s in ('attack', 'follow', 'leader', 'second')]
    + [name for k in WEATHER_SCALES for name in ('context_weather_' + k, 'context_weather_' + k + '_missing')]
    + ['context_home_headwind', 'context_home_crosswind', 'context_back_headwind', 'context_back_crosswind',
       'context_directional_wind_missing', 'context_wind_x_attack', 'context_wind_x_leader']
    + [name for metric in TIMINGS for stat in TIMING_STATS
       for name in (f'history_observed_{metric}_{stat}', f'history_observed_{metric}_{stat}_missing')]
    + [f'history_observed_{metric}_relative' for metric in TIMINGS]
)


def _weather(record, as_of):
    weather = record.get('weather_observation')
    if not isinstance(weather, dict):
        return {}, None
    try:
        if weather.get('kind') not in ('forecast', 'observation') or not re.fullmatch('[0-9a-f]{64}', weather.get('source_sha256', '')):
            return {}, None
        available, issued, cutoff = utc(weather['available_at']), utc(weather['issued_at']), utc(as_of)
        if issued > available or available > cutoff:
            return {}, None
        if record.get('cohort') != 'prospective':
            # No race-time clock exists in the pinned archive. Same-day weather
            # captured after the race is not promoted to a pre-race observation.
            if available.astimezone(ZoneInfo('Asia/Tokyo')).date() >= day(record['day']):
                return {}, None
        if weather['kind'] == 'observation' and utc(weather.get('observed_at', weather['issued_at'])) > cutoff:
            return {}, None
        values = {}
        bounds = {'wind_speed_m_s': (0, 100), 'gust_m_s': (0, 100), 'temperature_c': (-80, 65),
                  'humidity_percent': (0, 100), 'precipitation_mm': (0, 1000), 'wind_from_deg': (0, 360)}
        for key, (lo, hi) in bounds.items():
            value = weather.get(key)
            if value is None:
                continue
            if type(value) not in (int, float) or not isfinite(value) or not lo <= value <= hi:
                return {}, None
            values[key] = float(value)
        return values, weather['source_sha256']
    except (ValueError, TypeError, KeyError):
        return {}, None


def augment_features(rows, *, venue_store=None, timing_records=(), as_of,
                     allow_current_geometry_assumption=False):
    """Return new feature rows. Call for both training and forecasting.

    The supplied as_of is the actual research run time for retrospective rows,
    or the authentic prediction clock for prospective inputs. It is never
    substituted for a historical publication or cutoff clock.
    """
    utc(as_of)
    book = TimingBook.from_records(timing_records)
    indexed = defaultdict(list)
    for observation in book.observations:
        if any(observation.timings.get(metric) is not None for metric in ACTIVE_TIMINGS):
            indexed[observation.rider_id, observation.venue_id].append(observation)
    books = {key: TimingBook(value) for key, value in indexed.items()}
    out = []
    for original in rows:
        from .model import _verify_feature_binding
        _verify_feature_binding(original)
        row = dict(original)
        scope = 'prospective' if row.get('cohort') == 'prospective' else 'retrospective'
        target = (row.get('race_at') or row.get('event_at') or row.get('cutoff_at')) if scope == 'prospective' else row['day']
        if not target:
            raise ValueError('CONTEXT_TARGET_CLOCK_REQUIRED')
        venue = str(row.get('venue_code', row.get('venue_id', '')))
        geometry = venue_store.features(venue, target, as_of,
            allow_current_geometry_assumption=allow_current_geometry_assumption) if venue_store else {}
        weather, weather_sha = _weather(row, as_of)
        timing_by_rider, admitted_sources = {}, set()
        for rider in row['riders']:
            if rider.get('identity_usable') is not True:
                continue
            identity = str(rider.get('identity_key', rider.get('athlete_id', '')))
            rider_book = books.get((identity, venue))
            if rider_book:
                timing_by_rider[identity] = rider_book.features(identity, venue, target, as_of, scope=scope)
                for observation in rider_book.observations:
                    event_before = (observation.event_at is not None and utc(observation.event_at) < utc(target)) if scope == 'prospective' else day(observation.event_day or observation.event_at) < day(target)
                    if event_before and utc(observation.provenance.available_at) <= utc(as_of):
                        admitted_sources.add(digest(asdict(observation)))
        means = {}
        for metric in ACTIVE_TIMINGS:
            vals = [v[metric + '_mean'] for v in timing_by_rider.values() if v.get(metric + '_mean') is not None]
            means[metric] = float(np.mean(vals)) if vals else None
        groups = row.get('line_groups') or []
        places = {car: pos for group in groups for pos, car in enumerate(group)} if row.get('lines_known') else {}
        extras = []
        for rider in row['riders']:
            values = {}
            for key in GEOMETRY_FIELDS:
                number = geometry.get('venue_' + key)
                values['context_venue_' + key] = 0. if number is None else float(number) / GEOMETRY_SCALES[key]
                values['context_venue_' + key + '_missing'] = float(number is None)
            values['context_geometry_present'] = float(geometry.get('venue_geometry_present', 0))
            values['context_current_geometry_assumption'] = float(geometry.get('retrospective_current_geometry_assumption', 0))
            roles = {'attack': rider.get('style') in ('NIGE', 'RYO', 'MAKURI', 'JIZAI', 'ALLROUND'),
                     'follow': rider.get('style') in ('OI', 'SASHI', 'MARK'),
                     'leader': places.get(rider['car']) == 0, 'second': places.get(rider['car']) == 1}
            for label, key in (('circumference', 'circumference_m'), ('straight', 'straight_m'), ('cant', 'cant_deg')):
                for role, active in roles.items():
                    values[f'context_{label}_x_{role}'] = values['context_venue_' + key] * active
            for key, scale in WEATHER_SCALES.items():
                number = weather.get(key)
                values['context_weather_' + key] = 0. if number is None else number / scale
                values['context_weather_' + key + '_missing'] = float(number is None)
            speed, direction = weather.get('wind_speed_m_s'), weather.get('wind_from_deg')
            direction_known = speed is not None and direction is not None
            directions_available = []
            for section in ('home', 'back'):
                bearing = geometry.get('venue_' + section + '_bearing_deg')
                valid = direction_known and bearing is not None
                angle = radians(direction - bearing) if valid else 0.
                values[f'context_{section}_headwind'] = speed * cos(angle) / 10 if valid else 0.
                values[f'context_{section}_crosswind'] = speed * sin(angle) / 10 if valid else 0.
                directions_available.append(valid)
            values['context_directional_wind_missing'] = float(not all(directions_available))
            values['context_wind_x_attack'] = values['context_weather_wind_speed_m_s'] * roles['attack']
            values['context_wind_x_leader'] = values['context_weather_wind_speed_m_s'] * roles['leader']
            timing = (timing_by_rider.get(str(rider.get('identity_key', rider.get('athlete_id', ''))), {})
                      if rider.get('identity_usable') is True else {})
            for metric in TIMINGS:
                scale = 20.
                active = metric in ACTIVE_TIMINGS
                for stat in TIMING_STATS:
                    missing = 0 if stat == 'count' else None
                    number = timing.get(metric + '_' + stat, missing) if active else missing
                    key = f'history_observed_{metric}_{stat}'
                    values[key] = (0. if number is None else log1p(number) / log1p(100)
                                   if stat == 'count' else number / (scale * scale if stat == 'variance' else scale))
                    values[key + '_missing'] = float(number is None)
                mean = timing.get(metric + '_mean') if active else None
                values[f'history_observed_{metric}_relative'] = (mean - means[metric]) / scale if mean is not None and means.get(metric) is not None else 0.
            extras.append([values[name] for name in EXTRA_NAMES])
        row['features'] = np.concatenate((np.asarray(row['features']), np.asarray(extras).reshape(len(row['riders']), len(EXTRA_NAMES))), axis=1)
        row['feature_names'] = tuple(row['feature_names']) + EXTRA_NAMES
        row['feature_version'] = row['feature_version'] + '+evidenced-context-v1'
        sources = []
        if venue_store and geometry.get('venue_geometry_present'):
            sources = sorted({v.source_sha256 for v in venue_store.records if v.venue_code == venue and utc(v.retrieved_at) <= utc(as_of)})
        evidence = {'scope': scope, 'as_of': as_of, 'venue_sources': sources, 'timing_sources': sorted(admitted_sources),
                    'weather_source': weather_sha, 'current_geometry_assumption': bool(geometry.get('retrospective_current_geometry_assumption')),
                    'measured_timing_rider_count': sum(any(t.get(metric + '_count', 0) for metric in ACTIVE_TIMINGS) for t in timing_by_rider.values())}
        row['context_evidence'] = evidence
        row['history_evidence'] = dict(row['history_evidence'], external_context=evidence)
        out.append(_bind_feature_input(row))
    return out
