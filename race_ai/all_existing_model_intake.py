"""Authenticated private native inputs joined to separate settled outcomes.

This bridge performs no fetch, training, source grant or feature derivation.
Its records contain private originals and must remain in the encrypted owner
path. The summary contains counts only. Missing/special results are not losses.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import math
import re

from .actions_contract import digest
from . import all_existing_model_receipt as receipts
from . import all_existing_model_registry as registry
from .boat_venue_learning import RESULT_RIGHTS
from .existing_model_dispatch import _race_key


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_INTAKE_' + reason)


def _time(value):
    _need(type(value) is str, 'AWARE_RESULT_CLOCK_REQUIRED')
    try:
        clock = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(clock.utcoffset() is not None, 'AWARE_RESULT_CLOCK_REQUIRED')
        return clock
    except ValueError as exc:
        raise ValueError('ALL_MODEL_INTAKE_AWARE_RESULT_CLOCK_REQUIRED') from exc


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _legacy_boat(observation):
    """Preserve the established ordinary-result conditions and source clocks."""
    data = observation.get('data')
    result = dict(race_id=observation['race_id'], sport='boat', status='pending',
        ordered_top3=[], captured_at=observation.get('captured_at'), published_at=None,
        source_ref=observation.get('source_url'), source_rights_ref=RESULT_RIGHTS,
        source_sha256=observation.get('source_sha256'),
        identity_verified=observation.get('body_identity_verified') is True,
        roster={}, payout_per_100_yen=0, refund_numbers=[], closed_at=observation.get('closed_at'))
    if observation.get('status') != 'AVAILABLE' or type(data) is not dict:
        return result
    if data.get('status') in ('cancelled', 'no_contest') or data.get('refund_boats'):
        result['status'] = 'special'
        return result
    if data.get('finish_confirmed') is not True:
        return result
    rows = data.get('results')
    _need(type(rows) is list and len(rows) == 6 and all(type(row) is dict and
        type(row.get('lane')) is int and 1 <= row['lane'] <= 6 and
        type(row.get('racer_registration_id')) is str and row['racer_registration_id'] for row in rows),
        'BOAT_REGISTERED_ROSTER_INVALID')
    result['roster'] = {str(row['lane']): row['racer_registration_id'] for row in rows}
    _need(len(result['roster']) == 6, 'BOAT_REGISTERED_ROSTER_INVALID')
    if any(row.get('finish_status') != 'FINISHED' for row in rows):
        result['status'] = 'special'
        return result
    if data.get('status') != 'settled' or data.get('confirmed') is not True:
        return result
    payouts = [row for row in data.get('payouts', [])
               if type(row) is dict and row.get('bet_type') == 'trifecta']
    if len(payouts) != 1:
        result['status'] = 'special'
        return result
    winner = data.get('top3')
    _need(type(winner) is list and winner == payouts[0].get('combination') and
          all(type(row.get('finish')) is int for row in rows) and
          sorted(row['finish'] for row in rows) == list(range(1, 7)) and
          [row['lane'] for row in sorted(rows, key=lambda row: row['finish'])[:3]] == winner,
          'BOAT_RESULT_PAYOUT_MISMATCH')
    _need(type(result['closed_at']) is str, 'BOAT_ACTUAL_CUTOFF_REQUIRED')
    result.update(status='settled', ordered_top3=deepcopy(winner),
                  payout_per_100_yen=payouts[0].get('payout_per_100_yen'))
    return result


def _results(observations, now):
    _need(type(observations) is list and len(observations) <= 10000, 'BOUNDED_RESULTS_REQUIRED')
    indexed = {}; duplicates = 0
    for observation in observations:
        _need(type(observation) is dict and type(observation.get('race_id')) is str and
              observation['race_id'], 'RESULT_IDENTITY_INVALID')
        legacy = ('data' in observation or observation.get('status') == 'AVAILABLE' or
                  'body_identity_verified' in observation or
                  'sport' not in observation and 'source_url' in observation)
        value = _legacy_boat(observation) if legacy else deepcopy(observation)
        sport = value.get('sport')
        _need(sport in ('boat', 'keirin', 'autorace', 'horse'), 'RESULT_SPORT_INVALID')
        if value.get('captured_at') is not None:
            _need(_time(value['captured_at']) <= now, 'FUTURE_RESULT')
        key = (sport, _race_key(value['race_id'], sport))
        value['race_id'] = key[1]
        if key in indexed:
            _need(digest(value) == digest(indexed[key]['result']), 'CONFLICTING_RESULT')
            duplicates += 1
            continue
        indexed[key] = dict(result=value, original=deepcopy(observation))
    return indexed, duplicates


def _ordinary_result(value, info, now):
    """Validate ordinary labels against the actual race cutoff and roster."""
    cutoff = _time(info['race_cutoff_at'])
    if value.get('closed_at') is not None:
        _need(_time(value['closed_at']) == cutoff, 'RESULT_ACTUAL_CUTOFF_MISMATCH')
    status = value.get('status')
    if status == 'pending':
        return None, 'pending'
    if status != 'settled' or value.get('refund_numbers'):
        return None, 'special'
    _need(value.get('identity_verified') is True and type(value.get('roster')) is dict and
          value['roster'] == info['roster'], 'RESULT_REGISTERED_ROSTER_MISMATCH')
    captured = _time(value.get('captured_at'))
    _need(cutoff <= captured <= now, 'RESULT_CAPTURE_CLOCK_INVALID')
    published = value.get('published_at')
    if published is not None:
        _need(cutoff < _time(published) <= captured, 'RESULT_PUBLICATION_CLOCK_INVALID')
    _need(type(value.get('source_sha256')) is str and
          re.fullmatch('[a-f0-9]{64}', value['source_sha256']), 'RESULT_SOURCE_HASH_INVALID')
    _need(all(type(value.get(key)) is str and value[key]
              for key in ('source_ref', 'source_rights_ref')), 'RESULT_SOURCE_REQUIRED')
    winner = value.get('ordered_top3')
    _need(type(winner) is list and len(winner) == 3 and len(set(winner)) == 3 and
          all(type(number) is int and str(number) in info['roster'] for number in winner),
          'RESULT_ORDER_INVALID')
    _need(type(value.get('refund_numbers')) is list and not value['refund_numbers'] and
          _number(value.get('payout_per_100_yen')), 'RESULT_SETTLEMENT_INVALID')
    # Match documented BOAT aliases above, then retain the native race identity
    # expected by the existing ranker's exact same-race label contract.
    result = {key: deepcopy(value.get(key)) for key in (
        'sport', 'status', 'ordered_top3', 'captured_at', 'published_at', 'source_ref',
        'source_rights_ref', 'source_sha256', 'identity_verified', 'roster',
        'payout_per_100_yen', 'refund_numbers')}
    result['race_id'] = info['race_id']
    return result, None


def records_from_private_artifact(raw, metadata, observations, *, now,
                                  expected_run_id, expected_head_sha):
    """Authenticate before reading private capsules or independent outcomes.

    ``metadata`` must be the actual caller-fetched artifact metadata. Its digest,
    run/head, repository, expiry and save-before-every-cutoff proof are checked
    by the existing receipt reader. Records do not authorize source/model use.
    """
    admission, payloads = receipts._verified_private_pairs_artifact(raw, metadata,
        now=now, expected_run_id=expected_run_id, expected_head_sha=expected_head_sha)
    # No observation parsing or private input use precedes authentication.
    results, duplicate_results = _results(observations, now)
    known = {cell['cell_key']: cell for cell in registry.cells()}
    unique = {}; duplicate_inputs = 0; captured = 0; unfitted = 0
    for payload in payloads:
        for capsule in payload.get('captured_native_inputs', []):
            captured += 1
            cell = known[capsule['cell_key']]
            unfitted += cell['cell_key'] not in payload['training']['models']
            native = capsule['native_payload']
            info = registry.identity(cell['model_id'], cell['sport'], native)
            key = (cell['cell_key'], _race_key(info['race_id'], cell['sport']))
            provenance = dict(carrier_cell_key=payload.get('cell_key'), generated_at=payload['generated_at'],
                training_sha256=payload['training']['training_sha256'])
            if 'pair' in payload:
                provenance['pair_sha256'] = payload['pair']['pair_sha256']
            else:
                provenance['native_inputs_record_sha256'] = digest(payload)
            if key in unique:
                _need(digest(capsule) == digest(unique[key]['capsule']), 'CONFLICTING_NATIVE_INPUT')
                unique[key]['partitions'].append(provenance)
                duplicate_inputs += 1
                continue
            unique[key] = dict(cell=cell, capsule=deepcopy(capsule), info=info, partitions=[provenance])
    records = []; excluded = Counter(); used_results = set()
    receipt = dict(artifact_id=admission['artifact_id'], artifact_name=admission['artifact_name'],
        digest=admission['artifact_digest'], workflow_run_id=admission['workflow_run_id'],
        head_sha=admission['head_sha'], saved_at=admission['saved_at'],
        independent_pre_cutoff_receipt_verified=True, artifact_metadata=deepcopy(metadata))
    for key, retained in sorted(unique.items()):
        cell, capsule, info = retained['cell'], retained['capsule'], retained['info']
        result_key = (cell['sport'], key[1])
        if result_key not in results:
            excluded['missing'] += 1
            continue
        used_results.add(result_key)
        source = results[result_key]
        result, reason = _ordinary_result(source['result'], info, now)
        if reason is not None:
            excluded[reason] += 1
            continue
        records.append(dict(model_id=cell['model_id'], sport=cell['sport'], race_id=info['race_id'],
            stage=info['stage'], scope=info['scope'], as_of=info['as_of'], cutoff_at=info['cutoff_at'],
            native_payload=deepcopy(capsule['native_payload']), input_sha256=capsule['input_sha256'],
            input_saved_at=admission['saved_at'], input_receipt=deepcopy(receipt),
            input_partitions=deepcopy(retained['partitions']), result=result,
            result_observation=deepcopy(source['original'])))
    captured_cells = {key[0] for key in unique}
    summary = dict(schema='RACE_AI_ALL_EXISTING_MODEL_NATIVE_INTAKE_COUNTS_V1',
        state='AUTHENTICATED_NATIVE_RECORDS_READY' if records else 'NO_ORDINARY_SETTLED_NATIVE_RECORDS',
        artifact_id=admission['artifact_id'], artifact_digest=admission['artifact_digest'],
        workflow_run_id=admission['workflow_run_id'], head_sha=admission['head_sha'],
        partition_count=len(payloads), registered_cell_count=len(known),
        captured_cell_count=len(captured_cells), uncaptured_cell_count=len(known)-len(captured_cells),
        captured_native_input_count=captured, captured_unfitted_native_input_count=unfitted,
        unique_native_input_count=len(unique), duplicate_native_input_count=duplicate_inputs,
        admitted_record_count=len(records), admitted_cell_count=len({(r['sport'], r['model_id']) for r in records}),
        record_counts_by_cell=dict(Counter(registry.cell_key(r['sport'], r['model_id']) for r in records)),
        missing_result_native_input_count=excluded['missing'], pending_result_native_input_count=excluded['pending'],
        special_result_native_input_count=excluded['special'], unmatched_result_count=len(set(results)-used_results),
        duplicate_result_count=duplicate_results, independent_pre_cutoff_receipt_verified=True,
        provider_permission_confirmed=False, training_permission_granted=False,
        historical_inputs_backfilled=False, production_promoted=False, actual_purchases=False,
        missing_results_are_not_losses=True, plaintext_published=False)
    result = dict(records=records, summary=summary)
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('ALL_MODEL_INTAKE_JSON_SAFE_PRIVATE_RECORDS_REQUIRED') from exc
    return result
