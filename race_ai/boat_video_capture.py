"""Private HLS acquisition of caller-authorized sources, never source discovery.

The manifest pins the caller's declared scope, not a provider licence or race
identity. HTTP and upstream PDT remain separate from media PTS. No total GET,
segment, round or runtime quota is imposed. Per-response bounds protect parsers
and storage; finite export windows do not end acquisition.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import ctypes
import errno
import fcntl
import ipaddress
import http.client
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile
from urllib import error, request
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from .source_retry_policy import plan_http_wait, wait_active


SOURCE_SCHEMA = 'RACE_AI_AUTHORIZED_HLS_SOURCE_V1'
EXPORT_SCHEMA = 'RACE_AI_HLS_CAPTURE_EXPORT_V1'
_SCHEMA = 'RACE_AI_HLS_CAPTURE_STORE_V1'
_MANIFEST_FIELDS = {'schema', 'source_id', 'playlist_url', 'allowed_origins',
                    'source_role', 'source_evidence_sha256'}
_ROLES = {'LICENSED_DEVELOPMENT', 'OWNER_AUTHORIZED', 'SYNTHETIC_TEST'}
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_MAX_PLAYLIST = 2 * 1024 * 1024
_MAX_OBJECT = 1024 * 1024 * 1024
_MAX_ANALYSIS_BYTES = 256 * 1024 * 1024
_MAX_ANALYSIS_SECONDS = 120.0
_WINDOW_SECONDS = 30.0


class CaptureError(ValueError):
    """A safe machine reason; source URLs and server exceptions are excluded."""


class _Waiting(Exception):
    pass


class _IncompleteBody(Exception):
    pass


@dataclass
class HTTPResult:
    status: int
    headers: object
    body: object


def _need(ok, reason='HLS_CAPTURE_REJECTED'):
    if not ok:
        raise CaptureError(reason)


def _wire(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                       allow_nan=False) + '\n').encode()


def _json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            _need(k not in out)
            out[k] = v
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: _need(False))
    except (ValueError, TypeError, UnicodeError):
        raise CaptureError('HLS_CAPTURE_INVALID_JSON') from None


def _stamp(value):
    try:
        t = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(t.utcoffset() is not None)
        return t
    except (TypeError, AttributeError, ValueError, OverflowError):
        raise CaptureError('HLS_CAPTURE_CLOCK_INVALID') from None


def _origin(url, role):
    _need(type(url) is str and 0 < len(url) <= 8192 and
          not any(ord(c) < 33 or ord(c) == 127 for c in url) and '\\' not in url)
    try:
        p = urlsplit(url)
        host, port = p.hostname, p.port
        _need(host is not None and p.username is None and p.password is None and not p.fragment)
        if p.scheme != 'https':
            _need(p.scheme == 'http' and role == 'SYNTHETIC_TEST')
            _need(ipaddress.ip_address(host).is_loopback, 'HLS_CAPTURE_INSECURE_ORIGIN')
        _need(p.scheme in ('http', 'https'))
        display = '[' + host.lower() + ']' if ':' in host else host.lower()
        return p.scheme + '://' + display + ((':' + str(port)) if port is not None else '')
    except (ValueError, TypeError):
        raise CaptureError('HLS_CAPTURE_INVALID_ORIGIN') from None


def _manifest(value):
    _need(type(value) is dict and set(value) == _MANIFEST_FIELDS and value['schema'] == SOURCE_SCHEMA)
    _need(type(value['source_id']) is str and re.fullmatch(r'[A-Za-z0-9._-]{1,128}', value['source_id']))
    _need(value['source_role'] in _ROLES and type(value['source_evidence_sha256']) is str and
          _SHA.fullmatch(value['source_evidence_sha256']))
    origins = value['allowed_origins']
    _need(type(origins) is list and 0 < len(origins) <= 64 and len(set(origins)) == len(origins))
    for origin in origins:
        _need(type(origin) is str and _origin(origin, value['source_role']) == origin)
        p = urlsplit(origin)
        _need(p.path == '' and not p.query)
    _need(_origin(value['playlist_url'], value['source_role']) in origins, 'HLS_CAPTURE_ORIGIN_DENIED')
    return _json(_wire(value))


def _private_path(path, *, directory=False):
    p = Path(path).absolute()
    _need('..' not in Path(path).parts and not any(x.is_symlink() for x in (p, *p.parents)),
          'HLS_CAPTURE_PRIVATE_PATH_REJECTED')
    info = p.lstat()
    _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600),
          'HLS_CAPTURE_PRIVATE_PATH_REJECTED')
    _need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
          'HLS_CAPTURE_PRIVATE_PATH_REJECTED')
    return p, (info.st_dev, info.st_ino)


def _read_private(path, *, maximum=_MAX_OBJECT):
    p, identity = _private_path(path)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        _need((before.st_dev, before.st_ino) == identity and 0 < before.st_size <= maximum)
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        _need((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
              (after.st_size, after.st_mtime_ns, after.st_ctime_ns) and len(raw) <= maximum)
    _need(_private_path(p)[1] == identity)
    return raw


def _hash_private(path, maximum, target=None):
    p,identity=_private_path(path)
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    digest=sha256();total=0
    with os.fdopen(fd,'rb') as source:
        before=os.fstat(source.fileno())
        _need((before.st_dev,before.st_ino)==identity and 0<before.st_size<=maximum)
        while True:
            chunk=source.read(65536)
            if not chunk:break
            total+=len(chunk);_need(total<=maximum)
            digest.update(chunk)
            if target is not None:target.write(chunk)
        after=os.fstat(source.fileno())
        _need((before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
              (after.st_size,after.st_mtime_ns,after.st_ctime_ns) and total==before.st_size)
    _need(_private_path(p)[1]==identity)
    return digest.hexdigest()


def _atomic(path, raw):
    """Create only: a complete private temporary becomes one immutable name."""
    p = Path(path)
    temporary = p.parent / ('.tmp-' + uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            _rename_private(temporary, p)
        except FileExistsError:
            _need(_read_private(p, maximum=max(_MAX_OBJECT, len(raw))) == raw,
                  'HLS_CAPTURE_IMMUTABLE_CONFLICT')
        finally:
            temporary.unlink(missing_ok=True)
        descriptor = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _rename_private(source, target):
    """Atomic no-replace publication without a crash-sensitive hardlink pair."""
    _need(source.parent == target.parent)
    rename = getattr(ctypes.CDLL(None, use_errno=True), 'renameat2', None)
    _need(rename is not None, 'HLS_CAPTURE_ATOMIC_RENAME_UNAVAILABLE')
    fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        rename.argtypes = (ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(fd,os.fsencode(source.name),fd,os.fsencode(target.name),1):
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise FileExistsError()
            raise OSError(code, 'HLS_CAPTURE_ATOMIC_RENAME_FAILED')
        os.fsync(fd)
    finally:
        os.close(fd)


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http(url, headers):
    """Normal inherited proxy/CA/TLS, no cookies, invented UA or auth refresh."""
    try:
        result = request.build_opener(_NoRedirect()).open(
            request.Request(url, headers=headers, method='GET'), timeout=30)
    except error.HTTPError as exc:
        result = exc
    return HTTPResult(result.status, result.headers, result)


def _attributes(text):
    result = {}
    while text:
        m = re.match(r'([A-Z0-9-]+)=("[^"\r\n]*"|[^,\s]+)(?:,|$)', text)
        _need(m is not None, 'HLS_CAPTURE_PLAYLIST_INVALID')
        k, v = m.group(1), m.group(2)
        _need(k not in result, 'HLS_CAPTURE_PLAYLIST_INVALID')
        result[k] = v[1:-1] if v.startswith('"') else v
        text = text[m.end():]
    return result


def _integer(value):
    _need(type(value) is str and re.fullmatch(r'[0-9]{1,19}', value) is not None,
          'HLS_CAPTURE_PLAYLIST_INVALID')
    n = int(value)
    _need(n <= 2**63-1, 'HLS_CAPTURE_PLAYLIST_INVALID')
    return n


def _byterange(token, uri, previous):
    m = re.fullmatch(r'([0-9]{1,19})(?:@([0-9]{1,19}))?', token)
    _need(m is not None, 'HLS_CAPTURE_RANGE_INVALID')
    length = _integer(m[1]); _need(0 < length <= _MAX_OBJECT, 'HLS_CAPTURE_RANGE_INVALID')
    if m[2] is not None:
        start = _integer(m[2])
    else:
        _need(previous is not None and previous[0] == uri, 'HLS_CAPTURE_RANGE_INVALID')
        start = previous[1] + previous[2]
    _need(start + length <= 2**63-1, 'HLS_CAPTURE_RANGE_INVALID')
    return start, length


def _parse(raw, base, admit):
    """Validate the complete playlist, including unselected URI references."""
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise CaptureError('HLS_CAPTURE_PLAYLIST_INVALID') from None
    lines = text.splitlines()
    _need(lines and lines[0] == '#EXTM3U' and '\x00' not in text, 'HLS_CAPTURE_PLAYLIST_INVALID')
    seq = disc = 0; duration = None; target = None; map_value = None; pdt = None
    previous = previous_map = None; byte_range = None; variants = []; segments = []
    variant = False; ended = False; seen_media = False
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        tag, _, value = line.partition(':')
        if line.startswith('#EXT-X-KEY:'):
            a = _attributes(value)
            _need(a == {'METHOD':'NONE'}, 'HLS_CAPTURE_ENCRYPTED_OR_UNSUPPORTED')
        elif tag in {'#EXT-X-SESSION-KEY', '#EXT-X-PART', '#EXT-X-PART-INF', '#EXT-X-PRELOAD-HINT',
                     '#EXT-X-SKIP', '#EXT-X-SERVER-CONTROL', '#EXT-X-RENDITION-REPORT', '#EXT-X-MEDIA',
                     '#EXT-X-I-FRAME-STREAM-INF', '#EXT-X-I-FRAMES-ONLY', '#EXT-X-SESSION-DATA', '#EXT-X-GAP'}:
            raise CaptureError('HLS_CAPTURE_ENCRYPTED_OR_UNSUPPORTED')
        elif tag == '#EXT-X-STREAM-INF':
            _attributes(value); _need(not variant and duration is None and not segments)
            variant = True
        elif tag == '#EXT-X-TARGETDURATION':
            _need(target is None); target = _integer(value); _need(target > 0)
        elif tag == '#EXT-X-MEDIA-SEQUENCE':
            _need(not seen_media); seq = _integer(value)
        elif tag == '#EXT-X-DISCONTINUITY-SEQUENCE':
            _need(not seen_media); disc = _integer(value)
        elif tag == '#EXT-X-DISCONTINUITY':
            disc += 1
        elif tag == '#EXT-X-MAP':
            a = _attributes(value); _need(set(a) <= {'URI','BYTERANGE'} and 'URI' in a)
            uri = admit(urljoin(base, a['URI']))
            br = _byterange(a['BYTERANGE'], uri, previous_map) if 'BYTERANGE' in a else None
            map_value = dict(uri=uri, byte_range=br)
            previous_map = (uri, *br) if br else None
        elif tag == '#EXT-X-BYTERANGE':
            _need(byte_range is None); byte_range = value
        elif tag == '#EXT-X-PROGRAM-DATE-TIME':
            _need(len(value)<=128);_stamp(value); pdt = value
        elif tag == '#EXTINF':
            _need(duration is None and not variant and not ended)
            try:
                duration = float(value.split(',',1)[0])
            except ValueError:
                raise CaptureError('HLS_CAPTURE_PLAYLIST_INVALID') from None
            _need(math.isfinite(duration) and duration > 0)
        elif tag == '#EXT-X-ENDLIST':
            ended = True
        elif line.startswith('#'):
            _need(not line.startswith('#EXT-X-') or tag in {'#EXT-X-VERSION', '#EXT-X-PLAYLIST-TYPE',
                  '#EXT-X-INDEPENDENT-SEGMENTS', '#EXT-X-START'}, 'HLS_CAPTURE_PLAYLIST_UNSUPPORTED')
        else:
            uri = admit(urljoin(base, line))
            if variant:
                variants.append(uri); variant = False
            else:
                _need(duration is not None and not ended and not variants)
                br = _byterange(byte_range, uri, previous) if byte_range is not None else None
                segments.append(dict(sequence=seq, discontinuity_sequence=disc, uri=uri,
                    byte_range=br, map=map_value, duration_seconds=duration, program_date_time=pdt))
                previous = (uri, *br) if br else None
                seq += 1; duration = None; byte_range = None; pdt = None; seen_media = True
    _need(duration is None and byte_range is None and not variant)
    _need(bool(variants) or target is not None)
    return dict(variants=variants, segments=segments, target=target, ended=ended)


def _media_fingerprint(item):
    # Explicit PDT may be newly attached to an already-known segment when the
    # live window slides. Its upstream claim is separate from media identity.
    return sha256(_wire({k:v for k,v in item.items() if k!='program_date_time'})).hexdigest()


class Collector:
    """One private source, serialized acquisition ticks, no background service."""
    def __init__(self, root, manifest, fetch=None, clock=None):
        self.manifest = _manifest(manifest)
        self.manifest_sha256 = sha256(_wire(self.manifest)).hexdigest()
        self.root = Path(root).absolute()
        _need(not any((p/'.git').exists() for p in (self.root, *self.root.parents)),
              'HLS_CAPTURE_OUTSIDE_GIT_REQUIRED')
        self.root.mkdir(mode=0o700, exist_ok=True)
        _, self._root_identity = _private_path(self.root, directory=True)
        for name in ('blobs', 'exports'):
            (self.root/name).mkdir(mode=0o700, exist_ok=True)
            _private_path(self.root/name, directory=True)
        self._lock_fd = os.open(self.root/'capture.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        _private_path(self.root/'capture.lock')
        self.db = None
        self.fetch = fetch or _http
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        try:
            with self._lock():
                path = self.root/'capture.sqlite'
                if not path.exists():
                    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    os.close(fd)
                _, self._db_identity = _private_path(path)
                self.db = sqlite3.connect(path, isolation_level=None)
                self.db.row_factory = sqlite3.Row
                self.db.executescript('''
                    PRAGMA synchronous=FULL;
                    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, url_sha TEXT NOT NULL,
                      role TEXT NOT NULL, range_start INTEGER, range_length INTEGER, state TEXT NOT NULL,
                      started_at TEXT NOT NULL, completed_at TEXT, status INTEGER, body_sha TEXT, bytes INTEGER);
                    CREATE TABLE IF NOT EXISTS resources (key TEXT PRIMARY KEY, body_sha TEXT NOT NULL,
                      bytes INTEGER NOT NULL, captured_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS objects (sha TEXT PRIMARY KEY, bytes INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS windows (id INTEGER PRIMARY KEY, closed INTEGER NOT NULL,
                      duration REAL NOT NULL, closure_reason TEXT, export_json TEXT);
                    CREATE TABLE IF NOT EXISTS segments (sequence INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL,
                      body_sha TEXT NOT NULL, map_sha TEXT, window_id INTEGER NOT NULL, duration REAL NOT NULL,
                      captured_at TEXT NOT NULL, metadata TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS segment_windows ON segments(window_id,sequence);
                    CREATE TABLE IF NOT EXISTS gaps (id INTEGER PRIMARY KEY, expected INTEGER NOT NULL,
                      observed INTEGER NOT NULL, recorded_at TEXT NOT NULL, reason TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS export_intents (window_id INTEGER PRIMARY KEY,
                      receipt_json TEXT NOT NULL, record_json TEXT NOT NULL, staging_name TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS pdt_claims (id INTEGER PRIMARY KEY,sequence INTEGER NOT NULL,
                      claim TEXT NOT NULL,observed_at TEXT NOT NULL,playlist_sha256 TEXT NOT NULL,
                      UNIQUE(sequence,claim));
                ''')
                if 'wait_json' not in {r[1] for r in self.db.execute('PRAGMA table_info(requests)')}:
                    self.db.execute('ALTER TABLE requests ADD COLUMN wait_json TEXT')
                if self._meta('schema') is None:
                    with self._transaction():
                        self._set('schema', _SCHEMA); self._set('manifest', self.manifest)
                        self._set('manifest_sha256', self.manifest_sha256)
                _need(self._meta('schema') == _SCHEMA and self._meta('manifest') == self.manifest and
                      self._meta('manifest_sha256') == self.manifest_sha256, 'HLS_CAPTURE_SOURCE_MISMATCH')
                self.db.execute("UPDATE requests SET state='UNKNOWN' WHERE state='PENDING'")
                self.db.execute('INSERT OR IGNORE INTO objects SELECT body_sha,MAX(bytes) FROM resources GROUP BY body_sha')
                self._restore_wait()
        except BaseException:
            self.close(); raise

    def close(self):
        if self.db is not None:
            self.db.close(); self.db = None
        if getattr(self, '_lock_fd', None) is not None:
            os.close(self._lock_fd); self._lock_fd = None

    @contextmanager
    def _lock(self):
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

    def _guard(self):
        _need(self.db is not None and _private_path(self.root, directory=True)[1] == self._root_identity)
        _need(_private_path(self.root/'capture.sqlite')[1] == self._db_identity)
        _need(_private_path(self.root/'capture.lock')[1] ==
              (os.fstat(self._lock_fd).st_dev, os.fstat(self._lock_fd).st_ino))
        for name in ('blobs', 'exports'):
            _private_path(self.root/name, directory=True)
        _need(self._meta('manifest_sha256') == self.manifest_sha256 and self._meta('manifest') == self.manifest)

    @contextmanager
    def _transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        else:
            self.db.execute('COMMIT')

    def _restore_wait(self):
        """Known denials survive older split-write checkpoints and restarts."""
        authorization = self.db.execute('SELECT * FROM requests WHERE status IN (401,403) ORDER BY id DESC LIMIT 1').fetchone()
        last = self.db.execute('SELECT * FROM requests ORDER BY id DESC LIMIT 1').fetchone()
        row = authorization or last
        if row is None:
            return
        plan = _json(row['wait_json']) if row['wait_json'] else None
        if authorization and plan is None:
            plan = plan_http_wait(row['status'], {}, row['completed_at'] or row['started_at'])
        if plan is not None and (authorization or self._meta('source_wait') is None):
            self._set('source_wait',plan)

    def _now(self):
        value = self.clock(); _need(isinstance(value, datetime), 'HLS_CAPTURE_CLOCK_INVALID')
        return _stamp(value)

    def _meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return _json(row[0]) if row else None

    def _set(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, _wire(value).decode()))

    def _admit(self, url):
        _need(_origin(url, self.manifest['source_role']) in self.manifest['allowed_origins'],
              'HLS_CAPTURE_ORIGIN_DENIED')
        return url

    def _blob(self, sha, *, read=False):
        _need(type(sha) is str and _SHA.fullmatch(sha), 'HLS_CAPTURE_MEDIA_INTEGRITY')
        path=self.root/'blobs'/(sha+'.blob')
        _need(_hash_private(path,_MAX_OBJECT)==sha,'HLS_CAPTURE_MEDIA_INTEGRITY')
        return _read_private(path,maximum=_MAX_PLAYLIST) if read else path

    def _review(self, reason):
        self._set('source_wait', dict(state='SOURCE_REVIEW_WAIT', reason=reason, retry_at=None,
                                     http_status=None, attempts=1))

    def _wait(self, status, headers, *, publication=False, request_id=None, failure_id=None):
        attempt = (self._meta('failure_attempt') or 0) + 1
        now=self._now().isoformat()
        plan=plan_http_wait(status,headers,now,attempt=attempt,not_yet_published=publication)
        with self._transaction():
            if request_id is not None:
                self.db.execute("UPDATE requests SET state='COMPLETE',status=?,completed_at=?,bytes=0,wait_json=? WHERE id=?",
                                (status,now,_wire(plan).decode(),request_id))
            if failure_id is not None:
                self.db.execute("UPDATE requests SET state='FAILED',completed_at=?,wait_json=? WHERE id=?",
                                (now,_wire(plan).decode(),failure_id))
            self._set('failure_attempt',attempt)
            self._set('source_wait',plan)
        raise _Waiting()

    def _get(self, url, role, byte_range=None, *, context=None):
        url = self._admit(url)
        key = sha256(_wire([url, byte_range, role, context])).hexdigest()
        if role != 'playlist':
            cached = self.db.execute('SELECT * FROM resources WHERE key=?', (key,)).fetchone()
            if cached:
                self._blob(cached['body_sha'])
                return cached['body_sha'], cached['captured_at'], url
        visited = set()
        for _ in range(6):
            _need(url not in visited, 'HLS_CAPTURE_REDIRECT_LOOP'); visited.add(url)
            self._admit(url)
            headers = {} if byte_range is None else {'Range': f'bytes={byte_range[0]}-{sum(byte_range)-1}'}
            row = self.db.execute('INSERT INTO requests(url_sha,role,range_start,range_length,state,started_at) '
                'VALUES (?,?,?,?,?,?)', (sha256(url.encode()).hexdigest(), role,
                byte_range[0] if byte_range else None, byte_range[1] if byte_range else None,
                'PENDING', self._now().isoformat()))
            ident = row.lastrowid
            try:
                result = self.fetch(url, headers)
            except Exception:
                self.db.execute("UPDATE requests SET state='FAILED',completed_at=? WHERE id=?",
                                (self._now().isoformat(), ident))
                self._wait(None, {},failure_id=ident)
            _need(isinstance(result, HTTPResult) and type(result.status) is int and 100 <= result.status <= 599)
            status = result.status
            response_headers = {}
            for k in result.headers.keys():
                if str(k).lower() in ('location','retry-after','content-range','content-length'):
                    response_headers[str(k).lower()]=str(result.headers[k])
            try:
                if status not in (200,206):
                    if status in (301,302,303,307,308):
                        self.db.execute("UPDATE requests SET state='COMPLETE',status=?,completed_at=?,bytes=0 WHERE id=?",
                                        (status,self._now().isoformat(),ident))
                        _need('location' in response_headers, 'HLS_CAPTURE_REDIRECT_INVALID')
                        url = self._admit(urljoin(url, response_headers['location']))
                        continue
                    self._wait(status,response_headers,publication=status==404,request_id=ident)
                if byte_range is not None:
                    start, length = byte_range
                    m = re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/(?:[0-9]+|\*)',response_headers.get('content-range',''))
                    _need(status == 206 and m is not None and int(m[1]) == start and int(m[2]) == start+length-1,
                          'HLS_CAPTURE_RANGE_RESPONSE_INVALID')
                else:
                    _need(status == 200, 'HLS_CAPTURE_RANGE_RESPONSE_INVALID')
                maximum = _MAX_PLAYLIST if role == 'playlist' else _MAX_OBJECT
                expected = byte_range[1] if byte_range else None
                if 'content-length' in response_headers:
                    length=response_headers['content-length'].strip()
                    _need(re.fullmatch(r'[0-9]{1,19}',length) is not None,'HLS_CAPTURE_RESPONSE_LENGTH_INVALID')
                    declared=int(length)
                    _need(declared<=maximum and (expected is None or declared==expected),
                          'HLS_CAPTURE_RESPONSE_LENGTH_INVALID')
                    expected=declared
                sha, size = self._stream_blob(result.body, maximum, expected)
                at = self._now().isoformat()
                with self._transaction():
                    self.db.execute("UPDATE requests SET state='COMPLETE',status=?,completed_at=?,body_sha=?,bytes=? WHERE id=?",
                                    (status,at,sha,size,ident))
                    self.db.execute('INSERT OR IGNORE INTO objects VALUES (?,?)',(sha,size))
                    if role != 'playlist':
                        self.db.execute('INSERT INTO resources VALUES (?,?,?,?)', (key,sha,size,at))
                return sha, at, url
            except (_IncompleteBody,http.client.HTTPException,OSError):
                self.db.execute("UPDATE requests SET status=? WHERE id=?",(status,ident))
                self._wait(None,response_headers,failure_id=ident)
            finally:
                close = getattr(result.body, 'close', None)
                if callable(close): close()
        raise CaptureError('HLS_CAPTURE_REDIRECT_LOOP')

    def _stream_blob(self, body, maximum, expected):
        _need(callable(getattr(body,'read',None)), 'HLS_CAPTURE_RESPONSE_INVALID')
        temporary = self.root/'blobs'/('.tmp-'+uuid4().hex)
        fd = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        digest = sha256(); size = 0
        try:
            with os.fdopen(fd,'wb') as stream:
                while True:
                    chunk = body.read(min(65536, maximum-size+1))
                    _need(type(chunk) is bytes, 'HLS_CAPTURE_RESPONSE_INVALID')
                    if not chunk: break
                    size += len(chunk); _need(size <= maximum, 'HLS_CAPTURE_RESPONSE_TOO_LARGE')
                    stream.write(chunk); digest.update(chunk)
                if expected is not None and size<expected:
                    raise _IncompleteBody()
                _need(size > 0 and (expected is None or size == expected), 'HLS_CAPTURE_RESPONSE_LENGTH_INVALID')
                stream.flush(); os.fsync(stream.fileno())
            sha = digest.hexdigest(); target = self.root/'blobs'/(sha+'.blob')
            try: _rename_private(temporary,target)
            except FileExistsError: self._blob(sha)
            temporary.unlink(missing_ok=True)
            directory = os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try: os.fsync(directory)
            finally: os.close(directory)
            return sha,size
        finally:
            temporary.unlink(missing_ok=True)

    def _close_window(self, reason):
        self.db.execute('UPDATE windows SET closed=1,closure_reason=? WHERE closed=0', (reason,))

    def _record_pdt(self, items, playlist_sha, observed_at):
        with self._transaction():
            for item in items:
                claim=item['program_date_time']
                if claim is None:continue
                prior=[r[0] for r in self.db.execute('SELECT claim FROM pdt_claims WHERE sequence=?',(item['sequence'],))]
                old=self.db.execute('SELECT metadata FROM segments WHERE sequence=?',(item['sequence'],)).fetchone()
                if old and _json(old[0]).get('program_date_time') is not None:
                    prior.append(_json(old[0])['program_date_time'])
                _need(all(_stamp(p)==_stamp(claim) for p in prior),'HLS_CAPTURE_PDT_CLAIM_CONFLICT')
                self.db.execute('INSERT OR IGNORE INTO pdt_claims(sequence,claim,observed_at,playlist_sha256) '
                                'VALUES (?,?,?,?)',(item['sequence'],claim,observed_at,playlist_sha))

    def _append(self, item, fingerprint, body_sha, map_sha, at):
        previous = self.db.execute('SELECT * FROM segments ORDER BY sequence DESC LIMIT 1').fetchone()
        if previous:
            old = _json(previous['metadata'])
            if item['sequence'] > previous['sequence'] + 1:
                self._close_window('SLIDING_GAP')
                self.db.execute('INSERT INTO gaps(expected,observed,recorded_at,reason) VALUES (?,?,?,?)',
                    (previous['sequence']+1,item['sequence'],at,'SLIDING_GAP'))
            elif item['discontinuity_sequence'] != old['discontinuity_sequence']:
                self._close_window('DISCONTINUITY')
            elif map_sha != previous['map_sha']:
                self._close_window('MAP_CHANGE')
        row = self.db.execute('SELECT id FROM windows WHERE closed=0').fetchone()
        wid = row['id'] if row else self.db.execute('INSERT INTO windows(closed,duration) VALUES (0,0)').lastrowid
        safe = {k:item[k] for k in ('sequence','discontinuity_sequence','byte_range','duration_seconds','program_date_time')}
        safe.update(uri_sha256=sha256(item['uri'].encode()).hexdigest(),map_sha256=map_sha)
        self.db.execute('INSERT INTO segments VALUES (?,?,?,?,?,?,?,?)',
            (item['sequence'],fingerprint,body_sha,map_sha,wid,item['duration_seconds'],at,_wire(safe).decode()))
        self.db.execute('UPDATE windows SET duration=duration+? WHERE id=?', (item['duration_seconds'],wid))
        duration = self.db.execute('SELECT duration FROM windows WHERE id=?',(wid,)).fetchone()[0]
        if duration >= _WINDOW_SECONDS: self._close_window('WINDOW_DURATION')

    def _summary(self):
        counts = {r['state']:r['n'] for r in self.db.execute('SELECT state,COUNT(*) n FROM requests GROUP BY state')}
        wait = self._meta('source_wait')
        return dict(status=wait['state'] if wait else 'ENDED' if self._meta('ended') else 'ACQUIRING',
            source_id=self.manifest['source_id'],source_role=self.manifest['source_role'],manifest_sha256=self.manifest_sha256,
            requests_attempted=sum(counts.values()),requests_completed=counts.get('COMPLETE',0),
            requests_unknown=counts.get('UNKNOWN',0)+counts.get('PENDING',0),requests_failed=counts.get('FAILED',0),
            segments_saved=self.db.execute('SELECT COUNT(*) FROM segments').fetchone()[0],
            gaps_recorded=self.db.execute('SELECT COUNT(*) FROM gaps').fetchone()[0],source_wait=wait,
            next_poll_at=wait.get('retry_at') if wait else self._meta('next_poll_at'),
            ready_windows=[r[0] for r in self.db.execute('SELECT id FROM windows WHERE closed=1 AND export_json IS NULL ORDER BY id LIMIT 100')])

    def tick(self):
        self._guard()
        try:
            with self._lock():
                self._guard(); now = self._now()
                last = self._meta('last_clock')
                _need(last is None or _stamp(last) <= now, 'HLS_CAPTURE_CLOCK_REVERSED')
                self._set('last_clock',now.isoformat())
                wait = self._meta('source_wait')
                if wait and wait_active(wait,now): return self._summary()
                if self._meta('ended'): return self._summary()
                poll = self._meta('next_poll_at')
                if not wait and poll and now < _stamp(poll): return self._summary()
                self._set('source_wait',None)
                try:
                    uri = self._meta('selected_url') or self._meta('media_url') or self.manifest['playlist_url']
                    for level in range(5):
                        sha, playlist_at, final = self._get(uri,'playlist')
                        parsed = _parse(self._blob(sha,read=True),final,self._admit)
                        if not parsed['variants']:
                            with self._transaction():
                                self._set('media_url',final);self._set('selected_url',final)
                            break
                        _need(self._meta('media_url') is None, 'HLS_CAPTURE_VARIANT_CHANGED')
                        uri = parsed['variants'][0]
                        # Pin the chosen nested frontier BEFORE the first GET;
                        # a rate limit cannot reopen selection at an ancestor.
                        self._set('selected_url',uri)
                    else:
                        raise CaptureError('HLS_CAPTURE_MASTER_DEPTH')
                    items = parsed['segments']
                    # Pin every repeated sequence before acquiring ANY new map/media.
                    for item in items:
                        fp = _media_fingerprint(item)
                        old = self.db.execute('SELECT * FROM segments WHERE sequence=?',(item['sequence'],)).fetchone()
                        if old:
                            legacy=dict(item,program_date_time=_json(old['metadata'])['program_date_time'])
                            _need(old['fingerprint'] in (fp,sha256(_wire(legacy)).hexdigest()),'HLS_CAPTURE_SEQUENCE_CHANGED')
                            self._blob(old['body_sha'])
                            if old['map_sha']: self._blob(old['map_sha'])
                    self._record_pdt(items,sha,playlist_at)
                    if items:
                        first = items[0]['sequence']; prior = self._meta('last_playlist_start')
                        _need(prior is None or first >= prior,'HLS_CAPTURE_ENCODER_RESET')
                        self._set('last_playlist_start',first)
                    for item in items:
                        if self.db.execute('SELECT 1 FROM segments WHERE sequence=?',(item['sequence'],)).fetchone(): continue
                        map_sha = None
                        if item['map']:
                            m = item['map']; map_sha,_,_ = self._get(m['uri'],'map',m['byte_range'],
                                context=[item['discontinuity_sequence']])
                        body_sha,at,_ = self._get(item['uri'],'segment',item['byte_range'],
                            context=[item['sequence'],item['discontinuity_sequence'],map_sha])
                        with self._transaction():
                            self._append(item,_media_fingerprint(item),body_sha,map_sha,at)
                    if parsed['ended']:
                        self._close_window('ENDLIST'); self._set('ended',True); self._set('next_poll_at',None)
                    elif not items:
                        self._wait(200,{},publication=True)
                    else:
                        self._set('next_poll_at',(self._now()+timedelta(seconds=parsed['target'])).isoformat())
                    self._set('failure_attempt',0)
                except _Waiting:
                    pass
                except (CaptureError, OSError, sqlite3.Error, OverflowError):
                    self._review('HLS_CAPTURE_SOURCE_OR_INTEGRITY_REVIEW_REQUIRED')
                return self._summary()
        except BlockingIOError:
            value=self._summary(); value['status']='BUSY'; return value

    def list_windows(self, after_id=0, limit=100):
        self._guard()
        _need(type(after_id) is int and after_id >= 0 and type(limit) is int and 1 <= limit <= 1000)
        result=[]
        for row in self.db.execute('SELECT w.*,COUNT(s.sequence) n FROM windows w LEFT JOIN segments s '
                'ON s.window_id=w.id WHERE w.id>? GROUP BY w.id ORDER BY w.id LIMIT ?', (after_id,limit)):
            hold=self._analysis_hold(row)
            result.append(dict(window_id=row['id'],closed=bool(row['closed']),exported=row['export_json'] is not None,
                duration_seconds=row['duration'],closure_reason=row['closure_reason'],segment_count=row['n'],
                analysis_exportable=hold is None,analysis_hold_reason=hold))
        return result

    def _analysis_hold(self, row):
        if row['duration']>_MAX_ANALYSIS_SECONDS:
            return 'CLIP_DURATION_EXCEEDS_ANALYSIS_BOUND'
        size=self.db.execute('SELECT COALESCE(SUM(o.bytes),0) FROM segments s JOIN objects o ON o.sha=s.body_sha '
                             'WHERE s.window_id=?',(row['id'],)).fetchone()[0]
        first=self.db.execute('SELECT map_sha FROM segments WHERE window_id=? ORDER BY sequence LIMIT 1',(row['id'],)).fetchone()
        if first and first[0]:
            entry=self.db.execute('SELECT bytes FROM objects WHERE sha=?',(first[0],)).fetchone()
            _need(entry is not None,'HLS_CAPTURE_MEDIA_INTEGRITY')
            size+=entry[0]
        if size>_MAX_ANALYSIS_BYTES:
            return 'CLIP_BYTES_EXCEED_ANALYSIS_BOUND'
        return None

    def _window_segments(self, window_id):
        segments=list(self.db.execute('SELECT * FROM segments WHERE window_id=? ORDER BY sequence',(window_id,)))
        _need(segments,'HLS_CAPTURE_EMPTY_WINDOW')
        metadata=[]
        first=_json(segments[0]['metadata'])
        for index,segment in enumerate(segments):
            m=_json(segment['metadata']);m.update(media_sha256=segment['body_sha'],captured_at=segment['captured_at'])
            _need(not index or segment['sequence']==segments[index-1]['sequence']+1)
            _need(segment['map_sha']==segments[0]['map_sha'] and m['discontinuity_sequence']==first['discontinuity_sequence'])
            self._blob(segment['body_sha'])
            if segment['map_sha']:self._blob(segment['map_sha'])
            metadata.append(m)
        return segments,metadata

    def _finish_export(self, intent, metadata):
        receipt=_json(intent['receipt_json']);value=_json(intent['record_json'])
        wid=intent['window_id'];media=self.root/'exports'/f'{wid}.mp4';path=self.root/'exports'/f'{wid}.json'
        _need(receipt['segments']==metadata and receipt['window_id']==wid and
              receipt['manifest_sha256']==self.manifest_sha256 and
              value['manifest_sha256']==self.manifest_sha256 and value['window_id']==wid and
              value['media_path']==str(media) and value['receipt_path']==str(path))
        _need(_stamp(receipt['last_media_captured_at'])<=_stamp(receipt['captured_at'])<=self._now())
        _need(re.fullmatch(r'\.tmp-export-[a-f0-9]{32}\.mp4',intent['staging_name']) is not None)
        staged=self.root/'exports'/intent['staging_name']
        if media.exists():
            _need(_hash_private(media,_MAX_ANALYSIS_BYTES)==value['media_sha256'])
        else:
            _need(_hash_private(staged,_MAX_ANALYSIS_BYTES)==value['media_sha256'])
            _rename_private(staged,media)
        raw=_wire(receipt);_need(sha256(raw).hexdigest()==value['receipt_sha256'])
        _atomic(path,raw)
        with self._transaction():
            self.db.execute('UPDATE windows SET export_json=? WHERE id=?',(_wire(value).decode(),wid))
        return verify_export(value)

    @contextmanager
    def _export_stage(self):
        media=self.root/'exports'/('.tmp-export-'+uuid4().hex+'.mp4')
        fd=os.open(media,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
        try:
            yield media
        finally:
            # A durable intent owns its stage across restart. Earlier partial
            # output is ours to remove, never a source original or receipt.
            try:
                intended=self.db.execute('SELECT 1 FROM export_intents WHERE staging_name=?',(media.name,)).fetchone()
            except sqlite3.Error:
                intended=True  # Do not destroy recovery bytes on DB failure.
            if not intended:
                media.unlink(missing_ok=True)
                directory=os.open(media.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:os.fsync(directory)
                finally:os.close(directory)

    def export_window(self, window_id):
        self._guard(); _need(type(window_id) is int and window_id > 0)
        with self._lock():
            self._guard()
            row = self.db.execute('SELECT * FROM windows WHERE id=?',(window_id,)).fetchone()
            _need(row is not None and row['closed'], 'HLS_CAPTURE_WINDOW_NOT_CLOSED')
            if row['export_json'] is not None: return verify_export(_json(row['export_json']))
            _need(self._analysis_hold(row) is None,'HLS_CAPTURE_WINDOW_ANALYSIS_INELIGIBLE')
            segments,metadata=self._window_segments(window_id)
            intent=self.db.execute('SELECT * FROM export_intents WHERE window_id=?',(window_id,)).fetchone()
            if intent:return self._finish_export(intent,metadata)
            with tempfile.TemporaryDirectory(prefix='.remux-',dir=self.root) as temporary,self._export_stage() as media:
                folder=Path(temporary); os.chmod(folder,0o700)
                combined=folder/'input.media'
                fd=os.open(combined,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as target:
                    for sha in ([segments[0]['map_sha']] if segments[0]['map_sha'] else [])+[s['body_sha'] for s in segments]:
                        _need(_hash_private(self._blob(sha),_MAX_OBJECT,target)==sha,'HLS_CAPTURE_MEDIA_INTEGRITY')
                try:
                    completed=subprocess.run(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe',
                        '-format_whitelist','mov,mpegts','-copyts','-i',str(combined),'-map','0:v:0','-c:v','copy',
                        '-map','0:a:0?','-c:a','copy','-avoid_negative_ts','disabled',
                        '-movflags','+faststart','-y',str(media)],
                        capture_output=True,check=True,timeout=120)
                    _need(not completed.stderr.strip(),'HLS_CAPTURE_LOCAL_REMUX_FAILED')
                except (OSError,subprocess.SubprocessError):
                    raise CaptureError('HLS_CAPTURE_LOCAL_REMUX_FAILED') from None
                media_sha=_hash_private(media,_MAX_ANALYSIS_BYTES)
                with media.open('rb') as stream:os.fsync(stream.fileno())
                directory=os.open(media.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:os.fsync(directory)
                finally:os.close(directory)
                at=self._now().isoformat()
                receipt=dict(schema=EXPORT_SCHEMA,source_id=self.manifest['source_id'],source_role=self.manifest['source_role'],
                    manifest_sha256=self.manifest_sha256,window_id=window_id,media_sha256=media_sha,captured_at=at,
                    capture_started_at=segments[0]['captured_at'],last_media_captured_at=segments[-1]['captured_at'],
                    segments=metadata,timeline='MEDIA_PTS_NOT_UPSTREAM_PDT',
                    audio_policy='FIRST_EMBEDDED_AUDIO_STREAM_COPY_IF_PRESENT',
                    map_reuse_scope='URI_RANGE_DISCONTINUITY_CONTEXT_NOT_PROVIDER_IMMUTABILITY_PROOF',
                    forecast_eligible=False,production_eligible=False)
                pdt_max=self.db.execute('SELECT COALESCE(MAX(id),0) FROM pdt_claims').fetchone()[0]
                receipt.update(pdt_claim_max_id=pdt_max,program_date_time_claims=[dict(r) for r in
                    self.db.execute('SELECT p.* FROM pdt_claims p JOIN segments s ON s.sequence=p.sequence '
                                    'WHERE s.window_id=? AND p.id<=? ORDER BY p.id',(window_id,pdt_max))])
                receipt_raw=_wire(receipt); receipt_sha=sha256(receipt_raw).hexdigest()
                target=self.root/'exports'/f'{window_id}.mp4'; receipt_path=self.root/'exports'/f'{window_id}.json'
                value=dict(schema=EXPORT_SCHEMA,source_id=self.manifest['source_id'],source_role=self.manifest['source_role'],
                    manifest_sha256=self.manifest_sha256,window_id=window_id,media_path=str(target),media_sha256=media_sha,
                    receipt_path=str(receipt_path),receipt_sha256=receipt_sha,captured_at=at)
                self.db.execute('INSERT INTO export_intents VALUES (?,?,?,?)',
                    (window_id,_wire(receipt).decode(),_wire(value).decode(),media.name))
                intent=self.db.execute('SELECT * FROM export_intents WHERE window_id=?',(window_id,)).fetchone()
                return self._finish_export(intent,metadata)


def verify_export(export_record):
    """Replay private DB registration, exact receipt, MP4 and original blobs.

    This authenticates local consistency only, not upstream source rights,
    current race identity or a pre-cutoff provider witness. No HTTP or mutation.
    """
    try:
        _need(type(export_record) is dict and set(export_record)=={'schema','source_id','source_role','manifest_sha256',
            'window_id','media_path','media_sha256','receipt_path','receipt_sha256','captured_at'})
        _need(export_record['schema']==EXPORT_SCHEMA and type(export_record['window_id']) is int and export_record['window_id']>0)
        receipt_path=Path(export_record['receipt_path']).absolute(); root=receipt_path.parent.parent
        _private_path(root,directory=True); _private_path(root/'exports',directory=True); _private_path(root/'blobs',directory=True)
        _need(receipt_path==root/'exports'/f"{export_record['window_id']}.json" and
              Path(export_record['media_path'])==root/'exports'/f"{export_record['window_id']}.mp4")
        _private_path(root/'capture.sqlite')
        with sqlite3.connect('file:'+str(root/'capture.sqlite')+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM windows WHERE id=?',(export_record['window_id'],)).fetchone()
            _need(row is not None and row['closed'] and row['export_json'] is not None and _json(row['export_json'])==export_record)
            meta={r['key']:_json(r['value']) for r in db.execute('SELECT * FROM meta WHERE key IN (?,?,?)',('manifest','manifest_sha256','schema'))}
            source=_manifest(meta['manifest'])
            _need(meta['schema']==_SCHEMA and sha256(_wire(source)).hexdigest()==meta['manifest_sha256']==export_record['manifest_sha256'])
            _need(source['source_id']==export_record['source_id'] and source['source_role']==export_record['source_role'])
            raw=_read_private(receipt_path,maximum=_MAX_PLAYLIST)
            _need(sha256(raw).hexdigest()==export_record['receipt_sha256'])
            receipt=_json(raw)
            for name in ('schema','source_id','source_role','manifest_sha256','window_id','media_sha256','captured_at'):
                _need(receipt[name]==export_record[name])
            _need(receipt['forecast_eligible'] is False and receipt['production_eligible'] is False)
            if 'audio_policy' in receipt:
                _need(receipt['audio_policy']=='FIRST_EMBEDDED_AUDIO_STREAM_COPY_IF_PRESENT')
            segments=list(db.execute('SELECT * FROM segments WHERE window_id=? ORDER BY sequence',(export_record['window_id'],)))
            expected=[]
            for index,segment in enumerate(segments):
                m=_json(segment['metadata']);m.update(media_sha256=segment['body_sha'],captured_at=segment['captured_at']);expected.append(m)
                _need(not index or segment['sequence']==segments[index-1]['sequence']+1)
                for blob in (segment['body_sha'],segment['map_sha']):
                    if blob is not None:
                        _need(type(blob) is str and _SHA.fullmatch(blob))
                        _need(_hash_private(root/'blobs'/(blob+'.blob'),_MAX_OBJECT)==blob)
            _need(expected and receipt['segments']==expected)
            if 'pdt_claim_max_id' in receipt:
                maximum=receipt['pdt_claim_max_id'];_need(type(maximum) is int and maximum>=0)
                claims=[dict(r) for r in db.execute('SELECT p.* FROM pdt_claims p JOIN segments s ON s.sequence=p.sequence '
                    'WHERE s.window_id=? AND p.id<=? ORDER BY p.id',(export_record['window_id'],maximum))]
                _need(receipt['program_date_time_claims']==claims and all(
                    _stamp(r['observed_at'])<=_stamp(receipt['captured_at']) for r in claims))
            _need(_stamp(receipt['capture_started_at'])<=_stamp(receipt['last_media_captured_at'])<=_stamp(receipt['captured_at']))
            _need(_hash_private(export_record['media_path'],_MAX_ANALYSIS_BYTES)==export_record['media_sha256'])
        return _json(_wire(export_record))
    except (KeyError,TypeError,OSError,sqlite3.Error,OverflowError,ValueError):
        raise CaptureError('HLS_CAPTURE_EXPORT_REJECTED') from None
