"""Interpretable research baseline and immutable, as-of-safe evaluation.

No fitted accuracy or live purchase recommendation is claimed. Ranking
probabilities describe strict orders; ties/cancellations are reported exclusions.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import sqlite3
from datetime import datetime, timezone

from .core import SourceError, summarize, utc
from .money import MoneyError, settle_bets


class PredictionError(ValueError):
    """Missing, nonfinite, temporally unavailable or inconsistent research input."""


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])', value):
        raise PredictionError('timezone-aware ISO timestamp required')
    try:
        utc(value)  # Reuse existing timezone-required validation, retaining fractions below.
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


SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_versions (
 version_id TEXT PRIMARY KEY, race_id TEXT NOT NULL, model_id TEXT NOT NULL,
 model_version TEXT NOT NULL, as_of TEXT NOT NULL, generated_at TEXT NOT NULL,
 saved_at TEXT NOT NULL, race_start_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS prediction_race_model ON prediction_versions(race_id,model_id,generated_at);
CREATE TABLE IF NOT EXISTS result_revisions (
 revision_id TEXT PRIMARY KEY, race_id TEXT NOT NULL, revision_no INTEGER NOT NULL,
 available_at TEXT NOT NULL, captured_at TEXT NOT NULL, saved_at TEXT NOT NULL,
 supersedes_id TEXT, payload_json TEXT NOT NULL, UNIQUE(race_id,revision_no)
);
CREATE TRIGGER IF NOT EXISTS prediction_no_update BEFORE UPDATE ON prediction_versions
 BEGIN SELECT RAISE(ABORT,'prediction versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prediction_no_delete BEFORE DELETE ON prediction_versions
 BEGIN SELECT RAISE(ABORT,'prediction versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_no_update BEFORE UPDATE ON result_revisions
 BEGIN SELECT RAISE(ABORT,'result revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_no_delete BEFORE DELETE ON result_revisions
 BEGIN SELECT RAISE(ABORT,'result revisions are immutable'); END;
"""


def setup_prediction_store(db):
    db.executescript(SCHEMA)


def save_prediction(db, forecast):
    """Use server clock for saved_at; reject backfilled pre-race performance."""
    if not isinstance(forecast, dict) or 'inputs' not in forecast:
        raise PredictionError('replayable forecast required')
    checked = build_prediction(forecast['inputs'])
    if _json(checked) != _json(forecast):
        raise PredictionError('forecast hash or derived probabilities were changed')
    now = _now()
    if not _time(checked['generated_at']) <= now < _time(checked['race_start_at']):
        raise PredictionError('prediction must actually be saved before race start and after generation')
    setup_prediction_store(db)
    identifier = checked['content_sha256']
    with db:
        db.execute('INSERT OR IGNORE INTO prediction_versions VALUES (?,?,?,?,?,?,?,?,?)',
            (identifier, checked['race_id'], checked['model_id'], checked['model_version'], checked['as_of'],
             checked['generated_at'], now.isoformat(timespec='microseconds'), checked['race_start_at'], _json(checked)))
    row = db.execute('SELECT saved_at FROM prediction_versions WHERE version_id=?', (identifier,)).fetchone()
    return dict(version_id=identifier, saved_at=row[0], content_sha256=identifier)


def export_prediction(db, version_id):
    setup_prediction_store(db)
    row = db.execute('SELECT payload_json FROM prediction_versions WHERE version_id=?', (_id(version_id, 'version_id'),)).fetchone()
    if row is None:
        raise PredictionError('prediction version not found')
    return row[0]


def save_result_revision(db, official_result):
    if not isinstance(official_result, dict):
        raise PredictionError('official result must be an object')
    required = {'race_id', 'race_start_at', 'available_at', 'captured_at', 'source_ref', 'status', 'confirmed', 'payouts'}
    if not required <= set(official_result):
        raise PredictionError('complete dated official result required')
    value = json.loads(_json(official_result))
    race = _id(value['race_id'], 'race_id')
    _description(value['source_ref'], 'source_ref', 256)
    start, available, capture = (_time(value[key]) for key in ('race_start_at', 'available_at', 'captured_at'))
    now = _now()
    if not start <= available <= capture <= now:
        raise PredictionError('result evidence must be available and captured after start and before save')
    try:
        settle_bets([], value)
    except MoneyError as exc:
        raise PredictionError(str(exc)) from exc
    if value['status'] == 'settled':
        top3 = value.get('top3')
        if (not isinstance(top3, list) or len(top3) != 3 or any(type(x) is not int or x not in range(1, 7) for x in top3)
                or len(set(top3)) != 3):
            raise PredictionError('normal result requires three distinct finish boat identities')
    for key in ('race_start_at', 'available_at', 'captured_at'):
        value[key] = _stamp(value[key])
    setup_prediction_store(db)
    identifier = _sha(value)
    with db:
        existing = db.execute('SELECT revision_no,supersedes_id FROM result_revisions WHERE revision_id=?', (identifier,)).fetchone()
        if existing is not None:
            return dict(revision_id=identifier, revision_no=existing[0], supersedes_id=existing[1])
        last = db.execute('SELECT revision_id,revision_no,available_at,captured_at FROM result_revisions WHERE race_id=? ORDER BY revision_no DESC LIMIT 1', (race,)).fetchone()
        if last is not None and (available < _time(last[2]) or capture < _time(last[3])):
            raise PredictionError('correction cannot predate an already stored official revision')
        revision, supersedes = (last[1] + 1, last[0]) if last is not None else (1, None)
        db.execute('INSERT INTO result_revisions VALUES (?,?,?,?,?,?,?,?)',
            (identifier, race, revision, value['available_at'], value['captured_at'], now.isoformat(timespec='microseconds'), supersedes, _json(value)))
    return dict(revision_id=identifier, revision_no=revision, supersedes_id=supersedes)


