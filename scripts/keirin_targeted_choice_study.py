"""Prior-race features and group probability corrections for the existing keirin ranker."""

from collections import defaultdict

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit

from scripts.keirin_line_event_study import accumulate, estimate, race_layout


METRICS = (
    'beat_line_front', 'beat_line_predecessor', 'cross_line_second', 'same_line_second',
    'win_from_other_back_line', 'second_from_other_back_line', 'win_from_own_back_line',
    'take_back_from_other_start_line',
)
ROLE_PRIOR = (.40, .40, .14, .28, .09, .12, .28, .10)


class LineRoleHistory:
    """Pool prior, finish-verified races by registration and planned line position."""

    def __init__(self):
        self.last_day = None
        self.counts = defaultdict(lambda: np.zeros((len(METRICS), 2), dtype=int))
        self.population = np.zeros((4, len(METRICS), 2), dtype=int)

    def observe(self, snapshot, finish_order, *, start, back):
        day, cars, registrations, positions = race_layout(snapshot)
        if self.last_day is not None and day < self.last_day:
            raise ValueError('Historical observations must arrive in calendar order.')
        if sorted(finish_order) != cars:
            raise ValueError('A complete finish order for the observed starters is required.')
        if any(value is not None and value not in cars for value in (start, back)):
            raise ValueError('S and B marks must refer to observed starters.')
        finish = {car: rank for rank, car in enumerate(finish_order, 1)}
        winner = finish_order[0]
        winning_line = positions[winner][0]
        start_line = positions[start][0] if start is not None else None
        back_line = positions[back][0] if back is not None else None
        leads = {car: (line[0], line[index - 1]) for line in snapshot['line_groups']
                 for index, car in enumerate(line) if index > 0}

        for car, registration in zip(cars, registrations, strict=True):
            if registration is None:
                continue
            line, role = positions[car]
            rank = finish[car]
            front, predecessor = leads.get(car, (None, None))
            values = (
                rank < finish[front] if front is not None else None,
                rank < finish[predecessor] if predecessor is not None else None,
                rank == 2 if line != winning_line else None,
                rank == 2 if line == winning_line and car != winner else None,
                rank == 1 if back_line is not None and line != back_line else None,
                rank == 2 if back_line is not None and line != back_line else None,
                rank == 1 if line == back_line else None,
                car == back if back_line is not None and start_line is not None and line != start_line else None,
            )
            accumulate(self.counts[registration, role], self.population[role], values)
        self.last_day = day

    def features(self, snapshot):
        day, cars, registrations, positions = race_layout(snapshot)
        if self.last_day is not None and self.last_day >= day:
            raise ValueError('Forecast history must end on earlier days.')
        features = np.zeros((len(cars), 2 * len(METRICS)))
        for index, (car, registration) in enumerate(zip(cars, registrations, strict=True)):
            role = positions[car][1]
            counts = self.counts.get((registration, role))
            if counts is not None:
                features[index] = estimate(counts, self.population[role], ROLE_PRIOR)
        return features


def group_mass(probabilities, member):
    return np.sum(np.where(member, probabilities, 0.), axis=-1)


def rescale_group(probabilities, member, target):
    """Set event mass, retaining relative chances inside each possible group."""
    mass = group_mass(probabilities, member)
    exchange = (mass > 1e-12) & (mass < 1 - 1e-12)
    if not np.any(exchange):
        return probabilities.copy()
    selected = probabilities[exchange]
    inside = target[exchange] / mass[exchange]
    outside = (1 - target[exchange]) / (1 - mass[exchange])
    revised = probabilities.copy()
    revised[exchange] = selected * np.where(member[exchange], inside[:, None], outside[:, None])
    return revised


def fit_group_offset(probabilities, member, design, outcomes):
    """Fit a regularized adjustment to observed event odds in calibration races."""
    mass = group_mass(probabilities, member)
    eligible = (mass > 1e-12) & (mass < 1 - 1e-12)
    existing = logit(mass[eligible])
    evidence = design[eligible]
    labels = outcomes[eligible]
    ridge = 2.5

    def objective(weights):
        scores = existing + evidence @ weights
        loss = np.logaddexp(0, scores).sum() - scores @ labels + ridge * (weights @ weights) / 2
        gradient = evidence.T @ (expit(scores) - labels) + ridge * weights
        return loss, gradient

    result = minimize(objective, np.zeros(design.shape[1]), method='L-BFGS-B', jac=True)
    if not result.success:
        raise RuntimeError(f'Group calibration failed: {result.message}')
    return result.x


def calibrate_group(probabilities, member, design, weights):
    mass = group_mass(probabilities, member)
    adjusted = expit(logit(np.clip(mass, 1e-12, 1 - 1e-12)) + design @ weights)
    return rescale_group(probabilities, member, adjusted)
