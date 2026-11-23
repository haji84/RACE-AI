"""Train and compare conditional ranking and limited ticket counts on KEIRIN snapshots."""

import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path

import numpy as np

from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_ranking_adjustment as adjustment
from race_ai.keirin_small_ticket_budget import pick_budget, spread_heads, wilson_lower
from scripts import keirin_fit_ranking_weights as fitter


COUNTS = (1, 4, 8)
MARKS = adjustment.MARK_FIELDS
STYLES = adjustment.STYLE_FIELDS
RIDER_SIGNALS = (
    'points_percentile', 'points_squared', 'grade_known', 'grade_s',
    'grade_a1', 'grade_a2', 'grade_l', 'mark_head_points', 'mark_head_gap',
)
PAIR_SIGNALS = (
    'points_proximity', 'marked_proximity', 'same_front_style',
    'follow_front', 'prior_favorite_own_marked', 'prior_unmarked_own_favorite',
    'prior_points_rank_own_rank',
)
MODES = ('static', 'rider_signals', 'prior_finishers')


def rider_evidence(snapshot):
    profiles, _ = core._evidence_profiles(snapshot)
    cars = sorted(profiles)
    vectors = adjustment.feature_vectors(profiles)
    columns = {
        key: np.array([vectors[c][key] for c in cars], dtype=float)
        for key in adjustment.FEATURES
    }
    points = columns['relative_points']
    scored = columns['relative_points_known'].astype(bool)
    rank = np.zeros(len(cars))
    totals = points[scored]
    rank[scored] = ((points[scored, None] > totals).sum(axis=1)
                    + .5*(points[scored, None] == totals).sum(axis=1)) / len(totals)
    ordered = sorted(totals, reverse=True)
    gap = ordered[0] - ordered[1] if len(ordered) > 1 else 0.0
    by_car = {row['car']: row for row in snapshot['riders']}
    classes = [(by_car[c].get('class') or '').upper() for c in cars]
    valid = {'SS', 'S1', 'S2', 'A1', 'A2', 'A3', 'L1'}
    columns.update(
        points_percentile=rank, points_squared=points**2,
        grade_known=np.array([g in valid for g in classes], dtype=float),
        grade_s=np.array([g in {'SS', 'S1', 'S2'} for g in classes], dtype=float),
        grade_a1=np.array([g == 'A1' for g in classes], dtype=float),
        grade_a2=np.array([g == 'A2' for g in classes], dtype=float),
        grade_l=np.array([g == 'L1' for g in classes], dtype=float),
        mark_head_points=points * columns['mark_first'],
        mark_head_gap=gap * columns['mark_first'],
    )
    return cars, columns


def feature_names(mode, position):
    names = fitter.fields('separate_finish_rates')[position]
    if mode != 'static':
        names += STYLES + RIDER_SIGNALS
    if mode == 'prior_finishers':
        names += tuple(f'place_{index+1}_{key}'
                       for index in range(position) for key in PAIR_SIGNALS)
    return names


def choice_matrix(columns, names, prefix):
    """Build the same inputs when learning and ranking candidate orders."""
    prefix_count = len(prefix[0]) if prefix else 1
    base = np.column_stack([columns[name] for name in names if name in columns])
    base = np.broadcast_to(base, (prefix_count, *base.shape))
    if not prefix or all(name in columns for name in names):
        return base
    points, rank = (columns[name] for name in ('relative_points', 'points_percentile'))
    known = columns['relative_points_known']
    favorite = columns['mark_first']
    marked = sum(columns[name] for name in MARKS[:-1])
    front = columns['front_style']
    follower = columns['follower_style']
    blocks = [base]
    for previous in prefix:
        # Each row compares the remaining starters against one already placed rider.
        previous = previous[:, None]
        valid_pair = known[previous] * known
        blocks.append(np.stack((
            -np.abs(points[previous] - points) * valid_pair,
            marked[previous] * marked,
            front[previous] * front,
            front[previous] * follower,
            favorite[previous] * marked,
            (columns['mark_known'][previous] - marked[previous]) * favorite,
            rank[previous] * rank * valid_pair,
        ), axis=-1))
    return np.concatenate(blocks, axis=-1)


