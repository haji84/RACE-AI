"""Exact Actions originals and raw captures on the fixed encrypted vault ref.

All private bytes, including legacy clear ZIPs and the exact metadata response,
are inside an owner-key AEAD envelope. Git stores bounded ciphertext chunks,
immutable batch descriptors and authenticated bounded indexes. No source or
Actions API request occurs here. An archived receipt is never a current live
receipt and Git timestamps never supply an original save time.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from urllib.parse import parse_qsl, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .boat_pdca_github_handoff import GitStateRepository, TRANSFER_REF, REPO
from .boat_pdca_state import state_key
from . import boat_private_original_archive as native

SCHEMA = 'RACE_AI_BOAT_PRIVATE_ORIGINAL_VAULT_V1'
LOCATOR = 'RACE_AI_BOAT_PRIVATE_ORIGINAL_LOCATOR_V1'
VAULT_REF = 'state/boat-private-originals'
_REFS = frozenset((VAULT_REF,TRANSFER_REF))
PREFIX = 'state/boat-private-originals/v1/'
DOMAIN = SCHEMA.encode('ascii')
REPO_ID = '1416489937'
MAGIC = b'RABOV1\0\0'
CHUNK_BYTES = 8*1024*1024
MAX_ORIGINAL = 160*1024*1024
MAX_METADATA = 128*1024
MAX_PLAIN = 320*1024*1024
MAX_BATCH_PLAIN = 512*1024*1024
MAX_INDEX = 4*1024*1024
MAX_BATCH = 128
MAX_CHUNKS = 48
MAX_RUN_ENTRIES = 512
MAX_MONTH_RUNS = 2048
MAX_MONTH_ENTRIES = 32768
MAX_MONTH_CIPHER_BYTES = 32*1024*1024*1024
LOOKUP_SPAN = 10000
JST = timezone(timedelta(hours=9))
KINDS = frozenset(('P0', 'P1', 'RESULT', 'CONTINUITY', 'ALL_MODEL', 'SOURCE_CONTROL'))
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_HEAD = re.compile(r'[a-f0-9]{40}\Z')
_MONTH = re.compile(r'\d{4}-(?:0[1-9]|1[0-2])\Z')
_MEMBER = re.compile(r'(?:original\.zip|metadata\.json|continuity\.zip|continuity\.metadata\.json|capture-[0-9]{4}\.(?:raw|json))\Z')


def _need(value, reason):
    if not value:
        raise ValueError('VAULT_'+reason)


def _sha(raw):
    return sha256(raw).hexdigest()


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise ValueError('VAULT_JSON_INVALID') from None


def _json(raw, limit=MAX_INDEX):
    _need(type(raw) is bytes and 0 < len(raw) <= limit, 'JSON_BOUND_INVALID')
    def unique(items):
        value = {}
        for name, child in items:
            _need(name not in value, 'DUPLICATE_JSON_KEY')
            value[name] = child
        return value
    def nonfinite(_):
        raise ValueError('VAULT_JSON_NONFINITE')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=nonfinite)
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('VAULT_JSON_INVALID') from None


def _hex(value, pattern=_SHA):
    _need(type(value) is str and pattern.fullmatch(value), 'IDENTITY_INVALID')
    return value


def _id(value):
    _need(type(value) is int and 0 < value < 10**20, 'ARTIFACT_ID_INVALID')
    return value


def _time(value):
    try:
        _need(type(value) is str and len(value) <= 64, 'CLOCK_INVALID')
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(parsed.utcoffset() is not None, 'CLOCK_INVALID')
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise ValueError('VAULT_CLOCK_INVALID') from None


def _month(value):
    _need(type(value) is str and _MONTH.fullmatch(value), 'MONTH_INVALID')
    return value


def _keys(key):
    root = state_key('production', key)
    def derive(purpose):
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=REPO_ID.encode('ascii'),
                    info=DOMAIN+b'\0'+purpose).derive(root)
    return derive(b'encryption'), derive(b'index-authentication')


def _signed(value, mac_key):
    return _wire(dict(state=value, mac=hmac.digest(mac_key, _wire(value), 'sha256').hex()))+b'\n'


def _unsigned(raw, mac_key):
    value = _json(raw)
    _need(type(value) is dict and set(value) == {'state', 'mac'}
          and type(value['state']) is dict, 'INDEX_INVALID')
    _hex(value['mac'])
    _need(hmac.compare_digest(value['mac'], hmac.digest(mac_key, _wire(value['state']), 'sha256').hex()),
          'INDEX_AUTHENTICATION_FAILED')
    _need(_signed(value['state'], mac_key) == raw, 'INDEX_NONCANONICAL')
    return value['state']


class VaultGitRepository(GitStateRepository):
    """Existing Git guards with shallow metadata and on-demand encrypted blobs.

    A fresh readback must not download every historical ciphertext. The fixed
    vault ref isolates new writers from legacy transfer-ref source workers.
    GitHub's blob filter retains its exact commit/tree identity;
    cat-file/show retrieve only the requested missing blobs from the same
    authenticated origin. Git may record standard local promisor/filter
    bookkeeping; credential helpers, auth headers and origin URLs are untouched.
    """
    def __init__(self,repo,*,ref=VAULT_REF):
        _need(ref in _REFS,'REF_REQUIRED')
        # Keep the canonical state publisher's ref allowlist unchanged.
        self.ref=ref;self.repo=Path(repo).resolve()
        self._reject_rewrites();self._check_remote()

    def _run(self,args,*,body=None,env=None):
        if args and args[0] in ('ls-remote','fetch','push'):
            self._reject_rewrites(env)
        return super()._run(['-c','remote.origin.promisor=true',
            '-c','remote.origin.partialclonefilter=blob:none','-c','protocol.version=2',*args],body=body,env=env)

    def fetch(self,commit):
        _hex(commit,_HEAD)
        self._run(['fetch','--no-tags','--no-write-fetch-head','--depth=1','--filter=blob:none',
            self.fetch_url,commit+':refs/race-ai/pinned-state/'+commit])

    def exists(self,commit,path):
        _hex(commit,_HEAD)
        _need(type(path) is str and path and not any(char in path for char in ('\0','\n','\r','\t')),
              'GIT_PATH_INVALID')
        raw = self._run(['ls-tree','-z',commit,'--',path])
        if not raw: return False
        _need(raw.count(b'\0') == 1 and raw.endswith(b'\t'+path.encode('utf-8')+b'\0'),
              'GIT_PATH_IDENTITY_INVALID')
        return True


def _transport(repo, transport):
    git = transport if transport is not None else VaultGitRepository(repo)
    _need(git.ref in _REFS, 'REF_REQUIRED')
    return git


def refresh_parent(git,expected_parent):
    """Accept only a verified descendant, walking at most 64 commit headers.

    Shallow commits still contain actual parent IDs, so no merge-base inference
    or full-history/blob download is needed. Missing refs, rewinds, divergence,
    metadata failures and an exhausted ancestry bound are stop conditions.
    """
    _need(git.ref in _REFS,'REF_REQUIRED');_hex(expected_parent,_HEAD)
    current=git.head();_need(current is not None,'REF_CONCURRENT_UPDATE_OR_MISSING')
    _hex(current,_HEAD)
    if current==expected_parent:return current
    pending=[current];seen=set()
    while pending and len(seen)<64:
        commit=pending.pop(0)
        if commit==expected_parent:return current
        if commit in seen:continue
        seen.add(commit);git.fetch(commit)
        _need(git._run(['cat-file','-t',commit]).strip()==b'commit','PARENT_REFRESH_ANCESTRY_UNVERIFIED')
        size=int(git._run(['cat-file','-s',commit]))
        _need(0<size<=1024*1024,'PARENT_REFRESH_ANCESTRY_UNVERIFIED')
        raw=git._run(['cat-file','-p',commit])
        _need(len(raw)==size,'PARENT_REFRESH_ANCESTRY_UNVERIFIED')
        for line in raw.split(b'\n\n',1)[0].splitlines():
            if line.startswith(b'parent '):
                try:parent=line[7:].decode('ascii')
                except UnicodeError:raise ValueError('VAULT_PARENT_REFRESH_ANCESTRY_UNVERIFIED') from None
                _hex(parent,_HEAD)
                if parent==expected_parent:return current
                if parent not in seen and parent not in pending:pending.append(parent)
        _need(len(seen)+len(pending)<=64,'PARENT_REFRESH_ANCESTRY_UNVERIFIED')
    raise ValueError('VAULT_PARENT_REFRESH_ANCESTRY_UNVERIFIED')


def _read(git, commit, path, limit):
    try:
        return git.read(commit, path, limit)
    except (ValueError, OSError, subprocess.SubprocessError):
        raise ValueError('VAULT_RETAINED_BYTES_MISSING_OR_INVALID') from None


def _index(git, parent, path, shape, mac_key):
    if not git.exists(parent, path):
        return dict(schema=SCHEMA, repository_id=REPO_ID, **shape)
    value = _unsigned(_read(git, parent, path, MAX_INDEX), mac_key)
    _need(set(value) == {'schema', 'repository_id', *shape}
          and value['schema'] == SCHEMA and value['repository_id'] == REPO_ID, 'INDEX_SCOPE_INVALID')
    for name, expected in shape.items():
        if name in ('entries', 'cipher_bytes') and type(expected) is int:
            _need(type(value[name]) is int and value[name] >= 0, 'INDEX_COUNT_INVALID')
        elif type(expected) is not dict:
            _need(value[name] == expected, 'INDEX_SCOPE_INVALID')
        else:
            _need(type(value[name]) is dict, 'INDEX_ENTRIES_INVALID')
    return value


def _kind(metadata):
    name = metadata.get('name'); run = metadata['workflow_run']['id']
    from .repeated_cycle import matches
    for kind, prefix in native.PREFIXES.items():
        if (name == f'{prefix}-{run}' if kind == 'CONTINUITY' else matches(name, f'{prefix}-{run}')):
            return kind
    if type(name) is str and re.fullmatch(f'boat-all-model-forecasts-{run}-r(?:0|[1-9][0-9]{{0,5}})', name):
        return 'ALL_MODEL'
    if name == f'race-source-control-{run}':
        return 'SOURCE_CONTROL'
    raise ValueError('VAULT_ARTIFACT_NAME_INVALID')


def _artifact(raw, metadata_raw, *, key, now, expected_kind=None, companion=None):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ORIGINAL, 'ORIGINAL_BOUND_INVALID')
    metadata = _json(metadata_raw, MAX_METADATA)
    _need(type(metadata) is dict and metadata.get('expired') is False, 'ARTIFACT_STATUS_INVALID')
    _id(metadata.get('id'))
    run = metadata.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int and 0 < run['id'] < 10**20
          and all(type(run.get(name)) is int and run[name] == int(REPO_ID)
                  for name in ('repository_id', 'head_repository_id')), 'ARTIFACT_REPOSITORY_INVALID')
    _hex(run.get('head_sha'), _HEAD)
    _need(metadata.get('digest') == 'sha256:'+_sha(raw)
          and type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes'] == len(raw),
          'ARTIFACT_DIGEST_INVALID')
    created = _time(metadata.get('created_at'))
    _need(created <= now < _time(metadata.get('expires_at')), 'ARTIFACT_CLOCK_INVALID')
    kind = _kind(metadata)
    _need(expected_kind is None or expected_kind == kind, 'ARTIFACT_KIND_INVALID')
    # Decrypt and use the existing phase checks. Retention cannot make an
    # unsupported forecast valid or manufacture a source-control receipt.
    if kind in ('P0', 'P1'):
        from .frozen_day_cycle import archive_json, read_p1
        if kind == 'P0':
            from .cycle_recovery import p0_original_or_empty, _day
            document, _ = archive_json(raw, metadata, 'forecasts.json', f'boat-p0-existing-{run["id"]}')
            p0_original_or_empty(raw, metadata, _day(document.get('day_jst')))
        else:
            read_p1(raw, metadata)
    elif kind == 'RESULT':
        from .cycle_recovery import _result_day, result_archive
        result_archive(raw, metadata, _result_day(raw, metadata))
    elif kind == 'CONTINUITY':
        from .cycle_recovery import authenticated_source_control
        _need(authenticated_source_control(raw, metadata, expected_run=run['id']) is not None,
              'CONTINUITY_CONTROL_REQUIRED')
    elif kind == 'ALL_MODEL':
        from . import boat_all_model_store as store
        from .boat_all_model_cycle import project_round
        from .actions_contract import digest
        with native._checked_zip(raw, max_zip_bytes=40*1024*1024, max_expanded=store.MAX_WIRE) as archive:
            _need(archive.namelist() == ['forecasts.enc'], 'ALL_MODEL_MEMBERS_INVALID')
            cipher = archive.read('forecasts.enc')
        header = store.forecast_header(cipher)
        _need(header['run_id'] == str(run['id']) and metadata['name'] ==
              f'boat-all-model-forecasts-{run["id"]}-r{header["round_no"]}', 'ALL_MODEL_RUN_ROUND_INVALID')
        payload = store.open_forecasts(cipher, key=key)
        _need(payload.get('source_code_commit') == run['head_sha'] and str(payload.get('run_id')) == str(run['id']),
              'ALL_MODEL_HEAD_INVALID')
        project_round(payload, dict(repository_id=REPO_ID, repository=REPO, run_id=str(run['id']),
            head_sha=run['head_sha'], artifact_id=metadata['id'], created_at=metadata['created_at'],
            payload_sha256=digest(payload), independently_verified=True))
    else:
        from .boat_source_control import read_summary
        _need(type(companion) in (tuple, list) and len(companion) == 2, 'CONTINUITY_COMPANION_REQUIRED')
        continuity_raw, continuity_metadata_raw = companion
        continuity = _artifact(continuity_raw, continuity_metadata_raw, key=key, now=now,
                               expected_kind='CONTINUITY')
        read_summary(raw, metadata, continuity_raw, continuity['metadata'], run_id=run['id'], head_sha=run['head_sha'])
    files = {'original.zip':raw, 'metadata.json':metadata_raw}
    if kind == 'SOURCE_CONTROL':
        files.update({'continuity.zip':companion[0], 'continuity.metadata.json':companion[1]})
    summary = dict(kind=kind, artifact_id=metadata['id'], run_id=run['id'], head_sha=run['head_sha'],
                   created_at=metadata['created_at'], month=created.astimezone(JST).strftime('%Y-%m'))
    return dict(files=files, summary=summary, metadata=metadata)


def _capture_record(captures, *, run_id, head_sha, now):
    _id(run_id); _hex(head_sha, _HEAD)
    _need(type(captures) in (list, tuple) and 0 < len(captures) <= 240, 'CAPTURE_COUNT_INVALID')
    files = {}; seen = set(); total = 0
    for number, pair in enumerate(captures):
        _need(type(pair) in (list, tuple) and len(pair) == 2, 'CAPTURE_PAIR_INVALID')
        raw, metadata_raw = pair
        _need(type(raw) is bytes and 0 < len(raw) <= 4*1024*1024, 'CAPTURE_BOUND_INVALID')
        metadata = _json(metadata_raw, 16384)
        _need(type(metadata) is dict and metadata.get('http_status') == 200
              and metadata.get('source_sha256') == _sha(raw), 'CAPTURE_RECEIPT_INVALID')
        url = metadata.get('source_url')
        _need(_capture_url(url), 'CAPTURE_SOURCE_INVALID')
        _need(_time(metadata.get('captured_at')) <= now, 'CAPTURE_CLOCK_INVALID')
        identity = (url, metadata['captured_at'])
        _need(identity not in seen, 'CAPTURE_DUPLICATE')
        seen.add(identity); total += len(raw)+len(metadata_raw)
        _need(total <= MAX_PLAIN, 'CAPTURE_TOTAL_BOUND_INVALID')
        files[f'capture-{number:04d}.raw'] = raw
        files[f'capture-{number:04d}.json'] = metadata_raw
    summary = dict(kind='SOURCE_CAPTURES', artifact_id=None, run_id=run_id, head_sha=head_sha,
                   created_at=None, month=now.astimezone(JST).strftime('%Y-%m'), capture_count=len(captures))
    return dict(files=files, summary=summary)


def _capture_url(url):
    if type(url) is not str or len(url) > 2048:
        return False
    if re.fullmatch(r'https://www\.boatrace\.jp/owpc/pc/race/raceresult\?rno=(?:[1-9]|1[0-2])&jcd=(?:0[1-9]|1[0-9]|2[0-4])&hd=[0-9]{8}', url):
        return True
    archive=re.fullmatch(r'https://www1\.mbrace\.or\.jp/od2/B/([0-9]{4})([0-9]{2})/b([0-9]{2})([0-9]{2})([0-9]{2})\.lzh',url)
    if archive:
        from datetime import date
        from scripts.existing_day_program import official_url
        try:
            day=date(int(archive[1]),int(archive[2]),int(archive[5]))
        except ValueError:
            return False
        return official_url(day,'B')==url
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'api.github.com' or parsed.fragment:
        return False
    if not re.fullmatch(r'/repos/haji84/RACE-AI/actions/(?:runs/[1-9][0-9]*(?:/artifacts)?|artifacts/[1-9][0-9]*|workflows/[1-9][0-9]*/runs)', parsed.path):
        return False
    query = parse_qsl(parsed.query, keep_blank_values=True)
    return len(query) <= 2 and len({name for name, _ in query}) == len(query) and all(
        name in ('per_page','page') and re.fullmatch(r'[1-9][0-9]{0,5}', value)
        and (name != 'per_page' or int(value) <= 100) for name, value in query)


def _file_inventory(files):
    _need(type(files) is dict and 0 < len(files) <= 480, 'FILES_INVALID')
    out = {}; total = 0
    for name, raw in sorted(files.items()):
        _need(type(name) is str and _MEMBER.fullmatch(name) and type(raw) is bytes
              and 0 < len(raw) <= MAX_ORIGINAL, 'FILE_BOUND_INVALID')
        total += len(raw); _need(total <= MAX_PLAIN, 'PLAIN_TOTAL_BOUND_INVALID')
        out[name] = dict(size=len(raw), sha256=_sha(raw))
    return out


def _seal(record, now, encryption_key):
    files = record['files']; inventory = _file_inventory(files)
    header = dict(schema=SCHEMA, repository_id=REPO_ID, purpose='private-original-vault',
                  archived_at=now.isoformat(), summary=record['summary'], files=inventory)
    encoded = _wire(header); _need(len(encoded) <= MAX_INDEX//2, 'HEADER_BOUND_INVALID')
    plain = b''.join(files[name] for name in sorted(files)); nonce = os.urandom(12)
    raw = MAGIC+struct.pack('>I', len(encoded))+encoded+nonce+AESGCM(encryption_key).encrypt(
        nonce, plain, DOMAIN+b'\0'+encoded+nonce)
    chunks = [raw[start:start+CHUNK_BYTES] for start in range(0, len(raw), CHUNK_BYTES)]
    _need(0 < len(chunks) <= MAX_CHUNKS and 0 < CHUNK_BYTES <= 8*1024*1024, 'CHUNK_BOUND_INVALID')
    month = header['summary']['month']
    locations = [dict(path=PREFIX+month+'/chunks/'+_sha(chunk)+'.enc', size=len(chunk), sha256=_sha(chunk))
                 for chunk in chunks]
    entry = dict(header=header, cipher_sha256=_sha(raw), cipher_size=len(raw), chunks=locations)
    return entry, {location['path']:chunk for location, chunk in zip(locations, chunks)}


def _entry(value):
    _need(type(value) is dict and set(value) == {'header','cipher_sha256','cipher_size','chunks'}, 'ENTRY_INVALID')
    _hex(value['cipher_sha256'])
    _need(type(value['cipher_size']) is int and 0 < value['cipher_size'] <= MAX_PLAIN+MAX_INDEX,
          'CIPHER_BOUND_INVALID')
    header = value['header']
    _need(type(header) is dict and set(header) == {'schema','repository_id','purpose','archived_at','summary','files'}
          and header['schema'] == SCHEMA and header['repository_id'] == REPO_ID
          and header['purpose'] == 'private-original-vault', 'HEADER_SCOPE_INVALID')
    _time(header['archived_at']); summary = header['summary']
    _need(type(summary) is dict and summary.get('kind') in KINDS | {'SOURCE_CAPTURES'}, 'SUMMARY_INVALID')
    required = {'kind','artifact_id','run_id','head_sha','created_at','month'}
    if summary['kind'] == 'SOURCE_CAPTURES':
        required.add('capture_count')
        _need(summary['artifact_id'] is None and summary['created_at'] is None
              and type(summary.get('capture_count')) is int and 0 < summary['capture_count'] <= 240,
              'CAPTURE_SUMMARY_INVALID')
    else:
        _id(summary.get('artifact_id')); _time(summary.get('created_at'))
    _need(set(summary) == required, 'SUMMARY_FIELDS_INVALID')
    _id(summary.get('run_id')); _hex(summary.get('head_sha'), _HEAD); _month(summary.get('month'))
    inventory = header['files']
    _need(type(inventory) is dict and 0 < len(inventory) <= 480, 'FILE_INVENTORY_INVALID')
    total = 0
    for name, item in inventory.items():
        _need(type(name) is str and _MEMBER.fullmatch(name) and type(item) is dict
              and set(item) == {'size','sha256'} and type(item['size']) is int
              and 0 < item['size'] <= MAX_ORIGINAL, 'FILE_INVENTORY_INVALID')
        _hex(item['sha256']); total += item['size']
    _need(total <= MAX_PLAIN, 'PLAIN_TOTAL_BOUND_INVALID')
    _need(type(value['chunks']) is list and 0 < len(value['chunks']) <= MAX_CHUNKS, 'CHUNKS_INVALID')
    total = 0
    for chunk in value['chunks']:
        _need(type(chunk) is dict and set(chunk) == {'path','size','sha256'}
              and type(chunk['size']) is int and 0 < chunk['size'] <= 8*1024*1024, 'CHUNK_INVALID')
        ident = _hex(chunk['sha256'])
        _need(chunk['path'] == PREFIX+summary['month']+'/chunks/'+ident+'.enc', 'CHUNK_PATH_INVALID')
        total += chunk['size']
    _need(total == value['cipher_size'], 'CIPHER_SIZE_INVALID')
    return value


def _reference(batch_path, batch_sha, entry):
    summary = entry['header']['summary']
    return dict(batch_path=batch_path, batch_sha256=batch_sha, entry_sha256=_sha(_wire(entry)),
                artifact_id=summary['artifact_id'], kind=summary['kind'])


def _ref(value):
    _need(type(value) is dict and set(value) == {'batch_path','batch_sha256','entry_sha256','artifact_id','kind'}, 'REFERENCE_INVALID')
    digest = _hex(value['batch_sha256']); _hex(value['entry_sha256'])
    _need(type(value['batch_path']) is str and re.fullmatch(re.escape(PREFIX)+r'\d{4}-(?:0[1-9]|1[0-2])/batches/'+digest+r'\.json', value['batch_path']),
          'BATCH_PATH_INVALID')
    _need(value['kind'] in KINDS | {'SOURCE_CAPTURES'}, 'REFERENCE_KIND_INVALID')
    if value['kind'] == 'SOURCE_CAPTURES': _need(value['artifact_id'] is None, 'REFERENCE_ID_INVALID')
    else: _id(value['artifact_id'])
    return value


def _locator(commit, reference, *, ref=VAULT_REF):
    _hex(commit, _HEAD); _ref(reference)
    _need(ref in _REFS,'REF_REQUIRED')
    return dict(schema=LOCATOR, status='READY', repository_id=REPO_ID, ref=ref,
                source_commit=commit, **reference)


def _validate_locator(locator):
    _need(type(locator) is dict and set(locator) == {'schema','status','repository_id','ref','source_commit',
          'batch_path','batch_sha256','entry_sha256','artifact_id','kind'} and locator['schema'] == LOCATOR
          and locator['status'] == 'READY' and locator['repository_id'] == REPO_ID
          and locator['ref'] in _REFS, 'LOCATOR_INVALID')
    return _locator(locator['source_commit'], {k:locator[k] for k in
        ('batch_path','batch_sha256','entry_sha256','artifact_id','kind')},ref=locator['ref'])


def _batch_entry(git, commit, reference, mac_key):
    _ref(reference)
    raw = _read(git, commit, reference['batch_path'], MAX_INDEX)
    _need(_sha(raw) == reference['batch_sha256'], 'BATCH_HASH_INVALID')
    value = _unsigned(raw, mac_key)
    _need(set(value) == {'schema','repository_id','entries'} and value['schema'] == SCHEMA
          and value['repository_id'] == REPO_ID and type(value['entries']) is list
          and 0 < len(value['entries']) <= MAX_BATCH, 'BATCH_INVALID')
    matches = [entry for entry in value['entries'] if _sha(_wire(entry)) == reference['entry_sha256']]
    _need(len(matches) == 1, 'ENTRY_NOT_FOUND')
    entry = _entry(matches[0]); summary = entry['header']['summary']
    _need(summary['kind'] == reference['kind'] and summary['artifact_id'] == reference['artifact_id'],
          'ENTRY_BINDING_INVALID')
    return entry


def _lookup_path(ident):
    return PREFIX+'lookup/'+str(_id(ident)//LOOKUP_SPAN)+'.json'


def _lookup(git, commit, ident, mac_key):
    path = _lookup_path(ident)
    index = _index(git, commit, path, dict(kind='lookup', bucket=ident//LOOKUP_SPAN, entries={}), mac_key)
    _need(len(index['entries']) <= LOOKUP_SPAN, 'LOOKUP_BOUND_INVALID')
    for name, value in index['entries'].items():
        _need(re.fullmatch(r'[1-9][0-9]{0,19}', name) and int(name)//LOOKUP_SPAN == ident//LOOKUP_SPAN,
              'LOOKUP_ID_INVALID')
        _ref(value); _need(value['artifact_id'] == int(name), 'LOOKUP_BINDING_INVALID')
    return path, index


@contextmanager
def _independent_reader(git, supplied):
    if supplied is not None:
        _need(supplied.ref == git.ref and Path(supplied.repo).resolve() != Path(git.repo).resolve(),
              'INDEPENDENT_GIT_READER_REQUIRED')
        yield supplied
        return
    with tempfile.TemporaryDirectory(prefix='boat-vault-readback-') as temporary:
        root = Path(temporary)
        for args in (['git','init','--bare',str(root)], ['git','-C',str(root),'remote','add','origin',git.fetch_url]):
            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            _need(result.returncode == 0, 'READBACK_REPOSITORY_FAILED')
        yield VaultGitRepository(root,ref=git.ref)


def _verify_restored_records(reader,locators,records,key):
    """Read/decrypt every selected remote original, including unchanged entries.

    These caller records already passed native validation. Byte-exact restore
    against them proves that the independently fetched commit retains those
    same originals and receipts; matching public descriptors alone cannot.
    """
    _need(len(locators)==len(records),'READBACK_RECORD_COUNT_INVALID')
    for locator,record in zip(locators,records):
        files,header,_=_open(locator,reader.repo,key=key,transport=reader)
        _need(files==record['files'] and header['summary']==record['summary'],
              'REMOTE_ORIGINAL_READBACK_MISMATCH')


def _retain(records, repo, *, expected_parent, key, transport, readback_transport, now):
    encryption_key, mac_key = _keys(key)
    _hex(expected_parent, _HEAD)
    _need(type(records) is list and 0 < len(records) <= MAX_BATCH, 'BATCH_BOUND_INVALID')
    _need(sum(sum(item['size'] for item in _file_inventory(record['files']).values())
              for record in records) <= MAX_BATCH_PLAIN, 'BATCH_TOTAL_BOUND_INVALID')
    git = _transport(repo, transport)
    if readback_transport is not None:
        _need(readback_transport.ref == git.ref and Path(readback_transport.repo).resolve() != Path(git.repo).resolve(),
              'INDEPENDENT_GIT_READER_REQUIRED')
    parent = git.head()
    _need(parent is not None, 'REF_CONCURRENT_UPDATE_OR_MISSING')
    if parent!=expected_parent:raise ValueError('STATE_REF_CONCURRENT_UPDATE')
    git.fetch(parent)
    files = {}; pending = []; retained = []; existing = []; lookups = {}; run_indexes = {}; months = {}
    seen = set()
    for record in records:
        summary = record['summary']; ident = summary['artifact_id']
        identity = ('artifact', ident) if ident is not None else ('captures', _sha(_wire(_file_inventory(record['files']))))
        _need(identity not in seen, 'DUPLICATE_BATCH_ORIGINAL'); seen.add(identity)
        if ident is not None:
            lookup_path = _lookup_path(ident)
            if lookup_path not in lookups:
                lookups[lookup_path] = _lookup(git, parent, ident, mac_key)[1]
            previous = lookups[lookup_path]['entries'].get(str(ident))
            if previous is not None:
                old = _batch_entry(git, parent, previous, mac_key)
                _need(old['header']['summary'] == summary and old['header']['files'] == _file_inventory(record['files']),
                      'IMMUTABLE_ARTIFACT_CONFLICT')
                retained.append(previous); existing.append((previous,record)); continue
        else:
            run_path = PREFIX+summary['month']+'/runs/'+str(summary['run_id'])+'.json'
            if run_path not in run_indexes:
                run_indexes[run_path] = _index(git, parent, run_path,
                    dict(kind='run',month=summary['month'],run_id=summary['run_id'],entries={}),mac_key)
            entry_key = 'captures-'+_sha(_wire(_file_inventory(record['files'])))
            previous = run_indexes[run_path]['entries'].get(entry_key)
            if previous is not None:
                old = _batch_entry(git,parent,previous,mac_key)
                _need(old['header']['summary'] == summary and old['header']['files'] == _file_inventory(record['files']),
                      'IMMUTABLE_CAPTURE_CONFLICT')
                retained.append(previous); existing.append((previous,record)); continue
        entry, chunks = _seal(record, now, encryption_key)
        pending.append(entry); files.update(chunks); retained.append(entry)
    if not pending:
        locators=[_locator(parent,r,ref=git.ref) for r in retained]
        with _independent_reader(git,readback_transport) as reader:
            _verify_restored_records(reader,locators,records,key)
        return dict(status='EXACT_ORIGINAL_VAULT_UNCHANGED', source_commit=parent,
                    retained_originals=len(records), locators=locators,
                    independent_git_readback_verified=True, plaintext_published=False)
    if existing:
        # Detect broken inherited originals before adding a new batch. The
        # final commit is verified again below, including these old entries.
        with _independent_reader(git,readback_transport) as reader:
            _verify_restored_records(reader,[_locator(parent,r,ref=git.ref) for r,_ in existing],
                                     [record for _,record in existing],key)
    # A batch can span months without requiring several ref updates. Every
    # entry's chunks/index live in its own month; the batch is under the first.
    batch_raw = _signed(dict(schema=SCHEMA, repository_id=REPO_ID, entries=pending), mac_key)
    _need(len(batch_raw) <= MAX_INDEX, 'BATCH_INDEX_BOUND_INVALID')
    batch_sha = _sha(batch_raw); batch_path = PREFIX+pending[0]['header']['summary']['month']+'/batches/'+batch_sha+'.json'
    files[batch_path] = batch_raw
    references = {}
    for entry in pending:
        summary = entry['header']['summary']; month = summary['month']; run = summary['run_id']
        reference = _reference(batch_path, batch_sha, entry); references[id(entry)] = reference
        if summary['artifact_id'] is not None:
            lookups[_lookup_path(summary['artifact_id'])]['entries'][str(summary['artifact_id'])] = reference
        month_path = PREFIX+month+'/month.json'; run_path = PREFIX+month+'/runs/'+str(run)+'.json'
        if month_path not in months:
            months[month_path] = _index(git, parent, month_path,
                dict(kind='month', month=month, runs={}, entries=0, cipher_bytes=0), mac_key)
        month_index = months[month_path]
        _need(type(month_index['entries']) is int and type(month_index['cipher_bytes']) is int
              and 0 <= month_index['entries'] < MAX_MONTH_ENTRIES
              and 0 <= month_index['cipher_bytes'] <= MAX_MONTH_CIPHER_BYTES, 'MONTH_CAPACITY_EXHAUSTED')
        if run_path not in run_indexes:
            run_indexes[run_path] = _index(git, parent, run_path,
                dict(kind='run', month=month, run_id=run, entries={}), mac_key)
        run_index = run_indexes[run_path]
        # A mutable run index must match the authenticated monthly root, rather
        # than silently accepting an omitted/rolled-back run file.
        if run_path not in files and str(run) in month_index['runs']:
            old_run_raw = _read(git, parent, run_path, MAX_INDEX)
            _need(month_index['runs'][str(run)] == _sha(old_run_raw), 'RUN_INDEX_HASH_INVALID')
        entry_key = str(summary['artifact_id']) if summary['artifact_id'] is not None else 'captures-'+_sha(_wire(entry['header']['files']))
        _need(entry_key not in run_index['entries'] and len(run_index['entries']) < MAX_RUN_ENTRIES,
              'RUN_CAPACITY_OR_ORIGINAL_CONFLICT')
        run_index['entries'][entry_key] = reference
        run_raw = _signed(run_index, mac_key); files[run_path] = run_raw
        month_index['runs'][str(run)] = _sha(run_raw)
        month_index['entries'] += 1; month_index['cipher_bytes'] += entry['cipher_size']
        _need(len(month_index['runs']) <= MAX_MONTH_RUNS and month_index['entries'] <= MAX_MONTH_ENTRIES
              and month_index['cipher_bytes'] <= MAX_MONTH_CIPHER_BYTES, 'MONTH_CAPACITY_EXHAUSTED')
    for path, index in {**lookups, **months}.items():
        files[path] = _signed(index, mac_key)
    for path, body in files.items():
        _need(0 < len(body) <= (8*1024*1024 if '/chunks/' in path else MAX_INDEX), 'GIT_BLOB_BOUND_INVALID')
        if '/chunks/' in path or '/batches/' in path:
            if git.exists(parent, path):
                _need(_read(git, parent, path, 8*1024*1024) == body, 'IMMUTABLE_BYTES_CONFLICT')
    commit = git.commit(files, parent); git.push(commit, parent)
    locators = [_locator(commit, references[id(r)] if id(r) in references else r,ref=git.ref) for r in retained]
    # Use a different object database, populated from the actual remote commit.
    # Re-reading the writer's just-authored objects would not be independent.
    with _independent_reader(git, readback_transport) as reader:
        reader.fetch(commit)
        for path, body in files.items():
            _need(_read(reader, commit, path, 8*1024*1024) == body, 'REMOTE_READBACK_MISMATCH')
        _verify_restored_records(reader,locators,records,key)
    return dict(status='EXACT_ORIGINAL_VAULT_RETAINED', source_commit=commit,
                retained_originals=len(records), locators=locators,
                independent_git_readback_verified=True, plaintext_published=False)


def retain_originals(originals, repo, *, expected_parent, key=None, transport=None,
                     readback_transport=None, now=None):
    """Authenticate and append a bounded list in one CAS and fresh Git readback.

    Items are ``(exact_outer_zip, exact_metadata_response)`` pairs or dictionaries
    with ``raw_zip``, ``metadata_raw``, optional ``expected_kind`` and optional
    ``companion=(continuity_zip, continuity_metadata_raw)`` for SOURCE_CONTROL.
    The caller owns actual receipt acquisition. Expired receipts cannot be newly
    admitted; restore instead uses the exact previously captured receipt.
    """
    _keys(key)  # Missing key stops before remote access or private staging.
    clock = now or datetime.now(timezone.utc)
    _need(type(clock) is datetime and clock.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    _need(type(originals) in (tuple, list) and 0 < len(originals) <= MAX_BATCH, 'BATCH_BOUND_INVALID')
    records = []
    # Existing native readers obtain their key from the Actions environment.
    # Explicit test/API keys stay in a scoped environment and are never logged.
    with _native_key(key):
        for item in originals:
            if type(item) is dict:
                _need(set(item) <= {'raw_zip','metadata_raw','expected_kind','companion'}
                      and {'raw_zip','metadata_raw'} <= set(item), 'ORIGINAL_FIELDS_INVALID')
                records.append(_artifact(item['raw_zip'], item['metadata_raw'], key=key, now=clock,
                    expected_kind=item.get('expected_kind'), companion=item.get('companion')))
            else:
                _need(type(item) in (list, tuple) and len(item) == 2, 'ORIGINAL_PAIR_INVALID')
                records.append(_artifact(*item, key=key, now=clock))
    return _retain(records, repo, expected_parent=expected_parent, key=key, transport=transport,
                   readback_transport=readback_transport, now=clock)


@contextmanager
def _native_key(key):
    # Existing phase readers intentionally expose no key parameter. Production
    # uses the already-present Actions secret; explicit keys are fixture-only
    # dependency injection, restored immediately after synchronous validation.
    if key is None:
        yield
        return
    import base64
    original = os.environ.get('RACE_AI_STATE_KEY')
    os.environ['RACE_AI_STATE_KEY'] = base64.b64encode(state_key('production', key)).decode('ascii')
    try:
        yield
    finally:
        if original is None: os.environ.pop('RACE_AI_STATE_KEY', None)
        else: os.environ['RACE_AI_STATE_KEY'] = original


def retain_original(raw_zip, metadata_raw, repo, *, expected_parent, expected_kind=None,
                    companion=None, key=None, transport=None, readback_transport=None, now=None):
    return retain_originals([dict(raw_zip=raw_zip, metadata_raw=metadata_raw,
        expected_kind=expected_kind, companion=companion)], repo, expected_parent=expected_parent,
        key=key, transport=transport, readback_transport=readback_transport, now=now)['locators'][0]


def _open(locator, repo, *, key, transport):
    encryption_key, mac_key = _keys(key)
    _validate_locator(locator); git = _transport(repo, transport); commit = locator['source_commit']
    git.fetch(commit)
    reference = {name:locator[name] for name in ('batch_path','batch_sha256','entry_sha256','artifact_id','kind')}
    entry = _batch_entry(git, commit, reference, mac_key)
    chunks = []
    for chunk in entry['chunks']:
        raw = _read(git, commit, chunk['path'], 8*1024*1024)
        _need(len(raw) == chunk['size'] and _sha(raw) == chunk['sha256'], 'CHUNK_HASH_INVALID')
        chunks.append(raw)
    raw = b''.join(chunks)
    _need(len(raw) == entry['cipher_size'] and _sha(raw) == entry['cipher_sha256']
          and raw.startswith(MAGIC) and len(raw) > 40, 'CIPHER_HASH_INVALID')
    size = struct.unpack('>I', raw[8:12])[0]; encoded = raw[12:12+size]
    _need(0 < size <= MAX_INDEX//2 and len(raw) >= 12+size+28
          and encoded == _wire(entry['header']), 'CIPHER_HEADER_INVALID')
    nonce, ciphertext = raw[12+size:24+size], raw[24+size:]
    try:
        plain = AESGCM(encryption_key).decrypt(nonce, ciphertext, DOMAIN+b'\0'+encoded+nonce)
    except Exception:
        raise ValueError('VAULT_AUTHENTICATION_FAILED') from None
    files = {}; offset = 0
    for name, item in sorted(entry['header']['files'].items()):
        body = plain[offset:offset+item['size']]; offset += item['size']
        _need(len(body) == item['size'] and _sha(body) == item['sha256'], 'ORIGINAL_FILE_HASH_INVALID')
        files[name] = body
    _need(offset == len(plain), 'PLAIN_FRAMING_INVALID')
    provenance = dict(receipt_scope='ARCHIVED_GITHUB_ARTIFACT_RESPONSE', current_artifact_status='NOT_QUERIED',
        archived_at=entry['header']['archived_at'], source_commit=commit, entry_sha256=locator['entry_sha256'],
        independent_git_readback_verified=True, github_artifact_receipt_created=False)
    return files, entry['header'], provenance


def restore_original(locator, repo, *, key=None, transport=None):
    """Restore exact bytes from pinned Git; never query/rewrite current metadata."""
    files, header, provenance = _open(locator, repo, key=key, transport=transport)
    _need(header['summary']['kind'] in KINDS, 'ORIGINAL_LOCATOR_REQUIRED')
    expected = {'original.zip','metadata.json'}
    companion = None
    if header['summary']['kind'] == 'SOURCE_CONTROL':
        expected |= {'continuity.zip','continuity.metadata.json'}
        companion = (files['continuity.zip'], files['continuity.metadata.json'])
    _need(set(files) == expected, 'ORIGINAL_LAYOUT_INVALID')
    with _native_key(key):
        record = _artifact(files['original.zip'], files['metadata.json'], key=key,
            now=_time(header['archived_at']), expected_kind=header['summary']['kind'], companion=companion)
    _need(record['summary'] == header['summary'], 'ORIGINAL_SUMMARY_MISMATCH')
    return dict(raw_zip=files['original.zip'], metadata_raw=files['metadata.json'],
                metadata=record['metadata'], provenance=provenance)


def lookup_original(artifact_id, repo, *, source_commit=None, key=None, transport=None):
    """Read one numeric-ID bucket and one batch; no all-history/blob enumeration."""
    _, mac_key = _keys(key); _id(artifact_id)
    git = _transport(repo, transport); commit = source_commit if source_commit is not None else git.head()
    _need(commit is not None, 'EXISTING_VAULT_REF_REQUIRED'); _hex(commit, _HEAD); git.fetch(commit)
    _, index = _lookup(git, commit, artifact_id, mac_key)
    reference = index['entries'].get(str(artifact_id))
    if reference is None: return None
    _batch_entry(git, commit, reference, mac_key)
    return _locator(commit, reference,ref=git.ref)


def list_originals(month, repo, *, source_commit=None, run_id=None, key=None, transport=None):
    """List bounded authenticated month/run descriptors, without reading chunks."""
    _, mac_key = _keys(key); _month(month)
    if run_id is not None: _id(run_id)
    git = _transport(repo, transport); commit = source_commit if source_commit is not None else git.head()
    _need(commit is not None, 'EXISTING_VAULT_REF_REQUIRED'); _hex(commit, _HEAD); git.fetch(commit)
    path = PREFIX+month+'/month.json'
    if not git.exists(commit, path): return []
    index = _index(git, commit, path, dict(kind='month',month=month,runs={},entries=0,cipher_bytes=0), mac_key)
    _need(type(index['entries']) is int and 0 <= index['entries'] <= MAX_MONTH_ENTRIES
          and type(index['cipher_bytes']) is int and 0 <= index['cipher_bytes'] <= MAX_MONTH_CIPHER_BYTES
          and len(index['runs']) <= MAX_MONTH_RUNS, 'MONTH_CAPACITY_EXHAUSTED')
    found = []
    for run, expected in sorted(index['runs'].items(), key=lambda pair:int(pair[0])):
        _need(re.fullmatch(r'[1-9][0-9]{0,19}', run), 'RUN_ID_INVALID'); _hex(expected)
        if run_id is not None and int(run) != run_id: continue
        run_path = PREFIX+month+'/runs/'+run+'.json'
        raw = _read(git, commit, run_path, MAX_INDEX); _need(_sha(raw) == expected, 'RUN_INDEX_HASH_INVALID')
        values = _unsigned(raw, mac_key)
        _need(set(values) == {'schema','repository_id','kind','month','run_id','entries'}
              and values['schema'] == SCHEMA and values['repository_id'] == REPO_ID
              and values['kind'] == 'run' and values['month'] == month and values['run_id'] == int(run)
              and type(values['entries']) is dict and len(values['entries']) <= MAX_RUN_ENTRIES, 'RUN_INDEX_INVALID')
        for ident, reference in values['entries'].items():
            _ref(reference)
            _need(ident == str(reference['artifact_id']) or reference['kind'] == 'SOURCE_CAPTURES'
                  and re.fullmatch(r'captures-[a-f0-9]{64}', ident), 'RUN_ENTRY_INVALID')
            found.append(_locator(commit, reference,ref=git.ref))
    if run_id is None: _need(len(found) == index['entries'], 'MONTH_INDEX_INCOMPLETE')
    return found


def retain_capture_bundle(captures, repo, *, run_id, head_sha, expected_parent, key=None,
                          transport=None, readback_transport=None, now=None):
    """Retain exact raw result captures; this creates no Actions artifact receipt."""
    _keys(key); clock = now or datetime.now(timezone.utc)
    _need(type(clock) is datetime and clock.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    record = _capture_record(captures, run_id=run_id, head_sha=head_sha, now=clock)
    return _retain([record], repo, expected_parent=expected_parent, key=key, transport=transport,
        readback_transport=readback_transport, now=clock)['locators'][0]


def restore_capture_bundle(locator, repo, *, key=None, transport=None):
    files, header, provenance = _open(locator, repo, key=key, transport=transport)
    summary = header['summary']; _need(summary['kind'] == 'SOURCE_CAPTURES', 'CAPTURE_LOCATOR_REQUIRED')
    captures = [(files[f'capture-{number:04d}.raw'], files[f'capture-{number:04d}.json'])
                for number in range(summary['capture_count'])]
    record = _capture_record(captures, run_id=summary['run_id'], head_sha=summary['head_sha'],
                             now=_time(header['archived_at']))
    _need(record['files'] == files and record['summary'] == summary, 'CAPTURE_SUMMARY_MISMATCH')
    provenance['receipt_scope'] = 'OWNER_RETAINED_SOURCE_CAPTURES'
    return dict(captures=captures, provenance=provenance)


class VaultArtifactReader:
    """Select a pinned archive before live GET; a denied live GET never falls back.

    Wrap the existing strict ``get(endpoint)`` function once per invocation.
    This adapter owns only exact actions/artifacts/<id> and /zip reads. Other
    endpoints keep their existing transport, pagination and denial semantics.
    A missing required original is still the caller's stop condition, never
    permission to reset a database or regenerate forecasts.
    """
    def __init__(self, github_get, repo, *, key=None, transport=None, known_locators=None):
        _keys(key)
        self.get = github_get; self.repo = repo; self.key = key; self.transport = transport
        self.known = dict(known_locators or {}); self.selected = {}; self.cache = {}

    def __call__(self, endpoint):
        matched = re.fullmatch(r'actions/artifacts/([1-9][0-9]{0,19})(/zip)?', endpoint)
        if matched is None: return self.get(endpoint)
        ident = int(matched[1])
        if ident not in self.selected:
            # Commit the selection before calling live transport, including a
            # missing entry. No later HTTP failure can change this decision.
            locator = self.known.get(ident)
            if locator is None:
                locator = lookup_original(ident, self.repo, key=self.key, transport=self.transport)
            self.selected[ident] = locator
        locator = self.selected[ident]
        if locator is None: return self.get(endpoint)
        _need(locator['artifact_id'] == ident, 'READER_LOCATOR_ID_INVALID')
        if ident not in self.cache:
            self.cache[ident] = restore_original(locator, self.repo, key=self.key, transport=self.transport)
        return self.cache[ident]['raw_zip' if matched[2] else 'metadata_raw']
