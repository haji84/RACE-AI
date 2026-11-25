"""Build dated, registration-bound features from public KEIRIN result records."""

from bisect import bisect_left, bisect_right
from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from math import isfinite, log
import re

import numpy as np


ROLES = ('LEAD', 'SECOND', 'REAR', 'SOLO')
GRADES = ('S', 'A', 'L')
METHODS = ('escape', 'makuri', 'sashi', 'mark')
METRICS = ('win', 'second', 'third', 'speed', *METHODS, 's', 'b')
FORM_FIELDS = (
    'overall_win', 'overall_second', 'overall_third', 'recent_win_change',
    'recent_top2_change', 'overall_speed', 'escape', 'makuri', 'sashi',
    'mark', 's', 'b', 'days_since_start',
)
CONTEXT_FIELDS = (
    'role_win', 'role_second', 'role_third', 'role_speed', 'role_s', 'role_b',
    'role_front_method', 'track_top3', 'track_speed', 'grade_top3',
)


def grade_family(racer_class):
    initial = str(racer_class or '').strip().upper()[:1]
    return initial if initial in GRADES else None


def is_registration(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9]{6}', value) is not None


def expected_finish(scores):
    """Derive a field-strength reference for the first three places using pre-race points."""
    points = np.asarray(scores, dtype=float)
    if points.ndim != 1 or not 3 <= len(points) <= 9 or not np.all(np.isfinite(points)):
        raise ValueError('A score is required for every starter in the reference field.')
    if np.any((points < 1) | (points > 150)):
        raise ValueError('Historical competition points are out of range.')
    strengths = np.exp((points - points.max()) / 8.0)
    first = strengths / strengths.sum()
    other = ~np.eye(len(first), dtype=bool)
    available_second = np.where(other, strengths, 0)
    second_given_first = available_second / available_second.sum(axis=1, keepdims=True)
    pair = first[:, None] * second_given_first
    second = pair.sum(axis=0)
    available_third = np.where(other[:, None, :] & other[None, :, :], strengths, 0)
    third_given_pair = available_third / available_third.sum(axis=2, keepdims=True)
    third = (pair[:, :, None] * third_given_pair).sum(axis=(0, 1))
    return np.column_stack((first, second, third))


@dataclass(frozen=True, slots=True)
class Ride:
    race_id: str
    registration: str
    finish: int
    expected: tuple[float, float, float] | None
    role: str | None
    grade: str | None
    speed: float | None = None
    method: str | None = None
    method_known: bool = False
    s: bool | None = None
    b: bool | None = None

    def __post_init__(self):
        if (not re.fullmatch(r'[0-9]{12}', self.race_id) or not is_registration(self.registration)
                or type(self.finish) is not int or not 1 <= self.finish <= 9):
            raise ValueError('An observation needs a bound registration, race and numeric finish.')
        date.fromisoformat(self.race_id[:8])
        if self.role not in (*ROLES, None) or self.grade not in (*GRADES, None):
            raise ValueError('Unknown historical role or grade.')
        if (self.expected is not None and
                (len(self.expected) != 3 or not all(0 <= value <= 1 for value in self.expected))):
            raise ValueError('Invalid probabilities for an observed past field.')
        if self.speed is not None and (not isfinite(self.speed) or abs(self.speed) > 1):
            raise ValueError('Relative finishing speed must be finite and bounded.')
        if self.method is not None and (self.method not in METHODS or not self.method_known):
            raise ValueError('Unknown or unconfirmed finishing method.')
        if any(value is not None and type(value) is not bool for value in (self.s, self.b)):
            raise ValueError('Historical S/B can only be observed true, false or missing.')

    def metrics(self):
        finish = ([float(self.finish == index) - expected
                   for index, expected in enumerate(self.expected, 1)]
                  if self.expected is not None else [None] * 3)
        methods = [float(self.method == method) if self.method_known else None for method in METHODS]
        return (*finish, self.speed, *methods, self.s, self.b)


