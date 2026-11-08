"""Authenticated, all-day model PDCA history stored in the *existing* AES Git control.

Every day has append-only result revisions; only the latest authenticated revision
contributes to an all-time score. No source requests, plaintext exports or bets.
The encrypted state has a hard capacity: exceed it with an explicit HOLD, not
with eviction or silently unscored historical races.
"""
import base64
import binascii
import json
import re
import zlib
from copy import deepcopy
from .racer_daily import sha, wire
from . import saved_view_feed as F

SCHEMA='RACE_AI_MODEL_PDCA_ALL_DAYS_V1'
ENCODING='zlib-json-v1'
MAX_ENCODED=7_500_000
MAX_PLAIN=60_000_000
DAY=re.compile(r'\d{4}-\d{2}-\d{2}\Z')
SHA=re.compile(r'[a-f0-9]{64}\Z')
COUNTS=('forecasts','eligible','hits','misses','void','pending','held','stake_yen','returned_yen','refund_yen','net_yen')


def need(value, code):
    if not value:raise ValueError('MODEL_PDCA_HISTORY_'+code)


def _unwrap(control):
    need(type(control) is dict,'CONTROL_INVALID')
    header=control.get('model_pdca_all_days')
    if header is None:return {'days':{}}
    need(type(header) is dict and set(header)=={'schema','encoding','payload','raw_sha256','days','revisions'}
         and header['schema']==SCHEMA and header['encoding']==ENCODING,'HEADER_INVALID')
    b64=header['payload'];need(type(b64) is str and len(b64)<=MAX_ENCODED,'PAYLOAD_BOUND')
    try:
        compressed=base64.b64decode(b64,validate=True)
        decoder=zlib.decompressobj()
        body=decoder.decompress(compressed,MAX_PLAIN+1)
        need(len(body)<=MAX_PLAIN and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,'DECOMPRESSION_BOUND')
        value=json.loads(body)
    except (ValueError,TypeError,binascii.Error,zlib.error) as exc:
        if isinstance(exc,ValueError) and str(exc).startswith('MODEL_PDCA_HISTORY_'):raise
        raise ValueError('MODEL_PDCA_HISTORY_PAYLOAD_INVALID') from None
    need(sha(body)==header['raw_sha256'],'RAW_SHA_MISMATCH')
    need(type(value) is dict and set(value)=={'days'} and type(value['days']) is dict,'BODY_SCHEMA_INVALID')
    revisions=0
    for day, entries in value['days'].items():
        need(type(day) is str and DAY.fullmatch(day) and type(entries) is list and entries,'DAY_INVALID')
        need(all(type(e) is dict and set(e)=={'revision_sha','inventory_sha','result_evidence_sha','summary'}
                 and all(type(e[k]) is str and SHA.fullmatch(e[k]) for k in ('revision_sha','inventory_sha','result_evidence_sha'))
                 and type(e['summary']) is dict and e['summary'].get('schema')=='RACE_AI_RETAINED_MODEL_PDCA_AUDIT_V1'
                 for e in entries),'REVISION_INVALID')
        revisions+=len(entries)
    need(len(value['days'])==header['days'] and revisions==header['revisions'],'INDEX_MISMATCH')
    return value


def _wrap(value):
    raw=wire(value).encode('utf-8')
    need(len(raw)<=MAX_PLAIN,'RAW_BOUND')
    payload=base64.b64encode(zlib.compress(raw,9)).decode('ascii')
    need(len(payload)<=MAX_ENCODED,'CAPACITY_HOLD')
    return dict(schema=SCHEMA,encoding=ENCODING,payload=payload,raw_sha256=sha(raw),days=len(value['days']),
                revisions=sum(len(v) for v in value['days'].values()))


def evidence_sha(view,day):
    need(type(day) is str and DAY.fullmatch(day),'DAY_INVALID')
    rows=[r for r in view['records'] if r.get('sport')=='boat' and r['event_date_jst']==day]
    need(len(rows)==len(view['records']),'DAY_SCOPE_INVALID')
    need(len({r['race_id'] for r in rows})==len(rows),'DUPLICATE_RACE')
    receipts=[dict(race_id=r['race_id'],result=r.get('result'),revisions=r.get('result_revisions',[]),
                   observations=r.get('result_observations',[]),cutoff_refs=r.get('saved_observation_cutoff_variants',[]))
              for r in sorted(rows,key=lambda x:x['race_id'])]
    return sha(wire(receipts).encode('utf-8'))


