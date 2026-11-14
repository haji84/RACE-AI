"""Fail-closed legal-source admission before optional exhibition-video research.

Research only. A public FAQ, an asserted license, or a self-declared SHA cannot
prove a permitted automated download/ML use. The caller must independently
retrieve and verify the actual applicable authorization via verify_grant.
This pure gate never fetches video, modifies forecast originals, or authorizes
publication. It is not a substitute for legal review.
"""
from datetime import datetime, timedelta
from .actions_contract import digest
from .boat_national_video_research_gate import instant, _RACE, _SHA

SCHEMA = 'RACE_AI_BOAT_PRIVATE_VIDEO_RIGHTS_V1'
USES = frozenset(('PRIVATE_COPY','AUTOMATED_FRAME_ANALYSIS','RESEARCH_FORECAST_DERIVATION'))
CANDIDATE_FIELDS = frozenset(('race_id','cutoff_at','captured_at','media_sha256','source_kind'))
GRANT_FIELDS = frozenset(('schema','race_id','video_sha256','grant_evidence_sha256','rights_source',
                          'permitted_uses','begins_at','expires_at','restrictions_verified_at',
                          'public_distribution_permitted'))

def _hold(state, candidate):
    return dict(schema='RACE_AI_BOAT_VIDEO_RIGHTS_ADMISSION_V1',
                state=state, race_id=candidate.get('race_id') if type(candidate) is dict else None,
                source_fetch_performed=False, production_video_forecast_proven=False,
                publication_approved=False, source_authorization_independently_claimed=False)

def review(candidate,grant,*,now,verify_grant=None):
    """Admission request does no I/O. Missing/contradictory proofs always HOLD."""
    if type(candidate) is not dict or set(candidate)!=CANDIDATE_FIELDS or not isinstance(now,datetime) or now.utcoffset() is None:
        return _hold('HOLD_VIDEO_SOURCE_INPUT_INVALID',candidate)
    rid = candidate.get('race_id')
    try:
        if (type(rid) is not str or _RACE.fullmatch(rid) is None or
                candidate['source_kind'] not in ('OWNER_RECORDED','RIGHTS_HOLDER_SUPPLIED') or
                type(candidate['media_sha256']) is not str or
                _SHA.fullmatch(candidate['media_sha256']) is None):
            return _hold('HOLD_VIDEO_SOURCE_INPUT_INVALID',candidate)
        captured,cutoff=instant(candidate['captured_at']),instant(candidate['cutoff_at'])
        if captured>=cutoff or captured<cutoff-timedelta(days=2):
            return _hold('HOLD_PRE_CUTOFF_VIDEO_SOURCE_REQUIRED',candidate)
        if now>=cutoff:
            return _hold('HOLD_PRE_CUTOFF_WINDOW_CLOSED',candidate)
        if captured>now:
            return _hold('HOLD_PRE_CUTOFF_VIDEO_SOURCE_REQUIRED',candidate)
        if (type(grant) is not dict or set(grant)!=GRANT_FIELDS or grant.get('schema')!=SCHEMA or
                grant.get('rights_source')!='RIGHTS_HOLDER_WRITTEN_GRANT'):
            return _hold('HOLD_EXPLICIT_RIGHTS_SCOPE_REQUIRED',candidate)
        if (grant['race_id']!=rid or grant['video_sha256']!=candidate['media_sha256'] or
                type(grant['grant_evidence_sha256']) is not str or
                _SHA.fullmatch(grant['grant_evidence_sha256']) is None or
                grant['public_distribution_permitted'] is not False or
                type(grant['permitted_uses']) is not list or
                len(grant['permitted_uses'])!=len(set(grant['permitted_uses'])) or
                not USES.issubset(set(grant['permitted_uses']))):
            return _hold('HOLD_EXPLICIT_RIGHTS_SCOPE_REQUIRED',candidate)
        if not (instant(grant['begins_at'])<=captured and
                instant(grant['restrictions_verified_at'])<=now and
                now<instant(grant['expires_at'])):
            return _hold('HOLD_GRANT_NOT_VALID_AT_ANALYSIS',candidate)
        if not callable(verify_grant):
            return _hold('HOLD_INDEPENDENT_RIGHTS_RECEIPT_REQUIRED',candidate)
        # The caller's verifier must independently validate actual stored
        # permission, venue/scope binding and terms. This gate does not certify
        # legal clearance, media authenticity, or production readiness.
        receipt=verify_grant(grant,candidate)
        if (type(receipt) is not dict or
                receipt.get('state')!='INDEPENDENT_RIGHTS_RECEIPT_VERIFIED' or
                receipt.get('manifest_sha256')!=digest(grant) or
                receipt.get('evidence_sha256')!=grant['grant_evidence_sha256'] or
                instant(receipt['verified_at'])>now):
            return _hold('HOLD_RIGHTS_RECEIPT_INVALID_OR_LATE',candidate)
        result=_hold('READY_PRIVATE_RESEARCH_INPUT_ONLY',candidate)
        result.update(video_sha256=candidate['media_sha256'],grant_sha256=digest(grant),
                      source_authorization_independently_claimed=True)
        return result
    except (KeyError,ValueError,TypeError,OverflowError,AssertionError,AttributeError):
        return _hold('HOLD_RIGHTS_RECEIPT_INVALID_OR_LATE',candidate)



def enqueue_licensed_capture(private_root, export_record, template, grant, *, now, verify_grant=None):
    """Opt-in rights-gated bridge to the existing verified private intake.

    This function does not capture remote media, accept a public license claim,
    publish video, certify identity or create a race forecast. The existing
    enqueue_export path separately verifies the saved capture's actual bytes.
    """
    hold=dict(status='HOLD_CAPTURE_SOURCE_NOT_OWNER_BOUND',source_fetch_performed=False,
              production_video_forecast_proven=False,source_authorization_independently_claimed=False)
    if (type(export_record) is not dict or export_record.get('source_role')!='OWNER_AUTHORIZED'
            or type(template) is not dict or not all(k in template for k in ('race_id','cutoff_at'))
            or type(export_record.get('media_sha256')) is not str or
            type(export_record.get('captured_at')) is not str):
        return hold
    source=dict(race_id=template['race_id'],cutoff_at=template['cutoff_at'],
                captured_at=export_record['captured_at'],media_sha256=export_record['media_sha256'],
                source_kind='OWNER_RECORDED')
    decision=review(source,grant,now=now,verify_grant=verify_grant)
    if decision['state']!='READY_PRIVATE_RESEARCH_INPUT_ONLY':
        return dict(status=decision['state'],source_fetch_performed=False,
                    production_video_forecast_proven=False,
                    source_authorization_independently_claimed=False)
    from .boat_video_capture_bridge import enqueue_export
    try:
        receipt=enqueue_export(private_root,export_record,template)
        if (type(receipt) is not dict or receipt.get('status')!='ENQUEUED_UNVALIDATED' or
                receipt.get('media_sha256')!=source['media_sha256']):
            raise ValueError('CAPTURE_NOT_VERIFIED_FOR_PRIVATE_RESEARCH')
    except (OSError,ValueError,TypeError,KeyError):
        return dict(status='HOLD_VERIFIED_CAPTURE_UNAVAILABLE',source_fetch_performed=False,
                    production_video_forecast_proven=False,
                    source_authorization_independently_claimed=False)
    return dict(status='ENQUEUED_UNVALIDATED',source_fetch_performed=False,
                production_video_forecast_proven=False,source_authorization_independently_claimed=True,
                media_sha256=receipt['media_sha256'],job_sha256=receipt['job_sha256'])
