"""Keep a full trifecta distribution and learn the suffix of the finishing order."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from itertools import permutations
from math import exp, fsum, isclose, isfinite, log
from numbers import Real
from typing import Mapping

TOLERANCE = 1e-9
FEATURE_COUNT = 2


def _is_field(cars):
    return (3 <= len(cars) <= 9 and all(type(car) is int and 1 <= car <= 9 for car in cars)
            and len(set(cars)) == len(cars))


def _distribution(cars, trifectas):
    cars = tuple(cars)
    if not _is_field(cars):
        raise ValueError('Expected 3 to 9 distinct keirin car numbers.')
    expected = set(permutations(cars, 3))
    if (not isinstance(trifectas, Mapping)
            or any(not isinstance(order, tuple) or any(type(car) is not int for car in order) for order in trifectas)
            or set(trifectas) != expected):
        raise ValueError('Expected every ordered trifecta for the specified starters.')
    if any(isinstance(p, bool) or not isinstance(p, Real) or not isfinite(p) or not 0 <= p <= 1
           for p in trifectas.values()) or not isclose(fsum(trifectas.values()), 1., abs_tol=TOLERANCE, rel_tol=0.):
        raise ValueError('Expected finite trifecta probabilities summing to one.')
    return cars, dict(trifectas)


def _validate_finish(cars, order):
    order = tuple(order)
    if len(order) != len(cars) or not _is_field(order) or set(order) != set(cars):
        raise ValueError('Expected a complete finishing order for these starters.')
    return order


def _strength_features(cars, trifectas):
    wins = defaultdict(list)
    podium = defaultdict(list)
    for order, probability in trifectas.items():
        wins[order[0]].append(probability)
        for car in order:
            podium[car].append(probability)
    result = {}
    for car in cars:
        p = fsum(podium[car])
        podium_odds = log(max(1e-9, p)) - log(max(1e-9, 1 - p))
        win_given_podium = log(max(1e-9, fsum(wins[car]))) - log(max(1e-9, p))
        result[car] = (podium_odds, win_given_podium)
    return result


@dataclass(frozen=True)
class TailTrainingRace:
    """Earlier recorded prediction and its complete, independently bound finish."""

    day: date
    cars: tuple[int, ...]
    trifectas: Mapping[tuple[int, int, int], float]
    finish: tuple[int, ...]


def fit_tail(races, *, before):
    """Fit two shared conditional Plackett–Luce weights exclusively before a JST race date."""
    from scipy.optimize import minimize
    from scipy.special import logsumexp
    import numpy as np

    if type(before) is not date:
        raise ValueError('A JST training cutoff date is required.')
    blocks = defaultdict(list)
    for race in races:
        if type(race.day) is not date or race.day >= before:
            raise ValueError('Tail training requires a complete finish from an earlier race day.')
        cars, tris = _distribution(race.cars, race.trifectas)
        order = _validate_finish(cars, race.finish)
        features = _strength_features(cars, tris)
        for pos in range(3, len(order) - 1):
            choices = order[pos:]
            blocks[len(choices)].append([features[car] for car in choices])
    if not blocks:
        raise ValueError('Tail training requires a nontrivial choice of fourth or later finishers.')
    matrices = [np.asarray(v, dtype=np.float64) for v in blocks.values()]
    decisions = sum(len(x) for x in matrices)

    def loss(weight):
        total = 0.
        grad = np.zeros(FEATURE_COUNT)
        for x in matrices:
            z = x @ weight
            normal = logsumexp(z, axis=1)
            total += (normal - z[:, 0]).sum()
            soft = np.exp(z - normal[:, None])
            grad += (soft[:, :, None] * x).sum((0, 1)) - x[:, 0].sum(0)
        return total / decisions + .02 * (weight @ weight), grad / decisions + .04 * weight

    fitted = minimize(loss, np.zeros(FEATURE_COUNT), jac=True, method='L-BFGS-B',
                      options={'gtol': 1e-8, 'ftol': 1e-12})
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise ValueError('Conditional tail training did not converge.')
    return tuple(map(float, fitted.x))


class JointFinish:
    """A completed joint ranking with an unchanged ordered first-three distribution."""

    def __init__(self, cars, trifectas, *, tail=None):
        self._cars, self._trifectas = _distribution(cars, trifectas)
        if tail is None:
            if len(self._cars) > 4:
                raise ValueError('A fitted conditional tail is required with more than four starters.')
            tail = (0., 0.)
        theta = tuple(tail)
        if (len(theta) != FEATURE_COUNT or any(isinstance(w, bool) or not isinstance(w, Real)
                                                or not isfinite(w) for w in theta)):
            raise ValueError('Expected finite conditional tail coefficients.')
        features = _strength_features(self._cars, self._trifectas)
        self._score = {}
        for car, values in features.items():
            terms = [w * v for w, v in zip(theta, values, strict=True)]
            if not all(map(isfinite, terms)):
                raise ValueError('Conditional tail coefficients produce nonfinite scores.')
            result = sum(terms)
            if not isfinite(result):
                raise ValueError('Conditional tail coefficients produce nonfinite scores.')
            self._score[car] = result

    def trifectas(self):
        """Return the direct ordered trifecta mass, unchanged by tail training."""
        return dict(self._trifectas)

    def exactas(self):
        """Marginalize over all possible third-place finishers."""
        mass = defaultdict(list)
        for order, probability in self._trifectas.items():
            mass[order[:2]].append(probability)
        return {pair: fsum(weights) for pair, weights in mass.items()}

    def _choice(self, cars):
        peak = max(self._score[car] for car in cars)
        weights = [exp(self._score[car] - peak) for car in cars]
        total = fsum(weights)
        return [w / total for w in weights]

    def order_probability(self, order):
        """Evaluate one full official order under the single completed joint law."""
        order = _validate_finish(self._cars, order)
        probability = self._trifectas[order[:3]]
        for pos in range(3, len(order) - 1):
            probability *= self._choice(order[pos:])[0]
        return probability

    def marginals(self):
        """Return each car's probabilities at every finish slot, including the tail."""
        cars = self._cars
        car_index = {car: i for i, car in enumerate(cars)}
        n = len(cars)
        rows = [[0.] * n for _ in cars]
        by_remainder = defaultdict(list)
        for order, probability in self._trifectas.items():
            if not probability:
                continue
            for pos, car in enumerate(order):
                rows[car_index[car]][pos] += probability
            if n > 3:
                rest = tuple(car for car in cars if car not in order)
                by_remainder[rest].append(probability)

        @lru_cache(maxsize=None)
        def suffix(rest):
            weight = [[0.] * len(rest) for _ in cars]
            if not rest:
                return weight
            for chosen, probability in zip(rest, self._choice(rest), strict=True):
                weight[car_index[chosen]][0] += probability
                if len(rest) > 1:
                    sub = tuple(car for car in rest if car != chosen)
                    for car in sub:
                        i = car_index[car]
                        for pos, p in enumerate(suffix(sub)[i], start=1):
                            weight[i][pos] += probability * p
            return weight

        for rest, values in by_remainder.items():
            mass = fsum(values)
            tail = suffix(rest)
            for car in rest:
                i = car_index[car]
                for pos, probability in enumerate(tail[i], start=3):
                    rows[i][pos] += mass * probability

        if any(not isclose(fsum(line), 1., rel_tol=0., abs_tol=TOLERANCE)
               for line in (*rows, *zip(*rows, strict=True))):
            raise ArithmeticError('Joint finish marginals do not sum to one in every row and column.')
        return {car: tuple(row) for car, row in zip(cars, rows, strict=True)}

    def rider_summary(self):
        """Summarize the same full-position probabilities without a confidence claim."""
        grids = self.marginals()
        riders = {}
        for car, ranks in grids.items():
            riders[car] = dict(
                top2_probability=fsum(ranks[:2]),
                top3_probability=fsum(ranks[:3]),
                outside_top3_probability=fsum(ranks[3:]),
                most_likely_rank=1 + max(range(len(ranks)), key=ranks.__getitem__),
                expected_rank=fsum(place * probability for place, probability in enumerate(ranks, start=1)),
            )
        return dict(
            premise='Given the listed starters, the frozen pre-race distribution for the first three '
                    'places and the conditional order of the remaining starters fitted to earlier finishes.',
            calibration_status='unavailable',
            riders=riders,
        )
