"""Owner-encrypted native baseline/learned pairs for existing research models.

The supplied context comes from the actual encrypted artifact reader. Local
sealing is never an external receipt. Every cell retains its native input and
ticket policy; a registered but unfitted cell remains visibly missing.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import json
import re
import time

from .actions_contract import digest
from .boat_pdca_state import state_key
from .boat_venue_dataset import _bytes
from .boat_venue_learning import seal_candidate
from .all_existing_model_learning import forecast_pair, verify_training
from . import all_existing_model_registry as registry
from .existing_model_dispatch import _race_key
from scripts.boat_all_racers import _write
from scripts.boat_history_collect import private_root

SCHEMA = 'RACE_AI_PRIVATE_ALL_EXISTING_MODEL_PAIR_V1'
INPUTS_SCHEMA = 'RACE_AI_PRIVATE_EXISTING_NATIVE_INPUTS_V1'
FIELDS = {'schema', 'generated_at', 'training', 'training_receipt', 'cell_key',
          'native_payload', 'pair', 'source_sha256', 'summary'}
INPUT_FIELDS = {'schema', 'generated_at', 'training', 'training_receipt', 'sport',
                'race_id', 'captured_native_inputs', 'summary'}
CAPSULE_FIELDS = {'cell_key', 'native_payload', 'input_sha256', 'captured_as_of', 'cutoff_at'}
REPOSITORY_ID = 1416489937
MAX_REQUESTS = 16_384


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_PRIVATE_PAIRS_' + reason)


def _time(value):
    try:
        result = value if type(value) is datetime else datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(result.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        return result
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('ALL_MODEL_PRIVATE_PAIRS_AWARE_CLOCK_REQUIRED') from exc


def _physical(now):
    _need(type(now) is datetime and now.utcoffset() is not None, 'PHYSICAL_CLOCK_REQUIRED')
    return now


def _output(path):
    root = Path(path).absolute()
    _need('..' not in root.parts and not any(p.is_symlink() for p in (root, *root.parents)),
          'OUTPUT_PATH_INVALID')
    _need(not root.exists(), 'OUTPUT_EXISTS_DO_NOT_RESET')
    _need(not any((p/'.git').exists() for p in (root, *root.parents)), 'OUTPUT_OUTSIDE_GIT_REQUIRED')
    return root


def _training_receipt(training, receipt, now):
    """Recheck the actual-reader context's identity and current availability."""
    _need(type(receipt) is dict and type(receipt.get('id')) is int and receipt['id'] > 0 and
          receipt.get('expired') is False and type(receipt.get('size_in_bytes')) is int and
          receipt['size_in_bytes'] > 0 and type(receipt.get('digest')) is str and
          re.fullmatch(r'sha256:[a-f0-9]{64}', receipt['digest']), 'TRAINING_RECEIPT_INVALID')
    name = receipt.get('name')
    _need(type(name) is str and len(name) <= 200 and any(
          name.startswith(prefix) and len(name) > len(prefix)
          for prefix in ('boat-venue-learning-', 'all-existing-model-learning-')),
          'TRAINING_RECEIPT_NAME_INVALID')
    run = receipt.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int and run['id'] > 0 and
          all(type(run.get(k)) is int and run[k] == REPOSITORY_ID
              for k in ('repository_id', 'head_repository_id')) and
          type(run.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}', run['head_sha']),
          'TRAINING_RECEIPT_REPOSITORY_INVALID')
    saved = _time(receipt.get('created_at'))
    created = _time(training.get('created_at'))
    available = _time(training.get('data_available_until'))
    _need(available <= created < saved+timedelta(seconds=1) and
          saved+timedelta(seconds=1) <= now < _time(receipt.get('expires_at')),
          'TRAINING_RECEIPT_CLOCK_INVALID')


def partition_key(pair):
    """A flat, opaque, reproducible cell/race partition name."""
    return digest(dict(sport=pair['sport'], cell_key=pair['cell_key'],
                       race_id=_race_key(pair['race_id'], pair['sport'])))


