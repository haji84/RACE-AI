"""Reuse immutable encrypted transport bytes; never reuse admission or scores.

Every caller still validates the fresh receipt and replays the native scorer.
The independent Git cache is caller-owned runner-temporary storage, populated
only by the unchanged authenticated remote-fetch/selected-object readers.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess

from .boat_pdca_github_handoff import GitStateRepository, TRANSFER_REF
from .boat_private_original_vault import VaultGitRepository, MAX_METADATA


_OVERRIDES = ('GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
              'GIT_COMMON_DIR', 'GIT_DIR', 'GIT_WORK_TREE')
_SHA = re.compile(r'[a-f0-9]{40}')
_DIGEST = re.compile(r'sha256:[a-f0-9]{64}')


def _need(value, reason):
    if not value:
        raise ValueError('RESEARCH_CACHE_' + reason)


def _no_overrides(env=None):
    _need(not any(name in os.environ or env is not None and name in env
                  for name in _OVERRIDES), 'GIT_STORAGE_OVERRIDE_REJECTED')


def _path(value):
    try:
        path = Path(value).absolute()
        _need('..' not in path.parts, 'PATH_REJECTED')
        _need(not any(item.is_symlink() for item in (path, *path.parents)), 'PATH_REJECTED')
        return path
    except (OSError, TypeError, RuntimeError):
        raise ValueError('RESEARCH_CACHE_PATH_REJECTED') from None


def _private_directory(path, *, missing=False):
    path = _path(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        _need(missing, 'PRIVATE_DIRECTORY_REQUIRED')
        return path
    _need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
          and info.st_mode & 0o077 == 0, 'PRIVATE_DIRECTORY_REQUIRED')
    return path


def _json(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_METADATA, 'METADATA_BOUND_INVALID')
    def unique(pairs):
        result = {}
        for name, value in pairs:
            _need(name not in result, 'METADATA_INVALID')
            result[name] = value
        return result
    def finite(value):
        number = float(value)
        _need(math.isfinite(number), 'METADATA_INVALID')
        return number
    def nonfinite(value):
        raise ValueError('RESEARCH_CACHE_METADATA_INVALID')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                           parse_constant=nonfinite, parse_float=finite)
        _need(type(value) is dict, 'METADATA_INVALID')
        return value
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError('RESEARCH_CACHE_METADATA_INVALID') from None


def _cached_zip(path, maximum):
    path = _path(path)
    if not path.exists():
        return None
    # Refuse special files before open; O_NONBLOCK also closes a FIFO race.
    info = path.lstat()
    _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
          and info.st_mode & 0o077 == 0 and info.st_nlink == 1,
          'PRIVATE_ARCHIVE_REQUIRED')
    flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
             | getattr(os, 'O_NONBLOCK', 0))
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                  and before.st_mode & 0o077 == 0 and before.st_nlink == 1,
                  'PRIVATE_ARCHIVE_REQUIRED')
            if not 0 < before.st_size <= maximum:
                return None
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                  (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                  'ARCHIVE_CHANGED_DURING_READ')
            return raw
    except (OSError, OverflowError):
        raise ValueError('RESEARCH_CACHE_PRIVATE_ARCHIVE_REQUIRED') from None


def read_research_archive(reference, *, gh, cache_root, maximum_bytes):
    """Return exact ZIP bytes plus this call's metadata, without admitting it."""
    _need(type(reference) is dict and set(reference) ==
          {'artifact_id', 'run_id', 'head_sha', 'digest'}
          and all(type(reference.get(key)) is int and reference[key] > 0
                  for key in ('artifact_id', 'run_id'))
          and type(reference.get('head_sha')) is str and _SHA.fullmatch(reference['head_sha'])
          and type(reference.get('digest')) is str and _DIGEST.fullmatch(reference['digest']),
          'REFERENCE_INVALID')
    _need(type(maximum_bytes) is int and maximum_bytes > 0 and callable(gh), 'INPUT_INVALID')
    ident = reference['artifact_id']
    try:
        metadata = _json(gh('actions/artifacts/' + str(ident)))
    except Exception:
        raise ValueError('RESEARCH_CACHE_FRESH_METADATA_REQUIRED') from None
    run = metadata.get('workflow_run')
    _need(type(metadata.get('id')) is int and metadata['id'] == ident
          and metadata.get('digest') == reference['digest']
          and type(run) is dict and type(run.get('id')) is int and run['id'] == reference['run_id']
          and run.get('head_sha') == reference['head_sha'], 'FRESH_IDENTITY_MISMATCH')
    size = metadata.get('size_in_bytes')
    _need(type(size) is int and 0 < size <= maximum_bytes, 'ARCHIVE_BOUND_INVALID')
    root = _private_directory(cache_root, missing=True)
    folder = _private_directory(root / str(ident), missing=True)
    raw = _cached_zip(folder / 'archive.zip', maximum_bytes)
    expected = reference['digest'][7:]
    if raw is None or len(raw) != size or hashlib.sha256(raw).hexdigest() != expected:
        try:
            raw = gh('actions/artifacts/' + str(ident) + '/zip')
        except Exception:
            raise ValueError('RESEARCH_CACHE_ZIP_READ_FAILED') from None
        _need(type(raw) is bytes and len(raw) == size
              and hashlib.sha256(raw).hexdigest() == expected, 'ARCHIVE_BYTES_INVALID')
    # Expiry, external clocks, AEAD, native replay and scoring remain the
    # unchanged caller's job, with this fresh complete metadata on every use.
    return raw, metadata


