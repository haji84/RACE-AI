"""Compare registration-bound rider histories within the existing KEIRIN ranking."""

import argparse
from collections import Counter, defaultdict
from math import exp, fsum, isfinite
import json
from pathlib import Path

import numpy as np

from race_ai import keirin_nationwide_auto_generator as core
from scripts import keirin_fit_ranking_weights as fitter
from scripts import keirin_line_history_study as lines
from scripts import keirin_small_ticket_study as ranking
from scripts.keirin_rider_profile_history import CONTEXT_FIELDS, FORM_FIELDS, is_registration


MODES = ('published_line', 'rider_form', 'rider_context')
ADDITIONS = ((), FORM_FIELDS, FORM_FIELDS + CONTEXT_FIELDS)
CAPS = {'2t': (1, 2, 4), '3t': (1, 4, 8)}
CURRENT_B_PROFILE_STRENGTH = 0.5


def profile_columns(riders, cars):
    by_car = {rider['car']: rider for rider in riders}
    columns = {key: np.zeros(len(cars)) for key in FORM_FIELDS + CONTEXT_FIELDS}
    for index, car in enumerate(cars):
        rider = by_car[car]
        if not is_registration(rider.get('registration')):
            continue
        features = rider.get('profile', {})
        for key in features.keys() & columns.keys():
            value = features[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or abs(value) > 3):
                raise ValueError('A rider profile contains an invalid feature value.')
            columns[key][index] = value
    return columns


def names_for(mode, position):
    return lines.names_for('published_line', position) + ADDITIONS[MODES.index(mode)]


def features(snapshot):
    if 'outcomes' in snapshot or 'result' in snapshot:
        raise ValueError('Prediction snapshots must contain pre-race data only.')
    line_frame = lines.frame(snapshot)
    return line_frame, profile_columns(snapshot['riders'], line_frame[0])


def design(frame, mode, prefix):
    line_frame, rider_features = frame
    baseline = lines.design(line_frame, 'published_line', prefix)
    added_names = ADDITIONS[MODES.index(mode)]
    if not added_names:
        return baseline
    added = np.column_stack([rider_features[name] for name in added_names])
    return np.concatenate((baseline, np.broadcast_to(added, (len(baseline), *added.shape))), axis=-1)


def fit(examples):
    races = []
    for example in examples:
        paid = example['outcomes']
        if any(len(paid[market]) != 1 for market in CAPS):
            continue
        observed = list(paid['3t'][0])
        if len(observed) != 3 or len(set(observed)) != 3 or observed[:2] != list(paid['2t'][0]):
            raise ValueError('Records must have a consistent first three finishers.')
        frame = features(example['input'])
        cars = frame[0][0]
        races.append((frame, [cars.index(car) for car in observed]))
    if not races:
        raise ValueError('No earlier races with an unambiguous podium.')

    remaining = np.array([np.arange(9) < len(frame[0][0]) for frame, _ in races])
    winners = np.array([order for _, order in races])
    parameters = {mode: [] for mode in MODES}
    for stage in range(3):
        matrix = np.zeros((len(races), 9, len(names_for(MODES[-1], stage))))
        for index, (frame, order) in enumerate(races):
            prefix = tuple(np.array([placed]) for placed in order[:stage])
            matrix[index, :len(frame[0][0])] = design(frame, MODES[-1], prefix)[0]
        for mode in MODES:
            names = names_for(mode, stage)
            fitted = fitter.fit_choice(matrix[:, :, :len(names)], remaining, winners[:, stage])
            parameters[mode].append(dict(zip(names, fitted, strict=True)))
        remaining[np.arange(len(races)), winners[:, stage]] = False
    return parameters, len(races)


def predict(snapshot, parameters, modes=MODES):
    frame = features(snapshot)
    cars = frame[0][0]
    ranked = {}
    for mode in modes:
        coefficients = [np.array([weights[key] for key in names_for(mode, stage)])
                        for stage, weights in enumerate(parameters[mode])]

        def conditional(prefix):
            logits = design(frame, mode, prefix) @ coefficients[len(prefix)]
            return ranking.available_probabilities(logits, prefix)

        orders = ranking.conditional_rankings(cars, conditional)
        ranked[mode] = {market: ordered[:max(CAPS[market])] for market, (ordered, _) in orders.items()}
    return ranked


def current_b_with_profile(snapshot, prediction, coefficients):
    """Keep B's existing scenario paths and adjust only their support with past results."""
    paths = prediction['six_phase_scenarios']
    cars = sorted(rider['car'] for rider in snapshot['riders'])
    vectors = profile_columns(snapshot['riders'], cars)
    factors = []
    for weights in coefficients:
        factors.append({car: exp(CURRENT_B_PROFILE_STRENGTH * fsum(
            vectors[key][index] * weights.get(key, 0.0) for key in vectors))
                        for index, car in enumerate(cars)})
    if not paths or all(value == 1.0 for by_car in factors for value in by_car.values()):
        return prediction['candidate_tickets']

    first, second, third = factors
    branches = defaultdict(dict)
    for path in paths:
        head, following, final = path['projected_3ren_tan']
        branch = path['tactical_branch_id'], head, following
        branches[branch][final] = path['support_B'] / path['pair_support_B'] * third[final]
    totals = {branch: fsum(values.values()) for branch, values in branches.items()}
    adjusted = []
    for path in paths:
        head, following, final = path['projected_3ren_tan']
        branch = path['tactical_branch_id'], head, following
        pair_support = path['pair_support_B'] * first[head] * second[following]
        support = pair_support * branches[branch][final] / totals[branch]
        adjusted.append(dict(path, pair_support_B=pair_support, support_B=support))
    return core.select_scenario_markets(adjusted, arm='B', indistinguishable_field=(
        prediction['selection_context']['indistinguishable_solo_field']))['candidate_tickets']


def learn(training, calibration):
    parameters, used = fit(training)
    scores = {mode: Counter() for mode in MODES}
    for example in calibration:
        outcomes = {market: {tuple(order) for order in example['outcomes'][market]} for market in CAPS}
        for mode, ranked in predict(example['input'], parameters).items():
            for market, caps in CAPS.items():
                for cap in caps:
                    scores[mode][f'{market}:{cap}'] += bool(outcomes[market].intersection(ranked[market][:cap]))

    def key(mode):
        return tuple(scores[mode][metric] for metric in ('3t:4', '3t:8', '2t:2'))

    return {'schema': 'KEIRIN_RIDER_PROFILE_COMPARISON_V1', 'fit_unique': used,
            'calibration_races': len(calibration), 'selected': max(MODES, key=key),
            'selected_rider_variant': max(MODES[1:], key=key),
            'coefficients': parameters, 'calibration_hits': {mode: dict(counts) for mode, counts in scores.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fit', required=True, type=Path)
    parser.add_argument('--calibrate', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    fitted = learn(lines.examples(args.fit, '20251001', '20260731'),
                   lines.examples(args.calibrate, '20260801', '20260930'))
    with args.output.open('x') as target:
        json.dump(fitted, target, ensure_ascii=False, allow_nan=False, indent=2)
        target.write('\n')
    print(json.dumps({key: value for key, value in fitted.items() if key != 'coefficients'}))


if __name__ == '__main__':
    main()
