"""One developmental nonlinear DT-R1 winner-stage trial on the pinned archive.

Fit a pointwise winner classifier on Oct 2025 through May 2026, with exactly
seven earlier JST days of DT-R1 facts. Pick June temperature by winner log
loss, equivalently joint 3T log loss up to a fixed conditional loss. Freeze
before July. The winner stage changes only the first marginal of the frozen
DT-R1 joint 3T forecast, using the identical seven-day feature row. Compare
the resulting joint and exact 2T marginal against frozen cold/seven in July.
July overlaps the original engine's tuning. Prior August onward evaluation
is never used. Archived availability and official identities are unverified.
"""
import argparse
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
import json
from math import fsum, isclose, isfinite, log
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import (GEOMETRY, OLD_DATASET, ROOT, FeatureBuilder, augment_abilities,
                              augment_agari, augment_features, blind_target, check)
from .historical_replay import digest_file
from .pipeline import _result_key, write_private_json
from .policy import digest


SPLITS = {'train': ('2025-10-01', '2026-05-31'), 'june': ('2026-06-01', '2026-06-30'),
          'july': ('2026-07-01', '2026-07-31')}
EXPECTED_JULY = 2393
TEMPERATURES = (.60, .80, 1., 1.25, 1.50, 2.)
ROUNDS = 60
SEED = 462
LGB_VERSION = '4.6.0'
TREE = dict(objective='binary', learning_rate=.06, num_leaves=15, max_depth=4, min_data_in_leaf=150,
            lambda_l2=1., deterministic=True, force_col_wise=True, seed=SEED, num_threads=2, verbosity=-1)
HITS = ('tri1', 'ex1', 'tri2', 'tri4', 'ex2')
PROPER = ('tri_log_loss', 'ex_log_loss', 'tri_brier', 'ex_brier')
METRICS = HITS + PROPER
BOOTSTRAPS = 2000


def contract():
    return dict(schema='DT_R1_BOOSTED_FIRST_CONTRACT_V1', splits=SPLITS, history_days=7,
        library='LightGBM', library_version=LGB_VERSION, tree=TREE, rounds=ROUNDS,
        temperature_grid=TEMPERATURES, temperature_objective='june_winner_log_loss_lower_temperature_tiebreak',
        probability_rule='race_softmax_first_times_frozen_seven_day_conditional',
        common_july_expected=EXPECTED_JULY, comparisons=['frozen_cold', 'frozen_seven'],
        bootstrap=dict(unit='paired_jst_day', seed=SEED, draws=BOOTSTRAPS),
        development_only=True, original_july_temperature_and_selection_overlap=True,
        official_registration_authentication=False, pre_cutoff_time_verified=False, august_onward_used=False)


def marginal(joint, *, count):
    terms = defaultdict(list)
    for order, probability in joint.items():
        terms[order[:count]].append(probability)
    return {prefix: fsum(values) for prefix, values in terms.items()}


def reweight_joint(base, first):
    old = {prefix[0]: p for prefix, p in marginal(base, count=1).items()}
    check(old and old.keys() == first.keys() and all(isfinite(p) and p >= 0 for p in base.values()) and
          all(p > 0 for p in old.values()) and isclose(fsum(old.values()), 1., rel_tol=0., abs_tol=1e-10)
          and all(isfinite(p) and p >= 0 for p in first.values()) and
          isclose(fsum(first.values()), 1., rel_tol=0., abs_tol=1e-10), 'JOINT_REWEIGHT_MASS_OR_SUPPORT')
    return {order: (probability / old[order[0]]) * first[order[0]] for order, probability in base.items()}


def softmax(scores, temperature):
    a = np.asarray(scores, dtype=np.float64)
    check(a.ndim == 1 and len(a) and np.isfinite(a).all() and isfinite(temperature) and temperature > 0.,
          'FINITE_RACE_WINNER_SCORES')
    scaled = np.exp((a - a.max()) / temperature)
    return scaled / scaled.sum()


def pick_temperature(rows):
    check(rows, 'JUNE_TEMPERATURE_ROWS_REQUIRED')
    losses = {temp: fsum(-log(max(softmax(scores, temp)[win], 1e-300))
                        for scores, win in rows) / len(rows) for temp in TEMPERATURES}
    return min(losses, key=lambda temp: (losses[temp], temp)), losses