def record(control,*,day,view,summary):
    """Append a single authenticated day revision, idempotently and atomically."""
    need(type(view) is dict and type(summary) is dict,'INPUT_INVALID')
    need(summary.get('schema')=='RACE_AI_RETAINED_MODEL_PDCA_AUDIT_V1'
         and summary.get('source')=='AES_AUTHENTICATED_SAVED_VIEW_ONLY'
         and summary.get('actual_purchases') is False,'NOT_AUTHENTICATED')
    need('_private_due_race_ids' not in summary,'PRIVATE_IDS_LEAK')
    inventory=F.inventory_sha(view)
    evidence=evidence_sha(view,day)
    revision=sha(wire(dict(day=day,inventory_sha=inventory,result_evidence_sha=evidence,summary=summary)).encode('utf-8'))
    data=_unwrap(control)
    series=data['days'].setdefault(day,[])
    if series and series[-1]['revision_sha']==revision:
        return dict(changed=False,days=len(data['days']),revisions=sum(len(s) for s in data['days'].values()))
    series.append(dict(revision_sha=revision,inventory_sha=inventory,result_evidence_sha=evidence,summary=deepcopy(summary)))
    header=_wrap(data)
    control['model_pdca_all_days']=header
    return dict(changed=True,days=header['days'],revisions=header['revisions'])


def latest(control):
    """Summarize all saved days by model/stage/version; no stale revision double count."""
    data=_unwrap(control)
    result={}
    for day,history in data['days'].items():
        summary=history[-1]['summary']
        for group in summary['model_groups']:
            key=(group['model_id'],group['stage'],group.get('version') or '',group.get('variant') or '')
            if key not in result:
                result[key]=dict(model_id=key[0],stage=key[1],version=key[2],variant=key[3],
                                 **{k:0 for k in COUNTS},miss_reasons={},unresolved_reasons={})
            a=result[key]
            for field in COUNTS:
                n=group[field]
                need(type(n) in (int,float) and (field=='net_yen' or n>=0),'BAD_SUMMARY_COUNT')
                a[field]+=n
            for reason_name in ('miss_reasons','unresolved_reasons'):
                for reason,n in group.get(reason_name,{}).items():
                    need(type(n) is int and n>=0,'BAD_REASON_COUNT')
                    a[reason_name][reason]=a[reason_name].get(reason,0)+n
    groups=[]
    for key in sorted(result):
        a=result[key]
        need(a['eligible']==a['hits']+a['misses'],'INCONSISTENT_HITS')
        need(a['forecasts']==a['eligible']+a['void']+a['pending']+a['held'],'INCONSISTENT_COVERAGE')
        a['hit_rate']=a['hits']/a['eligible'] if a['eligible'] else None
        a['roi']=a['returned_yen']/a['stake_yen'] if a['stake_yen'] else None
        groups.append(a)
    return dict(schema='RACE_AI_ALL_DAYS_PDCA_SUMMARY_V1',days=len(data['days']),
                revisions=sum(len(v) for v in data['days'].values()),model_groups=groups,
                unscored=sum(g['pending']+g['held'] for g in groups),
                actual_purchases=False,source_provider_requests=0,full_history_coverage_verified=False)


def verify_day(control,*,day,view,summary):
    data=_unwrap(control)
    history=data['days'].get(day)
    need(bool(history),'DAY_NOT_ARCHIVED')
    current=history[-1]
    need(current['inventory_sha']==F.inventory_sha(view) and current['result_evidence_sha']==evidence_sha(view,day),
         'LATEST_EVIDENCE_MISMATCH')
    need(wire(current['summary'])==wire(summary),'SCORE_READBACK_MISMATCH')
    expected=sha(wire(dict(day=day,inventory_sha=current['inventory_sha'],result_evidence_sha=current['result_evidence_sha'],summary=summary)).encode('utf-8'))
    need(current['revision_sha']==expected,'REVISION_SHA_MISMATCH')
    return dict(status='VERIFIED',revision_sha=current['revision_sha'],days=len(data['days']),revisions=sum(len(v) for v in data['days'].values()))
