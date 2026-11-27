"""Conditional ordered finishes learned from chronological, pre-race-shaped inputs."""
from dataclasses import dataclass
from hashlib import sha256
from itertools import permutations
from math import fsum, isfinite

import numpy as np

from . import keirin_dossier_conditions as dossier
from . import keirin_nationwide_auto_generator as core
from .keirin_joint_finish import JointFinish

MODEL_ID = 'keirin-conditional-order-trees-v1'
RIDER_NUMERIC = ('mark_rank', 'points', 'win_rate', 'top2_rate', 'top3_rate', 'age', 'gear')
STYLE = ('NIGE', 'MAKURI', 'SASHI', 'MARK', 'ALLROUND')
RIDER_CLASS = ('A3', 'A2', 'A1', 'S2', 'S1', 'SS', 'L1')
BASE = (*RIDER_NUMERIC, 'points_vs_field', 'style', 'rider_class', 'line_role', 'line_size',
        'leader_points_vs_field', 'line_points_vs_field', 'line_points_max_vs_field',
        'field_size', 'lines_known', 'line_count', 'largest_line', 'venue', 'meeting_grade',
        'round_stage', 'competition', 'mark_count')
CONDITIONAL = ('stage', 'same_line_first', 'same_line_second', 'position_vs_first', 'position_vs_second',
               'points_vs_first', 'points_vs_second', 'first_style', 'second_style', 'first_role', 'second_role')
FEATURES = BASE + CONDITIONAL
CATEGORICAL = ('style', 'rider_class', 'venue', 'meeting_grade', 'round_stage', 'competition',
               'first_style', 'second_style')
TEMPERATURES = (.8, .9, 1., 1.1, 1.25, 1.5)
NUM_ROUNDS = 140
NAN = float('nan')


def _number(value):
    return float(value) if type(value) in (int, float) and isfinite(value) else NAN


def _category(value, choices):
    return choices.index(value) if value in choices else NAN


def _mean(values):
    known = [value for value in values if isfinite(value)]
    return fsum(known) / len(known) if known else NAN


@dataclass(frozen=True)
class Context:
    race_id: str
    cars: tuple
    static: np.ndarray
    lines: tuple | None

    def choices(self, prefix):
        options = tuple(i for i in range(len(self.cars)) if i not in prefix)
        size = len(options)
        conditioned = np.full((size, len(CONDITIONAL)), np.nan, dtype=np.float32)
        conditioned[:, 0] = len(prefix)
        data = self.static[list(options)]
        for place, previous in enumerate(prefix):
            pos = BASE.index('line_role')
            if self.lines is not None:
                conditioned[:, 1 + place] = [self.lines[i] == self.lines[previous] for i in options]
                conditioned[:, 3 + place] = data[:, pos] - self.static[previous, pos]
            points = BASE.index('points')
            conditioned[:, 5 + place] = data[:, points] - self.static[previous, points]
            conditioned[:, 7 + place] = self.static[previous, BASE.index('style')]
            conditioned[:, 9 + place] = self.static[previous, pos]
        return options, np.column_stack((data, conditioned))


def context(race):
    """Translate published card fields. Missing attributes remain missing."""
    allowed = {'race_id', 'riders', 'line_groups', 'competition', 'meeting_grade', 'round_stage'}
    if (not set(race) <= allowed or not core.VENUE.fullmatch(race['race_id']) or
            type(race['riders']) is not list):
        raise ValueError('LEARNED_ORDER_INPUT_FIELDS')
    riders = sorted(race['riders'], key=lambda row: row['car'])
    cars = tuple(row['car'] for row in riders)
    if (not 3 <= len(cars) <= 9 or len(cars) != len(set(cars)) or
            not all(type(car) is int and 1 <= car <= 9 for car in cars) or
            any(not set(row) <= {'car', 'style', 'rider_class', *RIDER_NUMERIC} for row in riders)):
        raise ValueError('LEARNED_ORDER_RIDER_FIELDS')
    groups = race.get('line_groups')
    if groups is not None and (type(groups) is not list or not all(type(group) is list and group for group in groups)
                               or sorted(car for group in groups for car in group) != list(cars)):
        raise ValueError('LEARNED_ORDER_LINE_PARTITION')
    assignment = {car: (index, pos + 1) for index, group in enumerate(groups or []) for pos, car in enumerate(group)}
    points = {row['car']: _number(row.get('points')) for row in riders}
    average = _mean(points.values())
    mark_count = sum(1 <= _number(row.get('mark_rank')) <= len(cars) for row in riders)
    rows = []
    for row in riders:
        car = row['car']
        line = (NAN,) * 5
        if groups is not None:
            line_id, pos = assignment[car]
            members = groups[line_id]
            line_points = [points[member] for member in members if isfinite(points[member])]
            line = (pos, len(members), points[members[0]] - average,
                    _mean(line_points) - average, max(line_points, default=NAN) - average)
        rows.append([*(_number(row.get(field)) for field in RIDER_NUMERIC), points[car] - average,
                     _category(row.get('style'), STYLE), _category(row.get('rider_class'), RIDER_CLASS), *line,
                     len(cars), groups is not None, len(groups) if groups else NAN,
                     max(map(len, groups)) if groups else NAN, int(race['race_id'][8:10]),
                     _category(race.get('meeting_grade'), tuple(sorted(dossier.GRADES))),
                     _category(race.get('round_stage'), tuple(dossier.ROUND_PATTERNS)),
                     _category(race.get('competition'), tuple(sorted(core.CLASSES))), mark_count])
    return Context(race['race_id'], cars, np.array(rows, dtype=np.float32),
                   tuple(assignment[car][0] for car in cars) if groups is not None else None)


