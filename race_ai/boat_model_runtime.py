"""Owner-recipient model inputs on an isolated encrypted Git ref.

``seal_runtime`` returns (binary_envelope, public_header); ``open_runtime``
returns private file bytes. ``publish_runtime`` returns the pinned pointer for
audit/state/boat-model-runtime-input.json. ``restore_runtime`` returns a safe
receipt plus private output paths, never the file contents. No canonical PDCA
database, transfer encryption domain or Git ref is changed.
"""
from datetime import datetime
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import tempfile
import zipfile
import zlib

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .boat_pdca_recipient import _receiver, _private, _json as bounded_json
from .boat_pdca_github_handoff import GitStateRepository
from scripts.boat_history_collect import private_root


SCHEMA = "RACE_AI_BOAT_MODEL_RUNTIME_V1"
DOMAIN = SCHEMA.encode("ascii")
PURPOSE = "boat-model-runtime"
REPO_ID = "1416489937"
RUNTIME_REF = "state/boat-model-runtime"
INPUT_PATH = "audit/state/boat-model-runtime-input.json"
MAGIC = b"RABMR1\0\0"
MAX_HEADER = 16 * 1024
MAX_SEALED = 96 * 1024 * 1024
MAX_TREE_TOTAL = 8 * 1024 * 1024 * 1024
MAX_TREE_ENTRIES = 4096
FILE_LIMITS = {"history.sqlite": 256 * 1024 * 1024, "racers.sqlite": 16 * 1024 * 1024,
               "ranker.json": 4 * 1024 * 1024, "native-view.json": 24 * 1024 * 1024,
               "p0-source.json": 8 * 1024 * 1024,
               "prospective-budget-plan.json": 16 * 1024 * 1024,
               "metadata.json": 1024 * 1024}
REQUIRED = frozenset({"history.sqlite", "racers.sqlite", "ranker.json", "metadata.json"})
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_HEAD = re.compile(r"[a-f0-9]{40}\Z")
_CIPHER = re.compile(r"runtime/([a-f0-9]{64})\.enc\Z")


def _need(ok, reason):
    if not ok:
        raise ValueError("MODEL_RUNTIME_" + reason)


def _sha(raw):
    return sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _json(raw, limit):
    try:
        value = bounded_json(raw, limit)
        stack = [(value, 0)]
        while stack:
            item, depth = stack.pop()
            _need(depth <= 64, "JSON_DEPTH_INVALID")
            if type(item) is float:
                _need(math.isfinite(item), "JSON_NONFINITE_INVALID")
            elif type(item) is dict:
                stack.extend((child, depth + 1) for child in item.values())
            elif type(item) is list:
                stack.extend((child, depth + 1) for child in item)
        return value
    except (ValueError, TypeError, OverflowError):
        raise ValueError("MODEL_RUNTIME_JSON_INVALID") from None


def _stamp(value):
    try:
        _need(type(value) is str, "TIMESTAMP_INVALID")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(parsed.utcoffset() is not None, "TIMESTAMP_INVALID")
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise ValueError("MODEL_RUNTIME_TIMESTAMP_INVALID") from None


def _hex(value, pattern=_SHA):
    _need(type(value) is str and pattern.fullmatch(value) is not None, "IDENTITY_INVALID")
    return value


def _header(value):
    fields = {"schema", "purpose", "repository_id", "recipient_key_id", "receiver_document_sha256",
              "receiver_run_id", "receiver_source_head", "created_at", "files"}
    _need(type(value) is dict and set(value) == fields and value["schema"] == SCHEMA
          and value["purpose"] == PURPOSE and value["repository_id"] == REPO_ID, "HEADER_INVALID")
    for field in ("recipient_key_id", "receiver_document_sha256"):
        _hex(value[field])
    _hex(value["receiver_source_head"], _HEAD)
    _need(type(value["receiver_run_id"]) is str
          and re.fullmatch(r"[1-9][0-9]{0,19}", value["receiver_run_id"]), "RECEIVER_RUN_INVALID")
    _stamp(value["created_at"])
    files = value["files"]
    _need(type(files) is dict and REQUIRED <= set(files) <= set(FILE_LIMITS), "FILE_WHITELIST_INVALID")
    for name, info in files.items():
        _need(type(info) is dict and set(info) == {"sha256", "size"}
              and type(info["size"]) is int and 0 < info["size"] <= FILE_LIMITS[name], "FILE_BOUND_INVALID")
        _hex(info["sha256"])
    return value


