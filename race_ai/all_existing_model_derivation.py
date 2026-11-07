"""Deterministic research inputs from caller-authenticated observed originals.

The earlier receipt proves availability of the retained source observations,
not pre-cutoff storage of these newly constructed native payload bytes. This
module performs no authentication transport, collection, storage or fitting.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import re

from .actions_contract import digest
from .boat_all_model_inputs import shared_snapshot_from_observed
from .boat_multi_feature_models import MODEL_IDS as FULL, FEATURE_RANGES, CONDITIONS, SCHEMA_SPARSE
from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from .existing_model_dispatch import _race_key
from .four_sport_learning import LEARNED_ID
from .four_sport_model_suite import ALL_MODELS
from .observed_weight_learning import ts

SCHEMA = 'RACE_AI_EXISTING_MODEL_INPUT_DERIVATION_V1'
DERIVATION_ID = 'OBSERVED_TO_EXISTING_SPARSE_NATIVE_V1'
AVAILABILITY_BASIS = 'DERIVED_FROM_INDEPENDENT_PRE_CUTOFF_ORIGINAL'
NATIVE_SCHEMA = 'RACE_AI_EXISTING_MODEL_INPUT_DERIVATION_V2'
NATIVE_DERIVATION_ID = 'NATIVE_OBSERVED_CAPSULE_TO_EXISTING_SPARSE_NATIVE_V2'
NATIVE_AVAILABILITY_BASIS = 'DERIVED_FROM_AUTHENTICATED_PRE_CUTOFF_NATIVE_CAPSULE'
_GROUPS = {'shared': ALL_MODELS, 'boat_full': FULL, 'shared_learned': (LEARNED_ID,)}


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_DERIVATION_' + reason)


def _clock(now):
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    return now


def _original(record, now, *, allow_source=None, allow_training=None, structural=False):
    """Replay the existing bridge before accepting an original's claims.

    Structural replay's exact-source callbacks do not grant any rights. The
    caller already authenticated derive_records inputs; verify_derivation
    separately requires its external analysis and training authorizers.
    """
    from .all_existing_model_learning import _record, _sources, records_from_observed
    _need(type(record) is dict and record.get('model_id') in OBSERVED and
          record.get('sport') == 'boat' and 'input_derivation' not in record, 'OBSERVED_ORIGINAL_REQUIRED')
    if 'observed_row' not in record and 'observed_result' not in record:
        return _native_original(record, now, allow_source=allow_source,
                                allow_training=allow_training, structural=structural)
    row = record.get('observed_row'); result = record.get('observed_result')
    _need(type(row) is dict and type(result) is dict, 'RETAINED_OBSERVED_PROOF_REQUIRED')
    snapshot = row.get('learning_snapshot')
    _need(type(snapshot) is dict and row.get('learning_snapshot_sha256') == digest(snapshot),
          'ORIGINAL_SNAPSHOT_HASH')
    _need(record.get('native_payload') == dict(snapshot=snapshot, scope=snapshot.get('scope')),
          'ORIGINAL_PAYLOAD_BINDING')
    replay = records_from_observed([row], [result])
    _need(len(replay) == 1 and replay[0] == record, 'ORIGINAL_BRIDGE_BINDING')
    if structural:
        pairs = _sources(record['native_payload'])
        pairs.add((record['result'].get('source_ref'), record['result'].get('source_rights_ref')))
        allow_source = lambda ref, rights, purpose: purpose == 'analysis' and (ref, rights) in pairs
        allow_training = lambda ref, rights, purpose: purpose == 'model_training' and (ref, rights) in pairs
    return _record(record, now, allow_source, allow_training)


def _native_original(record, now, *, allow_source=None, allow_training=None, structural=False):
    """Replay a caller-authenticated native capsule's complete source binding.

    The archive reader owns decryption and the independently fetched metadata.
    This pure replay checks that its retained receipt, original native bytes,
    source clocks and separately authenticated result have not diverged. A
    self-hashed JSON document cannot authenticate itself through this helper.
    """
    from .all_existing_model_learning import _record, _sources
    from .all_existing_model_intake import _results, _ordinary_result
    from . import all_existing_model_registry as registry
    _need(record.get('stage') == 'P1', 'NATIVE_P1_ORIGINAL_REQUIRED')
    payload=record.get('native_payload');receipt=record.get('input_receipt')
    _need(type(payload) is dict and type(payload.get('snapshot')) is dict and
          record.get('input_sha256') == digest(payload), 'ORIGINAL_PAYLOAD_BINDING')
    _need(type(receipt) is dict and type(receipt.get('artifact_metadata')) is dict and
          receipt.get('independent_pre_cutoff_receipt_verified') is True, 'NATIVE_ARTIFACT_RECEIPT_REQUIRED')
    metadata=receipt['artifact_metadata'];run=metadata.get('workflow_run')
    run_id=receipt.get('workflow_run_id');head=receipt.get('head_sha');name=receipt.get('artifact_name')
    _need(type(receipt.get('artifact_id')) is int and receipt['artifact_id'] > 0 and
          metadata.get('id') == receipt['artifact_id'] and metadata.get('expired') is False and
          type(run_id) is int and run_id > 0 and type(run) is dict and run.get('id') == run_id and
          all(type(run.get(k)) is int and run[k] == 1416489937 for k in ('repository_id','head_repository_id')) and
          type(head) is str and re.fullmatch('[a-f0-9]{40}',head) and run.get('head_sha') == head,
          'NATIVE_ARTIFACT_IDENTITY_BINDING')
    _need(type(name) is str and metadata.get('name') == name and
          (re.fullmatch('all-existing-model-pairs-'+str(run_id)+'-[1-9][0-9]*',name) or
           re.fullmatch('boat-all-model-forecasts-'+str(run_id)+'-r[1-9][0-9]*',name)) and
          type(receipt.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}',receipt['digest']) and
          metadata.get('digest') == receipt['digest'] and type(metadata.get('size_in_bytes')) is int and
          0 < metadata['size_in_bytes'] <= 64*1024*1024, 'NATIVE_ARTIFACT_BYTES_BINDING')
    _need(all(type(record.get(k)) is str for k in ('input_saved_at','as_of','cutoff_at')) and
          all(type(metadata.get(k)) is str for k in ('created_at','expires_at')) and
          type(receipt.get('saved_at')) is str, 'NATIVE_ARTIFACT_CLOCK_BINDING')
    saved=ts(record['input_saved_at']);asof=ts(record['as_of']);cutoff=ts(record['cutoff_at'])
    _need(receipt.get('saved_at') == metadata.get('created_at') and
          ts(receipt['saved_at']) == saved and asof < saved+timedelta(seconds=1) < cutoff and
          saved <= now < ts(metadata.get('expires_at')), 'NATIVE_ARTIFACT_CLOCK_BINDING')
    partitions=record.get('input_partitions')
    _need(type(partitions) is list and 0 < len(partitions) <= 10000 and
          all(type(p) is dict and type(p.get('generated_at')) is str and
              asof <= ts(p['generated_at']) < saved+timedelta(seconds=1) for p in partitions),
          'NATIVE_PARTITION_CLOCK_BINDING')
    if name.startswith('boat-all-model-forecasts-'):
        _need(receipt.get('authenticated_original_artifact_verified') is True and
              receipt.get('model_input_sha256') == record['input_sha256'] and
              type(record.get('frozen_native_payload')) is dict and
              receipt.get('frozen_native_input_sha256') == digest(record['frozen_native_payload']) and
              all(p.get('capsule_sha256') == receipt.get('capsule_sha256') and
                  p.get('dispatch_input_sha256') == receipt.get('dispatch_input_sha256') for p in partitions),
              'NATIVE_ROUND_CAPSULE_BINDING')
    else:
        _need(all(any(type(p.get(k)) is str and re.fullmatch('[a-f0-9]{64}',p[k])
                      for k in ('pair_sha256','native_inputs_record_sha256')) for p in partitions),
              'NATIVE_PRIVATE_CAPSULE_BINDING')
    info=registry.identity(record['model_id'],'boat',payload,race_id=record['race_id'])
    observation=record.get('result_observation')
    _need(type(observation) is dict, 'NATIVE_SEPARATE_RESULT_REQUIRED')
    outcomes,_=_results([observation],now)
    key=('boat',_race_key(record['race_id'],'boat'))
    _need(key in outcomes, 'NATIVE_RESULT_IDENTITY_BINDING')
    outcome,reason=_ordinary_result(outcomes[key]['result'],info,now)
    _need(reason is None and outcome == record.get('result'), 'NATIVE_RESULT_REPLAY_BINDING')
    if structural:
        pairs=_sources(payload)
        pairs.add((record['result'].get('source_ref'),record['result'].get('source_rights_ref')))
        allow_source=lambda ref,rights,purpose: purpose == 'analysis' and (ref,rights) in pairs
        allow_training=lambda ref,rights,purpose: purpose == 'model_training' and (ref,rights) in pairs
    return _record(record,now,allow_source,allow_training)


def _proof(source):
    return dict(source_ref=source['source_url'], source_rights_ref=source['source_rights_ref'],
                source_sha256=source['source_sha256'], published_at=source['published_at'],
                captured_at=source['captured_at'])


def _full_payload(original):
    observed = original['native_payload']['snapshot']
    sources = {source['source_id']: source for source in observed['sources']}
    primary = sources[observed['race_source_id']]
    entrants = []; lineage = {}
    mappings = [('national_win_rate', 'ability_rating', lambda value: value*10,
                 'official-national-win-rate-times10-v1'),
                ('motor_top2_rate', 'motor_rating', lambda value: value,
                 'official-motor-top2-percent-identity-v1')]
    if observed['stage'] == 'P1':
        mappings += [('exhibition_time_seconds', 'exhibition_time_seconds', lambda value: value,
                      'official-exhibition-seconds-identity-v1'),
                     ('exhibition_start_seconds', 'exhibition_start_seconds', lambda value: value,
                      'official-exhibition-start-seconds-identity-v1')]
    for entrant in sorted(observed['participants'], key=lambda row: row['lane']):
        features = {}; used = {primary['source_id']: primary}; member_lineage = {}
        for old, name, transform, transform_id in mappings:
            feature = entrant['features'].get(old)
            if feature is None:
                continue
            source = sources[feature['source_id']]
            used[source['source_id']] = source
            features[name] = transform(feature['value'])
            member_lineage[name] = dict(_proof(source), original_feature=old,
                                       original_source_id=source['source_id'], transform_id=transform_id)
        publications = [source['published_at'] for source in used.values()]
        publication = None if any(value is None for value in publications) else max(publications, key=ts)
        entrants.append(dict(lane=entrant['lane'], participant_id=entrant['registration_no'], features=features,
            missing={name: ('NOT_YET_PUBLISHED' if observed['stage'] == 'P0' and name.startswith('exhibition_')
                            else 'NOT_AVAILABLE') for name in FEATURE_RANGES if name not in features},
            source_ref=primary['source_url'], published_at=publication,
            captured_at=max((source['captured_at'] for source in used.values()), key=ts)))
        lineage[str(entrant['lane'])] = member_lineage
    snapshot = dict(schema=SCHEMA_SPARSE, scope=observed['scope'], race_id=observed['race_id'],
        venue=observed['venue'], event_date_jst=observed['event_date_jst'],
        sales_cutoff_at=observed['sales_cutoff_at'], as_of=observed['as_of'], entrants=entrants,
        conditions={}, conditions_missing={name: 'NOT_AVAILABLE' for name in CONDITIONS},
        conditions_source=None, conditions_published_at=None, conditions_captured_at=None)
    return dict(scope=observed['scope'], stage=observed['stage'], snapshot=snapshot,
                source_evidence=[_proof(source) for source in observed['sources']], feature_lineage=lineage)


def _native(original, group):
    if group == 'boat_full':
        return _full_payload(original)
    return dict(scope=original['scope'], stage=original['stage'],
                snapshot=shared_snapshot_from_observed(original['native_payload']['snapshot']))


def _derive(original, model_id, group, derived_at):
    payload = _native(original, group); fingerprint = digest(payload)
    if 'observed_row' not in original:
        proof = dict(schema=NATIVE_SCHEMA, derivation_id=NATIVE_DERIVATION_ID, derived_at=derived_at,
            original_record=deepcopy(original), original_record_sha256=digest(original),
            original_model_id=original['model_id'], original_payload_sha256=original['input_sha256'],
            original_snapshot_sha256=digest(original['native_payload']['snapshot']),
            original_input_receipt=deepcopy(original['input_receipt']),
            original_input_receipt_sha256=digest(original['input_receipt']),
            original_input_saved_at=original['input_saved_at'], original_as_of=original['as_of'],
            original_cutoff_at=original['cutoff_at'], native_input_sha256=fingerprint,
            data_availability_basis=NATIVE_AVAILABILITY_BASIS,
            derived_payload_saved_before_cutoff=False, historical_native_payload_bytes=False)
        return dict(model_id=model_id,sport='boat',race_id=original['race_id'],stage=original['stage'],
            scope=original['scope'],as_of=original['as_of'],cutoff_at=original['cutoff_at'],
            native_payload=payload,input_sha256=fingerprint,input_saved_at=original['input_saved_at'],
            input_receipt=deepcopy(original['input_receipt']),result=deepcopy(original['result']),
            input_derivation=proof)
    proof = dict(schema=SCHEMA, derivation_id=DERIVATION_ID, derived_at=derived_at,
        original_record=deepcopy(original), original_record_sha256=digest(original),
        original_model_id=original['model_id'], original_payload_sha256=original['input_sha256'],
        original_snapshot_sha256=original['observed_row']['learning_snapshot_sha256'],
        original_input_receipt=deepcopy(original['input_receipt']), original_input_saved_at=original['input_saved_at'],
        original_as_of=original['as_of'], original_cutoff_at=original['cutoff_at'],
        native_input_sha256=fingerprint, data_availability_basis=AVAILABILITY_BASIS,
        derived_payload_saved_before_cutoff=False)
    return dict(model_id=model_id, sport='boat', race_id=original['race_id'], stage=original['stage'],
                scope=original['scope'], as_of=original['as_of'], cutoff_at=original['cutoff_at'],
                native_payload=payload, input_sha256=fingerprint, input_saved_at=original['input_saved_at'],
                input_receipt=deepcopy(original['input_receipt']), result=deepcopy(original['result']),
                input_derivation=proof)


def derive_records(observed_records, *, now, include_groups=('shared', 'boat_full')):
    """Expand retained observations once per race into existing native cells.

    Input records come from the caller's authenticated observed journal reader
    or authenticated P1 native capsule reader. Their V1 and V2 proof formats
    remain separate. Local replay creates no independent source receipt or
    model-training permission. Latest as-of wins, with P1 preferred at equal
    times, matching the existing observed cohort selection.
    """
    _clock(now)
    _need(type(observed_records) is list, 'OBSERVED_RECORD_LIST_REQUIRED')
    _need(type(include_groups) in (tuple, list) and len(include_groups) == len(set(include_groups)) and
          all(group in _GROUPS for group in include_groups), 'SUPPORTED_GROUPS_REQUIRED')
    selected = {}; buckets = {}
    for supplied in observed_records:
        original = _original(supplied, now, structural=True)
        key = _race_key(original['race_id'], 'boat')
        order = (ts(original['as_of']), original['stage'] == 'P1')
        bucket = (key, order)
        if bucket in buckets:
            previous = buckets[bucket]
            _need(digest(original['native_payload']['snapshot']) ==
                  digest(previous['native_payload']['snapshot']) and original['result'] == previous['result'],
                  'CONFLICTING_ORIGINALS')
        else:
            buckets[bucket] = original
        if key not in selected or order > selected[key][0]:
            selected[key] = (order, original)
        elif order == selected[key][0]:
            previous = selected[key][1]
            stable = lambda row: (row['model_id'], ts(row['input_saved_at']), digest(row))
            if stable(original) < stable(previous):
                selected[key] = (order, original)
    return [_derive(original, model_id, group, now.isoformat())
            for key, (_, original) in sorted(selected.items())
            for group in include_groups for model_id in _GROUPS[group]]


def verify_derivation(record, *, now, allow_source=None, allow_training=None):
    """Verify deterministic derivation from a caller-authenticated original.

    An arbitrary self-hashed original cannot become independently authenticated
    through this function. Its caller must retain the original journal/archive
    admission, and separately authorize analysis and model training.
    """
    from . import all_existing_model_registry as registry
    _clock(now)
    _need(type(record) is dict and type(record.get('input_derivation')) is dict, 'PROOF_REQUIRED')
    proof = record['input_derivation']
    legacy=proof.get('schema') == SCHEMA and proof.get('derivation_id') == DERIVATION_ID and \
        proof.get('data_availability_basis') == AVAILABILITY_BASIS
    native=proof.get('schema') == NATIVE_SCHEMA and proof.get('derivation_id') == NATIVE_DERIVATION_ID and \
        proof.get('data_availability_basis') == NATIVE_AVAILABILITY_BASIS and \
        proof.get('historical_native_payload_bytes') is False
    _need((legacy or native) and proof.get('derived_payload_saved_before_cutoff') is False, 'PROOF_SEMANTICS')
    original = _original(proof.get('original_record'), now,
                         allow_source=allow_source, allow_training=allow_training)
    _need(legacy == ('observed_row' in original), 'ORIGINAL_PROOF_KIND_BINDING')
    _need(type(proof.get('derived_at')) is str and
          ts(original['input_saved_at']) <= ts(proof['derived_at']) <= now, 'DERIVATION_CLOCK')
    model_id = record.get('model_id')
    group = next((name for name, models in _GROUPS.items() if model_id in models), None)
    _need(group is not None, 'UNSUPPORTED_TARGET')
    expected = _derive(original, model_id, group, proof['derived_at'])
    _need(record == expected, 'DETERMINISTIC_REPLAY_BINDING')
    registry.validate_payload(model_id, 'boat', record['native_payload'], at=record['as_of'],
                              allow_source=allow_source, race_id=record['race_id'])
    return True
