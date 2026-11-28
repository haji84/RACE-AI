"""Developmental frozen-DT-R1 probability pool. No production promotion.

Preregistered comparison: use the same archived racecard and the same locked
462-feature ranker with empty history and with results from the exact prior
seven JST days. Alpha is the probability weight on seven-day history, from
0, .25, .50, .75, 1. Learn on June 2026 only. One candidate minimizes joint
trifecta log loss, ties to lower alpha. The other maximizes, lexicographically,
3T@1, 2T@1, 3T@2, 3T@4, 2T@2, then prefers lower alpha, subject to June joint
trifecta log loss at most that of cold. Freeze both alpha values before
scoring July, then evaluate once on the common 2,393 races with a unique 3T.
The frozen engine's fitted weights include June and its temperature and
model choice used July. July is developmental, not an independent test.
August onward results are not used. Archived outcome availability
and official registration identity are unverified in this study.
"""
import argparse
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from math import fsum, isclose, isfinite, log
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from scripts.keirin_dt_r1_future_shadow import MODEL_SHA, MODEL_FILE_SHA, load_frozen

from .data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import (GEOMETRY, OLD_DATASET, ROOT, FeatureBuilder, augment_abilities,
                              augment_agari, augment_features, blind_target, check)
from .historical_replay import digest_file
from .pipeline import _result_key, write_private_json
from .policy import digest


GRID = (0., .25, .50, .75, 1.)
TRAIN_START = date(2026, 6, 1)
EVAL_START = date(2026, 7, 1)
EVAL_END = date(2026, 7, 31)
EXPECTED_JULY = 2393
RANK_METRICS = ('tri1', 'ex1', 'tri2', 'tri4', 'ex2')
PROPER_METRICS = ('tri_log_loss', 'ex_log_loss', 'tri_brier', 'ex_brier')
METRICS = RANK_METRICS + PROPER_METRICS
BOOTSTRAP_SEED = 462
BOOTSTRAP_N = 2000


def specification():
    return dict(schema='DT_R1_JUNE_HISTORY_MIX_CONTRACT_V1', grid=GRID,
        alpha_definition='probability_weight_on_exact_prior_seven_jst_days',
        train_days=[TRAIN_START.isoformat(), (EVAL_START - timedelta(days=1)).isoformat()],
        evaluation_days=[EVAL_START.isoformat(), EVAL_END.isoformat()],
        evaluation_expected_common_races=EXPECTED_JULY, joint_market='trifecta',
        exacta='marginal_prefix_of_joint_trifecta',
        objectives={'log_loss': ['min_joint_trifecta_log_loss', 'min_alpha'],
                    'top_ranks_guarded': [*RANK_METRICS, 'min_alpha']},
        top_ranks_guard='june_joint_trifecta_log_loss_no_worse_than_cold',
        bootstrap=dict(unit='paired_jst_day', samples=BOOTSTRAP_N, seed=BOOTSTRAP_SEED),
        companions=['cold', 'seven', 'long'], use_august_or_later=False,
        official_identity_available=False, pre_cutoff_time_verified=False,
        scope='RETROSPECTIVE_REUSED_ARCHIVE_DEVELOPMENTAL')


def prior_week(groups, target_day):
    first = target_day - timedelta(days=7)
    return (rows for day, rows in groups if first <= day < target_day)


def mix_joint(cold, recent, alpha):
    check(type(alpha) in (int, float) and 0 <= alpha <= 1 and cold and cold.keys() == recent.keys(),
          'MIXTURE_SUPPORT')
    for values in (cold.values(), recent.values()):
        check(all(isfinite(p) and p >= 0 for p in values) and isclose(fsum(values), 1., abs_tol=1e-12),
              'MIXTURE_MASS')
    return {ticket: (1 - alpha) * p + alpha * recent[ticket] for ticket, p in cold.items()}


def exacta_marginal(joint):
    groups = defaultdict(list)
    for triple, mass in joint.items():
        groups[triple[:2]].append(mass)
    return {pair: fsum(masses) for pair, masses in groups.items()}


def select_alphas(cells):
    best_loss = min(cells, key=lambda alpha: (cells[alpha]['tri_log_loss'], alpha))
    eligible = [alpha for alpha in cells if cells[alpha]['tri_log_loss'] <= cells[0.]['tri_log_loss']]
    best_ranks = max(eligible, key=lambda alpha: (*[cells[alpha][key] for key in RANK_METRICS], -alpha))
    return dict(log_loss=best_loss, top_ranks_guarded=best_ranks)


