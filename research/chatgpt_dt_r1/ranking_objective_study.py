"""Bounded comparison of two objectives on the same frozen DT-R1 joint law."""
import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
import os
import signal
import subprocess
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logsumexp

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .boosted_first_study import _features, week_groups
from .data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import GEOMETRY, OLD_DATASET, ROOT, FeatureBuilder, check
from .historical_replay import digest_file
from .history_mix_study import PROPER_METRICS, paired_difference
from .pipeline import _result_key, write_private_json
from .policy import digest


PERIODS = dict(fit=('2026-03-01', '2026-05-31'), june=('2026-06-01', '2026-06-30'),
               july=('2026-07-01', '2026-07-31'))
EXPECTED_JULY = 2393
OBJECTIVES = dict(nll=0., nll_rank=.25)
BASIS = ('points_1', 'points_2', 'points_3', 'attack_1', 'follow_2',
         'same_line_12', 'same_line_13', 'same_line_23')
RIDGE = .01
ITERATIONS = 40
MAX_SECONDS = 540
METRICS = ('tri1', 'ex1', *PROPER_METRICS)


def specification():
    return dict(schema='DT_R1_RANKING_OBJECTIVE_CONTRACT_V1',
                periods=PERIODS, basis=BASIS, points_definition='clip(points_relative/10,-3,3)',
                prior_days=7, expected_july_scored=EXPECTED_JULY,
                frozen_law='frozen-DT-R1-prior-seven-JST-days',
                objectives={name: dict(joint_nll=1., strongest_frozen_wrong_softplus=penalty)
                            for name, penalty in OBJECTIVES.items()},
                rival='highest frozen probability except the observed triple; lexical car tie break',
                optimizer=dict(method='L-BFGS-B', ridge=RIDGE, zero_start=True,
                               max_iterations=ITERATIONS, threads=1, max_seconds=MAX_SECONDS),
                june_guard=dict(metrics=PROPER_METRICS, tolerance=1e-12, baseline='frozen',
                                priority=['tri1', 'ex1', *PROPER_METRICS]),
                july='evaluate both fixed corrections and frozen; never use July to select',
                exacta='sum over third place in each ordered triple',
                scope='RETROSPECTIVE_REUSED_ARCHIVE_DEVELOPMENTAL')


@dataclass(frozen=True)
class RaceBatch:
    base: np.ndarray
    features: np.ndarray
    truth: np.ndarray
    rival: np.ndarray


def batch(rows):
    base, features, truth = zip(*rows, strict=True)
    log_base = np.stack(base)
    truth = np.asarray(truth, dtype=int)
    wrong = log_base.copy()
    wrong[np.arange(len(truth)), truth] = -np.inf
    return RaceBatch(log_base, np.asarray(features, dtype=np.float32), truth, wrong.argmax(axis=1))


def _scores(group, weights):
    return group.base + np.einsum('rcf,f->rc', group.features, weights)


def probabilities(group, weights):
    scores = _scores(group, weights)
    return np.exp(scores - logsumexp(scores, axis=1, keepdims=True))


def objective(groups, weights, penalty):
    value, gradient, count = .0, np.zeros(len(BASIS)), 0
    for group in groups:
        ix = np.arange(len(group.truth))
        scores = _scores(group, weights)
        normal = logsumexp(scores, axis=1)
        value += np.sum(normal - scores[ix, group.truth])
        residual = np.exp(scores - normal[:, None])
        residual[ix, group.truth] -= 1.
        if penalty:
            z = scores[ix, group.rival] - scores[ix, group.truth]
            value += penalty * np.logaddexp(0., z).sum()
            effect = penalty * expit(z)
            residual[ix, group.rival] += effect
            residual[ix, group.truth] -= effect
        gradient += np.einsum('rc,rcf->f', residual, group.features)
        count += len(ix)
    return float(value / count + .5 * RIDGE * np.dot(weights, weights)), gradient / count + RIDGE * weights


def exactas(trifectas, starters):
    return trifectas.reshape(-1, starters * (starters - 1), starters - 2).sum(axis=-1)