def _git(path, args, *, missing=False):
    try:
        result = subprocess.run(['git', '-C', str(path), *args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=30)
        _need(result.returncode == 0 or missing and result.returncode == 1, 'GIT_LAYOUT_INVALID')
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError('RESEARCH_CACHE_GIT_LAYOUT_INVALID') from None


def _layout(path):
    gitdir = _path(_git(path, ['rev-parse', '--path-format=absolute', '--git-dir']).decode().strip())
    common = _path(_git(path, ['rev-parse', '--path-format=absolute', '--git-common-dir']).decode().strip())
    objects = _path(_git(path, ['rev-parse', '--path-format=absolute', '--git-path', 'objects']).decode().strip())
    _need(gitdir.is_dir() and common.is_dir() and objects.is_dir(), 'GIT_LAYOUT_INVALID')
    return gitdir, common, objects


def _validate_reader(path, writer_layout, expected_origin):
    _private_directory(path)
    gitdir, common, objects = _layout(path)
    _need(gitdir == common == path and objects == path / 'objects'
          and _git(path, ['rev-parse', '--is-bare-repository']).strip() == b'true',
          'INDEPENDENT_BARE_READER_REQUIRED')
    _need(not _git(path, ['config', '--get', 'core.worktree'], missing=True).strip(),
          'WORKTREE_REJECTED')
    for item in (path / 'commondir', path / 'gitdir',
                 objects / 'info/alternates', objects / 'info/http-alternates'):
        _need(not item.exists() and not item.is_symlink(), 'SHARED_OBJECTS_REJECTED')
    worktrees = path / 'worktrees'
    _need(not worktrees.exists() and not worktrees.is_symlink(), 'WORKTREE_REJECTED')
    for reader_part, writer_part in zip((gitdir, common, objects), writer_layout):
        _need(reader_part != writer_part and not os.path.samefile(reader_part, writer_part),
              'SHARED_OBJECTS_REJECTED')
    for args in (['remote', 'get-url', '--all', 'origin'],
                 ['remote', 'get-url', '--push', '--all', 'origin']):
        _need(_git(path, args).decode().splitlines() == [expected_origin], 'ORIGIN_CHANGED')
    return objects


class _ReadOnlyResearchRepository(VaultGitRepository):
    """Allow the existing remote reader's commands; prohibit publication."""
    def __init__(self, repo, origin):
        self._cache_path = Path(repo)
        self._expected_origin = origin
        super().__init__(repo, ref=TRANSFER_REF)

    def _run(self, args, *, body=None, env=None):
        _no_overrides(env)
        _need(self.repo == self._cache_path and self.ref == TRANSFER_REF, 'READER_IDENTITY_CHANGED')
        args = list(args)
        index = 0
        while index < len(args):
            if args[index] == '--no-lazy-fetch':
                index += 1
            elif args[index:index+2] == ['-c', 'fetch.negotiationAlgorithm=noop']:
                index += 2
            else:
                break
        command = args[index] if index < len(args) else None
        tail = args[index:]
        _need(command in ('remote', 'cat-file', 'ls-tree', 'show', 'fetch', 'ls-remote'),
              'READ_ONLY_REPOSITORY')
        if command == 'remote':
            _need(tail in (['remote', 'get-url', '--all', 'origin'],
                           ['remote', 'get-url', '--push', '--all', 'origin']),
                  'READ_ONLY_REPOSITORY')
        elif command == 'fetch':
            metadata = (len(tail) == 7 and tail[:5] ==
                ['fetch', '--no-tags', '--no-write-fetch-head', '--depth=1', '--filter=blob:none']
                and tail[5] == self._expected_origin
                and re.fullmatch(r'([a-f0-9]{40}):refs/race-ai/pinned-state/\1', tail[6])
                and body is None)
            selected = (tail == ['fetch', '--no-tags', '--no-write-fetch-head',
                '--recurse-submodules=no', '--filter=blob:none', '--stdin', self._expected_origin]
                and type(body) is bytes and re.fullmatch(rb'(?:[a-f0-9]{40}\n)+', body))
            _need(metadata or selected, 'READ_ONLY_REPOSITORY')
        elif command == 'ls-remote':
            _need(tail == ['ls-remote', '--heads', self._expected_origin,
                          'refs/heads/' + TRANSFER_REF], 'READ_ONLY_REPOSITORY')
        result = super()._run(args, body=body, env=env)
        if command == 'remote':
            _need(result.decode().splitlines() == [self._expected_origin], 'ORIGIN_CHANGED')
        return result

    def _publication_rejected(self, *args, **kwargs):
        raise ValueError('RESEARCH_CACHE_READ_ONLY_REPOSITORY')

    commit = commit_snapshot = push = _write_tree = _publication_rejected


def research_readback_transport(repo, *, cache_root):
    """Reopen a separate private bare ODB; normal batch code owns every fetch."""
    _no_overrides()
    writer_path = _path(repo)
    path = _path(cache_root)
    _need(path != writer_path and writer_path not in path.parents, 'INDEPENDENT_READER_REQUIRED')
    writer = GitStateRepository(writer_path, ref=TRANSFER_REF)
    writer_layout = _layout(writer_path)
    _need(not any(part == path or part in path.parents for part in writer_layout),
          'INDEPENDENT_READER_REQUIRED')
    if not path.exists():
        try:
            path.mkdir(mode=0o700)
            result = subprocess.run(['git', 'init', '--bare', str(path)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            _need(result.returncode == 0, 'GIT_INITIALIZATION_FAILED')
            _git(path, ['remote', 'add', 'origin', writer.fetch_url])
        except (OSError, subprocess.SubprocessError):
            raise ValueError('RESEARCH_CACHE_GIT_INITIALIZATION_FAILED') from None
    _validate_reader(path, writer_layout, writer.fetch_url)
    return _ReadOnlyResearchRepository(path, writer.fetch_url)
