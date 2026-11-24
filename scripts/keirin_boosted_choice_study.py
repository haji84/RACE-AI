"""Research-only residuals for the existing ordered keirin ranker."""

from hashlib import sha256

import numpy as np
from scipy.special import softmax

from scripts import keirin_line_event_study as saved
from scripts import keirin_line_history_study as lines
from scripts import keirin_ordered_ticket_study as ordered
from scripts import keirin_rider_profile_study as profiles
from scripts import keirin_small_ticket_study as tickets


BASE_FIELDS = tuple(dict.fromkeys(tickets.feature_names('prior_finishers', 0)
                                 + ('second_only_rate', 'third_only_rate',
                                    'second_only_known', 'third_only_known',
                                    'top2_rate', 'top3_rate', 'top2_known', 'top3_known')))
PROFILE_FIELDS = ('overall_win', 'overall_second', 'overall_third', 'recent_win_change',
                  'overall_speed', 'days_since_start', 'role_win', 'role_second',
                  'role_third', 'role_speed', 'track_top3', 'track_speed')
ARMS = {
    'saved': ((0, 0, 0), 0.),
    'first_two_24': ((24, 24, 0), 1.),
    'first_two_56': ((56, 56, 0), 1.),
    'third_56': ((0, 0, 56), 1.),
    'all_24': ((24, 24, 24), 1.),
    'all_56': ((56, 56, 56), 1.),
    'all_96': ((96, 96, 96), 1.),
    'all_96_half': ((96, 96, 96), .5),
}


def group_derivatives(scores, labels, sizes):
    stops = np.r_[0, np.cumsum(sizes[:-1])]
    maximum = np.maximum.reduceat(scores, stops)
    scaled = np.exp(scores - np.repeat(maximum, sizes))
    mass = scaled / np.repeat(np.add.reduceat(scaled, stops), sizes)
    return mass - labels, np.maximum(mass * (1 - mass), 1e-6)


def without_marks(snapshot):
    return {**snapshot, 'riders': [{**row, 'mark_rank': None} for row in snapshot['riders']]}


def mark_dropout(race_id):
    return sha256(race_id.encode()).digest()[0] < 64


def frame(snapshot):
    actual = ordered.frame(snapshot)
    cars, base, line, group, position, size = actual[0]
    known_prior = profiles.profile_columns(snapshot['riders'], cars)
    count = len(cars)
    points = base['relative_points']
    scored = points[base['relative_points_known'] != 0]
    quality = np.std(scored) if len(scored) else 0.
    how_many_lines = len(set(group))
    line_strength = line['line_average_score']
    outside = np.max(np.where(group[:, None] != group, line_strength, -np.inf), axis=1)
    outside[~np.isfinite(outside)] = 0.
    main = np.column_stack((
        *(base[key] for key in BASE_FIELDS), *(line[key] for key in lines.LINE_FIELDS), actual[1],
        *(known_prior[key] for key in PROFILE_FIELDS), position, size, cars,
        np.full(count, quality), np.full(count, count), np.full(count, how_many_lines),
        line_strength - outside, points - line['line_leader_score'],
    ))
    return actual, main


def availability(shape, prefix):
    available = np.ones(shape, dtype=bool)
    for placed in prefix:
        available[np.arange(len(placed)), placed] = False
    return available


def masked_probabilities(scores, prefix):
    return softmax(np.where(availability(scores.shape, prefix), scores, -np.inf), axis=-1)


def design(context, prefix, baseline):
    actual, static = context
    _, base, line, group, position, size = actual[0]
    count = len(group)
    rows = baseline.shape[0]
    raw = [np.broadcast_to(static, (rows, *static.shape)), baseline[..., None]]
    for actor in prefix:
        same = group[actor, None] == group
        differences = position[None, :] - position[actor, None]
        raw.append(np.stack((
            same, same * differences, same & (differences == 1),
            base['relative_points'][actor, None] - base['relative_points'],
            base['mark_first'][actor, None] + np.zeros(count),
            base['win_rate'][actor, None] - base['win_rate'],
            line['line_average_score'][actor, None] - line['line_average_score'],
            position[actor, None] + np.zeros(count),
            size[actor, None] + np.zeros(count),
        ), axis=-1))
    if len(prefix) == 2:
        join = group[prefix[0]] == group[prefix[1]]
        raw.append(np.broadcast_to(join[:, None, None], (rows, count, 1)))
    return np.asarray(np.concatenate(raw, axis=-1), dtype=np.float32)


