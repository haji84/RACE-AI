"""Development-only favorite-failure comparison on the frozen DT-R1 law."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from math import isclose, log, log1p
import os
from pathlib import Path
import signal
import subprocess
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from research.chatgpt_dt_r1.boosted_first_study import _features, marginal, reweight_joint, week_groups
from research.chatgpt_dt_r1.data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from research.chatgpt_dt_r1.frozen_followup import GEOMETRY, OLD_DATASET, ROOT, FeatureBuilder, check
from research.chatgpt_dt_r1.historical_replay import digest_file
from research.chatgpt_dt_r1.history_mix_study import METRICS, PROPER_METRICS, _score, _sums, _summary, paired_difference
from research.chatgpt_dt_r1.pipeline import _result_key, write_private_json
from research.chatgpt_dt_r1.policy import digest
from research.chatgpt_dt_r1.ranking_objective_study import EXPECTED_JULY, PERIODS, select


BASE = 'frozen'
ARMS = {'intercept': 1, 'context': 4}
BASIS = ('intercept', 'line_unknown_or_not_applicable', 'favorite_line_teammates_divided_by_eight',
         'other_multi_rider_lines_divided_by_eight')
RIDGE = .01
MAX_ITERATIONS = 40
MAX_SECONDS = 540


def specification():
    return dict(schema='DT_R1_FAVORITE_FAILURE_CONTRACT_V1', periods=PERIODS, prior_days=7,
                arms={name: BASIS[:size] for name, size in ARMS.items()}, ridge=RIDGE,
                max_iterations=MAX_ITERATIONS, max_seconds=MAX_SECONDS,
                favorite='greatest frozen first-place marginal, tied to lowest car number',
                target='favorite wins; a loss is its binary complement',
                objective='binary penalized log likelihood with frozen log-odds offset',
                normalization='rescale each favorite-wins and favorite-loses stratum uniformly',
                exacta='sum over third place in adjusted ordered trifecta',
                alternative='highest conditional winner marginal from the favorite-loses stratum; tied to lowest car',
                june_guard=dict(metrics=PROPER_METRICS, tolerance=1e-12, priority=['tri1', 'ex1'],
                                rank_gain_required=True),
                july='single developmental comparison, no selection or retuning',
                association_only=True, august_or_later_used_for_study=False,
                expected_july_scored=EXPECTED_JULY)


def favorite(joint):
    winner = marginal(joint, count=1)
    (car,) = min(winner, key=lambda key: (-winner[key], key))
    return car, winner[(car,)]


def context(row, car):
    if not row['lines_known']:
        return 1., 1., 0., 0.
    groups = row['line_groups']
    own = next(group for group in groups if car in group)
    other_lines = sum(len(group) > 1 for group in groups if car not in group)
    return 1., 0., (len(own) - 1) / 8., other_lines / 8.


def _logit(p):
    return log(p) - log1p(-p)


def adjusted_win_probability(frozen_win, inputs, weights):
    correction = float(np.dot(inputs, weights))
    return float(expit(_logit(frozen_win) + correction)) if correction else frozen_win


def correct_joint(joint, car, frozen_win, adjusted_win):
    if frozen_win == adjusted_win:
        return joint
    first = {rider: mass * (1. - adjusted_win) / (1. - frozen_win)
             for (rider,), mass in marginal(joint, count=1).items()}
    first[car] = adjusted_win
    return reweight_joint(joint, first)


def fit(design, offset, target):
    def objective(weights):
        weighted = offset + design @ weights
        loss = np.logaddexp(0., weighted).mean() - np.dot(target, weighted) / len(target)
        grad = design.T @ (expit(weighted) - target) / len(target)
        return float(loss + .5 * RIDGE * np.dot(weights, weights)), grad + RIDGE * weights

    solved = minimize(objective, np.zeros(design.shape[1]), method='L-BFGS-B', jac=True,
                      options={'maxiter': MAX_ITERATIONS, 'gtol': 1e-6})
    check(solved.success and np.isfinite(solved.x).all(), 'FAVORITE_FAILURE_OPTIMIZATION')
    return solved.x, dict(parameter_sha256=digest(solved.x.tolist()), converged=True,
                          iterations=int(solved.nit), objective=float(solved.fun))


def select_candidate(metrics):
    # First enforce the existing proper-score guard and rank ordering.
    chosen = select(metrics)
    rank = lambda values: (values['tri1'], values['ex1'])
    return chosen if rank(metrics[chosen]) > rank(metrics[BASE]) else BASE


def _period(records, phase, model, venues, at):
    seen = set()
    for day, rows, earlier in week_groups(records, *PERIODS[phase]):
        scorable = [(record, truth) for record in rows if (truth := _result_key(record)) is not None]
        frames = []
        if scorable:
            inputs, truths = zip(*scorable, strict=True)
            builder = FeatureBuilder()
            for _, history in earlier:
                builder.update_day(history)
            projected = _features(inputs, builder, model, venues, at)
            for original, row, truth in zip(inputs, projected, truths, strict=True):
                rid = original['race_id']
                check(rid not in seen, 'FAVORITE_FAILURE_DUPLICATE_RACE')
                seen.add(rid)
                joint = {tuple(t['cars']): t['probability'] for t in model.distribution(row)['trifectas']}
                car, win = favorite(joint)
                check(0. < win < 1. and truth in joint and isclose(sum(joint.values()), 1., abs_tol=1e-10),
                      'FAVORITE_FAILURE_FROZEN_LAW')
                status = row['line_status'] if row['lines_applicable'] else 'NOT_APPLICABLE'
                frames.append((rid, row['input_sha256'], status, joint, car, win, context(row, car), truth))
        yield day.isoformat(), len(rows), frames


def _coverage(registered, keys, status):
    n = len(keys)
    check(n > 0 and n <= registered and sum(status.values()) == n, 'FAVORITE_FAILURE_COHORT')
    return dict(registered=registered, scored=n, excluded_no_unique_top3=registered - n,
                line_status=dict(sorted(status.items())), race_input_cohort_sha256=digest(keys))


def _training(records, model, venues, at):
    design, offset, labels, keys = [], [], [], []
    registered, status = 0, Counter()
    for _, count, frames in _period(records, 'fit', model, venues, at):
        registered += count
        for rid, pin, line_status, _, car, win, inputs, truth in frames:
            keys.append((rid, pin))
            status[line_status] += 1
            design.append(inputs)
            offset.append(_logit(win))
            labels.append(float(car == truth[0]))
    return np.asarray(design), np.asarray(offset), np.asarray(labels), _coverage(registered, keys, status)


def _evaluate(records, phase, model, venues, at, fits):
    days, keys, favorite_masses = {}, [], {}
    registered, status, favorite_lost, alternate_hits = 0, Counter(), 0, 0
    for day, count, frames in _period(records, phase, model, venues, at):
        registered += count
        scores = {name: [] for name in (BASE, *fits)}
        for rid, pin, line_status, joint, car, win, inputs, truth in frames:
            keys.append((rid, pin))
            status[line_status] += 1
            scores[BASE].append(_score(joint, truth))
            event = float(truth[0] == car)
            if not event:
                favorite_lost += 1
                other = {r: p for (r,), p in marginal(joint, count=1).items() if r != car}
                alternate_hits += int(min(other, key=lambda r: (-other[r], r)) == truth[0])
            for name, weights in fits.items():
                adjusted = adjusted_win_probability(win, inputs[:len(weights)], weights)
                scores[name].append(_score(correct_joint(joint, car, win, adjusted), truth))
                favorite_masses.setdefault(name, []).append((adjusted, event))
            favorite_masses.setdefault(BASE, []).append((win, event))
        if frames:
            days[day] = {name: _sums(s) for name, s in scores.items()}
    coverage = _coverage(registered, keys, status)
    metrics = _summary(days)
    for name, rows in favorite_masses.items():
        p, event = np.asarray(rows).T
        check(len(p) == metrics[name]['n'] == coverage['scored'], 'FAVORITE_FAILURE_SCORING_DENOMINATOR')
        metrics[name]['favorite_win_probability'] = dict(
            predicted_mean=float(p.mean()), observed_rate=float(event.mean()),
            binary_brier=float(np.mean((p - event) ** 2)),
            binary_log_loss=float(np.mean(-np.log(np.where(event, p, 1. - p)))))
    return dict(coverage, days=len(days), metrics=metrics,
                observed_favorite_losses=favorite_lost,
                top_alternative_winner_hits_when_favorite_lost=alternate_hits), days


def run(paths, private):
    before = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    contract = specification()
    registration = dict(contract=contract, contract_sha256=digest(contract), registered_at=at,
                        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                        study_source_sha256=digest_file(Path(__file__)))
    write_private_json(private / 'contract.json', registration)
    records, audit = load_archives(paths)
    check(audit['dataset_sha256'] == OLD_DATASET, 'FAVORITE_FAILURE_ARCHIVE_PIN')
    records = [record for record in records if record['day'] <= PERIODS['july'][1]]
    model, venues = load_frozen(ROOT.parents[1])
    check(model is not None, 'FAVORITE_FAILURE_FROZEN_MODEL')
    print('PINNED_INPUTS_VERIFIED', flush=True)
    design, offset, labels, training = _training(records, model, venues, at)
    solutions, fits = {}, {}
    for name, size in ARMS.items():
        solutions[name], fits[name] = fit(design[:, :size], offset, labels)
    print('FIXED_CORRECTIONS_FIT', training['scored'], flush=True)
    june, _ = _evaluate(records, 'june', model, venues, at, solutions)
    by_guard = {name: {**cell['hits'], **cell['proper']} for name, cell in june['metrics'].items()}
    selected = select_candidate(by_guard)
    freeze = dict(selected=selected, frozen_at=datetime.now(timezone.utc).isoformat(),
                  fit_parameter_sha256={name: row['parameter_sha256'] for name, row in fits.items()})
    write_private_json(private / 'june-selection.json', freeze)
    print('JUNE_SELECTION_FROZEN', selected, flush=True)
    july, days = _evaluate(records, 'july', model, venues, at, solutions)
    check(july['scored'] == EXPECTED_JULY, 'FAVORITE_FAILURE_JULY_COHORT')
    july['paired_day_bootstrap_deltas'] = {
        f'{a}_minus_{b}': paired_difference(days, a, b, metrics=METRICS)
        for a, b in (('intercept', BASE), ('context', BASE), ('context', 'intercept'))}
    return dict(registration, schema='DT_R1_FAVORITE_FAILURE_STUDY_V1',
                scope='RETROSPECTIVE_REUSED_ARCHIVE_DEVELOPMENTAL',
                archive=dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET,
                             official_identity_authenticated=False, pre_cutoff_authenticated=False),
                frozen=dict(model_sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA, geometry_sha256=GEOMETRY,
                            fit_period_overlaps_training_and_june=True, calibration_and_selection_overlap_july=True),
                training=dict(training, fits=fits), june=dict(june, selection=freeze), july=july,
                production_promoted=False, elapsed_seconds=round(time.monotonic() - before, 3),
                stop_reason='NO_ELIGIBLE_FIXED_CORRECTION' if selected == BASE else 'FIXED_PILOT_COMPLETED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private', type=Path)
    parser.add_argument('archives', nargs=2, type=Path)
    args = parser.parse_args()
    private = args.private.resolve()
    check(private.is_dir() and not any(private.iterdir()) and not private.stat().st_mode & 0o077 and
          not any((path / '.git').exists() for path in (private, *private.parents)), 'PRIVATE_WORKSPACE_REQUIRED')
    os.umask(0o077)

    def timeout(*_):
        raise TimeoutError('FAVORITE_FAILURE_STUDY_TIME_BUDGET_EXHAUSTED')

    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(MAX_SECONDS)
    try:
        report = run(args.archives, private)
        write_private_json(private / 'aggregate.json', report)
    finally:
        signal.alarm(0)
    print('AGGREGATE_SAVED', report['elapsed_seconds'], flush=True)


if __name__ == '__main__':
    main()
