"""Private current-race facts and immutable cloud ingestion receipts.

Only the serialized, pinned OIDC workflow may write. Blob SDK has no CAS.
A raw observation is written and read back before its server receipt time is
measured. Runner timestamps alone never establish durable pre-race evidence.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from api.today import https_url, unique_object, reject_constant, finite_float
from race_contract import canonical, validate_record, program_digest, stamp

MAX_BYTES = 256_000
REVIEW = 'user-confirmation-2026-10-15-official-facts'
KINDS = {'beforeinfo','odds3t','raceresult'}
JST = ZoneInfo('Asia/Tokyo')


def instant(value):
    return datetime.fromisoformat(stamp(value))


def checked_race_id(value, now):
    if (not isinstance(value,str) or not re.fullmatch(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',value)
            or value[:8]!=now.astimezone(JST).strftime('%Y%m%d')):
        raise ValueError('CURRENT_RACE_REQUIRED')
    return value


def find_program(feed, race_id, now):
    checked_race_id(race_id,now)
    matches=[race for venue in feed.get('venues',[]) for race in venue.get('races',[]) if race.get('race_id')==race_id]
    if len(matches)!=1:
        raise ValueError('RACE_NOT_IN_APPROVED_PROGRAM')
    return matches[0]


def paths(race_id, snapshot_id=None):
    if snapshot_id is None: return f'race-ai/races/{race_id}.json'
    if not isinstance(snapshot_id,str) or not re.fullmatch(r'[0-9a-f]{64}',snapshot_id):
        raise ValueError('SNAPSHOT_ID_INVALID')
    return (f'race-ai/observations/{race_id}/{snapshot_id}.json',
            f'race-ai/receipts/{race_id}/{snapshot_id}.json')


def read_blob(client, key):
    from vercel.blob import BlobNotFoundError
    try:
        result=client.get(key,access='private',use_cache=False,timeout=8)
    except BlobNotFoundError:
        return None
    if result is None: return None
    url=https_url(result.url)
    if (result.status_code!=200 or result.pathname!=key or url.path!='/'+key or url.query
            or not re.fullmatch(r'[A-Za-z0-9]+\.private\.blob\.vercel-storage\.com',url.hostname or '')
            or not isinstance(result.content_type,str) or result.content_type.split(';')[0].strip().lower()!='application/json'
            or not isinstance(result.content,bytes) or not 0<len(result.content)<=MAX_BYTES
            or type(result.size) is not int or not 0<=result.size<=MAX_BYTES):
        raise ValueError('RACE_STORE_RESPONSE_INVALID')
    return result.content


def decode(raw):
    value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_object,parse_constant=reject_constant,parse_float=finite_float)
    canonical(value)  # Validate output encoding, including escaped lone surrogates.
    return value


def put_verified(client,key,raw,*,overwrite):
    if not 0<len(raw)<=MAX_BYTES: raise ValueError('RACE_SNAPSHOT_TOO_LARGE')
    result=client.put(key,raw,access='private',content_type='application/json',add_random_suffix=False,overwrite=overwrite)
    if result.pathname!=key or read_blob(client,key)!=raw:
        raise ValueError('RACE_WRITE_READBACK_MISMATCH')


def validate_current_record(record, race, now):
    validate_record(record,race,now)
    day=now.astimezone(JST).date()
    if (record.get('rights_review')!=REVIEW or any(instant(record[key]).astimezone(JST).date()!=day for key in ('captured_at','saved_at'))):
        raise ValueError('RACE_REVIEW_OR_DAY_INVALID')


def checked_receipt(value,race,now):
    if not isinstance(value,dict) or set(value)!={'record','program_sha256','cloud_saved_at','cloud_eligible_pre_race'}:
        raise ValueError('RACE_RECEIPT_INVALID')
    record=value['record'];validate_current_record(record,race,now)
    saved=instant(value['cloud_saved_at'])
    eligible=record['storage_eligible_pre_race'] and saved<instant(race['closed_at'])
    if (value['program_sha256']!=program_digest(race) or not instant(record['saved_at'])<=saved<=instant(now)
            or saved.astimezone(JST).date()!=now.astimezone(JST).date()
            or type(value['cloud_eligible_pre_race']) is not bool or value['cloud_eligible_pre_race']!=eligible):
        raise ValueError('RACE_RECEIPT_TIME_OR_IDENTITY_INVALID')
    return value


def checked_manifest(value,race,now):
    fields={'schema_version','race_id','date_jst','closed_at','program_sha256','published_at','latest'}
    if (not isinstance(value,dict) or set(value)!=fields or type(value.get('schema_version')) is not int or value['schema_version']!=1
            or value['race_id']!=race['race_id'] or value['date_jst']!=now.astimezone(JST).date().isoformat()
            or instant(value['closed_at'])!=instant(race['closed_at']) or value['program_sha256']!=program_digest(race)
            or instant(value['published_at'])>instant(now)
            or instant(value['published_at']).astimezone(JST).date()!=now.astimezone(JST).date()
            or not isinstance(value['latest'],dict) or not 1<=len(value['latest'])<=3 or not set(value['latest'])<=KINDS):
        raise ValueError('RACE_MANIFEST_INVALID')
    for identifier in value['latest'].values(): paths(race['race_id'],identifier)
    if len(set(value['latest'].values()))!=len(value['latest']):raise ValueError('RACE_MANIFEST_DUPLICATE_ID')
    return value


def load_receipt(client,race,identifier,now):
    raw_key,receipt_key=paths(race['race_id'],identifier)
    raw,receipt_raw=read_blob(client,raw_key),read_blob(client,receipt_key)
    if raw is None or receipt_raw is None:raise ValueError('RACE_VERSION_MISSING')
    record=decode(raw);receipt=checked_receipt(decode(receipt_raw),race,now)
    if record.get('snapshot_id')!=identifier or canonical(record)!=canonical(receipt['record']):
        raise ValueError('RACE_VERSION_CONFLICT')
    return receipt


def read_current_race(race,*,client,now):
    checked_race_id(race['race_id'],now)
    raw=read_blob(client,paths(race['race_id']))
    if raw is None:return None
    manifest=checked_manifest(decode(raw),race,now)
    receipts=[]
    for kind,identifier in sorted(manifest['latest'].items()):
        receipt=load_receipt(client,race,identifier,now)
        if receipt['record']['kind']!=kind or instant(receipt['cloud_saved_at'])>instant(manifest['published_at']):
            raise ValueError('RACE_LATEST_IDENTITY_INVALID')
        receipts.append(receipt)
    served={**manifest,'records':receipts}
    if len(canonical(served))>MAX_BYTES:raise ValueError('RACE_API_RESPONSE_TOO_LARGE')
    return served


def publish_bundle(request,race,*,client,now,clock=None):
    checked_race_id(race['race_id'],now)
    clock=clock or (lambda:datetime.now(timezone.utc))
    if not isinstance(request,dict) or set(request)!={'publication_review','bundle'} or request['publication_review']!=REVIEW:
        raise ValueError('RACE_PUBLICATION_REVIEW_REQUIRED')
    bundle=request['bundle']
    if (not isinstance(bundle,dict) or set(bundle)!={'schema_version','race_id','records','latest'}
            or type(bundle['schema_version']) is not int or bundle['schema_version']!=1 or bundle['race_id']!=race['race_id']
            or not isinstance(bundle['records'],list) or not 1<=len(bundle['records'])<=3 or not isinstance(bundle['latest'],dict)):
        raise ValueError('RACE_BUNDLE_INVALID')
    incoming={}
    for record in bundle['records']:
        validate_current_record(record,race,now)
        kind=record['kind']
        if kind in incoming:raise ValueError('RACE_BATCH_DUPLICATE_KIND')
        incoming[kind]=record
    if bundle['latest']!={kind:record['snapshot_id'] for kind,record in incoming.items()}:
        raise ValueError('RACE_BUNDLE_LATEST_INVALID')
    if len(canonical(request))>MAX_BYTES:raise ValueError('RACE_BUNDLE_TOO_LARGE')
    previous=read_current_race(race,client=client,now=now)
    current={r['record']['kind']:r for r in previous['records']} if previous else {}
    accepted=[]
    for kind,record in sorted(incoming.items()):
        identifier=record['snapshot_id'];raw_key,receipt_key=paths(race['race_id'],identifier)
        raw=canonical(record);existing=read_blob(client,raw_key)
        if existing is None:put_verified(client,raw_key,raw,overwrite=False)
        elif existing!=raw:raise ValueError('RACE_IMMUTABLE_RECORD_CONFLICT')
        saved_raw=read_blob(client,receipt_key)
        if saved_raw is None:
            saved=instant(clock())
            if saved<instant(now) or saved.astimezone(JST).date()!=now.astimezone(JST).date():
                raise ValueError('CLOUD_SAVE_CLOCK_INVALID')
            receipt={'record':record,'program_sha256':program_digest(race),'cloud_saved_at':saved.isoformat(timespec='microseconds'),
                'cloud_eligible_pre_race':record['storage_eligible_pre_race'] and saved<instant(race['closed_at'])}
            checked_receipt(receipt,race,saved)
            put_verified(client,receipt_key,canonical(receipt),overwrite=False)
        else:
            receipt=checked_receipt(decode(saved_raw),race,instant(clock()))
            if canonical(receipt['record'])!=raw:raise ValueError('RACE_IMMUTABLE_RECEIPT_CONFLICT')
        accepted.append(identifier)
        old=current.get(kind)
        position=lambda r:(instant(r['record']['captured_at']),instant(r['record']['saved_at']))
        if old and position(old)==position(receipt) and old['record']['snapshot_id']!=identifier:
            raise ValueError('RACE_REVISION_TIME_AMBIGUOUS')
        if old is None or position(receipt)>position(old):current[kind]=receipt
    latest={kind:receipt['record']['snapshot_id'] for kind,receipt in sorted(current.items())}
    key=paths(race['race_id'])
    if previous is None or latest!=previous['latest']:
        # A receipt time is measured after durable observation readback. Manifest
        # time must cover every receipt even if a deterministic test clock stops.
        published=max([instant(clock()),*(instant(r['cloud_saved_at']) for r in current.values())])
        manifest={'schema_version':1,'race_id':race['race_id'],'date_jst':now.astimezone(JST).date().isoformat(),
            'closed_at':race['closed_at'],'program_sha256':program_digest(race),
            'published_at':published.isoformat(timespec='microseconds'),'latest':latest}
        checked_manifest(manifest,race,published)
        if len(canonical({**manifest,'records':list(current.values())}))>MAX_BYTES:
            raise ValueError('RACE_API_RESPONSE_TOO_LARGE')
        put_verified(client,key,canonical(manifest),overwrite=True)
    served=read_current_race(race,client=client,now=instant(clock()))
    return {'status':'verified','race_id':race['race_id'],'pathname':key,'accepted_snapshot_ids':accepted,
        'sha256':hashlib.sha256(canonical(served)).hexdigest(),'records':len(served['records'])}