def _samples(db, cutoff, model_ids=None):
    setup_prediction_store(db)
    latest, excluded = {}, []
    for row in db.execute('SELECT version_id,race_id,model_id,model_version,generated_at,saved_at,race_start_at,payload_json FROM prediction_versions ORDER BY generated_at,saved_at,version_id'):
        if model_ids is not None and row[2] not in model_ids or _time(row[5]) > cutoff:
            continue
        if not _time(row[4]) <= _time(row[5]) < _time(row[6]):
            excluded.append(dict(race_id=row[1], model_id=row[2], reason='not_saved_before_start'))
            continue
        forecast = json.loads(row[7])
        if build_prediction(forecast['inputs']) != forecast or forecast['content_sha256'] != row[0]:
            raise PredictionError('stored forecast integrity mismatch')
        latest[(row[1], row[2], row[3])] = forecast
    result_map = {}
    for row in db.execute('SELECT race_id,revision_no,available_at,captured_at,saved_at,payload_json FROM result_revisions ORDER BY revision_no'):
        if max(_time(row[2]), _time(row[3]), _time(row[4])) <= cutoff:
            result_map[row[0]] = json.loads(row[5])
    samples = []
    for forecast in latest.values():
        result = result_map.get(forecast['race_id'])
        reason = None
        if result is None:
            reason = 'no_result_at_cutoff'
        elif result['status'] != 'settled':
            reason = 'unsupported_result:' + result['status']
        elif _time(result['race_start_at']) != _time(forecast['race_start_at']):
            reason = 'race_start_mismatch'
        if reason:
            excluded.append(dict(race_id=forecast['race_id'], model_id=forecast['model_id'], reason=reason))
        else:
            samples.append((forecast, result))
    return samples, excluded


def _metrics(samples, bin_count):
    groups = {}
    for forecast, result in samples:
        groups.setdefault((forecast['model_id'], forecast['model_version']), []).append((forecast, result))
    models = []
    for (model, version), group in sorted(groups.items()):
        briers, losses = [], []
        bins = [dict(sample_count=0, positive_count=0, probability_sum=0.0) for _ in range(bin_count)]
        for forecast, result in group:
            truth = tuple(result['top3'])
            errors, winner_probability = [], None
            for row in forecast['triples']:
                p = row['probability']
                hit = tuple(row['combination']) == truth
                errors.append((p - int(hit)) ** 2)
                if hit:
                    winner_probability = p
                bucket = bins[min(bin_count - 1, int(p * bin_count))]
                bucket['sample_count'] += 1
                bucket['positive_count'] += int(hit)
                bucket['probability_sum'] += p
            briers.append(math.fsum(errors))
            if winner_probability is None or not 0 < winner_probability <= 1:
                raise PredictionError('winning outcome missing or nonpositive in forecast')
            losses.append(-math.log(winner_probability))
        calibration = [dict(lower=i / bin_count, upper=(i + 1) / bin_count, sample_count=b['sample_count'],
            positive_count=b['positive_count'], mean_probability=b['probability_sum'] / b['sample_count'] if b['sample_count'] else None,
            observed_frequency=b['positive_count'] / b['sample_count'] if b['sample_count'] else None)
            for i, b in enumerate(bins)]
        models.append(dict(model_id=model, model_version=version, race_count=len(group), ticket_count=len(group) * 120,
                           race_ids=sorted(f['race_id'] for f, _ in group),
                           multiclass_brier=math.fsum(briers) / len(group), log_loss=math.fsum(losses) / len(group),
                           calibration=calibration, validation_status='UNVALIDATED',
                           selection_reasons=sorted({f['selection_reason'] for f, _ in group})))
    return models


