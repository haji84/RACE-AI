"""Bind a frozen execution intent to byte-exact existing recovery authority.

This transport wrapper supplies no grant, key, source clock or extra request.
Existing recovery validators still authenticate every inner authority field.
"""
import base64
from copy import deepcopy
from hashlib import sha256
import hmac
import re

from .actions_contract import digest
from .boat_all_model_store import open_forecasts,seal_forecasts,forecast_header,MAX_WIRE

SCHEMA='RACE_AI_OFFICIAL_FROZEN_CAPSULE_V2'
BINDING='RACE_AI_OFFICIAL_FROZEN_SOURCE_BINDING_V1'
ROUND=900034


def need(ok,reason):
    if not ok:raise ValueError('OFFICIAL_FROZEN_CAPSULE_'+reason)


def validate_binding(value):
    fields={'schema','tested_execution_head_sha','intent_head_sha','intent_parent_sha','target',
            'issue_request_blob_sha256','recovery_request_blob_sha256','protected_files_sha256'}
    need(type(value) is dict and set(value)==fields and value['schema']==BINDING,'BINDING_FIELDS')
    need(all(type(value[k]) is str and re.fullmatch('[a-f0-9]{40}',value[k]) for k in
        ('tested_execution_head_sha','intent_head_sha','intent_parent_sha')) and
        all(type(value[k]) is str and re.fullmatch('[a-f0-9]{64}',value[k]) for k in
        ('issue_request_blob_sha256','recovery_request_blob_sha256','protected_files_sha256')),'BINDING_HASHES')
    target=value['target']
    need(type(target) is dict and set(target)=={'head_sha','run_id','run_attempt'} and
        target['head_sha']==value['tested_execution_head_sha'] and type(target['run_id']) is int and
        0<target['run_id']<10**20 and type(target['run_attempt']) is int and target['run_attempt']==2,'BINDING_TARGET')
    return deepcopy(value)


def _inner(raw,key):
    from . import all_existing_model_official_recovery as recovery
    from . import all_existing_model_official_continuation as continuation
    from . import all_existing_model_official_probe16 as probe
    need(type(raw) is bytes and 0<len(raw)<=MAX_WIRE,'INNER_BYTES')
    value=open_forecasts(raw,key=key);header=forecast_header(raw)
    authorities={a.SCHEMA:a for a in (recovery,continuation,probe)}
    need(type(value) is dict and set(value)=={'schema','body','mac'} and value.get('schema') in authorities and
        type(value.get('body')) is dict and type(value.get('mac')) is str,'INNER_SCHEMA')
    authority=authorities[value['schema']];body=value['body']
    need(hmac.compare_digest(value['mac'],authority._mac(body,key)) and body.get('schema')==authority.SCHEMA and
        type(body.get('request')) is dict and body.get('request_sha256')==digest(body['request']) and
        type(body.get('target')) is dict and header['run_id']==str(body['target'].get('run_id')) and
        header['round_no']==authority.ROUND,'INNER_AUTHENTICATION')
    return value


def wrap_capsule(inner,binding,*,key):
    scope=validate_binding(binding);value=_inner(inner,key)
    need(value['body']['target']==scope['target'],'INNER_TARGET')
    payload=dict(schema=SCHEMA,source_frozen_binding=scope,inner_sha256=sha256(inner).hexdigest(),
                 inner_capsule_base64=base64.b64encode(inner).decode())
    return seal_forecasts(payload,run_id=str(scope['target']['run_id']),round_no=ROUND,key=key)


def _unwrap(raw,key):
    value=open_forecasts(raw,key=key);header=forecast_header(raw)
    need(type(value) is dict and set(value)=={'schema','source_frozen_binding','inner_sha256','inner_capsule_base64'} and
        value.get('schema')==SCHEMA,'OUTER_SCHEMA')
    scope=validate_binding(value['source_frozen_binding'])
    need(header['run_id']==str(scope['target']['run_id']) and header['round_no']==ROUND and
        type(value['inner_capsule_base64']) is str,'OUTER_TARGET')
    try:inner=base64.b64decode(value['inner_capsule_base64'],validate=True)
    except (ValueError,TypeError):raise ValueError('OFFICIAL_FROZEN_CAPSULE_INNER_ENCODING') from None
    need(base64.b64encode(inner).decode()==value['inner_capsule_base64'] and
        sha256(inner).hexdigest()==value['inner_sha256'],'INNER_HASH')
    decoded=_inner(inner,key);need(decoded['body']['target']==scope['target'],'INNER_TARGET')
    return inner,scope,decoded


def unwrap_capsule(raw,*,expected_binding,key):
    expected=validate_binding(expected_binding);inner,scope,_=_unwrap(raw,key)
    need(scope==expected,'ACTIVE_INTENT_BINDING')
    return inner


def archival_inner(raw,*,request,target,key):
    """Decode transport for the existing archival validator, never live admit."""
    value=open_forecasts(raw,key=key)
    if value.get('schema')==SCHEMA:inner,scope,value=_unwrap(raw,key)
    else:inner=raw;value=_inner(raw,key)
    need(value['body']['request']==request and value['body']['target']==target,'ARCHIVAL_SCOPE')
    return inner


def archival_probe_inner(raw,*,request_sha256,target,key):
    """Decode only the hash-pinned prior probe used by old continuation checks."""
    need(type(request_sha256) is str and re.fullmatch('[a-f0-9]{64}',request_sha256),'ARCHIVAL_REQUEST_HASH')
    value=open_forecasts(raw,key=key)
    if value.get('schema')==SCHEMA:inner,scope,value=_unwrap(raw,key)
    else:inner=raw;value=_inner(raw,key)
    need(value['body']['request_sha256']==request_sha256 and value['body']['target']==target,'ARCHIVAL_SCOPE')
    return inner
