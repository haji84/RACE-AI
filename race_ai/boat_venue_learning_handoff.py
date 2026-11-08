"""Retain authenticated learning ciphertext on the existing transfer state ref.

This persistence pointer is not an independent future shadow receipt. It grants
no training rights, promotes no model, and exposes no fitted parameters.
"""
import json
from pathlib import Path
import re
import tempfile

from .boat_observed_pairwise_models import MODEL_IDS
from .boat_venue_dataset import _bytes, _sha
from .boat_venue_history_handoff import GitStateRepository, TRANSFER_REF, PREFIX
from .boat_venue_learning import read_candidate
from .observed_weight_learning import verify_training
from .teiai_history import need
from scripts.boat_all_racers import _key_ready, _read, _write

INPUT = 'RACE_AI_BOAT_VENUE_LEARNING_INPUT_V1'
FILES = {'learning.json': 1_000_000, 'learning.enc': 12 * 1024 * 1024,
         'summary.json': 1_000_000}
POINTER_FIELDS = {'schema', 'status', 'repository_id', 'source_commit',
                  'manifest_path', 'manifest_sha256', 'training_sha256'}
MAX_BATCH_BYTES = 64 * 1024 * 1024
MAX_BATCH_CANDIDATES = 256


def _path(value):
    path = Path(value)
    need('..' not in path.parts and not any(p.is_symlink() for p in
         (path.absolute(), *path.absolute().parents)), 'VENUE_LEARNING_PATH_INVALID')
    return path


def _output_ready(value):
    path = _path(value)
    need(not path.exists() or (path.is_dir() and not any(path.iterdir())),
         'VENUE_LEARNING_OUTPUT_EXISTS_DO_NOT_RESET')
    return path


def _bounded(raw, limit):
    need(type(raw) is bytes and 0 < len(raw) <= limit,
         'VENUE_LEARNING_FILE_SIZE_INVALID')
    return raw


def _verified(files):
    """Authenticate the same bounded byte snapshot that will be transferred."""
    with tempfile.TemporaryDirectory(prefix='boat-learning-handoff-') as folder:
        root = Path(folder)
        for name, limit in FILES.items():
            _write(root / name, _bounded(files[name], limit))
        payload = read_candidate(root)
    training = payload.get('training')
    need(type(training) is dict and training.get('state') == 'FITTED_SHADOW_ONLY',
         'VENUE_LEARNING_FITTED_TRAINING_REQUIRED')
    if training.get('schema') == 'RACE_AI_ALL_EXISTING_MODEL_FIT_V1':
        # The registry verifier authenticates the complete cell roster and each
        # fitted member; genuinely missing members remain explicit HOLD cells.
        need(type(training.get('models')) is dict and bool(training['models']),
             'VENUE_LEARNING_FITTED_REGISTRY_MEMBERS_REQUIRED')
    else:
        need(set(training.get('models', {})) == set(MODEL_IDS),
             'VENUE_LEARNING_FITTED_TWO_FAMILIES_REQUIRED')
    verify_training(training)
    expected = dict(payload['summary'], encrypted_readback_verified=True,
                    plaintext_published=False)
    try:
        summary = json.loads(files['summary.json'])
    except (ValueError, UnicodeError) as exc:
        raise ValueError('VENUE_LEARNING_SUMMARY_INVALID') from exc
    need(_bytes(summary) == _bytes(expected), 'VENUE_LEARNING_SUMMARY_MISMATCH')
    return training['training_sha256'], len(training['models'])


def _git(repo, transport):
    git = transport if transport is not None else GitStateRepository(repo, ref=TRANSFER_REF)
    need(getattr(git, 'ref', TRANSFER_REF) == TRANSFER_REF,
         'VENUE_LEARNING_TRANSFER_REF_REQUIRED')
    return git


def _pointer(commit, manifest_sha, training_sha):
    return dict(schema=INPUT, status='READY', repository_id='1416489937',
                source_commit=commit, manifest_path=PREFIX + 'learning/' + manifest_sha + '/learning.json',
                manifest_sha256=manifest_sha, training_sha256=training_sha)


def _validate_pointer(pointer):
    need(type(pointer) is dict and set(pointer) == POINTER_FIELDS and
         pointer.get('schema') == INPUT and pointer.get('status') == 'READY' and
         pointer.get('repository_id') == '1416489937' and
         all(type(pointer.get(name)) is str and re.fullmatch(pattern, pointer[name])
             for name, pattern in (('source_commit', '[a-f0-9]{40}'),
                                   ('manifest_sha256', '[a-f0-9]{64}'),
                                   ('training_sha256', '[a-f0-9]{64}'))) and
         pointer == _pointer(pointer['source_commit'], pointer['manifest_sha256'],
                             pointer['training_sha256']), 'VENUE_LEARNING_INPUT_INVALID')


def publish_learning_candidate(folder, repo, *, transport=None):
    """Append only the original encrypted three-file candidate after owner readback."""
    need(_key_ready(), 'OWNER_STATE_KEY_REQUIRED')
    root = _path(folder)
    files = {name: _read(root / name, limit) for name, limit in FILES.items()}
    training_sha, _ = _verified(files)  # Wrong local owner key must fail before Git.
    identity = _sha(files['learning.json'])
    prefix = PREFIX + 'learning/' + identity + '/'
    git = _git(repo, transport)
    parent = git.head()
    need(type(parent) is str and re.fullmatch('[a-f0-9]{40}', parent),
         'VENUE_EXISTING_TRANSFER_REF_REQUIRED')
    git.fetch(parent)
    additions = {}
    for name, raw in files.items():
        path = prefix + name
        if git.exists(parent, path):
            need(_bounded(git.read(parent, path, FILES[name]), FILES[name]) == raw,
                 'VENUE_LEARNING_IMMUTABLE_FILE_CHANGED')
        else:
            additions[path] = raw
    commit = parent
    if additions:
        commit = git.commit(additions, parent)
        need(type(commit) is str and re.fullmatch('[a-f0-9]{40}', commit),
             'VENUE_LEARNING_COMMIT_INVALID')
        git.push(commit, parent)
        git.fetch(commit)
    for name, raw in files.items():
        need(_bounded(git.read(commit, prefix + name, FILES[name]), FILES[name]) == raw,
             'VENUE_LEARNING_REMOTE_READBACK_MISMATCH')
    return _pointer(commit, identity, training_sha)


