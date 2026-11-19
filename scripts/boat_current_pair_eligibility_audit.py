"""Count authenticated current BOAT native records; never score or qualify G8.

Called inside the existing trusted main audit, with its frozen API reader and
clock. Private originals stay in the existing AES readers and local memory.
Raw official qualification and a prospective sample policy are not audited here.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re


_PAIR_CUTOFF_AVAILABLE = 'LATEST_PRODUCER_JOURNAL_CUTOFF_COUNTS_UNQUALIFIED'
_PAIR_CUTOFF_SUFFIXES = (
    'total_record_count', 'total_race_count',
    'equal_record_count', 'earlier_record_count', 'later_record_count',
    'missing_observation_record_count', 'no_closed_at_record_count',
    'equal_race_count', 'earlier_race_count', 'later_race_count',
    'uncomparable_race_count')
_PAIR_CUTOFF_FIELDS = tuple('current_pair_cutoff_' + name for name in _PAIR_CUTOFF_SUFFIXES)


def _current_pair_cutoff_unavailable():
    result = {'current_pair_cutoff_status': 'UNAVAILABLE'}
    result.update({name: None for name in _PAIR_CUTOFF_FIELDS})
    return result


def _current_pair_exact_cutoff_error(error):
    if type(error) is not ValueError:
        return False
    arguments = error.args
    return (type(arguments) is tuple and len(arguments) == 1 and type(arguments[0]) is str
            and arguments[0] == 'ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH')


def _current_pair_cutoff_projection(value):
    default = _current_pair_cutoff_unavailable()
    if type(value) is not dict or not all(type(name) is str for name in value):
        return default
    if set(value) != set(default):
        return default
    status = value['current_pair_cutoff_status']
    if type(status) is not str:
        return default
    if status == 'UNAVAILABLE':
        return default
    if status != _PAIR_CUTOFF_AVAILABLE:
        return default
    counts = {}
    for suffix in _PAIR_CUTOFF_SUFFIXES:
        observed = value['current_pair_cutoff_' + suffix]
        if type(observed) is not int or not 0 <= observed <= 1_000_000:
            return default
        counts[suffix] = observed
    records, races = counts['total_record_count'], counts['total_race_count']
    categories = ('equal', 'earlier', 'later', 'missing_observation', 'no_closed_at')
    if (sum(counts[name + '_record_count'] for name in categories) != records
            or races > records or (records == 0) != (races == 0)):
        return default
    uncomparable = counts['uncomparable_race_count']
    uncomparable_records = counts['missing_observation_record_count'] + counts['no_closed_at_record_count']
    if (uncomparable > races or uncomparable > uncomparable_records
            or (uncomparable == 0) != (uncomparable_records == 0)):
        return default
    for name in ('equal', 'earlier', 'later'):
        record_count, race_count = counts[name + '_record_count'], counts[name + '_race_count']
        if (race_count > record_count or race_count > races - uncomparable
                or (record_count == 0) != (race_count == 0)):
            return default
    if races > uncomparable + sum(counts[name + '_race_count'] for name in ('equal', 'earlier', 'later')):
        return default
    result = {'current_pair_cutoff_status': _PAIR_CUTOFF_AVAILABLE}
    result.update({'current_pair_cutoff_' + name: counts[name] for name in _PAIR_CUTOFF_SUFFIXES})
    return result


def _current_pair_cutoff_counts(first, latest, *, parse_time):
    """Inventory only the already authenticated first originals and latest journal."""
    if (type(first) is not dict or type(latest) is not dict
            or len(first) > 1_000_000 or not callable(parse_time)):
        raise ValueError('CURRENT_PAIR_CUTOFF_DIAGNOSTIC_UNAVAILABLE')
    counts = {name: 0 for name in _PAIR_CUTOFF_SUFFIXES}
    races = set()
    directions = {name: set() for name in ('equal', 'earlier', 'later')}
    uncomparable = set()
    for descriptor in first.values():
        if type(descriptor) is not dict:
            raise ValueError('CURRENT_PAIR_CUTOFF_DIAGNOSTIC_UNAVAILABLE')
        race = descriptor.get('race')
        info = descriptor.get('info')
        if (type(race) is not tuple or len(race) != 2
                or not all(type(part) is str for part in race) or type(info) is not dict):
            raise ValueError('CURRENT_PAIR_CUTOFF_DIAGNOSTIC_UNAVAILABLE')
        expected = parse_time(info['race_cutoff_at'])
        if type(expected) is not datetime or expected.utcoffset() is None:
            raise ValueError('CURRENT_PAIR_CUTOFF_DIAGNOSTIC_UNAVAILABLE')
        races.add(race)
        counts['total_record_count'] += 1
        if race[1] not in latest:
            counts['missing_observation_record_count'] += 1
            uncomparable.add(race)
            continue
        observation = latest[race[1]]
        if type(observation) is not dict:
            raise ValueError('CURRENT_PAIR_CUTOFF_DIAGNOSTIC_UNAVAILABLE')
        closed = observation.get('closed_at')
        if closed is None:
            counts['no_closed_at_record_count'] += 1
            uncomparable.add(race)
            continue
        actual = parse_time(closed)
        if type(actual) is not datetime or actual.utcoffset() is None:
            raise ValueError('CURRENT_PAIR_CUTOFF_DIAGNOSTIC_UNAVAILABLE')
        direction = 'equal' if actual == expected else 'earlier' if actual < expected else 'later'
        counts[direction + '_record_count'] += 1
        directions[direction].add(race)
    counts['total_race_count'] = len(races)
    for name in directions:
        counts[name + '_race_count'] = len(directions[name])
    counts['uncomparable_race_count'] = len(uncomparable)
    result = {'current_pair_cutoff_status': _PAIR_CUTOFF_AVAILABLE}
    result.update({'current_pair_cutoff_' + name: counts[name] for name in _PAIR_CUTOFF_SUFFIXES})
    return _current_pair_cutoff_projection(result)


def current_pair_cutoff_diagnostic(error):
    """Expose only an exact cutoff rejection's bounded, unqualified inventory."""
    default = _current_pair_cutoff_unavailable()
    if type(error) is not ValueError:
        return default
    arguments = error.args
    if (type(arguments) is not tuple or len(arguments) != 1 or type(arguments[0]) is not str
            or arguments[0] != 'CURRENT_PAIR_AUDIT_REJECTED'):
        return default
    attached = getattr(error, '_current_pair_diagnostic', None)
    if type(attached) is not dict:
        return default
    phase = attached.get('current_pair_failure_phase')
    reason = attached.get('current_pair_failure_reason')
    if (type(phase) is not str or phase != 'PAIR_RESULT_JOIN' or type(reason) is not str
            or reason != 'ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH'):
        return default
    return _current_pair_cutoff_projection(attached.get('cutoff_inventory'))


