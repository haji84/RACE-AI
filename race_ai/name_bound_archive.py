"""Pure retrospective replay of immutable, completed name-bound archives.

Original evaluations replay at their unchanged as_of; the independently
supplied actual audit clock only bounds history and dates the new aggregate.
No forecasts, labels, receipt clocks, or live validation rules are rewritten.
"""
import copy
import hashlib
import math
import re

from web import race_contract as facts
from web.evaluation_contract import _clock
from web.name_bound_evaluation import build_name_bound_evaluation
from web.name_bound_result import result_bundle, validate_name_bound_result_envelope


MAX_BYTES = 256_000
MAX_TOTAL_BYTES = 8_000_000
MAX_INPUTS = 24
OPERATION = 'OFFLINE_NAME_BOUND_ARCHIVE_COHORT'
SCOPE = 'RETROSPECTIVE_ARCHIVE_REPLAY_DIFFERENT_FEATURE_PHASES'
ENTRY_FIELDS = set('archive_kind manifest program forecast request result evaluation'.split())
READ_ONLY_EVALUATION = 'READ_ONLY_EVALUATION'
RESULT_PUBLICATION = 'RESULT_PUBLICATION'
ARCHIVE_FILES = {
    READ_ONLY_EVALUATION: frozenset({'manifest.json', 'program.json', 'forecast.json', 'result.json', 'evaluation.json'}),
    RESULT_PUBLICATION: frozenset({'manifest.json', 'program.json', 'forecast.json', 'request.json', 'result.json', 'evaluation.json'}),
}
OLD_MANIFEST = set('schema_version status failure_reason race_id forecast_request_id commit_sha backups reads_used posts_attempted official_source_requests max_seconds validation_status purchase_decision purchase_recommendations'.split())
NEW_MANIFEST = OLD_MANIFEST | {'operation', 'request_id'}
REQUEST_FIELDS = set('publication_review race_id request_id forecast_request_id snapshot runner_saved_at'.split())
PHASES = ('B_ONLY_BASELINE', 'DISPLAY_V2', 'ORIGINAL_V2')
ERRORS = (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError, StopIteration)


def _require(condition):
    if not condition:
        raise ValueError('NAME_BOUND_ARCHIVE_INVALID')


def _digest(value):
    return hashlib.sha256(facts.canonical(value)).hexdigest()


def _nonce(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}', value) is not None


def _payload_bytes(entry):
    _require(isinstance(entry, dict) and set(entry) == ENTRY_FIELDS)
    kind = entry['archive_kind']
    _require(isinstance(kind, str) and kind in ARCHIVE_FILES)
    _require(kind != READ_ONLY_EVALUATION or entry['request'] is None)
    payloads = {name: facts.canonical(entry[name[:-5]]) for name in ARCHIVE_FILES[kind]}
    _require(all(0 < len(raw) <= MAX_BYTES for raw in payloads.values()))
    return payloads


def _manifest(entry, payloads):
    manifest, kind = entry['manifest'], entry['archive_kind']
    publication = kind == RESULT_PUBLICATION
    fields=NEW_MANIFEST if publication else OLD_MANIFEST
    allowed=(fields,fields|{'result_disposition_contract'}) if publication else (fields,)
    _require(isinstance(manifest, dict) and set(manifest) in allowed)
    if 'result_disposition_contract' in manifest:
        _require(manifest['result_disposition_contract']==facts.RESULT_DISPOSITION_V2)
    _require(type(manifest['schema_version']) is int and manifest['schema_version'] == 1
        and manifest['status'] == 'COMPLETED' and manifest['failure_reason'] is None
        and manifest['validation_status'] == 'UNVALIDATED' and manifest['purchase_decision'] == 'skip'
        and manifest['purchase_recommendations'] == [])
    _require(isinstance(manifest['commit_sha'], str) and re.fullmatch(r'[0-9a-f]{40}', manifest['commit_sha']) is not None)
    _require(_nonce(manifest['forecast_request_id'])
        and manifest['race_id'] == entry['program']['race_id']
        and manifest['forecast_request_id'] == entry['forecast']['receipt']['request_id'])
    counts = (5, 1, 1, 240) if publication else (4, 0, 0, 180)
    for field, expected in zip(('reads_used', 'posts_attempted', 'official_source_requests', 'max_seconds'), counts):
        _require(type(manifest[field]) is int and manifest[field] == expected)
    if publication:
        _require(manifest['operation'] == 'NAME_BOUND_RESULT_PUBLICATION' and _nonce(manifest['request_id']))
    backups = manifest['backups']
    _require(isinstance(backups, dict) and set(backups) == set(payloads) - {'manifest.json'})
    for name, meta in backups.items():
        _require(isinstance(meta, dict) and set(meta) == {'bytes', 'sha256'}
            and type(meta['bytes']) is int and meta['bytes'] == len(payloads[name])
            and isinstance(meta['sha256'], str) and meta['sha256'] == hashlib.sha256(payloads[name]).hexdigest())


