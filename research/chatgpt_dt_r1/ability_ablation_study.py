"""Frozen DT-R1 coefficient sensitivity across the owner's five abilities.

July 2026 is the old tuning month. Evaluate the baseline and five fixed
omissions on the same eligible races for long and seven-day archived history.
No refit, temperature changes or use of the previous August onward evaluation.
These interventions remove specific nonzero top-three inference coefficients,
including scoped derived interactions. Shared terms can belong to more than
one omission: the effects are neither additive nor causal. Failure inversion
is a post-inference diagnostic, so omission is an exact no-feedback control.
"""
import argparse
from collections import deque
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from math import fsum, log
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .abilities import DISC_NAMES, DISC_PAIRS
from .boosted_first_study import (_features, _joint, _score, marginal, validate_july,
                                 EXPECTED_JULY, SPLITS)
from .data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import GEOMETRY, OLD_DATASET, ROOT, FeatureBuilder, check
from .historical_replay import digest_file
from .history_mix_study import (BOOTSTRAP_N, BOOTSTRAP_SEED, METRICS, PROPER_METRICS,
                                 RANK_METRICS, paired_difference, prior_week)
from .model import PAIR_NAMES
from .pipeline import _result_key, write_private_json
from .policy import digest


DIRECT = {
    'latent': dict(prefixes=('history_half_lap_', 'history_venue_half_lap_', 'history_observed_agari_',
        'history_agari_', 'history_form_', 'history_win_', 'history_top2_', 'history_top3_',
        'history_same_class_', 'history_same_venue_', 'history_dt_form_change',
        'history_dt_agari_x_pressure'), contains=()),
    'depletion': dict(prefixes=('history_rest_', 'history_starts_', 'history_dt_recent_load_',
        'history_dt_line_front_exposure_', 'history_dt_line_shelter_', 'history_dt_line_state_',
        'history_dt_load_x_pressure', 'history_dt_weather_load_', 'history_dt_motion_',
        'context_weather_', 'context_directional_wind_', 'context_wind_'),
        contains=('_x_weather_', '_headwind', '_crosswind')),
    'interaction': dict(prefixes=('line_', 'history_dt_rival_', 'history_dt_third_line_',
        'history_dt_line_', 'history_dt_load_x_pressure', 'history_dt_agari_x_pressure'),
        contains=('_x_role_', '_x_line_size', '_x_leader', '_x_second')),
    'favorite_failure': dict(prefixes=(), contains=()),
}
HISTORY_ARM = ('long', 'seven')
FAMILIES = (*DIRECT, 'discovery')


def _matches(name, rule):
    return name.startswith(rule['prefixes']) or any(text in name for text in rule['contains'])


def ablations(frozen):
    """Preserve scaling, row bytes, tail coefficients and temperature."""
    cases, masks = {}, {}
    for family in FAMILIES:
        if family == 'discovery':
            columns = set(DISC_NAMES)
        else:
            rule = DIRECT[family]
            columns = {name for name in frozen.feature_names if _matches(name, rule)}
            columns.update(name for name, terms in zip(DISC_NAMES, DISC_PAIRS, strict=True)
                           if any(_matches(term, rule) for term in terms))
        positions = [i for i, name in enumerate(frozen.feature_names)
                     if name in columns and np.any(frozen.weights[:3, i])]
        if family == 'favorite_failure':
            cases[family] = frozen
            removed_pair = 0
        else:
            weights, pairs = frozen.weights.copy(), frozen.pair_weights.copy()
            weights[:3, positions] = 0.
            removed_pair = int(np.count_nonzero(pairs[1:3])) if family == 'interaction' else 0
            if family == 'interaction':
                pairs[1:3] = 0.
            cases[family] = replace(frozen, weights=weights, pair_weights=pairs)
        masks[family] = dict(
            effective_columns=[frozen.feature_names[i] for i in positions],
            removed_individual_coefficients=int(np.count_nonzero(frozen.weights[:3, positions])),
            removed_pair_coefficients=removed_pair,
            model_sha256=cases[family].to_dict()['model_sha256'])
    return cases, masks


def specification():
    return dict(schema='DT_R1_FIVE_ABILITIES_ABLATION_CONTRACT_V1', dates=SPLITS['july'],
        common_scorable=EXPECTED_JULY, histories=HISTORY_ARM, coefficients='nonzero_ranks_1_to_3_only',
        direct_rules=DIRECT, discovery_descendants='omit_if_any_direct_input_was_omitted',
        discovery='all_effective_DISC_names', pair_rule='interaction_only_rank_2_and_3',
        pair_names=PAIR_NAMES, pair_inputs='line_membership_position_and_competition_points_only',
        shared_inputs_retained=['current_profile', 'plain_venue_geometry', 'unscoped_history'],
        failure_rule='post_inference_no_ranker_coefficient_exact_null_control',
        bootstrap=dict(unit='paired_jst_day', draws=BOOTSTRAP_N, seed=BOOTSTRAP_SEED),
        causal=False, refit=False, old_final_used=False, independent_accuracy_claim=False)


def _days(data, frozen, venues, at):
    long, queue = FeatureBuilder(), deque()
    for stamp, group in groupby(data, key=lambda row: row['day']):
        day = date.fromisoformat(stamp)
        if stamp > SPLITS['july'][1]:
            break
        rows = list(group)
        while queue and queue[0][0] < day - timedelta(days=7):
            queue.popleft()
        if stamp >= SPLITS['july'][0]:
            eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
            if eligible:
                kept, outcomes = zip(*eligible)
                seven = FeatureBuilder()
                for prior in prior_week(queue, day):
                    seven.update_day(prior)
                yield stamp, kept, outcomes, {
                    'long': _features(kept, long, frozen, venues, at),
                    'seven': _features(kept, seven, frozen, venues, at)}
        long.update_day(rows)
        queue.append((day, rows))