def evaluate_predictions(db, *, as_of, model_ids=None, calibration_bins=10):
    if type(calibration_bins) is not int or not 1 <= calibration_bins <= 100:
        raise PredictionError('calibration_bins must be 1..100')
    if model_ids is not None:
        if not isinstance(model_ids, list) or not model_ids:
            raise PredictionError('nonempty model_ids list required')
        model_ids = [_id(x, 'model_id') for x in model_ids]
    samples, excluded = _samples(db, _time(as_of), model_ids)
    return dict(as_of=_stamp(as_of), research_only=True, validation_status='UNVALIDATED',
                version_policy='latest_saved_pre_race_per_model_version',
                comparison_scope='per_model_available_samples', models=_metrics(samples, calibration_bins), excluded=excluded)


def compare_models(db, model_ids, *, as_of, calibration_bins=10):
    if not isinstance(model_ids, list) or len(model_ids) < 2:
        raise PredictionError('at least two distinct model IDs required')
    model_ids = [_id(x, 'model_id') for x in model_ids]
    if len(set(model_ids)) != len(model_ids):
        raise PredictionError('at least two distinct model IDs required')
    if type(calibration_bins) is not int or not 1 <= calibration_bins <= 100:
        raise PredictionError('calibration_bins must be 1..100')
    samples, excluded = _samples(db, _time(as_of), model_ids)
    by_race = {}
    for item in samples:
        by_race.setdefault(item[0]['race_id'], []).append(item)
    common, chosen = [], []
    for race, group in sorted(by_race.items()):
        if len(group) != len(model_ids) or {f['model_id'] for f, _ in group} != set(model_ids):
            excluded.append(dict(race_id=race, reason='incomplete_or_ambiguous_model_cohort'))
        elif len({f['as_of'] for f, _ in group}) != 1:
            excluded.append(dict(race_id=race, reason='information_cutoff_mismatch'))
        else:
            common.append(race)
            chosen.extend(group)
    return dict(as_of=_stamp(as_of), research_only=True, validation_status='UNVALIDATED',
                comparison_scope='same_races_and_information_cutoffs', common_race_ids=common,
                models=_metrics(chosen, calibration_bins), excluded=excluded)


def build_history_baseline(db, *, race_id, entries, race_start_at, as_of, generated_at):
    """Smoothed historical win-rate worths; no current actual ST/course/finish."""
    if not isinstance(entries, list) or len(entries) != 6:
        raise PredictionError('six explicit race entries required')
    cutoff = _time(as_of)
    boats, racers_seen, courses_seen = [], set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'lane', 'racer_id', 'predicted_course'}:
            raise PredictionError('entry requires lane, racer_id and predicted_course only')
        lane, racer, course = entry['lane'], entry['racer_id'], entry['predicted_course']
        if type(course) is not int or course not in range(1, 7) or not isinstance(racer, str) or not re.fullmatch(r'[0-9]{4}', racer):
            raise PredictionError('valid racer ID and explicit predicted course required')
        if racer in racers_seen or course in courses_seen:
            raise PredictionError('distinct racers and a predicted-course permutation required')
        racers_seen.add(racer)
        courses_seen.add(course)
        # Compare full parsed timestamps; existing core stores UTC seconds, but
        # imported revisions may carry fractions. Latest eligible source wins.
        eligible = []
        for row in db.execute('''SELECT * FROM starts WHERE race_id!=? AND (race_id,lane) IN
             (SELECT race_id,lane FROM starts WHERE racer_id=?)''', (race_id, racer)):
            if _time(row['published_at']) <= _time(row['captured_at']) <= cutoff:
                eligible.append(row)
        latest = {}
        for row in sorted(eligible, key=lambda r: (_time(r['captured_at']), r['sha'])):
            latest[(row['race_id'], row['lane'])] = row
        rows = sorted((row for row in latest.values() if row['racer_id'] == racer and row['course'] == course
                       and row['st_status'] != 'ABSENT' and _time(row['race_at']) < cutoff),
                      key=lambda r: (_time(r['race_at']), r['race_id']), reverse=True)[:20]
        stats = summarize(rows, 20)
        n, wins = stats['n'], sum(row['finish'] == 1 for row in rows)
        # Beta-style fixed shrinkage to one win in six; deliberately untrained.
        strength = (wins + 1) / (n + 6)
        available = max((_time(row['published_at']) for row in rows), default=cutoff)
        captured = max((_time(row['captured_at']) for row in rows), default=cutoff)
        source_ref = 'history-sha256:' + _sha([dict(race_id=r['race_id'], sha=r['sha'], captured_at=r['captured_at']) for r in rows])
        boats.append(dict(lane=lane, racer_id=racer, predicted_course=course, strength=strength,
                          available_at=available.isoformat(), captured_at=captured.isoformat(), generated_at=available.isoformat(),
                          source_ref=source_ref, feature_kind='history_baseline', sample_n=n, historical_first_count=wins))
    return build_prediction(dict(race_id=race_id, race_start_at=race_start_at, as_of=as_of, generated_at=generated_at,
        model_id='history-course-plackett-luce', model_version='1', selection_reason='untrained smoothed historical same predicted course first-rate baseline', boats=boats))