def fit_coefficients(records):
    usable = []
    for record in records:
        outcomes = record['outcomes']
        if len(outcomes['3t']) != 1 or len(outcomes['2t']) != 1:
            continue
        podium = outcomes['3t'][0]
        if list(podium[:2]) != list(outcomes['2t'][0]) or len(set(podium)) != 3:
            raise ValueError('Training labels do not agree across markets.')
        cars, columns = rider_evidence(record['input'])
        usable.append((cars, columns, [cars.index(car) for car in podium]))
    if not usable:
        raise ValueError('No exact confirmed historical finishing orders.')

    result = {}
    rows = np.arange(len(usable))
    mask = np.array([np.arange(9) < len(cars) for cars, _, _ in usable])
    actual = np.array([order for _, _, order in usable])
    # Fit the full feature matrices once, then project fewer inputs for the controls.
    for position in range(3):
        names = feature_names('prior_finishers', position)
        full = np.zeros((len(usable), 9, len(names)), dtype=float)
        for index, (cars, columns, order) in enumerate(usable):
            prefix = tuple(np.array([item]) for item in order[:position])
            full[index, :len(cars)] = choice_matrix(columns, names, prefix)[0]
        for mode in MODES:
            active = feature_names(mode, position)
            data = full[:, :, :len(active)]
            weights = fitter.fit_choice(data, mask, actual[:, position])
            result.setdefault(mode, []).append(dict(zip(active, weights)))
        mask[rows, actual[:, position]] = False
    return result, len(usable)


def probabilities(columns, weights, mode, prefix):
    position = len(prefix)
    names = feature_names(mode, position)
    matrix = choice_matrix(columns, names, prefix)
    logits = matrix @ np.array([weights[position][key] for key in names])
    for fixed in prefix:
        logits[np.arange(len(fixed)), fixed] = -np.inf
    mass = np.exp(logits - np.max(logits, axis=1, keepdims=True))
    return mass / mass.sum(axis=1, keepdims=True)


