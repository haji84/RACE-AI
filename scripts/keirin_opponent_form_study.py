"""Measure earlier full finishes against the published strength of each opponent."""

from collections import defaultdict, deque

import numpy as np
from scipy.special import expit

from scripts.keirin_line_event_study import race_layout


OPPONENTS = ('all_opponents', 'other_line', 'same_line', 'higher_scoring')
WINDOWS = (('recent', 28), ('season', 180), ('role', 180), ('venue', 3))
FEATURES = tuple(
    window + '_' + name + suffix
    for window, _ in WINDOWS
    for suffix in ('', '_support')
    for name in OPPONENTS
)


class OpponentForm:
    """Accumulate only earlier results, identified by confirmed registration."""

    def __init__(self):
        self.last_day = None
        self.seen = set()
        self.readings = defaultdict(deque)

    def observe(self, snapshot, finish, *, points_scale=6.):
        day, cars, registrations, positions = race_layout(snapshot)
        race = snapshot['race_id']
        if race in self.seen:
            raise ValueError('This race was already observed.')
        if self.last_day is not None and day < self.last_day:
            raise ValueError('Results must arrive in calendar order.')
        if sorted(finish) != cars:
            raise ValueError('Full finishes must match the published starters.')
        by_car = {rider['car']:rider.get('competition_points') for rider in snapshot['riders']}
        points = np.array([by_car[car] if by_car[car] is not None else np.nan for car in cars])
        known = np.isfinite(points)
        if np.any(known & ((points < 1) | (points > 150))) or not 0 < points_scale <= 20:
            raise ValueError('Invalid historical competition points or scale.')
        order = {car:rank for rank,car in enumerate(finish)}
        finishes = np.array([order[car] for car in cars])
        groups = np.array([positions[car][0] for car in cars])
        different = groups[:, None] != groups
        compared = known[:, None] & known & ~np.eye(len(cars), dtype=bool)
        stronger = points[None,:] > points[:,None]
        observed = finishes[:, None] < finishes
        expected = expit((points[:, None] - points) / points_scale)
        residual = observed - expected

        filters = (compared, compared & different, compared & ~different, compared & stronger)
        support = np.stack([mask.sum(axis=1) for mask in filters],axis=1)
        totals = np.stack([np.where(mask, residual, 0).sum(axis=1) for mask in filters],axis=1)
        rates = np.divide(totals, support, out=np.zeros_like(totals), where=support > 0)
        venue = race[8:10]
        day_index = day.toordinal()
        for index,(car,registration) in enumerate(zip(cars,registrations,strict=True)):
            if registration is None or not np.any(support[index]):
                continue
            series = self.readings[registration]
            while series and day_index-series[0][0] > WINDOWS[1][1]:
                series.popleft()
            series.append((day_index,venue,positions[car][1],rates[index],support[index] > 0))
        self.seen.add(race)
        self.last_day = day

    def features(self, snapshot):
        day, cars, registrations, positions = race_layout(snapshot)
        if self.last_day is not None and self.last_day >= day:
            raise ValueError('Forecast history must end on earlier days.')
        n = len(OPPONENTS)
        result = np.zeros((len(cars), len(FEATURES)))
        venue = snapshot['race_id'][8:10]
        for index,(car,registration) in enumerate(zip(cars,registrations,strict=True)):
            series = self.readings.get(registration)
            if not series:
                continue
            role = positions[car][1]
            now = day.toordinal()
            age = np.array([now-prev for prev,_,_,_,_ in series])
            rates = np.stack([row[3] for row in series])
            present = np.stack([row[4] for row in series])
            for band,(name,days) in enumerate(WINDOWS):
                selected = age <= days
                if name == 'role':
                    selected &= np.array([row[2]==role for row in series])
                if name == 'venue':
                    selected &= np.array([row[1]==venue for row in series])
                seen = present[selected].sum(axis=0)
                shrinkage = 2 if name == 'venue' else 8
                column = band*2*n
                result[index,column:column+n] = rates[selected].sum(axis=0)/(seen+shrinkage)
                result[index,column+n:column+2*n] = seen/(seen+shrinkage)
        return result


class DynamicHeadToHead:
    """Research ratings from full orders, with each day learned simultaneously."""

    def __init__(self):
        self.last_day = None
        self.ratings = {}

    def _before_day(self, registration, day):
        if registration not in self.ratings:
            return np.zeros(2), False
        recorded_day, deviation, has_cross_line_history = self.ratings[registration]
        return deviation * np.exp2((recorded_day - day) / 60), has_cross_line_history

    def features(self, day, registrations):
        if self.last_day is not None and day <= self.last_day:
            raise ValueError('Forecast history must end on earlier days.')
        snapshot = [self._before_day(registration, day) for registration in registrations]
        return np.array([[rate[0], rate[1] - rate[0] if cross else 0.]
                         for rate, cross in snapshot]).reshape(-1, 2)

    def observe_day(self, day, races):
        """Update from (registrations, competition points, line groups, finishing places).

        Unknown line memberships use -1. The result for one race can only affect
        ratings supplied on a subsequent JST day.
        """
        if self.last_day is not None and day <= self.last_day:
            raise ValueError('Observations require increasing dates.')
        shifts = defaultdict(lambda: (np.zeros(2), np.zeros(2)))
        for registrations, points, groups, places in races:
            if not len(registrations) == len(points) == len(groups) == len(places):
                raise ValueError('Mismatched observed field lengths.')
            known_identities = [r for r in registrations if r]
            if len(set(known_identities)) != len(known_identities) or len(set(places)) != len(places):
                raise ValueError('Duplicate registration or placing.')
            if not registrations:
                continue
            points = np.array([value or 0 for value in points], dtype=float)
            groups = np.asarray(groups)
            places = np.asarray(places)
            known = np.array([bool(r) for r in registrations]) & np.isfinite(points) & (points > 0)
            same_field = known[:, None] & known[None, :] & ~np.eye(len(points), dtype=bool)
            cross = same_field & (groups[:, None] >= 0) & (groups[None, :] >= 0) & (groups[:, None] != groups[None, :])
            previous = np.array([self._before_day(reg, day)[0] for reg in registrations])
            points = np.where(known, points, 0)
            offset = (points[:, None] - points[None, :]) / 6
            earlier_finish = places[:, None] < places[None, :]
            for column, eligible in enumerate((same_field, cross)):
                deviation = previous[:, column]
                expected = expit(offset + deviation[:, None] - deviation[None, :])
                samples = eligible.sum(1)
                errors = (earlier_finish - expected) * eligible
                mean = np.divide(errors.sum(1), samples, out=np.zeros(len(points)), where=samples > 0)
                for reg, count, error in zip(registrations, samples, mean, strict=True):
                    if count:
                        total, starts = shifts[reg]
                        total[column] += error
                        starts[column] += 1
        for reg, (total, starts) in shifts.items():
            prior, cross = self._before_day(reg, day)
            step = np.divide(total, starts, out=np.zeros_like(total), where=starts > 0)
            self.ratings[reg] = (day, prior + .24 * step, cross or starts[1] > 0)
        self.last_day = day