def _race(row, truth, model):
    cars = sorted(r['car'] for r in row['riders'])
    log_tickets = {tuple(t['cars']): t['probability'] for t in model.distribution(row)['trifectas']}
    triples = list(permutations(cars, 3))
    base = np.array([log_tickets[t] for t in triples])
    check(np.all(np.isfinite(base)) and np.all(base > 0) and abs(base.sum() - 1.) <= 1e-10, 'FROZEN_SUPPORT')
    indices = [model.feature_names.index(name) for name in ('points_relative', 'line_role_attack', 'line_role_follow')]
    card = {r['car']: row['features'][i, indices] for i, r in enumerate(row['riders'])}
    values = np.stack([card[car] for car in cars])
    values[:, 0] = np.clip(values[:, 0] / 10., -3., 3.)
    position = {car: i for i, car in enumerate(cars)}
    a, b, c = np.array([[position[car] for car in ticket] for ticket in triples]).T
    groups = row['line_groups'] if row['lines_known'] else []
    membership = {car: i for i, group in enumerate(groups) for car in group}
    line = np.array([membership.get(car, -1) for car in cars])

    def same(x, y):
        return (line[x] != -1) & (line[x] == line[y])

    features = np.column_stack((values[a, 0], values[b, 0], values[c, 0], values[a, 1],
                                values[b, 2], same(a, b), same(a, c), same(b, c))).astype(np.float32)
    return np.log(base), features, triples.index(truth)


def _period(records, phase, model, venues, at):
    for day, rows, earlier in week_groups(records, *PERIODS[phase]):
        eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
        groups = defaultdict(list)
        if eligible:
            kept, truths = zip(*eligible)
            builder = FeatureBuilder()
            for _, history in earlier:
                builder.update_day(history)
            for row, truth in zip(_features(kept, builder, model, venues, at), truths, strict=True):
                groups[len(row['riders'])].append(_race(row, truth, model))
        yield day.isoformat(), len(rows), len(rows) - len(eligible), groups


def _score(group, starters, weights):
    tri = probabilities(group, weights)
    ex = exactas(tri, starters)
    i = np.arange(len(group.truth))
    ex_winner = group.truth // (starters - 2)
    p, q = tri[i, group.truth], ex[i, ex_winner]
    values = (tri.argmax(axis=1) == group.truth, ex.argmax(axis=1) == ex_winner,
              -np.log(p), -np.log(q), 1. - 2. * p + np.sum(tri * tri, axis=1),
              1. - 2. * q + np.sum(ex * ex, axis=1))
    return dict(n=len(i), **{name: float(v.sum()) for name, v in zip(METRICS, values, strict=True)})


def _aggregate(parts):
    return {key: sum(row[key] for row in parts) for key in ('n', *METRICS)}


def _assessment(records, phase, model, venues, at, parameters):
    days, cards, held = {}, 0, 0
    for day, registered, excluded, groups in _period(records, phase, model, venues, at):
        cards += registered
        held += excluded
        caches = {size: batch(rows) for size, rows in groups.items()}
        if caches:
            days[day] = {name: _aggregate([_score(group, size, weights) for size, group in caches.items()])
                         for name, weights in parameters.items()}
    metrics = {}
    for name in parameters:
        totals = _aggregate([day[name] for day in days.values()])
        check(totals['n'] == cards - held and totals['n'] > 0, 'COMMON_SCORING_DENOMINATOR')
        metrics[name] = dict(n=totals['n'], tri1=int(totals['tri1']), ex1=int(totals['ex1']),
            tri1_rate=totals['tri1'] / totals['n'], ex1_rate=totals['ex1'] / totals['n'],
            **{k: totals[k] / totals['n'] for k in PROPER_METRICS})
    return dict(cards=cards, excluded_without_unique_top3=held, days=len(days), metrics=metrics), days


def select(metrics):
    frozen = metrics['frozen']
    eligible = [name for name, row in metrics.items() if all(
        row[key] <= frozen[key] + 1e-12 for key in PROPER_METRICS)]
    return min(eligible, key=lambda name: (-metrics[name]['tri1'], -metrics[name]['ex1'],
               *(metrics[name][key] for key in PROPER_METRICS), name != 'frozen', name))