def _need(value):
    if not value:
        raise ValueError('CURRENT_PAIR_AUDIT_REJECTED')


def _current_pair_failure_tables():
    """Finite constant output values; no private exception text is constructed."""
    phases = (
        'PAIR_PREFLIGHT',
        'PAIR_SCOPE',
        'PAIR_INVENTORY',
        'PAIR_RECEIPT',
        'PAIR_TRAINING',
        'PAIR_RECORD_BINDING',
        'PAIR_RECORD_FINALIZE',
        'PAIR_RESULT_INVENTORY',
        'PAIR_RESULT_RECEIPT',
        'PAIR_RESULT_JOURNAL',
        'PAIR_RESULT_REVISIONS',
        'PAIR_RESULT_JOIN',
        'PAIR_FINALIZE',
    )
    value_codes = (
        'ALL_MODEL_INTAKE_AWARE_RESULT_CLOCK_REQUIRED',
        'ALL_MODEL_INTAKE_BOAT_ACTUAL_CUTOFF_REQUIRED',
        'ALL_MODEL_INTAKE_BOAT_REGISTERED_ROSTER_INVALID',
        'ALL_MODEL_INTAKE_BOAT_RESULT_PAYOUT_MISMATCH',
        'ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH',
        'ALL_MODEL_INTAKE_RESULT_CAPTURE_CLOCK_INVALID',
        'ALL_MODEL_INTAKE_RESULT_ORDER_INVALID',
        'ALL_MODEL_INTAKE_RESULT_PUBLICATION_CLOCK_INVALID',
        'ALL_MODEL_INTAKE_RESULT_REGISTERED_ROSTER_MISMATCH',
        'ALL_MODEL_INTAKE_RESULT_SETTLEMENT_INVALID',
        'ALL_MODEL_INTAKE_RESULT_SOURCE_HASH_INVALID',
        'ALL_MODEL_INTAKE_RESULT_SOURCE_REQUIRED',
        'ALL_MODEL_PAIR_RECEIPT_ARCHIVE_REJECTED',
        'ALL_MODEL_PAIR_RECEIPT_ARTIFACT_BYTES_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ARTIFACT_CLOCK_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ARTIFACT_IDENTITY_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ARTIFACT_NAME_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ARTIFACT_RUN_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_AWARE_CLOCK_REQUIRED',
        'ALL_MODEL_PAIR_RECEIPT_AWARE_TIME_REQUIRED',
        'ALL_MODEL_PAIR_RECEIPT_CAPTURED_INPUT_PRE_CUTOFF_CLOCK_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_DUPLICATE_CELL_RACE',
        'ALL_MODEL_PAIR_RECEIPT_EXPECTED_RUN_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_MIXED_CANDIDATE_CONTEXTS_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_PAYLOAD_DIRECTORY_MISMATCH',
        'ALL_MODEL_PAIR_RECEIPT_PAYLOAD_REPLAY_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_PAYLOAD_SCHEMA_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_PRE_CUTOFF_CLOCK_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_PUBLIC_SUMMARY_BINDING_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ZIP_CONTENT_BOUND_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ZIP_MEMBERS_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ZIP_MEMBER_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ZIP_MEMBER_SIZE_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ZIP_PATH_INVALID',
        'ALL_MODEL_PAIR_RECEIPT_ZIP_SIZE_INVALID',
        'ALL_MODEL_RESULT_INTAKE_ARCHIVE_BOUND_INVALID',
        'ALL_MODEL_RESULT_INTAKE_ARCHIVE_INVALID',
        'ALL_MODEL_RESULT_INTAKE_ARTIFACT_BYTES_INVALID',
        'ALL_MODEL_RESULT_INTAKE_ARTIFACT_CLOCK_INVALID',
        'ALL_MODEL_RESULT_INTAKE_ARTIFACT_IDENTITY_INVALID',
        'ALL_MODEL_RESULT_INTAKE_ARTIFACT_NAME_INVALID',
        'ALL_MODEL_RESULT_INTAKE_ARTIFACT_RUN_INVALID',
        'ALL_MODEL_RESULT_INTAKE_AWARE_CLOCK_REQUIRED',
        'ALL_MODEL_RESULT_INTAKE_BOUNDED_OBSERVATIONS_REQUIRED',
        'ALL_MODEL_RESULT_INTAKE_CONFLICTING_RESULT_CAPTURE',
        'ALL_MODEL_RESULT_INTAKE_DUPLICATE_JSON_KEY',
        'ALL_MODEL_RESULT_INTAKE_ENCRYPTED_RESULT_REQUIRED',
        'ALL_MODEL_RESULT_INTAKE_EXPECTED_RUN_INVALID',
        'ALL_MODEL_RESULT_INTAKE_JOURNAL_MEMBER_INVALID',
        'ALL_MODEL_RESULT_INTAKE_JSON_INVALID',
        'ALL_MODEL_RESULT_INTAKE_NONFINITE_JSON',
        'ALL_MODEL_RESULT_INTAKE_OBSERVATION_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_BEFORE_ACTUAL_CUTOFF',
        'ALL_MODEL_RESULT_INTAKE_RESULT_BODY_IDENTITY_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_CAPTURE_CLOCK_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_CUTOFF_DAY_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_DATA_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_DAY_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_PUBLICATION_CLOCK_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_RACE_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_REGISTERED_ROSTER_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_REPORT_BINDING_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_REPORT_CLOCK_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_REPORT_HASH_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_REPORT_PRECEDES_CAPTURE',
        'ALL_MODEL_RESULT_INTAKE_RESULT_ROSTER_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_SOURCE_HASH_INVALID',
        'ALL_MODEL_RESULT_INTAKE_RESULT_SOURCE_KIND_INVALID',
        'CURRENT_PAIR_AUDIT_REJECTED',
        'OWNER_ACTIVE_AUDIT_ACTIVE_OWNER_IDENTITY',
        'OWNER_ACTIVE_AUDIT_AWARE_CLOCK_REQUIRED',
        'OWNER_ACTIVE_AUDIT_COMPLETED_SCOPE_NOT_PINNED',
        'OWNER_ACTIVE_AUDIT_COUNTERS_DECREASED',
        'OWNER_ACTIVE_AUDIT_FINAL_COMPLETED_ROUND_PREFIX_MISSING',
        'OWNER_ACTIVE_AUDIT_FINAL_CONTROL_AES_PUBLIC_DISAGREE',
        'OWNER_ACTIVE_AUDIT_FINAL_CONTROL_AES_REQUIRED',
        'OWNER_ACTIVE_AUDIT_FINAL_CONTROL_BOUND',
        'OWNER_ACTIVE_AUDIT_FINAL_CONTROL_CHANGED',
        'OWNER_ACTIVE_AUDIT_FINAL_CONTROL_CLOCK',
        'OWNER_ACTIVE_AUDIT_FINAL_CONTROL_MISSING_OR_DUPLICATE',
        'OWNER_ACTIVE_AUDIT_FINAL_COUNTERS_OR_RECEIPT_CHANGED',
        'OWNER_ACTIVE_AUDIT_FINAL_OWNER_JOB_STATUS',
        'OWNER_ACTIVE_AUDIT_JOBS_INCOMPLETE_OR_CHANGED',
        'OWNER_ACTIVE_AUDIT_MODEL_ARCHIVE_DUPLICATE',
        'OWNER_ACTIVE_AUDIT_MODEL_ARCHIVE_NAME_UNSUPPORTED',
        'OWNER_ACTIVE_AUDIT_MODEL_ARCHIVE_SCOPE_CHANGED',
        'OWNER_ACTIVE_AUDIT_NESTED_P1_CHANGED',
        'OWNER_ACTIVE_AUDIT_NO_COMPLETED_ROUND',
        'OWNER_ACTIVE_AUDIT_ORIGINAL_CLOCK',
        'OWNER_ACTIVE_AUDIT_OWNER_JOB_IDENTITY',
        'OWNER_ACTIVE_AUDIT_OWNER_JOB_MISSING_OR_DUPLICATE',
        'OWNER_ACTIVE_AUDIT_OWNER_STEPS_MISSING',
        'OWNER_ACTIVE_AUDIT_P0_CODE_HEAD',
        'OWNER_ACTIVE_AUDIT_P0_DUPLICATE',
        'OWNER_ACTIVE_AUDIT_P0_ORIGINAL_MISSING_OR_DUPLICATE',
        'OWNER_ACTIVE_AUDIT_P0_ORIGIN_IDENTITY',
        'OWNER_ACTIVE_AUDIT_P0_REGISTRY_FILE',
        'OWNER_ACTIVE_AUDIT_P0_REGISTRY_HASH',
        'OWNER_ACTIVE_AUDIT_P0_REGISTRY_IDENTITY',
        'OWNER_ACTIVE_AUDIT_P0_REGISTRY_RECEIPT_CHANGED',
        'OWNER_ACTIVE_AUDIT_P0_REGISTRY_REF',
        'OWNER_ACTIVE_AUDIT_P0_SUPPLEMENT_DUPLICATE',
        'OWNER_ACTIVE_AUDIT_P0_SUPPLEMENT_SCOPE',
        'OWNER_ACTIVE_AUDIT_P1_DAY',
        'OWNER_ACTIVE_AUDIT_READ_ENDPOINT_REJECTED',
        'OWNER_ACTIVE_AUDIT_RESPONSE_BYTES_REQUIRED',
        'OWNER_ACTIVE_AUDIT_RESULT_COUNTERS',
        'OWNER_ACTIVE_AUDIT_RESULT_P1_RECEIPT_CHANGED',
        'OWNER_ACTIVE_AUDIT_RESULT_REPORT_BOUND',
        'OWNER_ACTIVE_AUDIT_RESULT_REPORT_CLOCK',
        'OWNER_ACTIVE_AUDIT_RESULT_SCOPE_OR_HASH',
        'OWNER_ACTIVE_AUDIT_ROUND_COMPLETION_CLOCK_OR_GAP',
        'OWNER_ACTIVE_AUDIT_ROUND_ORIGINAL_MISSING_OR_DUPLICATE',
        'OWNER_ACTIVE_AUDIT_ROUND_RECEIPT_COMPLETION_CLOCK',
        'OWNER_ACTIVE_AUDIT_ROUND_STEP_DUPLICATE',
        'OWNER_ACTIVE_AUDIT_SNAPSHOT_CHANGED',
        'OWNER_ACTIVE_AUDIT_SOURCE_NOT_PINNED',
        'OWNER_ACTIVE_AUDIT_TARGET_CONFIG',
        'OWNER_ACTIVE_AUDIT_TARGET_EVENT',
        'OWNER_ACTIVE_AUDIT_TARGET_REPOSITORY',
        'OWNER_ACTIVE_AUDIT_TARGET_RUN_ID',
        'OWNER_STATE_KEY_REQUIRED',
        'OWNER_STATE_KEY_REQUIRED_NOT_PUBLIC_FIXTURE',
        'VENUE_LEARNING_CONTEXT_ARCHIVE_REJECTED',
        'VENUE_LEARNING_CONTEXT_ARTIFACT_BYTES_INVALID',
        'VENUE_LEARNING_CONTEXT_ARTIFACT_CLOCK_INVALID',
        'VENUE_LEARNING_CONTEXT_ARTIFACT_HEAD_INVALID',
        'VENUE_LEARNING_CONTEXT_ARTIFACT_IDENTITY_INVALID',
        'VENUE_LEARNING_CONTEXT_ARTIFACT_ID_INVALID',
        'VENUE_LEARNING_CONTEXT_ARTIFACT_NAME_INVALID',
        'VENUE_LEARNING_CONTEXT_ARTIFACT_REPOSITORY_INVALID',
        'VENUE_LEARNING_CONTEXT_AWARE_CLOCK_REQUIRED',
        'VENUE_LEARNING_CONTEXT_CUTOFF_ELAPSED_DURING_SEAL',
        'VENUE_LEARNING_CONTEXT_FITTED_SHADOWS_REQUIRED',
        'VENUE_LEARNING_CONTEXT_FITTED_TRAINING_REQUIRED',
        'VENUE_LEARNING_CONTEXT_PHYSICAL_CUTOFF_REQUIRED',
        'VENUE_LEARNING_CONTEXT_SUMMARY_BINDING_INVALID',
        'VENUE_LEARNING_CONTEXT_TIMESTAMP_INVALID',
        'VENUE_LEARNING_CONTEXT_TIMESTAMP_REQUIRED',
        'VENUE_LEARNING_CONTEXT_TRAINING_CLOCK_INVALID',
        'VENUE_LEARNING_CONTEXT_ZIP_MEMBERS_INVALID',
        'VENUE_LEARNING_CONTEXT_ZIP_MEMBER_INVALID',
        'VENUE_LEARNING_CONTEXT_ZIP_SIZE_INVALID',
    )
    runtime_codes = (
        'GITHUB_API_READ_ATTEMPTS_EXHAUSTED_HALT',
        'GITHUB_API_READ_UNCLASSIFIED_CLI_ERROR_HALT',
        'GITHUB_API_TIMEOUT_HALT',
    )
    phase_map = {code: code for code in phases}
    value_map = {code: code for code in value_codes}
    runtime_map = {code: code for code in runtime_codes}
    for status in range(400, 600):
        code = f'GITHUB_API_READ_HTTP_{status}_HALT'
        runtime_map[code] = code
    return phase_map, value_map, runtime_map