def _replay(entry, clock):
    race, forecast, result, original = (entry[k] for k in ('program', 'forecast', 'result', 'evaluation'))
    _require(isinstance(original, dict))
    replay = facts._time(original['as_of'])
    day, _, _ = facts._program(race)
    _require(replay <= clock and replay.astimezone(facts.JST).date() == day)
    result_request_id = None
    if entry['archive_kind'] == RESULT_PUBLICATION:
        checked = validate_name_bound_result_envelope(result, race, forecast, now=replay)
        receipt, request = checked['receipt'], entry['request']
        _require(receipt['snapshot']['result_record'].get('result_disposition_contract')
            ==entry['manifest'].get('result_disposition_contract'))
        _require(isinstance(request, dict) and set(request) == REQUEST_FIELDS
            and request['publication_review'] == 'user-confirmation-2026-10-15-official-facts'
            and request['race_id'] == race['race_id'] and request['request_id'] == entry['manifest']['request_id'])
        # The entire snapshot is already validated inside its own finalized
        # envelope. The publication request must preserve that exact snapshot.
        _require(all(request[k] == receipt[k] for k in ('request_id', 'forecast_request_id', 'runner_saved_at'))
            and facts.canonical(request['snapshot']) == facts.canonical(receipt['snapshot']))
        result_request_id = receipt['request_id']
        result = result_bundle(checked, race, forecast, now=replay)
    rebuilt = build_name_bound_evaluation(forecast, result, race, replay)
    _require(rebuilt['result_proof'] is not None and facts.canonical(original) == facts.canonical(rebuilt))
    snapshot = forecast['receipt']['snapshot']
    baseline = next(m for m in forecast['baseline']['snapshot']['models'] if m['model_id'] == snapshot['baseline_link']['model_id'])
    signature = [dict(phase=phase, model_id=model['model_id'], model_version=model['model_version'],
        parameters=None if phase == PHASES[0] else copy.deepcopy(model['parameters']))
        for phase, model in zip(PHASES, [baseline, *snapshot['models']])]
    observation = dict(race_id=race['race_id'], date_jst=rebuilt['date_jst'],
        forecast_request_id=forecast['receipt']['request_id'], result_request_id=result_request_id,
        archive_kind=entry['archive_kind'], **{k+'_sha256': _digest(entry[k])
            for k in ('manifest', 'program', 'forecast', 'result', 'evaluation')},
        original_evaluation_as_of=original['as_of'], status=rebuilt['status'],
        exclusion_reason=rebuilt['exclusion_reason'], model_rows=copy.deepcopy(rebuilt['models']))
    return observation, signature


def _build(entries, now):
    clock = _clock(now)
    _require(isinstance(entries, list) and 1 <= len(entries) <= MAX_INPUTS)
    # Bound all original canonical files, including every manifest. Wrapper
    # keys and the absent legacy request.json are not original file bytes.
    payloads = [_payload_bytes(entry) for entry in entries]
    _require(sum(len(raw) for files in payloads for raw in files.values()) <= MAX_TOTAL_BYTES)
    observations, signature, seen = [], None, set()
    for entry, files in zip(entries, payloads):
        _manifest(entry, files)
        observation, current_signature = _replay(entry, clock)
        _require(observation['race_id'] not in seen)
        seen.add(observation['race_id'])
        if signature is None:
            signature = current_signature
        _require(facts.canonical(signature) == facts.canonical(current_signature))
        observations.append(observation)
    observations.sort(key=lambda row: row['race_id'])
    evaluated = [row for row in observations if row['status'] == 'EVALUATED']
    count = len(evaluated)
    models = []
    if count:
        for index, identity in enumerate(signature):
            rows = [race['model_rows'][index] for race in evaluated]
            baseline_rows = [race['model_rows'][0] for race in evaluated]
            models.append(dict(phase=identity['phase'], model_id=identity['model_id'], model_version=identity['model_version'],
                race_count=count, ticket_count_per_race=120,
                mean_multiclass_brier=math.fsum(row['multiclass_brier'] for row in rows)/count,
                mean_log_loss=math.fsum(row['log_loss'] for row in rows)/count,
                mean_winner_probability=math.fsum(row['winner_probability'] for row in rows)/count,
                mean_brier_delta_from_baseline=math.fsum(row['multiclass_brier']-base['multiclass_brier'] for row,base in zip(rows,baseline_rows))/count,
                mean_log_loss_delta_from_baseline=math.fsum(row['log_loss']-base['log_loss'] for row,base in zip(rows,baseline_rows))/count))
    dates = sorted({row['date_jst'] for row in evaluated})
    report = dict(schema_version=1, operation=OPERATION, as_of=facts.stamp(clock),
        status='EXPLORATORY_AGGREGATE' if count else 'NO_SCORABLE_RACES', scope=SCOPE,
        research_only=True, validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[],
        physical_exhibition_timing_verified=False, holdout_status='NOT_ESTABLISHED',
        calibration_status='NOT_EVALUATED', model_adoption_status='NOT_EVALUATED',
        input_count=len(observations), race_count=count, day_count=len(dates),
        requested_race_ids=[row['race_id'] for row in observations],
        evaluated_race_ids=[row['race_id'] for row in evaluated], evaluated_dates=dates,
        excluded=[dict(race_id=row['race_id'], forecast_request_id=row['forecast_request_id'],
            status=row['status'], reason=row['exclusion_reason']) for row in observations if row['status'] != 'EVALUATED'],
        models=models, observations=observations, signature_sha256=_digest(signature))
    report['snapshot_id'] = _digest(report)
    _require(len(facts.canonical(report)) <= MAX_BYTES)
    return report


def build_archived_name_bound_cohort(entries, *, now):
    """Replay 1..24 full archives without changing any supplied object."""
    try:
        return _build(entries, now)
    except ERRORS as exc:
        raise ValueError('NAME_BOUND_ARCHIVE_INVALID') from exc


def validate_archived_name_bound_cohort(report, entries, *, now):
    """Replay the aggregate at its saved audit clock, bounded by actual now."""
    try:
        clock = _clock(now)
        _require(isinstance(report, dict) and 0 < len(facts.canonical(report)) <= MAX_BYTES)
        replay = facts._time(report['as_of'])
        _require(replay <= clock)
        rebuilt = _build(entries, replay)
        _require(facts.canonical(report) == facts.canonical(rebuilt))
        return rebuilt
    except ERRORS as exc:
        raise ValueError('NAME_BOUND_ARCHIVE_INVALID') from exc
