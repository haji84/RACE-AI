"""Fit and validate exact-point public shortlist confidence on earlier dates."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import NormalDist
import re

from . import keirin_calibrated_selection as calibration
from .keirin_nationwide_auto_generator import VENUE, when
from .keirin_nationwide_forecast_view import JST
from .keirin_paired_measurement import _wilson


SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_SHORTLIST_CONFIDENCE_V1'
LANES = ('official', 'reference', 'racecard')
ARMS = ('A', 'B')
MIN_FIT_RACES, MIN_FIT_DAYS = 20, 3
Z95 = NormalDist().inv_cdf(.975)


@dataclass(frozen=True)
class ShortlistObservation:
    """A genuine frozen shortlist and its separately admitted settled hit."""

    lane: str
    arm: str
    race_id: str
    points: int
    forecast_at: str
    cutoff_at: str
    result_at: str
    hit: bool


def _summary(rows):
    return dict(n=len(rows), hits=sum(row.hit for row in rows),
                days=len({row.race_id[:8] for row in rows}))


def _evaluate(key, fit, validation, *, fit_end, assessment):
    lane, arm, points = key
    row = dict(lane=lane, arm=arm, points=points, fit=_summary(fit), validation=_summary(validation),
               state='HOLD_CALIBRATION_FIT_INSUFFICIENT', probability=None, grade=None,
               ci95=_wilson(sum(item.hit for item in validation), len(validation), Z95))
    if row['fit']['n'] < MIN_FIT_RACES or row['fit']['days'] < MIN_FIT_DAYS:
        return row
    # A single constant per model lane, arm and point count. Fit frequencies
    # are unsmoothed and published only after the separate validation gate.
    frequency = row['fit']['hits'] / row['fit']['n']
    series = f'{lane}/{arm}/trifecta/{points}'
    evidence = calibration.calibration_evidence(
        (calibration.CalibrationObservation(item.race_id, item.forecast_at, item.result_at,
                                            frequency, item.hit, cutoff_at=item.cutoff_at)
         for item in validation), series=series, trained_through=fit_end.isoformat())
    outcome = calibration.grade_confidence(frequency, series=series, at=assessment, evidence=evidence)
    row.update(state=outcome['status'], grade=outcome['grade'],
               probability=frequency if outcome['status'] == 'GRADED' else None)
    return row


def build(observations, *, day, assessed_at, archive_commit):
    """Group admitted hit observations without importing outcomes or forecasts.

    The fitting dates are target minus 10 through minus 4 in JST. Fitting
    results precede validation midnight. Validation uses only forecasts after
    that boundary and outcomes available strictly before the target day and
    assessment. Race grouping follows the official or reference cutoff date,
    including a shortlist captured the previous evening.
    """
    target = date.fromisoformat(day)
    if day != target.isoformat() or not re.fullmatch(r'[0-9a-f]{40}', archive_commit):
        raise ValueError('PUBLIC_CONFIDENCE_TARGET_OR_ARCHIVE_PIN')
    assessment = when(assessed_at)
    fit_start, fit_last, validation_start, validation_last = (
        target - timedelta(days=offset) for offset in (10, 4, 3, 1))
    fit_end = datetime.combine(validation_start, time.min, JST)
    validation_end = min(assessment, datetime.combine(target, time.min, JST))
    fitting, verifying = defaultdict(list), defaultdict(list)
    seen, groups = set(), set()
    for item in observations:
        if (not isinstance(item, ShortlistObservation) or item.lane not in LANES or item.arm not in ARMS or
                type(item.points) is not int or not 1 <= item.points <= 8 or type(item.hit) is not bool or
                type(item.race_id) is not str or not VENUE.fullmatch(item.race_id) or
                not 1 <= int(item.race_id[-2:]) <= 12):
            raise ValueError('PUBLIC_CONFIDENCE_OBSERVATION')
        forecast, cutoff, result = map(when, (item.forecast_at, item.cutoff_at, item.result_at))
        race_day = cutoff.astimezone(JST).date()
        if race_day.strftime('%Y%m%d') != item.race_id[:8]:
            raise ValueError('PUBLIC_CONFIDENCE_RACE_DAY')
        key = item.lane, item.arm, item.points
        identity = key, item.race_id
        if identity in seen:
            raise ValueError('PUBLIC_CONFIDENCE_DUPLICATE')
        seen.add(identity)
        if not fit_start <= race_day <= validation_last:
            continue
        groups.add(key)
        if not forecast < cutoff < result:
            continue
        if race_day <= fit_last and result < min(fit_end, assessment):
            fitting[key].append(item)
        elif race_day >= validation_start and fit_end < forecast and result < validation_end:
            verifying[key].append(item)
    return dict(schema=SCHEMA, day=day, assessed_at=assessed_at, archive_commit=archive_commit,
                training_window=[fit_start.isoformat(), fit_last.isoformat()],
                validation_window=[validation_start.isoformat(), validation_last.isoformat()],
                rows=[_evaluate(key, fitting[key], verifying[key], fit_end=fit_end, assessment=assessed_at)
                      for key in sorted(groups)])