def group_softmax(logits, offsets):
    logits = np.asarray(logits, dtype=np.float64)
    lengths = np.diff(offsets)
    maxima = np.maximum.reduceat(logits, offsets[:-1])
    mass = np.exp(logits - np.repeat(maxima, lengths))
    return mass / np.repeat(np.add.reduceat(mass, offsets[:-1]), lengths)


def fit(examples, *, train_through, threads=2):
    """Train one grouped softmax tree model for all three prefix lengths."""
    import lightgbm as lgb

    features, labels, lengths, weights = [], [], [], []
    for race, winners in examples:
        if race.race_id[:8] > train_through or not winners:
            raise ValueError('LEARNED_ORDER_TRAINING_PERIOD_OR_LABEL')
        positions = {car: i for i, car in enumerate(race.cars)}
        for outcome in winners:
            order = tuple(positions[car] for car in outcome)
            if len(order) != 3 or len(set(order)) != 3:
                raise ValueError('LEARNED_ORDER_TRAINING_LABEL')
            for stage, winner in enumerate(order):
                choices, rows = race.choices(order[:stage])
                features.append(rows)
                labels.extend(int(i == winner) for i in choices)
                weights.extend([1. / len(winners)] * len(choices))
                lengths.append(len(choices))
    if not lengths:
        raise ValueError('LEARNED_ORDER_NO_TRAINING_EXAMPLES')
    offsets = np.r_[0, np.cumsum(lengths)]
    weights = np.asarray(weights)
    dataset = lgb.Dataset(np.concatenate(features), label=labels, feature_name=list(FEATURES),
                          categorical_feature=list(CATEGORICAL))

    def objective(scores, data):
        p = group_softmax(scores, offsets)
        return (p - data.get_label()) * weights, np.maximum(p * (1 - p), 1e-6) * weights

    return lgb.train(dict(objective=objective, metric='None', learning_rate=.05, num_leaves=31,
                          min_data_in_leaf=160, lambda_l2=4, force_col_wise=True, deterministic=True,
                          verbosity=-1, num_threads=threads, seed=20261128), dataset, num_boost_round=NUM_ROUNDS)


def load_frozen(manifest, tree_text):
    """Open the verified model payload from a private file or authenticated envelope."""
    import lightgbm as lgb

    if (manifest.get('model_id') != MODEL_ID or manifest.get('features') != list(FEATURES) or
            manifest.get('lightgbm') != lgb.__version__ or type(tree_text) is not str or
            sha256(tree_text.encode()).hexdigest() != manifest.get('tree_sha256') or
            manifest.get('calibration', {}).get('temperature') not in TEMPERATURES):
        raise ValueError('LEARNED_ORDER_FROZEN_MODEL_MISMATCH')
    model = lgb.Booster(model_str=tree_text)
    if model.feature_name() != list(FEATURES):
        raise ValueError('LEARNED_ORDER_FROZEN_FEATURE_LAYOUT')
    return model, manifest['calibration']['temperature']


@dataclass(frozen=True)
class Basis:
    cars: tuple
    logits: np.ndarray
    groups: tuple
    offsets: np.ndarray

    def _conditionals(self, temperature):
        if not isfinite(temperature) or temperature <= 0:
            raise ValueError('LEARNED_ORDER_TEMPERATURE')
        mass = group_softmax(self.logits / temperature, self.offsets)
        return {prefix: dict(zip(options, mass[a:b], strict=True))
                for (prefix, options), a, b in zip(self.groups, self.offsets[:-1], self.offsets[1:], strict=True)}

    def winning_mass(self, tickets, temperature):
        conditionals = self._conditionals(temperature)
        index = {car: pos for pos, car in enumerate(self.cars)}
        return fsum(conditionals[()][a] * conditionals[a,][b] * conditionals[a, b][c]
                    for a, b, c in (tuple(index[car] for car in ticket) for ticket in tickets))

    def joint(self, temperature=1.):
        p = self._conditionals(temperature)
        trifectas = {(self.cars[a], self.cars[b], self.cars[c]): float(p[()][a] * p[a,][b] * p[a, b][c])
                     for a, b, c in permutations(range(len(self.cars)), 3)}
        return JointFinish(self.cars, trifectas, tail=(0., 0.))


def bases(trained, contexts, *, batch_size=64, threads=2):
    for start in range(0, len(contexts), batch_size):
        batch = contexts[start:start + batch_size]
        arrays, descriptions, positions = [], [], [0]
        for race in batch:
            prefixes = [prefix for size in range(3) for prefix in permutations(range(len(race.cars)), size)]
            groups, ends = [], [0]
            for prefix in prefixes:
                options, array = race.choices(prefix)
                arrays.append(array)
                groups.append((prefix, options))
                ends.append(ends[-1] + len(array))
            descriptions.append((tuple(groups), np.array(ends)))
            positions.append(positions[-1] + ends[-1])
        logits = trained.predict(np.concatenate(arrays), raw_score=True, num_threads=threads)
        for row, (groups, ends), a, b in zip(batch, descriptions, positions[:-1], positions[1:], strict=True):
            yield Basis(row.cars, logits[a:b], groups, ends)


def predict(trained, contexts, *, temperature=1.):
    return (basis.joint(temperature) for basis in bases(trained, contexts))
