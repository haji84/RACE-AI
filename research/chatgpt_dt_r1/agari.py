"""Past agari (official final half lap) interactions; no full-lap conversion.

All values are derived from the already bound pre-race feature matrix, not
target results. Cross-venue raw seconds are not interpreted as physical speed.
Products are statistical hypotheses, not causal estimates. Missing components
zero their products; explicit availability features retain the distinction.
"""
from __future__ import annotations

import numpy as np

from .features import _bind_feature_input
from .model import _verify_feature_binding

VERSION = 'agari-interactions-v1'
PREFIX = 'history_agari_'
CONTEXT_PREFIX = 'history_agari_context_'
STYLE = ('nige','ryo','oi','makuri','sashi','jizai')
ROLES = ('leader','second','third_plus','solo')
GEOMETRY = ('circumference_m','straight_m','cant_deg','home_width_m','back_width_m','center_width_m')
WEATHER = ('wind_speed_m_s','gust_m_s','temperature_c','humidity_percent','precipitation_mm')
WIND = ('home_headwind','home_crosswind','back_headwind','back_crosswind')
SIGNALS = ('overall_relative','venue_relative')
# The official archive averages are normalized seconds (seconds/20).
BASE_KEYS = (
    'overall_relative','venue_relative','venue_vs_overall','overall_present','venue_present',
    'overall_relative_available','venue_relative_available',
    'overall_sample_fraction','venue_sample_fraction',
)
BASE_INTERACTIONS = tuple(f'{signal}_x_style_{style}' for signal in SIGNALS for style in STYLE) + tuple(
    f'{signal}_x_role_{role}' for signal in SIGNALS for role in ROLES) + tuple(
    f'{signal}_x_line_size' for signal in SIGNALS)
CONTEXT_KEYS = (
    'observed_venue_relative','observed_venue_present','observed_relative_available',
    'observed_recent_minus_mean','observed_best_minus_mean','observed_variance',
)
CONTEXT_INTERACTIONS = tuple(f'{signal}_x_bank_{g}' for signal in ('venue_relative','observed_venue_relative') for g in GEOMETRY) + tuple(
    f'{signal}_x_weather_{w}' for signal in ('venue_relative','observed_venue_relative') for w in WEATHER + WIND) + tuple(
    f'venue_relative_x_bank_{g}_x_style_{s}' for g in ('circumference_m','straight_m','cant_deg') for s in ('nige','oi','makuri','sashi')) + tuple(
    f'venue_relative_x_weather_{w}_x_role_{role}' for w in ('wind_speed_m_s','back_headwind','precipitation_mm') for role in ROLES)
AGARI_NAMES = tuple(PREFIX + k for k in BASE_KEYS + BASE_INTERACTIONS) + tuple(
    CONTEXT_PREFIX + k for k in CONTEXT_KEYS + CONTEXT_INTERACTIONS)


def uses_agari(names):
    return any(name.startswith(PREFIX) for name in names)