def record_identity(payload):
    """Return the sport and documented canonical race identity of either record."""
    if payload.get('schema') == SCHEMA:
        identity = payload['pair']
    else:
        _need(payload.get('schema') == INPUTS_SCHEMA, 'PAYLOAD_SCHEMA_INVALID')
        identity = payload
    sport, race_id = identity['sport'], identity['race_id']
    _need(type(sport) is str and type(race_id) is str and race_id, 'RECORD_IDENTITY_INVALID')
    return sport, _race_key(race_id, sport)


def record_partition_key(payload):
    """Opaque partitions distinguish input evidence from a model forecast pair."""
    if payload.get('schema') == SCHEMA:
        return partition_key(payload['pair'])
    sport, race_id = record_identity(payload)
    return digest(dict(kind=INPUTS_SCHEMA, sport=sport, race_id=race_id))


def _source_replay(native):
    """Replay frozen admitted references without claiming a new source grant."""
    references = set()
    def visit(value):
        if type(value) is dict:
            rights = value.get('source_rights_ref')
            for key in ('source_url', 'source_ref'):
                if type(value.get(key)) is str and type(rights) is str:
                    references.add((value[key], rights))
            for child in value.values():
                visit(child)
        elif type(value) in (list, tuple):
            for child in value:
                visit(child)
    visit(native)
    return lambda reference, rights, purpose: purpose == 'analysis' and (reference, rights) in references


def _states(training):
    result = {}
    for key, item in training['model_states'].items():
        result[key] = item['state'] if type(item) is dict else item
    return result


def _flags():
    return dict(independent_pre_cutoff_receipt_verified=False, provider_permission_confirmed=False,
                baseline_coefficients_changed=False, production_promoted=False,
                actual_purchases=False, accuracy_improvement_proven=False, plaintext_published=False)


def _native_input(cell, native, known_cells, *, now, allow_source):
    """Validate retained inputs independently of whether their cell has a fit."""
    try:
        member = known_cells[cell]
        info = registry.validate_payload(member['model_id'], member['sport'], native,
                                         at=now, allow_source=allow_source)
        capsule = dict(cell_key=cell, native_payload=deepcopy(native), input_sha256=digest(native),
                       captured_as_of=info['as_of'], cutoff_at=info['cutoff_at'])
        return capsule, info, member['sport']
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError('ALL_MODEL_PRIVATE_PAIRS_CAPTURED_NATIVE_INPUT_INVALID') from exc


def _verify_captured_inputs(payload, now):
    if 'captured_native_inputs' not in payload:
        return
    capsules = payload['captured_native_inputs']; training = payload['training']; pair = payload.get('pair')
    record_sport, record_race = record_identity(payload)
    known = {member['cell_key']: member for member in registry.cells()}
    _need(type(capsules) is list and 0 < len(capsules) <= len(known), 'CAPTURED_INPUTS_BOUND_INVALID')
    seen = set(); first_info = None
    for capsule in capsules:
        _need(type(capsule) is dict and set(capsule) == CAPSULE_FIELDS and
              type(capsule['cell_key']) is str and capsule['cell_key'] in known and
              type(capsule['native_payload']) is dict, 'CAPTURED_INPUT_SCHEMA_INVALID')
        cell = capsule['cell_key']; native = capsule['native_payload']
        _need(cell not in seen, 'CAPTURED_DUPLICATE_CELL_RACE'); seen.add(cell)
        expected, info, sport = _native_input(cell, native, known, now=now, allow_source=_source_replay(native))
        _need(capsule == expected and info['scope'] == training['scope'], 'CAPTURED_INPUT_BINDING_INVALID')
        _need(sport == record_sport and _race_key(info['race_id'], sport) == record_race,
              'CAPTURED_INPUT_RACE_BINDING_INVALID')
        if pair is not None:
            _need(info['roster'] == pair['baseline_normalized']['roster'] and
                  _time(info['race_cutoff_at']) == _time(pair['race_cutoff_at']),
                  'CAPTURED_INPUT_RACE_BINDING_INVALID')
        elif first_info is not None:
            _need(info['roster'] == first_info['roster'] and
                  _time(info['race_cutoff_at']) == _time(first_info['race_cutoff_at']),
                  'CAPTURED_INPUT_RACE_BINDING_INVALID')
        first_info = info
        if pair is not None and cell == payload['cell_key']:
            _need(capsule['input_sha256'] == payload['source_sha256'], 'CAPTURED_FITTED_INPUT_MISMATCH')