def run(paths, private):
    start = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    contract = specification()
    registration = dict(contract=contract, contract_sha256=digest(contract),
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        study_source_sha256=digest_file(Path(__file__)), registered_at=at)
    write_private_json(private / 'contract.json', registration)
    records, audit = load_archives(paths)
    check({path.name for path in paths} == PINNED_SOURCE_SHA256.keys() and
          audit['dataset_sha256'] == OLD_DATASET, 'PINNED_ARCHIVE_MISMATCH')
    model, venues = load_frozen(ROOT.parents[1])
    check(model is not None, 'FROZEN_MODEL_UNAVAILABLE')
    print('PINNED_INPUTS_VERIFIED', flush=True)
    groups, training_cards, training_excluded = defaultdict(list), 0, 0
    for _, registered, excluded, races in _period(records, 'fit', model, venues, at):
        training_cards += registered
        training_excluded += excluded
        for size, rows in races.items():
            groups[size].extend(rows)
    batches = [batch(rows) for rows in groups.values()]
    usable = sum(len(b.truth) for b in batches)
    check(usable == training_cards - training_excluded and usable > 0, 'FIT_COMMON_DENOMINATOR')
    del groups
    print('FIT_FEATURES_READY', usable, flush=True)
    weights, fits = dict(frozen=np.zeros(len(BASIS))), {}
    for name, penalty in OBJECTIVES.items():
        fitted = minimize(lambda w: objective(batches, w, penalty), weights['frozen'], jac=True,
                          method='L-BFGS-B', options={'maxiter': ITERATIONS, 'gtol': 1e-6})
        weights[name] = fitted.x
        fits[name] = dict(converged=bool(fitted.success), iterations=int(fitted.nit), final_objective=float(fitted.fun),
            parameter_sha256=digest(fitted.x.tolist()), stop_code=int(fitted.status))
        check(fitted.success and np.all(np.isfinite(fitted.x)), 'OPTIMIZATION_NOT_CONVERGED')
        print('FIXED_OBJECTIVE_FIT', name, fitted.nit, flush=True)
    del batches
    june, _ = _assessment(records, 'june', model, venues, at, weights)
    selection = select(june['metrics'])
    frozen_selection = dict(june_selection=selection, parameter_hashes={key: f['parameter_sha256']
        for key, f in fits.items()}, frozen_at=datetime.now(timezone.utc).isoformat())
    write_private_json(private / 'june-selection.json', frozen_selection)
    print('JUNE_SELECTION_FROZEN', selection, flush=True)
    july, days = _assessment(records, 'july', model, venues, at, weights)
    check(all(row['n'] == EXPECTED_JULY for row in july['metrics'].values()), 'JULY_COMMON_DENOMINATOR')
    july['paired_day_bootstrap_deltas'] = {f'{left}_minus_{right}': paired_difference(days, left, right, metrics=METRICS)
        for left, right in (('nll', 'frozen'), ('nll_rank', 'frozen'), ('nll_rank', 'nll'))}
    return dict(registration, schema='DT_R1_RANKING_OBJECTIVE_STUDY_V1',
        archive=dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET),
        frozen=dict(model_sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA, geometry_sha256=GEOMETRY,
                    fit_period_overlaps_training_and_june=True, calibration_and_selection_overlap_july=True),
        training=dict(cards=training_cards, excluded_without_unique_top3=training_excluded, scored=usable, objectives=fits),
        june=dict(june, selection=frozen_selection), july=july, production_promoted=False,
        elapsed_seconds=round(time.monotonic() - start, 3), stop_reason='FIXED_DEVELOPMENT_COMPARISON_COMPLETED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private', type=Path)
    parser.add_argument('archives', type=Path, nargs=2)
    args = parser.parse_args()
    private = args.private.resolve()
    check(private.is_dir() and not any(private.iterdir()) and not private.stat().st_mode & 0o077 and
          not any((path / '.git').exists() for path in (private, *private.parents)), 'PRIVATE_WORKSPACE_REQUIRED')
    os.umask(0o077)

    def timeout(*_):
        raise TimeoutError('STUDY_TIME_BUDGET_EXHAUSTED')

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