def _validate_file(name, raw):
    _need(type(raw) is bytes and 0 < len(raw) <= FILE_LIMITS[name], "FILE_BOUND_INVALID")
    if name.endswith(".sqlite"):
        _need(raw.startswith(b"SQLite format 3\0"), "SQLITE_INVALID")
        db = sqlite3.connect(":memory:")
        try:
            db.deserialize(raw)
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA query_only=ON")
            _need(db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "SQLITE_INVALID")
        except sqlite3.Error:
            raise ValueError("MODEL_RUNTIME_SQLITE_INVALID") from None
        finally:
            db.close()
    else:
        doc = _json(raw, FILE_LIMITS[name])
        _need(type(doc) is dict or name == "native-view.json" and type(doc) is list, "JSON_DOCUMENT_INVALID")


def _aad(header, ephemeral, nonce):
    return DOMAIN + b"\0" + _wire(header) + ephemeral + nonce


def _session(shared, header, ephemeral, recipient):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=recipient,
                info=DOMAIN + b"/transport/" + ephemeral + _wire(header)).derive(shared)


def _split(raw):
    _need(type(raw) is bytes and len(MAGIC) + 4 + 44 + 16 < len(raw) <= MAX_SEALED
          and raw.startswith(MAGIC), "ENVELOPE_BOUND_INVALID")
    size = struct.unpack(">I", raw[8:12])[0]
    _need(0 < size <= MAX_HEADER and len(raw) >= 12 + size + 44 + 16, "HEADER_BOUND_INVALID")
    encoded = raw[12:12 + size]
    header = _header(_json(encoded, MAX_HEADER))
    _need(_wire(header) == encoded, "NONCANONICAL_HEADER")
    start = 12 + size
    return header, raw[start:start + 32], raw[start + 32:start + 44], raw[start + 44:]


def seal_runtime(files: dict[str, bytes], receiver, *, created_at):
    """Seal exact whitelisted files using only the owner's public recipient.

    The caller authenticates the receiver artifact before supplying it. The
    returned header contains sizes and SHA-256 identities, never file bodies.
    Ranker fit semantics remain the native model loader's responsibility.
    """
    public = _receiver(receiver)
    _need(type(files) is dict and REQUIRED <= set(files) <= set(FILE_LIMITS), "FILE_WHITELIST_INVALID")
    _stamp(created_at)
    for name, raw in files.items():
        _validate_file(name, raw)
    # Receiver wire matches the existing authenticated recipient artifact.
    from .boat_history_store import wire
    header = _header(dict(schema=SCHEMA, purpose=PURPOSE, repository_id=REPO_ID,
                          recipient_key_id=receiver["key_id"], receiver_document_sha256=_sha((wire(receiver) + "\n").encode()),
                          receiver_run_id=receiver["run_id"], receiver_source_head=receiver["source_head"],
                          created_at=created_at,
                          files={name: dict(size=len(raw), sha256=_sha(raw)) for name, raw in sorted(files.items())}))
    encoded = _wire(header)
    _need(len(encoded) <= MAX_HEADER, "HEADER_BOUND_INVALID")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, raw)
    zipped = output.getvalue()
    _need(len(zipped) + len(encoded) + 72 <= MAX_SEALED, "ENVELOPE_BOUND_INVALID")
    ephemeral = X25519PrivateKey.generate()
    epub = ephemeral.public_key().public_bytes_raw()
    try:
        shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(public))
    except ValueError:
        raise ValueError("MODEL_RUNTIME_PUBLIC_RECIPIENT_INVALID") from None
    nonce = os.urandom(12)
    cipher = AESGCM(_session(shared, header, epub, public)).encrypt(nonce, zipped, _aad(header, epub, nonce))
    envelope = MAGIC + struct.pack(">I", len(encoded)) + encoded + epub + nonce + cipher
    _need(len(envelope) <= MAX_SEALED, "ENVELOPE_BOUND_INVALID")
    return envelope, header


