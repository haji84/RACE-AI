"""Private, disk-backed inventory of exact already-fetched source captures.

Inventory creation validates every receipt and streams every body before any
caller may publish. Only descriptors live in SQLite; raw bytes are rechecked
and materialized one vault-sized group (or one feed capture) at a time. This
does not acquire sources, expand their allowlist or create a source receipt.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import boat_private_original_vault as V

MAX_CAPTURE = 4*1024*1024
MAX_CAPTURES = 240  # A vault bundle bound, never a folder/retention count limit.
READ_BYTES = 128*1024


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _private_root(value, repo=None):
    path = Path(value).absolute()
    V._need('..' not in path.parts
            and not any(p.is_symlink() for p in (path, *path.parents))
            and not any((p/'.git').exists() for p in (path, *path.parents))
            and (repo is None or not path.is_relative_to(Path(repo).resolve())),
            'PRIVATE_OUTSIDE_GIT_REQUIRED')
    info = path.lstat()
    V._need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and not info.st_mode & 0o077, 'PRIVATE_INPUT_REQUIRED')
    return path


def _private_file(info, limit):
    V._need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and not info.st_mode & 0o077 and info.st_nlink == 1
            and 0 < info.st_size <= limit, 'PRIVATE_INPUT_BOUND_INVALID')


def _read_at(root_fd, name, limit, *, expected=None, collect=False):
    """Use a pinned directory fd, streamed hashing and before/after identity."""
    V._need(type(name) is str and '/' not in name and name not in ('.', '..'),
            'CAPTURE_FILENAME_INVALID')
    path_info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    _private_file(path_info, limit)
    if expected is not None:
        V._need(_signature(path_info) == tuple(expected), 'PRIVATE_INPUT_CHANGED')
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno()); _private_file(before, limit)
        V._need(_signature(before) == _signature(path_info), 'PRIVATE_INPUT_CHANGED')
        digest = sha256(); size = 0; chunks = [] if collect else None
        while True:
            raw = stream.read(min(READ_BYTES, limit+1-size))
            if not raw:break
            size += len(raw); V._need(size <= limit, 'PRIVATE_INPUT_BOUND_INVALID')
            digest.update(raw)
            if collect:chunks.append(raw)
        after = os.fstat(stream.fileno())
    final = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    V._need(size == before.st_size and _signature(before) == _signature(after)
            and _signature(after) == _signature(final), 'PRIVATE_INPUT_CHANGED')
    return (b''.join(chunks) if collect else None), digest.hexdigest(), _signature(after)


def capture_metadata(raw, *, now):
    """The same source/clock/body contract as the unchanged vault primitive."""
    metadata = V._json(raw, 16384)
    V._need(type(metadata) is dict and type(metadata.get('http_status')) is int
            and metadata['http_status'] == 200, 'CAPTURE_RECEIPT_INVALID')
    V._hex(metadata.get('source_sha256'))
    V._need(V._capture_url(metadata.get('source_url')), 'CAPTURE_SOURCE_INVALID')
    instant = V._time(metadata.get('captured_at'))
    V._need(instant <= now, 'CAPTURE_CLOCK_INVALID')
    return metadata, instant.astimezone(timezone.utc).isoformat(timespec='microseconds')


def _identity_url(url):
    # The allowed official result URL already has a fixed canonical spelling.
    # Allowed GitHub pagination parameters may be received in either order.
    parsed = urlsplit(url)
    if parsed.netloc == 'api.github.com':
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                           urlencode(sorted(parse_qsl(parsed.query))), ''))
    return url


def capture_http200(raw, *, source_url, received_at, source_guard=None):
    """Preserve one accepted response privately, before any parser or day clock.

    Only the existing vault opt-in and owner/source context enable this sink.
    Opaque retention grants no typed program, forecast or artifact authority.
    No request, caller admission clock, model input or source counter changes.
    """
    if os.environ.get('RACE_AI_ORIGINAL_VAULT_ENABLED') != 'true':
        return
    try:
        from .boat_pdca_state import state_key
        from .boat_owner_source_identity import owner_run_origin
        state_key('production')
        V._need(os.environ.get('GITHUB_ACTIONS') == 'true'
                and os.environ.get('GITHUB_REPOSITORY') == 'haji84/RACE-AI'
                and owner_run_origin(os.environ.get('GITHUB_REF_NAME'),
                                     os.environ.get('GITHUB_EVENT_NAME')),
                'ACTIONS_OWNER_CONTEXT_REQUIRED')
        parsed = urlsplit(source_url)
        p1 = parsed.netloc == 'www.boatrace.jp' and parsed.path in (
            '/owpc/pc/race/racelist', '/owpc/pc/race/beforeinfo')
        program = parsed.netloc == 'www1.mbrace.or.jp' and parsed.path.startswith('/od2/B/')
        V._need((p1 or program) and V._capture_url(source_url), 'CAPTURE_SOURCE_INVALID')
        V._need(os.environ.get('RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED') == 'true' if p1 else
                os.environ.get('RACE_AI_SAVED_PROGRAM_CAPTURE') == 'true', 'SOURCE_SCOPE_REQUIRED')
        V._need(type(raw) is bytes and 0 < len(raw) <= MAX_CAPTURE, 'CAPTURE_BOUND_INVALID')
        V._need(type(received_at) is datetime and received_at.utcoffset() is not None,
                'AWARE_CLOCK_REQUIRED')
        receipt = dict(source_url=source_url, source_sha256=sha256(raw).hexdigest(),
            captured_at=received_at.astimezone(timezone.utc).isoformat(timespec='microseconds'),
            http_status=200)
        encoded = V._wire(receipt)+b'\n'
        repo = Path(__file__).resolve().parents[1]
        runner = Path(os.environ['RUNNER_TEMP'])

        def check_runner():
            # Match the existing typed program capture's runner-parent rule.
            # Only the secret child needs 0700; an owned 0755 parent is safe.
            V._need(runner.is_absolute() and '..' not in runner.parts
                    and not any(p.is_symlink() for p in (runner, *runner.parents))
                    and not any((p/'.git').exists() for p in (runner, *runner.parents))
                    and not runner.is_relative_to(repo.resolve()), 'PRIVATE_OUTSIDE_GIT_REQUIRED')
            info = runner.lstat()
            V._need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                    and not info.st_mode & 0o022, 'PRIVATE_RUNNER_TEMP_REQUIRED')
            return _signature(info)[:4]

        runner_identity = check_runner()
        root = runner/'boat-saved-view-captures'
        try:root.mkdir(mode=0o700)
        except FileExistsError:pass
        _private_root(root, repo)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            import fcntl
            # Serialize cooperating raw writers on the existing directory
            # itself. A busy writer is a fixed HOLD, never a blocking wait or
            # a new lockfile. Closing descriptor releases this invocation's lock.
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            identity = _signature(os.fstat(descriptor))[:5]

            def check_root():
                V._need(check_runner() == runner_identity, 'PRIVATE_INPUT_CHANGED')
                _private_root(root, repo)
                V._need(_signature(root.lstat())[:5] == identity
                        and _signature(os.fstat(descriptor))[:5] == identity,
                        'PRIVATE_INPUT_CHANGED')

            def verify(fd, name, body, limit):
                actual, _, _ = _read_at(fd, name, limit, collect=True)
                V._need(actual == body, 'EXISTING_CAPTURE_CONFLICT')

            check_root()
            bodies = []
            for suffix in ('.html', '.raw'):
                name = receipt['source_sha256']+suffix
                try:os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:continue
                bodies.append(name)
            V._need(len(bodies) <= 1, 'CAPTURE_BODY_REQUIRED')
            # Preserve the existing feed filename convention for opaque B too.
            files = [(bodies[0] if bodies else receipt['source_sha256']+'.html', raw, MAX_CAPTURE),
                     (V._sha(V._wire(receipt))+'.json', encoded, 16384)]
            pending = []
            for name, body, limit in files:
                try:os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:pending.append((name, body, limit))
                else:verify(descriptor, name, body, limit)
            check_root()
            if not pending:return

            created = []
            try:
                # No partial body or receipt is ever visible in the flat
                # inventory. This invocation owns this entire private stage.
                with tempfile.TemporaryDirectory(dir=runner, prefix='boat-source-capture-stage-') as temporary:
                    stage = _private_root(temporary, repo)
                    stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    try:
                        stage_identity = _signature(os.fstat(stage_fd))[:5]

                        def check_stage():
                            check_root(); _private_root(stage, repo)
                            V._need(_signature(stage.lstat())[:5] == stage_identity
                                    and _signature(os.fstat(stage_fd))[:5] == stage_identity,
                                    'PRIVATE_INPUT_CHANGED')

                        # Prepare every needed file before publishing either.
                        for name, body, limit in pending:
                            check_stage()
                            output = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                             0o600, dir_fd=stage_fd)
                            with os.fdopen(output, 'wb') as stream:
                                V._need(stream.write(body) == len(body), 'PRIVATE_WRITE_INCOMPLETE')
                                stream.flush(); os.fsync(stream.fileno())
                            verify(stage_fd, name, body, limit)
                            check_stage()

                        for name, body, limit in pending:
                            check_stage()
                            info = os.stat(name, dir_fd=stage_fd, follow_symlinks=False)
                            # The staged inode is newly owned by this invocation.
                            # Track it before link, including an interrupted call.
                            created.append((name, (info.st_dev, info.st_ino)))
                            try:
                                # link is atomic and refuses an existing final
                                # name; no original can be replaced or truncated.
                                os.link(name, name, src_dir_fd=stage_fd, dst_dir_fd=descriptor,
                                        follow_symlinks=False)
                            except FileExistsError:
                                verify(descriptor, name, body, limit)
                            else:
                                os.unlink(name, dir_fd=stage_fd)
                            check_stage()
                    finally:
                        os.close(stage_fd)
                for name, body, limit in files:
                    verify(descriptor, name, body, limit)
                os.fsync(descriptor)
                check_root()
            except BaseException:
                # Only final links created by this invocation are eligible
                # for rollback. Preexisting/shared files are never touched.
                for name, expected in reversed(created):
                    try:
                        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                        if (info.st_dev, info.st_ino) == expected:
                            os.unlink(name, dir_fd=descriptor)
                    except OSError:
                        pass
                if created:
                    try:os.fsync(descriptor)
                    except OSError:pass
                raise
        finally:
            os.close(descriptor)
    except Exception:
        # Reuse the existing durable review latch; even a latch write failure
        # must leave this invocation in the same fixed, non-retryable HOLD.
        if source_guard is not None:
            try:source_guard.verification_failure('SOURCE_CAPTURE_UNAVAILABLE')
            except Exception:pass
        from .source_retry_policy import SourceWait
        raise SourceWait('SOURCE_CAPTURE_UNAVAILABLE', retry_at=None,
                         state='SOURCE_REVIEW_WAIT') from None


@dataclass(frozen=True)
class _Capture:
    # File paths, source URLs and receipts must not leak through a debug repr.
    number: int = field(repr=False)
    receipt_name: str = field(repr=False)
    body_name: str = field(repr=False)
    body_sha256: str = field(repr=False)
    metadata_sha256: str = field(repr=False)
    body_size: int = field(repr=False)
    metadata_size: int = field(repr=False)
    clock: str = field(repr=False)
    source_url: str = field(repr=False)
    receipt_stat: tuple = field(repr=False)
    body_stat: tuple = field(repr=False)


class CaptureInventory:
    """Context-managed complete preflight, with no logical capture count cap.

    ``groups`` returns bounded descriptors, not bodies. Callers release the
    materialized group before requesting the next one. ``iter_captures`` keeps
    the old filename order for one uninterrupted saved-feed replay.
    """
    _columns = ('number,receipt_name,body_name,body_sha256,metadata_sha256,'
                'body_size,metadata_size,clock,source_url,receipt_stat,body_stat')
    _ordered_sql = ('SELECT '+_columns+' FROM captures '
                    'INDEXED BY capture_chronological ORDER BY clock,source_url,body_sha256,receipt_name')

    def __init__(self, folder, *, repo=None, now=None, metadata_limit=16384,
                 suffixes=('.html', '.raw'), missing_ok=False):
        self.folder = Path(folder); self.repo = repo
        self.now = now if now is not None else datetime.now(timezone.utc)
        V._need(type(self.now) is datetime and self.now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        V._need(type(metadata_limit) is int and 0 < metadata_limit <= 16384, 'CAPTURE_METADATA_BOUND_INVALID')
        V._need(type(suffixes) is tuple and suffixes in (('.html',), ('.html', '.raw')), 'CAPTURE_SUFFIX_INVALID')
        self.metadata_limit = metadata_limit; self.suffixes = suffixes; self.missing_ok = missing_ok
        self.count = 0; self._db = None; self._root_fd = None; self._temp = None; self._ready = False

    def __enter__(self):
        try:
            self._temp = tempfile.TemporaryDirectory(prefix='boat-capture-inventory-')
            spool_root = _private_root(self._temp.name, self.repo)
            self.spool_path = spool_root/'inventory.sqlite'
            fd = os.open(self.spool_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            self._db = sqlite3.connect(self.spool_path)
            self._db.execute('PRAGMA cache_size=-2048')
            self._db.execute('PRAGMA mmap_size=0')
            self._db.execute('PRAGMA temp_store=FILE')
            self._db.execute('PRAGMA journal_mode=DELETE')
            self._db.execute('CREATE TABLE captures ('
                'number INTEGER PRIMARY KEY, receipt_name TEXT UNIQUE, body_name TEXT,'
                'body_sha256 TEXT, metadata_sha256 TEXT, body_size INTEGER, metadata_size INTEGER,'
                'clock TEXT, source_url TEXT, receipt_stat TEXT, body_stat TEXT, UNIQUE(source_url,clock))')
            self._db.execute('CREATE INDEX capture_chronological '
                             'ON captures(clock,source_url,body_sha256,receipt_name)')
            if not os.path.lexists(self.folder) and self.missing_ok:
                self._ready = True; return self
            self.folder = _private_root(self.folder, self.repo)
            self._root_fd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._root_stat = _signature(os.fstat(self._root_fd))
            self._check_root()
            with os.scandir(self._root_fd) as entries:
                for item in entries:
                    if item.name.endswith('.json'):self._preflight(item.name)
            self._check_root(); self._db.commit(); self._ready = True
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        self._ready = False
        if self._db is not None:self._db.close(); self._db = None
        if self._root_fd is not None:os.close(self._root_fd); self._root_fd = None
        if self._temp is not None:self._temp.cleanup(); self._temp = None

    def _check_root(self):
        if self._root_fd is None:
            V._need(not os.path.lexists(self.folder), 'PRIVATE_INPUT_CHANGED'); return
        # Recheck ancestors too; an fd alone would hide a replaced directory.
        _private_root(self.folder, self.repo)
        V._need(_signature(self.folder.lstat()) == self._root_stat
                and _signature(os.fstat(self._root_fd)) == self._root_stat, 'PRIVATE_INPUT_CHANGED')

    def _preflight(self, name):
        metadata_raw, meta_sha, receipt_stat = _read_at(self._root_fd, name, self.metadata_limit, collect=True)
        metadata, clock = capture_metadata(metadata_raw, now=self.now)
        V._need(name == V._sha(V._wire(metadata))+'.json', 'CAPTURE_FILENAME_INVALID')
        ident = metadata['source_sha256']; candidates = []
        for suffix in self.suffixes:
            try:os.stat(ident+suffix, dir_fd=self._root_fd, follow_symlinks=False)
            except FileNotFoundError:continue
            candidates.append(ident+suffix)
        V._need(len(candidates) == 1, 'CAPTURE_BODY_REQUIRED')
        _, body_sha, body_stat = _read_at(self._root_fd, candidates[0], MAX_CAPTURE)
        V._need(body_sha == ident, 'CAPTURE_RECEIPT_INVALID')
        values = (self.count, name, candidates[0], body_sha, meta_sha, body_stat[5], receipt_stat[5],
                  clock, _identity_url(metadata['source_url']), V._wire(receipt_stat).decode(), V._wire(body_stat).decode())
        try:self._db.execute('INSERT INTO captures VALUES (?,?,?,?,?,?,?,?,?,?,?)', values)
        except sqlite3.IntegrityError:raise ValueError('VAULT_CAPTURE_DUPLICATE') from None
        self.count += 1

    def _rows(self, *, chronological):
        V._need(self._ready, 'CAPTURE_PREFLIGHT_REQUIRED'); self._check_root()
        query = self._ordered_sql if chronological else 'SELECT '+self._columns+' FROM captures ORDER BY receipt_name'
        for row in self._db.execute(query):
            yield _Capture(*row[:9], tuple(V._json(row[9].encode())), tuple(V._json(row[10].encode())))

    def groups(self, *, count_limit=MAX_CAPTURES, byte_limit=V.MAX_PLAIN):
        V._need(type(count_limit) is int and 0 < count_limit <= MAX_CAPTURES
                and type(byte_limit) is int and 0 < byte_limit <= V.MAX_PLAIN, 'CAPTURE_GROUP_BOUND_INVALID')
        group = []; total = 0
        for descriptor in self._rows(chronological=True):
            size = descriptor.body_size+descriptor.metadata_size
            V._need(size <= byte_limit, 'CAPTURE_TOTAL_BOUND_INVALID')
            if group and (len(group) == count_limit or total+size > byte_limit):
                yield tuple(sorted(group, key=lambda item:item.receipt_name)); group = []; total = 0
            group.append(descriptor); total += size
        if group:yield tuple(sorted(group, key=lambda item:item.receipt_name))
        # The last yield may have spent time publishing/readback-verifying its
        # bundle. A concurrent receipt addition must not receive a complete ACK
        # for the earlier folder snapshot; the verified prefix stays retained.
        self._check_root()

    def _materialize(self, descriptor):
        V._need(self._ready, 'CAPTURE_PREFLIGHT_REQUIRED'); self._check_root()
        raw, body_sha, _ = _read_at(self._root_fd, descriptor.body_name, MAX_CAPTURE,
                                   expected=descriptor.body_stat, collect=True)
        metadata_raw, meta_sha, _ = _read_at(self._root_fd, descriptor.receipt_name, self.metadata_limit,
                                           expected=descriptor.receipt_stat, collect=True)
        V._need(body_sha == descriptor.body_sha256 and meta_sha == descriptor.metadata_sha256,
                'PRIVATE_INPUT_CHANGED')
        metadata, clock = capture_metadata(metadata_raw, now=self.now)
        V._need(metadata['source_sha256'] == body_sha and _identity_url(metadata['source_url']) == descriptor.source_url
                and clock == descriptor.clock, 'PRIVATE_INPUT_CHANGED')
        self._check_root()
        return raw, metadata_raw

    def materialize(self, group):
        V._need(type(group) is tuple and 0 < len(group) <= MAX_CAPTURES
                and all(type(item) is _Capture for item in group)
                and sum(d.body_size+d.metadata_size for d in group) <= V.MAX_PLAIN, 'CAPTURE_GROUP_BOUND_INVALID')
        return [self._materialize(item) for item in group]

    def count_urls(self, urls):
        V._need(self._ready, 'CAPTURE_PREFLIGHT_REQUIRED')
        return sum(1 for row in self._db.execute('SELECT source_url FROM captures') if row[0] in urls)

    def iter_captures(self, *, urls=None):
        for descriptor in self._rows(chronological=False):
            if urls is None or descriptor.source_url in urls:
                raw, metadata_raw = self._materialize(descriptor)
                yield raw, V._json(metadata_raw, self.metadata_limit)
        self._check_root()


def bundle_inventory(pairs):
    """Count/hash acknowledgment only; authority remains each vault locator."""
    return V._sha(V._wire([dict(body_sha256=V._sha(raw), metadata_sha256=V._sha(meta))
                          for raw, meta in pairs]))


def capture_set_hash(bundle_hashes):
    result = sha256(b'RACE_AI_SOURCE_CAPTURE_SET_V1\n')
    for value in bundle_hashes:result.update((V._hex(value)+'\n').encode('ascii'))
    return result.hexdigest()


class CaptureReceiptIndex:
    """Disk-backed global duplicate check while restoring bounded bundles."""
    def __init__(self, *, repo, now):
        self.repo = repo; self.now = now; self.count = 0; self._temp = None; self._db = None

    def __enter__(self):
        try:
            self._temp = tempfile.TemporaryDirectory(prefix='boat-capture-restore-index-')
            root = _private_root(self._temp.name, self.repo)
            path = root/'identities.sqlite'
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600); os.close(fd)
            self._db = sqlite3.connect(path)
            self._db.execute('PRAGMA cache_size=-2048'); self._db.execute('PRAGMA mmap_size=0')
            self._db.execute('PRAGMA temp_store=FILE'); self._db.execute('PRAGMA journal_mode=DELETE')
            self._db.execute('CREATE TABLE identities (source_url TEXT, clock TEXT, PRIMARY KEY(source_url,clock))')
            return self
        except BaseException:
            self.__exit__(None, None, None); raise

    def add(self, pairs):
        for raw, metadata_raw in pairs:
            metadata, clock = capture_metadata(metadata_raw, now=self.now)
            V._need(V._sha(raw) == metadata['source_sha256'], 'CAPTURE_RECEIPT_INVALID')
            try:self._db.execute('INSERT INTO identities VALUES (?,?)', (_identity_url(metadata['source_url']), clock))
            except sqlite3.IntegrityError:raise ValueError('VAULT_CAPTURE_DUPLICATE') from None
            self.count += 1

    def __exit__(self, *args):
        if self._db is not None:self._db.close(); self._db = None
        if self._temp is not None:self._temp.cleanup(); self._temp = None
