"""Admit encrypted private P1 forecasts against actual GitHub artifact metadata.

The caller fetches metadata for its actual artifact ID. This reader performs no
network or Git operations. Its public API returns only aggregate proof; the
internal reader is shared by private result scoring after all races verify.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import io
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import zipfile
import zlib

from .actions_contract import digest
from .boat_pdca_state import state_key
from .boat_venue_dataset import _bytes
from .boat_venue_learning import read_candidate
from .boat_venue_learning_context import MEMBER_LIMITS
from .boat_venue_research_forecast import SCHEMA, verify_private_forecast
from .frozen_day_cycle import official_id
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _write

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_RACES = 24 * 12  # Physical archive bound; never a pilot prediction cap.
REPOSITORY_ID = 1416489937
MAX_RESEARCH_REFS = 10_000


def _need(ok, reason):
    if not ok:
        raise ValueError('VENUE_PRIVATE_P1_RECEIPT_' + reason)


def validate_research_refs(values):
    """Normalize continuity handles only; these references never admit an artifact."""
    _need(type(values) is list and len(values) <= MAX_RESEARCH_REFS, 'REFERENCES_BOUND_INVALID')
    by_id = {}
    for value in values:
        _need(type(value) is dict and set(value) == {'artifact_id', 'run_id', 'head_sha', 'digest'} and
              all(type(value.get(key)) is int and value[key] > 0 for key in ('artifact_id', 'run_id')) and
              type(value.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}', value['head_sha']) and
              type(value.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}', value['digest']),
              'REFERENCE_INVALID')
        old = by_id.setdefault(value['artifact_id'], value)
        _need(old == value, 'REFERENCE_ID_CONFLICT')
    return [deepcopy(by_id[artifact_id]) for artifact_id in sorted(by_id)]


def _timestamp(value):
    _need(type(value) is str and 0 < len(value) <= 64, 'AWARE_TIME_REQUIRED')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(result.utcoffset() is not None, 'AWARE_TIME_REQUIRED')
        return result
    except ValueError as exc:
        raise ValueError('VENUE_PRIVATE_P1_RECEIPT_AWARE_TIME_REQUIRED') from exc


def _metadata(raw, metadata, now, expected_run_id, expected_head_sha):
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    _need(type(expected_run_id) is int and expected_run_id > 0 and
          type(expected_head_sha) is str and re.fullmatch('[a-f0-9]{40}', expected_head_sha),
          'EXPECTED_RUN_INVALID')
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE_BYTES, 'ZIP_SIZE_INVALID')
    _need(type(metadata) is dict and type(metadata.get('id')) is int and metadata['id'] > 0 and
          metadata.get('expired') is False, 'ARTIFACT_IDENTITY_INVALID')
    name = metadata.get('name')
    _need(type(name) is str and len(name) <= 200 and
          re.fullmatch('boat-venue-research-p1-'+str(expected_run_id)+'-[1-9][0-9]*', name),
          'ARTIFACT_NAME_INVALID')
    run = metadata.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int and run['id'] == expected_run_id and
          all(type(run.get(key)) is int and run[key] == REPOSITORY_ID
              for key in ('repository_id', 'head_repository_id')) and
          run.get('head_sha') == expected_head_sha, 'ARTIFACT_RUN_INVALID')
    _need(type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes'] == len(raw) and
          metadata.get('digest') == 'sha256:'+hashlib.sha256(raw).hexdigest(), 'ARTIFACT_BYTES_INVALID')
    saved = _timestamp(metadata.get('created_at'))
    _need(saved <= now < _timestamp(metadata.get('expires_at')), 'ARTIFACT_CLOCK_INVALID')
    return saved


def _entries(archive):
    entries = archive.infolist()
    _need(3 <= len(entries) <= 3*MAX_RACES and
          len(entries) == len({entry.filename for entry in entries}), 'ZIP_MEMBERS_INVALID')
    groups = {}
    for entry in entries:
        _need(entry.filename == entry.orig_filename and '\0' not in entry.filename,
              'ZIP_PATH_INVALID')
        match = re.fullmatch(r'([0-9]{8}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2]))/'
                             r'(learning\.json|learning\.enc|summary\.json)', entry.filename)
        _need(match is not None, 'ZIP_PATH_INVALID')
        race_id, name = match.groups()
        try:
            date.fromisoformat(race_id[:4]+'-'+race_id[4:6]+'-'+race_id[6:8])
        except ValueError as exc:
            raise ValueError('VENUE_PRIVATE_P1_RECEIPT_ZIP_PATH_INVALID') from exc
        kind = stat.S_IFMT(entry.external_attr >> 16)
        _need(0 < entry.file_size <= MEMBER_LIMITS[name] and not entry.flag_bits & 0x41 and
              kind in (0, stat.S_IFREG) and
              entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'ZIP_MEMBER_INVALID')
        groups.setdefault(race_id, {})[name] = entry
    _need(1 <= len(groups) <= MAX_RACES and
          all(set(group) == set(MEMBER_LIMITS) for group in groups.values()) and
          sum(entry.file_size for entry in entries) <= MAX_ARCHIVE_BYTES, 'ZIP_CONTENT_BOUND_INVALID')
    return groups


def _payload_clock(payload, saved, now):
    generated = _timestamp(payload['generated_at'])
    as_of = _timestamp(payload['snapshot']['as_of'])
    cutoff = _timestamp(payload['snapshot']['sales_cutoff_at'])
    precision_end = saved+timedelta(seconds=1)
    _need(generated == as_of and generated <= now and generated < precision_end and
          precision_end < cutoff, 'PRE_CUTOFF_CLOCK_INVALID')
    receipt = payload['training_receipt']
    run = receipt.get('workflow_run')
    _need(type(receipt.get('id')) is int and receipt['id'] > 0 and receipt.get('expired') is False and
          type(receipt.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}', receipt['digest']) and
          type(run) is dict and type(run.get('id')) is int and run['id'] > 0 and
          all(type(run.get(key)) is int and run[key] == REPOSITORY_ID
              for key in ('repository_id', 'head_repository_id')), 'TRAINING_RECEIPT_INVALID')
    _need(_timestamp(receipt.get('created_at'))+timedelta(seconds=1) <= as_of,
          'TRAINING_RECEIPT_CLOCK_INVALID')
    if 'expires_at' in receipt:
        _need(as_of < _timestamp(receipt['expires_at']), 'TRAINING_RECEIPT_EXPIRED_AT_INPUT')


def _verified_private_p1_artifact(raw, metadata, *, now, expected_run_id, expected_head_sha):
    """Internal scoring boundary: return private payloads only after full admission."""
    state_key('production')  # Key readiness precedes ZIP or metadata inspection.
    saved = _metadata(raw, metadata, now, expected_run_id, expected_head_sha)
    payloads = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            groups = _entries(archive)  # Validate every entry before decompressing any.
            with tempfile.TemporaryDirectory(prefix='boat-private-p1-receipt-') as temporary:
                for index, (race_id, group) in enumerate(sorted(groups.items())):
                    root = Path(temporary)/str(index)
                    root.mkdir(mode=0o700)
                    files = {}
                    for name, entry in group.items():
                        with archive.open(entry) as stream:
                            body = stream.read(MEMBER_LIMITS[name]+1)
                        _need(len(body) == entry.file_size and 0 < len(body) <= MEMBER_LIMITS[name],
                              'ZIP_MEMBER_SIZE_INVALID')
                        files[name] = body
                        _write(root/name, body)
                    payload = read_candidate(root)
                    _need(type(payload) is dict and payload.get('schema') == SCHEMA and
                          type(payload.get('summary')) is dict and
                          payload['summary'].get('state') == 'ENCRYPTED_PRIVATE_VENUE_P1_LOCAL_ONLY',
                          'PAYLOAD_SCHEMA_INVALID')
                    public = read_json_bytes(files['summary.json'])
                    expected = dict(payload['summary'], encrypted_readback_verified=True, plaintext_published=False)
                    _need(_bytes(public) == _bytes(expected), 'PUBLIC_SUMMARY_BINDING_INVALID')
                    _need(verify_private_forecast(payload) is True, 'PAYLOAD_REPLAY_INVALID')
                    _need(official_id(payload['snapshot']['race_id']) == race_id,
                          'PAYLOAD_RACE_DIRECTORY_MISMATCH')
                    _payload_clock(payload, saved, now)
                    payloads.append(payload)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, KeyError, TypeError,
            AttributeError, sqlite3.Error, zlib.error, EOFError) as exc:
        raise ValueError('VENUE_PRIVATE_P1_RECEIPT_ARCHIVE_REJECTED') from exc
    _need(len({payload['training']['training_sha256'] for payload in payloads}) == 1 and
          len({digest(payload['dataset_pointer']) for payload in payloads}) == 1 and
          len({digest(payload['training_receipt']) for payload in payloads}) == 1,
          'MIXED_CANDIDATE_CONTEXTS_INVALID')
    summary = dict(schema='RACE_AI_PRIVATE_VENUE_P1_ARTIFACT_ADMISSION_COUNTS_V1',
                   status='PRIVATE_VENUE_P1_ARTIFACT_PRE_CUTOFF_VERIFIED',
                   artifact_id=metadata['id'], artifact_name=metadata['name'], artifact_digest=metadata['digest'],
                   workflow_run_id=expected_run_id, head_sha=expected_head_sha, saved_at=metadata['created_at'],
                   unique_races=len(payloads), baseline_forecast_count=2*len(payloads),
                   learned_forecast_count=2*len(payloads), record_sha256=[digest(p) for p in payloads],
                   training_sha256=payloads[0]['training']['training_sha256'],
                   independent_pre_cutoff_receipt_verified=True, provider_permission_confirmed=False,
                   production_promoted=False, actual_purchases=False, plaintext_published=False)
    return summary, payloads


def verify_private_p1_artifact(raw, metadata, *, now, expected_run_id, expected_head_sha):
    """Return aggregate proof only; callers must supply independently read metadata."""
    summary, _ = _verified_private_p1_artifact(raw, metadata, now=now,
        expected_run_id=expected_run_id, expected_head_sha=expected_head_sha)
    return summary
