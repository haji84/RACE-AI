"""Replay observed line and finish history within the saved keirin ranker."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import permutations

import numpy as np

from scripts import keirin_line_history_study as lines
from scripts import keirin_ordered_ticket_study as ordered
from scripts import keirin_small_ticket_study as ranking
from scripts.keirin_rider_profile_history import is_registration


ROLE_PRIORS = (.15, .15, .45, .2, .4, .5, .1, .25, .4)
PAIR_PRIORS = (.08, .18, .14)
PHASE_COLUMNS = (0, 1, 2, 3, 4, 6, 7)
MODES = ('saved', 'past_phases', 'past_phases_and_pairs')


def race_layout(snapshot):
    riders = sorted(snapshot['riders'], key=lambda row: row['car'])
    cars = [row['car'] for row in riders]
    line_groups = snapshot['line_groups']
    members = [car for line in line_groups for car in line]
    if any(not line for line in line_groups) or not 5 <= len(cars) <= 9 or sorted(members) != cars or len(set(cars)) != len(cars):
        raise ValueError('Race and published lines must contain the same unique starters.')
    registrations = [value if is_registration(value := row.get('registration')) else None for row in riders]
    ids = [value for value in registrations if value is not None]
    if len(set(ids)) != len(ids):
        raise ValueError('A registration appears twice in one race.')
    positions = {
        car: (number, 3 if len(line) == 1 else min(position, 2))
        for number, line in enumerate(line_groups) for position, car in enumerate(line)
    }
    day = date.fromisoformat(snapshot['race_id'][:8])
    return day, cars, registrations, positions


def accumulate(specific, group, values):
    for column, observation in enumerate(values):
        if observation is None:
            continue
        specific[column, 0] += 1
        specific[column, 1] += observation
        group[column, 0] += 1
        group[column, 1] += observation


def estimate(counts, population, prior):
    reference = (population[:, 1] + 12 * np.asarray(prior)) / (population[:, 0] + 12)
    observed = counts[:, 0]
    return np.concatenate(((counts[:, 1] - observed * reference) / (observed + 8),
                           observed / (observed + 8)))


@dataclass(frozen=True)
class HistoryFeatures:
    individual: np.ndarray
    pairs: np.ndarray
    back_counts: np.ndarray
    pair_counts: np.ndarray


class History:
    """Use only earlier day results, preserving absent S/B as unobserved."""

    def __init__(self):
        self.last_day = None
        self.roles = defaultdict(lambda: np.zeros((len(ROLE_PRIORS), 2), dtype=int))
        self.role_populations = np.zeros((4, len(ROLE_PRIORS), 2), dtype=int)
        self.duos = defaultdict(lambda: np.zeros((len(PAIR_PRIORS), 2), dtype=int))
        self.duo_populations = np.zeros((4, 4, len(PAIR_PRIORS), 2), dtype=int)

    def observe(self, snapshot, finish_order, *, start, back):
        day, cars, registrations, positions = race_layout(snapshot)
        if self.last_day is not None and day < self.last_day:
            raise ValueError('Historical observations must arrive in calendar order.')
        if sorted(finish_order) != cars:
            raise ValueError('A complete finish order for the observed starters is required.')
        if any(value is not None and value not in cars for value in (start, back)):
            raise ValueError('S and B marks must refer to observed starters.')
        finishes = {car: rank for rank, car in enumerate(finish_order, 1)}
        by_car = dict(zip(cars, registrations, strict=True))
        back_line = positions[back][0] if back is not None else None
        for car, registration in by_car.items():
            if registration is None:
                continue
            group, role = positions[car]
            rank = finishes[car]
            own = back_line is not None and group == back_line
            other = back_line is not None and group != back_line
            values = (
                car == start if start is not None else None,
                car == back if back is not None else None,
                rank <= 2 if car == back else None,
                rank == 1 if own else None, rank <= 2 if own else None, rank <= 3 if own else None,
                rank == 1 if other else None, rank <= 2 if other else None, rank <= 3 if other else None,
            )
            accumulate(self.roles[registration, role], self.role_populations[role], values)
        for line in snapshot['line_groups']:
            for first, second in permutations((car for car in line if by_car[car] is not None), 2):
                group, first_role = positions[first]
                second_role = positions[second][1]
                first_rank, second_rank = finishes[first], finishes[second]
                wins = first_rank == 1 and second_rank == 2
                values = wins, first_rank <= 3 and second_rank <= 3, wins if group == back_line else None
                accumulate(self.duos[by_car[first], by_car[second], first_role, second_role],
                           self.duo_populations[first_role, second_role], values)
        self.last_day = day

    def features(self, snapshot):
        day, cars, registrations, positions = race_layout(snapshot)
        if self.last_day is not None and self.last_day >= day:
            raise ValueError('Forecast history must end on earlier days.')
        count = len(cars)
        individual = np.zeros((count, 2 * len(ROLE_PRIORS)))
        pairs = np.zeros((count, count, 2 * len(PAIR_PRIORS)))
        back_counts = np.zeros(count, dtype=int)
        pair_counts = np.zeros((count, count), dtype=int)
        for index, (car, registration) in enumerate(zip(cars, registrations, strict=True)):
            group, role = positions[car]
            counts = self.roles.get((registration, role))
            if counts is not None:
                individual[index] = estimate(counts, self.role_populations[role], ROLE_PRIORS)
                back_counts[index] = counts[1, 0]
            for other, other_car in enumerate(cars):
                other_group, other_role = positions[other_car]
                if group != other_group or index == other:
                    continue
                previous = self.duos.get((registration, registrations[other], role, other_role))
                if previous is not None:
                    pairs[index, other] = estimate(previous, self.duo_populations[role, other_role], PAIR_PRIORS)
                    pair_counts[index, other] = previous[0, 0]
        return HistoryFeatures(individual, pairs, back_counts, pair_counts)


def history_design(groups, prefix, history, use_pairs):
    count = len(groups)
    size = len(prefix[0]) if prefix else 1
    shares_line = groups == groups[:, None]
    current_back = history.individual[:, 1]
    line_back = np.max(np.where(shares_line, current_back, -np.inf), axis=1)
    comparison = np.max(np.where(~shares_line, current_back, -np.inf), axis=1)
    comparison[~np.isfinite(comparison)] = 0
    individual = np.column_stack((history.individual, line_back, comparison))
    design = [np.broadcast_to(individual, (size, count, individual.shape[1]))]
    for selected in prefix:
        same = shares_line[selected]
        activity = history.individual[:, PHASE_COLUMNS]
        leader_back = current_back[selected, None] * same
        design.extend((same[..., None] * activity, (~same)[..., None] * activity, leader_back[..., None]))
        if use_pairs:
            design.append(history.pairs[selected])
    return np.concatenate(design, axis=-1)


class SavedRanker:
    """Add research offsets to the same frozen ordered finish probabilities."""

    def __init__(self, configuration):
        self.baseline = [
            np.array([mapping[key] for key in lines.names_for(ordered.BASE, stage)])
            for stage, mapping in enumerate(configuration['baseline'])
        ]
        self.saved_offsets = [np.asarray(values) for values in configuration['offsets']]

    def logits(self, info, prefix):
        stage = len(prefix)
        logits = lines.design(info[0], ordered.BASE, prefix) @ self.baseline[stage]
        if stage:
            logits += ordered.additional_design(info, prefix) @ self.saved_offsets[stage]
        return logits

    def fit(self, examples):
        races = []
        for example, history in examples:
            paid = example['outcomes']
            if len(paid['3t']) != 1 or len(paid['2t']) != 1:
                continue
            trio = tuple(paid['3t'][0])
            if len(trio) != 3 or len(set(trio)) != 3 or trio[:2] != tuple(paid['2t'][0]):
                raise ValueError('Training exacta and trifecta results disagree.')
            info = ordered.frame(example['input'])
            cars = info[0][0]
            races.append((info, history, [cars.index(car) for car in trio]))
        if not races:
            raise ValueError('No unambiguous earlier races for fitting.')
        available = np.array([np.arange(9) < len(info[0][0]) for info, _, _ in races])
        target = np.array([finish for _, _, finish in races])
        row_indices = np.arange(len(races))
        weights = {name: [] for name in MODES[1:]}
        for stage in range(3):
            baselines = np.zeros((len(races), 9))
            matrices = {}
            for index, (info, history, finish) in enumerate(races):
                prefix = tuple(np.array([car]) for car in finish[:stage])
                count = len(info[0][0])
                baselines[index, :count] = self.logits(info, prefix)[0]
                for name in weights:
                    extra = history_design(info[0][-3], prefix, history, name == 'past_phases_and_pairs')[0]
                    if name not in matrices:
                        matrices[name] = np.zeros((len(races), 9, extra.shape[-1]))
                    matrices[name][index, :count] = extra
            for name, matrix in matrices.items():
                weights[name].append(ordered.fit_offset(baselines, matrix, available, target[:, stage]))
            available[row_indices, target[:, stage]] = False
        return {'fit_races': len(races), 'weights': weights}

    def predict(self, snapshot, history, weights):
        info = ordered.frame(snapshot)
        cars, groups = info[0][0], info[0][-3]

        def conditional(prefix):
            logits = self.logits(info, prefix)
            if weights is not None:
                coefficient, use_pairs = weights
                logits += history_design(groups, prefix, history, use_pairs) @ coefficient[len(prefix)]
            return ranking.available_probabilities(logits, prefix)

        return ranking.conditional_rankings(cars, conditional)