def _seal_cutoff(payload):
    deadlines = [_time(capsule['cutoff_at']) for capsule in payload.get('captured_native_inputs', [])]
    if payload.get('schema') == SCHEMA:
        deadlines.append(_time(payload['pair']['cutoff_at']))
    _need(bool(deadlines), 'NATIVE_CUTOFF_REQUIRED')
    return min(deadlines)


def _summary(payload):
    pair = payload['pair']; training = payload['training']
    baseline = pair['baseline_normalized']; learned = pair['learned_normalized']
    summary = dict(schema='RACE_AI_PRIVATE_ALL_EXISTING_MODEL_PAIR_COUNTS_V1',
        state='ENCRYPTED_PRIVATE_NATIVE_PAIR_LOCAL_ONLY', cell_key=payload['cell_key'],
        scope=training['scope'],
        baseline_forecast_count=1, learned_forecast_count=1,
        baseline_ticket_count=baseline['ticket_count'], learned_ticket_count=learned['ticket_count'],
        baseline_selection_status=baseline['selection_status'], learned_selection_status=learned['selection_status'],
        registered_cell_count=len(training['model_states']), fitted_cell_count=len(training['models']),
        training_sha256=training['training_sha256'], native_input_sha256=payload['source_sha256'], **_flags())
    if 'plans' in baseline or 'plans' in learned:
        summary['baseline_native_plan_ticket_counts'] = {k:v['ticket_count'] for k,v in baseline.get('plans', {}).items()}
        summary['learned_native_plan_ticket_counts'] = {k:v['ticket_count'] for k,v in learned.get('plans', {}).items()}
    if 'captured_native_inputs' in payload:
        summary['captured_native_input_count'] = len(payload['captured_native_inputs'])
        summary['captured_unfitted_native_input_count'] = sum(
            capsule['cell_key'] not in training['models'] for capsule in payload['captured_native_inputs'])
    return summary


def _input_summary(payload):
    training = payload['training']; capsules = payload['captured_native_inputs']
    return dict(schema='RACE_AI_PRIVATE_EXISTING_NATIVE_INPUT_COUNTS_V1',
        state='ENCRYPTED_FROZEN_NATIVE_INPUTS_LOCAL_ONLY', partition_kind='FROZEN_NATIVE_INPUTS',
        scope=training['scope'], baseline_forecast_count=0, learned_forecast_count=0,
        registered_cell_count=len(training['model_states']), fitted_cell_count=len(training['models']),
        captured_native_input_count=len(capsules),
        captured_unfitted_native_input_count=sum(c['cell_key'] not in training['models'] for c in capsules),
        training_sha256=training['training_sha256'], **_flags())


def verify_private_native_inputs(payload):
    """Replay frozen input evidence without constructing any model prediction."""
    try:
        _need(type(payload) is dict and set(payload) == INPUT_FIELDS and payload['schema'] == INPUTS_SCHEMA,
              'INPUT_PAYLOAD_SCHEMA_INVALID')
        training = payload['training']; verify_training(training)
        _need(training.get('state') == 'FITTED_SHADOW_ONLY' and bool(training['models']),
              'FITTED_TRAINING_CONTEXT_REQUIRED')
        now = _time(payload['generated_at']); _training_receipt(training, payload['training_receipt'], now)
        _verify_captured_inputs(payload, now)
        _need(payload['summary'] == _input_summary(payload), 'INPUT_SUMMARY_BINDING_INVALID')
        return True
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError('ALL_MODEL_PRIVATE_PAIRS_INPUT_PAYLOAD_INVALID') from exc