def _current_pair_failure_values(error, phase):
    """Classify only exact builtin exception types and exact fixed arguments."""
    phases, values, runtimes = _current_pair_failure_tables()
    result = dict(current_pair_failure_phase=phases.get(phase, 'UNKNOWN_PHASE')
                  if type(phase) is str else 'UNKNOWN_PHASE',
                  current_pair_failure_reason='UNCLASSIFIED_EXCEPTION')
    kind = type(error)
    if kind is not ValueError and kind is not RuntimeError:
        return result
    arguments = error.args
    if type(arguments) is not tuple or len(arguments) != 1 or type(arguments[0]) is not str:
        return result
    reasons = values if kind is ValueError else runtimes
    result['current_pair_failure_reason'] = reasons.get(arguments[0], 'UNCLASSIFIED_EXCEPTION')
    return result


def current_pair_failure_diagnostic(error):
    """Detach only the two fixed diagnostic values from the existing rejection."""
    result = dict(current_pair_failure_phase='UNKNOWN_PHASE',
                  current_pair_failure_reason='UNCLASSIFIED_EXCEPTION')
    if type(error) is not ValueError:
        return result
    arguments = error.args
    if (type(arguments) is not tuple or len(arguments) != 1 or type(arguments[0]) is not str
            or arguments[0] != 'CURRENT_PAIR_AUDIT_REJECTED'):
        return result
    attached = getattr(error, '_current_pair_diagnostic', None)
    if type(attached) is not dict:
        return result
    phases, values, runtimes = _current_pair_failure_tables()
    phase = attached.get('current_pair_failure_phase')
    reason = attached.get('current_pair_failure_reason')
    if type(phase) is str:
        result['current_pair_failure_phase'] = phases.get(phase, 'UNKNOWN_PHASE')
    if type(reason) is str:
        reasons = dict(values)
        reasons.update(runtimes)
        result['current_pair_failure_reason'] = reasons.get(reason, 'UNCLASSIFIED_EXCEPTION')
    return result


