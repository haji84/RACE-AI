"""Immutable current-day BOATCAST numeric evidence, never source originals."""
from datetime import datetime,timezone
from api.race_store import canonical,decode,instant,read_blob,put_verified,checked_race_id,JST,MAX_BYTES
from api.prediction_store import request_identifier
from original_exhibition_contract import validate_original_receipt,validate_original_observation
from exhibition_contract import _clock,digest
from race_contract import program_digest

REVIEW='user-confirmation-2026-10-15-exhibition-private-analysis'


def manifest_key(race_id):return f'race-ai/original-exhibition/{race_id}.json'
def receipt_key(race_id,request_id):return f'race-ai/original-exhibition-receipts/{race_id}/{request_identifier(request_id)}.json'
def version_key(race_id,snapshot_id):
    import re
    if not isinstance(snapshot_id,str) or re.fullmatch(r'[0-9a-f]{64}',snapshot_id) is None:raise ValueError('ORIGINAL_SNAPSHOT_INVALID')
    return f'race-ai/original-exhibition-versions/{race_id}/{snapshot_id}.json'


def load_receipt(race,request_id,*,client,now):
    raw=read_blob(client,receipt_key(race['race_id'],request_id))
    if raw is None:return None
    receipt=decode(raw);validate_original_receipt(receipt,race,now)
    if receipt['request_id']!=request_id or read_blob(client,version_key(race['race_id'],receipt['observation']['snapshot_id']))!=canonical(receipt['observation']):
        raise ValueError('ORIGINAL_IMMUTABLE_CONFLICT')
    return receipt


def read_original_exhibition(race,*,client,now,request_id=None):
    now,day,_=_clock(now,race);checked_race_id(race['race_id'],now)
    if request_id is not None:return load_receipt(race,request_id,client=client,now=now)
    raw=read_blob(client,manifest_key(race['race_id']))
    if raw is None:return None
    value=decode(raw)
    if (not isinstance(value,dict) or set(value)!={'schema_version','race_id','request_id','snapshot_id','program_identity_sha256','published_at'}
        or type(value['schema_version']) is not int or value['schema_version']!=1 or value['race_id']!=race['race_id']
        or value['program_identity_sha256']!=program_digest(race) or instant(value['published_at'])>now
        or instant(value['published_at']).astimezone(JST).date()!=day):raise ValueError('ORIGINAL_MANIFEST_INVALID')
    receipt=load_receipt(race,value['request_id'],client=client,now=now)
    if receipt is None or value['snapshot_id']!=receipt['observation']['snapshot_id'] or instant(value['published_at'])<instant(receipt['cloud_saved_at']):
        raise ValueError('ORIGINAL_MANIFEST_CONFLICT')
    return receipt


def publish_original_exhibition(request,race,*,client,now,clock=None):
    now,day,closed=_clock(now,race);checked_race_id(race['race_id'],now)
    clock=clock or (lambda:datetime.now(timezone.utc))
    if (not isinstance(request,dict) or set(request)!={'publication_review','race_id','request_id','observation','runner_saved_at'}
        or request['publication_review']!=REVIEW or request['race_id']!=race['race_id'] or len(canonical(request))>MAX_BYTES):
        raise ValueError('ORIGINAL_PUBLICATION_INVALID')
    identifier=request_identifier(request['request_id']);observation=request['observation']
    validate_original_observation(observation,race,now)
    runner=instant(request['runner_saved_at'])
    probe=dict(schema_version=1,request_id=identifier,observation=observation,runner_saved_at=request['runner_saved_at'],
        cloud_saved_at=now.isoformat(timespec='microseconds'),cloud_eligible_pre_race=observation['capture_eligible_pre_race'] and runner<closed and now<closed,
        program_identity_sha256=program_digest(race))
    validate_original_receipt(probe,race,now)
    previous=read_original_exhibition(race,client=client,now=now)
    receipt=load_receipt(race,identifier,client=client,now=now)
    if receipt is not None:
        if canonical(receipt['observation'])!=canonical(observation) or instant(receipt['runner_saved_at'])!=runner:
            raise ValueError('ORIGINAL_NONCE_CONFLICT')
    else:
        raw=canonical(observation);key=version_key(race['race_id'],observation['snapshot_id']);existing=read_blob(client,key)
        if existing is None:put_verified(client,key,raw,overwrite=False)
        elif existing!=raw:raise ValueError('ORIGINAL_IMMUTABLE_CONFLICT')
        saved,_,_=_clock(clock(),race)
        if saved<now:raise ValueError('ORIGINAL_CLOUD_CLOCK_INVALID')
        receipt={**probe,'cloud_saved_at':saved.isoformat(timespec='microseconds'),
            'cloud_eligible_pre_race':observation['capture_eligible_pre_race'] and runner<closed and saved<closed}
        validate_original_receipt(receipt,race,saved)
        put_verified(client,receipt_key(race['race_id'],identifier),canonical(receipt),overwrite=False)
    position=lambda r:(max(instant(s['captured_at']) for s in r['observation']['sources']),instant(r['runner_saved_at']),instant(r['cloud_saved_at']),r['request_id'])
    key=manifest_key(race['race_id'])
    if previous is None or position(receipt)>position(previous):
        published,_,_=_clock(clock(),race)
        if published<instant(receipt['cloud_saved_at']) or published<now:raise ValueError('ORIGINAL_MANIFEST_CLOCK_INVALID')
        value=dict(schema_version=1,race_id=race['race_id'],request_id=identifier,snapshot_id=observation['snapshot_id'],
            program_identity_sha256=program_digest(race),published_at=published.isoformat(timespec='microseconds'))
        put_verified(client,key,canonical(value),overwrite=True)
    served=read_original_exhibition(race,client=client,now=clock(),request_id=identifier)
    return dict(status='verified',race_id=race['race_id'],request_id=identifier,snapshot_id=served['observation']['snapshot_id'],
        pathname=key,sha256=digest(served),runner_saved_at=served['runner_saved_at'],cloud_saved_at=served['cloud_saved_at'],
        cloud_eligible_pre_race=served['cloud_eligible_pre_race'],program_identity_sha256=served['program_identity_sha256'])
