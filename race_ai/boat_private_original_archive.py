"""Owner-encrypted original ZIPs bound to independently read Actions receipts.

The caller supplies actual GitHub artifact ZIP bytes and metadata. This helper
performs no source requests and infers no physical save time: created_at stays
in the supplied receipt. Decoded member bytes are never rewritten or extracted.
"""
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import io
import json
from pathlib import PurePosixPath
import re
import stat
import struct
import zipfile
import zlib
import os

from .repeated_cycle import matches

SCHEMA = 'RACE_AI_BOAT_PRIVATE_ORIGINAL_ARCHIVE_V1'
DOMAIN = SCHEMA.encode('ascii')
PURPOSE = 'boat-private-original-archive'
REPO_ID = '1416489937'
MAGIC = b'RABPO1\0\0'
CIPHER_MEMBER = 'private-original.enc'
MAX_PLAIN_ZIP = 128*1024*1024
MAX_WIRE = 160*1024*1024
MAX_EXPANDED = 512*1024*1024
MAX_ENTRIES = 10000
MAX_HEADER = 8192
MAX_OVERHEAD = 64*1024
KINDS = frozenset(('P0', 'P1', 'RESULT', 'CONTINUITY'))
PREFIXES = {'P0': 'boat-p0-existing', 'P1': 'boat-national-cutoff',
            'RESULT': 'race-existing-cycle', 'CONTINUITY': 'race-cycle-continuity'}
_HEAD = re.compile(r'[a-f0-9]{40}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, EOFError,
               RuntimeError, NotImplementedError, OSError, struct.error, UnicodeError)


def _need(ok, reason):
    if not ok:
        raise ValueError('PRIVATE_ORIGINAL_'+reason)


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('PRIVATE_ORIGINAL_JSON_INVALID') from None


def _run(value):
    if type(value) is int:
        value = str(value)
    _need(type(value) is str and re.fullmatch(r'[1-9][0-9]{0,19}', value), 'RUN_INVALID')
    return value


def _limit(value):
    _need(type(value) is int and 0 < value <= MAX_PLAIN_ZIP, 'PLAIN_ZIP_BOUND_INVALID')
    return value


def _name(name, *, directory=False):
    _need(type(name) is str and 0 < len(name.encode('utf-8')) <= 1024
          and '\\' not in name and not any(ord(c) < 32 or ord(c) == 127 for c in name), 'ZIP_PATH_INVALID')
    clean = name[:-1] if directory and name.endswith('/') else name
    path = PurePosixPath(clean)
    _need(clean and not path.is_absolute() and str(path) == clean and len(path.parts) <= 32
          and all(part not in ('', '.', '..') for part in path.parts)
          and ':' not in path.parts[0], 'ZIP_PATH_INVALID')


def _checked_zip(raw, *, max_zip_bytes, max_expanded=None):
    """Open and fully validate bounded members, including their actual CRCs."""
    max_expanded = MAX_EXPANDED if max_expanded is None else max_expanded
    _need(type(raw) is bytes and 0 < len(raw) <= max_zip_bytes, 'ZIP_BOUND_INVALID')
    source = None
    try:
        # Reject prefixed/concatenated/trailing containers rather than guessing
        # which bytes a hash or member name was intended to describe.
        end = raw.rfind(b'PK\x05\x06', max(0, len(raw)-65557))
        _need(end >= 0 and end+22 <= len(raw)
              and end+22+struct.unpack('<H', raw[end+20:end+22])[0] == len(raw), 'ZIP_FRAMING_INVALID')
        source = zipfile.ZipFile(io.BytesIO(raw))
        entries = source.infolist()
        _need(0 < len(entries) <= MAX_ENTRIES
              and len({entry.filename for entry in entries}) == len(entries), 'ZIP_MEMBERS_INVALID')
        _need(min(entry.header_offset for entry in entries) == 0, 'ZIP_PREFIX_INVALID')
        total = 0
        for entry in entries:
            _need(entry.filename == entry.orig_filename, 'ZIP_PATH_INVALID')
            directory = entry.is_dir()
            _name(entry.filename, directory=directory)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            _need(mode in ((0, stat.S_IFDIR) if directory else (0, stat.S_IFREG))
                  and not entry.flag_bits & 0x41
                  and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                  and 0 <= entry.file_size <= max_expanded
                  and 0 <= entry.compress_size <= len(raw)
                  and 0 <= entry.header_offset < source.start_dir
                  and (not directory or entry.file_size == 0), 'ZIP_MEMBER_INVALID')
            total += entry.file_size
            _need(total <= max_expanded, 'ZIP_EXPANDED_BOUND_INVALID')
        for entry in entries:
            size = 0
            with source.open(entry) as member:
                while chunk := member.read(min(1024*1024, entry.file_size-size+1)):
                    size += len(chunk)
                    _need(size <= entry.file_size, 'ZIP_MEMBER_SIZE_INVALID')
            _need(size == entry.file_size, 'ZIP_MEMBER_SIZE_INVALID')
        return source
    except _ZIP_ERRORS:
        if source is not None:
            source.close()
        raise ValueError('PRIVATE_ORIGINAL_ZIP_INVALID') from None
    except Exception:
        if source is not None:
            source.close()
        raise