def _open_zip(zipped, header):
    _need(len(zipped) >= 22 and zipped[-22:-18] == b"PK\x05\x06"
          and zipped[-2:] == b"\0\0", "ZIP_FRAMING_INVALID")
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
            infos = archive.infolist()
            _need(not archive.comment and len(infos) == len(header["files"])
                  and {info.filename for info in infos} == set(header["files"]), "ZIP_MEMBERS_INVALID")
            _need(len({info.filename for info in infos}) == len(infos), "ZIP_DUPLICATE_MEMBER")
            _need(min(info.header_offset for info in infos) == 0, "ZIP_PREFIX_INVALID")
            total = 0
            for info in infos:
                expected = header["files"][info.filename]
                mode = stat.S_IFMT(info.external_attr >> 16)
                _need(info.filename == info.orig_filename and not info.is_dir()
                      and mode in (0, stat.S_IFREG) and not info.flag_bits & 1
                      and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                      and info.file_size == expected["size"]
                      and 0 <= info.compress_size <= len(zipped), "ZIP_MEMBER_INVALID")
                total += info.file_size
                _need(total <= sum(FILE_LIMITS.values()), "ZIP_TOTAL_BOUND_INVALID")
                with archive.open(info) as stream:
                    raw = stream.read(expected["size"] + 1)
                _need(len(raw) == expected["size"] and _sha(raw) == expected["sha256"], "FILE_HASH_MISMATCH")
                _validate_file(info.filename, raw)
                files[info.filename] = raw
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError, OSError):
        raise ValueError("MODEL_RUNTIME_ZIP_INVALID") from None
    return files


def open_runtime(raw, *, key=None) -> dict[str, bytes]:
    """Authenticate and return private bytes; missing/wrong owner key fails closed."""
    header, epub, nonce, cipher = _split(raw)
    owner = _private(key)
    public = owner.public_key().public_bytes_raw()
    _need(_sha(public) == header["recipient_key_id"], "OWNER_RECIPIENT_MISMATCH")
    try:
        shared = owner.exchange(X25519PublicKey.from_public_bytes(epub))
        zipped = AESGCM(_session(shared, header, epub, public)).decrypt(nonce, cipher, _aad(header, epub, nonce))
    except Exception:
        raise ValueError("MODEL_RUNTIME_AUTHENTICATION_FAILED") from None
    return _open_zip(zipped, header)


class GitRuntimeRepository(GitStateRepository):
    """The existing URL/rewrite/CAS guards, with one separate fixed ref.

    The canonical GitStateRepository allowlist is deliberately unchanged.
    """
    def __init__(self, repo):
        self.ref = RUNTIME_REF
        self.repo = Path(repo).resolve()
        self._reject_rewrites()
        self._check_remote()

    def commit_snapshot(self, files, parent):
        """Write a bounded current tree while preserving every parent object."""
        if parent is not None:
            _hex(parent, _HEAD)
        with tempfile.TemporaryDirectory(prefix='boat-runtime-head-') as folder:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(folder) / 'index'))
            self._run(['read-tree', '--empty'], env=env)
            for path, raw in sorted(files.items()):
                blob = self._run(['hash-object', '-w', '--stdin'], body=raw, env=env).decode().strip()
                self._run(['update-index', '--add', '--cacheinfo', '100644,' + blob + ',' + path], env=env)
            tree = self._run(['write-tree'], env=env).decode().strip()
            args = ['-c', 'user.name=RACE-AI encrypted state',
                    '-c', 'user.email=race-ai-state@users.noreply.github.com',
                    '-c', 'commit.gpgSign=false', 'commit-tree', tree]
            if parent is not None:
                args += ['-p', parent]
            return self._run(args, body=b'Retain bounded owner-encrypted model runtime\n', env=env).decode().strip()