class HistorySeries:
    def __init__(self, observations):
        self.days, values = zip(*observations)
        matrix = np.asarray(values, dtype=float)
        known = np.isfinite(matrix)
        self.totals = np.vstack((np.zeros(len(METRICS)), np.cumsum(np.where(known, matrix, 0), axis=0)))
        self.counts = np.vstack((np.zeros(len(METRICS), dtype=int), np.cumsum(known, axis=0)))

    def window(self, cutoff, lookback):
        right = bisect_left(self.days, cutoff)
        left = bisect_left(self.days, cutoff - lookback, hi=right)
        return (self.totals[right] - self.totals[left], self.counts[right] - self.counts[left],
                right-left, self.days[right-1] if right else None)


EMPTY_WINDOW = np.zeros(len(METRICS)), np.zeros(len(METRICS)), 0, None
FINISH_PERIODS = {'all': None, '3_years': 36, '1_year': 12, '6_months': 6,
                  '4_months': 4, '3_months': 3, '1_month': 1}
FINISH_START_COUNTS = (30, 20, 10, 5)


def _history_cutoff(race_id, latest_day):
    cutoff = date.fromisoformat(race_id[:8]).toordinal()
    if latest_day is not None:
        cutoff = min(cutoff, date.fromisoformat(latest_day).toordinal() + 1)
    return date.fromordinal(cutoff)


