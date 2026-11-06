"""Actual GitHub artifact admission for encrypted native research pairs.

No HTTP or Git is performed here. The public reader exposes aggregate proof;
the private reader shares fully authenticated records with native PDCA only.
"""
from datetime import datetime, timedelta
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
from .all_existing_model_pairs import (
    SCHEMA, INPUTS_SCHEMA, record_partition_key, record_identity, verify_private_record,
)
from .boat_pdca_state import state_key
from .boat_venue_learning import read_candidate
from .boat_venue_learning_context import MEMBER_LIMITS
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _write

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_PARTITIONS = 16_384
REPOSITORY_ID = 1416489937


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_PAIR_RECEIPT_' + reason)


def _time(value):
    _need(type(value) is str and 0 < len(value) <= 64, 'AWARE_TIME_REQUIRED')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(result.utcoffset() is not None, 'AWARE_TIME_REQUIRED')
        return result
    except ValueError as exc:
        raise ValueError('ALL_MODEL_PAIR_RECEIPT_AWARE_TIME_REQUIRED') from exc


def _metadata(raw, metadata, now, expected_run_id, expected_head_sha):
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    _need(type(expected_run_id) is int and expected_run_id > 0 and
          type(expected_head_sha) is str and re.fullmatch('[a-f0-9]{40}', expected_head_sha),
          'EXPECTED_RUN_INVALID')
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE_BYTES, 'ZIP_SIZE_INVALID')
    _need(type(metadata) is dict and type(metadata.get('id')) is int and metadata['id'] > 0 and
          metadata.get('expired') is False, 'ARTIFACT_IDENTITY_INVALID')
    name = metadata.get('name')
    _need(type(name) is str and len(name) <= 200 and re.fullmatch(
          'all-existing-model-pairs-'+str(expected_run_id)+'-[1-9][0-9]*', name), 'ARTIFACT_NAME_INVALID')
    run = metadata.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int and run['id'] == expected_run_id and
          all(type(run.get(k)) is int and run[k] == REPOSITORY_ID
              for k in ('repository_id', 'head_repository_id')) and
          run.get('head_sha') == expected_head_sha, 'ARTIFACT_RUN_INVALID')
    _need(type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes'] == len(raw) and
          metadata.get('digest') == 'sha256:'+hashlib.sha256(raw).hexdigest(), 'ARTIFACT_BYTES_INVALID')
    saved = _time(metadata.get('created_at'))
    _need(saved <= now < _time(metadata.get('expires_at')), 'ARTIFACT_CLOCK_INVALID')
    return saved


def _entries(archive):
    entries = archive.infolist()
    _need(3 <= len(entries) <= 3*MAX_PARTITIONS and
          len(entries) == len({entry.filename for entry in entries}), 'ZIP_MEMBERS_INVALID')
    groups = {}
    for entry in entries:
        _need(entry.filename == entry.orig_filename and '\0' not in entry.filename, 'ZIP_PATH_INVALID')
        match = re.fullmatch(r'([a-f0-9]{64})/(learning\.json|learning\.enc|summary\.json)', entry.filename)
        _need(match is not None, 'ZIP_PATH_INVALID')
        key, name = match.groups(); kind = stat.S_IFMT(entry.external_attr >> 16)
        _need(0 < entry.file_size <= MEMBER_LIMITS[name] and not entry.flag_bits & 0x41 and
              kind in (0, stat.S_IFREG) and
              entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'ZIP_MEMBER_INVALID')
        groups.setdefault(key, {})[name] = entry
    _need(1 <= len(groups) <= MAX_PARTITIONS and
          all(set(group) == set(MEMBER_LIMITS) for group in groups.values()) and
          sum(entry.file_size for entry in entries) <= MAX_ARCHIVE_BYTES, 'ZIP_CONTENT_BOUND_INVALID')
    return groups


def _payload_clock(payload, saved, now):
    generated = _time(payload['generated_at'])
    precision_end = saved+timedelta(seconds=1)
    _need(generated <= now and generated < precision_end, 'PRE_CUTOFF_CLOCK_INVALID')
    if payload.get('schema') != INPUTS_SCHEMA:
        pair = payload['pair']; as_of = _time(pair['as_of']); cutoff = _time(pair['cutoff_at'])
        _need(generated == as_of and precision_end < cutoff, 'PRE_CUTOFF_CLOCK_INVALID')
    for capsule in payload.get('captured_native_inputs', []):
        _need(_time(capsule['captured_as_of']) <= generated and
              precision_end < _time(capsule['cutoff_at']), 'CAPTURED_INPUT_PRE_CUTOFF_CLOCK_INVALID')


