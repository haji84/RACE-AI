"""Opt-in v2 admission for the three actual research entrants.

This is a contract adapter, not a source, key, storage, or forecast authority.
It never creates rivals, alters their prediction clocks, selects an integrated
recipe, or authenticates self-declared hashes. ``checked_contract`` requires an
externally retained canonical JSON SHA and an explicit expected integration
recipe. The A/B-each-50% entrant and the legacy research ensemble have separate
native IDs. Each contest accepts one integrated entrant.

``admit_original`` requires the same immutable input snapshot and source as-of
for all entrants, while retaining each original's actual generation, seal, and
independent readback times. Every time must precede cutoff by at least 15 minutes
where applicable. A caller-supplied callable must invoke the EXISTING trusted
model/source/original verifier. Its return must bind the exact reverify payload
and explicitly confirm all three checks. A synthetic callback is only a test.

Registry additions are input_snapshot_sha256 (the preserved common material
manifest bytes) and input_frozen_at (its independently witnessed freeze time).
Existing input/history/dataset/context digests still bind that material. A
receipt is a declaration until the external verifier rereads its artifact and
source evidence. Official result/payout admission remains the existing scorer's
separate responsibility; this module never declares a winner or promotion.
"""
from copy import deepcopy
from datetime import timedelta
import math
import re

from .policy import (checked_sha, clock, digest, finite_number, require,
                     shared_evidence_digest)


CONTRACT_SCHEMA = 'dt-r1-prospective-contest-v2'
ORIGINAL_SCHEMA = 'dt-r1-prospective-original-v2'
REVERIFY_SCHEMA = 'dt-r1-prospective-reverify-v2'
AB_EQUAL_MODEL_ID = 'official-ab-equal-weight-v1'
PARTICIPANTS = {
    AB_EQUAL_MODEL_ID: 'existing-integrated',
    'official-and-research-ensemble-v1': 'existing-integrated',
    'keirin-conditional-order-trees-v1': 'codex-independent',
    'chatgpt-dt-r1': 'chatgpt-dt-r1',
}
INTEGRATED_MODELS = {model_id for model_id, role in PARTICIPANTS.items()
                     if role == 'existing-integrated'}
REQUIRED_MODELS = PARTICIPANTS.keys() - INTEGRATED_MODELS
MARGIN = timedelta(minutes=15)
PIN_FIELDS = ('model_sha256', 'policy_sha256', 'feature_schema_sha256')


def _need(ok, code):
    require(ok, 'PROSPECTIVE_V2_' + code)


def _recipe(value):
    _need(isinstance(value, dict) and set(value) == {
        'current_arm_weights', 'research_weight', 'research_allocation'}, 'INTEGRATION_RECIPE_REQUIRED')
    arms = value['current_arm_weights']
    _need(isinstance(arms, dict) and set(arms) == {'A', 'B'}, 'INTEGRATION_ARMS_REQUIRED')
    weights = tuple(finite_number(weight) for weight in (arms['A'], arms['B'], value['research_weight']))
    allocation = value['research_allocation']
    if allocation == 'none':
        valid = weights == (.5, .5, 0.)
    else:
        valid = (allocation == 'equal_available_families_equal_members' and
                 all(0 <= w <= 1 for w in weights) and abs(math.fsum(weights) - 1) <= 1e-12 and
                 weights[0] == weights[1])
    _need(valid, 'INTEGRATION_RECIPE_INVALID')
    return value