def augment_agari(rows):
    """Same deterministic transform at fitting, inference and independent replay."""
    out = []
    for original in rows:
        _verify_feature_binding(original)
        names = tuple(original['feature_names'])
        if uses_agari(names):
            raise ValueError('AGARI_FEATURES_ALREADY_ATTACHED')
        row = dict(original)
        x = np.asarray(row['features'], dtype=np.float64)
        n = len(x)
        cols = {name: x[:, i] for i, name in enumerate(names)}
        zero = np.zeros(n)
        def col(k):
            return cols.get(k, zero)
        def valid(k, missing):
            return (col(missing) == 0) & (k in cols) & (missing in cols)
        def relative(v, known):
            if np.count_nonzero(known) < 2:
                return zero.copy(), zero.copy()
            return np.where(known, float(v[known].mean()) - v, 0.), known.astype(float)
        def count(log_col):
            return np.clip(np.expm1(col(log_col) * np.log(21.)) / 20., 0., 1.)
        overall = col('history_half_lap_mean')
        venue = col('history_venue_half_lap_mean')
        has_overall = valid('history_half_lap_mean', 'history_half_lap_missing')
        has_venue = valid('history_venue_half_lap_mean', 'history_venue_half_lap_missing')
        og, og_ok = relative(overall, has_overall)
        vg, vg_ok = relative(venue, has_venue)
        values = {
            'overall_relative': og, 'venue_relative': vg,
            'venue_vs_overall': np.where(has_overall & has_venue, overall - venue, 0.),
            'overall_present': has_overall.astype(float), 'venue_present': has_venue.astype(float),
            'overall_relative_available': og_ok, 'venue_relative_available': vg_ok,
            'overall_sample_fraction': np.where(has_overall, count('history_half_lap_log'), 0.),
            'venue_sample_fraction': np.where(has_venue, count('history_venue_half_lap_log'), 0.),
        }
        # Solo means a known singleton, not an unknown line or a women's
        # race with no applicable formal line. Third+ is not "tail" (a pair
        # has a tail, but not a third rider).
        known_line = col('line_known') > .5
        solo = known_line & (col('line_size_fraction') * n < 1.5)
        roles = {
            'solo': solo,
            'leader': known_line & ~solo & (col('line_leader') > .5),
            'second': known_line & (col('line_second') > .5),
            'third_plus': known_line & (col('line_position_fraction') >= .25),
        }
        for signal in SIGNALS:
            v = values[signal]
            for style in STYLE:
                values[f'{signal}_x_style_{style}'] = v * col('style_' + style)
            for role in ROLES:
                values[f'{signal}_x_role_{role}'] = v * roles[role]
            values[f'{signal}_x_line_size'] = v * col('line_size_fraction') * known_line
        obs = 'history_observed_agari_half_seconds_'
        observed = col(obs + 'mean')
        present = valid(obs + 'mean', obs + 'mean_missing')
        ov, ov_ok = relative(observed, present)
        cv = {
            'observed_venue_relative': ov,
            'observed_venue_present': present.astype(float),
            'observed_relative_available': ov_ok,
            'observed_recent_minus_mean': np.where(present & valid(obs+'recent',obs+'recent_missing'), col(obs+'recent')-observed, 0.),
            'observed_best_minus_mean': np.where(present & valid(obs+'min',obs+'min_missing'), col(obs+'min')-observed, 0.),
            'observed_variance': np.where(present & valid(obs+'variance',obs+'variance_missing'), col(obs+'variance'), 0.),
        }
        banks = {g: np.where(valid('context_venue_'+g,'context_venue_'+g+'_missing'),col('context_venue_'+g),0.) for g in GEOMETRY}
        weather = {w: np.where(valid('context_weather_'+w,'context_weather_'+w+'_missing'),col('context_weather_'+w),0.) for w in WEATHER}
        for w in WIND:
            weather[w] = np.where(valid('context_'+w,'context_directional_wind_missing'),col('context_'+w),0.)
        for signal, v in (('venue_relative',vg),('observed_venue_relative',ov)):
            for g, value in banks.items():
                cv[f'{signal}_x_bank_{g}'] = v*value
            for w, value in weather.items():
                cv[f'{signal}_x_weather_{w}'] = v*value
        for g in ('circumference_m','straight_m','cant_deg'):
            for s in ('nige','oi','makuri','sashi'):
                cv[f'venue_relative_x_bank_{g}_x_style_{s}'] = vg*banks[g]*col('style_'+s)
        for w in ('wind_speed_m_s','back_headwind','precipitation_mm'):
            for role in ROLES:
                cv[f'venue_relative_x_weather_{w}_x_role_{role}'] = vg*weather[w]*roles[role]
        extra = np.column_stack([values[k] for k in BASE_KEYS + BASE_INTERACTIONS] + [cv[k] for k in CONTEXT_KEYS + CONTEXT_INTERACTIONS])
        if not np.isfinite(extra).all():
            raise ValueError('NONFINITE_AGARI_FEATURES')
        row['features'] = np.concatenate((x, extra), axis=1)
        row['feature_names'] = names + AGARI_NAMES
        row['feature_version'] = original['feature_version'] + '+' + VERSION
        row['history_evidence'] = dict(original['history_evidence'], agari_interactions={
            'version': VERSION, 'official_half_lap_only': True,
            'overall_riders': int(has_overall.sum()), 'same_venue_riders': int(has_venue.sum()),
            'observed_venue_riders': int(present.sum()), 'source': 'bound_prior_features_only'})
        out.append(_bind_feature_input(row))
    return out