def _header(value):
    fields = {'schema', 'purpose', 'repository_id', 'run_id', 'head_sha', 'kind',
              'plain_zip_sha256', 'plain_zip_size', 'encoding'}
    _need(type(value) is dict and set(value) == fields and value['schema'] == SCHEMA
          and value['purpose'] == PURPOSE and value['repository_id'] == REPO_ID
          and value['encoding'] == 'zip' and type(value['kind']) is str
          and value['kind'] in KINDS, 'HEADER_INVALID')
    _need(type(value['run_id']) is str and _run(value['run_id']) == value['run_id']
          and type(value['head_sha']) is str and _HEAD.fullmatch(value['head_sha'])
          and type(value['plain_zip_sha256']) is str and _SHA.fullmatch(value['plain_zip_sha256']), 'HEADER_IDENTITY_INVALID')
    _limit(value['plain_zip_size'])
    return value


def _key(key=None):
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError:
        raise ValueError('PRIVATE_ORIGINAL_CRYPTO_RUNTIME_UNAVAILABLE') from None
    # Frozen original readers are dependencies of the canonical state module.
    # Import only when encryption is requested; legacy reads need no owner key.
    from .boat_pdca_state import state_key
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=REPO_ID.encode('ascii'),
                info=DOMAIN).derive(state_key('production', key))


def _split(raw):
    _need(type(raw) is bytes and 40 < len(raw) <= min(MAX_WIRE, MAX_PLAIN_ZIP+MAX_OVERHEAD)
          and raw.startswith(MAGIC), 'ENVELOPE_INVALID')
    size = struct.unpack('>I', raw[8:12])[0]
    _need(0 < size <= MAX_HEADER and len(raw) >= 12+size+28, 'HEADER_BOUND_INVALID')
    encoded = raw[12:12+size]
    def unique(items):
        result = {}
        for name, value in items:
            _need(name not in result, 'HEADER_DUPLICATE_JSON_KEY')
            result[name] = value
        return result
    try:
        # Header parsing is stdlib-only too: the shared recipient JSON helper
        # belongs to a crypto-backed module that legacy readers do not need.
        header = _header(json.loads(encoded.decode('utf-8'), object_pairs_hook=unique,
                                    parse_constant=lambda _: _need(False, 'HEADER_INVALID')))
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ValueError('PRIVATE_ORIGINAL_HEADER_INVALID') from None
    _need(_wire(header) == encoded, 'HEADER_NONCANONICAL')
    nonce, cipher = raw[12+size:24+size], raw[24+size:]
    _need(len(cipher) == header['plain_zip_size']+16, 'CIPHER_SIZE_INVALID')
    return header, encoded, nonce, cipher


def _open_envelope(raw, *, key=None, max_plain_zip_bytes=MAX_PLAIN_ZIP):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ValueError('PRIVATE_ORIGINAL_CRYPTO_RUNTIME_UNAVAILABLE') from None
    header, encoded, nonce, cipher = _split(raw)
    _need(header['plain_zip_size'] <= _limit(max_plain_zip_bytes), 'PLAIN_ZIP_BOUND_INVALID')
    derived = _key(key)
    try:
        plain = AESGCM(derived).decrypt(nonce, cipher, DOMAIN+b'\0'+encoded+nonce)
    except Exception:
        raise ValueError('PRIVATE_ORIGINAL_AUTHENTICATION_FAILED') from None
    _need(len(plain) == header['plain_zip_size'] and sha256(plain).hexdigest() == header['plain_zip_sha256'],
          'PLAIN_ZIP_HASH_INVALID')
    return plain, header