def verify_private_record(payload):
    """Verify the explicit forecast-pair or frozen-input-only record schema."""
    _need(type(payload) is dict, 'PAYLOAD_SCHEMA_INVALID')
    if payload.get('schema') == INPUTS_SCHEMA:
        return verify_private_native_inputs(payload)
    return verify_private_pair(payload)


def verify_private_pair(payload):
    """Pure native replay; artifact/save-clock admission is a separate boundary."""
    try:
        _need(type(payload) is dict and set(payload) in (FIELDS, FIELDS | {'captured_native_inputs'}) and
              payload['schema'] == SCHEMA,
              'PAYLOAD_SCHEMA_INVALID')
        training = payload['training']; verify_training(training)
        cell = payload['cell_key']; now = _time(payload['generated_at'])
        _need(type(cell) is str and cell in training['models'], 'FITTED_CELL_REQUIRED')
        _training_receipt(training, payload['training_receipt'], now)
        native = payload['native_payload']; pair = payload['pair']
        _need(type(native) is dict and payload['source_sha256'] == digest(native) == pair['input_sha256'] and
              pair['cell_key'] == cell and _time(pair['as_of']) == now and
              now < _time(pair['cutoff_at']), 'NATIVE_INPUT_BINDING_INVALID')
        replay = forecast_pair(training, cell, native, now=now, allow_source=_source_replay(native))
        _need(digest(replay) == digest(pair), 'NATIVE_PAIR_REPLAY_MISMATCH')
        _verify_captured_inputs(payload, now)
        _need(payload['summary'] == _summary(payload), 'SUMMARY_BINDING_INVALID')
        return True
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError('ALL_MODEL_PRIVATE_PAIRS_PAYLOAD_INVALID') from exc


