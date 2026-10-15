"""Immutable independent name proofs with pre-close receipt finalization.

Finalization persistence is not input timing evidence: its clock attests the
preceding exact receipt-byte readback. Only the serialized OIDC writer writes.
"""
import copy
from datetime import datetime, timezone
import hashlib
import re
from api.race_store import REVIEW,JST,canonical,decode,instant,checked_race_id,read_blob,put_verified
from api.prediction_store import request_identifier
from evaluation_contract import _checked_prediction
from name_binding_contract import validate_name_binding,validate_name_binding_receipt

MAX_BYTES=64_000
REQUEST={'publication_review','race_id','request_id','baseline_request_id','snapshot','runner_saved_at'}
PINS=('baseline_snapshot_id','b_program_sha256','program_identity_sha256')
MARKER={'schema_version','race_id','request_id','baseline_request_id','snapshot_id',*PINS,'receipt_sha256','receipt_confirmed_at'}
MANIFEST={'schema_version','race_id','request_id','snapshot_id',*PINS,'published_at'}

def require(value):
    if not value:raise ValueError('NAME_BINDING_STORE_INVALID')

def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def manifest_key(race_id):return f'race-ai/name-binding/{race_id}.json'
def receipt_key(race_id,request_id):return f'race-ai/name-binding-receipts/{race_id}/{request_identifier(request_id)}.json'
def finalization_key(race_id,request_id):return f'race-ai/name-binding-finalizations/{race_id}/{request_identifier(request_id)}.json'
def version_key(race_id,snapshot_id):
    require(isinstance(snapshot_id,str) and re.fullmatch('[0-9a-f]{64}',snapshot_id) is not None)
    return f'race-ai/name-binding-versions/{race_id}/{snapshot_id}.json'

def bounded_read(client,key):
    raw=read_blob(client,key)
    require(raw is None or len(raw)<=MAX_BYTES)
    return raw

def bounded_put(client,key,value,*,overwrite=False):
    raw=canonical(value);require(len(raw)<=MAX_BYTES)
    put_verified(client,key,raw,overwrite=overwrite)

def baseline_pins(baseline,race,now):
    now=instant(now);checked_race_id(race['race_id'],now)
    checked=_checked_prediction(baseline,race,now,now.astimezone(JST).date(),instant(race['closed_at']))
    require(checked is not None)
    return dict(baseline_snapshot_id=checked['snapshot']['snapshot_id'],b_program_sha256=checked['snapshot']['program_sha256'])

def checked_receipt(receipt,race,baseline,now):
    pins=baseline_pins(baseline,race,now)
    value=validate_name_binding_receipt(receipt,race,**pins,now=now)
    require(value['baseline_request_id']==baseline['request_id']
        and instant(baseline['cloud_saved_at'])<=instant(value['snapshot']['source']['captured_at']))
    return value

def validate_finalized_binding(envelope,race,baseline,*,now):
    """Pure replay of server evidence; does not itself claim cloud persistence."""
    try:
        require(isinstance(envelope,dict) and set(envelope)=={'receipt','finalization'} and len(canonical(envelope))<=MAX_BYTES)
        receipt=checked_receipt(envelope['receipt'],race,baseline,now)
        marker=envelope['finalization'];require(isinstance(marker,dict) and set(marker)==MARKER)
        require(type(marker['schema_version']) is int and marker['schema_version']==1
            and marker['race_id']==race['race_id'] and marker['request_id']==receipt['request_id']
            and marker['baseline_request_id']==receipt['baseline_request_id']
            and marker['snapshot_id']==receipt['snapshot']['snapshot_id']
            and all(marker[k]==receipt[k] for k in PINS) and marker['receipt_sha256']==digest(receipt))
        confirmed=instant(marker['receipt_confirmed_at'])
        require(instant(receipt['cloud_saved_at'])<=confirmed<instant(race['closed_at']) and confirmed<=instant(now)
            and confirmed.astimezone(JST).date()==instant(now).astimezone(JST).date())
        return copy.deepcopy(envelope)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,UnicodeError,RecursionError) as exc:
        raise ValueError('NAME_BINDING_FINALIZATION_INVALID') from exc

def resolve_request_id(race,*,client,now,request_id=None):
    checked_race_id(race['race_id'],instant(now))
    if request_id is not None:return request_identifier(request_id)
    raw=bounded_read(client,manifest_key(race['race_id']))
    if raw is None:return None
    value=decode(raw)
    require(isinstance(value,dict) and set(value)==MANIFEST and type(value['schema_version']) is int
        and value['schema_version']==1 and value['race_id']==race['race_id'])
    published=instant(value['published_at'])
    require(published<=instant(now) and published.astimezone(JST).date()==instant(now).astimezone(JST).date())
    return request_identifier(value['request_id'])

def baseline_request_hint(race,*,client,now,request_id=None):
    """Bounded untrusted hint only; caller must load and verify immutable baseline."""
    identifier=resolve_request_id(race,client=client,now=now,request_id=request_id)
    if identifier is None:return None
    raw=bounded_read(client,receipt_key(race['race_id'],identifier))
    if raw is None:return None
    value=decode(raw);require(isinstance(value,dict) and value.get('request_id')==identifier)
    return request_identifier(value.get('baseline_request_id'))