def paired_difference(days, left, right, *, metrics=METRICS):
    ordered = [days[day] for day in sorted(days)]
    check(ordered and all(item[left]['n'] == item[right]['n'] > 0 for item in ordered), 'PAIRED_DENOMINATOR')
    n = np.array([item[left]['n'] for item in ordered])
    picks = np.random.default_rng(BOOTSTRAP_SEED).integers(0, len(n), (BOOTSTRAP_N, len(n)))
    bootstrap_n = n[picks].sum(axis=1)
    out = {}
    for key in metrics:
        d = np.array([item[left][key] - item[right][key] for item in ordered])
        intervals = np.quantile(d[picks].sum(axis=1) / bootstrap_n, [.025, .975])
        out[key] = dict(delta=float(d.sum() / n.sum()), ci95=intervals.tolist())
    return out


def _score(joint, truth):
    exacta = exacta_marginal(joint)
    by_prob = lambda values: sorted(values, key=lambda ticket: (-values[ticket], ticket))
    tri, two = by_prob(joint), by_prob(exacta)
    actual_two = truth[:2]
    tri_mass, ex_mass = joint[truth], exacta[actual_two]
    return dict(tri1=int(truth == tri[0]), tri2=int(truth in tri[:2]), tri4=int(truth in tri[:4]),
        ex1=int(actual_two == two[0]), ex2=int(actual_two in two[:2]),
        tri_log_loss=-log(max(tri_mass, 1e-300)), ex_log_loss=-log(max(ex_mass, 1e-300)),
        tri_brier=1. - 2. * tri_mass + fsum(p*p for p in joint.values()),
        ex_brier=1. - 2. * ex_mass + fsum(p*p for p in exacta.values()))


def _projected_days(records, model, venue_store, at):
    cold, long, queue = FeatureBuilder(), FeatureBuilder(), deque()
    for stamp, group in groupby(records, key=lambda row: row['day']):
        day = date.fromisoformat(stamp)
        if day > EVAL_END:
            break
        rows = list(group)
        while queue and queue[0][0] < day - timedelta(days=7):
            queue.popleft()
        if day >= TRAIN_START:
            seven = FeatureBuilder()
            for prior in prior_week(queue, day):
                seven.update_day(prior)
            blinded = [blind_target(row) for row in rows]
            frames = {}
            for name, builder in (('cold', cold), ('seven', seven), ('long', long)):
                if name == 'long' and day < EVAL_START:
                    continue
                context = augment_features([builder.transform(row) for row in blinded], venue_store=venue_store,
                                           as_of=at, allow_current_geometry_assumption=True)
                featured = augment_abilities(augment_agari(context))
                frames[name] = []
                for original, row in zip(rows, featured, strict=True):
                    check(row['race_id'] == original['race_id'] and row['input_sha256'] == original['input_sha256']
                          and tuple(row['feature_names']) == model.feature_names, 'COMMON_FROZEN_INPUT')
                    if row['feature_status'] != 'READY':
                        frames[name].append(None)
                        continue
                    d = model.distribution(row)['trifectas']
                    frames[name].append({tuple(item['cars']): item['probability'] for item in d})
            yield day, rows, frames
        long.update_day(rows)
        queue.append((day, rows))


def _sums(scores):
    return {'n': len(scores), **{key: fsum(row[key] for row in scores) for key in METRICS}}


def _collect(rows, frames, policies):
    day = {name: [] for name in policies}
    excluded = 0
    for i, row in enumerate(rows):
        truth = _result_key(row)
        if truth is None:
            excluded += 1
            continue
        check(all(frame[i] is not None for frame in frames.values()), 'COMMON_PREDICTED_RESULT_REQUIRED')
        cold, seven = frames['cold'][i], frames['seven'][i]
        pools = {alpha: mix_joint(cold, seven, alpha) for alpha in set(policies.values()) - {None}}
        if None in policies.values():
            pools[None] = frames['long'][i]
        for name, alpha in policies.items():
            day[name].append(_score(pools[alpha], truth))
    return {name: _sums(rows) for name, rows in day.items()}, excluded