def collect_training(records):
    races = []
    augmented = 0
    for example in records:
        paid = example['outcomes']
        if len(paid['3t']) != 1 or len(paid['2t']) != 1:
            continue
        outcome = tuple(paid['3t'][0])
        if len(outcome) != 3 or len(set(outcome)) != 3 or outcome[:2] != tuple(paid['2t'][0]):
            raise ValueError('Training records must have consistent ordered results.')
        card = example['input']
        if mark_dropout(card['race_id']) and any(r.get('mark_rank') is not None for r in card['riders']):
            card = without_marks(card)
            augmented += 1
        prepared = frame(card)
        cars = prepared[0][0][0]
        races.append((prepared, tuple(cars.index(car) for car in outcome)))
    if not races:
        raise ValueError('No unambiguous earlier results were supplied.')
    return races, augmented


def fit_stage(races, baseline, stage):
    import lightgbm as lgb

    widths = np.array([len(context[0][0][0]) - stage for context, _ in races])
    designs, y, offsets = [], [], []
    for context, order in races:
        prefix = tuple(np.array([value]) for value in order[:stage])
        initial = baseline.logits(context[0], prefix)
        keep = availability(initial.shape, prefix)[0]
        designs.append(design(context, prefix, initial)[0, keep])
        labels = np.arange(len(keep)) == order[stage]
        y.append(labels[keep])
        offsets.append(initial[0, keep])

    training = lgb.Dataset(np.concatenate(designs), label=np.concatenate(y), init_score=np.concatenate(offsets))
    started = False

    def objective(raw_scores, data):
        nonlocal started
        if not started:
            np.testing.assert_allclose(raw_scores, data.get_init_score(), atol=1e-12)
            started = True
        return group_derivatives(raw_scores, data.get_label(), widths)

    return lgb.train({
        'objective': objective, 'metric': 'None', 'boosting_type': 'gbdt',
        'learning_rate': .04, 'max_depth': 4, 'num_leaves': 12, 'min_data_in_leaf': 90,
        'lambda_l2': 6., 'feature_fraction': .85, 'max_bin': 63,
        'num_threads': 4, 'verbosity': -1, 'seed': 21904, 'deterministic': True, 'force_col_wise': True,
    }, training, num_boost_round=96)


def stage_prefix(cars, stage):
    indices = np.arange(len(cars))
    if stage == 0:
        return ()
    if stage == 1:
        return (indices,)
    return np.where(indices[:, None] != indices)


def batch_stage(contexts, ranker, booster, stage):
    batches, initial, eligible, prefixes = [], [], [], []
    for context in contexts:
        cars = context[0][0][0]
        prefix = stage_prefix(cars, stage)
        scores = ranker.logits(context[0], prefix)
        kept = availability(scores.shape, prefix)
        initial.append(scores)
        eligible.append(kept)
        prefixes.append(prefix)
        batches.append(design(context, prefix, scores)[kept])
    flat = np.concatenate(batches, axis=0)
    offsets = np.r_[0, np.cumsum([len(rows) for rows in batches])]
    steps = sorted(set(steps[stage] for steps, _ in ARMS.values()) - {0})
    corrections = {n: booster.predict(flat, raw_score=True, num_iteration=n, num_threads=4) for n in steps}
    output = []
    for index, (scores, keep, prefix) in enumerate(zip(initial, eligible, prefixes, strict=True)):
        at = {0: masked_probabilities(scores, prefix)}
        left, right = offsets[index:index+2]
        for n, predicted in corrections.items():
            updated = scores.copy()
            updated[keep] += predicted[left:right]
            at[n] = masked_probabilities(updated, prefix)
            if n == 96:
                updated[keep] = scores[keep] + .5 * predicted[left:right]
                at[-n] = masked_probabilities(updated, prefix)
        output.append(at)
    return output


def joint_orders(cars, probabilities, size):
    head, second = stage_prefix(cars, 2)
    first, following, last = probabilities
    pair = first[0, head] * following[head, second]
    triple = (pair[:, None] * last).ravel()
    assert np.isclose(np.sum(triple), 1.)
    order = np.argsort(-triple, kind='stable')
    keep = order[triple[order] > 0.]
    if size is not None:
        keep = keep[:size]
    n = len(cars)
    picks = [(cars[head[i//n]], cars[second[i//n]], cars[i%n]) for i in keep]
    return picks


def rank_batch(keys, contexts, ranker, boosters, size=8):
    phases = [batch_stage(contexts, ranker, model, stage) for stage, model in enumerate(boosters)]
    output = []
    for idx, race in enumerate(keys):
        cars = contexts[idx][0][0][0]
        prediction = {}
        for mode, (iterations, factor) in ARMS.items():
            selected = [phases[k][idx][step if factor != .5 else -step] for k, step in enumerate(iterations)]
            prediction[mode] = joint_orders(cars, selected, size)
        output.append((race, prediction))
    return output