def _scope(get, run_id, now, source, *, closed_round=None):
    from scripts import boat_owner_active_snapshot_audit as active
    from race_ai import boat_all_model_recovery as recovery
    from race_ai.cycle_recovery import artifact_pages
    from race_ai.actions_contract import digest
    source = active._expected_source(source)
    closed_round = active._closed_round(run_id, source, closed_round)
    reads = active._Reads(get)
    run = recovery._run(reads(f'actions/runs/{run_id}'), run_id, now)
    listing = artifact_pages(reads, run_id)
    allow_completed = source in active.PARTIAL_RECEIPT_OWNER_SHAS
    control = active._final_control(reads, run, listing, now) if allow_completed and run['status'] == 'completed' and closed_round is None else None
    job, rounds = active._jobs(reads, run, now, expected_owner_sha=source,
        completed_round_limit=control['completed_round'] if control else None,closed_round=closed_round)
    scope = dict(schema=active.SCHEMA, run=run, job=job, rounds=rounds, inventory=listing,
        inventory_sha256=digest(listing), captured_at=now.isoformat(), expected_owner_sha=source,
        allow_completed_receipts=allow_completed, final_control=control)
    if closed_round is not None:scope['closed_round']=closed_round
    if allow_completed:
        scope['all_model_archive_scope'] = active._model_archive_scope(listing, run_id, rounds, now)
    active.validate_active_scope(scope, run, listing, now, reads, expected_owner_sha=source,
                                 allow_completed_receipts=allow_completed)
    return active, reads, scope


