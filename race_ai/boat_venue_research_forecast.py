"""Private future P1 research using the two existing observed model families.

The original public P1 bundle remains unchanged. A new physical input version
adds the pinned venue features and holds both paired forecasts in owner
ciphertext. Local validation and replay never assert an external freeze or a
provider licence. This module performs no HTTP, Git operations or scheduling.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import re
import time

from .actions_contract import digest
from .boat_observed_pairwise_models import (
    FEATURE_TRANSFORMS, HISTORY_FIELDS, MODEL_IDS, _validate, predict_pair as run_suite,
)
from .boat_pdca_state import state_key
from .boat_venue_feature_adapter import FIELDS, RIGHTS, enrich_venue_snapshot
from .boat_venue_learning import _pin, seal_candidate
from .frozen_day_cycle import official_id, sealed
from .observed_p1_connection import RIGHTS as P1_RIGHTS, SCHEMA as P1_SCHEMA, locator
from .observed_result_history import verify_history_evidence
from .observed_weight_learning import make_shadows, verify_training

SCHEMA = 'RACE_AI_PRIVATE_VENUE_P1_FORECAST_V1'
PAYLOAD_FIELDS = {'schema', 'generated_at', 'original_bundle', 'original_bundle_sha256',
                  'snapshot', 'baseline_suite', 'training', 'training_receipt', 'shadows',
                  'venue_evidence', 'dataset_pointer', 'dataset_verified_at', 'summary', 'excluded'}
POINTER_FIELDS = {'schema', 'status', 'repository_id', 'source_commit', 'dataset_sha256', 'dataset_path'}


def _need(ok, reason):
    if not ok:
        raise ValueError('VENUE_PRIVATE_P1_' + reason)


def _time(value):
    try:
        result = value if type(value) is datetime else datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(result.utcoffset() is not None, 'AWARE_TIME_REQUIRED')
        return result
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('VENUE_PRIVATE_P1_AWARE_TIME_REQUIRED') from exc


def _frozen_source_replay(snapshot):
    pairs = {(s['source_url'], s['source_rights_ref']) for s in snapshot['sources']}
    return lambda url, rights, purpose: (url, rights) in pairs and purpose == 'analysis'


def verify_bundle(bundle, *, allow_source=None):
    """Validate the original native 2/3-source bundle without inventing a receipt."""
    try:
        fields = {'schema', 'race_id', 'base_source_sha256', 'snapshot', 'suite', 'http_provenance',
                  'source_locator_semantics', 'actual_purchases', 'new_model', 'bundle_sha256'}
        _need(type(bundle) is dict, 'ORIGINAL_SCHEMA_INVALID')
        has_history = 'history_evidence' in bundle
        _need(set(bundle) == fields | ({'history_evidence'} if has_history else set()) and
              bundle.get('schema') == P1_SCHEMA and
              bundle.get('actual_purchases') is False and bundle.get('new_model') is False,
              'ORIGINAL_SCHEMA_INVALID')
        _need(type(bundle['base_source_sha256']) is str and re.fullmatch('[a-f0-9]{64}', bundle['base_source_sha256']) and
              bundle['source_locator_semantics'] == 'QUERY_FREE_LOCATOR_WITH_EXACT_REQUEST_BESIDE_IT',
              'ORIGINAL_SOURCE_SCHEMA_INVALID')
        sealed(bundle, 'bundle_sha256')
        snapshot = bundle['snapshot']; _validate(snapshot)
        _need(snapshot['stage'] == 'P1' and snapshot['scope'] == 'OPERATOR_SUPPLIED_RESEARCH' and
              official_id(snapshot['race_id']) == bundle['race_id'], 'ORIGINAL_IDENTITY_INVALID')
        _need(type(bundle['http_provenance']) is list and
              len(bundle['http_provenance']) == len(snapshot['sources']) == (3 if has_history else 2),
              'ORIGINAL_SOURCE_COUNT_INVALID')
        for kind, source, proof in zip(('racelist', 'beforeinfo'), snapshot['sources'], bundle['http_provenance']):
            _need(type(proof) is dict and set(proof) == {'source_id', 'request_url', 'source_sha256', 'captured_at'} and
                  source['source_url'] == locator(proof['request_url'], kind, bundle['race_id']) and
                  source['source_rights_ref'] == P1_RIGHTS and
                  all(source[key] == proof[key] for key in ('source_id', 'source_sha256', 'captured_at')) and
                  _time(proof['captured_at']) <= _time(snapshot['as_of']), 'ORIGINAL_SOURCE_BINDING')
        if has_history:
            history = verify_history_evidence(bundle['history_evidence'], race_id=bundle['race_id'],
                                               participants=snapshot['participants'], as_of=snapshot['as_of'])
            source = history['source']
            _need(snapshot['sources'][2] == source and bundle['http_provenance'][2] == dict(
                source_id=source['source_id'], request_url=source['source_url'],
                source_sha256=source['source_sha256'], captured_at=source['captured_at']),
                'ORIGINAL_HISTORY_SOURCE_BINDING')
            by_lane = {p['lane']: p for p in history['participants']}
            for participant in snapshot['participants']:
                prior = by_lane[participant['lane']]
                _need({k:v for k,v in participant['features'].items() if k in HISTORY_FIELDS} == prior['features'] and
                      {k:v for k,v in participant['missing'].items() if k in HISTORY_FIELDS} == prior['missing'],
                      'ORIGINAL_HISTORY_MEMBERSHIP')
        else:
            _need(all(not HISTORY_FIELDS.intersection(p['features']) for p in snapshot['participants']),
                  'ORIGINAL_HISTORY_EVIDENCE_REQUIRED')
        replay = run_suite(snapshot, allow_source=allow_source if allow_source is not None else _frozen_source_replay(snapshot))
        _need(digest(bundle['suite']) == digest(replay), 'ORIGINAL_NATIVE_REPLAY_MISMATCH')
        return True
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('VENUE_PRIVATE_P1_ORIGINAL_INVALID') from exc


def _check_training(training, pointer):
    _need(type(pointer) is dict and set(pointer) == POINTER_FIELDS, 'DATASET_POINTER_INVALID')
    _pin(pointer)
    _need(type(training) is dict, 'OWNER_TRAINING_REQUIRED')
    verify_training(training)
    _need(training.get('state') == 'FITTED_SHADOW_ONLY' and
          training.get('training_basis') == 'OWNER_PERSONAL_RESEARCH' and
          training.get('provider_permission_confirmed') is False and
          training.get('venue_dataset_sha256') == pointer['dataset_sha256'], 'OWNER_TRAINING_DATASET_MISMATCH')


def _expected_participant(original, evidence, source_id):
    """Replay observed-only course features from the frozen profile evidence."""
    participant = deepcopy(original)
    for name in FIELDS:
        participant['features'].pop(name, None); participant['missing'][name] = 'NO_PRIOR_SAMPLES'
    profile = evidence['profile']; bucket = profile['by_actual_course'][str(participant['lane'])]
    n = bucket['opportunities']
    if not n:
        return participant
    def add(name, value, ok, f=0, l=0, missing=0):
        _need(ok > 0 and ok+f+l+missing == n and missing >= 0, 'VENUE_COUNTS_INVALID')
        participant['features'][name] = dict(value=value, sample_n=ok, source_id=source_id,
            transform_id=FEATURE_TRANSFORMS[name], history=dict(
                window_id='official-venue-course-observed-published-files-only-'+digest(evidence),
                total_n=n, ok_n=ok, f_n=f, l_n=l, missing_n=missing, unresolved_n=0))
        participant['missing'].pop(name, None)
    if bucket['numeric_finish_n'] == n and not bucket['special_result_n']:
        add('course_mean_finish', sum((i+1)*count for i,count in enumerate(bucket['finish_counts']))/n, n)
    else:
        participant['missing']['course_mean_finish'] = 'UNRESOLVED_DISPOSITION'
    statuses = bucket.get('st_status_counts')
    if (bucket['st_n'] and type(statuses) is dict and all(type(v) is int and v >= 0 for v in statuses.values())
            and sum(statuses.values()) == n and statuses.get('OK', 0) == bucket['st_n']):
        f = statuses.get('F', 0); l = statuses.get('L', 0)
        add('course_mean_st', bucket['mean_st'], bucket['st_n'], f, l, n-bucket['st_n']-f-l)
    else:
        participant['missing']['course_mean_st'] = 'UNRESOLVED_DISPOSITION'
    return participant


def _summary(payload):
    participants = payload['snapshot']['participants']; evidence = payload['venue_evidence']
    return dict(schema='RACE_AI_PRIVATE_VENUE_P1_COUNTS_V1', state='ENCRYPTED_PRIVATE_VENUE_P1_LOCAL_ONLY',
        baseline_model_count=2, learned_shadow_count=2, participant_count=6,
        course_st_participants=sum('course_mean_st' in p['features'] for p in participants),
        source_coverage_complete=all(e['profile']['history_completeness'] for e in evidence.values()),
        original_bundle_sha256=payload['original_bundle_sha256'], training_sha256=payload['training']['training_sha256'],
        dataset_sha256=payload['dataset_pointer']['dataset_sha256'],
        provider_permission_confirmed=False, production_promoted=False, actual_purchases=False,
        independent_pre_cutoff_receipt_verified=False, baseline_coefficients_changed=False, plaintext_published=False)


def verify_private_forecast(payload):
    """Pure encrypted-payload replay; external archive/clock checks are caller-owned."""
    try:
        _need(type(payload) is dict and set(payload) == PAYLOAD_FIELDS and payload['schema'] == SCHEMA and
              type(payload['summary']) is dict and type(payload['shadows']) is list and
              type(payload['venue_evidence']) is dict and type(payload['baseline_suite']) is dict and
              type(payload['training_receipt']) is dict and payload['excluded'] == [], 'PAYLOAD_SCHEMA_INVALID')
        original = payload['original_bundle']; verify_bundle(original)
        _need(payload['original_bundle_sha256'] == original['bundle_sha256'], 'ORIGINAL_HASH_MISMATCH')
        pointer = payload['dataset_pointer']; _check_training(payload['training'], pointer)
        snapshot = payload['snapshot']; _validate(snapshot)
        generated = _time(payload['generated_at']); verified = _time(payload['dataset_verified_at'])
        _need(snapshot['as_of'] == payload['generated_at'] and
              _time(original['snapshot']['as_of']) <= generated < _time(snapshot['sales_cutoff_at']) and
              verified <= generated, 'INPUT_CLOCK_INVALID')
        source_id = 'official-venue-grid-'+pointer['dataset_sha256'][:16]
        source = dict(source_id=source_id, source_url=_pin(pointer), source_sha256=pointer['dataset_sha256'],
                      source_rights_ref=RIGHTS, published_at=None, captured_at=payload['dataset_verified_at'],
                      evidence_basis='CAPTURED_BY_CLAIM')
        expected = deepcopy(original['snapshot']); expected['as_of'] = payload['generated_at']
        expected['sources'].append(source)
        evidence = payload['venue_evidence']
        _need(set(evidence) == {p['registration_no'] for p in expected['participants']}, 'VENUE_ROSTER_MISMATCH')
        for index, participant in enumerate(expected['participants']):
            entry = evidence[participant['registration_no']]; profile = entry['profile']
            _need(type(entry) is dict and set(entry) == {'profile', 'condition', 'current_frame', 'period_start',
                  'period_end', 'source_scope', 'unknown_course_rows_excluded_without_membership_inference'} and
                  profile['racer_id'] == participant['registration_no'] and
                  profile['venue_code'] == snapshot['venue'].removeprefix('boatrace-jcd-') and
                  _time(profile['as_of']) <= verified and
                  type(profile['history_completeness']) is bool and
                  entry['condition'] == 'HISTORICAL_ACTUAL_COURSE_EQUALS_CURRENT_FRAME_NOT_CURRENT_ENTRY' and
                  entry['current_frame'] == participant['lane'] and
                  entry['source_scope'] == 'OBSERVED_KNOWN_COURSE_ROWS_IN_PUBLISHED_FILES_ONLY' and
                  entry['unknown_course_rows_excluded_without_membership_inference'] == profile['stats']['unknown_course_n'] and
                  date.fromisoformat(entry['period_start']) <= date.fromisoformat(entry['period_end']) <
                  date.fromisoformat(snapshot['event_date_jst']), 'VENUE_EVIDENCE_INVALID')
            expected['participants'][index] = _expected_participant(participant, entry, source_id)
        _need(snapshot == expected, 'ENRICHED_INPUT_REPLAY_MISMATCH')
        replay = run_suite(snapshot, allow_source=_frozen_source_replay(snapshot))
        _need(digest(payload['baseline_suite']) == digest(replay), 'BASELINE_REPLAY_MISMATCH')
        context = dict(training=payload['training'], receipt=payload['training_receipt'])
        _need(payload['shadows'] == make_shadows(snapshot, replay, context), 'LEARNED_REPLAY_MISMATCH')
        _need(digest(payload['summary']) == digest(_summary(payload)), 'SUMMARY_BINDING_INVALID')
        return True
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError('VENUE_PRIVATE_P1_PAYLOAD_INVALID') from exc


def forecast_private_venue_p1(bundle, context, dataset_folder, dataset_pointer, output, *,
                              now, dataset_verified_at, allow_source):
    """Create exactly one encrypted private same-input baseline/learned P1 pair."""
    started = time.monotonic(); state_key('production')
    _need(type(now) is datetime, 'PHYSICAL_CLOCK_REQUIRED'); now = _time(now)
    original = deepcopy(bundle); context = deepcopy(context); pointer = deepcopy(dataset_pointer)
    _check_training(context.get('training'), pointer)
    _need(callable(allow_source), 'ANALYSIS_ADMISSION_REQUIRED')
    verify_bundle(original, allow_source=allow_source)
    snapshot = deepcopy(original['snapshot']); cutoff = _time(snapshot['sales_cutoff_at'])
    verified = _time(dataset_verified_at)
    _need(_time(snapshot['as_of']) <= now and verified <= now and cutoff-now > timedelta(seconds=210),
          'PHYSICAL_CUTOFF_REQUIRED')
    snapshot['as_of'] = now.isoformat()
    enrichment = enrich_venue_snapshot(snapshot, dataset_folder, pointer,
        verified_at=verified.isoformat(), allow_source=allow_source, observed_only=True)
    snapshot = enrichment['snapshot']; baseline = run_suite(snapshot, allow_source=allow_source)
    shadows = make_shadows(snapshot, baseline, context)
    _need(len(shadows) == len(MODEL_IDS), 'TWO_SHADOWS_REQUIRED')
    payload = dict(schema=SCHEMA, generated_at=now.isoformat(), original_bundle=original,
        original_bundle_sha256=original['bundle_sha256'], snapshot=snapshot, baseline_suite=baseline,
        training=context['training'], training_receipt=context['receipt'], shadows=shadows,
        venue_evidence=enrichment['venue_evidence'], dataset_pointer=pointer,
        dataset_verified_at=verified.isoformat(), excluded=[])
    payload['summary'] = _summary(payload)
    # Native model specifications contain tuples. Freeze one JSON-native
    # representation before encryption so exact readback comparison remains
    # meaningful, including the retained original bundle and baseline suite.
    payload = json.loads(json.dumps(payload, allow_nan=False))
    verify_private_forecast(payload)
    result = seal_candidate(payload, output)
    elapsed = time.monotonic()-started
    _need(elapsed >= 0 and now+timedelta(seconds=elapsed) < cutoff, 'CUTOFF_ELAPSED_DURING_SEAL')
    return result
