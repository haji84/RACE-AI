"""Research ticket budgets with separately measured coverage."""

from collections import Counter
from math import sqrt


def pick_budget(mass, policy):
    one, four, eight = mass
    threshold = policy['one_min']
    if threshold is not None and one >= threshold:
        return 1
    ceiling = policy['four_max_for_eight']
    if ceiling is not None and four <= ceiling and eight - four >= policy['extra_gain_min']:
        return 8
    return 4


def spread_heads(ordered, count, max_per_head):
    """Take the highest-ranked tickets under the cap, then fill from the same pool."""
    accepted, deferred = [], []
    heads = Counter()
    for ticket in ordered:
        head = ticket[0]
        if heads[head] < max_per_head:
            accepted.append(ticket)
            heads[head] += 1
            if len(accepted) == count:
                return accepted
        else:
            deferred.append(ticket)
    return accepted + deferred[:count-len(accepted)]


def wilson_lower(hits, observations):
    if not observations:
        return 0.0
    z = 1.959963984540054
    rate = hits / observations
    penalty = z*z / observations
    center = rate + penalty/2
    width = z * sqrt(rate*(1-rate)/observations + penalty/(4*observations))
    return (center-width) / (1+penalty)