def _audit(get, run_id, now, source, _diagnostic=None, _raw_cutoff_sink=None, *, closed_round=None):
    diagnostic = {} if _diagnostic is None else _diagnostic
    diagnostic['phase'] = 'PAIR_PREFLIGHT'
    from race_ai.actions_contract import canonical, digest
    from race_ai.boat_pdca_state import state_key
    from race_ai import boat_all_model_recovery as recovery
    from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact, MAX_ARCHIVE_BYTES
    from race_ai.all_existing_model_pairs import record_identity
    from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
    from race_ai.frozen_day_cycle import official_id
    _need(type(run_id) is int and 0 < run_id < 10**20 and type(now) is datetime and now.utcoffset() is not None)
    state_key('production')
    diagnostic['phase'] = 'PAIR_SCOPE'
    active, reads, scope = _scope(get, run_id, now, source,closed_round=closed_round)
    run, job, rounds, listing = (scope[key] for key in ('run', 'job', 'rounds', 'inventory'))
    day = active._time(run['created_at']).astimezone(timezone(timedelta(hours=9))).date().isoformat()
    items = {item['id']: item for item in listing}
    provenance = {}

    def read(item, limit):
        ident = item['id']; _need(type(ident) is int and ident > 0)
        metadata_raw = reads(f'actions/artifacts/{ident}')
        metadata, _ = recovery._metadata(metadata_raw, item, run, now, reads)
        _need(type(metadata.get('id')) is int and type(metadata.get('size_in_bytes')) is int
              and 0 < metadata['size_in_bytes'] <= limit)
        raw = reads(f'actions/artifacts/{ident}/zip')
        _need(type(raw) is bytes and 0 < len(raw) <= limit and metadata['size_in_bytes'] == len(raw)
              and metadata['digest'] == 'sha256:'+sha256(raw).hexdigest()
              and active._time(run['created_at']) <= active._time(metadata['created_at']) <= now)
        provenance[ident] = (sha256(metadata_raw).hexdigest(), sha256(raw).hexdigest())
        return raw, metadata

    def in_round(metadata, number):
        step = next(step for step in job['steps'] if step.get('name') == f'Deadline-ordered five-model round {number:02}')
        _need(active._time(step['started_at']) <= active._time(metadata['created_at']) <= active._time(step['completed_at']))

    diagnostic['phase'] = 'PAIR_INVENTORY'
    selected = {}; excluded = 0
    prefix = f'all-existing-model-pairs-{run_id}-'
    for item in listing:
        name = item.get('name', '')
        if not name.startswith(prefix):
            continue
        match = re.fullmatch(re.escape(prefix)+r'([1-9][0-9]*)', name)
        _need(match is not None)
        number = int(match[1]); _need(number not in selected)
        if number in rounds:
            selected[number] = item
        else:
            excluded += 1

    result = dict(current_pair_audit_schema='RACE_AI_CURRENT_NATIVE_PAIR_ELIGIBILITY_COUNTS_V1',
        current_pair_audit_status='HOLD_G8_UNQUALIFIED', current_pair_authenticated=False,
        current_pair_owner_run_id=run_id, current_pair_owner_source_commit=source,
        current_pair_inventory_sha256=scope['inventory_sha256'], current_pair_scope_sha256=digest(scope),
        current_pair_completed_round_count=len(rounds), current_pair_archive_count=len(selected),
        current_pair_missing_archive_round_count=len(set(rounds)-set(selected)), current_pair_excluded_archive_count=excluded,
        current_pair_forecast_record_count=None, current_pair_input_only_record_count=None,
        current_pair_first_forecast_record_count=None, current_pair_repeat_forecast_record_count=None,
        current_pair_distinct_race_count=None, current_pair_input_only_distinct_race_count=None,
        current_pair_training_archive_count=None, current_pair_result_archive_count=None,
        current_pair_result_unique_revision_count=None, current_pair_result_duplicate_revision_count=None,
        current_pair_producer_journal_settled_join_count=None, current_pair_producer_journal_pending_join_count=None,
        current_pair_producer_journal_special_join_count=None, current_pair_producer_journal_missing_join_count=None,
        current_pair_producer_journal_joined_race_count=None,
        current_pair_official_raw_verified=None, current_pair_official_cutoff_verified=None, current_pair_minimum_cohort=None,
        current_pair_official_source_status='UNKNOWN_HOLD', current_pair_evaluation_minimum_status='UNREGISTERED_HOLD',
        current_pair_result_scope='NOT_READ',
        current_pair_qualifying_g8_count=0, current_pair_qualifying_g8_denominator=None,
        current_pair_accuracy_improvement_proven=False, current_pair_promotion_allowed=False,
        current_pair_full_day_coverage=False, current_pair_new_forecasts=0, current_pair_source_requests=0)
    if not selected:
        return dict(result, current_pair_audit_status='HOLD_NO_PAIR_ARCHIVES')

    first = {}; input_races = set(); training_ids = set(); training_hashes = set()
    forecasts = 0; input_only = 0
    for number, item in sorted(selected.items(), key=lambda entry:(active._time(entry[1]['created_at']), entry[1]['id'])):
        diagnostic['phase'] = 'PAIR_RECEIPT'
        raw, metadata = read(item, MAX_ARCHIVE_BYTES); in_round(metadata, number)
        admission, records = _verified_private_pairs_artifact(raw, metadata, now=now,
            expected_run_id=run_id, expected_head_sha=source)
        _need(admission['scope'] == 'OPERATOR_SUPPLIED_RESEARCH')
        diagnostic['phase'] = 'PAIR_TRAINING'
        embedded = records[0]['training_receipt']; ident = embedded['id']
        _need(ident in items and ident != metadata['id'])
        learning_raw, learning_metadata = read(items[ident], MAX_ARCHIVE_BYTES)
        _need(re.fullmatch(r'(?:boat-venue-learning|all-existing-model-learning)-'+str(run_id)+r'-[1-9][0-9]*', learning_metadata['name']) is not None)
        def learning_receipt(route):
            _need(route == 'https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/'+str(ident))
            return learning_metadata
        context = context_from_encrypted_artifact(learning_raw, ident, now=now, _fetch=learning_receipt)
        _need(context['training']['scope'] == 'OPERATOR_SUPPLIED_RESEARCH')
        training_ids.add(ident); training_hashes.add(digest(context['training']))
        diagnostic['phase'] = 'PAIR_RECORD_BINDING'
        for payload in records:
            _need(canonical(payload['training']) == canonical(context['training'])
                  and canonical(payload['training_receipt']) == canonical(context['receipt']))
            sport, race = record_identity(payload)
            _need(sport == 'boat')
            race = official_id(race)
            _need(race.startswith(day.replace('-', '')+'-'))
            if 'pair' not in payload:
                input_only += 1; input_races.add((sport, race)); continue
            forecasts += 1; pair = payload['pair']
            identity = (sport, race, pair['stage'], pair['cell_key'])
            descriptor = dict(race=(sport, race), record_sha256=digest(payload), artifact_id=metadata['id'],
                cutoff_at=pair['cutoff_at'], info=dict(race_id=race,
                    race_cutoff_at=pair.get('race_cutoff_at', pair['cutoff_at']), roster=pair['baseline_normalized']['roster']))
            if identity in first:
                original = first[identity]
                _need(active._time(original['cutoff_at']) == active._time(descriptor['cutoff_at'])
                      and canonical(original['info']) == canonical(descriptor['info']))
            else:
                if _raw_cutoff_sink is not None:
                    try:
                        from scripts import boat_cutoff_raw_replay_audit as raw_cutoff
                        from race_ai import all_existing_model_registry as raw_registry
                        descriptor['_raw_program_ref'] = raw_cutoff._program_ref_for_pair(
                            payload, info=descriptor['info'], registry=raw_registry, parse_time=active._time)
                    except Exception:
                        descriptor['_raw_program_ref'] = None
                first[identity] = descriptor
        del records, context, raw, learning_raw

    diagnostic['phase'] = 'PAIR_RECORD_FINALIZE'
    result.update(current_pair_authenticated=True, current_pair_forecast_record_count=forecasts,
        current_pair_input_only_record_count=input_only, current_pair_first_forecast_record_count=len(first),
        current_pair_repeat_forecast_record_count=forecasts-len(first),
        current_pair_distinct_race_count=len({item['race'] for item in first.values()}),
        current_pair_input_only_distinct_race_count=len(input_races), current_pair_training_archive_count=len(training_ids),
        current_pair_result_archive_count=0,
        current_pair_training_bodies_sha256=digest(sorted(training_hashes)),
        current_pair_first_versions_sha256=digest(sorted((key, value['record_sha256'], value['artifact_id']) for key, value in first.items())))
    diagnostic['phase'] = 'PAIR_RESULT_INVENTORY'
    if first:
        from race_ai.all_existing_model_result_intake import observations_from_result_artifact, MAX_ARCHIVE_BYTES as RESULT_LIMIT, _json
        from race_ai.boat_private_original_archive import open_original_zip
        from race_ai.first_receipt_continuity import latest_result_observations
        from race_ai.all_existing_model_intake import _legacy_boat, _ordinary_result, _time as cutoff_time
        from race_ai.repeated_cycle import artifact_name
        revisions = {}; latest = {}; observation_count = 0
        for number in rounds:
            diagnostic['phase'] = 'PAIR_RESULT_INVENTORY'
            name = artifact_name('race-existing-cycle', run_id, number)
            matches = [item for item in listing if item.get('name') == name]; _need(len(matches) == 1)
            diagnostic['phase'] = 'PAIR_RESULT_RECEIPT'
            raw, metadata = read(matches[0], RESULT_LIMIT); in_round(metadata, number)
            admitted = observations_from_result_artifact(raw, metadata, now=now,
                expected_run_id=run_id, expected_head_sha=source)
            diagnostic['phase'] = 'PAIR_RESULT_JOURNAL'
            with open_original_zip(raw, metadata, expected_kind='RESULT', max_plain_zip_bytes=32*1024*1024) as archive:
                journal = _json(archive.read('official-result-observations.json'))
                report = _json(archive.read('status.json'))
            step = next(step for step in job['steps'] if step.get('name') == f'Deadline-ordered five-model round {number:02}')
            _need(type(report.get('round_no')) is int and report['round_no'] == number and report.get('day_jst') == day
                  and active._time(step['started_at']) <= active._time(report['updated_at']) <= active._time(metadata['created_at'])
                  and admitted['receipt']['original_journal_sha256'] == digest(journal))
            diagnostic['phase'] = 'PAIR_RESULT_REVISIONS'
            for observation in journal:
                key = (observation['race_id'], active._time(observation['captured_at']).isoformat())
                fingerprint = digest(observation)
                _need(key not in revisions or revisions[key] == fingerprint)
                revisions[key] = fingerprint; observation_count += 1
            combined, _ = latest_result_observations(list(latest.values())+admitted['observations'])
            latest = {row['race_id']:row for row in combined}
        diagnostic['phase'] = 'PAIR_RESULT_JOIN'
        joins = dict(settled=0, pending=0, special=0, missing=0); joined_races = set()
        try:
            for descriptor in first.values():
                sport, race = descriptor['race']; observation = latest.get(race)
                if observation is None:
                    joins['missing'] += 1; continue
                value = _legacy_boat(observation)
                _, reason = _ordinary_result(value, descriptor['info'], now)
                joins[reason or 'settled'] += 1; joined_races.add((sport, race))
        except Exception as error:
            if _current_pair_exact_cutoff_error(error):
                try:
                    inventory = _current_pair_cutoff_counts(first, latest, parse_time=cutoff_time)
                    diagnostic['cutoff_inventory'] = _current_pair_cutoff_projection(inventory)
                except Exception:
                    diagnostic['cutoff_inventory'] = _current_pair_cutoff_unavailable()
                if _raw_cutoff_sink is not None:
                    try:
                        _raw_cutoff_sink(first, latest)
                    except Exception:
                        pass
            raise
        result.update(current_pair_result_archive_count=len(rounds),
            current_pair_result_scope='PRODUCER_JOURNAL_ONLY_UNQUALIFIED',
            current_pair_result_unique_revision_count=len(revisions),
            current_pair_result_duplicate_revision_count=observation_count-len(revisions),
            current_pair_result_revisions_sha256=digest(sorted(revisions.items())),
            current_pair_producer_journal_joined_race_count=len(joined_races))
        result.update({'current_pair_producer_journal_'+name+'_join_count':count for name, count in joins.items()})
    diagnostic['phase'] = 'PAIR_FINALIZE'
    result['current_pair_artifacts_sha256'] = digest(sorted(provenance.items()))
    return result


def audit_current_pairs(*, get, run_id, now, expected_owner_sha, closed_round=None):
    """Raise on selected bad/missing evidence; return only flat unqualified counts."""
    diagnostic = {'phase': 'PAIR_PREFLIGHT'}
    try:
        options={} if closed_round is None else dict(closed_round=closed_round)
        return _audit(get, run_id, now, expected_owner_sha, _diagnostic=diagnostic,**options)
    except Exception as error:
        # The trusted workflow preserves its prior independent core proof and
        # emits static UNKNOWN/HOLD fields. Never echo private exception values.
        failure = ValueError('CURRENT_PAIR_AUDIT_REJECTED')
        failure._current_pair_diagnostic = _current_pair_failure_values(error, diagnostic['phase'])
        if (_current_pair_exact_cutoff_error(error)
                and type(diagnostic.get('phase')) is str and diagnostic['phase'] == 'PAIR_RESULT_JOIN'
                and 'cutoff_inventory' in diagnostic):
            failure._current_pair_diagnostic['cutoff_inventory'] = _current_pair_cutoff_projection(
                diagnostic['cutoff_inventory'])
        raise failure from None
