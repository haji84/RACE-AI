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
    need(type(training) is dict and training.get('state') == 'FITTED_SHADOW_ONLY'
         and set(training.get('models', {})) == set(MODEL_IDS),
         'VENUE_LEARNING_FITTED_TWO_FAMILIES_REQUIRED')
    verify_training(training)
    expected = dict(payload['summary'], encrypted_readback_verified=True,
                    plaintext_published=False)
    try:
        summary = json.loads(files['summary.json'])
    except (ValueError, UnicodeError) as exc:
        raise ValueError('VENUE_LEARNING_SUMMARY_INVALID') from exc
    need(_bytes(summary) == _bytes(expected), 'VENUE_LEARNING_SUMMARY_MISMATCH')
    return training['training_sha256']


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
    training_sha = _verified(files)  # Wrong local owner key must fail before Git.
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
    training_sha = _verified(files)
    need(training_sha == pointer['training_sha256'], 'VENUE_LEARNING_TRAINING_HASH_INVALID')
    root = _output_ready(root)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    for name, raw in files.items():
        _write(root / name, raw)
    return dict(status='OWNER_VENUE_LEARNING_READBACK_VERIFIED', source_commit=commit,
                manifest_sha256=pointer['manifest_sha256'], training_sha256=training_sha,
                fitted_model_count=2, encrypted_readback_verified=True, plaintext_published=False)
