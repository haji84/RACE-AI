"""Standalone stdlib research prediction and frozen official-program contract.

Imported from the Vercel web root without race_ai or optional packages.
All models remain untrained, UNVALIDATED and ineligible for purchases.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import itertools
import json
import math
import re

class PredictionError(ValueError):
    """Missing, nonfinite, temporally unavailable or inconsistent research input."""


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])', value):
        raise PredictionError('timezone-aware ISO timestamp required')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise PredictionError('timezone-aware ISO timestamp required') from exc


def _stamp(value):
    return _time(value).isoformat(timespec='microseconds')


def _now():
    return datetime.now(timezone.utc)


def _id(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        raise PredictionError(f'invalid {name}')
    return value


def _description(value, name, maximum=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise PredictionError(f'invalid {name}')
    return value


def _number(value, name, minimum, maximum):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not minimum <= value <= maximum or not math.isfinite(value)):
        raise PredictionError(f'invalid finite {name}')
    return float(value)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PredictionError('payload must be finite reproducible JSON') from exc


def _sha(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def plackett_luce(strengths_by_lane):
    """Exact enumeration of strict top-three orders plus all six rank marginals."""
    if not isinstance(strengths_by_lane, dict) or len(strengths_by_lane) != 6:
        raise PredictionError('exactly six distinct boat strengths required')
    strengths = {}
    for lane, value in strengths_by_lane.items():
        if isinstance(lane, str) and re.fullmatch(r'[1-6]', lane):
            lane = int(lane)
        if type(lane) is not int or lane not in range(1, 7) or lane in strengths:
            raise PredictionError('boat identities must be 1..6')
        strengths[lane] = _number(value, 'strength', 1e-9, 1e9)
    if set(strengths) != set(range(1, 7)):
        raise PredictionError('boat identities must be 1..6')
    lanes = tuple(range(1, 7))

    def order_probability(order):
        remaining, probability = list(lanes), 1.0
        for lane in order:
            probability *= strengths[lane] / math.fsum(strengths[x] for x in remaining)
            remaining.remove(lane)
        return probability

    triples = [dict(combination=list(order), probability=order_probability(order))
               for order in itertools.permutations(lanes, 3)]
    mass = math.fsum(row['probability'] for row in triples)
    for row in triples:
        row['probability'] /= mass
    full = [(order, order_probability(order)) for order in itertools.permutations(lanes)]
    full_mass = math.fsum(value for _, value in full)
    positions = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth')
    marginals = []
    for lane in lanes:
        row = dict(lane=lane)
        for index, label in enumerate(positions):
            row[label + '_probability'] = math.fsum(value for order, value in full if order[index] == lane) / full_mass
        row['top3_probability'] = math.fsum(row[label + '_probability'] for label in positions[:3])
        marginals.append(row)
    return dict(triples=triples, marginals=marginals,
                strengths=[dict(lane=lane, strength=strengths[lane]) for lane in lanes])


def build_prediction(data):
    """Build an unvalidated replayable forecast from explicit pre-race evidence."""
    required = {'race_id', 'race_start_at', 'as_of', 'generated_at', 'boats', 'model_id', 'model_version', 'selection_reason'}
    if not isinstance(data, dict) or set(data) != required:
        raise PredictionError('prediction inputs require exactly the documented fields')
    race, model, version = (_id(data[key], key) for key in ('race_id', 'model_id', 'model_version'))
    reason = _description(data['selection_reason'], 'selection_reason')
    start, cutoff, generated = (_time(data[key]) for key in ('race_start_at', 'as_of', 'generated_at'))
    if not cutoff <= generated < start:
        raise PredictionError('as_of <= generated_at < race_start_at required')
    raw_boats = data['boats']
    if not isinstance(raw_boats, list) or len(raw_boats) != 6:
        raise PredictionError('exactly six boat snapshots required')
    mandatory = {'lane', 'strength', 'available_at', 'captured_at', 'generated_at', 'source_ref', 'feature_kind'}
    optional = {'racer_id', 'predicted_course', 'sample_n', 'historical_first_count'}
    boats, seen = [], set()
    for raw in raw_boats:
        if not isinstance(raw, dict) or not mandatory <= set(raw) or set(raw) - mandatory - optional:
            raise PredictionError('unsupported feature; current-race outcome features are forbidden')
        lane = raw['lane']
        if type(lane) is not int or lane not in range(1, 7) or lane in seen:
            raise PredictionError('unique boat identities 1..6 required')
        seen.add(lane)
        available, capture, source_generated = (_time(raw[key]) for key in ('available_at', 'captured_at', 'generated_at'))
        if not available <= capture <= cutoff or source_generated > cutoff:
            raise PredictionError('evidence was unavailable at prediction cutoff')
        if raw['feature_kind'] not in ('pre_race_strength', 'history_baseline', 'uniform_baseline'):
            raise PredictionError('unsupported feature kind')
        row = dict(lane=lane, strength=_number(raw['strength'], 'strength', 1e-9, 1e9),
                   available_at=_stamp(raw['available_at']), captured_at=_stamp(raw['captured_at']),
                   generated_at=_stamp(raw['generated_at']), source_ref=_description(raw['source_ref'], 'source_ref', 256),
                   feature_kind=raw['feature_kind'])
        if 'racer_id' in raw:
            if not isinstance(raw['racer_id'], str) or not re.fullmatch(r'[0-9]{4}', raw['racer_id']):
                raise PredictionError('racer_id must be four digits')
            row['racer_id'] = raw['racer_id']
        if 'predicted_course' in raw:
            if type(raw['predicted_course']) is not int or raw['predicted_course'] not in range(1, 7):
                raise PredictionError('predicted_course must be 1..6')
            row['predicted_course'] = raw['predicted_course']
        for key in ('sample_n', 'historical_first_count'):
            if key in raw:
                if type(raw[key]) is not int or not 0 <= raw[key] <= 1000000:
                    raise PredictionError('invalid history count')
                row[key] = raw[key]
        if row.get('historical_first_count', 0) > row.get('sample_n', 0):
            raise PredictionError('historical wins exceed sample count')
        boats.append(row)
    boats.sort(key=lambda row: row['lane'])
    normalized = dict(race_id=race, race_start_at=_stamp(data['race_start_at']), as_of=_stamp(data['as_of']),
                      generated_at=_stamp(data['generated_at']), boats=boats, model_id=model,
                      model_version=version, selection_reason=reason)
    distribution = plackett_luce({row['lane']: row['strength'] for row in boats})
    payload = dict(inputs=normalized, race_id=race, model_id=model, model_version=version,
                   selection_reason=reason, race_start_at=normalized['race_start_at'], as_of=normalized['as_of'],
                   generated_at=normalized['generated_at'], research_only=True, validation_status='UNVALIDATED',
                   purchase_decision='skip', purchase_recommendations=[],
                   skip_reason='prediction_accuracy_unvalidated', **distribution,
                   explanations=[dict(row, method='supplied_strength' if row['feature_kind'] != 'history_baseline'
                                      else 'smoothed_same_predicted_course_historical_first_rate') for row in boats],
                   uncertainty=dict(not_calibrated=True, method='unvalidated_strict_order_baseline',
                       missing_racer_history=[row['racer_id'] for row in boats
                                              if row.get('sample_n') == 0 and 'racer_id' in row]))
    payload['content_sha256'] = _sha(payload)
    return payload


canonical_json = _json

JST = timezone(timedelta(hours=9))
UNIFORM_MODEL = 'official-program-uniform-pl'
RATING_MODEL = 'official-program-rating-pl'
UNIFORM_REASON = 'Uniform six-boat strict-order reference; no fitted accuracy or purchase recommendation.'
RATING_REASON = ('Untrained Plackett-Luce strengths=max(B national_win_rate points,0.01); '
                 '0..10 rating points, not a first-place probability; no fitted accuracy or purchase recommendation.')


def _clock(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise PredictionError('actual timezone-aware server clock required')
    return now.astimezone(timezone.utc)


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise PredictionError('valid Japan-local program day required')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PredictionError('invalid program day') from exc


def _race_identity(race, day):
    if not isinstance(race, dict):
        raise PredictionError('current race must be an object')
    race_id = race.get('race_id')
    if not isinstance(race_id, str) or not re.fullmatch(f'{day:%Y%m%d}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])', race_id):
        raise PredictionError('race identity differs from program day')
    close = _time(race.get('closed_at'))
    if close.astimezone(JST).date() != day:
        raise PredictionError('closing time differs from program day')
    return race_id, close


def _program_boats(raw, *, frozen=False, ratings=True):
    fields = {'lane', 'racer_registration_id', 'name', 'national_win_rate'}
    if not isinstance(raw, list) or len(raw) != 6:
        raise PredictionError('six frozen program boats required')
    boats, lanes, racers = [], set(), set()
    for value in raw:
        if not isinstance(value, dict) or (frozen and set(value) != fields):
            raise PredictionError('invalid frozen program boat schema')
        lane, racer, name = value.get('lane'), value.get('racer_registration_id'), value.get('name')
        if type(lane) is not int or lane not in range(1, 7) or lane in lanes:
            raise PredictionError('unique integer boat identities 1..6 required')
        if not isinstance(racer, str) or not re.fullmatch(r'[0-9]{4}', racer) or racer in racers:
            raise PredictionError('unique four-digit registration identities required')
        if name is not None:
            _description(name, 'program name', 128)
        lanes.add(lane)
        racers.add(racer)
        rate = value.get('national_win_rate') if ratings else None
        if rate is not None:
            rate = _number(rate, 'national_win_rate points', 0, 10)
        boats.append(dict(lane=lane, racer_registration_id=racer, name=name, national_win_rate=rate))
    return sorted(boats, key=lambda row: row['lane'])


def _source(value, day):
    if not isinstance(value, dict) or set(value) != {'source_url', 'source_sha256', 'captured_at'}:
        raise PredictionError('exact frozen B program source schema required')
    expected = f'https://www1.mbrace.or.jp/od2/B/{day:%Y%m}/b{day:%y%m%d}.lzh'
    if value['source_url'] != expected:
        raise PredictionError('exact same-day official B archive source required')
    digest = value['source_sha256']
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise PredictionError('official program SHA-256 required')
    capture = _time(value['captured_at'])
    if capture.astimezone(JST).date() != day:
        raise PredictionError('B program capture day differs from snapshot day')
    return dict(source_url=expected, source_sha256=digest, captured_at=capture.isoformat(timespec='microseconds'))


def _program_models(race_id, close, asof, generated, source, boats):
    results = []
    kinds = [(UNIFORM_MODEL, UNIFORM_REASON, 'uniform_baseline', [1.0] * 6)]
    if all(row['national_win_rate'] is not None for row in boats):
        kinds.append((RATING_MODEL, RATING_REASON, 'pre_race_strength',
                      [max(row['national_win_rate'], .01) for row in boats]))
    for model_id, reason, feature_kind, strengths in kinds:
        inputs = [dict(lane=boat['lane'], racer_id=boat['racer_registration_id'], strength=strength,
            available_at=source['captured_at'], captured_at=source['captured_at'], generated_at=source['captured_at'],
            source_ref='official-b:' + source['source_sha256'], feature_kind=feature_kind)
            for boat, strength in zip(boats, strengths)]
        results.append(build_prediction(dict(race_id=race_id, race_start_at=close, as_of=asof, generated_at=generated,
            model_id=model_id, model_version='1', selection_reason=reason, boats=inputs)))
    return results


def _assemble(race_id, day, close, asof, generated, source, boats):
    bundle = dict(schema_version=1, race_id=race_id, date_jst=day.isoformat(), closed_at=close,
        as_of=asof, generated_at=generated, program_sha256=source['source_sha256'], program_source=source,
        program_boats=boats, models=_program_models(race_id, close, asof, generated, source, boats),
        research_only=True, validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[])
    try:
        bundle['snapshot_id'] = _sha(bundle)
    except (UnicodeError, OverflowError) as exc:
        raise PredictionError('bundle must be finite UTF-8 JSON') from exc
    return bundle


def build_research_bundle(feed, race, now):
    """Freeze two fixed research models from an approved current-day B program.

    `now` is supplied by the trusted server; this function accepts no client
    strengths, model IDs, probabilities, result fields or trained status.
    """
    clock = _clock(now)
    if not isinstance(feed, dict) or feed.get('redistribution_authorized') is not True:
        raise PredictionError('approved official factual feed required')
    day = _day(feed.get('date_jst'))
    if clock.astimezone(JST).date() != day:
        raise PredictionError('only the actual current Japan-local program day may be generated')
    race_id, close = _race_identity(race, day)
    if clock >= close:
        raise PredictionError('new research generation must precede official closing time')
    boats = _program_boats(race.get('boats'))
    source = _source(dict(source_url=race.get('program_source_url'), source_sha256=race.get('program_source_sha256'),
                          captured_at=race.get('program_observed_at')), day)
    if _time(source['captured_at']) > clock:
        raise PredictionError('program source was not captured by research decision time')
    sources = feed.get('sources')
    if not isinstance(sources, list) or any(not isinstance(row, dict) for row in sources):
        raise PredictionError('approved feed source collection required')
    matching = [row for row in sources if row.get('source_url') == source['source_url']]
    if (len(matching) != 1 or matching[0].get('source_sha256') != source['source_sha256']
            or _time(matching[0].get('first_observed_at')) != _time(source['captured_at'])):
        raise PredictionError('race B source does not match approved feed source proof')
    venues = feed.get('venues')
    if not isinstance(venues, list):
        raise PredictionError('approved feed race registry required')
    selected = []
    for venue in venues:
        if not isinstance(venue, dict) or not isinstance(venue.get('races'), list):
            raise PredictionError('invalid feed race registry')
        for candidate in venue['races']:
            if not isinstance(candidate, dict):
                raise PredictionError('invalid feed race registry')
            if candidate.get('race_id') == race_id:
                if venue.get('venue') != race_id[9:11]:
                    raise PredictionError('race venue conflicts with feed registry')
                selected.append(candidate)
    if len(selected) != 1:
        raise PredictionError('race missing or duplicated in approved feed')
    registered = selected[0]
    if (_race_identity(registered, day) != (race_id, close) or _program_boats(registered.get('boats')) != boats
            or any(registered.get(key) != race.get(key) for key in ('program_source_url', 'program_source_sha256', 'program_observed_at'))):
        raise PredictionError('selected race differs from approved frozen program')
    stamp = clock.isoformat(timespec='microseconds')
    return _assemble(race_id, day, close.isoformat(timespec='microseconds'), stamp, stamp, source, boats)


def validate_research_bundle(bundle, race, now):
    """Replay a trusted stored snapshot; a current rating revision is not its input.

    Validation may happen after closing for receipt display. The writer must
    separately require its actual cloud save to finish before closing.
    A hash is integrity evidence, not a signature authenticating arbitrary input.
    """
    fields = {'schema_version', 'race_id', 'date_jst', 'closed_at', 'as_of', 'generated_at', 'program_sha256',
              'program_source', 'program_boats', 'models', 'research_only', 'validation_status',
              'purchase_decision', 'purchase_recommendations', 'snapshot_id'}
    if not isinstance(bundle, dict) or set(bundle) != fields or type(bundle.get('schema_version')) is not int or bundle['schema_version'] != 1:
        raise PredictionError('exact supported research bundle schema required')
    clock, day = _clock(now), _day(bundle['date_jst'])
    race_id, close = _race_identity(race, day)
    if bundle['race_id'] != race_id or _time(bundle['closed_at']) != close:
        raise PredictionError('saved research race/cutoff differs from current race identity')
    boats = _program_boats(bundle['program_boats'], frozen=True)
    current = _program_boats(race.get('boats'), ratings=False)
    identity = lambda row: (row['lane'], row['racer_registration_id'], row['name'])
    if [identity(row) for row in boats] != [identity(row) for row in current]:
        raise PredictionError('saved program roster differs from current race identity')
    source = _source(bundle['program_source'], day)
    asof, generated = _time(bundle['as_of']), _time(bundle['generated_at'])
    if (not _time(source['captured_at']) <= asof <= generated < close or generated > clock
            or asof.astimezone(JST).date() != day or generated.astimezone(JST).date() != day):
        raise PredictionError('research snapshot phase or source chronology is invalid')
    expected = _assemble(race_id, day, close.isoformat(timespec='microseconds'),
        asof.isoformat(timespec='microseconds'), generated.isoformat(timespec='microseconds'), source, boats)
    try:
        if _json(bundle) != _json(expected):
            raise PredictionError('research payload/hash/models differ from deterministic frozen-program replay')
    except (UnicodeError, OverflowError) as exc:
        raise PredictionError('research bundle must be finite UTF-8 JSON') from exc
    return expected