def make_private_pairs(context, requests, output, *, now, allow_source=None):
    """Seal fitted native cells without resetting an existing output container.

    ``now`` is the trusted caller's aware physical start time. Monotonic time
    covers inference, sealing and readback. Late ciphertext remains local and
    is explicitly quarantined; it can never obtain formal pre-cutoff admission.
    """
    started = time.monotonic(); state_key('production'); now = _physical(now)
    root = _output(output)
    _need(type(context) is dict and set(context) == {'training', 'receipt'}, 'ACTUAL_TRAINING_CONTEXT_REQUIRED')
    context = deepcopy(context); training = context['training']; verify_training(training)
    _need(training.get('state') == 'FITTED_SHADOW_ONLY' and bool(training['models']), 'FITTED_TRAINING_REQUIRED')
    _training_receipt(training, context['receipt'], now)  # Before any inference.
    _need(type(requests) in (list, tuple) and 0 < len(requests) <= MAX_REQUESTS, 'REQUESTS_INVALID')
    prepared = []; missing = []; identities = set(); retained = {}; validated = []
    known_cells = {member['cell_key']: member for member in registry.cells()}
    # Validate the entire request envelope before creating any output.
    for request in requests:
        _need(type(request) is dict and set(request) == {'cell_key', 'native_payload'} and
              type(request['cell_key']) is str and type(request['native_payload']) is dict,
              'REQUEST_SCHEMA_INVALID')
        cell = request['cell_key']
        _need(cell in training['model_states'], 'UNREGISTERED_CELL')
        if cell not in training['models']:
            missing.append(cell)
        if not request['native_payload'] and cell not in training['models']:
            continue
        native = deepcopy(request['native_payload'])
        capsule, info, sport = _native_input(cell, native, known_cells, now=now, allow_source=allow_source)
        _need(info['scope'] == training['scope'], 'CAPTURED_INPUT_SCOPE_MISMATCH')
        race = (sport, _race_key(info['race_id'], sport)); identity = (race, cell)
        _need(identity not in identities, 'DUPLICATE_CELL_RACE'); identities.add(identity)
        retained.setdefault(race, []).append(capsule)
        validated.append((cell, native, race))
    carrier_races = set()
    for cell, native, race in validated:
        if cell not in training['models']:
            continue
        pair = forecast_pair(training, cell, native, now=now, allow_source=allow_source)
        key = partition_key(pair)
        payload = dict(schema=SCHEMA, generated_at=now.isoformat(), training=training,
            training_receipt=context['receipt'], cell_key=cell, native_payload=native,
            pair=pair, source_sha256=digest(native))
        if race not in carrier_races:
            payload['captured_native_inputs'] = sorted(retained[race], key=lambda item: item['cell_key'])
            carrier_races.add(race)
        payload['summary'] = _summary(payload)
        payload = json.loads(json.dumps(payload, allow_nan=False))
        verify_private_pair(payload)
        prepared.append((key, payload))
    forecast_count = len(prepared)
    for race in sorted(set(retained)-carrier_races):
        sport, race_id = race
        payload = dict(schema=INPUTS_SCHEMA, generated_at=now.isoformat(), training=training,
            training_receipt=context['receipt'], sport=sport, race_id=race_id,
            captured_native_inputs=sorted(retained[race], key=lambda item: item['cell_key']))
        payload['summary'] = _input_summary(payload)
        payload = json.loads(json.dumps(payload, allow_nan=False))
        verify_private_record(payload)
        prepared.append((record_partition_key(payload), payload))
        carrier_races.add(race)
    input_only_count = len(prepared)-forecast_count
    summary = dict(schema='RACE_AI_PRIVATE_ALL_EXISTING_MODEL_PAIRS_COUNTS_V1',
        state='ENCRYPTED_PRIVATE_NATIVE_PAIRS_LOCAL_ONLY' if forecast_count else
              'ENCRYPTED_FROZEN_NATIVE_INPUTS_LOCAL_ONLY' if input_only_count else 'NO_VALID_NATIVE_INPUTS',
        scope=training['scope'],
        requested_cell_count=len(requests), partition_count=len(prepared),
        forecast_partition_count=forecast_count, frozen_input_only_partition_count=input_only_count,
        baseline_forecast_count=forecast_count, learned_forecast_count=forecast_count,
        registered_cell_count=len(training['model_states']), fitted_cell_count=len(training['models']),
        model_states=_states(training), missing_requested_cells=sorted(set(missing)),
        captured_native_input_count=sum(len(retained[race]) for race in carrier_races),
        captured_unfitted_native_input_count=sum(capsule['cell_key'] not in training['models']
            for race in carrier_races for capsule in retained[race]),
        unretained_native_input_count=sum(len(capsules) for race, capsules in retained.items() if race not in carrier_races),
        training_sha256=training['training_sha256'], **_flags())
    root.mkdir(parents=True, mode=0o700, exist_ok=False); private_root(root)
    late = False
    for key, payload in prepared:
        cutoff = _seal_cutoff(payload)
        elapsed = time.monotonic()-started
        if elapsed < 0 or now+timedelta(seconds=elapsed) >= cutoff:
            late = True
            break
        result = seal_candidate(payload, root/key)
        _need(result.get('encrypted_readback_verified') is True, 'PARTITION_READBACK_FAILED')
        elapsed = time.monotonic()-started
        if elapsed < 0 or now+timedelta(seconds=elapsed) >= cutoff:
            late = True
            break
    if late:
        summary['state'] = 'QUARANTINED_CUTOFF_ELAPSED_DURING_SEAL'
        _write(root/'quarantine.json', _bytes(summary))
        raise ValueError('ALL_MODEL_PRIVATE_PAIRS_CUTOFF_ELAPSED_DURING_SEAL')
    summary['encrypted_readback_verified'] = True
    _write(root/'summary.json', _bytes(summary))
    return summary
