"""Verbatim function extraction from PR64 web/research_contract.py.
Source commit 27f3df12ddca3971833d4dbf03f6fbcc88df6b07.
Only the six-boat ranking kernel and its error/number validation are reused.
No provider, betting, money, training or deployment dependency.
"""
import itertools
import math
import re

class PredictionError(ValueError):
    """Missing, nonfinite, temporally unavailable or inconsistent research input."""

def _number(value, name, minimum, maximum):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not minimum <= value <= maximum or not math.isfinite(value)):
        raise PredictionError(f'invalid finite {name}')
    return float(value)

def plackett_luce(strengths_by_lane):
    """Exact enumeration of strict top-three orders plus all six rank marginals."""
    if not isinstance(strengths_by_lane, dict) or len(strengths_by_lane) != 6:
        raise PredictionError('exactly six distinct boat strengths required')
    strengths = {}
    for lane, value in strengths_by_lane.items():
        if isinstance(lane, str) and re.fullmatch(r'[1-6]', lane):
            lane = int(lane)
        if type(lane) is not int or lane not in range(1, 7) or lane in strengths:
            raise PredictionError('boat identities must be 1..6')
        strengths[lane] = _number(value, 'strength', 1e-9, 1e9)
    if set(strengths) != set(range(1, 7)):
        raise PredictionError('boat identities must be 1..6')
    lanes = tuple(range(1, 7))

    def order_probability(order):
        remaining, probability = list(lanes), 1.0
        for lane in order:
            probability *= strengths[lane] / math.fsum(strengths[x] for x in remaining)
            remaining.remove(lane)
        return probability

    triples = [dict(combination=list(order), probability=order_probability(order))
               for order in itertools.permutations(lanes, 3)]
    mass = math.fsum(row['probability'] for row in triples)
    for row in triples:
        row['probability'] /= mass
    full = [(order, order_probability(order)) for order in itertools.permutations(lanes)]
    full_mass = math.fsum(value for _, value in full)
    positions = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth')
    marginals = []
    for lane in lanes:
        row = dict(lane=lane)
        for index, label in enumerate(positions):
            row[label + '_probability'] = math.fsum(value for order, value in full if order[index] == lane) / full_mass
        row['top3_probability'] = math.fsum(row[label + '_probability'] for label in positions[:3])
        marginals.append(row)
    return dict(triples=triples, marginals=marginals,
                strengths=[dict(lane=lane, strength=strengths[lane]) for lane in lanes])
