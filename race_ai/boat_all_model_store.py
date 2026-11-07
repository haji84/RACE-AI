"""Dedicated encrypted persistence for actual BOAT model dispatch payloads.

Only opaque ciphertext, its authenticated public header, and Git locators are
published. Payload source/roster/stage/as-of semantics belong to the dispatch
caller. Git commit timestamps are untrusted metadata; an independently checked
artifact/commit receipt must establish any claimed physical pre-cutoff save.
"""
from datetime import datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .boat_pdca_github_handoff import GitStateRepository
from .boat_pdca_recipient import _json as bounded_json
from .boat_pdca_state import state_key


SCHEMA = "RACE_AI_BOAT_ALL_MODEL_FORECAST_V1"
DOMAIN = SCHEMA.encode("ascii")
PURPOSE = "boat-all-model-forecasts"
REPO_ID = "1416489937"
FORECAST_REF = "state/boat-all-model-forecasts"
MAGIC = b"RABAF1\0\0"
MAX_PLAIN = 24 * 1024 * 1024
MAX_WIRE = 36 * 1024 * 1024
MAX_HEADER = 8192
MAX_TREE_TOTAL = 8 * 1024 * 1024 * 1024
MAX_TREE_ENTRIES = 4096
CLOCK_AUTHORITY = "UNAUTHENTICATED_GIT_METADATA"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_HEAD = re.compile(r"[a-f0-9]{40}\Z")
_CIPHER = re.compile(r"forecasts/([a-f0-9]{64})\.enc\Z")


def _need(ok, reason):
    if not ok:
        raise ValueError("ALL_MODEL_FORECAST_" + reason)


def _sha(raw):
    return sha256(raw).hexdigest()


def _json_value(value, depth=0):
    _need(depth <= 64, "JSON_DEPTH_INVALID")
    if type(value) is dict:
        _need(all(type(key) is str for key in value), "JSON_KEY_INVALID")
        for child in value.values():
            _json_value(child, depth + 1)
    elif type(value) is list:
        for child in value:
            _json_value(child, depth + 1)
    elif type(value) is float:
        _need(math.isfinite(value), "JSON_NONFINITE_INVALID")
    else:
        _need(value is None or type(value) in (str, int, bool), "JSON_VALUE_INVALID")


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise ValueError("ALL_MODEL_FORECAST_JSON_INVALID") from None


def _json(raw, limit):
    try:
        value = bounded_json(raw, limit)
        _json_value(value)
        return value
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("ALL_MODEL_FORECAST_JSON_INVALID") from None


def _payload(value):
    _need(type(value) is dict and type(value.get("schema")) is str
          and 0 < len(value["schema"]) <= 128 and value["schema"].strip() == value["schema"], "PAYLOAD_SCHEMA_REQUIRED")
    _json_value(value)
    return value


def _hex(value, pattern=_SHA):
    _need(type(value) is str and pattern.fullmatch(value), "IDENTITY_INVALID")
    return value


def _header(value):
    fields = {"schema", "purpose", "repository_id", "run_id", "round_no", "plain_sha256", "plain_size", "encoding"}
    _need(type(value) is dict and set(value) == fields and value["schema"] == SCHEMA
          and value["purpose"] == PURPOSE and value["repository_id"] == REPO_ID
          and value["encoding"] == "json-utf8", "HEADER_INVALID")
    _need(type(value["run_id"]) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value["run_id"]), "RUN_ID_INVALID")
    _need(type(value["round_no"]) is int and 0 <= value["round_no"] <= 999999, "ROUND_INVALID")
    _need(type(value["plain_size"]) is int and 0 < value["plain_size"] <= MAX_PLAIN, "PLAIN_BOUND_INVALID")
    _hex(value["plain_sha256"])
    return value


def _key(key=None):
    root = state_key("production", key)
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=REPO_ID.encode("ascii"), info=DOMAIN).derive(root)


def _aad(header, nonce):
    return DOMAIN + b"\0" + _wire(header) + nonce


def _split(raw):
    _need(type(raw) is bytes and 40 < len(raw) <= MAX_WIRE and raw.startswith(MAGIC), "ENVELOPE_BOUND_INVALID")
    size = struct.unpack(">I", raw[8:12])[0]
    _need(0 < size <= MAX_HEADER and len(raw) >= 12 + size + 12 + 16, "HEADER_BOUND_INVALID")
    encoded = raw[12:12 + size]
    header = _header(_json(encoded, MAX_HEADER))
    _need(_wire(header) == encoded, "NONCANONICAL_HEADER")
    start = 12 + size
    nonce, cipher = raw[start:start + 12], raw[start + 12:]
    _need(len(cipher) == header["plain_size"] + 16, "CIPHER_SIZE_MISMATCH")
    return header, nonce, cipher


