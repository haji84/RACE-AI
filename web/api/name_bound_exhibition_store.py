"""Immutable finalized v2 packets; each read resolves its own pinned parents."""
from datetime import datetime, timezone
import re
from api.race_store import REVIEW,JST,canonical,decode,instant,checked_race_id,read_blob,put_verified
from api.prediction_store import request_identifier,read_prediction
from api.name_binding_store import read_name_binding
from api.original_exhibition_store import REVIEW as MEDIA_REVIEW
from name_bound_inputs import validate_name_bound_inputs
from name_bound_prediction import build_name_bound_prediction,validate_name_bound_envelope,digest,MAX_BYTES

REQUEST={'publication_review','media_review','race_id','request_id','baseline_request_id','name_binding_request_id','inputs','runner_saved_at'}
MANIFEST={'schema_version','race_id','request_id','snapshot_id','input_snapshot_id','baseline_request_id','name_binding_request_id','program_identity_sha256','published_at'}

def require(value):
    if not value:raise ValueError('NAME_BOUND_STORE_INVALID')

def manifest_key(race):return f'race-ai/name-bound-exhibition/{race}.json'
def receipt_key(race,nonce):return f'race-ai/name-bound-receipts/{race}/{request_identifier(nonce)}.json'
def finalization_key(race,nonce):return f'race-ai/name-bound-finalizations/{race}/{request_identifier(nonce)}.json'
def _version(race,identifier,namespace):
    require(isinstance(identifier,str) and re.fullmatch('[0-9a-f]{64}',identifier) is not None)
    return f'race-ai/{namespace}/{race}/{identifier}.json'
def input_key(race,identifier):return _version(race,identifier,'name-bound-inputs')
def prediction_key(race,identifier):return _version(race,identifier,'name-bound-predictions')

def bounded_read(client,key):
    raw=read_blob(client,key);require(raw is None or len(raw)<=MAX_BYTES)
    return raw

def read_value(client,key):
    raw=bounded_read(client,key)
    if raw is None:return None
    value=decode(raw);require(raw==canonical(value))
    return value

def put(client,key,value,*,overwrite=False):
    raw=canonical(value);require(len(raw)<=MAX_BYTES)
    put_verified(client,key,raw,overwrite=overwrite)

def put_version(client,key,value):
    existing=bounded_read(client,key)
    if existing is None:put(client,key,value)
    else:require(existing==canonical(value))

def parents(race,baseline_id,binding_id,client,now):
    baseline=read_prediction(race,client=client,now=now,request_id=request_identifier(baseline_id))
    require(baseline is not None)
    binding=read_name_binding(race,baseline,client=client,now=now,request_id=request_identifier(binding_id))
    require(binding is not None)
    return baseline,binding

def _read_pinned(race,identifier,client,now):
    r=read_value(client,receipt_key(race['race_id'],identifier))
    if r is None:return None
    m=read_value(client,finalization_key(race['race_id'],identifier));require(m is not None)
    require(r['request_id']==identifier)
    baseline,binding=parents(race,r['baseline_request_id'],r['name_binding_request_id'],client,now)
    s=r['snapshot'];i=read_value(client,input_key(race['race_id'],s['input_link']['snapshot_id']))
    require(i is not None and bounded_read(client,prediction_key(race['race_id'],s['snapshot_id']))==canonical(s))
    return validate_name_bound_envelope(dict(receipt=r,finalization=m,inputs=i,baseline=baseline,name_binding=binding),race,now=now)

def read_name_bound_exhibition(race,*,client,now,request_id=None):
    now=instant(now);checked_race_id(race['race_id'],now)
    if request_id is not None:return _read_pinned(race,request_identifier(request_id),client,now)
    latest=read_value(client,manifest_key(race['race_id']))
    if latest is None:return None
    require(isinstance(latest,dict) and set(latest)==MANIFEST and type(latest['schema_version']) is int and latest['schema_version']==1 and latest['race_id']==race['race_id'])
    e=_read_pinned(race,request_identifier(latest['request_id']),client,now);require(e is not None)
    r=e['receipt'];s=r['snapshot'];published=instant(latest['published_at'])
    expected=dict(schema_version=1,race_id=race['race_id'],request_id=r['request_id'],snapshot_id=s['snapshot_id'],input_snapshot_id=e['inputs']['snapshot_id'],
        baseline_request_id=r['baseline_request_id'],name_binding_request_id=r['name_binding_request_id'],program_identity_sha256=s['program_identity_sha256'],published_at=latest['published_at'])
    require(latest==expected and instant(e['finalization']['receipt_confirmed_at'])<=published<=now and published<instant(race['closed_at'])
        and published.astimezone(JST).date()==now.astimezone(JST).date() and latest['published_at']==published.isoformat(timespec='microseconds'))
    return e

def position(e):
    r=e['receipt'];s=r['snapshot'];i=e['inputs']
    captures=[i['beforeinfo_record']['captured_at'],*[x['captured_at'] for x in i['original_observation']['sources']]]
    return (max(map(instant,captures)),instant(s['generated_at']),instant(s['input_link']['runner_saved_at']),instant(r['cloud_saved_at']),r['request_id'])