def _candidate_snapshot(folder):
    root = _path(folder)
    files = {name: _bounded(_read(root/name, limit), limit) for name, limit in FILES.items()}
    training_sha, _ = _verified(files)
    return files, _sha(files['learning.json']), training_sha


def _publish_candidate_batch(batch, repo, transport):
    expected = {}
    for identity, _, files in batch:
        prefix = PREFIX + 'learning/' + identity + '/'
        for name, raw in files.items():
            path = prefix + name
            if path in expected:
                need(expected[path][0] == raw, 'VENUE_LEARNING_IMMUTABLE_FILE_CHANGED')
            else:
                expected[path] = (raw, FILES[name])
    git = _git(repo, transport)
    parent = git.head()
    need(type(parent) is str and re.fullmatch('[a-f0-9]{40}', parent),
         'VENUE_EXISTING_TRANSFER_REF_REQUIRED')
    git.fetch(parent)
    additions = {}
    for path, (raw, limit) in expected.items():
        if git.exists(parent, path):
            need(_bounded(git.read(parent, path, limit), limit) == raw,
                 'VENUE_LEARNING_IMMUTABLE_FILE_CHANGED')
        else:
            additions[path] = raw
    commit = parent
    if additions:
        commit = git.commit(additions, parent)
        need(type(commit) is str and re.fullmatch('[a-f0-9]{40}', commit),
             'VENUE_LEARNING_COMMIT_INVALID')
        git.push(commit, parent)
        git.fetch(commit)
    for identity, _, files in batch:
        prefix = PREFIX + 'learning/' + identity + '/'
        for name, raw in files.items():
            need(_bounded(git.read(commit, prefix+name, FILES[name]), FILES[name]) == raw,
                 'VENUE_LEARNING_REMOTE_READBACK_MISMATCH')
    return [_pointer(commit, identity, training_sha) for identity, training_sha, _ in batch]


def publish_learning_candidates(folders, repo, *, transport=None):
    """Retain exact candidates with bounded bytes and one ref update per batch.

    Preflight all candidates with only fingerprints retained, then authenticate
    the unchanged snapshots again in bounded batches. A failed batch raises;
    previously committed batches never become a partial-success report.
    """
    need(_key_ready(), 'OWNER_STATE_KEY_REQUIRED')
    need(type(folders) is list and len(folders) <= 10000,
         'VENUE_LEARNING_BOUNDED_FOLDER_LIST_REQUIRED')
    prepared = []
    for folder in folders:
        files, _, _ = _candidate_snapshot(folder)
        size = sum(map(len, files.values()))
        need(size <= MAX_BATCH_BYTES, 'VENUE_LEARNING_BATCH_SIZE_INVALID')
        prepared.append((folder, {name: _sha(raw) for name, raw in files.items()}, size))
        del files
    pointers = []
    batch = []
    batch_bytes = 0
    for folder, fingerprints, size in prepared:
        if batch and (len(batch) >= MAX_BATCH_CANDIDATES or batch_bytes+size > MAX_BATCH_BYTES):
            pointers.extend(_publish_candidate_batch(batch, repo, transport))
            batch.clear()
            batch_bytes = 0
        files, identity, training_sha = _candidate_snapshot(folder)
        need({name: _sha(raw) for name, raw in files.items()} == fingerprints and
             sum(map(len, files.values())) == size, 'VENUE_LEARNING_SOURCE_CHANGED')
        batch.append((identity, training_sha, files))
        batch_bytes += size
        del files
    if batch:
        pointers.extend(_publish_candidate_batch(batch, repo, transport))
    return pointers


def restore_learning_candidate(pointer, output, repo, *, transport=None):
    """Restore an exact commit and decrypt privately; return aggregate proof only."""
    need(_key_ready(), 'OWNER_STATE_KEY_REQUIRED')
    _validate_pointer(pointer)
    root = _output_ready(output)
    git = _git(repo, transport)
    commit = pointer['source_commit']
    git.fetch(commit)
    manifest = _bounded(git.read(commit, pointer['manifest_path'], FILES['learning.json']),
                        FILES['learning.json'])
    need(_sha(manifest) == pointer['manifest_sha256'], 'VENUE_LEARNING_MANIFEST_HASH_INVALID')
    prefix = pointer['manifest_path'].removesuffix('learning.json')
    files = {'learning.json': manifest}
    for name in ('learning.enc', 'summary.json'):
        files[name] = _bounded(git.read(commit, prefix + name, FILES[name]), FILES[name])
    training_sha, fitted_model_count = _verified(files)
    need(training_sha == pointer['training_sha256'], 'VENUE_LEARNING_TRAINING_HASH_INVALID')
    root = _output_ready(root)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    for name, raw in files.items():
        _write(root / name, raw)
    return dict(status='OWNER_VENUE_LEARNING_READBACK_VERIFIED', source_commit=commit,
                manifest_sha256=pointer['manifest_sha256'], training_sha256=training_sha,
                fitted_model_count=fitted_model_count, encrypted_readback_verified=True,
                plaintext_published=False)
