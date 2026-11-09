"""Source-free reconciliation of *existing* result-receipt mismatches.

Only re-project an authenticated, already-retained result page whose saved
forecast and official proof then pass every formal check. No HTTP/provider
request, no editing forecast/real source, no reference-only promotion.
"""
from collections import defaultdict
import re
from copy import deepcopy
from . import result_due_ledger as D, result_due_case_audit as C
from . import saved_view_feed as F, retained_model_pdca_audit as P
from .racer_daily import clock,sha,wire,need

MAX_RACES=12


def repair_saved_receipt_mismatches(repo,*,state,now,bridge=None):
    """Publish only proven formal corrections, reject all other reconstructions."""
    from .racer_result_bridge import SavedResultBridge
    now=clock(now)
    before=wire(state.control)
    due=D.ledger(deepcopy(state.control),now=now.isoformat())
    C.summary(state.control,due)  # Check individual AES case IDs against all due bits.
    cases=C._validate(state.control['result_due_case_reasons'])['cases']
    pointers=state.control.get('settlement_captures') or {}
    need(type(pointers) is dict,'MODEL_REPLAY_POINTER_MAP_INVALID')
    # Both states already have an immutable retained capture. Re-run only the
    # existing strict parser and formal-eligibility gates, never trust a rejected
    # result just because its source bytes match their original SHA.
    # Reference-only labels remain excluded: they have no admissible proof.
    replayable={'MODEL_RESULT_EVIDENCE_MISMATCH','RESULT_SOURCE_REJECTED'}
    candidates=[rid for rid,entry in sorted(cases.items()) if
        entry['reason'] in replayable and rid in pointers][:MAX_RACES]
    report=dict(schema='RACE_AI_OFFLINE_MODEL_RECEIPT_REPAIR_V1',
        replay_candidates=len(candidates),source_bytes_authenticated=0,
        formal_result_repairs=0,formal_preview_holds=0,unavailable_saved_day=0,
        view_commits=0,formal_hold_reason_counts={},parser_conflict_field_counts={},metadata_only_reprojections=0,
        source_provider_requests=0,forecast_rewrites=0,
        public_originals_changed=False,actual_purchases=False)
    def add_hold(reason):
        # Whitelisted static reason codes only. Never echo an exception body,
        # exact race ID, URL, source content, forecast ticket, or owner key.
        code=reason if type(reason) is str and re.fullmatch(
            r'(?:RESULT|FEED|HISTORY|MODEL_REPLAY|RETAINED_MODEL_PDCA|INTRADAY)_[A-Z0-9_]{2,99}',reason) else 'MODEL_REPLAY_OTHER_HOLD'
        reasons=report['formal_hold_reason_counts']
        reasons[code]=reasons.get(code,0)+1
        report['formal_preview_holds']+=1
    if not candidates:return report
    bridge=bridge or SavedResultBridge(repo,now=now)
    available=set(bridge.available_days)
    old=sorted({D._rid_day(rid) for rid in candidates if D._rid_day(rid) not in bridge.recent_days})
    allowed=set(bridge.recent_days)|set(old[:1])
    byday=defaultdict(list)
    for rid in candidates:
        day=D._rid_day(rid)
        if day in available and day in allowed:byday[day].append(rid)
        else:report['unavailable_saved_day']+=1
    for day,ids in sorted(byday.items()):
        args=dict(day=day) if bridge.history else {}
        parent,previous,generation,current=F.current_view(bridge.git,bridge.bootstrap,**args)
        pin=F.originals_sha(current)
        accepted=[]
        for rid in ids:
            matches=[r for r in current['records'] if r.get('race_id')==rid and r.get('sport')=='boat']
            if len(matches)!=1:
                add_hold('MODEL_REPLAY_RACE_IDENTITY_INVALID');continue
            # A stale rejection index must never erase a prior explicit
            # reference-only / non-formal decision during offline replay.
            prior_result=matches[0].get('result') or {}
            prior_ref=prior_result.get('cutoff_reconciliation') or {}
            if (prior_result.get('cutoff_reference') is not None or
                prior_result.get('formal_eligible') is False or
                (isinstance(prior_ref,dict) and prior_ref.get('formal_eligible') is False)):
                add_hold('MODEL_REPLAY_REFERENCE_ONLY_BARRIER');continue
            try:
                if P._result_context(matches[0])[0] in ('FINAL','VOID'):
                    # Never re-publish an already proved formal result.
                    add_hold('MODEL_REPLAY_ALREADY_FORMAL');continue
            except (ValueError,TypeError,KeyError):
                pass
            try:
                raw,receipt=state.capture(pointers[rid])
                need(sha(raw)==receipt.get('source_sha256'),'MODEL_REPLAY_SOURCE_SHA_CHANGED')
                report['source_bytes_authenticated']+=1
                try:
                    revised=F.update_view(current,[],captures=[(raw,receipt)],
                                          synced_at=now.isoformat())
                except ValueError as parser_conflict:
                    if str(parser_conflict)!='RESULT_CAPTURE_CONFLICT':raise
                    # Preserve the original observation at its real source
                    # clock. An identical authenticated settlement can be
                    # reprojected when ONLY non-material parser metadata differs.
                    # Conflicting winners/payouts/identity/cutoff remain HOLD.
                    from .result_observation_conflict_diagnostics import result_conflict_counts
                    parsed=F.parse_capture(raw,receipt)
                    found=[o for o in current['records'] if o.get('race_id')==rid]
                    need(len(found)==1,'MODEL_REPLAY_RACE_IDENTITY_INVALID')
                    matching_observations=[o for o in found[0].get('result_observations',[]) if
                        o.get('source_sha256')==receipt['source_sha256'] and
                        o.get('captured_at')==receipt['captured_at'] and
                        o.get('source_url')==receipt['source_url']]
                    need(len(matching_observations)==1,'MODEL_REPLAY_PARSER_SOURCE_RECEIPT_MISMATCH')
                    old_observation=matching_observations[0]
                    differences=result_conflict_counts(old_observation,parsed)
                    for field,count in differences['differing_fields'].items():
                        report['parser_conflict_field_counts'][field]=report['parser_conflict_field_counts'].get(field,0)+count
                    immutable_fields=('race_id','captured_at','closed_at','source_sha256',
                        'source_url','body_identity_verified','status','schedule_binding')
                    compatible=(all(old_observation.get(field)==parsed.get(field)
                        for field in immutable_fields) and
                        old_observation.get('body_identity_verified') is True and
                        wire(old_observation.get('data'))==wire(parsed.get('data')))
                    need(compatible,'MODEL_REPLAY_PARSER_MATERIAL_CONFLICT')
                    revised=F.update_view(current,[old_observation],captures=[],
                                          synced_at=now.isoformat())
                    report['metadata_only_reprojections']+=1
                original=[r for r in revised['records'] if r.get('race_id')==rid]
                need(len(original)==1,'MODEL_REPLAY_RACE_IDENTITY_INVALID')
                row=original[0]
                outcome=P._result_context(row)[0]
                need(outcome in ('FINAL','VOID'),'MODEL_REPLAY_'+outcome)
                forecasts=([row['prediction']] if row.get('prediction') is not None else []
                    )+list(row.get('comparison_predictions') or [])
                need(bool(forecasts),'MODEL_REPLAY_NO_SAVED_PREDICTION')
                for forecast in forecasts:P._saved_clock(forecast,row)
                need(F.originals_sha(revised)==pin,'MODEL_REPLAY_ORIGINAL_FORECAST_CHANGED')
            except (ValueError,TypeError,KeyError,IndexError) as error:
                add_hold(str(error) if type(error) is ValueError else 'MODEL_REPLAY_OTHER_HOLD')
                continue
            current=revised;accepted.append(rid)
        if not accepted:continue
        need(F.originals_sha(current)==pin,'MODEL_REPLAY_ORIGINAL_FORECAST_CHANGED')
        F.publish_view(bridge.git,bridge.bootstrap,current,
                       parent=parent,previous=previous,generation=generation)
        _,_,_,restored=F.current_view(bridge.git,bridge.bootstrap,**args)
        need(F.originals_sha(restored)==pin,'MODEL_REPLAY_ORIGINAL_READBACK_CHANGED')
        for rid in accepted:
            matches=[r for r in restored['records'] if r.get('race_id')==rid]
            need(len(matches)==1 and P._result_context(matches[0])[0] in ('FINAL','VOID'),
                 'MODEL_REPLAY_INDEPENDENT_RESULT_READBACK_FAILED')
        report['view_commits']+=1
        report['formal_result_repairs']+=len(accepted)
    need(wire(state.control)==before,'MODEL_REPLAY_INTRADAY_ORIGINAL_CHANGED')
    return report