def _transport(repo, transport):
    git = transport if transport is not None else GitRuntimeRepository(repo)
    _need(git.ref == RUNTIME_REF, "FIXED_REF_REQUIRED")
    return git


def _latest(value):
    _need(type(value) is dict and set(value) == {"schema", "purpose", "repository_id", "ref", "cipher_path", "cipher_sha256", "header"}
          and value["schema"] == SCHEMA and value["purpose"] == PURPOSE
          and value["repository_id"] == REPO_ID and value["ref"] == RUNTIME_REF, "LATEST_INVALID")
    _header(value["header"])
    _hex(value["cipher_sha256"])
    _need(value["cipher_path"] == "runtime/" + value["cipher_sha256"] + ".enc", "CIPHER_PATH_INVALID")
    return value


def _tree(git, commit):
    """Audit every blob, including legacy accumulated trees, before use."""
    _hex(commit, _HEAD)
    raw = git._run(["ls-tree", "-rlz", "--full-tree", commit])
    _need(len(raw) <= 4 * 1024 * 1024, "TREE_BOUND_INVALID")
    paths = {}
    total = 0
    latest_raw = None
    for row in raw.split(b"\0"):
        if not row:
            continue
        try:
            details, name = row.split(b"\t", 1)
            mode, kind, oid, size = details.split()
            name = name.decode("ascii")
            length = int(size)
        except (ValueError, UnicodeError):
            raise ValueError("MODEL_RUNTIME_TREE_INVALID") from None
        _need(mode == b"100644" and kind == b"blob" and name not in paths
              and (name == "latest.json" or _CIPHER.fullmatch(name)), "TREE_ALLOWLIST_INVALID")
        limit = MAX_HEADER * 2 if name == "latest.json" else MAX_SEALED
        _need(0 < length <= limit, "TREE_BLOB_BOUND_INVALID")
        total += length
        _need(total <= MAX_TREE_TOTAL and len(paths) < MAX_TREE_ENTRIES, "TREE_TOTAL_BOUND_INVALID")
        body = git.read(commit, name, limit)
        _need(len(body) == length, "TREE_BLOB_SIZE_MISMATCH")
        if name != "latest.json":
            _need(_sha(body) == _CIPHER.fullmatch(name).group(1), "IMMUTABLE_CIPHER_HASH_INVALID")
            header = _split(body)[0]
            paths[name] = dict(size=length, header=header)
        else:
            latest_raw = body
            paths[name] = dict(size=length)
    _need("latest.json" in paths and len(paths) >= 2, "INHERITED_LATEST_REQUIRED")
    latest = _latest(_json(latest_raw, MAX_HEADER * 2))
    _need(_wire(latest) + b"\n" == latest_raw, "NONCANONICAL_LATEST")
    _need(latest["cipher_path"] in paths
          and paths[latest["cipher_path"]]["header"] == latest["header"], "LATEST_CIPHER_MISMATCH")
    return paths, latest


def _pointer(commit, latest):
    return dict(latest, status="READY", source_commit=_hex(commit, _HEAD))


def _validate_pointer(pointer):
    _need(type(pointer) is dict and set(pointer) == {"schema", "purpose", "repository_id", "ref", "cipher_path", "cipher_sha256", "header", "status", "source_commit"}
          and pointer["status"] == "READY", "POINTER_INVALID")
    _hex(pointer["source_commit"], _HEAD)
    _latest({name: value for name, value in pointer.items() if name not in {"status", "source_commit"}})
    return pointer


