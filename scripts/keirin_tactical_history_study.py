"""Earlier finish methods, named matchups and observed race movement for keirin research."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np

from scripts.keirin_line_event_study import race_layout
from scripts.keirin_rider_profile_history import is_registration


METHOD_WIDTH = 7
PHASE_WIDTH = 12
MATCHUP_WIDTH = 11
METHOD_DENOMINATORS = np.array([0, 0, 0, 1, 1, 1, 1])


def check_methods(methods):
    if any(type(code) is not int or not 0 <= code < limit
           for code, limit in zip(methods, (3, 4), strict=True) if code is not None):
        raise ValueError('Invalid observed finish method.')


def record_methods(count, rank, methods):
    winning, second = methods
    count[:2] += (winning is not None, second is not None)
    if winning is not None and rank == 0:
        count[2+winning] += 1
    if second is not None and rank == 1:
        count[5+second] += 1


def record_matchup(pair, rank, rival_rank, methods):
    winning, second = methods
    second_known = second is not None and rival_rank == 0
    pair[0] += winning is not None
    pair[1] += second_known
    if winning is not None and rank == 0:
        pair[2+winning] += 1
    if second_known and rank == 1:
        pair[5+second] += 1
    pair[9] += 1
    pair[10] += rank < rival_rank


@dataclass(frozen=True)
class TacticalFeatures:
    methods: np.ndarray
    matchups: np.ndarray
    movement: np.ndarray
    following: np.ndarray
    matchup_starts: np.ndarray


class TacticalHistory:
    def __init__(self):
        self.last_day = None
        self.seen = set()
        self.methods = defaultdict(lambda: np.zeros(9, dtype=np.int32))
        self.role_methods = defaultdict(lambda: np.zeros(9, dtype=np.int32))
        self.matchups = defaultdict(lambda: np.zeros(11, dtype=np.int32))
        self.phases = defaultdict(lambda: np.zeros((6, 2), dtype=np.int32))
        self.notes = defaultdict(lambda: np.zeros(6, dtype=np.int32))
        self.following = defaultdict(lambda: np.zeros(2, dtype=np.int32))

    def _check_day(self, day):
        if self.last_day is not None and day < self.last_day:
            raise ValueError('Tactical observations must arrive in calendar order.')

    def observe(self, snapshot, finish, *, methods, phase):
        day, cars, registrations, positions = race_layout(snapshot)
        self._check_day(day)
        if snapshot['race_id'] in self.seen or sorted(finish) != cars:
            raise ValueError('Require one complete result for the published starters.')
        check_methods(methods)
        start, home, back = phase
        if any(car is not None and car not in cars for car in phase):
            raise ValueError('A phase leader must be a member of the field.')

        winner = finish[0]
        ranks = {car: rank for rank, car in enumerate(finish)}
        for car,rider in zip(cars,registrations,strict=True):
            if rider is None:
                continue
            line, role = positions[car]
            record_methods(self.methods[rider], ranks[car], methods)
            record_methods(self.role_methods[rider, role], ranks[car], methods)

            evidence = (
                car == start if start is not None else None,
                car == home if home is not None else None,
                car == back if back is not None else None,
                car == back and home != back if home is not None and back is not None else None,
                car == back and line != positions[home][0] if home is not None and back is not None else None,
                car == winner if car == back else None,
            )
            phase_counts = self.phases[rider, role]
            for index,value in enumerate(evidence):
                if value is not None:
                    phase_counts[index] += (1,value)

            for rival_car,rival in zip(cars,registrations,strict=True):
                if rival is None or rival_car == car:
                    continue
                pair = self.matchups[rider,rival,line == positions[rival_car][0]]
                record_matchup(pair, ranks[car], ranks[rival_car], methods)
        self.seen.add(snapshot['race_id'])
        self.last_day = day

    def observe_archive(self, race_id, finish, *, methods):
        """Use exact registered finishes when the archive has no line groups."""
        day = date.fromisoformat(race_id[:8])
        self._check_day(day)
        bound = [(rank, rider) for rank, rider in enumerate(finish) if rider is not None]
        if (race_id in self.seen or not 5 <= len(finish) <= 9
                or any(not is_registration(rider) for _, rider in bound)
                or len({rider for _, rider in bound}) != len(bound)):
            raise ValueError('Require a new, unambiguous archived roster and finish.')
        check_methods(methods)
        for rank, rider in bound:
            record_methods(self.methods[rider], rank, methods)
            for rival_rank, rival in bound:
                if rival != rider:
                    record_matchup(self.matchups[rider, rival, None], rank, rival_rank, methods)
        self.seen.add(race_id)
        self.last_day = day

    def observe_report(self, published_day, actions, contacts):
        self._check_day(published_day)
        if any(not is_registration(rider) or type(phase) is not int or not 0 <= phase < 6
               for rider,phase in actions):
            raise ValueError('A reported action requires an identified rider and known phase.')
        if any(not is_registration(lead) or not is_registration(follower) or lead == follower or type(held) is not bool
               for lead,follower,held in contacts):
            raise ValueError('A following record requires an identified pair and observed result.')

        for rider,phase in set(map(tuple,actions)):
            self.notes[rider][phase] += 1
        for lead,follower,held in contacts:
            self.following[follower,lead] += (1,held)
        self.last_day = published_day

    def features(self, snapshot):
        day, cars, registrations, positions = race_layout(snapshot)
        if self.last_day is not None and self.last_day >= day:
            raise ValueError('Forecast history must end on earlier days.')
        count = len(cars)
        individual = np.zeros((count, 18))
        matchups = np.zeros((count, count, MATCHUP_WIDTH))
        matchup_starts = np.zeros((count, count), dtype=int)
        movement = np.zeros((count, PHASE_WIDTH+7))
        following = np.zeros((count,count,2))
        for i,(car,rider) in enumerate(zip(cars,registrations,strict=True)):
            if rider is None:
                continue
            line,role = positions[car]
            overall = self.methods.get(rider)
            specific = self.role_methods.get((rider,role))
            if overall is not None:
                rate = overall[2:]/(overall[METHOD_DENOMINATORS]+8)
                individual[i,:METHOD_WIDTH] = rate
                individual[i,7:9] = overall[:2]/(overall[:2]+8)
                if specific is not None:
                    trials = specific[METHOD_DENOMINATORS]
                    individual[i,9:16] = (specific[2:]-trials*rate)/(trials+8)
                    individual[i,16:] = specific[:2]/(specific[:2]+8)
            known = self.phases.get((rider,role))
            if known is not None:
                movement[i,:6] = known[:,1]/(known[:,0]+8)
                movement[i,6:PHASE_WIDTH] = known[:,0]/(known[:,0]+8)
            noted = self.notes.get(rider)
            if noted is not None:
                total = noted.sum()
                movement[i,PHASE_WIDTH:-1] = noted/(total+4)
                movement[i,-1] = total/(total+4)
            for j,(rival_car,rival) in enumerate(zip(cars,registrations,strict=True)):
                rival_line,rival_role = positions[rival_car]
                same = line == rival_line
                prior = self.matchups.get((rider,rival,same))
                without_line = self.matchups.get((rider,rival,None))
                shrinkage = 8
                if prior is None:
                    prior = without_line
                    shrinkage = 16
                if prior is not None:
                    trials = prior[METHOD_DENOMINATORS]
                    matchups[i,j,:METHOD_WIDTH] = (prior[2:9]-trials*individual[i,:METHOD_WIDTH])/(trials+shrinkage)
                    matchups[i,j,7:9] = prior[:2]/(prior[:2]+shrinkage)
                    matchups[i,j,9] = (prior[10]-.5*prior[9])/(prior[9]+shrinkage)
                    matchups[i,j,10] = prior[9]/(prior[9]+shrinkage)
                    matchup_starts[i,j] = prior[9]
                    if prior[1] == 0 and without_line is not None and without_line[1]:
                        second_trials = without_line[1]
                        matchups[i,j,3:METHOD_WIDTH] = (
                            without_line[5:9] - second_trials*individual[i,3:METHOD_WIDTH])/(second_trials+16)
                        matchups[i,j,8] = second_trials/(second_trials+16)
                if same and role > rival_role:
                    paired = self.following.get((rider,rival))
                    if paired is not None:
                        following[i,j] = ((paired[1]-.5*paired[0])/(paired[0]+4),paired[0]/(paired[0]+4))
        return TacticalFeatures(individual,matchups,movement,following,matchup_starts)