def read_name_binding(race,baseline,*,client,now,request_id=None):
    now=instant(now);baseline_pins(baseline,race,now)
    identifier=resolve_request_id(race,client=client,now=now,request_id=request_id)
    if identifier is None:return None
    raw=bounded_read(client,receipt_key(race['race_id'],identifier))
    if raw is None:return None
    marker=bounded_read(client,finalization_key(race['race_id'],identifier));require(marker is not None)
    receipt=decode(raw);require(raw==canonical(receipt))
    envelope=validate_finalized_binding(dict(receipt=receipt,finalization=decode(marker)),race,baseline,now=now)
    require(receipt['request_id']==identifier)
    stored=bounded_read(client,version_key(race['race_id'],receipt['snapshot']['snapshot_id']))
    require(stored==canonical(receipt['snapshot']))
    if request_id is None:
        latest=decode(bounded_read(client,manifest_key(race['race_id'])))
        require(latest['request_id']==identifier and latest['snapshot_id']==receipt['snapshot']['snapshot_id']
            and all(latest[k]==receipt[k] for k in PINS)
            and instant(latest['published_at'])>=instant(envelope['finalization']['receipt_confirmed_at']))
    return envelope

def position(envelope):
    r=envelope['receipt'];s=r['snapshot']
    return (instant(s['source']['captured_at']),instant(s['generated_at']),instant(r['runner_saved_at']),instant(r['cloud_saved_at']),r['request_id'])

def publish_name_binding(request,race,baseline,*,client,now,clock=None):
    now=instant(now);pins=baseline_pins(baseline,race,now);closed=instant(race['closed_at']);day=now.astimezone(JST).date()
    clock=clock or (lambda:datetime.now(timezone.utc))
    require(isinstance(request,dict) and set(request)==REQUEST and len(canonical(request))<=MAX_BYTES
        and request['publication_review']==REVIEW and request['race_id']==race['race_id']
        and request['baseline_request_id']==baseline['request_id'])
    identifier=request_identifier(request['request_id'])
    snapshot=validate_name_binding(request['snapshot'],race,**pins,now=now)
    # Validate all supplied clocks and pins before any write.
    provisional=dict(schema_version=1,request_id=identifier,baseline_request_id=request['baseline_request_id'],snapshot=snapshot,
        runner_saved_at=request['runner_saved_at'],cloud_saved_at=now.isoformat(timespec='microseconds'),cloud_eligible_pre_race=True,
        **pins,program_identity_sha256=snapshot['program_identity_sha256'])
    existing=bounded_read(client,receipt_key(race['race_id'],identifier))
    if existing is not None:
        envelope=read_name_binding(race,baseline,client=client,now=now,request_id=identifier)
        require(envelope['receipt']['snapshot']==snapshot and envelope['receipt']['runner_saved_at']==request['runner_saved_at']
            and envelope['receipt']['baseline_request_id']==request['baseline_request_id'])
        return metadata(envelope,race)
    checked_receipt(provisional,race,baseline,now)
    require(now<closed)
    previous=read_name_binding(race,baseline,client=client,now=now)
    key=version_key(race['race_id'],snapshot['snapshot_id']);old=bounded_read(client,key)
    if old is None:bounded_put(client,key,snapshot)
    else:require(old==canonical(snapshot))
    def preclose(minimum):
        measured=instant(clock())
        require(minimum<=measured<closed and measured.astimezone(JST).date()==day)
        return measured
    saved=preclose(now)
    receipt={**provisional,'cloud_saved_at':saved.isoformat(timespec='microseconds')}
    checked_receipt(receipt,race,baseline,saved)
    bounded_put(client,receipt_key(race['race_id'],identifier),receipt)
    confirmed=preclose(saved)
    marker=dict(schema_version=1,race_id=race['race_id'],request_id=identifier,baseline_request_id=receipt['baseline_request_id'],
        snapshot_id=snapshot['snapshot_id'],**{k:receipt[k] for k in PINS},receipt_sha256=digest(receipt),
        receipt_confirmed_at=confirmed.isoformat(timespec='microseconds'))
    envelope=validate_finalized_binding(dict(receipt=receipt,finalization=marker),race,baseline,now=confirmed)
    bounded_put(client,finalization_key(race['race_id'],identifier),marker)
    if previous is None or position(envelope)>position(previous):
        published=preclose(confirmed)
        latest=dict(schema_version=1,race_id=race['race_id'],request_id=identifier,snapshot_id=snapshot['snapshot_id'],
            **{k:receipt[k] for k in PINS},published_at=published.isoformat(timespec='microseconds'))
        bounded_put(client,manifest_key(race['race_id']),latest,overwrite=True)
    served=read_name_binding(race,baseline,client=client,now=instant(clock()),request_id=identifier)
    return metadata(served,race)

def metadata(envelope,race):
    r=envelope['receipt']
    return dict(status='verified',race_id=race['race_id'],request_id=r['request_id'],snapshot_id=r['snapshot']['snapshot_id'],
        baseline_request_id=r['baseline_request_id'],**{k:r[k] for k in PINS},runner_saved_at=r['runner_saved_at'],
        cloud_saved_at=r['cloud_saved_at'],receipt_confirmed_at=envelope['finalization']['receipt_confirmed_at'],
        cloud_eligible_pre_race=True,pathname=manifest_key(race['race_id']),sha256=digest(envelope),
        research_only=True,validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