def _summary(days):
    first = next(iter(days.values()))
    report = {}
    for name in first:
        n = sum(day[name]['n'] for day in days.values())
        check(n > 0, 'SCORABLE_ROWS_REQUIRED')
        sums = {k: fsum(day[name][k] for day in days.values()) for k in METRICS}
        report[name] = dict(n=n, hits={k: int(sums[k]) for k in RANK_METRICS},
            rates={k: sums[k] / n for k in RANK_METRICS},
            proper={k: sums[k] / n for k in PROPER_METRICS})
    return report


def evaluate(paths, private):
    start = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    contract = specification()
    contract_sha = digest(contract)
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    write_private_json(private / 'contract.json', dict(contract=contract, contract_sha256=contract_sha,
        code_base=code, study_sha256=digest_file(Path(__file__)), registered_at=at))
    model, venues = load_frozen(ROOT.parents[1])
    check({path.name for path in paths} == PINNED_SOURCE_SHA256.keys() and len(paths) == 2, 'ARCHIVE_PAIR')
    records, audit = load_archives(paths)
    check(audit['dataset_sha256'] == OLD_DATASET and len(records) == 30713, 'ARCHIVE_DATASET_PIN')
    train, evaluate_days, choices, evaluated = {}, {}, None, (0, 0)
    for day, rows, frames in _projected_days(records, model, venues, at):
        if day < EVAL_START:
            train[day.isoformat()], _ = _collect(rows, frames, {alpha: alpha for alpha in GRID})
            continue
        if choices is None:
            June = _summary(train)
            choices = select_alphas({alpha: {**d['proper'], **d['hits']} for alpha, d in June.items()})
            parameters = dict(schema='DT_R1_JUNE_HISTORY_MIX_PARAMETERS_V1', contract_sha256=contract_sha,
                              model_sha256=MODEL_SHA, alphas=choices)
            parameters_sha = digest(parameters)
            write_private_json(private / 'parameters.json', dict(parameters=parameters,
                parameters_sha256=parameters_sha, frozen_at=datetime.now(timezone.utc).isoformat()))
            print('JUNE_PARAMETERS_FROZEN', len(train), parameters_sha, flush=True)
        policies = dict(cold=0., seven=1., long=None, **choices)
        metrics, held = _collect(rows, frames, policies)
        evaluate_days[day.isoformat()] = metrics
        evaluated = (evaluated[0] + len(rows), evaluated[1] + held)
    July = _summary(evaluate_days)
    check(all(item['n'] == EXPECTED_JULY for item in July.values()) and
          evaluated[0] - evaluated[1] == EXPECTED_JULY, 'JULY_FROZEN_DENOMINATOR')
    return dict(schema='DT_R1_JUNE_HISTORY_MIX_STUDY_V1', contract=contract, contract_sha256=contract_sha,
        code_base=code, study_sha256=digest_file(Path(__file__)), started_at=at,
        runtime_seconds=round(time.monotonic() - start, 3), production_promoted=False,
        model=dict(id='chatgpt-dt-r1', sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA,
                   feature_count=len(model.feature_names), weight_fit_overlaps_june=True,
                   temperature_and_selection_overlap_july=True),
        archive=dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET,
                     current_geometry_assumption_sha256=GEOMETRY),
        selection=dict(june_grid=June, parameters=parameters, parameters_sha256=parameters_sha),
        july=dict(cards=evaluated[0], excluded_without_unique_trifecta=evaluated[1], days=len(evaluate_days),
            common_scorable=EXPECTED_JULY, metrics=July,
            compared_with_cold={name: paired_difference(evaluate_days, name, 'cold')
                                for name in policies if name != 'cold'},
            candidate_comparison=paired_difference(evaluate_days, 'top_ranks_guarded', 'log_loss')))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('private', type=Path, help='An empty, owner-only directory outside the repository.')
    cli.add_argument('archives', type=Path, nargs=2)
    args = cli.parse_args()
    os.umask(0o077)
    private = args.private.resolve()
    check(private.is_dir() and not any(private.iterdir()) and not private.stat().st_mode & 0o077 and
          not any((parent / '.git').exists() for parent in (private, *private.parents)), 'PRIVATE_RUNNER_PATH')
    receipt = evaluate(args.archives, private)
    write_private_json(private / 'aggregate.json', receipt)
    print('AGGREGATE_SAVED', receipt['runtime_seconds'], flush=True)


if __name__ == '__main__':
    main()