def seal_original_zip(private_zip_bytes, *, run_id, head_sha, kind, key=None):
    """Seal exact native ZIP bytes; no file contents or save clock enter header."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ValueError('PRIVATE_ORIGINAL_CRYPTO_RUNTIME_UNAVAILABLE') from None
    with _checked_zip(private_zip_bytes, max_zip_bytes=MAX_PLAIN_ZIP):
        pass
    header = _header(dict(schema=SCHEMA, purpose=PURPOSE, repository_id=REPO_ID,
                          run_id=_run(run_id), head_sha=head_sha, kind=kind,
                          plain_zip_sha256=sha256(private_zip_bytes).hexdigest(),
                          plain_zip_size=len(private_zip_bytes), encoding='zip'))
    encoded = _wire(header)
    _need(len(encoded) <= MAX_HEADER, 'HEADER_BOUND_INVALID')
    nonce = os.urandom(12)
    cipher = AESGCM(_key(key)).encrypt(nonce, private_zip_bytes, DOMAIN+b'\0'+encoded+nonce)
    raw = MAGIC+struct.pack('>I', len(encoded))+encoded+nonce+cipher
    _need(len(raw) <= min(MAX_WIRE, MAX_PLAIN_ZIP+MAX_OVERHEAD), 'ENVELOPE_BOUND_INVALID')
    return raw


def _receipt(raw, receipt):
    _need(type(receipt) is dict and receipt.get('expired') is False
          and receipt.get('digest') == 'sha256:'+sha256(raw).hexdigest(), 'ARTIFACT_DIGEST_OR_STATUS_INVALID')
    if 'size_in_bytes' in receipt:
        _need(type(receipt['size_in_bytes']) is int and receipt['size_in_bytes'] == len(raw), 'ARTIFACT_SIZE_INVALID')
    run = receipt.get('workflow_run')
    _need(type(run) is dict and type(run.get('id')) is int
          and type(run.get('head_repository_id')) is int and run['head_repository_id'] == int(REPO_ID), 'ARTIFACT_REPOSITORY_INVALID')
    run_id = _run(run['id'])
    if 'repository_id' in run:
        _need(type(run['repository_id']) is int and run['repository_id'] == int(REPO_ID), 'ARTIFACT_REPOSITORY_INVALID')
    name = receipt.get('name')
    _need(type(name) is str and len(name) <= 200, 'ARTIFACT_NAME_INVALID')
    kinds = [kind for kind, prefix in PREFIXES.items()
             if (name == prefix+'-'+run_id if kind == 'CONTINUITY' else matches(name, prefix+'-'+run_id))]
    _need(len(kinds) == 1, 'ARTIFACT_NAME_INVALID')
    return run, kinds[0]


@contextmanager
def open_original_zip(raw_actual_GitHub_artifact_ZIP, receipt, *, expected_kind=None,
                      key=None, max_plain_zip_bytes=MAX_PLAIN_ZIP):
    """Yield a validated private ZipFile while preserving its native member bytes.

    The digest always addresses the actual outer GitHub ZIP. Encrypted archives
    additionally require full repository/run/head metadata, bound in AEAD.
    Legacy clear ZIPs retain their older head_repository_id-only contract and
    require no key. Caller phase-specific member and forecast checks still apply.
    """
    raw = raw_actual_GitHub_artifact_ZIP
    limit = _limit(max_plain_zip_bytes)
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_WIRE, 'ARTIFACT_BOUND_INVALID')
    _need(expected_kind is None or type(expected_kind) is str and expected_kind in KINDS, 'EXPECTED_KIND_INVALID')
    run, kind = _receipt(raw, receipt)
    _need(expected_kind is None or kind == expected_kind, 'ARTIFACT_KIND_INVALID')
    with _checked_zip(raw, max_zip_bytes=MAX_WIRE) as source:
        if CIPHER_MEMBER not in source.namelist():
            _need(len(raw) <= limit, 'PLAIN_ZIP_BOUND_INVALID')
            yield source
            return
        _need(source.namelist() == [CIPHER_MEMBER], 'ENCRYPTED_OUTER_LAYOUT_INVALID')
        _need(type(run.get('repository_id')) is int and run['repository_id'] == int(REPO_ID)
              and type(run.get('head_sha')) is str and _HEAD.fullmatch(run['head_sha'])
              and type(receipt.get('id')) is int and receipt['id'] > 0, 'ENCRYPTED_ARTIFACT_IDENTITY_INVALID')
        try:
            saved = datetime.fromisoformat(receipt['created_at'].replace('Z', '+00:00'))
            _need(saved.utcoffset() is not None, 'ARTIFACT_CLOCK_INVALID')
        except (KeyError, AttributeError, TypeError, ValueError):
            raise ValueError('PRIVATE_ORIGINAL_ARTIFACT_CLOCK_INVALID') from None
        entry = source.getinfo(CIPHER_MEMBER)
        _need(entry.file_size <= MAX_PLAIN_ZIP+MAX_OVERHEAD, 'ENVELOPE_BOUND_INVALID')
        cipher = source.read(entry)
        header, _, _, _ = _split(cipher)
        _need(len(raw)-header['plain_zip_size'] <= MAX_OVERHEAD, 'ARTIFACT_OVERHEAD_BOUND_INVALID')
        _need(header['run_id'] == str(run['id']) and header['head_sha'] == run['head_sha']
              and header['kind'] == kind, 'ENCRYPTED_ARTIFACT_SCOPE_INVALID')
        plain, _ = _open_envelope(cipher, key=key, max_plain_zip_bytes=limit)
        with _checked_zip(plain, max_zip_bytes=limit) as original:
            yield original
