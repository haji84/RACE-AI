"""Separate immutable post-exhibition-original forecasts; B-only objects are read-only."""
from datetime import datetime, timezone

from api import prediction_store as baseline_store
from api import race_store
from api import original_exhibition_store as original_store
from api.race_store import (REVIEW, JST, MAX_BYTES, canonical, decode, instant,
    checked_race_id, read_blob, put_verified)
from api.prediction_store import request_identifier
from exhibition_contract import digest,ExhibitionUnavailable,_clock
from original_prediction_contract import build_original_prediction_bundle,validate_original_prediction_bundle
from race_contract import program_digest

UTC = timezone.utc


def manifest_key(race_id):
    return f'race-ai/post-exhibition-original/{race_id}.json'


def receipt_key(race_id, request_id):
    return f'race-ai/post-exhibition-original-receipts/{race_id}/{request_identifier(request_id)}.json'


def version_key(race_id, snapshot_id):
    import re
    if not isinstance(snapshot_id,str) or re.fullmatch(r'[0-9a-f]{64}',snapshot_id) is None:
        raise ValueError('EXHIBITION_SNAPSHOT_ID_INVALID')
    return f'race-ai/post-exhibition-original-versions/{race_id}/{snapshot_id}.json'


def checked_receipt(value, race, now, *, client):
    clock, day, closed = _clock(now, race)
    fields = {'schema_version','request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race','program_identity_sha256'}
    if (not isinstance(value,dict) or set(value)!=fields or type(value['schema_version']) is not int
            or value['schema_version']!=1 or value['cloud_eligible_pre_race'] is not True
            or value['program_identity_sha256']!=program_digest(race) or len(canonical(value))>MAX_BYTES):
        raise ValueError('EXHIBITION_RECEIPT_INVALID')
    request_identifier(value['request_id'])
    snapshot=value['snapshot']
    baseline=baseline_store.read_prediction(race,client=client,now=clock,request_id=snapshot['baseline_link']['request_id'])
    preview=race_store.load_receipt(client,race,snapshot['beforeinfo_link']['snapshot_id'],clock)
    original=original_store.read_original_exhibition(race,client=client,now=clock,request_id=snapshot['original_link']['request_id'])
    validate_original_prediction_bundle(snapshot,baseline,preview,original,race,clock)
    saved=instant(value['cloud_saved_at'])
    if not (instant(snapshot['generated_at'])<=saved<closed and saved<=clock and saved.astimezone(JST).date()==day):
        raise ValueError('EXHIBITION_RECEIPT_TIME_INVALID')
    return value


def load_receipt(race, request_id, *, client, now):
    raw=read_blob(client,receipt_key(race['race_id'],request_id))
    if raw is None:
        return None
    receipt=checked_receipt(decode(raw),race,now,client=client)
    snapshot=receipt['snapshot']
    stored=read_blob(client,version_key(race['race_id'],snapshot['snapshot_id']))
    if receipt['request_id']!=request_id or stored!=canonical(snapshot):
        raise ValueError('EXHIBITION_VERSION_CONFLICT')
    return receipt


def read_original_prediction(race, *, client, now, request_id=None):
    clock, day, _ = _clock(now,race)
    checked_race_id(race['race_id'],clock)
    if request_id is not None:
        return load_receipt(race,request_id,client=client,now=clock)
    raw=read_blob(client,manifest_key(race['race_id']))
    if raw is None:
        return None
    value=decode(raw)
    fields={'schema_version','race_id','request_id','snapshot_id','program_identity_sha256','published_at'}
    if (not isinstance(value,dict) or set(value)!=fields or type(value['schema_version']) is not int
            or value['schema_version']!=1 or value['race_id']!=race['race_id']
            or value['program_identity_sha256']!=program_digest(race)
            or instant(value['published_at'])>clock or instant(value['published_at']).astimezone(JST).date()!=day):
        raise ValueError('EXHIBITION_MANIFEST_INVALID')
    receipt=load_receipt(race,value['request_id'],client=client,now=clock)
    if (receipt is None or value['snapshot_id']!=receipt['snapshot']['snapshot_id']
            or value['program_identity_sha256']!=receipt['program_identity_sha256']
            or instant(value['published_at'])<instant(receipt['cloud_saved_at'])):
        raise ValueError('EXHIBITION_MANIFEST_CONFLICT')
    return receipt