def _verified_private_pairs_artifact(raw, metadata, *, now, expected_run_id, expected_head_sha):
    """Return private records only after every archive member has been admitted."""
    state_key('production')  # Authentication readiness precedes metadata and ZIP parsing.
    saved = _metadata(raw, metadata, now, expected_run_id, expected_head_sha)
    payloads = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            groups = _entries(archive)
            with tempfile.TemporaryDirectory(prefix='all-model-private-pair-receipt-') as temporary:
                for index, (key, group) in enumerate(sorted(groups.items())):
                    root = Path(temporary)/str(index); root.mkdir(mode=0o700)
                    files = {}
                    for name, entry in group.items():
                        with archive.open(entry) as stream:
                            body = stream.read(MEMBER_LIMITS[name]+1)
                        _need(len(body) == entry.file_size and 0 < len(body) <= MEMBER_LIMITS[name],
                              'ZIP_MEMBER_SIZE_INVALID')
                        files[name] = body; _write(root/name, body)
                    payload = read_candidate(root)
                    _need(type(payload) is dict and payload.get('schema') in (SCHEMA, INPUTS_SCHEMA) and
                          type(payload.get('summary')) is dict, 'PAYLOAD_SCHEMA_INVALID')
                    public = read_json_bytes(files['summary.json'])
                    _need(public == dict(payload['summary'], encrypted_readback_verified=True,
                                         plaintext_published=False), 'PUBLIC_SUMMARY_BINDING_INVALID')
                    _need(verify_private_record(payload) is True, 'PAYLOAD_REPLAY_INVALID')
                    _need(record_partition_key(payload) == key, 'PAYLOAD_DIRECTORY_MISMATCH')
                    _payload_clock(payload, saved, now)
                    payloads.append(payload)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, KeyError, TypeError,
            AttributeError, sqlite3.Error, zlib.error, EOFError) as exc:
        raise ValueError('ALL_MODEL_PAIR_RECEIPT_ARCHIVE_REJECTED') from exc
    _need(len({p['training']['training_sha256'] for p in payloads}) == 1 and
          len({digest(p['training_receipt']) for p in payloads}) == 1,
          'MIXED_CANDIDATE_CONTEXTS_INVALID')
    # The opaque directory binds sport/race/cell; duplicate ZIP names are already rejected.
    _need(len({record_partition_key(p) for p in payloads}) == len(payloads), 'DUPLICATE_CELL_RACE')
    forecasts = [p for p in payloads if p['schema'] == SCHEMA]
    input_only = [p for p in payloads if p['schema'] == INPUTS_SCHEMA]
    cells = sorted({p['cell_key'] for p in forecasts})
    summary = dict(schema='RACE_AI_PRIVATE_ALL_EXISTING_MODEL_ARTIFACT_COUNTS_V1',
        status='PRIVATE_NATIVE_PAIRS_ARTIFACT_PRE_CUTOFF_VERIFIED' if forecasts else
               'PRIVATE_NATIVE_INPUTS_ARTIFACT_PRE_CUTOFF_VERIFIED', artifact_id=metadata['id'],
        scope=payloads[0]['training']['scope'],
        artifact_name=metadata['name'], artifact_digest=metadata['digest'], workflow_run_id=expected_run_id,
        head_sha=expected_head_sha, saved_at=metadata['created_at'], partition_count=len(payloads),
        unique_races=len({record_identity(p) for p in payloads}),
        forecast_partition_count=len(forecasts), frozen_input_only_partition_count=len(input_only),
        cell_count=len(cells), cell_forecast_counts={cell: sum(p['cell_key'] == cell for p in forecasts) for cell in cells},
        baseline_forecast_count=len(forecasts), learned_forecast_count=len(forecasts),
        captured_native_input_count=sum(len(p.get('captured_native_inputs', [])) for p in payloads),
        captured_unfitted_native_input_count=sum(capsule['cell_key'] not in p['training']['models']
            for p in payloads for capsule in p.get('captured_native_inputs', [])),
        record_sha256=[digest(p) for p in payloads], training_sha256=payloads[0]['training']['training_sha256'],
        independent_pre_cutoff_receipt_verified=True, provider_permission_confirmed=False,
        production_promoted=False, actual_purchases=False, plaintext_published=False)
    return summary, payloads


def verify_private_pairs_artifact(raw, metadata, *, now, expected_run_id, expected_head_sha):
    """Return aggregate proof for raw ZIP bytes and independently fetched metadata."""
    summary, _ = _verified_private_pairs_artifact(raw, metadata, now=now,
        expected_run_id=expected_run_id, expected_head_sha=expected_head_sha)
    return summary
