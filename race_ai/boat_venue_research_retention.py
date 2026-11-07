"""Retain private research ciphertext with the existing append-only publisher.

Only an ephemeral HTTPS Git authentication header is added to subprocess
configuration. Repository/global Git configuration and existing credentials
are never written. The caller must use its existing GitHub HTTPS checkout.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat

from .boat_pdca_state import state_key
from .boat_venue_learning_handoff import FILES, publish_learning_candidate
from .boat_venue_history_handoff import GitStateRepository, PREFIX, TRANSFER_REF
from .boat_venue_dataset import _bytes, _sha
from .boat_venue_research_receipt import MAX_ARCHIVE_BYTES, verify_private_p1_artifact
from .all_existing_model_receipt import verify_private_pairs_artifact
from .all_existing_model_result_intake import observations_from_result_artifact
from .actions_contract import digest
from .permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _read
from scripts.boat_history_collect import private_root


def _need(ok, reason):
    if not ok:
        raise ValueError('VENUE_RESEARCH_RETENTION_'+reason)


ARCHIVE_FILES = {'archive.zip': MAX_ARCHIVE_BYTES, 'metadata.json': 32*1024}
REMOTE_ARCHIVE_FILES = dict(ARCHIVE_FILES, **{'manifest.json': 32*1024})


def _folders(values, *, files=FILES):
    _need(type(values) is list and len(values) <= 10000, 'BOUNDED_FOLDER_LIST_REQUIRED')
    result = []; seen = set()
    for value in values:
        _need(isinstance(value, (str, os.PathLike)), 'PRIVATE_FOLDER_REQUIRED')
        path = Path(value).absolute()
        _need('..' not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)) and
              path.is_dir(), 'PRIVATE_FOLDER_REQUIRED')
        # Check both levels without creating or relaxing a directory. All
        # paths finish preflight before even the first Git publisher is called.
        private_root(path.parent); private_root(path)
        _need({p.name for p in path.iterdir()} == set(files), 'PRIVATE_FILES_REQUIRED')
        for name, limit in files.items():
            file = path/name; metadata = file.lstat()
            _need(stat.S_ISREG(metadata.st_mode) and not metadata.st_mode & 0o077 and
                  0 < metadata.st_size <= limit, 'PRIVATE_FILES_REQUIRED')
        path = path.resolve()
        if path not in seen:
            seen.add(path); result.append(path)
    return result


@contextmanager
def _git_auth(token):
    raw_count = os.environ.get('GIT_CONFIG_COUNT', '0')
    _need(re.fullmatch('[0-9]{1,5}', raw_count) and int(raw_count) <= 10000,
          'GIT_ENVIRONMENT_INVALID')
    count = int(raw_count)
    encoded = base64.b64encode(('x-access-token:'+token).encode('ascii')).decode('ascii')
    changes = {'GIT_CONFIG_COUNT': str(count+1),
               'GIT_CONFIG_KEY_'+str(count): 'http.https://github.com/.extraheader',
               'GIT_CONFIG_VALUE_'+str(count): 'Authorization: basic '+encoded,
               'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never'}
    previous = {key: os.environ.get(key) for key in changes}
    try:
        os.environ.update(changes)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def retain_private_research(folders, repo, *, token=None):
    """Retain exact forecast/PDCA ciphertext; return public pointers and counts.

    Every path is an explicit private three-file folder outside Git. The
    existing publisher authenticates its ciphertext, appends on the existing
    transfer ref, and verifies byte-identical remote readback. No force update,
    source rights grant, storage service or production adoption is introduced.
    """
    state_key('production')
    token = os.environ.get('GH_TOKEN', '') if token is None else token
    _need(type(token) is str and re.fullmatch('[A-Za-z0-9_.-]{20,512}', token),
          'GITHUB_TOKEN_REQUIRED')
    roots = _folders(folders)
    pointers = []
    with _git_auth(token):
        for root in roots:
            pointers.append(publish_learning_candidate(root, repo))
    return dict(status='OWNER_PRIVATE_RESEARCH_RETENTION_VERIFIED',
                requested_folders=len(folders), retained_folders=len(roots), pointers=pointers,
                plaintext_published=False, production_promoted=False)


def _source_manifest(raw, metadata_raw, metadata, admission, key):
    state = dict(schema='RACE_AI_OWNER_PRIVATE_SOURCE_ARCHIVE_V1', repository_id='1416489937',
        archive_sha256=_sha(raw), metadata_sha256=_sha(metadata_raw),
        archive_size_bytes=len(raw), metadata_size_bytes=len(metadata_raw),
        source_artifact_id=metadata['id'], source_admission_sha256=digest(admission),
        provider_permission_confirmed=False, production_promoted=False, plaintext_published=False)
    domain_key = hmac.digest(key, b'RACE_AI_OWNER_PRIVATE_SOURCE_ARCHIVE_MANIFEST_V1', 'sha256')
    mac = hmac.new(domain_key, _bytes(state), hashlib.sha256).hexdigest()
    return _bytes(dict(state=state, mac=mac))


def _source_intake(root, now, key):
    raw = _read(root/'archive.zip', ARCHIVE_FILES['archive.zip'])
    metadata_raw = _read(root/'metadata.json', ARCHIVE_FILES['metadata.json'])
    # Preserve exact source bytes only after rejecting hidden leading/trailing
    # material and comments outside the authenticated encrypted-file layout.
    _need(raw.startswith(b'PK\x03\x04') and len(raw) >= 22 and
          raw[-22:-18] == b'PK\x05\x06' and raw[-2:] == b'\0\0', 'SOURCE_ZIP_ENVELOPE_INVALID')
    metadata = read_json_bytes(metadata_raw)
    _need(type(metadata) is dict and type(metadata.get('workflow_run')) is dict,
          'SOURCE_METADATA_INVALID')
    run = metadata['workflow_run']
    name = metadata.get('name')
    if type(name) is str and name.startswith('race-existing-cycle-'):
        # Preserve the complete authenticated RESULT wrapper. Its journal stays
        # encrypted; only the receipt hash enters the existing source manifest.
        admission = observations_from_result_artifact(raw, metadata, now=now,
            expected_run_id=run.get('id'), expected_head_sha=run.get('head_sha'))['receipt']
    else:
        verifier = (verify_private_pairs_artifact if type(name) is str and
                    name.startswith('all-existing-model-pairs-') else verify_private_p1_artifact)
        admission = verifier(raw, metadata, now=now,
            expected_run_id=run.get('id'), expected_head_sha=run.get('head_sha'))
    manifest = _source_manifest(raw, metadata_raw, metadata, admission, key)
    # Keep descriptors rather than every archive's potentially 64 MiB bytes.
    # Each exact archive is read once more and hash-bound before publication.
    return dict(root=root, archive_sha256=_sha(raw), metadata_sha256=_sha(metadata_raw),
                manifest=manifest, artifact_id=metadata['id'])


def retain_private_source_archives(archives, repo, *, token=None, now=None):
    """Append original ciphertext ZIPs and cached actual metadata on TRANSFER_REF.

    Cached metadata must be the caller's actual GitHub response. Every archive
    undergoes the existing owner-decryption/native replay and external-clock
    checks before any Git operation. Expired receipts remain inadmissible;
    preserving their earlier evidence never creates a new GitHub receipt.
    """
    key = state_key('production')
    token = os.environ.get('GH_TOKEN', '') if token is None else token
    _need(type(token) is str and re.fullmatch('[A-Za-z0-9_.-]{20,512}', token), 'GITHUB_TOKEN_REQUIRED')
    now = datetime.now(timezone.utc) if now is None else now
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    roots = _folders(archives, files=ARCHIVE_FILES)
    records = [_source_intake(root, now, key) for root in roots]
    pointers = []
    with _git_auth(token):
        git = None
        for record in records:
            raw = _read(record['root']/'archive.zip', ARCHIVE_FILES['archive.zip'])
            metadata_raw = _read(record['root']/'metadata.json', ARCHIVE_FILES['metadata.json'])
            _need(_sha(raw) == record['archive_sha256'] and _sha(metadata_raw) == record['metadata_sha256'],
                  'SOURCE_CHANGED_AFTER_AUTHENTICATION')
            if git is None:
                git = GitStateRepository(repo, ref=TRANSFER_REF)
                _need(getattr(git, 'ref', None) == TRANSFER_REF, 'TRANSFER_REF_REQUIRED')
            parent = git.head()
            _need(type(parent) is str and re.fullmatch('[a-f0-9]{40}', parent), 'EXISTING_TRANSFER_REF_REQUIRED')
            git.fetch(parent)
            prefix = PREFIX+'research-archives/'+record['archive_sha256']+'/'
            files = {'archive.zip': raw, 'metadata.json': metadata_raw, 'manifest.json': record['manifest']}
            additions = {}
            for name, body in files.items():
                path = prefix+name
                if git.exists(parent, path):
                    _need(git.read(parent, path, REMOTE_ARCHIVE_FILES[name]) == body, 'SOURCE_IMMUTABLE_FILE_CHANGED')
                else:
                    additions[path] = body
            commit = parent
            if additions:
                commit = git.commit(additions, parent)
                _need(type(commit) is str and re.fullmatch('[a-f0-9]{40}', commit), 'SOURCE_COMMIT_INVALID')
                git.push(commit, parent); git.fetch(commit)
            for name, body in files.items():
                _need(git.read(commit, prefix+name, REMOTE_ARCHIVE_FILES[name]) == body, 'SOURCE_REMOTE_READBACK_MISMATCH')
            pointers.append(dict(schema='RACE_AI_PRIVATE_SOURCE_ARCHIVE_INPUT_V1', status='READY',
                repository_id='1416489937', source_commit=commit, source_artifact_id=record['artifact_id'],
                archive_path=prefix+'archive.zip', archive_sha256=record['archive_sha256'],
                metadata_path=prefix+'metadata.json', metadata_sha256=record['metadata_sha256'],
                manifest_path=prefix+'manifest.json', manifest_sha256=_sha(record['manifest'])))
    return dict(status='OWNER_PRIVATE_SOURCE_ARCHIVES_RETENTION_VERIFIED', requested_archives=len(archives),
                retained_archives=len(pointers), pointers=pointers, plaintext_published=False, production_promoted=False)
