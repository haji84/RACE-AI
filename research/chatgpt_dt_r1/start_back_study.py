"""One retrospective DT-R1 candidate for the partial S-to-B transition."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import fsum, log
import os
from pathlib import Path
import time
import unicodedata

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from .back_phase_study import SOURCE, back_label, fit_leader, leader_prob, prepare
from .data import IDENTITY_STATUS, PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import OLD_DATASET, OLD_N, check
from .historical_replay import digest_file
from .history_mix_study import BOOTSTRAP_N, BOOTSTRAP_SEED, paired_difference
from .pipeline import write_private_json
from .policy import digest


TRAIN_START, EVAL_START, EVAL_END = '2026-01-01', '2026-07-01', '2026-07-31'
RIDGE = .01
METRICS = ('top1', 'log_loss')
_SWAP_S_AND_B = str.maketrans('SB', 'BS')


def _start_label_row(row):
    # Adapt the label slot consumed by the existing categorical learner only.
    # Its numeric feature matrix was already built with the real prior marks.
    def adapted(result):
        mark = result.get('sb_mark')
        if isinstance(mark, str):
            mark = unicodedata.normalize('NFKC', mark).upper().translate(_SWAP_S_AND_B)
        return dict(result, sb_mark=mark)

    return dict(row, result_rows=[adapted(result) for result in row['result_rows']])


def paired_marks(row):
    back, reason = back_label(row)
    if back is None:
        return None, reason
    start, reason = back_label(_start_label_row(row))
    if start is None:
        return None, {'NO_EXPLICIT_B': 'NO_EXPLICIT_S', 'AMBIGUOUS_B': 'AMBIGUOUS_S'}.get(reason, reason)
    return (start, back), 'UNIQUE_S_AND_B'


def line_relations(row):
    """Relation matrix indexed by hypothetical S candidate and B candidate."""
    cars = [rider['car'] for rider in row['riders']]
    self_relation = np.eye(len(cars))
    same_line = np.zeros_like(self_relation)
    groups = row.get('line_groups', ())
    if row.get('lines_known') is True and row.get('lines_applicable') is True:
        check(all(groups) and sorted(car for group in groups for car in group) == sorted(cars), 'S_B_LINE_ROSTER')
        position = {car: number for number, group in enumerate(groups) for car in group}
        same_line = np.array([[s != b and position[s] == position[b] for b in cars] for s in cars], dtype=float)
    return np.stack((self_relation, same_line), axis=-1)


def marginal_back(start, direct, relations, weights):
    """Forecast B by integrating every S candidate with its predicted probability."""
    if not np.any(weights):
        return direct.copy()
    conditional_logits = np.log(direct)[None, :] + relations @ weights
    conditional = np.exp(conditional_logits - logsumexp(conditional_logits, axis=1, keepdims=True))
    return start @ conditional


def _vector(model, row):
    law = leader_prob(model, row)
    return np.array([law[rider['car']] for rider in row['riders']])


def _fit_transition(training, direct):
    log_prior = np.full((len(training), 9), -np.inf)
    relations = np.zeros((len(training), 9, 2))
    labels = np.empty(len(training), dtype=int)
    for i, (row, (s, b)) in enumerate(training):
        cars = [rider['car'] for rider in row['riders']]
        size = len(cars)
        log_prior[i, :size] = np.log(_vector(direct, row))
        relations[i, :size, :] = line_relations(row)[cars.index(s)]
        labels[i] = cars.index(b)
    indices = np.arange(len(labels))

    def objective(weights):
        logits = log_prior + relations @ weights
        normal = logsumexp(logits, axis=1)
        residual = np.exp(logits - normal[:, None])
        residual[indices, labels] -= 1
        loss = np.mean(normal - logits[indices, labels]) + RIDGE * (weights @ weights) / 2
        gradient = np.mean(np.sum(residual[:, :, None] * relations, axis=1), axis=0) + RIDGE * weights
        return float(loss), gradient

    fitted = minimize(objective, np.zeros(2), method='L-BFGS-B', jac=True,
                      options={'maxiter': 160, 'ftol': 1e-9, 'gtol': 1e-5})
    check(np.isfinite(fitted.x).all() and np.isfinite(fitted.fun), 'S_B_CONDITIONAL_FIT_FAILED')
    return fitted.x, bool(fitted.success)


def _phase_cohort(rows):
    eligible, counts = [], Counter()
    for row in rows:
        pair, reason = paired_marks(row)
        if row.get('feature_status') != 'READY':
            reason = 'FEATURES_UNAVAILABLE'
        elif pair is not None:
            eligible.append((row, pair))
        counts[reason] += 1
    return eligible, dict(counts)


def _note_metrics(cars, p, actual):
    check(np.isfinite(p).all() and np.all(p > 0) and abs(float(p.sum()) - 1.) < 1e-10,
          'S_B_PROBABILITY_INVALID')
    chosen = max(range(len(cars)), key=lambda i: (p[i], -cars[i]))
    return int(cars[chosen] == actual), -log(float(p[cars.index(actual)]))


def _evaluate(evaluation, start_model, direct, weights):
    days = defaultdict(lambda: defaultdict(list))
    for row, (observed_s, observed_b) in evaluation:
        cars = [rider['car'] for rider in row['riders']]
        start, baseline = _vector(start_model, row), _vector(direct, row)
        transition = marginal_back(start, baseline, line_relations(row), weights)
        day = days[row['day']]
        day['start'].append(_note_metrics(cars, start, observed_s))
        day['direct_back'].append(_note_metrics(cars, baseline, observed_b))
        day['transition_back'].append(_note_metrics(cars, transition, observed_b))
    check(bool(days), 'S_B_EVALUATION_EMPTY')
    names = ('start', 'direct_back', 'transition_back')
    paired = {stamp: {name: dict(n=len(daily[name]), top1=sum(r[0] for r in daily[name]),
        log_loss=fsum(r[1] for r in daily[name])) for name in names} for stamp, daily in days.items()}
    metrics = {}
    n = len(evaluation)
    for name in names:
        hits = sum(block[name]['top1'] for block in paired.values())
        metrics[name] = dict(n=n, top1_hits=hits, top1_rate=hits / n,
            log_loss=fsum(block[name]['log_loss'] for block in paired.values()) / n)
    return len(days), metrics, paired_difference(paired, 'transition_back', 'direct_back', metrics=METRICS)


def specification():
    return dict(schema='DT_R1_ARCHIVED_S_TO_B_CONTRACT_V1', source_definition=SOURCE,
        start_definition='attach behind pacer immediately after start',
        back_definition='lead at final back-stretch marker, half lap remains',
        adjacent_phase_order_measured=False, physical_state_measured=False,
        training_days=[TRAIN_START, '2026-06-30'], development_days=[EVAL_START, EVAL_END],
        cutoff_clocks_authenticated=False, identity_scope=IDENTITY_STATUS,
        strict_prior_jst_days_for_features=True, older_archived_days_warm_history_only=True,
        same_pair_labeled_cohort=True, feature_builder='back_phase_study.prepare',
        direct_model='back_phase_study.fit_leader', start_model='same categorical fit with distinct S labels',
        conditional_terms=['same_rider', 'other_rider_on_same_known_line'], ridge=RIDGE,
        prediction_uses_actual_s_or_b=False, temperature_selection=False,
        bootstrap=dict(unit='paired JST day', samples=BOOTSTRAP_N, seed=BOOTSTRAP_SEED),
        independent_validation=False, production_promoted=False)


def run(paths, private):
    since = time.monotonic()
    contract = specification()
    pin = dict(contract=contract, contract_sha256=digest(contract),
        source=dict(commit=SOURCE_COMMIT, dataset_sha256=OLD_DATASET, files=PINNED_SOURCE_SHA256),
        study_sha256=digest_file(Path(__file__)),
        feature_and_leader_code_sha256=digest_file(Path(__file__).with_name('back_phase_study.py')),
        started_at=datetime.now(timezone.utc).isoformat())
    write_private_json(private / 'contract.json', pin)
    print('CONTRACT_SAVED', pin['contract_sha256'], flush=True)
    check(len(paths) == 2 and {path.name for path in paths} == PINNED_SOURCE_SHA256.keys(), 'ARCHIVE_PAIR')
    data, audit = load_archives(paths)
    check(len(data) == OLD_N and audit['dataset_sha256'] == OLD_DATASET, 'ARCHIVE_DATASET_PIN')
    rows = prepare([row for row in data if row['day'] <= EVAL_END])
    training, train_counts = _phase_cohort(row for row in rows if TRAIN_START <= row['day'] < EVAL_START)
    check(len(training) >= 30, 'S_B_PAIRED_TRAINING_REQUIRED')
    train_rows = [row for row, _ in training]
    print('PAIRED_TRAINING', len(training), flush=True)
    direct = fit_leader(train_rows, EVAL_START, ridge=RIDGE)
    start_model = fit_leader([_start_label_row(row) for row in train_rows], EVAL_START, ridge=RIDGE)
    transition, converged = _fit_transition(training, direct)
    model_pins = dict(start_sha256=digest(start_model), direct_back_sha256=digest(direct),
        transition_sha256=digest(dict(weights=transition.tolist(), start_sha256=digest(start_model),
                                      direct_back_sha256=digest(direct), contract_sha256=pin['contract_sha256'])))
    write_private_json(private / 'model-pins.json', dict(**model_pins, contract_sha256=pin['contract_sha256']))
    print('WEIGHTS_FROZEN', model_pins['transition_sha256'], flush=True)

    evaluation, july_counts = _phase_cohort(row for row in rows if EVAL_START <= row['day'] <= EVAL_END)
    days, metrics, paired = _evaluate(evaluation, start_model, direct, transition)
    report = dict(schema='DT_R1_ARCHIVED_S_TO_B_STUDY_V1', **pin, model_pins=model_pins,
        runtime_seconds=round(time.monotonic() - since, 3), production_promoted=False,
        feature_count=len(direct['feature_names']),
        optimizers_converged=dict(start=start_model['converged'], direct_back=direct['converged'],
                                  transition=converged),
        training=dict(cards=sum(train_counts.values()), common_labeled=len(training), counts=train_counts),
        july=dict(cards=sum(july_counts.values()), days=days, common_labeled=len(evaluation),
                  counts=july_counts, metrics=metrics, transition_minus_direct_back=paired))
    write_private_json(private / 'aggregate.json', report)
    print('AGGREGATE_SAVED', report['runtime_seconds'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private', type=Path)
    parser.add_argument('archives', type=Path, nargs=2)
    opts = parser.parse_args()
    os.umask(0o077)
    private = opts.private.resolve()
    check(private.is_dir() and not any(private.iterdir()) and not private.stat().st_mode & 0o077
          and not any((parent / '.git').exists() for parent in (private, *private.parents)), 'PRIVATE_RUNNER_PATH')
    run(opts.archives, private)


if __name__ == '__main__':
    main()
