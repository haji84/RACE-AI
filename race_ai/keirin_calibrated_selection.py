"""Select odds-facing research sets and grade calibrated set probabilities."""

from dataclasses import dataclass
from datetime import datetime
from math import fsum, isfinite
from numbers import Real

from .keirin_joint_finish import JointFinish
from .keirin_nationwide_auto_generator import VENUE, digest, when
from .keirin_nationwide_forecast_view import JST
from .keirin_paired_measurement import _wilson
from .keirin_public_forecast_odds import checked


POLICY = 'KEIRIN_RESEARCH_SET_SELECTION_V1'
MAX_ODDS_AGE_SECONDS = 300
MIN_INCREMENTAL_PROBABILITY = .01
MIN_CALIBRATION_RACES = 30
MIN_CALIBRATION_DAYS = 3
MAX_CALIBRATION_GAP = .10
GRADES = ((.90, 'VERY_HIGH'), (.80, 'HIGH'), (.60, 'MEDIUM'), (0., 'LOW'))


def _trifecta_cap(odds):
    if odds <= 10:
        return 2
    if odds <= 20:
        return 4
    if odds < 100:
        return 9
    return 12


def _rank(probabilities):
    return sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))


def _ticket(order):
    return '-'.join(map(str, order))


def _jst_day(clock):
    return clock.astimezone(JST).strftime('%Y%m%d')


def _race_clock(race_id, value):
    clock = when(value)
    if type(race_id) is not str or not VENUE.fullmatch(race_id) or _jst_day(clock) != race_id[:8]:
        raise ValueError('Race identity and JST clock must match.')
    return clock


def _odds_row(archive, race_id, decision, trifectas):
    if archive is None:
        return None, 'HOLD_ODDS_MISSING'
    try:
        checked(archive)
    except (KeyError, TypeError, ValueError):
        return None, 'HOLD_ODDS_INVALID'
    row = next((item for item in archive['races'] if item['race_id'] == race_id), None)
    if row is None:
        return None, 'HOLD_ODDS_RACE_MISSING'
    if when(archive['published_at']) > decision:
        return None, 'HOLD_ODDS_NOT_AVAILABLE_AS_OF'
    if any(quote < 1 for quote in row['quotes'].values()):
        return None, 'HOLD_ODDS_INVALID'
    if row['quotes'].keys() - {_ticket(order) for order in trifectas}:
        return None, 'HOLD_ODDS_STARTERS_MISMATCH'
    age = (decision - when(row['source_at'])).total_seconds()
    if age > MAX_ODDS_AGE_SECONDS:
        return None, 'HOLD_ODDS_STALE'
    return (row, age), None


def select_research(joint, *, race_id, forecast_at, cutoff_at, odds_archive):
    """Score a fixed probability-ranked slate against a single archived odds receipt.

    The caller supplies the validated race law and its independently admitted cutoff.
    Archived odds are for research selection, and never enter the probability law.
    """
    if not isinstance(joint, JointFinish):
        raise ValueError('A validated JointFinish law is required.')
    cutoff = _race_clock(race_id, cutoff_at)
    decision = when(forecast_at)
    trifectas = joint.trifectas()
    starters = {car for order in trifectas for car in order}
    if len(starters) < 5:
        raise ValueError('Expected a KEIRIN field of five to nine starters.')
    ranked = _rank(trifectas)
    favorite, probability = ranked[0]
    result = dict(policy=POLICY, scope='RESEARCH_ONLY', race_id=race_id,
                  forecast_at=forecast_at, cutoff_at=cutoff_at,
                  favorite=dict(order=favorite, probability=probability),
                  exacta=dict(status='HOLD_EXACTA_ODDS_UNAVAILABLE', cap=2,
                              probability_reference=[dict(order=order, probability=mass)
                                                     for order, mass in _rank(joint.exactas())[:2]
                                                     if mass > 0]))
    trifecta = result['trifecta'] = dict(cap=None, picks=[], set_probability=None)
    if decision >= cutoff:
        trifecta['status'] = 'HOLD_RACE_CUTOFF'
        return result
    odds, failure = _odds_row(odds_archive, race_id, decision, trifectas)
    if failure:
        trifecta['status'] = failure
        return result
    row, age = odds
    quotes = row['quotes']
    result['odds_evidence'] = dict(source_url=row['source_url'], source_at=row['source_at'],
                                   observed_at=row['observed_at'], published_at=odds_archive['published_at'],
                                   age_seconds=age, archive_sha256=digest(odds_archive))
    favorite_odds = quotes.get(_ticket(favorite))
    if favorite_odds is None:
        trifecta['status'] = 'HOLD_ODDS_FAVORITE_MISSING'
        return result
    cap = _trifecta_cap(favorite_odds)
    slate = [(order, mass) for order, mass in ranked[:cap] if mass > 0]
    trifecta.update(cap=cap, favorite_odds=favorite_odds, candidates=len(slate))
    if any(_ticket(order) not in quotes for order, _ in slate):
        trifecta['status'] = 'HOLD_ODDS_CANDIDATES_MISSING'
        return result

    # Discount the quote by 5–10% across the approved age window for drift.
    # Disjoint finishing orders contribute their own mass to any selected set.
    multiplier = .95 - .05 * (age / MAX_ODDS_AGE_SECONDS)
    picks = trifecta['picks']
    for order, mass in slate:
        quote = quotes[_ticket(order)]
        conservative_ev = mass * quote * multiplier - 1.
        if mass < MIN_INCREMENTAL_PROBABILITY or conservative_ev <= 0:
            continue
        cumulative = fsum([mass, *(item['marginal_probability'] for item in picks)])
        picks.append(dict(order=order, marginal_probability=mass, set_probability_after=cumulative,
                          odds=quote, fair_odds=1 / mass, conservative_ev=conservative_ev))
    trifecta.update(status='RESEARCH_SELECTION' if picks else 'HOLD_NO_QUALIFYING_TICKET',
                    set_probability=fsum(item['marginal_probability'] for item in picks),
                    conservative_ev_per_point=fsum(item['conservative_ev'] for item in picks) / len(picks) if picks else None,
                    odds_multiplier=multiplier)
    return result


