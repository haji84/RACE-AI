"""Attach an existing authenticated native ranker without changing source facts.

Artifact transports and current-source authorization belong to the caller.
The attachment records a structural replay and creates no source permission,
external receipt, fitted parameters or retrospective source availability.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hmac
import re

from .actions_contract import digest, stamp
from . import all_existing_model_research as research
from . import all_existing_model_registry as registry
from .all_existing_model_learning import _sources, verify_training
from .all_existing_model_pairs import _training_receipt
from .boat_pdca_state import state_key
from .boat_venue_learning_context import (
    BASE, MAX_ARCHIVE_BYTES, _candidate_from_zip, context_from_encrypted_artifact,
)
from .comprehensive_four_sport_models import SCHEMA as NATIVE_SCHEMA, validate
from .four_sport_learning import LEARNED_ID

SCHEMA = 'RACE_AI_FUTURE_NATIVE_BASELINE_ATTACHMENT_V1'
PIN_FIELDS = {'id', 'digest', 'run_id', 'head_sha'}
PROOF_FIELDS = {'schema', 'pin', 'artifact_receipt', 'training_sha256', 'model_sha256',
    'native_model_sha256', 'owner_research_record_sha256', 'source_metadata', 'attached_at',
    'original_payload_sha256', 'source_lineage', 'owner_research_record', 'historical_source_refs'}
SPORTS = frozenset(('boat', 'autorace', 'keirin', 'horse'))


def _need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_FUTURE_BASELINE_' + reason)


def _clock(value):
    if type(value) is str:
        value = stamp(value)
    _need(type(value) is datetime and value.utcoffset() is not None, 'AWARE_CLOCK')
    return value


def _hash(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def validate_pin(pin):
    _need(type(pin) is dict and set(pin) == PIN_FIELDS and
        all(type(pin[k]) is int and 0 < pin[k] < 10**20 for k in ('id', 'run_id')) and
        type(pin['digest']) is str and re.fullmatch('sha256:[a-f0-9]{64}', pin['digest']) and
        type(pin['head_sha']) is str and re.fullmatch('[a-f0-9]{40}', pin['head_sha']), 'ARTIFACT_PIN')
    return deepcopy(pin)


def verify_owner(training, owner, *, schema=None):
    """Verify the original fit decision at its original training clock."""
    verify_training(training)
    _need(schema in (None, research.SCHEMA, research.ORDER_SCHEMA), 'OWNER_SCHEMA')
    _need(type(owner) is dict and set(owner) == {'schema', 'decision', 'mac'} and
        owner['schema'] in (research.SCHEMA, research.ORDER_SCHEMA) and
        (schema is None or owner['schema'] == schema), 'OWNER_SCHEMA')
    version = owner['schema']; order = version == research.ORDER_SCHEMA
    fields = research.FIELDS | ({'label_evaluation_scope'} if order else set())
    decision = owner['decision']
    _need(type(decision) is dict and set(decision) == fields and _hash(owner['mac']) and
        hmac.compare_digest(owner['mac'], research._mac(decision, schema=version)), 'OWNER_MAC')
    scope = research._scope(training['registry_sha256'])
    clock = _clock(training['created_at'])
    _need(training.get('state') == 'FITTED_SHADOW_ONLY' and training.get('training_basis') == 'OWNER_PERSONAL_RESEARCH' and
        decision['repository_id'] == '1416489937' and decision['basis'] == 'OWNER_PERSONAL_RESEARCH' and
        decision['purpose'] == (research.ORDER_PURPOSE if order else research.PURPOSE) and
        decision['instruction_ref'] == research.INSTRUCTION and
        all(decision[k] is False for k in research.FALSE_FIELDS) and
        _clock(decision['issued_at']) <= clock < _clock(decision['expires_at']) and
        all(_hash(decision[k]) for k in ('source_pointer_sha256', 'source_content_sha256',
            'dataset_pointer_sha256', 'source_refs_sha256', 'intake_sha256')) and
        all(decision[k] == v for k, v in scope.items()) and
        sorted(decision['registered_model_ids']) == training['registered_model_ids'] and
        decision['source_content_sha256'] == training.get('source_content_sha256') and
        decision['intake_sha256'] == training.get('owner_bound_intake_sha256', training['source_intake_sha256']) and
        digest(owner) == training.get('owner_research_decision_sha256'), 'OWNER_TRAINING_BINDING')
    if order:
        from .official_order_only_result import EVALUATION_SCOPE
        _need(decision['label_evaluation_scope'] == training.get('label_evaluation_scope') == EVALUATION_SCOPE and
            training.get('monetary_evaluation_available') is False, 'OWNER_LABEL_SCOPE')
    else:
        _need('label_evaluation_scope' not in training and 'monetary_evaluation_available' not in training, 'OWNER_LABEL_SCOPE')
    return True


def _receipt_pin(receipt):
    run = receipt.get('workflow_run') if type(receipt) is dict else None
    _need(type(run) is dict, 'ARTIFACT_RECEIPT')
    return validate_pin(dict(id=receipt.get('id'), digest=receipt.get('digest'),
        run_id=run.get('id'), head_sha=run.get('head_sha')))


def load_baseline(pin, *, now, fetch_metadata, fetch_zip):
    """Use caller-supplied artifact reads, authenticating all four pin fields."""
    state_key('production')
    pin = validate_pin(pin); now = _clock(now)
    _need(callable(fetch_metadata) and callable(fetch_zip), 'ARTIFACT_READERS_REQUIRED')
    raw = fetch_zip(pin['id'])
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE_BYTES, 'ARCHIVE_BOUND')
    def actual(url):
        _need(url == BASE + '/actions/artifacts/' + str(pin['id']), 'METADATA_ROUTE')
        value = fetch_metadata(pin['id'])
        _need(type(value) is dict and _receipt_pin(value) == pin, 'ACTUAL_PIN_BINDING')
        name = value.get('name')
        _need(type(name) is str and re.fullmatch(
            '(?:boat-venue-learning|all-existing-model-learning)-' + str(pin['run_id']) + '-[1-9][0-9]*', name),
            'ACTUAL_ARTIFACT_NAME')
        return value
    context = context_from_encrypted_artifact(raw, pin['id'], now=now, _fetch=actual)
    owner = _candidate_from_zip(raw).get('owner_research_record')
    verify_owner(context['training'], owner)
    _need(any(cell == sport + '/' + LEARNED_ID and type(model.get('native_training')) is dict
        for cell, model in context['training']['models'].items() for sport in SPORTS), 'NATIVE_RANKER_REQUIRED')
    return dict(context, owner_research_record=deepcopy(owner))


def _selected(payload, context, sport, now):
    _need(type(context) is dict and set(context) == {'training', 'receipt', 'owner_research_record'}, 'ACTUAL_CONTEXT_REQUIRED')
    verify_owner(context['training'], context['owner_research_record'])
    _training_receipt(context['training'], context['receipt'], now)
    _need(type(sport) is str and sport in SPORTS and type(payload) is dict and
        type(payload.get('snapshot')) is dict, 'NATIVE_PAYLOAD_REQUIRED')
    key = sport + '/' + LEARNED_ID; model = context['training']['models'].get(key)
    _need(type(model) is dict and type(model.get('native_training')) is dict, 'SPORT_NATIVE_RANKER_REQUIRED')
    native = model['native_training']; snapshot = payload['snapshot']; race = snapshot.get('race', {})
    _need(race.get('sport') == sport and model['sport'] == native.get('sport') == sport and
        snapshot.get('schema') == model.get('input_schema', NATIVE_SCHEMA) == native.get('input_schema', NATIVE_SCHEMA) and
        snapshot.get('scope') == context['training']['scope'] == native.get('trained_scope') and
        payload.get('scope', snapshot['scope']) == snapshot['scope'], 'NATIVE_MODEL_SCHEMA_OR_SCOPE')
    asof = _clock(race.get('as_of'))
    _need(_clock(native['trained_until']) < asof and _clock(native['created_at']) <= asof <= now, 'NATIVE_MODEL_CLOCK')
    # Structural replay only. The caller still independently admits the exact
    # current and historical source pairs before inference or persistence.
    refs = _sources(payload)
    validate(snapshot, allow_source=lambda ref, rights, purpose: purpose == 'analysis' and (ref, rights) in refs)
    return model


def _source(payload, model, receipt, metadata, attached_at):
    _need(type(metadata) is dict and type(metadata.get('status')) is int and metadata['status'] == 200 and
        type(metadata.get('source_url')) is str and _hash(metadata.get('source_sha256')), 'CURRENT_CARD_METADATA')
    fetched = _clock(metadata.get('fetched_at')); completed = _clock(metadata.get('response_received_at'))
    _need(_clock(model['native_training']['created_at']) < fetched and
        _clock(receipt['created_at']) + timedelta(seconds=1) <= fetched <= completed <=
        _clock(payload['snapshot']['race']['as_of']) <= attached_at, 'CURRENT_CARD_CLOCK')
    evidence = payload.get('source_evidence')
    _need(type(evidence) is list and any(type(item) is dict and
        item.get('source_ref', item.get('source_url')) == metadata['source_url'] and
        item.get('source_sha256') == metadata['source_sha256'] and
        _clock(item.get('captured_at')) == completed for item in evidence), 'CURRENT_CARD_EVIDENCE')
    digest(metadata)  # Reject non-finite or non-JSON additions without changing them.


def _proof(original, context, model, metadata, attached_at):
    return dict(schema=SCHEMA, pin=_receipt_pin(context['receipt']), artifact_receipt=deepcopy(context['receipt']),
        training_sha256=context['training']['training_sha256'], model_sha256=model['model_sha256'],
        native_model_sha256=model['native_training']['model_sha256'],
        owner_research_record_sha256=digest(context['owner_research_record']), source_metadata=deepcopy(metadata),
        attached_at=attached_at, original_payload_sha256=digest(original), source_lineage=deepcopy(model['source_lineage']),
        owner_research_record=deepcopy(context['owner_research_record']),
        historical_source_refs=[list(pair) for pair in sorted(_sources(model))])


def attach(payload, context, *, sport, source_metadata, now):
    now = _clock(now)
    _need(type(payload) is dict and 'learned_model' not in payload and 'baseline_attachment' not in payload,
        'EXISTING_BASELINE_DO_NOT_REPLACE')
    original = deepcopy(payload); model = _selected(original, context, sport, now)
    _source(original, model, context['receipt'], source_metadata, now)
    output = deepcopy(original); output['learned_model'] = deepcopy(model['native_training'])
    output['baseline_attachment'] = _proof(original, context, model, source_metadata, now.isoformat())
    return output


def verify_attachment(payload, context, *, sport, now, generated_at=None):
    now = _clock(now)
    _need(type(payload) is dict and type(payload.get('learned_model')) is dict and
        type(payload.get('baseline_attachment')) is dict, 'ATTACHMENT_REQUIRED')
    proof = payload['baseline_attachment']
    _need(set(proof) == PROOF_FIELDS and proof.get('schema') == SCHEMA and
        type(proof.get('attached_at')) is str, 'ATTACHMENT_SCHEMA')
    attached = _clock(proof.get('attached_at'))
    _need(attached <= now and (generated_at is None or attached <= _clock(generated_at) <= now), 'ATTACHMENT_CLOCK')
    original = deepcopy(payload); del original['learned_model']; del original['baseline_attachment']
    model = _selected(original, context, sport, now)
    _source(original, model, context['receipt'], proof['source_metadata'], attached)
    _need(payload['learned_model'] == model['native_training'] and
        proof == _proof(original, context, model, proof['source_metadata'], proof['attached_at']), 'ATTACHMENT_BINDING')
    return True