def metadata(e,race):
    r=e['receipt'];s=r['snapshot']
    return dict(status='verified',race_id=race['race_id'],request_id=r['request_id'],snapshot_id=s['snapshot_id'],input_snapshot_id=e['inputs']['snapshot_id'],
        baseline_request_id=r['baseline_request_id'],name_binding_request_id=r['name_binding_request_id'],input_cloud_saved_at=s['input_link']['input_cloud_saved_at'],
        cloud_saved_at=r['cloud_saved_at'],receipt_confirmed_at=e['finalization']['receipt_confirmed_at'],sha256=digest(e),research_only=True,
        validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])

def publish_name_bound_exhibition(request,race,*,client,now,clock=None):
    now=instant(now);checked_race_id(race['race_id'],now);closed=instant(race['closed_at']);day=now.astimezone(JST).date()
    clock=clock or (lambda:datetime.now(timezone.utc))
    require(isinstance(request,dict) and set(request)==REQUEST and len(canonical(request))<=MAX_BYTES
        and request['publication_review']==REVIEW and request['media_review']==MEDIA_REVIEW and request['race_id']==race['race_id'])
    identifier=request_identifier(request['request_id'])
    for k in ('baseline_request_id','name_binding_request_id'):request_identifier(request[k])
    existing=bounded_read(client,receipt_key(race['race_id'],identifier))
    if existing is not None:
        e=_read_pinned(race,identifier,client,now);r=e['receipt'];s=r['snapshot']
        require(canonical(e['inputs'])==canonical(request['inputs']) and s['input_link']['runner_saved_at']==request['runner_saved_at']
            and all(r[k]==request[k] for k in ('request_id','baseline_request_id','name_binding_request_id')))
        return metadata(e,race)
    require(bounded_read(client,finalization_key(race['race_id'],identifier)) is None and now<closed)
    baseline,binding=parents(race,request['baseline_request_id'],request['name_binding_request_id'],client,now)
    def preclose(minimum):
        t=instant(clock());require(minimum<=t<closed and t.astimezone(JST).date()==day)
        return t
    resolved=preclose(now)
    inputs=validate_name_bound_inputs(request['inputs'],race,baseline,binding,now=resolved)
    runner=instant(request['runner_saved_at'])
    require(instant(inputs['generated_at'])<=runner<=resolved and request['runner_saved_at']==runner.isoformat(timespec='microseconds'))
    # Resolve previous latest against ITS parents, independently of this request.
    previous=read_name_bound_exhibition(race,client=client,now=resolved)
    put_version(client,input_key(race['race_id'],inputs['snapshot_id']),inputs)
    input_saved=preclose(resolved)
    generated=preclose(input_saved)
    snapshot=build_name_bound_prediction(inputs,race,baseline,binding,runner_saved_at=request['runner_saved_at'],
        parents_resolved_at=resolved,input_cloud_saved_at=input_saved,now=generated)
    put_version(client,prediction_key(race['race_id'],snapshot['snapshot_id']),snapshot)
    saved=preclose(generated)
    receipt=dict(schema_version=1,request_id=identifier,baseline_request_id=request['baseline_request_id'],name_binding_request_id=request['name_binding_request_id'],
        snapshot=snapshot,cloud_saved_at=saved.isoformat(timespec='microseconds'),cloud_eligible_pre_race=True)
    put(client,receipt_key(race['race_id'],identifier),receipt)
    confirmed=preclose(saved)
    marker=dict(schema_version=1,race_id=race['race_id'],request_id=identifier,snapshot_id=snapshot['snapshot_id'],input_snapshot_id=inputs['snapshot_id'],
        baseline_request_id=request['baseline_request_id'],name_binding_request_id=request['name_binding_request_id'],receipt_sha256=digest(receipt),receipt_confirmed_at=confirmed.isoformat(timespec='microseconds'))
    # Aggregate bound and full replay happen BEFORE marker makes the nonce eligible.
    e=validate_name_bound_envelope(dict(receipt=receipt,finalization=marker,inputs=inputs,baseline=baseline,name_binding=binding),race,now=confirmed)
    put(client,finalization_key(race['race_id'],identifier),marker)
    if previous is None or position(e)>position(previous):
        published=preclose(confirmed)
        latest=dict(schema_version=1,race_id=race['race_id'],request_id=identifier,snapshot_id=snapshot['snapshot_id'],input_snapshot_id=inputs['snapshot_id'],
            baseline_request_id=request['baseline_request_id'],name_binding_request_id=request['name_binding_request_id'],program_identity_sha256=snapshot['program_identity_sha256'],published_at=published.isoformat(timespec='microseconds'))
        put(client,manifest_key(race['race_id']),latest,overwrite=True)
    served=read_name_bound_exhibition(race,client=client,now=instant(clock()),request_id=identifier)
    return metadata(served,race)
