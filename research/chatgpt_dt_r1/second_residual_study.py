"""Evaluate one conditional second-place correction on the DT-R1 research archive."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from time import monotonic
from typing import NamedTuple

import numpy as np

from research.chatgpt_dt_r1 import boosted_first_study as base
from research.chatgpt_dt_r1.data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from research.chatgpt_dt_r1.features import retired_timing_feature
from research.chatgpt_dt_r1.frozen_followup import OLD_DATASET, ROOT, check
from research.chatgpt_dt_r1.historical_replay import digest_file
from research.chatgpt_dt_r1.history_mix_study import paired_difference
from research.chatgpt_dt_r1.model import PAIR_NAMES
from research.chatgpt_dt_r1.pipeline import write_private_json
from research.chatgpt_dt_r1.policy import digest
from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen


ARM = 'second_residual'


class SecondGroup(NamedTuple):
    first: int
    seconds: tuple[int, ...]
    offsets: np.ndarray
    features: np.ndarray


def _second_groups(frozen, row, keep, *, observed_first=None):
    cars, utilities, pairs = frozen._prepared(row)
    first, probabilities = frozen._choice(utilities, pairs, 0)
    if observed_first is not None:
        check(observed_first in cars, 'OBSERVED_FIRST_OUTSIDE_FROZEN_ROSTER')
    selected = row['features'][:, keep]
    groups = []
    for winner, probability in zip(first, probabilities, strict=True):
        if observed_first is not None and cars[winner] != observed_first:
            continue
        second, conditional = frozen._choice(utilities, pairs, 1 << winner)
        features = np.column_stack((selected[second], pairs[second, winner, :],
                                    np.full(len(second), probability))).astype(np.float32)
        groups.append(SecondGroup(cars[winner], tuple(cars[i] for i in second), np.log(conditional), features))
    return groups


def _correct_joint(joint, groups, corrections):
    sizes = [len(group.seconds) for group in groups]
    check(corrections.shape == (sum(sizes),) and np.isfinite(corrections).all(), 'FINITE_SECOND_RESIDUAL')
    aligned = np.split(corrections, np.cumsum(sizes)[:-1])
    scales = {}
    for group, values in zip(groups, aligned, strict=True):
        old = np.exp(group.offsets)
        adjusted = base.softmax(group.offsets + values, 1.)
        scales.update({(group.first, car): ratio for car, ratio in zip(group.seconds, adjusted / old, strict=True)})
    # All third places under the same first/second pair receive the same scale.
    return {order: float(mass * scales[order[:2]]) for order, mass in joint.items()}


def _fit(records, frozen, venues, at, keep, names):
    import lightgbm
    from research.chatgpt_dt_r1.winner_residual_study import ROUNDS, TREE, _frames, _group_objective

    features, offsets, sizes, labels = [], [], [], []
    for _, rows, truths in _frames(records, 'fit', frozen, venues, at):
        for row, truth in zip(rows, truths, strict=True):
            group, = _second_groups(frozen, row, keep, observed_first=truth[0])
            target = np.zeros(len(group.seconds), dtype=np.float32)
            target[group.seconds.index(truth[1])] = 1.
            features.append(group.features)
            offsets.append(group.offsets)
            sizes.append(len(target))
            labels.append(target)
    check(len(sizes) == 6857, 'FIT_COMMON_DENOMINATOR')
    offsets, labels = np.concatenate(offsets), np.concatenate(labels)
    starts = np.r_[0, np.cumsum(sizes)[:-1]]
    check(np.all(np.add.reduceat(labels, starts) == 1.) and
          np.allclose(np.add.reduceat(np.exp(offsets), starts), 1.), 'RACE_SECOND_BINDING')

    def objective(scores, dataset):
        return _group_objective(scores, dataset.get_label(), offsets, starts, sizes)

    train = lightgbm.Dataset(np.concatenate(features), label=labels, feature_name=names)
    fitted = lightgbm.train(dict(TREE, objective=objective), train, num_boost_round=ROUNDS)
    check(fitted.current_iteration() == ROUNDS, 'FIXED_TREE_BUDGET')
    return fitted, len(sizes), len(labels)


def _evaluate(records, period, frozen, venues, at, booster, keep):
    from research.chatgpt_dt_r1.winner_residual_study import TREE, _frames

    days = {}
    for day, rows, truths in _frames(records, period, frozen, venues, at):
        groups = [_second_groups(frozen, row, keep) for row in rows]
        sizes = [sum(len(group.seconds) for group in race) for race in groups]
        scores = booster.predict(np.concatenate([group.features for race in groups for group in race]),
                                 raw_score=True, num_threads=TREE['num_threads'])
        check(scores.shape == (sum(sizes),) and np.isfinite(scores).all(), 'FINITE_SECOND_BATCH')
        aligned = np.split(scores, np.cumsum(sizes)[:-1])
        counts = {arm: Counter(n=len(rows)) for arm in ('frozen', ARM)}
        for row, truth, race, correction in zip(rows, truths, groups, aligned, strict=True):
            joint = base._joint(frozen, row)
            for arm, law in (('frozen', joint), (ARM, _correct_joint(joint, race, correction))):
                counts[arm].update(dict(zip(base.METRICS, base._score(law, truth), strict=True)))
        days[day] = counts
    totals = {arm: sum((row[arm] for row in days.values()), Counter()) for arm in ('frozen', ARM)}
    expected = 2244 if period == 'june' else base.EXPECTED_JULY
    check(all(t['n'] == expected for t in totals.values()), 'HELD_PERIOD_COMMON_DENOMINATOR')
    report = {arm: dict(n=expected, hits={key: int(counts[key]) for key in base.HITS},
        proper={key: float(counts[key] / expected) for key in base.PROPER}) for arm, counts in totals.items()}
    return report, paired_difference(days, ARM, 'frozen', metrics=base.METRICS)


def run(paths, private):
    import lightgbm
    from research.chatgpt_dt_r1.winner_residual_study import PERIODS, ROUNDS, TREE

    started = monotonic()
    at = datetime.now(timezone.utc).isoformat()
    spec = dict(periods=PERIODS, history_days=7, rounds=ROUNDS, lightgbm_version=base.LGB_VERSION,
        tree={**TREE, 'objective': 'grouped second log loss with frozen conditional logit offset and diagonal Hessian'},
        correction_strength=1., candidate_budget=1, fixed_factors=['first', 'third_given_first_and_second'],
        second_features=['443 non-retired rider features', *PAIR_NAMES, 'frozen_first_probability'],
        official_registration_authentication=False, pre_cutoff_time_verified=False, august_onward_used=False,
        june_gate='more trifecta one-point hits, no fewer exacta one-point hits, no proper-score degradation',
        july_scope='fixed developmental comparison with no fitting or tuning',
        july_continuation_gate='more trifecta one-point hits and no fewer exacta one-point hits')
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
    names.extend(f'selected_first_pair_{name}' for name in PAIR_NAMES)
    names.append('frozen_first_probability')
    check(len(keep) == 443 and len(set(names)) == len(names) == 450, 'SECOND_FEATURE_CONTRACT')
    fitted, races, second_rows = _fit(records, frozen, venues, at, keep, names)
    weights = fitted.model_to_string()
    weights_sha = digest(weights)
    write_private_json(private / 'candidate.private.json', dict(weights=weights, sha256=weights_sha))
    print('FIXED_SECOND_RESIDUAL_TRAINED', races, second_rows, flush=True)
    june, june_delta = _evaluate(records, 'june', frozen, venues, at, fitted, keep)
    june_pass = (june_delta['tri1']['delta'] > 0 and june_delta['ex1']['delta'] >= 0 and
                 all(june_delta[key]['delta'] <= 0 for key in base.PROPER))
    write_private_json(private / 'june-selection.json', dict(weights_sha256=weights_sha, june_gate_passed=june_pass,
                                                            evaluated_at=datetime.now(timezone.utc).isoformat()))
    july, july_delta = _evaluate(records, 'july', frozen, venues, at, fitted, keep)
    check(july['frozen']['hits']['tri1'] == 252 and july['frozen']['hits']['ex1'] == 522, 'FROZEN_BASELINE_REPLAY')
    july_pass = july_delta['tri1']['delta'] > 0 and july_delta['ex1']['delta'] >= 0
    used = {name: int(count) for name, count in zip(names, fitted.feature_importance(), strict=True) if count}
    return dict(schema='DT_R1_SECOND_RESIDUAL_STUDY_V1', specification=spec, specification_sha256=digest(spec),
        scope='RETROSPECTIVE_DEVELOPMENTAL', code_sha256=code_sha, base_commit=revision, started_at=at,
        archive=dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET),
        model_sha256=MODEL_SHA, model_file_sha256=MODEL_FILE_SHA, learned_weights_sha256=weights_sha,
        feature_candidates=len(names), split_features=used, training=dict(races=races, second_rows=second_rows),
        june_gate_passed=june_pass, july_continuation_gate_passed=july_pass,
        selected_for_independent_validation=june_pass and july_pass,
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
