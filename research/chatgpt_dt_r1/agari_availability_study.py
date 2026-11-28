"""Paired frozen-DT-R1 study of the availability of archived final half-lap times."""
import argparse
from collections import Counter, deque
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
import json
from math import isfinite
from pathlib import Path
import os
import signal
import subprocess
import time

import numpy as np

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .abilities import DISC_NAMES, DISC_PAIRS, PREFIX as ABILITY_PREFIX
from .agari import AGARI_NAMES
from .boosted_first_study import _features, _joint, validate_july
from .data import IDENTITY_STATUS, PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import GEOMETRY, OLD_DATASET, OLD_N, ROOT, check
from .historical_replay import digest_file
from .history_mix_study import (BOOTSTRAP_N, BOOTSTRAP_SEED, EVAL_END, EVAL_START, EXPECTED_JULY,
                                METRICS, _score, _summary, _sums, paired_difference)
from .history_window_study import history_projection, prior_builder
from .pipeline import _result_key, write_private_json
from .policy import digest


WINDOW = 7
WIDTH = timedelta(days=WINDOW)
ARMS = ('place_only', 'place_and_half_lap')
SUBGROUPS = ('all', '7_cars', '9_cars')
BASE_TIMING = ('history_half_lap_', 'history_venue_half_lap_')
AGARI_DESCENDANTS = {ABILITY_PREFIX + 'agari_x_pressure', *(
    name for name, parents in zip(DISC_NAMES, DISC_PAIRS, strict=True)
    if any(parent in AGARI_NAMES for parent in parents))}
MAX_SECONDS = 360
PREVIOUS = ROOT / 'evidence/20261128-engine-history-followup/history-window-aggregate.json'
PREVIOUS_SHA256 = 'dd3221ae100d7f1fae9442541f2eef988bb140fc1d222fe503703e9c42d77297'


def specification():
    return dict(schema='DT_R1_AGARI_AVAILABILITY_CONTRACT_V1', scope='RETROSPECTIVE_DEVELOPMENT_ONLY',
        evaluation_days=[EVAL_START.isoformat(), EVAL_END.isoformat()], expected_common_scorable=EXPECTED_JULY,
        prior_jst_days=WINDOW, prior_target_day_excluded=True, target='same blinded card, no weather',
        arms=dict(place_only='history_window_study.history_projection',
                  place_and_half_lap='same prior roster and facts plus archived half_lap_seconds for numeric nonincident finishes'),
        accepted_timing='positive finite normalized archival agari field only',
        allowed_feature_changes=['half_lap_history', 'agari_interactions', 'existing_deterministic_agari_descendants'],
        excluded=['full_last_lap_seconds', 'historical_sb_mark', 'weather', 'current_race_outcomes'],
        metrics=METRICS, subgroups=SUBGROUPS,
        coverage=['target_races_with_timing', 'target_riders_with_timing', 'prior_timing_exposures',
                  'target_races_with_changed_features', 'target_riders_with_changed_features'],
        paired_bootstrap=dict(unit='JST day', samples=BOOTSTRAP_N, seed=BOOTSTRAP_SEED),
        archived_identity_scope=IDENTITY_STATUS, independent_official_registration_verified=False,
        availability_authenticated=False, current_geometry_shared_assumption=True,
        fitting=False, parameter_selection=False, independent_validation=False, production_promoted=False,
        threads=1, timeout_seconds=MAX_SECONDS)


def with_half_lap(projected, raw):
    """Extend only the same prior result row, leaving missing values untouched."""
    if projected is None:
        return None
    times = {row['car']: row.get('half_lap_seconds') for row in raw['result_rows']}
    results = []
    for row in projected['result_rows']:
        seconds = times[row['car']]
        if (type(row['rank']) is int and not row['incident'] and
                type(seconds) in (int, float) and isfinite(seconds) and seconds > 0):
            row = dict(row, half_lap_seconds=seconds)
        results.append(row)
    return dict(projected, result_rows=results)


def _groups(row):
    size = len(row['riders'])
    return ('all', f'{size}_cars') if size in (7, 9) else ('all',)


def _coverage(counts, base, treated, timing_mask):
    diff = base['features'] != treated['features']
    counts['target_rider_rows'] += len(diff)
    check(not np.any(diff[:, ~timing_mask]), 'NON_AGARI_FEATURE_CHANGED')
    changed = np.any(diff[:, timing_mask], axis=1)
    counts['target_races_with_changed_features'] += int(changed.any())
    counts['target_riders_with_changed_features'] += int(changed.sum())
    observations = [rider['timing_counts']['half_lap']
                    for rider in treated['history_evidence']['rider_evidence'].values()]
    counts['target_races_with_timing'] += int(any(observations))
    counts['target_riders_with_timing'] += sum(n > 0 for n in observations)
    counts['prior_timing_exposures'] += sum(observations)


def _matches_previous(all_scores, cohort_sha):
    check(digest_file(PREVIOUS) == PREVIOUS_SHA256, 'CONTROL_REFERENCE_SHA')
    previous = json.loads(PREVIOUS.read_text())['july']
    control, expected = all_scores[ARMS[0]], previous['metrics']['seven']
    check(cohort_sha == previous['common_cohort_sha256'] and control['n'] == expected['n'] and
          control['hits'] == expected['hits'] and
          all(abs(v - expected['proper'][k]) <= 1e-12 for k, v in control['proper'].items()),
          'PRIOR_CONTROL_NOT_REPRODUCED')