def rankings(cars, columns, weights, mode):
    size = len(cars)
    positions = np.arange(size)
    first = probabilities(columns, weights, mode, ())[0]
    second = probabilities(columns, weights, mode, (positions,))
    pair = first[:, None] * second
    head, following = np.where(pair > 0)
    third = probabilities(columns, weights, mode, (head, following))
    triple = pair[head, following, None] * third

    pair_order = np.argsort(-pair.ravel(), kind='stable')
    triple_order = np.argsort(-triple.ravel(), kind='stable')
    two = [(cars[i//size], cars[i%size]) for i in pair_order if pair.ravel()[i] > 0]
    three = [(cars[head[i//size]], cars[following[i//size]], cars[i%size])
             for i in triple_order if triple.ravel()[i] > 0]
    return {'2t': (two, dict(zip(two, map(float, pair.ravel()[pair_order[:len(two)]])))),
            '3t': (three, dict(zip(three, map(float, triple.ravel()[triple_order[:len(three)]]))))}


def study_rankings(snapshot, cars, columns, weights, mode):
    rank = rankings(cars, columns, weights, mode)
    if mode != 'static':
        return rank
    base = core.generate_evidence_analysis(snapshot)['A']
    existing = adjustment.adjust(snapshot, base, 'A', weights, 1.0)
    return {market: ([tuple(ticket) for ticket in existing['candidate_tickets'][market]], values)
            for market, (_, values) in rank.items()}


def limited(ordered, masses, spread):
    plans = {
        n: spread_heads(ordered, n, n//2) if spread and n > 1 else ordered[:n]
        for n in COUNTS
    }
    coverage = [sum(masses[ticket] for ticket in plans[count]) for count in COUNTS]
    return plans, coverage


def choices(snapshot, coefficients, mode, spread):
    cars, columns = rider_evidence(snapshot)
    candidate = study_rankings(snapshot, cars, columns, coefficients[mode], mode)
    return {market: limited(*value, spread) for market, value in candidate.items()}


def hits(plans, actual):
    actual = {tuple(order) for order in actual}
    return tuple(bool(actual.intersection(plans[count])) for count in COUNTS)


def learn_budget(trials, *, mean_limit, one_choices, eight_limit):
    """Fit ticket thresholds within the declared cost and coverage constraints."""
    masses = np.array([sample[0] for sample in trials])
    scored = np.array([sample[1] for sample in trials])
    one, four, eight = masses.T
    gain = eight - four
    four_opts = [None, *np.unique(np.quantile(four, [.3, .45, .6, .75, .9, 1]))]
    gain_opts = np.unique(np.quantile(gain, [0, .3, .5, .65, .8, .9, .95]))
    best = None
    indexes = np.arange(len(trials))
    for one_min, four_max, min_gain in product(one_choices, four_opts, gain_opts):
        single = one >= one_min if one_min is not None else np.zeros(len(trials), dtype=bool)
        needs_eight = (four <= four_max) & (gain >= min_gain) if four_max is not None else False
        choice = np.where(single, 0, np.where(needs_eight, 2, 1))
        budget = int(np.array(COUNTS)[choice].sum())
        if budget > mean_limit * len(trials) or np.count_nonzero(choice == 2) > eight_limit * len(trials):
            continue
        candidate = (int(scored[indexes, choice].sum()), -budget)
        if best is None or candidate > best[0]:
            policy = {'one_min': one_min, 'four_max_for_eight': four_max, 'extra_gain_min': min_gain}
            best = (candidate, {key: float(value) if value is not None else None
                                for key, value in policy.items()})
    return best[1]


def calibrated_summary(samples, policy):
    summary = {count: Counter(races=0, hits=0, points=0) for count in COUNTS}
    for coverage, scored in samples:
        count = pick_budget(coverage, policy)
        selected = summary[count]
        selected['races'] += 1
        selected['hits'] += scored[COUNTS.index(count)]
        selected['points'] += count
    return {count: dict(result) for count, result in summary.items()}


def confidence_gates(samples, minimum=100):
    thresholds = {}
    for index, count in enumerate(COUNTS):
        ordered = sorted(((coverage[index], scored[index]) for coverage, scored in samples),
                         reverse=True)
        total_hits = 0
        best = None
        for position, (mass, hit) in enumerate(ordered, start=1):
            total_hits += hit
            if position < minimum or (position < len(ordered) and ordered[position][0] == mass):
                continue
            if wilson_lower(total_hits, position) >= .90:
                best = {'threshold': mass, 'races': position, 'hits': total_hits}
        thresholds[count] = best
    return thresholds


def checked_dataset(path, start, end):
    records = fitter.read(path)
    ids = [record['input']['race_id'] for record in records]
    if (not ids or len(ids) != len(set(ids)) or
        any(not start <= key[:8] <= end for key in ids) or
        any(record['cohort'] != 'annual' or record['input']['line_groups'] is not None
            for record in records)):
        raise ValueError('Expected unique ability-only races within their declared time partition.')
    return records


def train(fit, tune, calibrate):
    coefficients, admitted = fit_coefficients(fit)
    counts = {(mode, spread): Counter() for mode in MODES for spread in (False, True)}
    for record in tune:
        cars, columns = rider_evidence(record['input'])
        for mode in MODES:
            prediction = study_rankings(record['input'], cars, columns, coefficients[mode], mode)
            for spread in (False, True):
                for market, value in prediction.items():
                    plan, _ = limited(*value, spread)
                    for count, hit in zip(COUNTS, hits(plan, record['outcomes'][market])):
                        counts[(mode, spread)][f'{market}_{count}'] += hit

    baseline = counts[('static', False)]
    eligible = [key for key, count in counts.items()
                if count['3t_8'] >= baseline['3t_8'] and count['2t_4'] >= baseline['2t_4']]
    mode, spread = max(eligible, key=lambda key: (counts[key]['3t_4'], counts[key]['3t_1']))
    samples = {market: [] for market in ('2t', '3t')}
    for record in calibrate:
        plans = choices(record['input'], coefficients, mode, spread)
        for market, (plan, masses) in plans.items():
            samples[market].append((masses, hits(plan, record['outcomes'][market])))
    policies, policy_stats, confidence = {}, {}, {}
    for market, rows in samples.items():
        gates = confidence_gates(rows)
        one_choices = [None] if gates[1] is None else [None, gates[1]['threshold']]
        policies[market] = {
            'equal_average_four': learn_budget(rows, mean_limit=4, one_choices=one_choices, eight_limit=1),
            'four_or_eight': learn_budget(
                rows, mean_limit=5, one_choices=one_choices, eight_limit=.25),
        }
        policy_stats[market] = {name: calibrated_summary(rows, policy)
                                for name, policy in policies[market].items()}
        confidence[market] = gates
    return {
        'schema': 'KEIRIN_SMALL_TICKET_STUDY_V1',
        'fit_unique_results': admitted,
        'tuning_races': len(tune),
        'calibration_races': len(calibrate),
        'coefficients': coefficients,
        'tuning_fixed_counts': {f'{key[0]}:{"spread" if key[1] else "rank"}': dict(value)
                                for key, value in counts.items()},
        'selected': {'mode': mode, 'spread': spread},
        'policies': policies,
        'calibration_policies': policy_stats,
        'calibration_confirmed_90pct': confidence,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fit', required=True, type=Path)
    parser.add_argument('--tune', required=True, type=Path)
    parser.add_argument('--calibrate', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    outcome = train(
        checked_dataset(args.fit, '20250101', '20250731'),
        checked_dataset(args.tune, '20250801', '20250831'),
        checked_dataset(args.calibrate, '20250901', '20250930'),
    )
    with args.output.open('x') as target:
        json.dump(outcome, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps({k: v for k, v in outcome.items() if k != 'coefficients'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
