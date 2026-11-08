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
    candidates=[rid for rid,entry in sorted(cases.items()) if
        entry['reason']=='MODEL_RESULT_EVIDENCE_MISMATCH' and rid in pointers][:MAX_RACES]
    report=dict(schema='RACE_AI_OFFLINE_MODEL_RECEIPT_REPAIR_V1',
        replay_candidates=len(candidates),source_bytes_authenticated=0,
        formal_result_repairs=0,formal_preview_holds=0,unavailable_saved_day=0,
        view_commits=0,formal_hold_reason_counts={},source_provider_requests=0,forecast_rewrites=0,
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
                revised=F.update_view(current,[],captures=[(raw,receipt)],
                                      synced_at=now.isoformat())
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
