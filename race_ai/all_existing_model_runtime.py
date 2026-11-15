"""Current privately captured inputs -> encrypted same-input native pairs.

The caller has already frozen the baseline and restored its candidate/grid.
This helper performs no provider or Git operations. Pending originals survive
every rejection until every expected input is verified in owner ciphertext.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import os
import re
import stat
import time

from .actions_contract import digest
from .all_existing_model_inputs import (
    read_private_pending_requests, validate_additional_requests, _additional_source_pairs, _location, _directory,
)
from .all_existing_model_learning import SCHEMA, verify_training
from .all_existing_model_pairs import (
    make_private_pairs, verify_private_record, record_partition_key, record_identity,
    INPUTS_SCHEMA, _training_receipt, _seal_cutoff,
)
from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from .boat_pdca_state import state_key
from .boat_venue_feature_adapter import enrich_venue_snapshot, RIGHTS
from .boat_venue_learning import _pin, read_candidate
from .observed_weight_learning import ts
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _read


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_RUNTIME_'+reason)


def _private_directory(path):
    root, descriptor = _directory(path)
    os.close(descriptor)
    return root


def _private_file(path):
    metadata = path.lstat()
    _need(stat.S_ISREG(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == 0o600 and
          metadata.st_uid == os.getuid(), 'PRIVATE_FILE_PERMISSIONS')


def _sources(value):
    references = set()
    def visit(item):
        if type(item) is dict:
            rights = item.get('source_rights_ref')
            for name in ('source_url', 'source_ref'):
                if type(item.get(name)) is str and type(rights) is str:
                    references.add((item[name], rights))
            for child in item.values():
                visit(child)
        elif type(item) in (list, tuple):
            for child in item:
                visit(child)
    visit(value)
    return references


def _hold(reason, *, requested=0, partitions=0):
    return dict(state='HOLD_PRIVATE_NATIVE_INPUTS', reason=reason,
        native_request_count=requested, partition_count=partitions, pending_removed=False,
        encrypted_readback_verified=False, independent_pre_cutoff_receipt_verified=False,
        production_promoted=False, actual_purchases=False, plaintext_published=False)


def _remove_original_pending(folder, originals):
    """Unlink only through the same private directory verified for cleanup."""
    pending, directory = _directory(folder)
    try:
        identity = os.fstat(directory)
        before = os.stat('pending.json', dir_fd=directory, follow_symlinks=False)
        _need(read_private_pending_requests(pending) == originals, 'PENDING_CHANGED_DURING_SEAL')
        current = pending.lstat()
        _need((current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino),
              'PENDING_DIRECTORY_CHANGED_DURING_SEAL')
        after = os.stat('pending.json', dir_fd=directory, follow_symlinks=False)
        signature = lambda value:(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        _need(signature(before) == signature(after) and os.listdir(directory) == ['pending.json'],
              'PENDING_CHANGED_DURING_SEAL')
        # A concurrent path replacement after the identity check can affect
        # neither this handle nor a new batch at the original directory name.
        os.unlink('pending.json', dir_fd=directory)
    finally:
        os.close(directory)


def _verify_output(root, summary, expected, expected_pairs, context):
    """Independently decrypt all partitions before disposing of any raw input."""
    _private_directory(root)
    children = list(root.iterdir())
    partitions = [path for path in children if re.fullmatch('[a-f0-9]{64}', path.name)]
    _need({path.name for path in children} == {'summary.json'} | {path.name for path in partitions} and
          len(partitions) == summary['partition_count'], 'OUTPUT_LAYOUT_INVALID')
    _private_file(root/'summary.json')
    public = read_json_bytes(_read(root/'summary.json', 1024*1024))
    _need(public == summary, 'OUTPUT_SUMMARY_MISMATCH')
    training = context['training']; training_sha = training['training_sha256']
    _need(summary['training_sha256'] == training_sha and summary['scope'] == training['scope'],
          'OUTPUT_TRAINING_MISMATCH')
    captured = []; cutoffs = []; forecast_members = []; forecast_races = set(); frozen_races = []
    unfitted = 0
    for folder in partitions:
        _private_directory(folder)
        _need({path.name for path in folder.iterdir()} == {'learning.enc', 'learning.json', 'summary.json'},
              'PARTITION_LAYOUT_INVALID')
        for path in folder.iterdir():
            _private_file(path)
        payload = read_candidate(folder)
        _need(verify_private_record(payload) is True, 'PARTITION_REPLAY_INVALID')
        _need(payload['training']['training_sha256'] == training_sha and
              digest(payload['training_receipt']) == digest(context['receipt']), 'PARTITION_TRAINING_MISMATCH')
        _need(folder.name == record_partition_key(payload), 'PARTITION_IDENTITY_INVALID')
        identity = record_identity(payload)
        if payload['schema'] == INPUTS_SCHEMA:
            frozen_races.append(identity)
        else:
            forecast_members.append((payload['cell_key'], payload['source_sha256']))
            forecast_races.add(identity)
        public = read_json_bytes(_read(folder/'summary.json', 1024*1024))
        _need(public == dict(payload['summary'], encrypted_readback_verified=True,
                            plaintext_published=False), 'PARTITION_SUMMARY_MISMATCH')
        cutoffs.append(_seal_cutoff(payload))
        for capsule in payload.get('captured_native_inputs', []):
            captured.append((capsule['cell_key'], capsule['input_sha256']))
            unfitted += capsule['cell_key'] not in training['models']
    _need(len(captured) == len(set(captured)) and set(captured) == expected,
          'CAPTURED_INPUTS_INCOMPLETE')
    _need(len(forecast_members) == len(set(forecast_members)) and
          set(forecast_members) == expected_pairs, 'FITTED_FORECASTS_INCOMPLETE')
    _need(len(frozen_races) == len(set(frozen_races)) and not set(frozen_races)&forecast_races,
          'DUPLICATE_RACE_CARRIER')
    _need(all(type(summary[field]) is int for field in ('forecast_partition_count',
          'baseline_forecast_count', 'learned_forecast_count', 'frozen_input_only_partition_count',
          'partition_count', 'captured_native_input_count', 'captured_unfitted_native_input_count')) and
          summary['captured_native_input_count'] == len(captured) and
          summary['captured_unfitted_native_input_count'] == unfitted, 'CAPTURED_INPUT_COUNTS_INVALID')
    _need(summary['forecast_partition_count'] == summary['baseline_forecast_count'] ==
          summary['learned_forecast_count'] == len(forecast_members) and
          summary['frozen_input_only_partition_count'] == len(frozen_races) and
          summary['partition_count'] == len(forecast_members)+len(frozen_races), 'PARTITION_COUNTS_INVALID')
    expected_state = ('ENCRYPTED_PRIVATE_NATIVE_PAIRS_LOCAL_ONLY' if forecast_members else
                      'ENCRYPTED_FROZEN_NATIVE_INPUTS_LOCAL_ONLY')
    _need(summary['state'] == expected_state, 'PARTITION_STATE_INVALID')
    return min(cutoffs)


def generate_current_pairs(runtime, pending_folder, output, *, now, additional_requests=()):
    """Return aggregate status after private input enrichment and exact readback."""
    started = time.monotonic()
    state_key('production')  # Before pending paths, context or grid are inspected.
    _need(type(now) is datetime and now.utcoffset() is not None, 'PHYSICAL_CLOCK_REQUIRED')
    root = _location(output)
    _need(not root.exists(), 'OUTPUT_EXISTS_DO_NOT_RESET')
    _private_directory(root.parent)
    _need(type(runtime) is dict and type(runtime.get('context')) is dict, 'CONTEXT_REQUIRED')
    context = deepcopy(runtime['context']); training = context.get('training')
    _need(type(training) is dict and training.get('schema') == SCHEMA, 'REGISTRY_CONTEXT_REQUIRED')
    verify_training(training)
    if training['state'] != 'FITTED_SHADOW_ONLY' or not training['models']:
        return _hold('NO_FITTED_MODELS')
    _training_receipt(training, context.get('receipt'), now)
    pointer = runtime.get('dataset_pointer', runtime.get('pointer'))
    if 'dataset_pointer' in runtime and 'pointer' in runtime:
        _need(runtime['dataset_pointer'] == runtime['pointer'], 'DATASET_POINTER_CONFLICT')
    url = _pin(pointer)
    _need(training.get('venue_dataset_sha256') == pointer['dataset_sha256'], 'TRAINING_DATASET_MISMATCH')
    verified = runtime['dataset_verified_at']
    verified = verified.isoformat() if type(verified) is datetime else verified
    _need(type(verified) is str and ts(verified) <= now, 'DATASET_CLOCK_INVALID')
    dataset = _private_directory(runtime['dataset_folder'])
    originals = read_private_pending_requests(pending_folder)
    if not originals:
        return _hold('NO_PENDING_INPUTS')
    references = _sources(originals) | {(url, RIGHTS)}
    requests = deepcopy(originals)
    extra = validate_additional_requests(additional_requests, now=now)
    if extra:
        from . import all_existing_model_registry as registry
        from .existing_model_dispatch import _race_key
        identities = set(); cohorts = {}
        def identity(request):
            info = registry.identity(request['cell_key'][5:], 'boat', request['native_payload'])
            race = _race_key(info['race_id'], 'boat')
            return (request['cell_key'], race), info, race
        def cohort(info):
            return (info['roster'], ts(info['race_cutoff_at']), info['scope'])
        for request in originals:
            key, info, race = identity(request)
            _need(race not in cohorts or cohorts[race] == cohort(info), 'ORIGINAL_RACE_BINDING_CONFLICT')
            cohorts[race] = cohort(info); identities.add(key)
        for request in extra:
            key, info, race = identity(request)
            _need(ts(info['as_of']) <= now < ts(info['cutoff_at']), 'ADDITIONAL_PHYSICAL_CLOCK')
            _need(race not in cohorts or cohorts[race] == cohort(info), 'ADDITIONAL_RACE_BINDING_CONFLICT')
            # The original five remain authoritative even when the engine's
            # equivalent native input has different builder/source metadata.
            if key in identities:
                continue
            references.update(_additional_source_pairs(request['native_payload'], as_of=info['as_of']))
            requests.append(request); identities.add(key); cohorts[race] = cohort(info)
    def analysis(source, rights, purpose):
        return purpose == 'analysis' and (source, rights) in references
    for request in requests:
        if request['cell_key'] not in {'boat/'+mid for mid in OBSERVED}:
            continue
        native = request['native_payload']; original = deepcopy(native)
        snapshot = deepcopy(native['snapshot'])
        _need(ts(snapshot['as_of']) <= now, 'FUTURE_PENDING_INPUT')
        snapshot['as_of'] = now.isoformat()
        native['snapshot'] = enrich_venue_snapshot(snapshot, dataset, pointer,
            verified_at=verified, allow_source=analysis, observed_only=True)['snapshot']
        native['original_native_payload'] = original
        native['original_input_sha256'] = digest(original)
    elapsed = time.monotonic()-started
    _need(elapsed >= 0, 'CLOCK_REGRESSED')
    physical = now+timedelta(seconds=elapsed)
    try:
        result = make_private_pairs(context, requests, root, now=physical, allow_source=analysis)
    except ValueError as exc:
        if str(exc) == 'ALL_MODEL_PRIVATE_PAIRS_CUTOFF_ELAPSED_DURING_SEAL':
            return _hold('QUARANTINED_CUTOFF_ELAPSED_DURING_SEAL', requested=len(requests))
        raise
    expected = {(request['cell_key'], digest(request['native_payload'])) for request in requests}
    expected_pairs = {(request['cell_key'], digest(request['native_payload']))
                      for request in requests if request['cell_key'] in training['models']}
    if (result.get('state') not in ('ENCRYPTED_PRIVATE_NATIVE_PAIRS_LOCAL_ONLY',
                                  'ENCRYPTED_FROZEN_NATIVE_INPUTS_LOCAL_ONLY') or
            result.get('encrypted_readback_verified') is not True or
            type(result.get('partition_count')) is not int or result['partition_count'] <= 0 or
            result.get('captured_native_input_count') != len(expected) or
            result.get('unretained_native_input_count') != 0):
        return _hold('INCOMPLETE_ENCRYPTED_NATIVE_INPUTS', requested=len(requests),
                     partitions=result.get('partition_count', 0))
    cutoff = _verify_output(root, result, expected, expected_pairs, context)
    elapsed = time.monotonic()-started
    _need(elapsed >= 0, 'CLOCK_REGRESSED')
    if now+timedelta(seconds=elapsed) >= cutoff:
        return _hold('QUARANTINED_CUTOFF_ELAPSED_DURING_READBACK', requested=len(requests),
                     partitions=result['partition_count'])
    # A new or changed pending batch must never be removed as an older batch's
    # cleanup. The private reader repeats source, hash and permission checks.
    _remove_original_pending(pending_folder, originals)
    return dict(result, native_request_count=len(requests), pending_removed=True)
