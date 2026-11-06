"""Ephemeral private handoff of native inputs already collected by the pilot.

No fetching, new feature construction, key access or external freeze claim.
The pending plaintext is permitted only outside Git with private permissions;
the caller owns encryption and removal after the independent baseline upload.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat

from .actions_contract import digest
from .boat_ab_shadow import MODEL_IDS as AB, _valid, _time
from .boat_live_feature_shadow import MODEL_ID as CLITE, build_live_feature_shadow
from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED, _validate
from .observed_p1_connection import RIGHTS, locator

SCHEMA = 'RACE_AI_PRIVATE_PENDING_NATIVE_INPUTS_V1'
DERIVATION = 'SHA256_UTF8_CONCAT_PROGRAM_AND_BEFOREINFO_HEX_V1'
MAX_REQUESTS = 24*12*5
MAX_PENDING_BYTES = 32*1024*1024
_REPOSITORY = Path(__file__).resolve().parents[1]
_DIRECT_FIELDS = {'source_ref', 'source_rights_ref', 'source_sha256', 'captured_at', 'evidence_basis'}
_DERIVED_FIELDS = _DIRECT_FIELDS | {'derivation', 'upstream_source_sha256'}
_MODEL_IDS = (*AB, CLITE, *OBSERVED)


def _need(condition, reason):
    if not condition:
        raise ValueError('NATIVE_INPUT_' + reason)


def _bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError):
        raise ValueError('NATIVE_INPUT_JSON_INVALID') from None


def _direct(url, sha, captured_at):
    return dict(source_ref=url, source_rights_ref=RIGHTS, source_sha256=sha,
                captured_at=captured_at, evidence_basis='HTTP_BODY_SHA256')


def _evidence(evidence, race_id):
    _need(type(evidence) is list and len(evidence) >= 2, 'SOURCE_EVIDENCE_REQUIRED')
    for kind, item in zip(('racelist', 'beforeinfo'), evidence):
        _need(type(item) is dict and set(item) == _DIRECT_FIELDS and item['source_rights_ref'] == RIGHTS and
              item['evidence_basis'] == 'HTTP_BODY_SHA256', 'DIRECT_SOURCE_FIELDS')
        locator(item['source_ref'], kind, race_id)
        _need(type(item['source_sha256']) is str and len(item['source_sha256']) == 64 and
              all(c in '0123456789abcdef' for c in item['source_sha256']), 'SOURCE_SHA_INVALID')
        _time(item['captured_at'])
    _need(_time(evidence[0]['captured_at']) <= _time(evidence[1]['captured_at']), 'SOURCE_CLOCK_ORDER')


def _request_identity(request):
    _need(type(request) is dict and set(request) == {'cell_key', 'native_payload'}, 'REQUEST_FIELDS')
    key = request['cell_key']
    _need(type(key) is str and key.startswith('boat/') and key[5:] in _MODEL_IDS, 'CURRENT_FAMILY_UNAVAILABLE')
    mid = key[5:]; payload = request['native_payload']
    fields = {'scope', 'source_evidence'} | ({'source'} if mid in AB else
             {'base_source', 'extra'} if mid == CLITE else {'snapshot'})
    _need(type(payload) is dict and set(payload) == fields and
          payload['scope'] == 'OPERATOR_SUPPLIED_RESEARCH', 'PAYLOAD_FIELDS_OR_SCOPE')
    evidence = payload['source_evidence']
    if mid in AB or mid == CLITE:
        source = payload['source'] if mid in AB else payload['base_source']
        _valid(source, source['captured_at'])
        rid = source['race_id']; _evidence(evidence, rid)
        _need(len(evidence) == (3 if mid == CLITE else 2), 'SOURCE_COUNT')
        _need(source['program_source_sha256'] == evidence[0]['source_sha256'] and
              source['beforeinfo_source_sha256'] == evidence[1]['source_sha256'] and
              _time(source['captured_at']) == _time(evidence[1]['captured_at']), 'SOURCE_INPUT_BINDING')
        if mid == CLITE:
            extra = payload['extra']; derived = evidence[2]
            expected = hashlib.sha256((source['program_source_sha256'] + source['beforeinfo_source_sha256']).encode('utf-8')).hexdigest()
            _need(type(derived) is dict and set(derived) == _DERIVED_FIELDS and
                  derived['evidence_basis'] == 'DERIVED_COMPOSITE_SHA256' and derived['derivation'] == DERIVATION and
                  derived['source_ref'] == evidence[1]['source_ref'] and derived['source_rights_ref'] == RIGHTS and
                  derived['source_sha256'] == extra['source_sha256'] == expected and
                  derived['upstream_source_sha256'] == [e['source_sha256'] for e in evidence[:2]] and
                  _time(derived['captured_at']) == _time(extra['observed_at']) == _time(source['captured_at']),
                  'COMPOSITE_SOURCE_BINDING')
            build_live_feature_shadow(source, extra, source['captured_at'])
        return rid
    snapshot = payload['snapshot']; _validate(snapshot)
    _need(snapshot['scope'] == payload['scope'] and snapshot['stage'] == 'P1', 'OBSERVED_SCOPE_OR_STAGE')
    from .frozen_day_cycle import official_id
    rid = official_id(snapshot['race_id']); _evidence(evidence, rid)
    _need(len(evidence) == 2 and len(snapshot['sources']) >= 2, 'OBSERVED_SOURCE_COUNT')
    for kind, source, proof in zip(('racelist', 'beforeinfo'), snapshot['sources'], evidence):
        _need(source['source_url'] == locator(proof['source_ref'], kind, rid) and
              source['source_sha256'] == proof['source_sha256'] and source['source_rights_ref'] == RIGHTS and
              _time(source['captured_at']) == _time(proof['captured_at']) <= _time(snapshot['as_of']),
              'OBSERVED_SOURCE_BINDING')
    return rid


def current_requests(events):
    """Detach and validate RAM sink batches, deduplicating identical inputs."""
    _need(type(events) is list and len(events) <= MAX_REQUESTS, 'BOUNDED_EVENTS_REQUIRED')
    requests = []
    for event in events:
        batch = event if type(event) is list else [event]
        _need(len(requests)+len(batch) <= MAX_REQUESTS, 'REQUEST_LIMIT')
        requests.extend(batch)
    result = []; seen = {}
    for supplied in requests:
        try:
            request = deepcopy(supplied); rid = _request_identity(request)
        except (TypeError, KeyError, AttributeError, OverflowError) as exc:
            raise ValueError('NATIVE_INPUT_REQUEST_INVALID') from exc
        # Serialization also rejects nonfinite JSON and unrecognized objects.
        _bytes(request)
        identity = (request['cell_key'], rid)
        fingerprint = digest(request['native_payload'])
        if identity in seen:
            _need(seen[identity] == fingerprint, 'CONFLICTING_CURRENT_INPUT')
            continue
        seen[identity] = fingerprint; result.append(request)
    return result


def build_current_requests(data, extra, observed, *, program_url, preview_url,
                           program_captured_at, preview_captured_at):
    """Retain only native families for which actual collected inputs exist."""
    evidence = [_direct(program_url, data['program_source_sha256'], program_captured_at),
                _direct(preview_url, data['beforeinfo_source_sha256'], preview_captured_at)]
    requests = [dict(cell_key='boat/'+mid, native_payload=dict(
        source=deepcopy(data), scope='OPERATOR_SUPPLIED_RESEARCH', source_evidence=deepcopy(evidence))) for mid in AB]
    composite = dict(source_ref=preview_url, source_rights_ref=RIGHTS,
        source_sha256=extra.get('source_sha256') if type(extra) is dict else None,
        captured_at=preview_captured_at, evidence_basis='DERIVED_COMPOSITE_SHA256',
        derivation=DERIVATION, upstream_source_sha256=[data['program_source_sha256'], data['beforeinfo_source_sha256']])
    clite = dict(cell_key='boat/'+CLITE, native_payload=dict(base_source=deepcopy(data), extra=deepcopy(extra),
        scope='OPERATOR_SUPPLIED_RESEARCH', source_evidence=deepcopy(evidence)+[composite]))
    try:
        _request_identity(clite)
        requests.append(clite)
    except (ValueError, TypeError, KeyError, AttributeError):
        pass  # A separately rejected optional family cannot fabricate inputs.
    if type(observed) is dict and 'snapshot' in observed and 'suite' in observed:
        snapshot = observed['snapshot']; suite = observed['suite']
        _need(observed.get('base_source_sha256') == digest(data) and
              suite.get('snapshot_sha256') == digest(snapshot), 'OBSERVED_NATIVE_INPUT_BINDING')
        for mid in OBSERVED:
            _need(mid in suite['models'], 'OBSERVED_NATIVE_MODEL_MISSING')
            requests.append(dict(cell_key='boat/'+mid, native_payload=dict(snapshot=deepcopy(snapshot),
                scope='OPERATOR_SUPPLIED_RESEARCH', source_evidence=deepcopy(evidence))))
    return current_requests(requests)


def _location(folder):
    path = Path(folder)
    _need(path.is_absolute() and '..' not in path.parts and '.git' not in path.parts, 'PRIVATE_ABSOLUTE_DIRECTORY_REQUIRED')
    for ancestor in (path, *path.parents):
        _need(not ancestor.is_symlink(), 'SYMLINK_REJECTED')
        _need(not (ancestor/'.git').exists() and not (ancestor/'.git').is_symlink(), 'PLAINTEXT_GIT_PATH_REJECTED')
    resolved = path.resolve()
    _need(resolved != _REPOSITORY and _REPOSITORY not in resolved.parents, 'PLAINTEXT_GIT_PATH_REJECTED')
    return path


def _directory(folder):
    path = _location(folder)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ValueError('NATIVE_INPUT_PRIVATE_DIRECTORY_UNAVAILABLE') from exc
    info = os.fstat(fd)
    if not (stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid()):
        os.close(fd)
        raise ValueError('NATIVE_INPUT_PRIVATE_DIRECTORY_PERMISSIONS')
    return path, fd


def write_private_pending_requests(requests, folder):
    """Write private ephemeral JSON, without coefficients, forecasts or keys."""
    requests = current_requests(requests)
    envelope = dict(schema=SCHEMA, requests=requests,
                    native_payload_sha256=[digest(r['native_payload']) for r in requests],
                    requests_sha256=digest(requests))
    raw = _bytes(envelope); _need(len(raw) <= MAX_PENDING_BYTES, 'PENDING_SIZE_LIMIT')
    path = _location(folder)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path, directory = _directory(path)
    try:
        _need(not any(path.iterdir()), 'PENDING_EXISTS_DO_NOT_RESET')
        try:
            fd = os.open('pending.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        except OSError as exc:
            raise ValueError('NATIVE_INPUT_PENDING_CREATE_REJECTED') from exc
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    finally:
        os.close(directory)
    _need(read_private_pending_requests(path) == requests, 'PENDING_READBACK_MISMATCH')
    return dict(schema=SCHEMA, native_request_count=len(requests), requests_sha256=envelope['requests_sha256'],
                plaintext_published=False, external_freeze_verified=False)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, 'DUPLICATE_JSON_FIELD')
        result[key] = value
    return result


def read_private_pending_requests(folder):
    """Recheck private path, permissions, payload hashes and source bindings."""
    path, directory = _directory(folder)
    try:
        _need(sorted(p.name for p in path.iterdir()) == ['pending.json'], 'PENDING_DIRECTORY_CONTENTS')
        try:
            fd = os.open('pending.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except OSError as exc:
            raise ValueError('NATIVE_INPUT_PENDING_READ_REJECTED') from exc
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            _need(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and
                  info.st_uid == os.getuid() and info.st_size <= MAX_PENDING_BYTES, 'PENDING_PERMISSIONS_OR_SIZE')
            raw = stream.read(MAX_PENDING_BYTES+1)
            _need(len(raw) <= MAX_PENDING_BYTES, 'PENDING_SIZE_LIMIT')
    finally:
        os.close(directory)
    try:
        envelope = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('NATIVE_INPUT_PENDING_JSON_INVALID') from exc
    _need(type(envelope) is dict and set(envelope) == {'schema', 'requests', 'native_payload_sha256', 'requests_sha256'} and
          envelope['schema'] == SCHEMA, 'PENDING_SCHEMA')
    requests = current_requests(envelope['requests'])
    _need(requests == envelope['requests'] and digest(requests) == envelope['requests_sha256'] and
          [digest(r['native_payload']) for r in requests] == envelope['native_payload_sha256'], 'PENDING_PAYLOAD_HASH')
    return requests