def _probability(value):
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Expected a finite probability in [0, 1].')
    return float(value)


def _band(probability):
    return next((threshold, grade) for threshold, grade in GRADES if probability >= threshold)


@dataclass(frozen=True)
class CalibrationObservation:
    """One previously frozen set probability with a subsequently observed outcome."""

    race_id: str
    forecast_at: str
    result_available_at: str
    probability: float
    hit: bool


@dataclass(frozen=True)
class CalibrationEvidence:
    """Per-race evidence for a single frozen model, market and set policy series."""

    series: str
    trained_through: datetime
    observations: tuple[CalibrationObservation, ...]


def calibration_evidence(observations, *, series, trained_through):
    """Collect independent out-of-time rows; the caller admits source and result identities."""
    if type(series) is not str or not series.strip():
        raise ValueError('A model, market and selection policy series is required.')
    fitted = when(trained_through)
    rows = tuple(observations)
    seen = set()
    for row in rows:
        if not isinstance(row, CalibrationObservation):
            raise ValueError('Expected an individual calibration observation.')
        _probability(row.probability)
        forecast = _race_clock(row.race_id, row.forecast_at)
        if row.race_id in seen or type(row.hit) is not bool or not fitted < forecast < when(row.result_available_at):
            raise ValueError('Calibration requires distinct out-of-time races and later result observations.')
        seen.add(row.race_id)
    return CalibrationEvidence(series, fitted, rows)


def grade_confidence(probability, *, series, at, evidence=None):
    """Grade a calibrated set probability after temporal, sample and calibration checks."""
    probability = _probability(probability)
    now = when(at)
    result = dict(series=series, probability=probability, grade=None, n=0, days=0)
    if not isinstance(evidence, CalibrationEvidence) or evidence.series != series:
        return dict(result, status='HOLD_CALIBRATION_SERIES_MISSING')
    result['trained_through'] = evidence.trained_through.isoformat()
    historical = [row for row in evidence.observations
                  if evidence.trained_through < when(row.forecast_at) < when(row.result_available_at) < now]
    if not historical:
        return dict(result, status='HOLD_CALIBRATION_OUT_OF_TIME_MISSING')
    threshold, grade = _band(probability)
    rows = [row for row in historical if _band(row.probability) == (threshold, grade)]
    days = len({row.race_id[:8] for row in rows})
    result.update(n=len(rows), days=days, out_of_time_races=len(historical), grade_threshold=threshold)
    if len(rows) < MIN_CALIBRATION_RACES or days < MIN_CALIBRATION_DAYS:
        return dict(result, status='HOLD_CALIBRATION_INSUFFICIENT')
    hits = sum(row.hit for row in rows)
    observed = hits / len(rows)
    predicted = fsum(row.probability for row in rows) / len(rows)
    lower, upper = _wilson(hits, len(rows), 1.959963984540054)
    result.update(observed_hits=hits, observed_rate=observed, mean_probability=predicted,
                  latest_result_available_at=max(when(row.result_available_at) for row in rows).isoformat(),
                  observed_rate_ci95=(lower, upper))
    if observed < threshold:
        return dict(result, status='HOLD_CALIBRATION_HIT_RATE_TARGET')
    if grade in ('VERY_HIGH', 'HIGH') and lower < threshold:
        return dict(result, status='HOLD_CALIBRATION_WILSON_LOWER_TARGET')
    if abs(observed - predicted) > MAX_CALIBRATION_GAP or not lower <= predicted <= upper:
        return dict(result, status='HOLD_CALIBRATION_ERROR')
    return dict(result, status='GRADED', grade=grade)