def forecast_header(raw):
    """Return the bounded public header; authenticity requires owner decryption."""
    return _split(raw)[0]


def seal_forecasts(payload, *, run_id, round_no, key=None) -> bytes:
    """Seal one dispatch payload; return bytes unchanged for artifact/Git saving.

    Requires the existing owner root key, explicitly supplied or available in
    Actions. No key generation, viewer-key fallback or source-time inference.
    """
    _payload(payload)
    plain = _wire(payload)
    header = _header(dict(schema=SCHEMA, purpose=PURPOSE, repository_id=REPO_ID,
                          run_id=run_id, round_no=round_no, plain_sha256=_sha(plain),
                          plain_size=len(plain), encoding="json-utf8"))
    encoded = _wire(header)
    _need(len(encoded) <= MAX_HEADER, "HEADER_BOUND_INVALID")
    nonce = os.urandom(12)
    cipher = AESGCM(_key(key)).encrypt(nonce, plain, _aad(header, nonce))
    raw = MAGIC + struct.pack(">I", len(encoded)) + encoded + nonce + cipher
    _need(len(raw) <= MAX_WIRE, "ENVELOPE_BOUND_INVALID")
    return raw


def open_forecasts(raw, *, key=None):
    """Authenticate repo/run/round/hash and return only the private payload."""
    header, nonce, cipher = _split(raw)
    derived = _key(key)
    try:
        plain = AESGCM(derived).decrypt(nonce, cipher, _aad(header, nonce))
    except Exception:
        raise ValueError("ALL_MODEL_FORECAST_AUTHENTICATION_FAILED") from None
    _need(len(plain) == header["plain_size"] and _sha(plain) == header["plain_sha256"], "PLAIN_HASH_MISMATCH")
    payload = _payload(_json(plain, MAX_PLAIN))
    _need(_wire(payload) == plain, "NONCANONICAL_PAYLOAD")
    return payload


class GitForecastRepository(GitStateRepository):
    """Existing remote/rewrite/CAS guards with a separate, fixed forecast ref."""
    def __init__(self, repo):
        self.ref = FORECAST_REF
        self.repo = Path(repo).resolve()
        self._reject_rewrites()
        self._check_remote()


def _transport(repo, transport):
    git = transport if transport is not None else GitForecastRepository(repo)
    _need(git.ref == FORECAST_REF, "FIXED_REF_REQUIRED")
    return git


def _latest(value):
    _need(type(value) is dict and set(value) == {"schema", "purpose", "repository_id", "ref", "cipher_path", "cipher_sha256", "header"}
          and value["schema"] == SCHEMA and value["purpose"] == PURPOSE
          and value["repository_id"] == REPO_ID and value["ref"] == FORECAST_REF, "LATEST_INVALID")
    _hex(value["cipher_sha256"])
    _need(value["cipher_path"] == "forecasts/" + value["cipher_sha256"] + ".enc", "CIPHER_PATH_INVALID")
    _header(value["header"])
    return value


def _tree(git, commit):
    _hex(commit, _HEAD)
    raw = git._run(["ls-tree", "-rlz", "--full-tree", commit])
    _need(len(raw) <= 4 * 1024 * 1024, "TREE_BOUND_INVALID")
    paths = {}
    latest_raw = None
    total = 0
    for row in raw.split(b"\0"):
        if not row:
            continue
        try:
            details, name = row.split(b"\t", 1)
            mode, kind, oid, size = details.split()
            name = name.decode("ascii")
            length = int(size)
        except (ValueError, UnicodeError):
            raise ValueError("ALL_MODEL_FORECAST_TREE_INVALID") from None
        _need(mode == b"100644" and kind == b"blob" and name not in paths
              and (name == "latest.json" or _CIPHER.fullmatch(name)), "TREE_ALLOWLIST_INVALID")
        limit = MAX_HEADER * 2 if name == "latest.json" else MAX_WIRE
        _need(0 < length <= limit, "TREE_BLOB_BOUND_INVALID")
        total += length
        _need(total <= MAX_TREE_TOTAL and len(paths) < MAX_TREE_ENTRIES, "TREE_TOTAL_BOUND_INVALID")
        body = git.read(commit, name, limit)
        _need(len(body) == length, "TREE_BLOB_SIZE_MISMATCH")
        if name == "latest.json":
            latest_raw = body
            paths[name] = None
        else:
            _need(_sha(body) == _CIPHER.fullmatch(name).group(1), "IMMUTABLE_CIPHER_HASH_INVALID")
            paths[name] = forecast_header(body)
    _need("latest.json" in paths and len(paths) >= 2, "INHERITED_LATEST_REQUIRED")
    latest = _latest(_json(latest_raw, MAX_HEADER * 2))
    _need(_wire(latest) + b"\n" == latest_raw, "NONCANONICAL_LATEST")
    _need(latest["cipher_path"] in paths and paths[latest["cipher_path"]] == latest["header"], "LATEST_CIPHER_MISMATCH")
    return paths, latest


