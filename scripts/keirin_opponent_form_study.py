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
