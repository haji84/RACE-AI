"""Learn ordering offsets for the same three riders in a keirin finish."""

from collections import defaultdict
from functools import lru_cache
from itertools import permutations

import numpy as np
from scipy.special import softmax


@lru_cache(maxsize=5)
def trio_layout(count):
    if not 5 <= count <= 9:
        raise ValueError('A keirin race must have five to nine starters.')
    orders = np.array(list(permutations(range(count), 3)))
    members = defaultdict(list)
    for index, order in enumerate(orders):
        members[tuple(sorted(order))].append(index)
    groups = np.array(list(members.values()))
    orders.flags.writeable = groups.flags.writeable = False
    return orders, groups


def reorder_trios(probabilities, groups, offsets):
    """Change probabilities within each trio while preserving its total mass."""
    grouped = probabilities[groups]
    mass = grouped.sum(axis=1, keepdims=True)
    updated = np.zeros_like(probabilities)
    possible = mass[:, 0] > 0
    indices = groups[possible]
    log_prob = np.full_like(grouped[possible], -np.inf)
    np.log(grouped[possible], where=grouped[possible] > 0, out=log_prob)
    updated[indices] = mass[possible] * softmax(log_prob + offsets[indices], axis=1)
    return updated


def order_design(info, order, prior, probability):
    _, base, lines, group, position, size = info[0]
    first, second, third = order.T
    same_pair = group[first] == group[second]
    first_third = group[first] == group[third]
    second_third = group[second] == group[third]
    role = (size > 1) & (position > 0)
    points = base['relative_points']
    front = lines['line_leader_score']
    return np.column_stack((
        .5 * np.log(np.maximum(probability, 1e-12)),
        same_pair, same_pair & (position[first] > position[second]), first_third, second_third,
        role[first], role[second], role[third],
        points[first] - points[second], points[second] - points[third],
        base['win_rate'][first] - base['win_rate'][second],
        base['mark_first'][first], base['mark_first'][second],
        (~same_pair) * (front[first] - front[second]),
        role[first] * prior[first, 0], role[second] * prior[second, 0],
        (~same_pair) * prior[second, 2], (~same_pair) * prior[second, 5],
        same_pair * prior[second, 3],
    ))
