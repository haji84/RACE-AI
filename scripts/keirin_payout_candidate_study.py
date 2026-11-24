"""Describe the potential payout of each legal ordered trio before a keirin race."""

import numpy as np
from scipy.stats import rankdata

from scripts.keirin_race_risk_study import concentrated


def candidate_vectors(snapshot, cars, orders, probability):
    if {'outcomes', 'payouts', 'result'} & snapshot.keys():
        raise ValueError('Candidate payout inputs must be forecast fields.')
    lineup = {
        car: (number, place)
        for number, line in enumerate(snapshot['line_groups'])
        for place, car in enumerate(line)
    }
    riders = {row['car']: row for row in snapshot['riders']}
    if set(cars) != set(lineup) or set(cars) != set(riders):
        raise ValueError('Candidate field, rider records and published lines must agree.')
    sizes = len(cars)
    groups, places = np.array([lineup[car] for car in cars]).T
    scores = np.array([riders[car].get('competition_points') for car in cars], dtype=float)
    known = np.isfinite(scores)
    behind_best = np.where(known, np.max(scores[known], initial=0.) - scores, 0.)
    first, second, third = orders.T
    pair = np.zeros((sizes, sizes))
    np.add.at(pair, (first, second), probability)
    head = pair.sum(axis=1)
    count = len(orders)
    rank = rankdata(-probability)
    logs = lambda values: np.log(np.maximum(values, 1e-12))
    return np.column_stack((
        logs(probability), logs(pair[first, second]), logs(head[first]),
        np.log(rank), rank / count,
        groups[first] == groups[second], groups[first] == groups[third], groups[second] == groups[third],
        places[first], places[second], places[third],
        behind_best[first], behind_best[second], behind_best[third],
        known[first], known[second], known[third],
        np.full(count, sizes), np.full(count, len(snapshot['line_groups'])),
        np.full(count, concentrated(probability, 8)),
    ))


def high_payout_order(race_probability, large_payout_if_correct):
    """Prioritize candidates with a higher chance of winning at the larger payout."""
    return np.argsort(-(race_probability * large_payout_if_correct), kind='stable')