def publish_runtime(raw, repo, *, expected_parent, transport=None):
    """Publish only current encrypted bytes and latest.json with a CAS parent.

    ``expected_parent=None`` initializes the separate ref only if it is absent.
    All inherited paths, blob hashes and envelope headers are audited first.
    Older ciphertext stays unchanged and reachable through Git ancestry; old
    pinned pointers continue to restore the complete tree they authenticated.
    No owner private key is needed to publish a public-recipient envelope.
    """
    header = _split(raw)[0]
    digest = _sha(raw)
    latest = _latest(dict(schema=SCHEMA, purpose=PURPOSE, repository_id=REPO_ID, ref=RUNTIME_REF,
                          cipher_path="runtime/" + digest + ".enc", cipher_sha256=digest, header=header))
    git = _transport(repo, transport)
    parent = git.head()
    _need(parent == expected_parent, "REF_CONCURRENT_UPDATE")
    paths = {}
    if parent is not None:
        git.fetch(parent)
        paths, previous = _tree(git, parent)
        _need(_stamp(header["created_at"]) >= _stamp(previous["header"]["created_at"]), "CREATED_AT_REGRESSION")
    encoded = _wire(latest) + b"\n"
    path = latest["cipher_path"]
    if path in paths:
        _need(git.read(parent, path, MAX_SEALED) == raw, "IMMUTABLE_CIPHER_CHANGED")
        if previous == latest:
            return _pointer(parent, latest)
    commit = git.commit_snapshot({path: raw, "latest.json": encoded}, parent)
    written, _ = _tree(git, commit)
    _need(set(written) == {path, "latest.json"}, "SNAPSHOT_TREE_INVALID")
    git.push(commit, parent)
    _need(git.read(commit, path, MAX_SEALED) == raw
          and git.read(commit, "latest.json", MAX_HEADER * 2) == encoded, "REMOTE_READBACK_MISMATCH")
    return _pointer(commit, latest)


def restore_runtime(pointer, repo, private_dir, *, key=None, transport=None):
    """Restore exact pinned encrypted bytes to a fresh 0700 directory outside Git.

    Failures raise ValueError/OSError; callers stop only this optional model
    path. Existing files are never overwritten and canonical state is untouched.
    ``files`` in the result maps whitelisted names to private filesystem paths.
    """
    _validate_pointer(pointer)
    # Reject absent owner keys before any remote Git operations.
    owner_public = _private(key).public_key().public_bytes_raw()
    _need(_sha(owner_public) == pointer["header"]["recipient_key_id"], "OWNER_RECIPIENT_MISMATCH")
    target = Path(private_dir).absolute()
    _need(not any(part.is_symlink() for part in (target, *target.parents)), "PRIVATE_SYMLINK_REJECTED")
    resolved = target.resolve()
    _need(not any((part / ".git").exists() for part in (resolved, *resolved.parents)), "PRIVATE_OUTSIDE_GIT_REQUIRED")
    _need(not resolved.is_relative_to(Path(repo).resolve()), "PRIVATE_OUTSIDE_REPOSITORY_REQUIRED")
    _need(not target.exists() or target.is_dir() and not any(target.iterdir()), "OUTPUT_EXISTS_DO_NOT_RESET")
    git = _transport(repo, transport)
    commit = pointer["source_commit"]
    git.fetch(commit)
    paths, latest = _tree(git, commit)
    _need(latest == {name: value for name, value in pointer.items() if name not in {"status", "source_commit"}}, "PINNED_LATEST_MISMATCH")
    raw = git.read(commit, pointer["cipher_path"], MAX_SEALED)
    _need(_sha(raw) == pointer["cipher_sha256"] and _split(raw)[0] == pointer["header"], "PINNED_CIPHER_MISMATCH")
    files = open_runtime(raw, key=key)
    root = private_root(target)
    _need(not any(root.iterdir()), "OUTPUT_EXISTS_DO_NOT_RESET")
    written = []
    try:
        for name, body in sorted(files.items()):
            path = root / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            written.append(path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return dict(status="OWNER_MODEL_RUNTIME_RESTORED", source_commit=commit,
                cipher_sha256=pointer["cipher_sha256"], header=pointer["header"],
                files={name: str(root / name) for name in sorted(files)}, plaintext_published=False)