def checked_contract(contract, expected_sha256, model_ids):
    """Return pinned identities; malformed or unresolved contracts raise HOLD reasons.

    This check is structural. The externally supplied verifier must still open
    the pinned artifacts and check their native manifests and code identity.
    """
    _need(isinstance(contract, dict) and set(contract) == {
        'schema', 'frozen_at', 'participants', 'expected_integration_recipe'} and
        contract['schema'] == CONTRACT_SCHEMA, 'CONTRACT_REQUIRED')
    checked_sha(expected_sha256, 'PROSPECTIVE_V2_EXTERNAL_CONTRACT_SHA_REQUIRED')
    _need(digest(contract) == expected_sha256, 'EXTERNAL_CONTRACT_SHA_MISMATCH')
    clock(contract['frozen_at'])
    participants = contract['participants']
    _need(isinstance(participants, dict), 'EXACT_PARTICIPANT_IDENTITIES_REQUIRED')
    integrated_ids = participants.keys() & INTEGRATED_MODELS
    _need(len(integrated_ids) == 1 and participants.keys() - integrated_ids == REQUIRED_MODELS and
          participants.keys() == set(model_ids), 'EXACT_PARTICIPANT_IDENTITIES_REQUIRED')
    for model_id, entry in participants.items():
        role = PARTICIPANTS[model_id]
        fields = {'role', 'model_sha256', 'policy_sha256', 'feature_schema_sha256', 'artifact_sha256', 'code_commit'}
        if role == 'existing-integrated':
            fields.add('integration_recipe')
        _need(isinstance(entry, dict) and set(entry) == fields and entry['role'] == role, 'PARTICIPANT_MANIFEST_REQUIRED')
        for key in (*PIN_FIELDS, 'artifact_sha256'):
            checked_sha(entry[key], 'PROSPECTIVE_V2_PARTICIPANT_SHA_REQUIRED')
        _need(isinstance(entry['code_commit'], str) and re.fullmatch('[0-9a-f]{40}', entry['code_commit']) is not None,
              'PARTICIPANT_CODE_COMMIT_REQUIRED')
    integrated_id, = integrated_ids
    actual = _recipe(participants[integrated_id]['integration_recipe'])
    if integrated_id == AB_EQUAL_MODEL_ID:
        _need(actual['research_allocation'] == 'none', 'EXISTING_INTEGRATED_RECIPE_INVALID')
    else:
        _need(0 < actual['research_weight'] < 1, 'EXISTING_INTEGRATED_RECIPE_INVALID')
    _need(contract['expected_integration_recipe'] is not None, 'INTEGRATED_RECIPE_UNRESOLVED')
    expected = _recipe(contract['expected_integration_recipe'])
    _need(digest(actual) == digest(expected), 'INTEGRATED_RECIPE_MISMATCH')
    _need(len({entry['model_sha256'] for entry in participants.values()}) == 3,
          'DISTINCT_MODEL_MANIFESTS_REQUIRED')
    return {model_id: {key: entry[key] for key in PIN_FIELDS} for model_id, entry in participants.items()}