def evaluate(paths, private):
    start = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    contract = specification()
    run = dict(contract=contract, contract_sha256=digest(contract), study_sha256=digest_file(Path(__file__)),
        prior_control_aggregate_sha256=PREVIOUS_SHA256, started_at=at,
        code_base=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        inputs=dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET),
        frozen=dict(id='chatgpt-dt-r1', model_sha256=MODEL_SHA, model_file_sha256=MODEL_FILE_SHA,
                    geometry_sha256=GEOMETRY, july_overlaps_frozen_temperature_calibration=True))
    write_private_json(private / 'contract.json', run)
    print('CONTRACT_SAVED', run['contract_sha256'], run['study_sha256'], flush=True)
    check(len(paths) == 2 and {p.name for p in paths} == PINNED_SOURCE_SHA256.keys(), 'ARCHIVE_PAIR')
    frozen, venues = load_frozen(ROOT.parents[1])
    check(frozen is not None, 'FROZEN_MODEL_UNAVAILABLE')
    data, audit = load_archives(paths)
    check(len(data) == OLD_N and audit['dataset_sha256'] == OLD_DATASET, 'ARCHIVE_DATASET_PIN')
    print('PINNED_INPUTS_VERIFIED', flush=True)
    timing_mask = np.array([name in AGARI_NAMES or name in AGARI_DESCENDANTS or
                            name.startswith(BASE_TIMING) for name in frozen.feature_names])
    expected = [row['race_id'] for row in data if EVAL_START.isoformat() <= row['day'] <= EVAL_END.isoformat()
                and _result_key(row) is not None]
    recent = {arm: deque() for arm in ARMS}
    coverage, scores = {group: Counter() for group in SUBGROUPS}, {group: {} for group in SUBGROUPS}
    admitted, cards = [], 0
    for stamp, batch in groupby(data, key=lambda row: row['day']):
        day = date.fromisoformat(stamp)
        if day > EVAL_END:
            break
        if day < EVAL_START - WIDTH:
            continue
        for queue in recent.values():
            while queue and queue[0][0] < day - WIDTH:
                queue.popleft()
        rows = list(batch)
        if day >= EVAL_START:
            cards += len(rows)
            eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
            day_scores = {group: {arm: [] for arm in ARMS} for group in SUBGROUPS}
            if eligible:
                targets, truths = zip(*eligible, strict=True)
                admitted.extend(row['race_id'] for row in targets)
                views = [_features(targets, prior_builder(recent[arm], day, WINDOW), frozen, venues, at)
                         for arm in ARMS]
                for base, treated, truth in zip(*views, truths, strict=True):
                    check(base['race_id'] == treated['race_id'] and base['input_sha256'] == treated['input_sha256'],
                          'TARGET_BINDING_CHANGED')
                    a, b = _score(_joint(frozen, base), truth), _score(_joint(frozen, treated), truth)
                    for group in _groups(base):
                        _coverage(coverage[group], base, treated, timing_mask)
                        day_scores[group][ARMS[0]].append(a)
                        day_scores[group][ARMS[1]].append(b)
                for group, both in day_scores.items():
                    if both[ARMS[0]]:
                        scores[group][stamp] = {arm: _sums(both[arm]) for arm in ARMS}
        projected, supplemented = [], []
        for row in rows:
            base = history_projection(row)
            if base is not None:
                projected.append(base)
                supplemented.append(with_half_lap(base, row))
        recent[ARMS[0]].append((day, projected))
        recent[ARMS[1]].append((day, supplemented))
    validate_july(expected, admitted)
    cohort_sha = digest(sorted(admitted))
    metrics = {group: _summary(days) for group, days in scores.items()}
    _matches_previous(metrics['all'], cohort_sha)
    return dict(run, schema='DT_R1_AGARI_AVAILABILITY_STUDY_V1', no_promotions=True,
        runtime_seconds=round(time.monotonic() - start, 3), stop_reason='FIXED_DEVELOPMENT_COMPARISON_COMPLETED',
        july=dict(cards=cards, excluded_without_unique_trifecta=cards-len(admitted), common_scorable=len(admitted),
                  common_cohort_sha256=cohort_sha, prior_place_only_control_reproduced=True, coverage=coverage,
                  metrics=metrics, paired_deltas={group: paired_difference(days, ARMS[1], ARMS[0])
                                                  for group, days in scores.items()}))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('private', type=Path)
    cli.add_argument('archives', nargs=2, type=Path)
    args = cli.parse_args()
    os.umask(0o077)
    private = args.private.resolve()
    check(private.is_dir() and not any(private.iterdir()) and not private.stat().st_mode & 0o077 and
          not any((parent / '.git').exists() for parent in (private, *private.parents)), 'PRIVATE_RUNNER_PATH')

    def timeout(*_):
        raise TimeoutError('STUDY_TIME_BUDGET_EXHAUSTED')

    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(MAX_SECONDS)
    try:
        report = evaluate(args.archives, private)
        write_private_json(private / 'aggregate.json', report)
    finally:
        signal.alarm(0)
    print('AGGREGATE_SAVED', report['runtime_seconds'], flush=True)


if __name__ == '__main__':
    main()