def _commit_at(git, commit):
    _hex(commit, _HEAD)
    value = git._run(["show", "-s", "--no-show-signature", "--format=%cI", commit]).decode("ascii").strip()
    _timestamp(value)
    return value


def _timestamp(value):
    try:
        _need(type(value) is str, "COMMIT_TIMESTAMP_INVALID")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(parsed.utcoffset() is not None, "COMMIT_TIMESTAMP_INVALID")
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise ValueError("ALL_MODEL_FORECAST_COMMIT_TIMESTAMP_INVALID") from None


def _pointer(git, commit, latest):
    return dict(latest, status="READY", source_commit=_hex(commit, _HEAD),
                git_commit_at=_commit_at(git, commit), commit_clock_authority=CLOCK_AUTHORITY)


def _validate_pointer(pointer):
    additional = {"status", "source_commit", "git_commit_at", "commit_clock_authority"}
    _need(type(pointer) is dict and set(pointer) == {"schema", "purpose", "repository_id", "ref", "cipher_path", "cipher_sha256", "header"} | additional
          and pointer["status"] == "READY" and pointer["commit_clock_authority"] == CLOCK_AUTHORITY, "POINTER_INVALID")
    _hex(pointer["source_commit"], _HEAD)
    _timestamp(pointer["git_commit_at"])
    _latest({name: value for name, value in pointer.items() if name not in additional})
    return pointer


def publish_forecasts(raw, repo, *, expected_parent, transport=None):
    """Append one immutable ciphertext and latest.json using an explicit CAS.

    The returned git_commit_at is merely commit metadata. Preserve the exact
    ciphertext bytes across artifact publication and independent receipt checks.
    """
    header = forecast_header(raw)
    digest = _sha(raw)
    latest = _latest(dict(schema=SCHEMA, purpose=PURPOSE, repository_id=REPO_ID, ref=FORECAST_REF,
                          cipher_path="forecasts/" + digest + ".enc", cipher_sha256=digest, header=header))
    git = _transport(repo, transport)
    parent = git.head()
    _need(parent == expected_parent, "REF_CONCURRENT_UPDATE")
    paths = {}
    if parent is not None:
        git.fetch(parent)
        paths, previous = _tree(git, parent)
    path = latest["cipher_path"]
    encoded = _wire(latest) + b"\n"
    if path in paths:
        _need(git.read(parent, path, MAX_WIRE) == raw, "IMMUTABLE_CIPHER_CHANGED")
        if previous == latest:
            return _pointer(git, parent, latest)
    commit = git.commit({path: raw, "latest.json": encoded}, parent)
    new_paths, new_latest = _tree(git, commit)
    _need(set(paths) <= set(new_paths)
          and all(new_paths[name] == header for name, header in paths.items() if name != "latest.json")
          and new_latest == latest, "INHERITED_CIPHERS_REMOVED_OR_CHANGED")
    git.push(commit, parent)
    _need(git.read(commit, path, MAX_WIRE) == raw
          and git.read(commit, "latest.json", MAX_HEADER * 2) == encoded, "REMOTE_READBACK_MISMATCH")
    return _pointer(git, commit, latest)


def restore_forecasts(pointer, repo, *, key=None, transport=None):
    """Return the exact private payload from a pinned commit; write no plaintext."""
    _validate_pointer(pointer)
    _key(key)  # Missing owner key stops before any Git/source operations.
    git = _transport(repo, transport)
    commit = pointer["source_commit"]
    git.fetch(commit)
    paths, latest = _tree(git, commit)
    _need(_pointer(git, commit, latest) == pointer, "PINNED_POINTER_MISMATCH")
    raw = git.read(commit, pointer["cipher_path"], MAX_WIRE)
    _need(_sha(raw) == pointer["cipher_sha256"] and forecast_header(raw) == pointer["header"], "PINNED_CIPHER_MISMATCH")
    return open_forecasts(raw, key=key)
