"""Private saved native rounds joined to separately authenticated outcomes.

The caller fetches actual GitHub metadata independently and authenticates the
official observation journal. This module performs no transport, grants no
source permission and never reconstructs missing native inputs from outcomes.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import io
import re
import stat
import zipfile
import zlib

from .actions_contract import digest
from . import all_existing_model_registry as registry
from . import boat_all_model_cycle as engine, boat_all_model_store as store
from .all_existing_model_intake import _results, _ordinary_result
from .boat_pdca_state import state_key
from .existing_model_dispatch import _race_key

MAX_ARCHIVE_BYTES = 40 * 1024 * 1024
SCHEMA = 'RACE_AI_ALL_EXISTING_MODEL_ROUND_INTAKE_COUNTS_V1'
STAGE_BINDING = 'CANONICAL_INPUT_FROM_FROZEN_NATIVE_AND_SAVED_STAGE'


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_ROUND_INTAKE_' + reason)


def _time(value):
    _need(type(value) is str and 0 < len(value) <= 64, 'AWARE_TIME_REQUIRED')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(result.utcoffset() is not None, 'AWARE_TIME_REQUIRED')
        return result
    except ValueError as exc:
        raise ValueError('ALL_MODEL_ROUND_INTAKE_AWARE_TIME_REQUIRED') from exc


def _metadata(raw, metadata, now, expected_run_id, expected_head_sha):
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    _need(type(expected_run_id) is int and 0 < expected_run_id < 10**20 and
          type(expected_head_sha) is str and re.fullmatch('[a-f0-9]{40}', expected_head_sha),
          'EXPECTED_RUN_INVALID')
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE_BYTES, 'ZIP_BOUND_INVALID')
    _need(type(metadata) is dict and type(metadata.get('id')) is int and metadata['id'] > 0 and
          metadata.get('expired') is False, 'ARTIFACT_IDENTITY_INVALID')
    name = metadata.get('name')
    match = re.fullmatch('boat-all-model-forecasts-'+str(expected_run_id)+r'-r(0|[1-9][0-9]{0,5})',
                         name) if type(name) is str else None
    _need(match is not None, 'ARTIFACT_NAME_INVALID')
    run = metadata.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int and run['id'] == expected_run_id and
          all(type(run.get(k)) is int and run[k] == int(engine.REPO_ID)
              for k in ('repository_id', 'head_repository_id')) and run.get('head_sha') == expected_head_sha,
          'ARTIFACT_RUN_INVALID')
    _need(type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes'] == len(raw) and
          metadata.get('digest') == 'sha256:'+sha256(raw).hexdigest(), 'ARTIFACT_BYTES_INVALID')
    saved = _time(metadata.get('created_at'))
    _need(saved <= now < _time(metadata.get('expires_at')), 'ARTIFACT_CLOCK_INVALID')
    return saved, int(match[1])


def _cipher(raw):
    # No ZIP prefix/suffix padding, comments, directories or unrelated members.
    _need(raw.startswith(b'PK\x03\x04') and len(raw) >= 22 and
          raw[-22:-18] == b'PK\x05\x06' and raw[-2:] == b'\0\0', 'ZIP_ENVELOPE_INVALID')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            _need(len(entries) == 1 and archive.comment == b'', 'ZIP_MEMBERS_INVALID')
            entry = entries[0]
            _need(entry.filename == entry.orig_filename == 'forecasts.enc' and
                  stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG) and
                  0 < entry.file_size <= store.MAX_WIRE and not entry.flag_bits & 0x41 and
                  entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'ZIP_MEMBER_INVALID')
            with archive.open(entry) as stream:
                cipher = stream.read(store.MAX_WIRE+1)
            _need(0 < len(cipher) == entry.file_size <= store.MAX_WIRE, 'ZIP_MEMBER_BOUND_INVALID')
            return cipher
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ValueError('ALL_MODEL_ROUND_INTAKE_ZIP_REJECTED') from exc


def _model_input(group, frozen, stage):
    """Bind the separately saved stage explicitly, preserving the frozen value."""
    _need(stage in ('P0', 'P1') and type(frozen) is dict, 'SAVED_STAGE_INVALID')
    _need('stage' not in frozen or frozen['stage'] == stage, 'CONFLICTING_NATIVE_STAGE')
    native = deepcopy(frozen)
    if group in ('shared', 'shared_learned', 'boat_full'):
        native['stage'] = stage
    return native


def records_from_round_artifact(raw, actual_metadata, observations, *, now,
                                expected_run_id, expected_head_sha):
    """Return private training records and aggregate counts from an actual ZIP.

    Owner-key readiness precedes metadata/ZIP/observation inspection. Actual
    artifact bytes, identity and current expiry precede authenticated native
    replay. Observation authenticity belongs to the caller; only independently
    verified ordinary labels may be supplied here. Retained owner MACs cannot
    refresh an expired GitHub receipt through this live-artifact API.
    """
    key = state_key('production')
    saved, round_no = _metadata(raw, actual_metadata, now, expected_run_id, expected_head_sha)
    cipher = _cipher(raw)
    payload = store.open_forecasts(cipher, key=key)
    header = store.forecast_header(cipher)
    _need(header['run_id'] == str(expected_run_id) and header['round_no'] == round_no and
          payload.get('schema') == engine.SCHEMA and payload.get('source_code_commit') == expected_head_sha and
          str(payload.get('run_id')) == str(expected_run_id), 'PAYLOAD_IDENTITY_INVALID')
    _need(_time(payload['generated_at']) <= now, 'FUTURE_GENERATION')
    proof = dict(repository_id=engine.REPO_ID, repository=engine.REPO, run_id=str(expected_run_id),
        head_sha=expected_head_sha, artifact_id=actual_metadata['id'], created_at=actual_metadata['created_at'],
        payload_sha256=digest(payload), independently_verified=True)
    # This authenticates the receipt binding and invokes native capsule replay.
    # No result parsing precedes the owner decryption and full native replay.
    engine.project_round(payload, proof)
    capsules = deepcopy(payload.get('native_input_capsules', []))
    precision_end = saved+timedelta(seconds=1)
    unique = {}; duplicate_inputs = 0; captured = 0; groups = 0
    for capsule in capsules:
        generated = _time(capsule['generated_at'])
        _need(generated <= now and generated < precision_end, 'GENERATION_RECEIPT_CLOCK_INVALID')
        for group, frozen in capsule['native_inputs'].items():
            groups += 1
            for mid in capsule['group_model_ids'][group]:
                captured += 1
                native = _model_input(group, frozen, capsule['stage'])
                info = registry.identity(mid, capsule['sport'], native)
                _need(info['stage'] == capsule['stage'] and
                      _race_key(info['race_id'], capsule['sport']) == _race_key(capsule['race_id'], capsule['sport']),
                      'NATIVE_IDENTITY_INVALID')
                _need(_time(info['as_of']) <= generated and precision_end < _time(info['cutoff_at']),
                      'INPUT_PRE_CUTOFF_RECEIPT_REQUIRED')
                _need(digest(frozen) == capsule['native_payload_sha256'][group], 'FROZEN_NATIVE_HASH_INVALID')
                cell = registry.cell_key(capsule['sport'], mid)
                identity = (cell, _race_key(info['race_id'], capsule['sport']))
                item = dict(model_id=mid, sport=capsule['sport'], group=group, cell_key=cell,
                    frozen=frozen, native=native, info=info, capsule=capsule)
                if identity in unique:
                    previous = unique[identity]
                    _need(digest(previous['native']) == digest(native) and previous['info'] == info,
                          'CONFLICTING_NATIVE_INPUT')
                    duplicate_inputs += 1
                    continue
                unique[identity] = item
    # Original archives without newly frozen inputs are authenticated but do
    # not become reconstructed historical training examples.
    missing_capsules = 'native_input_capsules' not in payload
    indexed, duplicate_results = _results(observations, now) if not missing_capsules else ({}, 0)
    base_receipt = dict(artifact_id=actual_metadata['id'], artifact_name=actual_metadata['name'],
        digest=actual_metadata['digest'], workflow_run_id=expected_run_id, head_sha=expected_head_sha,
        saved_at=actual_metadata['created_at'], payload_sha256=digest(payload),
        round_no=round_no, cipher_sha256=sha256(cipher).hexdigest(),
        artifact_metadata=deepcopy(actual_metadata), authenticated_original_artifact_verified=True,
        independent_pre_cutoff_receipt_verified=bool(unique))
    records = []; excluded = Counter(); used_results = set()
    for (cell, canonical_race), retained in sorted(unique.items()):
        result_key = (retained['sport'], canonical_race)
        if result_key not in indexed:
            excluded['missing'] += 1
            continue
        used_results.add(result_key)
        source = indexed[result_key]
        result, reason = _ordinary_result(source['result'], retained['info'], now)
        if reason is not None:
            excluded[reason] += 1
            continue
        info = retained['info']; capsule = retained['capsule']; native = retained['native']
        input_receipt = dict(base_receipt, capsule_sha256=capsule['capsule_sha256'],
            dispatch_input_sha256=capsule['dispatch_input_sha256'],
            frozen_native_input_sha256=digest(retained['frozen']), model_input_sha256=digest(native),
            saved_stage=capsule['stage'], stage_binding_semantics=STAGE_BINDING,
            native_group=retained['group'])
        records.append(dict(model_id=retained['model_id'], sport=retained['sport'], race_id=info['race_id'],
            stage=info['stage'], scope=info['scope'], as_of=info['as_of'], cutoff_at=info['cutoff_at'],
            native_payload=deepcopy(native), input_sha256=digest(native),
            frozen_native_payload=deepcopy(retained['frozen']), input_saved_at=actual_metadata['created_at'],
            input_receipt=input_receipt, input_partitions=[dict(native_group=retained['group'],
                capsule_sha256=capsule['capsule_sha256'], generated_at=capsule['generated_at'],
                dispatch_input_sha256=capsule['dispatch_input_sha256'])],
            result=result, result_observation=deepcopy(source['original'])))
    captured_cells = {cell for cell, _ in unique}
    applicable = {c['cell_key'] for c in registry.cells() if c['sport'] == 'boat'}
    summary = dict(schema=SCHEMA,
        state='NATIVE_INPUT_CAPSULES_MISSING' if missing_capsules else
              'AUTHENTICATED_NATIVE_RECORDS_READY' if records else 'NO_ORDINARY_SETTLED_NATIVE_RECORDS',
        artifact_id=actual_metadata['id'], artifact_digest=actual_metadata['digest'],
        workflow_run_id=expected_run_id, head_sha=expected_head_sha, round_no=round_no,
        payload_sha256=digest(payload), partition_count=len(capsules),
        registered_cell_count=len(registry.cells()), captured_cell_count=len(captured_cells),
        uncaptured_cell_count=len(registry.cells())-len(captured_cells),
        unavailable_model_cell_count=len(applicable-captured_cells), captured_native_group_count=groups,
        captured_native_input_count=captured, unique_native_input_count=len(unique),
        duplicate_native_input_count=duplicate_inputs, admitted_record_count=len(records),
        admitted_cell_count=len({(r['sport'], r['model_id']) for r in records}),
        record_counts_by_cell=dict(Counter(registry.cell_key(r['sport'], r['model_id']) for r in records)),
        missing_result_native_input_count=excluded['missing'], pending_result_native_input_count=excluded['pending'],
        special_result_native_input_count=excluded['special'], unmatched_result_count=len(set(indexed)-used_results),
        duplicate_result_count=duplicate_results, independent_pre_cutoff_receipt_verified=bool(unique),
        native_capsules_missing=missing_capsules, provider_permission_confirmed=False,
        training_permission_granted=False, historical_inputs_backfilled=False,
        production_promoted=False, actual_purchases=False, missing_results_are_not_losses=True,
        plaintext_published=False)
    return dict(records=records, summary=summary, receipt=base_receipt)
