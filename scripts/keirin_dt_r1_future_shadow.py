"""Produce only new, encrypted DT-R1 shadows from saved official-SP originals.

The existing protected main/manual study runtime remains the authority. This
module fetches only the existing GitHub archive and its independent source
evidence. Prior-day official results may supply history after independent
verification. It never reads a target-day result or calls a provider. Every registered race survives
as a saved candidate or HOLD. New model computation and local cipher readback
use actual clocks; original A/B clocks are never relabelled. Local readback is
not independent forecast admission, a three-way contest, or model promotion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import timedelta
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_run_history as codec
from race_ai.keirin_github_evidence_client import GitHubEvidenceClient, GitHubEvidenceError
from race_ai.keirin_github_origin_evidence import MAX_ARCHIVE_BYTES, OriginEvidenceError
from research.chatgpt_dt_r1 import back_official_shadow, codex_future_candidate, official_inputs
from research.chatgpt_dt_r1.abilities import augment_abilities
from research.chatgpt_dt_r1.agari import augment_agari
from research.chatgpt_dt_r1.context import augment_features
from research.chatgpt_dt_r1.model import RankModel
from research.chatgpt_dt_r1.official_history import OfficialHistory, POLICY as HISTORY_POLICY
from research.chatgpt_dt_r1.official_personal_history import POLICY as PERSONAL_HISTORY_POLICY
from research.chatgpt_dt_r1.official_personal_study import personal_trial
from research.chatgpt_dt_r1.pipeline import forecast_row, validate_prediction_inputs
from research.chatgpt_dt_r1.policy import checked_sha, clock as parse_clock, digest
from research.chatgpt_dt_r1.venues import VenueStore
from scripts import keirin_capture_official_form_history as capture_files
from scripts import keirin_official_nationwide_continuation as continuation


SCHEMA = 'DT_R1_FUTURE_SHADOW_MANIFEST_V1'
PRIVATE_SCHEMA = 'DT_R1_FUTURE_SHADOW_ORIGINAL_V1'
SUMMARY_SCHEMA = 'DT_R1_FUTURE_SHADOW_SUMMARY_V1'
CODEX_PRIVATE_SCHEMA = 'KEIRIN_CODEX_FUTURE_ORIGINAL_V1'
CODEX_SUMMARY_SCHEMA = 'KEIRIN_CODEX_FUTURE_SHADOW_SUMMARY_V1'
CODEX_MATERIAL_SCHEMA = 'KEIRIN_CODEX_SHARED_FUTURE_MATERIAL_V1'
CODEX_PEER_FIELDS = frozenset(('dt_producer_run_id', 'dt_manifest_sha256'))
CODEX_PEER_HOLD = 'SAVED_DT_PAIR_INPUT_MISSING'
LEGACY_MATERIAL_SCHEMA = 'DT_R1_SHARED_FUTURE_MATERIAL_V1'
HISTORY_MATERIAL_SCHEMA = 'DT_R1_SHARED_FUTURE_MATERIAL_V2'
PAIRED_HISTORY_MATERIAL_SCHEMA = 'DT_R1_SHARED_FUTURE_MATERIAL_V3'
BACK_STUDY_MATERIAL_SCHEMA = 'DT_R1_SHARED_FUTURE_MATERIAL_V4'
PERSONAL_STUDY_MATERIAL_SCHEMA = 'DT_R1_SHARED_FUTURE_MATERIAL_V5'
HISTORY_CONTROL_POLICY = 'DT_R1_FROZEN_SAME_SOURCE_NO_PRIOR_HISTORY_V1'
# Skip optional extra inference shortly before the mandatory production seal boundary.
PERSONAL_TRIAL_SEAL_RESERVE = timedelta(seconds=30)
PERSONAL_TRIAL_SOURCE_HOLDS = frozenset(('NO_REPLAYED_SEVEN_DAY_HISTORY', 'NO_AUTHENTICATED_PROFILE',
    'PROFILE_NOT_AVAILABLE_AT_PREDICTION', 'NO_ELIGIBLE_FINISHES', 'PROFILE_EVIDENCE_OR_FEATURE_REPLAY_UNVERIFIED',
    'PERSONAL_STUDY_DEADLINE_RESERVE', 'PERSONAL_STUDY_COMPUTE_UNVERIFIED', 'PERSONAL_STUDY_BINDING_UNVERIFIED'))
MODEL_FILE = 'research/chatgpt_dt_r1/evidence/20261128-resume/frozen_model.json'
MODEL_FILE_SHA = 'dab8c7f014c41ac18e4fed1ae28ac9b36e994611d1fcf5992f8b06e31a4c618b'
MODEL_SHA = '5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c'
VENUE_FILE = 'research/chatgpt_dt_r1/fixtures/venue_geometry.json'
VENUE_SHA = 'a7d832a2661c6f05167e7a412a55e51183c21e746447f91dac44e14eeb4dfe19'
INFERENCE_SOURCES = ('abilities.py', 'agari.py', 'context.py', 'data.py', 'features.py',
                     'model.py', 'observations.py', 'pipeline.py', 'policy.py', 'runtime.py', 'venues.py')
READY = 'SEALED_PENDING_INDEPENDENT_READBACK'
UPLOAD_BUDGET_HOLD = 'UPLOAD_BYTE_BUDGET_EXHAUSTED'
PRESERVED = 'PREVIOUS_T15_ORIGINAL_PRESERVED'
MAX_MANIFEST_BYTES = 2_000_000  # Manifest member limit in the independent reader.
# GitHub uploads this directory with ZIP compression level 0. Reserve space
# for container metadata and each member header, name and central directory.
ZIP_CONTAINER_RESERVE_BYTES = 1024
ZIP_MEMBER_RESERVE_BYTES = 1024
HOLD_REASONS = frozenset(('SAVED_ORIGINAL_MISSING', 'PRE_PREDICTION_T15_MARGIN',
    'SOURCE_ADMISSION_UNVERIFIED', 'INPUT_PROJECTION_UNVERIFIED', 'FROZEN_MODEL_OR_CONTEXT_UNVERIFIED',
    'PREDICTION_UNVERIFIED', 'POST_GENERATION_T15_MARGIN', 'POST_SAVE_T15_MARGIN',
    'ACTUAL_JST_DAY_CHANGED', 'CLOCK_REGRESSION', UPLOAD_BUDGET_HOLD, PRESERVED))
ENTRY_FIELDS = frozenset(('slot_sha256', 'state', 'reason', 'source_admitted',
                         'context_geometry_present', 'cipher', 'clocks', 'bindings'))
CLOCK_FIELDS = ('input_at', 'prediction_started_at', 'prediction_at', 'seal_started_at', 'local_readback_at')
BINDING_FIELDS = frozenset(('input_sha256', 'feature_input_sha256', 'source_receipt_sha256',
                           'shared_material_sha256'))
SUMMARY_FIELDS = frozenset(('schema', 'scope', 'day_jst', 'state', 'source_archive_commit',
    'reader_code_commit', 'reader_run_id', 'started_at', 'finished_at', 'registered_races',
    'saved_originals', 'source_admitted_races', 'new_encrypted_forecasts', 'locally_saved_before_t15',
    'held_races', 'hold_reasons', 'day_inventory_complete', 'frozen_model_verified',
    'venue_missing_forecasts', 'history_races', 'reviewed_motion_records', 'weather_records',
    'confidence', 'formal_three_way_races', 'independently_admitted_new_forecasts',
    'provider_source_requests', 'result_reads', 'training_runs', 'state_writes', 'production_promoted'))
RUNTIME_CODES = frozenset('OFFICIAL_CONTINUATION_' + code for code in (
    'TRUSTED_RUNTIME_REQUIRED', 'EXACT_SOURCE_JOB_REQUIRED', 'STUDY_MANUAL_ONLY',
    'OWNER_KEY_PAIR_REQUIRED', 'PRIVATE_ROOT_OUTSIDE_REPOSITORY',
    'RUN_CODE_IDENTITY_REQUIRED', 'CHECKOUT_CODE_CHANGED')) | frozenset('DT_R1_FUTURE_' + code for code in (
    'ACTUAL_JST_DAY_REQUIRED', 'OUTPUT_ALREADY_EXISTS', 'SAVED_REGISTRY_REQUIRED',
    'SAVED_REGISTRY_UNVERIFIED', 'REGISTRY_FROM_FUTURE', 'CODEX_PAIR_SCOPE',
    'CODEX_PEER_IDENTITY', 'CODEX_PEER_DAY', 'CODEX_PEER_REGISTRY_CHANGED', 'CODEX_PEER_COHORT_EMPTY'))


def need(ok, code):
    if not ok:
        raise ValueError('DT_R1_FUTURE_' + code)


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def slot(day, race_id):
    return digest({'day_jst': day, 'race_id': race_id})


def _model_identity():
    return dict(model_id='chatgpt-dt-r1', model_sha256=MODEL_SHA,
                model_file_sha256=MODEL_FILE_SHA, venue_file_sha256=VENUE_SHA, feature_count=462)


def _report_scope(codex):
    return 'CODEX_ONLY_FUTURE_SHADOW' if codex else 'DT_ONLY_FUTURE_SHADOW'


def _report_state(ready, codex):
    name = 'CODEX_SHADOW' if codex else 'DT_SHADOW'
    return name + '_SAVED_PENDING_INDEPENDENT_READBACK' if ready else 'HOLD_' + name + '_NO_TIMELY_LOCAL_ORIGINAL'


def _check_codex_peer(peer, current_run):
    need(type(peer) is dict and set(peer) == CODEX_PEER_FIELDS and
         type(peer['dt_producer_run_id']) is str and archive.RUN.fullmatch(peer['dt_producer_run_id']) and
         peer['dt_producer_run_id'] != current_run and _sha(peer['dt_manifest_sha256']), 'CODEX_PEER_IDENTITY')


def load_frozen(repo):
    """Verify the fixed public artifact and the exact inference implementation."""
    repo = Path(repo)
    try:
        model_path, venue_path = repo / MODEL_FILE, repo / VENUE_FILE
        need(not model_path.is_symlink() and not venue_path.is_symlink(), 'MODEL_PATH')
        raw, venue_raw = model_path.read_bytes(), venue_path.read_bytes()
        need(sha256(raw).hexdigest() == MODEL_FILE_SHA and sha256(venue_raw).hexdigest() == VENUE_SHA,
             'MODEL_BYTES')
        artifact = json.loads(raw)
        trained = RankModel.from_dict(artifact)
        need(artifact['model_sha256'] == MODEL_SHA and len(trained.feature_names) == 462 and
             trained.fit_meta['context']['venue_file_sha256'] == VENUE_SHA and
             trained.fit_meta['context']['weather_file_sha256'] is None and
             trained.fit_meta['context']['timing_file_sha256'] is None, 'MODEL_IDENTITY')
        for name in INFERENCE_SOURCES:
            path = repo / 'research/chatgpt_dt_r1' / name
            need(not path.is_symlink() and sha256(path.read_bytes()).hexdigest() ==
                 artifact['fit_meta']['source_code_sha256'][name], 'INFERENCE_SOURCE_CHANGED')
        return trained, VenueStore.from_records(json.loads(venue_raw))
    except Exception:
        raise ValueError('DT_R1_FUTURE_FROZEN_MODEL_OR_CONTEXT_UNVERIFIED') from None


def _entry(day, race_id, reason):
    return dict(slot_sha256=slot(day, race_id), state='HOLD', reason=reason,
                source_admitted=False, context_geometry_present=None, cipher=None, clocks=None, bindings=None)


def _same_day(at, day):
    return at.astimezone(continuation.form.JST).date().isoformat() == day


def _observe(clock):
    return continuation.form._aware(clock())


def _timely(at, cutoff):
    return at <= parse_clock(cutoff) - timedelta(minutes=15)


def _source_verifier(store, payload, private, client, cache, proof_sink):
    def verify(packet):
        # Re-run the existing independent authority. A self-hash or echo is
        # never accepted as source evidence, even if its field names look right.
        fresh, _ = records.admit_original(store, payload, private, origin_client=client, packet_cache=cache)
        expected = official_inputs.verification_payload(payload, fresh, prediction_at=packet['prediction_at'])
        need(digest(expected) == digest(packet), 'SOURCE_REPLAY_CHANGED')
        receipt = dict(schema='DT_R1_EXISTING_OFFICIAL_SOURCE_REVALIDATION_V1',
            source_archive_commit=store.head, payload_sha256=digest(expected),
            origin_receipt=fresh['origin_receipts']['baseline_origin'])
        proof_sink.update(receipt)
        return dict(verified=True, independent=True,
            verifier='race_ai.keirin_official_nationwide_records.admit_original',
            receipt_sha256=digest(receipt), payload_sha256=digest(expected))
    return verify


def _candidate(*, store, payload, original, trained, venues, private, client, cache, clock, official_history=None):
    at = _observe(clock).isoformat()
    proofs = {}
    history = official_history.arguments(payload, original, at) if official_history is not None else {}
    row = official_inputs.prepare(payload, original, prediction_at=at,
        source_verifier=_source_verifier(store, payload, private, client, cache, proofs), **history)
    # The actual fixed sidecar must already exist by this input clock. The
    # existing store handles absent venues as explicit missing feature values.
    need(all(parse_clock(v.retrieved_at) <= parse_clock(at) for v in venues.records), 'CONTEXT_FROM_FUTURE')
    row = augment_abilities(augment_agari(augment_features([row], venue_store=venues, as_of=at,
        allow_current_geometry_assumption=False)))[0]
    need(tuple(row['feature_names']) == trained.feature_names and row['features'].shape[1] == 462,
         'FEATURE_SCHEMA_CHANGED')
    return row, at, proofs


def _no_history_forecast(*, store, payload, original, trained, venues, private, client, cache,
                         input_at, prediction_started_at):
    row, _, _ = _candidate(store=store, payload=payload, original=original, trained=trained,
        venues=venues, private=private, client=client, cache=cache, clock=lambda: parse_clock(input_at))
    forecast = forecast_row(trained, row, prediction_at=prediction_started_at)
    need(forecast['status'] == 'READY' and forecast['model_sha256'] == MODEL_SHA, 'HISTORY_CONTROL_UNVERIFIED')
    return forecast


def _back_study_pair(back_trial, *, store, payload, original, private, client, cache, input_at,
                     official_history):
    history = official_history.arguments(payload, original, input_at) if official_history is not None else {}
    return back_trial(payload=payload, original=original, prediction_at=input_at,
        source_verifier=_source_verifier(store, payload, private, client, cache, {}), **history)


def _personal_study_material(trial, baseline, trained, prediction_at):
    row, forecast = trial['row'], trial['forecast']
    history = row['history_evidence']
    validate_prediction_inputs(row, prediction_at=prediction_at, model_meta=trained.fit_meta)
    fields = ('race_id', 'day', 'cutoff_at', 'context_as_of', 'input_sha256', 'source_attestation_sha256')
    need(all(row[key] == baseline[key] for key in fields) and row['result_rows'] == [] and
         history['official_support'] == baseline['history_evidence']['official_support'] and
         history['personal_profile_policy'] == PERSONAL_HISTORY_POLICY and
         type(trial['used_finishes']) is int and trial['used_finishes'] > 0 and
         forecast['status'] == 'READY' and all(forecast[key] == row[key] for key in ('race_id', 'input_sha256')),
         'PERSONAL_STUDY_INPUT')
    return dict(policy=PERSONAL_HISTORY_POLICY, used_finishes=trial['used_finishes'],
        profile_proof_sha256=checked_sha(history['personal_profile_proof_sha256']),
        feature_input_sha256=checked_sha(row['feature_input_sha256']),
        markets_sha256=digest({market: forecast[market] for market in ('trifectas', 'exactas')}),
        trifecta_top12=[ticket['cars'] for ticket in forecast['trifectas'][:12]],
        exacta_top2=[ticket['cars'] for ticket in forecast['exactas'][:2]])


def _shared_material(row, payload, original, store, proof, *, control=None, back_study=None):
    support = row['history_evidence']['official_support']
    shared = dict(schema=LEGACY_MATERIAL_SCHEMA,
        source_projection_sha256=digest(official_inputs.source_projection(payload, original)),
        source_projection_schema=official_inputs.SCHEMA, source_archive_commit=store.head,
        source_original_reference=store.index['originals'][row['race_id']], source_verification=proof,
        input_sha256=row['input_sha256'], context_identity=dict(venue_file_sha256=VENUE_SHA,
            timing_records=0, motion_records=0, weather_records=0),
        context_evidence=row['context_evidence'], history_status=support['status'],
        history_races=support['history_races'])
    if support['history_races']:
        shared.update(schema=HISTORY_MATERIAL_SCHEMA, history_policy=HISTORY_POLICY,
                      history_snapshot_sha256=support['history_snapshot_sha256'],
                      history_verification_receipt_sha256=support['verification_receipt_sha256'])
    if control is not None:
        need(support['history_races'] and control['race_id'] == row['race_id'] and
             control['input_sha256'] == row['input_sha256'], 'HISTORY_CONTROL_INPUT')
        # Both complete distributions were computed before the common seal.
        # Retain compact ranked controls and the hash of the exact probabilities.
        shared.update(schema=PAIRED_HISTORY_MATERIAL_SCHEMA, no_history_control=dict(
            policy=HISTORY_CONTROL_POLICY, feature_input_sha256=control['feature_input_sha256'],
            markets_sha256=digest({market: control[market] for market in ('trifectas', 'exactas')}),
            trifecta_top12=[ticket['cars'] for ticket in control['trifectas'][:12]],
            exacta_top2=[ticket['cars'] for ticket in control['exactas'][:2]]))
    if back_study is not None:
        need(back_study['schema'] == back_official_shadow.SCHEMA and
             back_study['race_id'] == row['race_id'] and
             back_study['input_sha256'] == row['input_sha256'] and
             parse_clock(back_study['cutoff_at']) == parse_clock(row['cutoff_at']) and
             back_study['prediction_at'] == row['context_as_of'] and
             back_study['source_attestation_sha256'] == row['source_attestation_sha256'] and
             back_study['history'] == support and
             back_study['back_leader_estimate']['observed'] is False and
             set(back_study['arms']) == {'back_mixture', 'direct'}, 'BACK_STUDY_INPUT')
        compact = dict(back_study)
        compact['back_leader_estimate'] = dict(observed=False,
            estimate_sha256=digest(back_study['back_leader_estimate']))
        compact['arms'] = {
            name: dict(model_sha256=arm['model_sha256'],
                       distribution_sha256=digest({key: arm[key] for key in ('trifectas', 'exactas', 'riders')}),
                       trifecta_top12=arm['trifecta_top12'], exacta_top2=arm['exacta_top2'])
            for name, arm in back_study['arms'].items()
        }
        shared.update(schema=BACK_STUDY_MATERIAL_SCHEMA, back_study=compact)
    return shared


def _save_forecast(*, output, entry, row, forecast, payload, original, store, public, private,
                   code_commit, input_at, prediction_started_at, proof, clock, remaining_cipher_bytes,
                   control=None, back_study=None, personal_study=None, source_diagnostics=None, codex_peer=None):
    seal_at = _observe(clock)
    cutoff = row['cutoff_at']
    if not _same_day(seal_at, store.day):
        return dict(entry, reason='ACTUAL_JST_DAY_CHANGED')
    if seal_at < parse_clock(forecast['prediction_at']):
        return dict(entry, reason='CLOCK_REGRESSION')
    if not _timely(seal_at, cutoff):
        return dict(entry, reason='POST_GENERATION_T15_MARGIN')
    codex = codex_peer is not None
    if codex:
        feature_row = row
        frozen = dict(schema=CODEX_MATERIAL_SCHEMA, **codex_peer,
            source_projection_sha256=row['source_projection_sha256'], source_archive_commit=store.head,
            source_original_reference=store.index['originals'][row['race_id']], source_verification=row['source_proof'],
            input_sha256=row['input_sha256'])
    else:
        feature_row = dict(row, features=row['features'].tolist(), feature_names=list(row['feature_names']))
        frozen = _shared_material(row, payload, original, store, proof, control=control, back_study=back_study)
    shared = frozen if personal_study is None else dict(schema=PERSONAL_STUDY_MATERIAL_SCHEMA,
        frozen_material=frozen, personal_history_trial=personal_study)
    private_payload = dict(schema=CODEX_PRIVATE_SCHEMA if codex else PRIVATE_SCHEMA,
        day_jst=store.day, race_id=row['race_id'],
        observed_at=seal_at.isoformat(), reader_code_commit=code_commit, reader_run_id=os.environ['GITHUB_RUN_ID'],
        source_archive_commit=store.head, source_registry_reference=store.index['registry'],
        source_original_reference=store.index['originals'][row['race_id']],
        forecast=forecast, feature_row=feature_row, shared_material=shared,
        safe_report=dict(day_jst=store.day, scope=_report_scope(codex), new_forecasts=1,
                         confidence='HOLD', independently_admitted_new_forecasts=0))
    plaintext = records.wire(private_payload)
    raw = codec.seal_evidence(plaintext, public, store.day, seal_at.isoformat())
    if len(raw) > remaining_cipher_bytes and personal_study is not None:
        if source_diagnostics is not None:
            source_diagnostics['PERSONAL_STUDY_UPLOAD_BYTE_RESERVE'] += 1
        shared = private_payload['shared_material'] = frozen
        plaintext = records.wire(private_payload)
        raw = codec.seal_evidence(plaintext, public, store.day, seal_at.isoformat())
    if len(raw) > remaining_cipher_bytes:
        return dict(entry, reason=UPLOAD_BUDGET_HOLD)
    filename = entry['slot_sha256'] + '.sealed.json'
    capture_files._save_once(output / filename, raw)
    restored = (output / filename).read_bytes()
    need(restored == raw, 'CIPHERTEXT_READBACK_MISMATCH')
    # Authenticate the just-written ciphertext in memory; never emit plaintext.
    need(codec.decrypt_evidence(restored, private) == plaintext, 'PLAINTEXT_READBACK_MISMATCH')
    readback_at = _observe(clock)
    envelope = codec._checked_cipher(restored)
    clocks = dict(input_at=input_at, prediction_started_at=prediction_started_at,
        prediction_at=forecast['prediction_at'], seal_started_at=seal_at.isoformat(),
        local_readback_at=readback_at.isoformat(), cutoff_at=cutoff)
    reason = ('CLOCK_REGRESSION' if readback_at < seal_at else
              'ACTUAL_JST_DAY_CHANGED' if not _same_day(readback_at, store.day) else
              'POST_SAVE_T15_MARGIN' if not _timely(readback_at, cutoff) else None)
    return dict(entry, state='HOLD' if reason else READY, reason=reason,
        cipher=dict(file=filename, bytes=len(restored), sha256=sha256(restored).hexdigest(),
                    plaintext_sha256=envelope['evidence_plaintext_sha256']), clocks=clocks,
        bindings=dict(input_sha256=row['input_sha256'], feature_input_sha256=row['feature_input_sha256'],
            source_receipt_sha256=row['source_attestation_sha256'], shared_material_sha256=digest(shared)))


def _source_failure(stage, error):
    code = str(error)
    if isinstance(error, GitHubEvidenceError):
        if code in {
            'GITHUB_EVIDENCE_HTTP_401', 'GITHUB_EVIDENCE_HTTP_403', 'GITHUB_EVIDENCE_HTTP_429',
            'GITHUB_EVIDENCE_UNAVAILABLE', 'GITHUB_EVIDENCE_ARTIFACT_EXPIRED_OR_INVALID',
        }:
            return code
        return 'GITHUB_SOURCE_EVIDENCE_FAILED'
    if isinstance(error, OriginEvidenceError):
        return 'OFFICIAL_SOURCE_PROOF_INVALID'
    if isinstance(error, archive.GitCipherFetchTimeout):
        return 'OFFICIAL_SOURCE_ARCHIVE_TIMEOUT'
    if isinstance(error, ValueError) and code in {
        'A_B_CONFIDENCE_NOT_IDENTICAL', 'A_B_DECRYPTED_PREDICTION_NOT_REPRODUCIBLE',
        'A_B_PLAIN_SNAPSHOTS_NOT_IDENTICAL', 'CONFIDENCE_RECOMPUTED_ASSESSMENT_MISMATCH',
        'ARCHIVE_BLOB_READ_UNAVAILABLE', 'ARCHIVE_BLOB_SIZE_INVALID',
        'ARCHIVE_ORIGINAL_OR_RECEIPT_MISSING', 'ARCHIVE_RECEIPT_OR_SHA_MISMATCH',
        'GIT_COMMAND_OR_REMOTE_UNAVAILABLE', 'OFFICIAL_SP_RECORD_BASELINE_ARCHIVE_LINEAGE',
        'OFFICIAL_SP_RECORD_CONFIDENCE_PRESENCE_MISMATCH',
        'OFFICIAL_SP_RECORD_CONFIDENCE_SOURCE_CIPHER_MISMATCH', 'OFFICIAL_SP_RECORD_ORIGINAL_COHORT',
        'OFFICIAL_SP_RECORD_ORIGINAL_SCHEMA', 'OFFICIAL_SP_RECORD_ORIGINAL_SOURCE_OR_MODEL_CHANGED',
        'OWNER_DECRYPT_OR_ZLIB_AUTH_FAILED', 'OWNER_PRIVATE_PUBLIC_FINGERPRINT_MISMATCH',
        'PRIVATE_ARM_ROLE_OR_SOURCE_LINEAGE_FAILED',
    }:
        return code
    return stage


def produce_day(*, store, repo, output, owner_public_pem, owner_private_pem, code_commit,
                origin_client, clock=continuation.now_utc, source_diagnostics=None,
                _ciphertext_byte_cap=None, accepted_slots=(), official_history=None, back_trial=None,
                compare_personal_history=False, codex_peer=None, codex_inputs=None):
    """Internal protected owner-job worker. A private cap can lower the default budget."""
    started = _observe(clock)
    need(_same_day(started, store.day), 'ACTUAL_JST_DAY_REQUIRED')
    need(not Path(output).exists() and not Path(output).is_symlink(), 'OUTPUT_ALREADY_EXISTS')
    need(store.index['registry'] is not None, 'SAVED_REGISTRY_REQUIRED')
    registry_payload = store.read(store.index['registry'], owner_private_pem)
    need(parse_clock(registry_payload['observed_at']) <= started, 'REGISTRY_FROM_FUTURE')
    registry = records.replay_registry(registry_payload)
    race_ids = registry['registered_race_ids']
    originals = store.index['originals']
    need(registry['event_day'] == store.day and type(race_ids) is list and
         len(race_ids) == len(set(race_ids)) and 0 < len(race_ids) <= records.MAX_RACES and
         all(type(rid) is str and re.fullmatch('20[0-9]{10}', rid) and
             rid.startswith(store.day.replace('-', '')) for rid in race_ids) and
         set(originals) <= set(race_ids), 'SAVED_REGISTRY_UNVERIFIED')
    accepted_slots = frozenset(accepted_slots)
    known_slots = {slot(store.day, rid) for rid in originals}
    need(accepted_slots <= known_slots, 'PRESERVED_SLOT_SCOPE')
    codex = codex_peer is not None
    if codex:
        _check_codex_peer(codex_peer, os.environ['GITHUB_RUN_ID'])
        need(official_history is None and back_trial is None and not compare_personal_history and
             type(codex_inputs) is dict and codex_inputs.keys() <= known_slots and
             all(type(pin) is tuple and len(pin) == 2 and _sha(pin[0]) and
                 _same_day(parse_clock(pin[1]), store.day) for pin in codex_inputs.values()), 'CODEX_PAIR_SCOPE')
    else:
        need(codex_inputs is None, 'CODEX_PAIR_SCOPE')
    identity = codex_future_candidate.model_identity() if codex else _model_identity()
    zip_reserve = ZIP_CONTAINER_RESERVE_BYTES + ZIP_MEMBER_RESERVE_BYTES * (len(race_ids) + 1)
    remaining_cipher_bytes = MAX_ARCHIVE_BYTES - MAX_MANIFEST_BYTES - zip_reserve
    if _ciphertext_byte_cap is not None:
        need(type(_ciphertext_byte_cap) is int and 0 <= _ciphertext_byte_cap <= remaining_cipher_bytes,
             'INVALID_UPLOAD_BYTE_BUDGET')
        remaining_cipher_bytes = _ciphertext_byte_cap
    output = capture_files._private_directory(output)
    try:
        if codex:
            trained, venues = codex_future_candidate.load_frozen(repo, owner_private_pem, store.day), None
        else:
            trained, venues = load_frozen(repo)
    except Exception:
        trained, venues = None, None
    entries, cache, history_uses = [], {}, 0
    # RecordStore validates each published cutoff. Compare actual instants
    # before any source replay, so even failed attempts follow deadline order.
    # A missing original has no trusted cutoff; retain its registered slot.
    known = sorted(originals, key=lambda rid: (parse_clock(originals[rid]['cutoff_at']), rid))
    for rid in known + sorted(set(race_ids) - originals.keys()):
        entry = _entry(store.day, rid, 'SAVED_ORIGINAL_MISSING')
        if entry['slot_sha256'] in accepted_slots:
            entries.append(dict(entry, reason=PRESERVED))
            continue
        meta = originals.get(rid)
        if meta is None:
            entries.append(entry); continue
        if codex and entry['slot_sha256'] not in codex_inputs:
            entries.append(dict(entry, reason=CODEX_PEER_HOLD)); continue
        now = _observe(clock)
        if not _same_day(now, store.day):
            entries.append(dict(entry, reason='ACTUAL_JST_DAY_CHANGED')); continue
        if not _timely(now, meta['cutoff_at']):
            entries.append(dict(entry, reason='PRE_PREDICTION_T15_MARGIN')); continue
        if trained is None:
            entries.append(dict(entry, reason='FROZEN_MODEL_OR_CONTEXT_UNVERIFIED')); continue
        stage = 'OFFICIAL_SOURCE_CIPHERTEXT_REPLAY_FAILED'

        def record_stage(value):
            nonlocal stage
            stage = value

        try:
            payload = store.read(meta, owner_private_pem)
            original, _ = records.admit_original(store, payload, owner_private_pem,
                origin_client=origin_client, packet_cache=cache, record_stage=record_stage)
            stage = 'OFFICIAL_SOURCE_BINDING_FAILED'
            need(original['race_id'] == rid and original['day_jst'] == store.day and
                 original['snapshot']['published_cutoff_at'] == meta['cutoff_at'], 'SOURCE_BINDING_CHANGED')
            entry['source_admitted'] = True
        except Exception as error:
            if source_diagnostics is not None:
                source_diagnostics[_source_failure(stage, error)] += 1
            entries.append(dict(entry, reason='SOURCE_ADMISSION_UNVERIFIED')); continue
        try:
            if codex:
                input_at = _observe(clock).isoformat()
                common = official_inputs.verification_payload(payload, original, prediction_at=input_at)['normalized_input']
                input_pin, cutoff_pin = codex_inputs[entry['slot_sha256']]
                need(common['input_sha256'] == input_pin and parse_clock(meta['cutoff_at']) == parse_clock(cutoff_pin),
                     'CODEX_COMMON_INPUT_CHANGED')
                row = codex_future_candidate.project(payload, original, day=store.day, cutoff_at=meta['cutoff_at'],
                    input_at=input_at, original_meta=meta, input_sha256=common['input_sha256'])
                need(row['input_sha256'] == common['input_sha256'], 'CODEX_COMMON_INPUT_CHANGED')
                proof = None
            else:
                row, input_at, proof = _candidate(store=store, payload=payload, original=original,
                    trained=trained, venues=venues, private=owner_private_pem, client=origin_client,
                    cache=cache, clock=clock, official_history=official_history)
                entry['context_geometry_present'] = bool(row['context_evidence']['venue_sources'])
        except Exception as error:
            if source_diagnostics is not None:
                source_diagnostics[_source_failure('OFFICIAL_HISTORY_OR_INPUT_PROJECTION_FAILED', error)] += 1
            entries.append(dict(entry, reason='INPUT_PROJECTION_UNVERIFIED')); continue
        try:
            prediction_started = _observe(clock)
            need(parse_clock(input_at) <= prediction_started, 'CLOCK_REGRESSION')
            if not _same_day(prediction_started, store.day):
                entries.append(dict(entry, reason='ACTUAL_JST_DAY_CHANGED')); continue
            if not _timely(prediction_started, row['cutoff_at']):
                entries.append(dict(entry, reason='PRE_PREDICTION_T15_MARGIN')); continue
            forecast = (codex_future_candidate.forecast(trained, row, generated_or_started_at=prediction_started.isoformat())
                        if codex else forecast_row(trained, row, prediction_at=prediction_started.isoformat(), full=True))
            need(forecast['status'] == 'READY' and forecast['model_id'] == identity['model_id'] and
                 forecast['model_sha256'] == identity['model_sha256'], 'PREDICTION_UNVERIFIED')
            control = None
            if not codex and row['history_evidence']['official_support']['history_races']:
                control = _no_history_forecast(store=store, payload=payload, original=original,
                    trained=trained, venues=venues, private=owner_private_pem, client=origin_client,
                    cache=cache, input_at=input_at, prediction_started_at=prediction_started.isoformat())
            back_study = None
            if back_trial is not None:
                back_study = _back_study_pair(back_trial, store=store, payload=payload, original=original,
                    private=owner_private_pem, client=origin_client, cache=cache, input_at=input_at,
                    official_history=official_history)
            personal, personal_hold = None, None
            if compare_personal_history:
                try:
                    if control is None:
                        personal_hold = 'NO_REPLAYED_SEVEN_DAY_HISTORY'
                    elif not _timely(_observe(clock) + PERSONAL_TRIAL_SEAL_RESERVE, row['cutoff_at']):
                        personal_hold = 'PERSONAL_STUDY_DEADLINE_RESERVE'
                    else:
                        personal, personal_hold = personal_trial(trained=trained, venues=venues, payload=payload,
                            original=original, baseline=row, prior=official_history, prediction_at=input_at)
                except Exception:
                    personal_hold = 'PERSONAL_STUDY_COMPUTE_UNVERIFIED'
            generated = _observe(clock)
            need(prediction_started <= generated, 'CLOCK_REGRESSION')
            if not _same_day(generated, store.day):
                entries.append(dict(entry, reason='ACTUAL_JST_DAY_CHANGED')); continue
            if not _timely(generated, row['cutoff_at']):
                entries.append(dict(entry, reason='POST_GENERATION_T15_MARGIN')); continue
            if not codex:
                validate_prediction_inputs(row, prediction_at=generated.isoformat(), model_meta=trained.fit_meta)
            personal_study = None
            if personal is not None:
                try:
                    personal_study = _personal_study_material(personal, row, trained, generated.isoformat())
                except Exception:
                    personal_hold = 'PERSONAL_STUDY_BINDING_UNVERIFIED'
            if personal_hold is not None and source_diagnostics is not None:
                safe = personal_hold if personal_hold in PERSONAL_TRIAL_SOURCE_HOLDS else 'PERSONAL_STUDY_COMPUTE_UNVERIFIED'
                source_diagnostics[safe] += 1
            forecast.update(prediction_at=generated.isoformat(),
                scope=_report_scope(codex) + '_PENDING_INDEPENDENT_READBACK',
                forecast_original_independently_read_back=False, production_promoted=False)
        except Exception:
            entries.append(dict(entry, reason='PREDICTION_UNVERIFIED')); continue
        # I/O/codec failure aborts the bundle: a partially saved file must never
        # disappear behind a successful per-race HOLD or an incomplete manifest.
        saved = _save_forecast(output=output, entry=entry, row=row, forecast=forecast,
            payload=payload, original=original, store=store, public=owner_public_pem,
            private=owner_private_pem, code_commit=code_commit, input_at=input_at,
            prediction_started_at=prediction_started.isoformat(), proof=proof, clock=clock,
            remaining_cipher_bytes=remaining_cipher_bytes, control=control, back_study=back_study,
            personal_study=personal_study, source_diagnostics=source_diagnostics, codex_peer=codex_peer)
        if saved['cipher'] is not None:
            remaining_cipher_bytes -= saved['cipher']['bytes']
            if not codex:
                history_uses += row['history_evidence']['official_support']['history_races']
        entries.append(saved)
    eligible = sum(r['state'] == READY for r in entries)
    report = dict(schema=CODEX_SUMMARY_SCHEMA if codex else SUMMARY_SCHEMA, scope=_report_scope(codex), day_jst=store.day,
        state=_report_state(eligible, codex),
        source_archive_commit=store.head, reader_code_commit=code_commit, reader_run_id=os.environ['GITHUB_RUN_ID'],
        started_at=started.isoformat(), finished_at=_observe(clock).isoformat(), registered_races=len(race_ids),
        saved_originals=len(store.index['originals']), source_admitted_races=sum(r['source_admitted'] for r in entries),
        new_encrypted_forecasts=sum(r['cipher'] is not None for r in entries), locally_saved_before_t15=eligible,
        held_races=len(race_ids) - eligible, hold_reasons=dict(sorted(Counter(r['reason'] for r in entries if r['state'] == 'HOLD').items())),
        day_inventory_complete=registry['day_inventory_complete'], frozen_model_verified=trained is not None,
        venue_missing_forecasts=sum(r['cipher'] is not None and r['context_geometry_present'] is False for r in entries),
        history_races=history_uses, reviewed_motion_records=0, weather_records=0, confidence='HOLD',
        formal_three_way_races=0, independently_admitted_new_forecasts=0,
        provider_source_requests=0, result_reads=0, training_runs=0, state_writes=0, production_promoted=False)
    if codex:
        report.update(codex_peer)
    manifest = dict(schema=SCHEMA, model=identity, summary=report,
        registry={key: store.index['registry'][key] for key in ('evidence_sha256', 'cipher_sha256')}, entries=entries)
    manifest_raw = codec._canonical(manifest)
    need(0 < len(manifest_raw) <= MAX_MANIFEST_BYTES, 'MANIFEST_BYTE_LIMIT')
    capture_files._save_once(output / 'manifest.json', manifest_raw)
    manifest_sha = sha256(manifest_raw).hexdigest()
    verify_output(output, expected_manifest_sha256=manifest_sha, codex=codex)
    return dict(report, manifest_sha256=manifest_sha, manifest_bytes=len(manifest_raw),
                cipher_files=report['new_encrypted_forecasts'],
                cipher_bytes=sum(r['cipher']['bytes'] for r in entries if r['cipher'] is not None))


def verify_output(directory, *, expected_manifest_sha256=None, codex=False):
    """Check only local ciphertext/manifest integrity; never assert independence."""
    directory = Path(directory)
    path = directory / 'manifest.json'
    need(not directory.is_symlink() and path.is_file() and not path.is_symlink(), 'MANIFEST_PATH')
    raw = path.read_bytes()
    need(0 < len(raw) <= MAX_MANIFEST_BYTES and (expected_manifest_sha256 is None or
         _sha(expected_manifest_sha256) and sha256(raw).hexdigest() == expected_manifest_sha256), 'MANIFEST_SHA')
    manifest = codec._json(raw)
    identity = codex_future_candidate.model_identity() if codex else _model_identity()
    need(type(manifest) is dict and set(manifest) == {'schema', 'model', 'summary', 'registry', 'entries'} and
         manifest['schema'] == SCHEMA and manifest['model'] == identity, 'MANIFEST_SCHEMA')
    report, entries = manifest['summary'], manifest['entries']
    fields = SUMMARY_FIELDS | CODEX_PEER_FIELDS if codex else SUMMARY_FIELDS
    summary_schema = CODEX_SUMMARY_SCHEMA if codex else SUMMARY_SCHEMA
    need(type(report) is dict and set(report) == fields and report['schema'] == summary_schema and
         report['scope'] == _report_scope(codex) and report['confidence'] == 'HOLD' and
         report['production_promoted'] is False, 'PUBLIC_SUMMARY_SCHEMA')
    if codex:
        _check_codex_peer({key: report[key] for key in CODEX_PEER_FIELDS}, report['reader_run_id'])
    codec._day(report['day_jst'])
    need(type(manifest['registry']) is dict and set(manifest['registry']) == {'evidence_sha256', 'cipher_sha256'} and
         all(_sha(v) for v in manifest['registry'].values()), 'REGISTRY_PINS')
    need(type(entries) is list and 0 < len(entries) <= records.MAX_RACES and
         type(report['registered_races']) is int and len(entries) == report['registered_races'], 'REGISTERED_DENOMINATOR')
    need(all(type(report[key]) is int and report[key] == 0 for key in ('reviewed_motion_records', 'weather_records',
        'formal_three_way_races', 'independently_admitted_new_forecasts', 'provider_source_requests',
        'result_reads', 'training_runs', 'state_writes')), 'UNSUPPORTED_SCOPE_CLAIM')
    need(type(report['day_inventory_complete']) is bool and type(report['frozen_model_verified']) is bool,
         'PUBLIC_SUMMARY_TYPES')
    for key in ('source_archive_commit', 'reader_code_commit'):
        need(type(report[key]) is str and re.fullmatch('[0-9a-f]{40}', report[key]), 'CODE_OR_ARCHIVE_PIN')
    need(type(report['reader_run_id']) is str and re.fullmatch('[1-9][0-9]*', report['reader_run_id']), 'RUN_ID')
    need(parse_clock(report['started_at']) <= parse_clock(report['finished_at']), 'REPORT_CLOCK')
    hold_reasons = HOLD_REASONS | {CODEX_PEER_HOLD} if codex else HOLD_REASONS
    seen, files = set(), {'manifest.json'}
    for entry in entries:
        need(type(entry) is dict and set(entry) == ENTRY_FIELDS and _sha(entry['slot_sha256']) and
             entry['slot_sha256'] not in seen and type(entry['source_admitted']) is bool and
             (entry['context_geometry_present'] is None or type(entry['context_geometry_present']) is bool), 'ENTRY_SCHEMA')
        seen.add(entry['slot_sha256'])
        need(entry['state'] in (READY, 'HOLD') and (entry['reason'] is None if entry['state'] == READY else
             entry['reason'] in hold_reasons), 'ENTRY_STATE')
        if codex:
            need(entry['context_geometry_present'] is None, 'CODEX_CONTEXT_SCOPE')
        geometry_checked = codex or type(entry['context_geometry_present']) is bool
        if entry['reason'] == PRESERVED:
            need(entry['cipher'] is None and not entry['source_admitted'] and
                 entry['context_geometry_present'] is None, 'PRESERVED_SLOT_ENTRY')
        if entry['reason'] == UPLOAD_BUDGET_HOLD:
            need(entry['cipher'] is None and entry['source_admitted'] and
                 geometry_checked, 'UPLOAD_BYTE_BUDGET_ENTRY')
        if entry['reason'] == CODEX_PEER_HOLD:
            need(entry['cipher'] is None and not entry['source_admitted'], 'CODEX_PEER_HOLD_ENTRY')
        if entry['cipher'] is None:
            need(entry['state'] == 'HOLD' and entry['clocks'] is None and entry['bindings'] is None, 'UNSAVED_ENTRY')
            continue
        cipher, clocks, bindings = entry['cipher'], entry['clocks'], entry['bindings']
        filename = entry['slot_sha256'] + '.sealed.json'
        need(type(cipher) is dict and set(cipher) == {'file', 'bytes', 'sha256', 'plaintext_sha256'} and
             cipher['file'] == filename and type(cipher['bytes']) is int and 0 < cipher['bytes'] <= codec.MAX_CIPHER_BYTES and
             _sha(cipher['sha256']) and _sha(cipher['plaintext_sha256']) and entry['source_admitted'], 'CIPHER_SCHEMA')
        target = directory / filename
        need(target.is_file() and not target.is_symlink() and target.stat().st_size == cipher['bytes'], 'CIPHER_PATH')
        sealed = target.read_bytes(); envelope = codec._checked_cipher(sealed)
        need(sha256(sealed).hexdigest() == cipher['sha256'] and
             envelope['evidence_plaintext_sha256'] == cipher['plaintext_sha256'] and
             envelope['day_jst'] == report['day_jst'], 'CIPHER_SHA')
        need(type(clocks) is dict and set(clocks) == set(CLOCK_FIELDS) | {'cutoff_at'} and
             envelope['observed_at'] == clocks['seal_started_at'] and type(bindings) is dict and
             set(bindings) == BINDING_FIELDS and all(_sha(v) for v in bindings.values()), 'CIPHER_BINDING')
        times = [parse_clock(clocks[key]) for key in CLOCK_FIELDS]
        need(_same_day(parse_clock(clocks['cutoff_at']), report['day_jst']) and
             geometry_checked and
             all(_same_day(t, report['day_jst']) for t in times[:-1]) and
             parse_clock(report['started_at']) <= times[0] and
             times[-1] <= parse_clock(report['finished_at']), 'CIPHER_CLOCK_SCOPE')
        if entry['reason'] != 'CLOCK_REGRESSION':
            need(times == sorted(times), 'CLOCK_REGRESSION')
        if entry['state'] == READY:
            need(_same_day(times[-1], report['day_jst']) and _timely(times[-1], clocks['cutoff_at']), 'T15_READBACK_REQUIRED')
        files.add(filename)
    need({p.name for p in directory.iterdir()} == files, 'UNLISTED_OUTPUT_FILE')
    counts = dict(source_admitted_races=sum(r['source_admitted'] for r in entries),
        new_encrypted_forecasts=sum(r['cipher'] is not None for r in entries),
        locally_saved_before_t15=sum(r['state'] == READY for r in entries),
        held_races=sum(r['state'] == 'HOLD' for r in entries),
        venue_missing_forecasts=sum(r['cipher'] is not None and r['context_geometry_present'] is False for r in entries))
    need(all(type(report[k]) is int and report[k] == v for k, v in counts.items()) and
         type(report['saved_originals']) is int and counts['source_admitted_races'] <= report['saved_originals'] <= len(entries) and
         report['hold_reasons'] == dict(Counter(r['reason'] for r in entries if r['state'] == 'HOLD')), 'SUMMARY_COUNT_MISMATCH')
    need(type(report['history_races']) is int and 0 <= report['history_races'] <=
         (0 if codex else 100_000 * counts['new_encrypted_forecasts']), 'HISTORY_COUNT_BOUND')
    expected_state = _report_state(counts['locally_saved_before_t15'], codex)
    need(report['state'] == expected_state and
         (report['frozen_model_verified'] or counts['new_encrypted_forecasts'] == 0), 'PUBLIC_SUMMARY_STATE')
    return manifest


def _codex_source(day, dt_producer_run, client):
    from scripts.keirin_dt_r1_future_readback import verified_producer

    with verified_producer(dt_producer_run, client=client) as batch:
        manifest = batch['manifest']
        need(manifest['summary']['day_jst'] == day, 'CODEX_PEER_DAY')
        inputs = {entry['slot_sha256']: (entry['bindings']['input_sha256'], entry['clocks']['cutoff_at'])
                  for entry in manifest['entries'] if entry['state'] == READY}
        need(bool(inputs), 'CODEX_PEER_COHORT_EMPTY')
        peer = dict(dt_producer_run_id=dt_producer_run, dt_manifest_sha256=batch['manifest_sha256'])
    _check_codex_peer(peer, os.environ['GITHUB_RUN_ID'])
    return manifest['summary']['source_archive_commit'], manifest['registry'], peer, inputs


def run_future_shadow(*, repo, private_root, output, owner_public_pem, owner_private_pem,
                      day=None, clock=continuation.now_utc, source_diagnostics=None, compare_back=False,
                      compare_personal_history=False, dt_producer_run=None):
    repo, root, day, public, commit = continuation._runtime(repo=repo, private_root=private_root,
        owner_public_pem=owner_public_pem, owner_private_pem=owner_private_pem, day=day, clock=clock, mode='study')
    need(_same_day(_observe(clock), day), 'ACTUAL_JST_DAY_REQUIRED')
    codex = dt_producer_run is not None
    need(not codex or not (compare_back or compare_personal_history), 'CODEX_PAIR_SCOPE')
    with TemporaryDirectory(prefix='dt-future-reader-', dir=root) as folder, ExitStack() as research:
        reader = Path(folder)
        archive._cmd(reader, 'init', '--quiet', '--template=')
        archive._cmd(reader, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
        archive._cmd(reader, 'config', '--local', 'remote.origin.promisor', 'true')
        archive._cmd(reader, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
        head = records.fetch_partial_head(reader, with_ancestry=True)
        from research.chatgpt_dt_r1.future_batch_retention import retained_slots
        from research.chatgpt_dt_r1.future_retention_gate import legacy_timely_slots
        from scripts.keirin_dt_r1_future_readback import verify_saved_batch

        client = GitHubEvidenceClient()
        source_head, registry, peer, shared_inputs = (head, None, None, None)
        if codex:
            source_head, registry, peer, shared_inputs = _codex_source(day, dt_producer_run, client)
        store = records.RecordStore(reader, day, index_commit=source_head)
        if codex:
            saved_registry = store.index['registry']
            need(saved_registry is not None and
                 {key: saved_registry.get(key) for key in registry} == registry, 'CODEX_PEER_REGISTRY_CHANGED')
        model_sha = codex_future_candidate.model_identity()['model_sha256'] if codex else MODEL_SHA
        provisioned = {slot(day, rid) for rid in store.index['originals']}
        accepted = retained_slots(reader, head, day, model_sha, provisioned,
                                  authenticate_batch=partial(verify_saved_batch, client=client, codex=codex))
        legacy = set() if codex else legacy_timely_slots(reader, head, day, model_sha256=MODEL_SHA, client=client)
        back_trial = None
        if compare_back:
            from scripts.keirin_dt_r1_owner_restore import BACK_RECEIPT
            back_trial = research.enter_context(back_official_shadow.restored_candidate(
                repo / BACK_RECEIPT, root, owner_private_pem=owner_private_pem))
        return produce_day(store=store, repo=repo, output=output, owner_public_pem=public,
            owner_private_pem=owner_private_pem, code_commit=commit, origin_client=client,
            clock=clock, source_diagnostics=source_diagnostics,
            accepted_slots=accepted | (legacy & provisioned),
            official_history=None if codex else OfficialHistory(store, owner_private_pem), back_trial=back_trial,
            compare_personal_history=compare_personal_history, codex_peer=peer, codex_inputs=shared_inputs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--owner-public-pem', type=Path, required=True)
    parser.add_argument('--day')
    parser.add_argument('--compare-back', action='store_true')
    parser.add_argument('--compare-personal-history', action='store_true')
    parser.add_argument('--dt-producer-run', help='Use a verified DT-R1 producer only to pin Codex source material')
    args = parser.parse_args(argv)
    codex = args.dt_producer_run is not None
    private = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    source_diagnostics = Counter()
    try:
        report = run_future_shadow(repo=args.repo, private_root=args.private_root, output=args.output,
            owner_public_pem=args.owner_public_pem, owner_private_pem=private, day=args.day,
            source_diagnostics=source_diagnostics, compare_back=args.compare_back,
            compare_personal_history=args.compare_personal_history, dt_producer_run=args.dt_producer_run)
    except Exception as error:
        report = dict(schema=CODEX_SUMMARY_SCHEMA if codex else SUMMARY_SCHEMA, scope=_report_scope(codex),
            state='HOLD_CODEX_SHADOW_RUNTIME_OR_BUNDLE_UNVERIFIED' if codex else 'HOLD_DT_SHADOW_RUNTIME_OR_BUNDLE_UNVERIFIED',
            registered_races=None,
            reason=str(error) if str(error) in RUNTIME_CODES else 'RUNTIME_OR_CIPHERTEXT_BUNDLE_UNVERIFIED',
            denominator_authenticated=False, independent_forecast_admission=False, production_promoted=False)
    finally:
        private = b''
    if source_diagnostics:
        # Keep diagnostics out of the v1 authenticated producer receipt so
        # previously retained batches and their verification stay unchanged.
        print(json.dumps(dict(schema='DT_R1_FUTURE_SOURCE_DIAGNOSTICS_V1',
                              source_hold_counts=source_diagnostics), sort_keys=True), file=sys.stderr)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['state'] == _report_state(True, codex) else 2


if __name__ == '__main__':
    raise SystemExit(main())