def week_groups(records, start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    pending = deque()
    for stamp, group in groupby(records, key=lambda row: row['day']):
        day = date.fromisoformat(stamp)
        if day > last:
            break
        earliest = day - timedelta(days=7)
        while pending and pending[0][0] < earliest:
            pending.popleft()
        if day < first - timedelta(days=7):
            continue
        rows = list(group)
        if day >= first:
            yield day, rows, tuple(pending)
        pending.append((day, rows))


def validate_july(expected, actual):
    check(len(expected) == len(set(expected)) == len(actual) == len(set(actual)) == EXPECTED_JULY and
          set(expected) == set(actual), 'JULY_COMMON_2393_RACE_DENOMINATOR')


def _features(rows, builder, frozen, venues, at):
    blinded = [builder.transform(blind_target(row)) for row in rows]
    ctx = augment_features(blinded, venue_store=venues, as_of=at, allow_current_geometry_assumption=True)
    view = augment_abilities(augment_agari(ctx))
    for raw, row in zip(rows, view, strict=True):
        check(row['race_id'] == raw['race_id'] and row['input_sha256'] == raw['input_sha256'] and
              tuple(row['feature_names']) == frozen.feature_names and row['feature_status'] == 'READY',
              'FROZEN_COMMON_FEATURE_BINDING')
    return view


def _frames(records, phase, frozen, venues, at):
    for day, rows, earlier in week_groups(records, *SPLITS[phase]):
        eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
        if not eligible:
            continue
        kept, truths = zip(*eligible)
        seven = FeatureBuilder()
        for _, prior in earlier:
            seven.update_day(prior)
        recent = _features(kept, seven, frozen, venues, at)
        cold = _features(kept, FeatureBuilder(), frozen, venues, at) if phase == 'july' else ()
        yield day.isoformat(), recent, cold, truths


def _cars(row):
    return tuple(r['car'] for r in row['riders'])


def _fit(data, frozen, venues, at, lightgbm):
    count = sum(len(r['riders']) for r in data if SPLITS['train'][0] <= r['day'] <= SPLITS['train'][1]
                and _result_key(r) is not None)
    x = np.empty((count, len(frozen.feature_names)), dtype=np.float32)
    y = np.zeros(count, dtype=np.uint8)
    offset = races = 0
    for _, recent, _, truths in _frames(data, 'train', frozen, venues, at):
        for row, truth in zip(recent, truths, strict=True):
            end = offset + len(row['riders'])
            x[offset:end] = row['features']
            y[offset + _cars(row).index(truth[0])] = 1
            offset = end
            races += 1
    check(offset == count and races > 0 and np.count_nonzero(y) == races, 'TRAIN_WINNER_MATRIX')
    train = lightgbm.Dataset(x, label=y, feature_name=list(frozen.feature_names))
    return lightgbm.train(dict(TREE), train, num_boost_round=ROUNDS), races, count


def _raw_scores(booster, rows):
    scores = booster.predict(np.concatenate([row['features'] for row in rows]), raw_score=True, num_threads=2)
    counts = [len(r['riders']) for r in rows]
    check(len(scores) == sum(counts), 'RACE_SCORE_LENGTH')
    return np.split(scores, np.cumsum(counts)[:-1])


def _joint(frozen, row):
    return {tuple(t['cars']): t['probability'] for t in frozen.distribution(row)['trifectas']}


def _score(joint, truth):
    actual_two = truth[:2]
    exactas = marginal(joint, count=2)
    tri = sorted(joint, key=lambda t: (-joint[t], t))
    ex = sorted(exactas, key=lambda t: (-exactas[t], t))
    p, q = joint[truth], exactas[actual_two]
    return (int(tri[0] == truth), int(ex[0] == actual_two), int(truth in tri[:2]), int(truth in tri[:4]),
            int(actual_two in ex[:2]), -log(max(p, 1e-300)), -log(max(q, 1e-300)),
            1 - 2 * p + fsum(v * v for v in joint.values()), 1 - 2 * q + fsum(v * v for v in exactas.values()))


def _july(data, frozen, venues, at, booster, temperature, expected):
    blocks, admitted = {}, []
    for day, recent, cold, truths in _frames(data, 'july', frozen, venues, at):
        rows = {'candidate': [], 'frozen_cold': [], 'frozen_seven': []}
        for row, control, truth, raw in zip(recent, cold, truths, _raw_scores(booster, recent), strict=True):
            admitted.append(row['race_id'])
            base = _joint(frozen, row)
            first = dict(zip(_cars(row), softmax(raw, temperature), strict=True))
            rows['candidate'].append(_score(reweight_joint(base, first), truth))
            rows['frozen_seven'].append(_score(base, truth))
            rows['frozen_cold'].append(_score(_joint(frozen, control), truth))
        blocks[day] = {name: (len(truths), np.sum(values, axis=0)) for name, values in rows.items()}
    validate_july(expected, admitted)
    return blocks


def _report_july(blocks):
    ordered = [blocks[day] for day in sorted(blocks)]
    n = np.array([day['candidate'][0] for day in ordered])
    samples = np.random.default_rng(SEED).integers(0, len(n), (BOOTSTRAPS, len(n)))
    bootstrap_n = n[samples].sum(axis=1)
    values = {name: np.stack([row[name][1] for row in ordered]) for name in ordered[0]}
    totals = {name: arr.sum(axis=0).tolist() for name, arr in values.items()}
    report = {name: dict(hits={key: int(v) for key, v in zip(HITS, scores[:len(HITS)], strict=True)},
        proper={key: v / EXPECTED_JULY for key, v in zip(PROPER, scores[len(HITS):], strict=True)})
        for name, scores in totals.items()}
    comparisons = {}
    for control in ('frozen_cold', 'frozen_seven'):
        d = values['candidate'] - values[control]
        rates = d[samples].sum(axis=1) / bootstrap_n[:, None]
        point = d.sum(axis=0) / n.sum()
        ci = np.quantile(rates, [.025, .975], axis=0).T
        comparisons[control] = {key: dict(delta=float(p), ci95=interval.tolist())
                                for key, p, interval in zip(METRICS, point, ci, strict=True)}
    return dict(days=len(blocks), common_scorable=EXPECTED_JULY, metrics=report,
                candidate_difference=comparisons)


def run(paths, private):
    import lightgbm

    clock = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    check(lightgbm.__version__ == LGB_VERSION, 'LIGHTGBM_VERSION_PIN')
    spec = contract()
    spec_sha = digest(spec)
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    replay_sha = digest_file(Path(__file__))
    write_private_json(private / 'contract.json', dict(contract=spec, contract_sha256=spec_sha, started_at=clock,
                                                      code_base=code, source_sha256=replay_sha))
    frozen, venues = load_frozen(ROOT.parents[1])
    check({p.name for p in paths} == PINNED_SOURCE_SHA256.keys() and len(paths) == 2, 'ARCHIVE_PAIR')
    data, audit = load_archives(paths)
    check(audit['dataset_sha256'] == OLD_DATASET and len(data) == 30713, 'FROZEN_ARCHIVE_PIN')
    july = [r for r in data if SPLITS['july'][0] <= r['day'] <= SPLITS['july'][1]]
    expected = [r['race_id'] for r in july if _result_key(r) is not None]
    validate_july(expected, expected)
    candidate, races, riders = _fit(data, frozen, venues, clock, lightgbm)
    print('WINNER_STAGE_TRAINED', races, riders, flush=True)
    tune = []
    for _, recent, _, truths in _frames(data, 'june', frozen, venues, clock):
        for row, truth, scores in zip(recent, truths, _raw_scores(candidate, recent), strict=True):
            tune.append((scores, _cars(row).index(truth[0])))
    temperature, losses = pick_temperature(tune)
    weights = candidate.model_to_string()
    candidate_spec = dict(schema='DT_R1_BOOSTED_FIRST_CANDIDATE_V1', base_model_sha256=MODEL_SHA,
        contract_sha256=spec_sha, weights_sha256=digest(weights), temperature=temperature,
        train_races=races, train_riders=riders, tune_races=len(tune))
    candidate_sha = digest(candidate_spec)
    frozen_at = datetime.now(timezone.utc).isoformat()
    path = private / 'candidate.private.json'
    write_private_json(path, dict(candidate=candidate_spec, candidate_sha256=candidate_sha,
                                  frozen_at=frozen_at, weights=weights))
    restored = json.loads(path.read_text())
    check(digest(restored['weights']) == candidate_spec['weights_sha256'] and
          digest(restored['candidate']) == restored['candidate_sha256'] == candidate_sha, 'PRIVATE_CANDIDATE_PIN')
    booster = lightgbm.Booster(model_str=restored['weights'])
    print('CANDIDATE_FROZEN', candidate_sha, flush=True)
    eval_report = _report_july(_july(data, frozen, venues, clock, booster, temperature, expected))
    return dict(schema='DT_R1_BOOSTED_FIRST_STUDY_V1', code_base=code, source_sha256=replay_sha,
        started_at=clock, runtime_seconds=round(time.monotonic() - started, 3), contract=spec,
        contract_sha256=spec_sha, candidate=candidate_spec, candidate_sha256=candidate_sha, frozen_at=frozen_at,
        train=dict(races=races, riders=riders), june=dict(evaluable=len(tune), winner_log_loss=losses),
        july=dict(cards=len(july), excluded_without_unique_trifecta=len(july) - len(expected),
                  cohort_sha256=digest(sorted(expected)), **eval_report),
        frozen_model=dict(sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA, features=len(frozen.feature_names)),
        archive=dict(commit=SOURCE_COMMIT, dataset_sha256=OLD_DATASET, files=PINNED_SOURCE_SHA256,
                     current_geometry_assumption_sha256=GEOMETRY),
        independent_accuracy_claim=False, production_promoted=False)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('private', type=Path, help='An empty owner-only output directory outside Git.')
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
