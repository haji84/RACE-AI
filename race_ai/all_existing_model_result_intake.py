"""Private result labels from actual owner-encrypted GitHub RESULT artifacts.

The caller must fetch ``metadata`` from the actual GitHub artifact endpoint,
independently of its cached files, and supply that artifact's unchanged ZIP
bytes. A caller-created metadata dictionary is not an external save receipt.
This boundary performs no HTTP, Git, extraction, fitting or publication. The
owner envelope authenticates the producer's captured journal, not an upstream
publication time or new source-use permission.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re

from .actions_contract import digest
from .all_existing_model_intake import _legacy_boat, _ordinary_result
from .boat_active_roster import active_roster
from .boat_pdca_state import state_key
from .boat_private_original_archive import CIPHER_MEMBER, _checked_zip, open_original_zip
from .first_receipt_continuity import latest_result_observations
from .observed_p1_connection import locator
from .repeated_cycle import matches

MAX_ARCHIVE_BYTES = 32*1024*1024+64*1024
MAX_MEMBER_BYTES = 16*1024*1024
MAX_OBSERVATIONS = 10000
REPOSITORY_ID = 1416489937
SCHEMA = 'RACE_AI_ALL_EXISTING_MODEL_RESULT_INTAKE_COUNTS_V1'
JST = timezone(timedelta(hours=9))


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_RESULT_INTAKE_'+reason)


def _time(value):
    _need(type(value) is str and 0 < len(value) <= 64, 'AWARE_CLOCK_REQUIRED')
    try:
        clock = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(clock.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        return clock
    except ValueError:
        raise ValueError('ALL_MODEL_RESULT_INTAKE_AWARE_CLOCK_REQUIRED') from None


def _json(raw):
    def unique(items):
        value = {}
        for key, item in items:
            _need(key not in value, 'DUPLICATE_JSON_KEY')
            value[key] = item
        return value
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
            parse_constant=lambda _: _need(False, 'NONFINITE_JSON'))
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('ALL_MODEL_RESULT_INTAKE_JSON_INVALID') from None


def _metadata(raw, metadata, now, run_id, head_sha):
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    _need(type(run_id) is int and 0 < run_id < 10**20 and type(head_sha) is str and
          re.fullmatch('[a-f0-9]{40}', head_sha), 'EXPECTED_RUN_INVALID')
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE_BYTES, 'ARCHIVE_BOUND_INVALID')
    _need(type(metadata) is dict and type(metadata.get('id')) is int and
          0 < metadata['id'] < 10**20 and metadata.get('expired') is False,
          'ARTIFACT_IDENTITY_INVALID')
    name = metadata.get('name')
    _need(type(name) is str and len(name) <= 200 and
          matches(name, 'race-existing-cycle-'+str(run_id)), 'ARTIFACT_NAME_INVALID')
    run = metadata.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int and run['id'] == run_id and
          all(type(run.get(key)) is int and run[key] == REPOSITORY_ID
              for key in ('repository_id', 'head_repository_id')) and
          run.get('head_sha') == head_sha, 'ARTIFACT_RUN_INVALID')
    _need(type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes'] == len(raw) and
          metadata.get('digest') == 'sha256:'+sha256(raw).hexdigest(), 'ARTIFACT_BYTES_INVALID')
    saved = _time(metadata.get('created_at'))
    _need(saved <= now < _time(metadata.get('expires_at')), 'ARTIFACT_CLOCK_INVALID')
    return saved


def _observation(row, *, day, saved, now):
    _need(type(row) is dict, 'OBSERVATION_INVALID')
    rid = row.get('race_id')
    _need(type(rid) is str and re.fullmatch(
        r'[0-9]{8}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])', rid) and
        rid[:8] == day.replace('-', ''), 'RESULT_RACE_INVALID')
    locator(row.get('source_url'), 'raceresult', rid)
    _need(type(row.get('source_sha256')) is str and
          re.fullmatch('[a-f0-9]{64}', row['source_sha256']), 'RESULT_SOURCE_HASH_INVALID')
    _need(row.get('kind', 'raceresult') == 'raceresult' and
          row.get('information_phase', 'official_result') == 'official_result' and
          row.get('status') in ('AVAILABLE', 'PENDING', 'PARTIAL', 'UNAVAILABLE'),
          'RESULT_SOURCE_KIND_INVALID')
    captured = _time(row.get('captured_at'))
    _need(captured <= now and captured < saved+timedelta(seconds=1), 'RESULT_CAPTURE_CLOCK_INVALID')
    for field in ('available_at', 'published_at', 'upstream_published_at'):
        if row.get(field) is not None:
            _need(_time(row[field]) <= captured, 'RESULT_PUBLICATION_CLOCK_INVALID')
    closed = _time(row['closed_at']) if row.get('closed_at') is not None else None
    if closed is not None:
        _need(closed.astimezone(JST).date().isoformat() == day, 'RESULT_CUTOFF_DAY_INVALID')
    data = row.get('data')
    _need(data is None or type(data) is dict, 'RESULT_DATA_INVALID')
    if row['status'] == 'AVAILABLE':
        _need(row.get('body_identity_verified') is True and closed is not None and
              type(data) is dict, 'RESULT_BODY_IDENTITY_INVALID')
    rows = data.get('results', []) if data is not None else []
    _need(type(rows) is list and len(rows) <= 6, 'RESULT_ROSTER_INVALID')
    if rows:
        active_roster(rows, identity_key='racer_registration_id')
        _need(all(item.get('race_id', rid) == rid and item.get('verified_official', True) is True
                  for item in rows), 'RESULT_REGISTERED_ROSTER_INVALID')
    if row['status'] == 'AVAILABLE' and data.get('status') in ('special', 'dead_heat'):
        return 'special'
    # Existing conversion preserves ordinary/special/pending semantics and does
    # not invent a publication time for the old captured-result format.
    converted = _legacy_boat(row)
    if converted['status'] != 'settled':
        return converted['status']
    _need(closed is not None and captured >= closed, 'RESULT_BEFORE_ACTUAL_CUTOFF')
    _ordinary_result(converted, dict(race_id=rid, race_cutoff_at=row['closed_at'],
        roster=converted['roster']), now)
    return 'settled'


def observations_from_result_artifact(raw, metadata, *, now, expected_run_id, expected_head_sha):
    """Return latest private revisions after complete encrypted receipt admission.

    Every original revision is validated before newest-per-race selection. A
    newer pending/special capture therefore cannot fall back to an older win.
    The receipt binds the complete original journal and revision inventory;
    callers retain the original encrypted archive to preserve those raw bytes.
    """
    state_key('production')  # Before metadata, ZIP or journal parsing.
    saved = _metadata(raw, metadata, now, expected_run_id, expected_head_sha)
    try:
        with _checked_zip(raw, max_zip_bytes=MAX_ARCHIVE_BYTES) as outer:
            _need(outer.namelist() == [CIPHER_MEMBER], 'ENCRYPTED_RESULT_REQUIRED')
        with open_original_zip(raw, metadata, expected_kind='RESULT',
                               max_plain_zip_bytes=32*1024*1024) as archive:
            def member(name):
                _need(name in archive.namelist() and
                      0 < archive.getinfo(name).file_size <= MAX_MEMBER_BYTES, 'JOURNAL_MEMBER_INVALID')
                body = archive.read(name)
                return _json(body), sha256(body).hexdigest()
            observations, body_sha = member('official-result-observations.json')
            report, report_body_sha = member('status.json')
        _need(type(observations) is list and len(observations) <= MAX_OBSERVATIONS,
              'BOUNDED_OBSERVATIONS_REQUIRED')
        _need(type(report) is dict and report.get('schema') == 'RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1' and
              report.get('report_sha256') == digest({key:value for key,value in report.items()
                                                    if key != 'report_sha256'}), 'RESULT_REPORT_HASH_INVALID')
        day = report.get('day_jst')
        _need(type(day) is str and re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', day) and
              datetime.fromisoformat(day).date().isoformat() == day, 'RESULT_DAY_INVALID')
        _need(str(report.get('run_id')) == str(expected_run_id) and
              report.get('code_sha') == expected_head_sha and
              type(report.get('result_observation_versions')) is int and
              report['result_observation_versions'] == len(observations), 'RESULT_REPORT_BINDING_INVALID')
        updated = _time(report.get('updated_at'))
        _need(updated <= now and updated < saved+timedelta(seconds=1), 'RESULT_REPORT_CLOCK_INVALID')
        states = {}; capture_identities = {}
        for row in observations:
            state = _observation(row, day=day, saved=saved, now=now)
            _need(_time(row['captured_at']) <= updated, 'RESULT_REPORT_PRECEDES_CAPTURE')
            identity = (row['race_id'], _time(row['captured_at']))
            fingerprint = digest(row)
            _need(identity not in capture_identities or capture_identities[identity] == fingerprint,
                  'CONFLICTING_RESULT_CAPTURE')
            capture_identities[identity] = fingerprint
            states[(row['race_id'], row['captured_at'])] = state
        latest, journal = latest_result_observations(observations)
        counts = Counter(states[(row['race_id'], row['captured_at'])] for row in latest)
        receipt = dict(artifact_id=metadata['id'], artifact_name=metadata['name'],
            digest=metadata['digest'], workflow_run_id=expected_run_id, head_sha=expected_head_sha,
            saved_at=metadata['created_at'], expires_at=metadata['expires_at'],
            artifact_metadata=deepcopy(metadata), original_journal_body_sha256=body_sha,
            original_journal_sha256=digest(observations), report_body_sha256=report_body_sha,
            report_sha256=report['report_sha256'], journal_index=[dict(race_id=row['race_id'],
                captured_at=row['captured_at'], observation_sha256=digest(row)) for row in journal],
            authenticated_encrypted_result_artifact=True)
        summary = dict(schema=SCHEMA, state='AUTHENTICATED_RESULT_OBSERVATIONS_READY',
            artifact_id=metadata['id'], artifact_digest=metadata['digest'],
            workflow_run_id=expected_run_id, head_sha=expected_head_sha,
            original_observation_count=len(observations), unique_revision_count=len(journal),
            duplicate_revision_count=len(observations)-len(journal), latest_observation_count=len(latest),
            ordinary_settled_result_count=counts['settled'], pending_result_count=counts['pending'],
            special_result_count=counts['special'], authenticated_encrypted_result_artifact=True,
            missing_results_are_not_losses=True, provider_permission_confirmed=False,
            production_promoted=False, actual_purchases=False, plaintext_published=False)
        return dict(observations=deepcopy(latest), summary=summary, receipt=receipt)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as exc:
        raise ValueError('ALL_MODEL_RESULT_INTAKE_ARCHIVE_INVALID') from exc
