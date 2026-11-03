"""Single-shot owner boundary connecting KEIRIN results to future forecast.

No built-in HTTP, API secrets, recurrent schedule, model implementation or
provider authorization. Explicit owner callbacks must independently validate
the original source bytes, rights, race results, pre-cutoff snapshots and
private create-once forecast storage. This orchestrator is NOT itself proof of
a rightsholder grant, remote timestamp, or formal Hit@8.
"""
from __future__ import annotations

from hashlib import sha256
from .keirin_result_delivery import build_research_batch, utc
from .evaluation_result_revision_bridge import link_result_revisions
from .keirin_result_reactor import react_to_result_delivery
from .keirin_next_forecast_worker import consume_next_intent

REQUIRED = frozenset((
    'clock', 'attest_raw_result_feed', 'authenticate_result',
    'verify_next', 'frozen_readback', 'enqueue_once', 'enqueue_readback',
    'read_queued_intent', 'read_snapshot', 'attest_source',
    'frozen_status', 'model_forecast', 'atomic_freeze',
    'freeze_readback', 'independent_receipt_check',
))


class OneCycleError(ValueError):
    pass


def execute_one_owner_cycle(*, bridge, raw_feed, admission,
                            forecast_reference, future_races,
                            callbacks, previous_batches=()):
    """Attempt one bounded result -> audit -> outbox -> forecast operation.

    Return non-sensitive summary only. Neither provider rights nor true
    external timestamp authority may be inferred from a successful callback.
    Forecast is blocked unless source bytes are independently admitted first.
    """
    if type(callbacks) is not dict or set(callbacks) != REQUIRED or any(
            not callable(cb) for cb in callbacks.values()):
        raise OneCycleError('OWNER_PRIVATE_CALLBACKS_INCOMPLETE')
    if type(raw_feed) is not bytes or not (0 < len(raw_feed) <= 4*1024*1024):
        raise OneCycleError('INVALID_SUPPLIED_SOURCE_BYTES')
    at = callbacks['clock']()
    utc(at)
    digest = sha256(raw_feed).hexdigest()
    # An owner-signed authenticated source verifier MUST live outside the
    # public repo and must bind provider, bytes, grant and exact purpose.
    try:
        cert = callbacks['attest_raw_result_feed'](digest, admission)
    except Exception:
        cert = None
    allowed = (type(cert) is dict and set(cert) ==
        {'source_sha256','rights_ref','verified_purposes'} and
        cert['source_sha256'] == digest and
        type(admission) is dict and cert['rights_ref'] == admission.get('rights_ref') and
        type(cert['verified_purposes']) is list and
        len(set(cert['verified_purposes'])) == len(cert['verified_purposes']) and
        {'result_collection','private_retention','result_analysis'} <=
            set(cert['verified_purposes']))
    if not allowed:
        return {'schema':'RACE_AI_KEIRIN_OWNER_CYCLE_V1',
                'state':'REAL_SOURCE_ATTESTATION_UNAVAILABLE',
                'real_e2e_verified':False,'formal_hit_at_8_all':None,
                'private_forecast_saved':False,'model_called':False}
    batch = build_research_batch(bridge, raw_feed,
            admission=admission, reviewed_at=at,
            previous_batches=previous_batches)
    revisions=link_result_revisions(bridge,[*previous_batches,batch])
    audit=react_to_result_delivery(
        batch,future_races,now=at,forecast_reference=forecast_reference,
        authenticate_result=callbacks['authenticate_result'],
        verify_next=callbacks['verify_next'],
        frozen_readback=callbacks['frozen_readback'],
        enqueue_once=callbacks['enqueue_once'],
        enqueue_readback=callbacks['enqueue_readback'],
        max_jobs=1)
    candidate=next(
        (x for x in audit['queue'] if
         x['state']=='DURABLY_QUEUED_FOR_APPROVED_MODEL'),None)
    out={'schema':'RACE_AI_KEIRIN_OWNER_CYCLE_V1',
         'as_of':at, 'research_hit8':audit['reference_hit8'],
         'revision_observations':revisions['result_observations'],
         'research_queued':audit.get('queued_count',0),
         'real_e2e_verified':False,'formal_hit_at_8_all':None,
         'private_forecast_saved':False,'model_called':False,
         'owner_rights_callbacks_not_independent_proof':True}
    if candidate is None:
        return {**out,'state':'NO_ELIGIBLE_AUTHENTICATED_FUTURE_JOB'}
    key=candidate['idempotency_key']
    intent=callbacks['read_queued_intent'](key)
    if intent is None:
        return {**out,'state':'OUTBOX_INTENT_UNAVAILABLE'}
    worker=consume_next_intent(
        intent,clock=callbacks['clock'],
        read_queued_intent=callbacks['read_queued_intent'],
        read_snapshot=callbacks['read_snapshot'],
        attest_source=callbacks['attest_source'],
        frozen_status=callbacks['frozen_status'],
        model_forecast=callbacks['model_forecast'],
        atomic_freeze=callbacks['atomic_freeze'],
        freeze_readback=callbacks['freeze_readback'],
        independent_receipt_check=callbacks['independent_receipt_check'],
    )
    return {**out,'state':worker['state'],
            'private_forecast_saved':worker['forecast_durably_saved'],
            'model_called':worker['model_called'],
            'independent_receipt_accepted_by_callback':
                worker['independent_receipt_accepted_by_callback']}
