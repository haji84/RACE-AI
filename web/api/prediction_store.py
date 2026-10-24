"""Private research forecasts with measured durable pre-cutoff evidence.

The existing serialized OIDC workflow is the only writer (Blob has no CAS).
The server chooses inputs/models/time. A runner cannot submit probabilities or
claim an earlier save time. No recommendation is enabled by this evidence.
"""
from datetime import datetime, timezone
import hashlib
import re

from api.race_store import (REVIEW, JST, MAX_BYTES, canonical, decode, instant,
    checked_race_id, read_blob, put_verified)
from research_contract import build_research_bundle, validate_research_bundle

UTC = timezone.utc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def request_identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',value):
        raise ValueError('PREDICTION_REQUEST_ID_INVALID')
    return value


def manifest_key(race_id):
    return f'race-ai/predictions/{race_id}.json'


def receipt_key(race_id,request_id):
    return f'race-ai/prediction-receipts/{race_id}/{request_identifier(request_id)}.json'


def version_key(race_id,snapshot_id):
    if not isinstance(snapshot_id,str) or not re.fullmatch(r'[0-9a-f]{64}',snapshot_id):
        raise ValueError('PREDICTION_SNAPSHOT_ID_INVALID')
    return f'race-ai/prediction-versions/{race_id}/{snapshot_id}.json'


def checked_receipt(value,race,now):
    fields={'schema_version','request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race','program_sha256'}
    if (not isinstance(value,dict) or set(value)!=fields or type(value['schema_version']) is not int
            or value['schema_version']!=1 or value['cloud_eligible_pre_race'] is not True):
        raise ValueError('PREDICTION_RECEIPT_INVALID')
    request_identifier(value['request_id'])
    snapshot=validate_research_bundle(value['snapshot'],race,now)
    saved=instant(value['cloud_saved_at'])
    if (value['program_sha256']!=snapshot['program_sha256']
            or not instant(snapshot['generated_at'])<=saved<instant(race['closed_at'])
            or saved>instant(now) or saved.astimezone(JST).date()!=now.astimezone(JST).date()):
        raise ValueError('PREDICTION_RECEIPT_TIME_INVALID')
    if len(canonical(value))>MAX_BYTES:raise ValueError('PREDICTION_RECEIPT_TOO_LARGE')
    return value


def load_receipt(race,request_id,*,client,now):
    raw=read_blob(client,receipt_key(race['race_id'],request_id))
    if raw is None:return None
    receipt=checked_receipt(decode(raw),race,now)
    snapshot=receipt['snapshot']
    stored=read_blob(client,version_key(race['race_id'],snapshot['snapshot_id']))
    if receipt['request_id']!=request_id or stored!=canonical(snapshot):
        raise ValueError('PREDICTION_VERSION_CONFLICT')
    return receipt


def read_prediction(race,*,client,now,request_id=None):
    checked_race_id(race['race_id'],now)
    if request_id is not None:return load_receipt(race,request_id,client=client,now=now)
    raw=read_blob(client,manifest_key(race['race_id']))
    if raw is None:return None
    value=decode(raw)
    fields={'schema_version','race_id','request_id','snapshot_id','program_sha256','published_at'}
    if (not isinstance(value,dict) or set(value)!=fields or type(value['schema_version']) is not int
            or value['schema_version']!=1 or value['race_id']!=race['race_id']
            or instant(value['published_at'])>instant(now)
            or instant(value['published_at']).astimezone(JST).date()!=now.astimezone(JST).date()):
        raise ValueError('PREDICTION_MANIFEST_INVALID')
    receipt=load_receipt(race,value['request_id'],client=client,now=now)
    if (receipt is None or value['snapshot_id']!=receipt['snapshot']['snapshot_id']
            or value['program_sha256']!=receipt['program_sha256']
            or instant(value['published_at'])<instant(receipt['cloud_saved_at'])):
        raise ValueError('PREDICTION_MANIFEST_CONFLICT')
    return receipt


def publish_prediction(request,feed,race,*,client,now,clock=None):
    checked_race_id(race['race_id'],now)
    clock=clock or (lambda:datetime.now(UTC))
    if (not isinstance(request,dict) or set(request)!={'publication_review','race_id','request_id'}
            or request['publication_review']!=REVIEW or request['race_id']!=race['race_id']):
        raise ValueError('PREDICTION_REQUEST_INVALID')
    identifier=request_identifier(request['request_id'])
    previous=read_prediction(race,client=client,now=now)
    receipt=load_receipt(race,identifier,client=client,now=now)
    if receipt is None:
        if instant(now)>=instant(race['closed_at']):raise ValueError('PREDICTION_CUTOFF_PASSED')
        snapshot=build_research_bundle(feed,race,now)
        raw=canonical(snapshot);key=version_key(race['race_id'],snapshot['snapshot_id'])
        existing=read_blob(client,key)
        if existing is None:put_verified(client,key,raw,overwrite=False)
        elif existing!=raw:raise ValueError('PREDICTION_IMMUTABLE_CONFLICT')
        # Measure after the complete immutable forecast's durable readback.
        saved=instant(clock())
        if (saved<instant(now) or saved>=instant(race['closed_at'])
                or saved.astimezone(JST).date()!=now.astimezone(JST).date()):
            raise ValueError('PREDICTION_SAVED_AFTER_CUTOFF')
        receipt={'schema_version':1,'request_id':identifier,'snapshot':snapshot,
            'cloud_saved_at':saved.isoformat(timespec='microseconds'),'cloud_eligible_pre_race':True,
            'program_sha256':snapshot['program_sha256']}
        checked_receipt(receipt,race,saved)
        put_verified(client,receipt_key(race['race_id'],identifier),canonical(receipt),overwrite=False)
    position=lambda r:(instant(r['snapshot']['generated_at']),instant(r['cloud_saved_at']),r['request_id'])
    key=manifest_key(race['race_id'])
    if previous is None or position(receipt)>position(previous):
        published=instant(clock())
        if (published<instant(receipt['cloud_saved_at']) or published<instant(now)
                or published.astimezone(JST).date()!=now.astimezone(JST).date()):
            raise ValueError('PREDICTION_MANIFEST_CLOCK_INVALID')
        manifest={'schema_version':1,'race_id':race['race_id'],'request_id':identifier,
            'snapshot_id':receipt['snapshot']['snapshot_id'],'program_sha256':receipt['program_sha256'],
            'published_at':published.isoformat(timespec='microseconds')}
        put_verified(client,key,canonical(manifest),overwrite=True)
    served=read_prediction(race,client=client,now=instant(clock()),request_id=identifier)
    return {'status':'verified','race_id':race['race_id'],'request_id':identifier,
        'snapshot_id':served['snapshot']['snapshot_id'],'pathname':key,'sha256':digest(served),
        'cloud_saved_at':served['cloud_saved_at'],'cloud_eligible_pre_race':True,'models':len(served['snapshot']['models'])}
