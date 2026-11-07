"""Verify consistency of national full-day evidence, not provider authenticity.

The trusted ingestion side must authenticate and retain the actual schedule, clock,
provider, private storage, scheduler, scoring and D+1 receipts. A string containing
one of their digests is not an independent witness. This module does not start a
collector, make network requests, retrain models or indicate validated accuracy.
"""
from datetime import date, datetime, timedelta, timezone
import re

JST = timezone(timedelta(hours=9))
MODELS = {'A':'boat-display-rating-PL-reference-v1-UNVALIDATED','B':'boat-course-motor-shadow-v0.1-UNTRAINED','K_TACTICAL':'boat-course-entry-method-scenarios-v0.1-UNTRAINED'}
FINAL = {'SETTLED','REFUNDED','CANCELLED','NO_TRIFECTA','OFFICIAL_SPECIAL'}
MISSES = {'EXHIBITION_INCOMPLETE','SOURCE_UNAVAILABLE','PROVIDER_BACKOFF','TIME_BUDGET','STORAGE_FAILED','RECEIPT_LATE','CLOCK_OR_ID_CONFLICT','NO_TRIFECTA','CANCELLED','WITHDRAWN','K_HISTORY_MISSING','AUTOMATIC_RECOVERY'}

def ts(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.utcoffset() is None: raise ValueError('missing timezone')
    return t

def digest(value):
    return isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) is not None

def assess(manifest):
    """Five minutes limits the gap between internal heartbeats, not upstream requests."""
    d=manifest; defects=set(); kdefects=set(); ab_count=k_count=normal=normal_ab=0
    def check(ok,reason):
        if not ok: defects.add(reason)
    try:
        day=date.fromisoformat(d['date']); start,stop=ts(d['start']),ts(d['stop']); first=ts(d['first_exhibition'])
        venues,schedule,rows=d['venues'],d['schedule'],d['rows']; ids={r['id'] for r in rows}
        expected={f'{day:%Y%m%d}-{v}-{i:02}' for v in venues for i in range(1,13)}
        check(bool(venues) and len(venues)==len(set(venues)) and all(re.fullmatch('0[1-9]|1[0-9]|2[0-4]',v) for v in venues) and ids==expected==set(schedule) and len(rows)==len(ids) and digest(d['schedule_receipt']),'NATIONAL_REGISTRY')
        check(day==first.astimezone(JST).date() and start<=first<=stop and digest(d['first_exhibition_receipt']),'FIRST_EXHIBITION_NOT_COVERED')
        check(d['trigger']=='AUTOMATIC' and type(d['manual_restarts']) is int and d['manual_restarts']==0 and digest(d['trace_receipt']),'OPERATOR_OR_TRACE')
        beats=[ts(v) for v in d['heartbeats']]; timeline=[start,*beats,stop]
        check(bool(beats) and all(0<=(b-a).total_seconds()<=300 for a,b in zip(timeline,timeline[1:])),'HEARTBEAT_GAP')
        for r in rows:
            rid=r['id']; close=ts(schedule[rid]); result=r['result']; state=result['state']; settled=ts(result['at'])
            check(close.astimezone(JST).date()==day and result.get('race_id')==rid and state in FINAL and digest(result['sha']) and start<=settled<=stop and (state in {'CANCELLED','NO_TRIFECTA'} or close<=settled),'NONFINAL_OR_OUTSIDE_TRACE:'+rid)
            normal+=state=='SETTLED'; ab=r['ab']; roles=[f['model'] for f in ab]
            def valid(f,role):
                return (f.get('race_id')==rid and f.get('model')==role and f.get('version')==MODELS[role] and all(digest(f.get(k)) for k in ('observation','sha','receipt')) and f['observation']==r.get('exhibition_sha') and first<=ts(r['exhibition_at'])<=ts(f['generated'])<=ts(f['saved'])<close and ts(f['saved'])<=stop)
            def explained(reason):
                return reason in MISSES and any(a['reason']==reason and digest(a['receipt']) and start<=ts(a['at'])<=min(close,stop) for a in r['attempts'])
            ok=(roles==['A','B'] and all(valid(f,role) for f,role in zip(ab,('A','B'))) and ab[0]['sha']!=ab[1]['sha'] and ab[0]['observation']==ab[1]['observation'])
            if ok:
                ab_count+=1; normal_ab+=state=='SETTLED'
            elif ab or not ((state in {'CANCELLED','NO_TRIFECTA'} and digest(result['sha'])) or explained(r.get('reason'))):
                defects.add('UNEXPLAINED_OR_INVALID_AB:'+rid)
            k=r.get('k')
            if k is not None:
                eligible=(ok and valid(k,'K_TACTICAL') and k['sha'] not in {f['sha'] for f in ab} and k['observation']==ab[0]['observation'] and digest(k['history']) and date.fromisoformat(k['last_k_day'])<day and ts(k['history_captured'])<=ts(k['generated']))
                if not eligible: kdefects.add('K_VERSION_SOURCE_OR_CLOCK:'+rid)
                elif state=='SETTLED':
                    comparison=k.get('comparison',{})
                    refs={'A':ab[0]['sha'],'B':ab[1]['sha'],'K':k['sha'],'result':result['sha']}
                    if all(comparison.get(key)==value for key,value in refs.items()) and digest(comparison.get('receipt')): k_count+=1
                    else: kdefects.add('K_COMPARISON_UNVERIFIED:'+rid)
            elif ok and state=='SETTLED' and not explained(r.get('k_reason')):
                kdefects.add('K_MISSING_WITHOUT_REASON:'+rid)
        check(ab_count>0,'NO_AB_FORECAST')
        rp=d.get('replay') or {}; clock=ts(rp['ran_at']) if rp else None
        replay_ok=bool(clock and clock.astimezone(JST).date()==day+timedelta(days=1) and stop<clock and rp.get('owner_only') is True and digest(rp.get('receipt')) and digest(rp.get('private_readback_sha')) and rp['private_readback_sha']==rp.get('archive_sha') and digest(d['close_sha']) and rp.get('report_sha')==d['close_sha'])
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        defects.add('MISSING_OR_INVALID_EVIDENCE_STRUCTURE'); replay_ok=False
    if not k_count: kdefects.add('NO_MATCHED_SETTLED_K_PAIR')
    return {'status':'INCOMPLETE' if defects or kdefects or not replay_ok else 'EVIDENCE_CONSISTENT','operations_ok':not defects,'next_day_ok':replay_ok,'k_comparison_ok':not kdefects,'all_normal_forecasted':normal>0 and normal_ab==normal and not defects,'normal_AB':normal_ab,'normal_total':normal,'matched_K':k_count,'operation_defects':sorted(defects),'k_defects':sorted(kdefects),'external_authentication_required':True}