def _score_day(rows, outcomes, cases, frozen):
    sums = {name: dict(n=len(rows), **dict.fromkeys(METRICS, 0.)) for name in ('full', *cases)}
    favorite_loss, favorite_brier, favorite_log_loss = [], [], []
    for row, truth in zip(rows, outcomes, strict=True):
        full = _joint(frozen, row)
        per_model = {'full': _score(full, truth)}
        for name, variant in cases.items():
            per_model[name] = per_model['full'] if variant is frozen else _score(_joint(variant, row), truth)
        for name, values in per_model.items():
            for metric, value in zip(METRICS, values, strict=True):
                sums[name][metric] += value
        first = marginal(full, count=1)
        favorite = max(first, key=lambda car: (first[car], -car[0]))
        predicted_loss = 1. - first[favorite]
        lost = truth[0] != favorite[0]
        favorite_loss.append(int(lost))
        favorite_brier.append((float(lost) - predicted_loss) ** 2)
        favorite_log_loss.append(-log(max(predicted_loss if lost else first[favorite], 1e-300)))
    return sums, dict(losses=sum(favorite_loss), brier_sum=fsum(favorite_brier),
                      log_loss_sum=fsum(favorite_log_loss))


def _rollup(daily, favorite):
    first = next(iter(daily.values()))
    hits_and_proper = {}
    for name in first:
        check(sum(d[name]['n'] for d in daily.values()) == EXPECTED_JULY, 'ABLATION_COMMON_DENOMINATOR')
        values = {key: fsum(d[name][key] for d in daily.values()) for key in METRICS}
        hits_and_proper[name] = dict(hits={k: int(values[k]) for k in RANK_METRICS},
                                    proper={k: values[k] / EXPECTED_JULY for k in PROPER_METRICS})
    return dict(metrics=hits_and_proper,
        ablated_minus_full={name: paired_difference(daily, name, 'full') for name in FAMILIES},
        favorite_failure=dict(observed_losses=sum(d['losses'] for d in favorite),
            brier=fsum(d['brier_sum'] for d in favorite) / EXPECTED_JULY,
            log_loss=fsum(d['log_loss_sum'] for d in favorite) / EXPECTED_JULY,
            affects_inference=False))


def run(paths, directory):
    started = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    script = digest_file(Path(__file__))
    spec = specification()
    spec_sha = digest(spec)
    frozen, venues = load_frozen(ROOT.parents[1])
    cases, masks = ablations(frozen)
    mask_sha = digest(masks)
    write_private_json(directory / 'contract.json', dict(contract=spec, contract_sha256=spec_sha,
        masks=masks, masks_sha256=mask_sha, code_base=code, script_sha256=script, started_at=at))
    check({p.name for p in paths} == PINNED_SOURCE_SHA256.keys() and len(paths) == 2, 'ARCHIVE_PAIR')
    data, audit = load_archives(paths)
    check(audit['dataset_sha256'] == OLD_DATASET and len(data) == 30713, 'FROZEN_ARCHIVE_PIN')
    cards = [r for r in data if SPLITS['july'][0] <= r['day'] <= SPLITS['july'][1]]
    expected = [r['race_id'] for r in cards if _result_key(r) is not None]
    validate_july(expected, expected)
    daily = {name: {} for name in HISTORY_ARM}
    favorite = {name: [] for name in HISTORY_ARM}
    seen = []
    for day, kept, outcomes, frames in _days(data, frozen, venues, at):
        seen.extend(row['race_id'] for row in kept)
        for name in HISTORY_ARM:
            item, inversion = _score_day(frames[name], outcomes, cases, frozen)
            daily[name][day] = item
            favorite[name].append(inversion)
        print('DAY_COMPARED', day, len(kept), flush=True)
    validate_july(expected, seen)
    report = {name: _rollup(daily[name], favorite[name]) for name in HISTORY_ARM}
    return dict(schema='DT_R1_FIVE_ABILITIES_ABLATION_STUDY_V1', code_base=code, script_sha256=script,
        started_at=at, runtime_seconds=round(time.monotonic() - started, 3), contract=spec,
        contract_sha256=spec_sha, masks=masks, masks_sha256=mask_sha, scopes=report,
        frozen_model=dict(sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA, feature_count=len(frozen.feature_names)),
        archive=dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET,
                     retrospective_venue_geometry_sha256=GEOMETRY,
                     official_registration_authentication=False, pre_cutoff_time_verified=False),
        july=dict(cards=len(cards), common_scorable=EXPECTED_JULY, days=len(daily['long']),
                  excluded_without_unique_trifecta=len(cards) - EXPECTED_JULY, cohort_sha256=digest(sorted(expected))))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('private', type=Path, help='An empty owner-only directory outside Git.')
    cli.add_argument('archives', type=Path, nargs=2)
    args = cli.parse_args()
    os.umask(0o077)
    directory = args.private.resolve()
    check(directory.is_dir() and not any(directory.iterdir()) and not directory.stat().st_mode & 0o077 and
          not any((parent / '.git').exists() for parent in (directory, *directory.parents)), 'PRIVATE_RUNNER_PATH')
    receipt = run(args.archives, directory)
    write_private_json(directory / 'aggregate.json', receipt)
    print('AGGREGATE_SAVED', receipt['runtime_seconds'], flush=True)


if __name__ == '__main__':
    main()
