"""Verify prior-day official result identities against a frozen pre-close roster.

PR64's racelist parser is intentionally same-day-only. This guard uses the
original sealed C-lite participant list to check a later individual
raceresult observation, without inventing a historical capture timestamp.
The caller must independently authenticate GitHub original ZIP and JSON.
No HTTP, forecasts, training, or scores are produced here.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re

RACER = re.compile(r'[0-9]{4}\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')
MODEL = 'boat-local-start-course-shadow-v0.1-UNTRAINED'


def _need(ok, why):
    if not ok:
        raise ValueError(why)


def _time(value):
    _need(isinstance(value,str),'timestamp required')
    value=datetime.fromisoformat(value.replace('Z','+00:00'))
    _need(value.utcoffset() is not None,'timezone required')
    return value


def _sealed(d):
    _need(isinstance(d,dict) and isinstance(d.get('bundle_sha256'),str),'sealed original required')
    actual=hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!='bundle_sha256'},
        ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    _need(d['bundle_sha256']==actual,'original bundle hash mismatch')


def _pre_receipt(generated,saved):
    return generated<=saved or (saved.microsecond==0 and saved<=generated<saved+timedelta(seconds=1))


def validate_historical_result_roster(pair, shadow, official, server_saved_at):
    """Return source-identity evidence or fail closed, never a graded race.

    Requires a previously frozen, separately sealed C-lite six-racer roster
    and an official parsed individual result with six finishing dispositions.
    Pending/return-only/cancelled results must be recorded in separate states.
    """
    _sealed(pair)
    _sealed(shadow)
    _need(pair.get('schema')=='RACE_AI_BOAT_PRE_CUTOFF_AB_PAIR_V1' and
          shadow.get('schema')=='RACE_AI_BOAT_CURRENT_FEATURE_SHADOW_V1' and
          shadow.get('model_id')==MODEL,'pair and frozen shadow required')
    rid=pair.get('race_id')
    cutoff=_time(pair.get('cutoff_at'))
    saved=_time(server_saved_at)
    _need(isinstance(rid,str) and re.fullmatch(r'\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])',rid) is not None
          and cutoff.strftime('%Y%m%d')==rid[:8]
          and cutoff.utcoffset()==timedelta(hours=9), 'valid race identity and JST cutoff required')
    _need(shadow.get('race_id')==rid and shadow.get('cutoff_at')==pair['cutoff_at']
          and shadow.get('source_snapshot_sha256')==pair.get('source_sha256')
          and all(isinstance(x,str) and HEX.fullmatch(x) for x in
                  (pair.get('source_sha256'),shadow.get('extra_source_sha256'))),
          'frozen current-roster source must match A/B race')
    _need(shadow.get('untrained') is True and shadow.get('calibrated') is False
          and shadow.get('odds_used') is False and shadow.get('auto_promoted') is False
          and shadow.get('betting_decision')=='NO_BET', 'unsafe shadow origin')
    captured=_time(pair['source_captured_at'])
    generated=_time(pair['generated_at'])
    shadow_at=_time(shadow['as_of'])
    _need(captured<=generated<=shadow_at<cutoff and _pre_receipt(generated,saved)
          and _pre_receipt(shadow_at,saved) and saved<cutoff,
          'original source and receipt chronology invalid')
    rows=shadow.get('features')
    _need(isinstance(rows,list) and len(rows)==6,'six preclose racer identities required')
    originals={}
    for entry in rows:
        _need(isinstance(entry,dict),'frozen racer invalid')
        lane=entry.get('lane');racer=entry.get('racer_id')
        _need(type(lane) is int and lane in range(1,7) and lane not in originals
              and isinstance(racer,str) and RACER.fullmatch(racer) is not None,
              'distinct lane and official registered racer required')
        originals[lane]=racer
    _need(len(set(originals.values()))==6,'duplicate frozen racer')
    _need(isinstance(official,dict) and official.get('race_id')==rid
          and official.get('kind')=='raceresult'
          and official.get('body_identity_verified') is True
          and official.get('closed_at')==pair['cutoff_at']
          and official.get('status')=='AVAILABLE', 'official dated result identity missing')
    result_time=_time(official.get('captured_at'))
    _need(result_time>=cutoff and result_time>=saved,'official result cannot be preclosing')
    data=official.get('data')
    _need(isinstance(data,dict) and data.get('finish_confirmed') is True,
          'confirmed six-boats result required')
    actual=data.get('results')
    _need(isinstance(actual,list) and len(actual)==6,'six official results required')
    seen={}
    for entry in actual:
        _need(isinstance(entry,dict),'result racer invalid')
        lane=entry.get('lane');racer=entry.get('racer_registration_id')
        _need(type(lane) is int and lane in range(1,7) and lane not in seen
              and isinstance(racer,str) and RACER.fullmatch(racer) is not None,
              'unique official finisher identity required')
        seen[lane]=racer
    _need(seen==originals,'official finishing racers differ from preclose frozen roster')
    return {'race_id':rid,'roster_source':'SEALED_PRE_CUTOFF_C_LITE',
            'official_result_captured_at':official['captured_at'],
            'original_server_saved_at':server_saved_at,
            'preclose_shadow_sha256':shadow['bundle_sha256']}
