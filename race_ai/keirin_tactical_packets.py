"""Shared admission of independently SHA-pinned reviewed tactical packets.

Source bytes and opportunity semantics are reviewed upstream; this module
validates the bound packet, identities and availability, not its interpretation.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time as time_of_day, timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import keirin_tactical_observations as tactics

TACTICAL_SCHEMA='KEIRIN_REVIEWED_TACTICAL_EPISODES_V1'
TACTICAL_SCOPE='PRIVATE_RETROSPECTIVE_TACTICAL_OBSERVATIONS'
TACTICAL_HOSTS={'keirin.jp','www.keirin.jp','keirin.kdreams.jp','keirin.netkeiba.com'}
JST=ZoneInfo('Asia/Tokyo')


def _need(condition,code):
    if not condition:raise ValueError('KEIRIN_DOSSIER_'+code)


def _json(raw):
    _need(type(raw) is bytes and 0<len(raw)<=16*1024*1024,'JSON_BYTES')
    def pairs(values):
        result={}
        for key,value in values:
            _need(key not in result,'JSON_DUPLICATE_KEY');result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:_need(False,'NONFINITE_JSON'))


def _clock(value):
    _need(type(value) is str,'CLOCK_INVALID')
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    _need(parsed.utcoffset() is not None,'CLOCK_INVALID')
    return parsed.astimezone(timezone.utc)



def _tactical_receipt(receipt,binding,*,identity=False):
    fields={'race_id','registration','car','url','sha256','available_at'}
    if identity:fields.add('finish')
    _need(type(receipt) is dict and set(receipt)==fields and
          all(type(receipt[key]) is type(value) and receipt[key]==value for key,value in binding.items()),'RECEIPT_UNBOUND')
    _need(type(receipt['url']) is str and not any(ord(c)<=32 for c in receipt['url']),'RECEIPT_UNBOUND')
    loc=urlsplit(receipt['url']);digest=receipt['sha256']
    _need(loc.scheme=='https' and loc.hostname in TACTICAL_HOSTS and loc.path.startswith('/') and
          not loc.username and not loc.password and loc.port is None and not loc.fragment and
          type(digest) is str and re.fullmatch(r'[0-9a-f]{64}',digest),'RECEIPT_UNBOUND')
    if identity:
        finish=receipt['finish']
        _need(finish is None or type(finish) is int and 1<=finish<=9,'RECEIPT_UNBOUND')
    return _clock(receipt['available_at'])


def _tactical_rows(raw,expected_sha,registered,as_of_day,now):
    """Admit a separately pinned packet produced by a source reviewer.

    The caller obtains the expected digest through an independent trusted path.
    Receipt bindings and clocks are checked here. Their source bytes and the
    reviewer's interpretation must already have been checked when preparing it.
    """
    _need(type(raw) is bytes and sha256(raw).hexdigest()==expected_sha,'TACTICAL_SHA_MISMATCH')
    packet=_json(raw)
    _need(type(packet) is dict and set(packet)=={'schema','scope','prepared_at','episodes'} and
          packet['schema']==TACTICAL_SCHEMA and packet['scope']==TACTICAL_SCOPE and
          type(packet['episodes']) is list and len(packet['episodes'])<=20000,'TACTICAL_SCHEMA')
    prepared=_clock(packet['prepared_at'])
    _need(prepared<=now,'TACTICAL_PREPARED_AFTER_BUILD')
    cutoff=min(now,datetime.combine(as_of_day,time_of_day.min,tzinfo=JST))
    fields={'race_id','registration','car','event_id','ability','source','reviewed_at','published_at',
            'observation_receipt','identity_receipt'}
    held=Counter();candidates=[];by_slot=defaultdict(set);by_rider=defaultdict(set);finishes=defaultdict(set)
    for row in packet['episodes']:
        try:
            _need(type(row) is dict,'ROW_INVALID')
            by_side=row.get('ability')=='inside_outside'
            _need(set(row)==fields|({'side','finish'} if by_side else {'outcome','measurement'}),'ROW_INVALID')
            rid,car,registration=row['race_id'],row['car'],row['registration']
            _need(type(rid) is str and re.fullmatch(r'20[0-9]{10}',rid) and 1<=int(rid[8:10])<=99 and
                  1<=int(rid[10:])<=12 and type(car) is int and 1<=car<=9 and
                  (type(registration) is str and re.fullmatch(r'[0-9]{6}',registration) is not None) and registration in registered,'RACE_OR_STARTER_INVALID')
            race_day=date.fromisoformat(rid[:8]);_need(race_day<as_of_day,'RACE_NOT_HISTORICAL')
            reviewed=_clock(row['reviewed_at'])
            _need(reviewed<=prepared and reviewed<cutoff,'REVIEW_NOT_AVAILABLE')
            binding=dict(race_id=rid,car=car,registration=registration)
            observed,identity=row['observation_receipt'],row['identity_receipt']
            observed_at=_tactical_receipt(observed,binding)
            identity_at=_tactical_receipt(identity,binding,identity=True)
            _need(observed['sha256']!=identity['sha256'] and observed['url']!=identity['url'] and
                  (not by_side or row['finish'] is None or row['finish']==identity['finish']),'RECEIPT_UNBOUND')
            race_start=datetime.combine(race_day,time_of_day.min,tzinfo=JST)
            _need(race_start<=min(observed_at,identity_at) and max(observed_at,identity_at)<=reviewed and
                  (row['published_at'] is None or race_start<=_clock(row['published_at'])<=observed_at),
                  'RECEIPT_CLOCK_INVALID')
            _need(type(row['source']) is str and row['source'] in tactics.SOURCES,'ROW_INVALID')
            evidence={key:value for key,value in row.items() if key not in
                      ('car','reviewed_at','observation_receipt','identity_receipt')}
            evidence['observed_at']=row['reviewed_at']
            tactics._episode(evidence)
        except (ValueError,TypeError,KeyError) as error:
            reason=str(error).removeprefix('KEIRIN_DOSSIER_') if str(error).startswith('KEIRIN_DOSSIER_') else 'ROW_INVALID'
            held[reason]+=1
            continue
        candidates.append((rid,car,registration,evidence))
        by_slot[rid,car].add(registration)
        by_rider[rid,registration].add(car)
        if identity['finish'] is not None:finishes[rid,car].add(identity['finish'])
    rows=defaultdict(list)
    for rid,car,registration,evidence in candidates:
        if len(by_slot[rid,car])>1 or len(by_rider[rid,registration])>1 or len(finishes[rid,car])>1:
            held['STARTER_CONFLICT']+=1
        else:rows[registration].append(evidence)
    meta=dict(scope=TACTICAL_SCOPE,source_sha256=expected_sha,prepared_at=packet['prepared_at'],
              review_available_before=cutoff.astimezone(timezone.utc).isoformat(),submitted_rows=len(packet['episodes']),
              admitted_rows=sum(map(len,rows.values())),held_by_reason=dict(held),predictive_model_changed=False)
    return rows,meta