def publish_original_prediction(request, race, *, client, now, clock=None):
    now, day, closed = _clock(now,race)
    checked_race_id(race['race_id'],now)
    clock=clock or (lambda:datetime.now(UTC))
    if (not isinstance(request,dict) or set(request)!={'publication_review','race_id','request_id'}
            or request['publication_review']!=REVIEW or request['race_id']!=race['race_id']):
        raise ValueError('EXHIBITION_REQUEST_INVALID')
    identifier=request_identifier(request['request_id'])
    previous=read_original_prediction(race,client=client,now=now)
    receipt=load_receipt(race,identifier,client=client,now=now)
    if receipt is None:
        if now>=closed:
            raise ExhibitionUnavailable('CUTOFF_PASSED')
        baseline=baseline_store.read_prediction(race,client=client,now=now)
        observations=race_store.read_current_race(race,client=client,now=now)
        original=original_store.read_original_exhibition(race,client=client,now=now)
        snapshot=build_original_prediction_bundle(baseline,observations,original,race,now)
        raw=canonical(snapshot); key=version_key(race['race_id'],snapshot['snapshot_id'])
        existing=read_blob(client,key)
        if existing is None:
            put_verified(client,key,raw,overwrite=False)
        elif existing!=raw:
            raise ValueError('EXHIBITION_IMMUTABLE_CONFLICT')
        # Measure only after immutable forecast durable readback, never reuse a
        # runner/client claim or backdate an orphan that crossed closing time.
        saved, saved_day, _ = _clock(clock(),race)
        if saved<now or saved>=closed or saved_day!=day:
            raise ValueError('EXHIBITION_SAVED_AFTER_CUTOFF')
        receipt=dict(schema_version=1,request_id=identifier,snapshot=snapshot,
            cloud_saved_at=saved.isoformat(timespec='microseconds'),cloud_eligible_pre_race=True,
            program_identity_sha256=program_digest(race))
        checked_receipt(receipt,race,saved,client=client)
        put_verified(client,receipt_key(race['race_id'],identifier),canonical(receipt),overwrite=False)
    position=lambda row:(instant(row['snapshot']['generated_at']),instant(row['cloud_saved_at']),row['request_id'])
    key=manifest_key(race['race_id'])
    if previous is None or position(receipt)>position(previous):
        published, published_day, _ = _clock(clock(),race)
        if published<instant(receipt['cloud_saved_at']) or published<now or published_day!=day:
            raise ValueError('EXHIBITION_MANIFEST_CLOCK_INVALID')
        manifest=dict(schema_version=1,race_id=race['race_id'],request_id=identifier,
            snapshot_id=receipt['snapshot']['snapshot_id'],program_identity_sha256=receipt['program_identity_sha256'],
            published_at=published.isoformat(timespec='microseconds'))
        put_verified(client,key,canonical(manifest),overwrite=True)
    served=read_original_prediction(race,client=client,now=clock(),request_id=identifier)
    return dict(status='verified',variant='original-v1',original_request_id=served['snapshot']['original_link']['request_id'],
        original_snapshot_id=served['snapshot']['original_link']['snapshot_id'],race_id=race['race_id'],request_id=identifier,
        snapshot_id=served['snapshot']['snapshot_id'],pathname=key,sha256=digest(served),
        cloud_saved_at=served['cloud_saved_at'],cloud_eligible_pre_race=True,models=1,
        program_identity_sha256=served['program_identity_sha256'],
        baseline_snapshot_id=served['snapshot']['baseline_link']['snapshot_id'],
        beforeinfo_snapshot_id=served['snapshot']['beforeinfo_link']['snapshot_id'],
        research_only=True,validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
