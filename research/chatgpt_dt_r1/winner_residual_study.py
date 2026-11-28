"""Test a single grouped winner-logit correction to the frozen DT-R1 joint law."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from time import monotonic

import lightgbm
import numpy as np

from research.chatgpt_dt_r1 import boosted_first_study as base
from research.chatgpt_dt_r1.data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from research.chatgpt_dt_r1.features import retired_timing_feature
from research.chatgpt_dt_r1.frozen_followup import FeatureBuilder, OLD_DATASET, ROOT, check
from research.chatgpt_dt_r1.historical_replay import digest_file
from research.chatgpt_dt_r1.history_mix_study import paired_difference
from research.chatgpt_dt_r1.pipeline import _result_key, write_private_json
from research.chatgpt_dt_r1.policy import digest
from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen


PERIODS = dict(fit=('2026-03-01', '2026-05-31'), june=base.SPLITS['june'], july=base.SPLITS['july'])
ROUNDS = 40
TREE = dict(base.TREE, learning_rate=.04, max_depth=3, num_leaves=7, min_data_in_leaf=200, lambda_l2=12.)


def specification():
    return dict(periods=PERIODS, history_days=7, rounds=ROUNDS, lightgbm_version=base.LGB_VERSION,
        tree={**TREE, 'objective': 'grouped winner log loss with frozen logit offset and diagonal Hessian'},
        correction_strength=1., support='identical frozen joint and fixed second and third conditionals',
        june_gate='more trifecta one-point hits, no fewer exacta one-point hits, no proper-score degradation',
        july_scope='fixed developmental comparison; no fitting or selection', candidate_budget=1)


def _frames(records, period, frozen, venues, at):
    for day, rows, earlier in base.week_groups(records, *PERIODS[period]):
        eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
        if not eligible:
            continue
        kept, truths = zip(*eligible, strict=True)
        builder = FeatureBuilder()
        for _, prior in earlier:
            builder.update_day(prior)
        yield day.isoformat(), base._features(kept, builder, frozen, venues, at), truths


def _offset(frozen, row):
    cars, utilities, pairs = frozen._prepared(row)
    positions, probabilities = frozen._choice(utilities, pairs, 0)
    check(positions == list(range(len(cars))) and np.all(probabilities > 0), 'FROZEN_WINNER_SUPPORT')
    return cars, np.log(probabilities)


def _group_objective(scores, labels, offsets, start, sizes):
    logits = scores + offsets
    maximum = np.repeat(np.maximum.reduceat(logits, start), sizes)
    weights = np.exp(logits - maximum)
    probabilities = weights / np.repeat(np.add.reduceat(weights, start), sizes)
    return probabilities - labels, np.maximum(probabilities * (1. - probabilities), 1e-6)


def _fit(records, frozen, venues, at, keep, names):
    features, offsets, sizes, labels = [], [], [], []
    for _, rows, truths in _frames(records, 'fit', frozen, venues, at):
        for row, truth in zip(rows, truths, strict=True):
            cars, offset = _offset(frozen, row)
            target = np.zeros(len(cars), dtype=np.float32)
            target[cars.index(truth[0])] = 1.
            features.append(row['features'][:, keep].astype(np.float32))
            sizes.append(len(cars))
            offsets.append(offset)
            labels.append(target)
    check(len(sizes) == 6857, 'FIT_COMMON_DENOMINATOR')
    offsets, labels = np.concatenate(offsets), np.concatenate(labels)
    starts = np.r_[0, np.cumsum(sizes)[:-1]]
    check(labels.sum() == len(sizes) and np.allclose(np.add.reduceat(np.exp(offsets), starts), 1.),
          'RACE_WINNER_BINDING')

    def objective(scores, dataset):
        return _group_objective(scores, dataset.get_label(), offsets, starts, sizes)

    train = lightgbm.Dataset(np.concatenate(features), label=labels, feature_name=names)
    fitted = lightgbm.train(dict(TREE, objective=objective), train, num_boost_round=ROUNDS)
    check(fitted.current_iteration() == ROUNDS, 'FIXED_TREE_BUDGET')
    return fitted, len(sizes), len(labels)


def _evaluate(records, period, frozen, venues, at, booster, keep):
    days = {}
    for day, rows, truths in _frames(records, period, frozen, venues, at):
        sizes = [len(row['riders']) for row in rows]
        tree = booster.predict(np.concatenate([row['features'][:, keep] for row in rows]), raw_score=True,
                               num_threads=TREE['num_threads'])
        check(len(tree) == sum(sizes) and np.isfinite(tree).all(), 'FINITE_WINNER_RESIDUAL')
        aligned = np.split(tree, np.cumsum(sizes)[:-1])
        counts = {arm: Counter(n=len(rows)) for arm in ('frozen', 'winner_residual')}
        for row, truth, correction in zip(rows, truths, aligned, strict=True):
            joint = base._joint(frozen, row)
            cars, offset = _offset(frozen, row)
            actual = base.marginal(joint, count=1)
            check(np.allclose(np.exp(offset), [actual[(car,)] for car in cars], atol=1e-12, rtol=0.),
                  'FROZEN_JOINT_FIRST_MARGINAL')
            adjusted_first = dict(zip(cars, base.softmax(offset + correction, 1.), strict=True))
            for arm, law in (('frozen', joint), ('winner_residual', base.reweight_joint(joint, adjusted_first))):
                counts[arm].update(dict(zip(base.METRICS, base._score(law, truth), strict=True)))
        days[day] = counts
    totals = {arm: sum((row[arm] for row in days.values()), Counter()) for arm in ('frozen', 'winner_residual')}
    expected = 2244 if period == 'june' else base.EXPECTED_JULY
    check(all(t['n'] == expected for t in totals.values()), 'HELD_PERIOD_COMMON_DENOMINATOR')
    report = {arm: dict(n=expected, hits={key: int(t[key]) for key in base.HITS},
        proper={key: float(t[key] / expected) for key in base.PROPER}) for arm, t in totals.items()}
    return report, paired_difference(days, 'winner_residual', 'frozen', metrics=base.METRICS)


def run(paths, private):
    started = monotonic()
    at = datetime.now(timezone.utc).isoformat()
    spec = specification()
    code_sha = digest_file(Path(__file__))
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    write_private_json(private / 'contract.json', dict(spec=spec, spec_sha256=digest(spec), code_sha256=code_sha,
                                                       base_commit=revision, started_at=at))
    check(lightgbm.__version__ == base.LGB_VERSION, 'LIGHTGBM_VERSION_PIN')
    records, audit = load_archives(paths)
    check({path.name for path in paths} == PINNED_SOURCE_SHA256.keys() and
          audit['dataset_sha256'] == OLD_DATASET, 'PINNED_ARCHIVE_MISMATCH')
    frozen, venues = load_frozen(ROOT.parents[1])
    check(frozen is not None, 'FROZEN_MODEL_UNAVAILABLE')
    keep = [index for index, name in enumerate(frozen.feature_names) if not retired_timing_feature(name)]
    names = [frozen.feature_names[index] for index in keep]
    fitted, races, riders = _fit(records, frozen, venues, at, keep, names)
    weights = fitted.model_to_string()
    weights_sha = digest(weights)
    write_private_json(private / 'candidate.private.json', dict(weights=weights, sha256=weights_sha))
    print('FIXED_RESIDUAL_TRAINED', races, riders, flush=True)
    june, june_delta = _evaluate(records, 'june', frozen, venues, at, fitted, keep)
    passing = (june_delta['tri1']['delta'] > 0 and june_delta['ex1']['delta'] >= 0 and
               all(june_delta[key]['delta'] <= 0 for key in base.PROPER))
    write_private_json(private / 'june-selection.json', dict(weights_sha256=weights_sha, selected=passing,
                                                            selected_at=datetime.now(timezone.utc).isoformat()))
    july, july_delta = _evaluate(records, 'july', frozen, venues, at, fitted, keep)
    check(july['frozen']['hits']['tri1'] == 252 and july['frozen']['hits']['ex1'] == 522, 'FROZEN_BASELINE_REPLAY')
    used = {name: int(count) for name, count in zip(names, fitted.feature_importance(), strict=True) if count}
    return dict(schema='DT_R1_WINNER_RESIDUAL_STUDY_V1', specification=spec, specification_sha256=digest(spec),
        scope='RETROSPECTIVE_DEVELOPMENTAL', code_sha256=code_sha, base_commit=revision, started_at=at,
        archive=dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET),
        model_sha256=MODEL_SHA, model_file_sha256=MODEL_FILE_SHA,
        learned_weights_sha256=weights_sha, feature_candidates=len(names), split_features=used,
        training=dict(races=races, rider_rows=riders), selected_for_independent_validation=passing,
        june=dict(metrics=june, differences=june_delta), july=dict(metrics=july, differences=july_delta),
        elapsed_seconds=round(monotonic() - started, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private', type=Path)
    parser.add_argument('archives', type=Path, nargs=2)
    args = parser.parse_args()
    output = args.private.resolve()
    check(output.is_dir() and not any(output.iterdir()) and not output.stat().st_mode & 0o077 and
          not any((path / '.git').exists() for path in (output, *output.parents)), 'PRIVATE_WORKSPACE_REQUIRED')
    write_private_json(output / 'aggregate.json', run(args.archives, output))


if __name__ == '__main__':
    main()