def admit_original(forecast, registered, receipt, *, contract, contract_sha256, verifier):
    """Reverify one original without requiring a missing rival or changing bytes.

    The verifier receives the exact contract, registry, original forecast, and
    receipt in a defensive copy. Its payload hash must match the pre-call value.
    Mutating that copy cannot change the comparison's original objects.
    """
    _need(callable(verifier), 'INDEPENDENT_VERIFIER_REQUIRED')
    _need(isinstance(receipt, dict) and receipt.get('schema') == ORIGINAL_SCHEMA, 'ORIGINAL_RECEIPT_REQUIRED')
    _need(forecast.get('cohort') == registered.get('cohort') == 'prospective', 'PROSPECTIVE_COHORT_REQUIRED')
    _need(receipt.get('contract_sha256') == contract_sha256 and
          receipt.get('registry_sha256') == digest(registered), 'CONTRACT_OR_REGISTRY_MISMATCH')
    for key in ('race_id', 'day', 'model_id', 'model_sha256', 'input_sha256'):
        _need(receipt.get(key) == forecast.get(key), 'FORECAST_IDENTITY_MISMATCH')
    for key in ('race_id', 'day', 'input_sha256'):
        _need(receipt.get(key) == registered.get(key), 'SOURCE_IDENTITY_MISMATCH')
    checked_sha(registered.get('input_snapshot_sha256'), 'PROSPECTIVE_V2_INPUT_SNAPSHOT_REQUIRED')
    _need(receipt.get('input_snapshot_sha256') == registered['input_snapshot_sha256'], 'INPUT_SNAPSHOT_MISMATCH')
    shared = shared_evidence_digest(registered)
    _need(receipt.get('shared_evidence_sha256') == forecast.get('shared_evidence_sha256') == shared,
          'SHARED_EVIDENCE_MISMATCH')
    _need(receipt.get('forecast_sha256') == digest(forecast), 'FORECAST_DIGEST_MISMATCH')
    pin = contract['participants'][forecast['model_id']]
    _need(forecast['model_sha256'] == pin['model_sha256'] and
          forecast.get('feature_schema_sha256') == pin['feature_schema_sha256'], 'MODEL_MANIFEST_MISMATCH')
    checked_sha(forecast.get('feature_input_sha256'), 'PROSPECTIVE_V2_FEATURE_INPUT_REQUIRED')
    selection = forecast.get('selection')
    _need(isinstance(selection, dict) and selection.get('policy_sha256') == pin['policy_sha256'] and
          selection.get('selection_sha256') == digest({k: v for k, v in selection.items() if k != 'selection_sha256'}),
          'POLICY_OR_SELECTION_MISMATCH')
    for key in ('race_id', 'day', 'model_id', 'model_sha256', 'input_sha256', 'cohort', 'prediction_at', 'cutoff_at'):
        _need(selection.get(key) == forecast.get(key), 'SELECTION_ORIGINAL_BINDING_MISMATCH')
    for key in ('original_cipher_sha256', 'source_receipt_sha256', 'readback_receipt_sha256'):
        checked_sha(receipt.get(key), 'PROSPECTIVE_V2_ORIGINAL_EVIDENCE_SHA_REQUIRED')
    as_of, frozen, generated, sealed, readback, cutoff = (clock(receipt.get(key)) for key in (
        'input_as_of', 'input_frozen_at', 'generated_at', 'sealed_at', 'readback_at', 'cutoff_at'))
    _need(as_of == clock(registered['context_as_of']) and
          frozen == clock(registered.get('input_frozen_at')) and generated == clock(forecast['prediction_at']) and
          cutoff == clock(forecast['cutoff_at']) == clock(registered['cutoff_at']), 'ORIGINAL_CLOCK_BINDING')
    _need(clock(contract['frozen_at']) <= frozen and as_of <= frozen <= generated <= sealed <= readback <= cutoff - MARGIN,
          'ORIGINAL_CLOCK_ORDER')
    if forecast.get('context_as_of') is not None:
        _need(clock(forecast['context_as_of']) == as_of, 'FORECAST_CONTEXT_CLOCK_MISMATCH')
    payload = deepcopy({'schema': REVERIFY_SCHEMA, 'contract': contract, 'registry': registered,
                        'forecast': forecast, 'receipt': receipt})
    payload_sha = digest(payload)
    try:
        verified = verifier(payload)
    except Exception:
        _need(False, 'EXTERNAL_REVERIFICATION_FAILED')
    _need(isinstance(verified, dict) and all(verified.get(key) is True for key in (
        'verified', 'independent', 'model_manifest_verified', 'input_snapshot_verified', 'original_readback_verified')) and
        isinstance(verified.get('verifier'), str) and bool(verified['verifier'].strip()) and
        verified.get('payload_sha256') == payload_sha, 'EXTERNAL_REVERIFICATION_FAILED')
    checked_sha(verified.get('receipt_sha256'), 'PROSPECTIVE_V2_EXTERNAL_REVERIFICATION_FAILED')
    return {'contract_sha256': contract_sha256, 'input_snapshot_sha256': registered['input_snapshot_sha256'],
            'input_frozen_at': receipt['input_frozen_at'], 'generated_at': receipt['generated_at'],
            'sealed_at': receipt['sealed_at'], 'readback_at': receipt['readback_at'],
            'verification_receipt_sha256': verified['receipt_sha256']}