def _months_before(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    if year < date.min.year:
        return date.min
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def _matching_finishes(rows, filters):
    matched = []
    known_nonmatch = undetermined = 0
    missing = dict.fromkeys(filters, 0)
    for row in rows:
        race_id, _, role, grade = row
        track_code = race_id[8:10]
        observed = dict(track_code=track_code if track_code != '00' else None, role=role, grade=grade)
        incomplete = different = False
        for field, required in filters.items():
            value = observed[field]
            if value is None:
                missing[field] += 1
                incomplete = True
            elif value != required:
                different = True
        if different:
            known_nonmatch += 1
        elif incomplete:
            undetermined += 1
        else:
            matched.append(row)
    return matched, dict(examined_count=len(rows), matched_count=len(matched),
                         known_nonmatch_count=known_nonmatch, undetermined_count=undetermined,
                         missing_by_field=missing)


class HistoryBook:
    """Keep independently dated series, so a query cannot consume a same-day result."""

    def __init__(self, rides):
        history = defaultdict(list)
        finishes = defaultdict(list)
        seen = set()
        for ride in rides:
            key = ride.registration, ride.race_id
            if key in seen:
                raise ValueError('Repeated rider and race in prior history.')
            seen.add(key)
            observation = date.fromisoformat(ride.race_id[:8]).toordinal(), ride.metrics()
            finishes[ride.registration].append((ride.race_id, ride.finish, ride.role, ride.grade))
            history[ride.registration, 'all', None].append(observation)
            history[ride.registration, 'track', ride.race_id[8:10]].append(observation)
            if ride.role is not None:
                history[ride.registration, 'role', ride.role].append(observation)
            if ride.grade is not None:
                history[ride.registration, 'grade', ride.grade].append(observation)
        self.series = {
            key: HistorySeries(sorted(values, key=lambda row: row[0])) for key, values in history.items()
        }
        self.finishes = {registration: tuple(sorted(rows)) for registration, rows in finishes.items()}

    def finish_history(self, registration, *, race_id, latest_day=None, track_code=None, role=None, grade=None):
        """Summarize bound numeric finishes available in the archive strictly before the cutoff day.

        The archive can omit starts entirely, so the count of missing finishes is unknown.
        Last-N windows use observable finishes and omit a boundary day if its order is unknown.
        Optional filters intersect all known matching fields before forming any of the windows.
        Filter coverage counts examined earlier finishes, including each requested field's missing values.
        Historical prediction callers must use the archive revision available at their cutoff.
        """
        if not is_registration(registration):
            raise ValueError('A rider registration is required for a finish history.')
        if track_code is not None and (not isinstance(track_code, str) or track_code == '00'
                                       or not re.fullmatch(r'[0-9]{2}', track_code)):
            raise ValueError('A track filter requires an observed two-digit venue code.')
        if role not in (*ROLES, None) or grade not in (*GRADES, None):
            raise ValueError('Unknown historical role or grade filter.')
        cutoff = _history_cutoff(race_id, latest_day)
        rows = self.finishes.get(registration, ())
        right = bisect_left(rows, (cutoff.isoformat().replace('-', ''),))
        filters = {field: value for field, value in dict(track_code=track_code, role=role, grade=grade).items()
                   if value is not None}
        if filters:
            rows, coverage = _matching_finishes(rows[:right], filters)
            right = len(rows)

        def summary(left):
            observed = right - left
            counts = Counter(row[1] for row in rows[left:right])
            counts = {rank: counts[rank] for rank in range(1, 10)}
            return dict(observed_count=observed, missing_finish_count=None, finish_counts=counts,
                        finish_rates={rank: count / observed for rank, count in counts.items()} if observed else None,
                        first_observed_day=date.fromisoformat(rows[left][0][:8]).isoformat() if observed else None,
                        latest_observed_day=date.fromisoformat(rows[right - 1][0][:8]).isoformat() if observed else None)

        periods = {}
        for name, months in FINISH_PERIODS.items():
            start = _months_before(cutoff, months) if months is not None else None
            left = bisect_left(rows, (start.isoformat().replace('-', ''),), hi=right) if start else 0
            periods[name] = dict(summary(left), start_day_inclusive=start.isoformat() if start else None)

        last_starts = {}
        for count in FINISH_START_COUNTS:
            left = max(0, right - count)
            tied = 0
            if left and rows[left - 1][0][:8] == rows[left][0][:8]:
                day = rows[left][0][:8]
                start = bisect_left(rows, (day,), hi=left)
                left = bisect_right(rows, day, lo=left, hi=right, key=lambda row: row[0][:8])
                tied = left - start
            last_starts[count] = dict(summary(left), unfilled_slots=count - (right - left),
                                      tied_boundary_observations=tied)

        report = dict(registration=registration, as_of_exclusive=cutoff.isoformat(),
                      periods=periods, last_starts=last_starts)
        if filters:
            report.update(filters=filters, filter_coverage=coverage)
        return report

    def features(self, registration, *, race_id, role, grade, latest_day=None):
        cutoff = _history_cutoff(race_id, latest_day).toordinal()

        def window(kind, tag, lookback):
            series = self.series.get((registration, kind, tag))
            return series.window(cutoff, lookback) if series is not None else EMPTY_WINDOW

        total, count, career_n, last_day = window('all', None, 365)
        recent_total, recent_count, recent_n, _ = window('all', None, 60)
        role_total, role_count, role_n, _ = window('role', role, 365)
        track_total, track_count, track_n, _ = window('track', race_id[8:10], 365)
        grade_total, grade_count, grade_n, _ = window('grade', grade, 365)

        career = total / (count + 12)
        recent = (recent_total - recent_count * career) / (recent_count + 12)
        # Role, venue and class contribute a conditional departure from the rider's overall history.
        by_role = (role_total - role_count * career) / (role_count + 18)
        by_track = (track_total - track_count * career) / (track_count + 18)
        by_grade = (grade_total - grade_count * career) / (grade_count + 18)
        gap = min(log(cutoff - last_day) / log(120), 1.0) if last_day is not None else 0.0
        form = (*career[:3], recent[0], recent[:2].sum(), *career[3:], gap)
        context = (*by_role[:4], by_role[8], by_role[9], by_role[4:6].sum(),
                   by_track[:3].sum(), by_track[3], by_grade[:3].sum())
        counts = dict(career=career_n, recent=recent_n, role=role_n, track=track_n, grade=grade_n)
        return dict(zip((*FORM_FIELDS, *CONTEXT_FIELDS), map(float, (*form, *context)), strict=True)), counts
