"""Bounded, current-day official BOAT input collection for private generation.

This provider performs no model inference. Exact originals are retained before
parsing; trusted application code separately admits personal analysis/private
storage. Source hashes and a local capture clock are not external attestation.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib import error, request
from urllib.parse import urlsplit
import uuid

import race_ai

_REPO = Path(__file__).resolve().parents[1]
for _name in ("pr64-reference", "pr72-reference"):
    _path = str(_REPO / _name / "race_ai")
    if _path not in race_ai.__path__:
        race_ai.__path__.append(_path)

from .official_archive_probe import official_url, inspect_lzh, MAX_ARCHIVE_BYTES
from .official_lzh_extract import extract_daily_lzh
from .program_race_isolation import normalize_races
from .boat_observed_program_bridge import build_program_snapshot
from .private_cycle_capture import _parent_handle
from .boat_deadline_queue import select_due_races
from .source_retry_policy import SourceWait, plan_http_wait, wait_active

JST = timezone(timedelta(hours=9))
# The owner explicitly removed numeric cumulative and per-call GET quotas.
# None is an actual unlimited policy value, never a large numeric sentinel.
REQUEST_LIMIT = None
CALL_REQUEST_LIMIT = None
P1_RACE_LIMIT = 3
DISCOVERY_SECONDS = 180
BUFFER = timedelta(seconds=210)
STATE_SCHEMA = "RACE_AI_CURRENT_BOAT_SOURCE_STATE_V1"
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class CurrentBoatInputError(ValueError):
    """A fixed safe reason; no source bodies, private paths or tickets."""

class CurrentBoatSourceWait(CurrentBoatInputError, SourceWait):
    """Compatible domain error carrying the shared nonterminal wait fields."""


def _need(value, reason="CURRENT_BOAT_INPUT_REJECTED"):
    if not value:
        raise CurrentBoatInputError(reason)


def _moment(value):
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(value.utcoffset() is not None, "SOURCE_CLOCK_REQUIRES_TIMEZONE")
        return value
    except (TypeError, AttributeError, ValueError, OverflowError):
        raise CurrentBoatInputError("SOURCE_CLOCK_REQUIRES_TIMEZONE") from None


def _identity(info):
    return info.st_dev, info.st_ino


def _private_file(info):
    _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
          and stat.S_IMODE(info.st_mode) == 0o600, "PRIVATE_SOURCE_FILE_REQUIRED")


def _write(fd, name, raw):
    _need(_FILE.fullmatch(name) is not None)
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(handle, "wb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _read(fd, name, limit):
    _need(type(name) is str and _FILE.fullmatch(name) is not None)
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(handle, "rb") as stream:
        info = os.fstat(stream.fileno()); _private_file(info)
        _need(0 < info.st_size <= limit, "PRIVATE_SOURCE_SIZE_REJECTED")
        raw = stream.read(limit + 1)
        _need(len(raw) == info.st_size and len(raw) <= limit and
              _identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) == _identity(info) and
              os.fstat(stream.fileno()).st_mtime_ns == info.st_mtime_ns, "PRIVATE_SOURCE_CHANGED")
        return raw


def _json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            _need(key not in out, "DUPLICATE_SOURCE_STATE_FIELD"); out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: _need(False, "INVALID_SOURCE_STATE_JSON"))


def _wire(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()

def _replace_json(folder,name,value):
    temporary='write-'+uuid.uuid4().hex+'.json'
    _write(folder,temporary,_wire(value))
    try:_private_file(os.stat(name,dir_fd=folder,follow_symlinks=False))
    except FileNotFoundError:pass
    os.replace(temporary,name,src_dir_fd=folder,dst_dir_fd=folder);os.fsync(folder)

def _raise_wait(wait):
    raise CurrentBoatSourceWait(wait['reason'],wait.get('retry_at'),state=wait['state'])

def _guard(callback):
    if callback is not None:
        _need(callable(callback),'TRUSTED_AUTOMATIC_GUARD_REQUIRED')
        try:_moment(callback())
        except ValueError:raise CurrentBoatInputError('AUTOMATIC_SESSION_END') from None

def _final_publication_allowed(state,rid,cutoff,now,preferred):
    if not preferred or (_moment(cutoff)-now).total_seconds()>600 or rid in state['final_publication_attempts']:
        return False
    wait=state['publication_waits'].get(rid)
    return not(wait and wait.get('server_retry_after') and wait_active(wait,now))


class _NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CurrentBoatInputError("OFFICIAL_SOURCE_REDIRECT_REJECTED")


def _default_open(req, *, timeout):
    return request.build_opener(_NoRedirects()).open(req, timeout=timeout)


class CurrentBoatInputs:
    """One explicit collection, fixed current JST day, no background polling.

    The private root is application-owned, outside Git and never selected by a
    browser request. A process lock and durable attempt counter survive restart.
    Cumulative and per-call GET counts have no numeric quota. The existing
    fresh-race batch, refresh interval, clock/session boundaries, and source
    failure stops remain: no retry or alternate endpoint occurs after HTTP4xx,
    redirect, or source identity/parse failure.
    """
    capabilities = {sport:{stage:sport == "boat" for stage in ("P0","P1")}
                    for sport in ("boat","keirin","autorace","horse")}
    def __init__(self, private_root, *, clock=None, opener=None):
        self.root = Path(private_root).expanduser()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.opener = opener or _default_open
        try:
            _need(os.name == "posix" and self.root.is_absolute() and ".." not in self.root.parts
                  and _FILE.fullmatch(self.root.name) is not None, "PRIVATE_SOURCE_ROOT_REQUIRED")
            with _parent_handle(self.root.parent) as parent:
                try: os.mkdir(self.root.name, 0o700, dir_fd=parent)
                except FileExistsError: pass
            with _parent_handle(self.root) as fd:
                info = os.fstat(fd)
                _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                      "PRIVATE_SOURCE_ROOT_REQUIRED")
                self.root_identity = _identity(info)
        except (ValueError, OSError):
            raise CurrentBoatInputError("PRIVATE_SOURCE_ROOT_REQUIRED") from None

    @contextmanager
    def _locked_day(self, day, *, create=True):
        with _parent_handle(self.root) as root:
            _need(_identity(os.fstat(root)) == self.root_identity, "PRIVATE_SOURCE_ROOT_CHANGED")
            try:
                lock = os.open("source.lock", os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0),
                               0o600, dir_fd=root)
            except FileNotFoundError:
                if create: raise
                # An existing day's protocol cannot silently become a fresh
                # zero-budget day merely because its lock was removed.
                try: os.stat(day, dir_fd=root, follow_symlinks=False)
                except FileNotFoundError: pass
                else: _need(False, "PRIVATE_SOURCE_LOCK_MISSING")
                yield None
                return
            try:
                _private_file(os.fstat(lock)); fcntl.flock(lock, fcntl.LOCK_EX)
                _need(_identity(os.stat("source.lock", dir_fd=root, follow_symlinks=False)) == _identity(os.fstat(lock)),
                      "PRIVATE_SOURCE_LOCK_CHANGED")
                if create:
                    try: os.mkdir(day, 0o700, dir_fd=root)
                    except FileExistsError: pass
                try:
                    folder = os.open(day, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                except FileNotFoundError:
                    if create: raise
                    yield None
                    return
                try:
                    info = os.fstat(folder)
                    _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                          "PRIVATE_SOURCE_DAY_REQUIRED")
                    try: os.stat(".git", dir_fd=folder, follow_symlinks=False)
                    except FileNotFoundError: pass
                    else: _need(False, "PRIVATE_SOURCE_OUTSIDE_GIT_REQUIRED")
                    yield folder
                    _need(_identity(os.stat(self.root, follow_symlinks=False)) == self.root_identity,
                          "PRIVATE_SOURCE_ROOT_CHANGED")
                finally: os.close(folder)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN); os.close(lock)

    def _state(self, folder, day):
        try:
            state = _json(_read(folder, "state.json", 16 * 1024 * 1024))
        except FileNotFoundError:
            _need(not os.listdir(folder), "PRIVATE_SOURCE_STATE_MISSING")
            state = dict(schema=STATE_SCHEMA, day=day, request_count=0, halted_reason=None,
                         captures=[], p0_capture=None, p1_ready={}, p1_attempted_at={})
        _need(type(state) is dict and state.get("schema") == STATE_SCHEMA and state.get("day") == day
              and type(state.get("request_count")) is int and state["request_count"] >= 0
              and type(state.get("captures")) is list and len(state["captures"]) <= state["request_count"]
              and type(state.get("p1_ready")) is dict and type(state.get("p1_attempted_at")) is dict,
              "PRIVATE_SOURCE_STATE_REJECTED")
        state.setdefault('capture_history',[])
        state.setdefault('first_B_capture',state.get('p0_capture'))
        state.setdefault('discovery_capture',state.get('p0_capture'))
        state.setdefault('race_registry',{})
        state.setdefault('schedule_registry',{})
        state.setdefault('discovery_revision',None)
        state.setdefault('next_discovery_at',None)
        state.setdefault('publication_waits',{})
        state.setdefault('final_publication_attempts',[])
        state.setdefault('next_deadline_at',None)
        state.setdefault('discovery_conflicts',{})
        return state

    def _save(self, folder, state):
        while len(state['captures'])>100:
            page=state['captures'][:100];body=_wire(page);name='capture-history-'+uuid.uuid4().hex+'.json'
            _write(folder,name,body)
            state['capture_history'].append(dict(file=name,sha256=hashlib.sha256(body).hexdigest(),count=len(page)))
            del state['captures'][:100]
        _replace_json(folder,'state.json',state)

    def _waits(self):
        with _parent_handle(self.root) as root:
            try:value=_json(_read(root,'source-waits.json',1024*1024))
            except FileNotFoundError:return {}
        _need(type(value) is dict and value.get('schema')=='RACE_AI_SOURCE_WAITS_V1'
              and type(value.get('origins')) is dict,'PRIVATE_SOURCE_WAIT_REJECTED')
        return value['origins']

    def _set_wait(self,url,wait):
        origin='https://'+urlsplit(url).netloc
        waits=self._waits()
        if wait is None:
            if origin not in waits:return
            del waits[origin]
        else:waits[origin]=wait
        with _parent_handle(self.root) as root:
            _replace_json(root,'source-waits.json',dict(schema='RACE_AI_SOURCE_WAITS_V1',origins=waits))

    def _active_wait(self,url=None):
        waits=self._waits()
        if url is not None:waits={key:value for key,value in waits.items() if key=='https://'+urlsplit(url).netloc}
        active=[value for value in waits.values() if wait_active(value,self.clock())]
        return min(active,key=lambda value:value.get('retry_at') or '') if active else None

    def _cached(self, folder, meta):
        _need(type(meta) is dict, "PRIVATE_SOURCE_METADATA_REJECTED")
        metadata = _read(folder, meta["metadata_file"], 32768)
        _need(hashlib.sha256(metadata).hexdigest() == meta["metadata_sha256"], "PRIVATE_SOURCE_METADATA_CHANGED")
        saved = _json(metadata)
        _need(saved == {k:v for k,v in meta.items() if k not in ("metadata_file", "metadata_sha256")},
              "PRIVATE_SOURCE_METADATA_CHANGED")
        raw = _read(folder, meta["raw_file"], MAX_ARCHIVE_BYTES)
        _need(hashlib.sha256(raw).hexdigest() == meta["source_sha256"] and len(raw) == meta["bytes"],
              "PRIVATE_SOURCE_CHANGED")
        _need(_moment(meta["captured_at"]) <= _moment(self.clock()), "SOURCE_CAPTURE_IN_FUTURE")
        return raw

    def _fetch(self, folder, state, url, kind, calls, *, automatic_stop_at=None,automatic_guard=None):
        # The server owns this boundary. Check before charging or opening each
        # source; a request already in flight may finish and retain its bytes.
        _guard(automatic_guard)
        wait=self._active_wait(url)
        if wait:_raise_wait(wait)
        _need(automatic_stop_at is None or _moment(self.clock()) < automatic_stop_at,
              "AUTOMATIC_SESSION_END")
        _need(not state["halted_reason"], "SOURCE_SESSION_HALTED")
        _need((REQUEST_LIMIT is None or state["request_count"] < REQUEST_LIMIT) and
              (CALL_REQUEST_LIMIT is None or calls[0] < CALL_REQUEST_LIMIT),
              "SOURCE_GET_BUDGET_EXHAUSTED")
        state["request_count"] += 1; calls[0] += 1
        state['last_source_url']=url
        self._save(folder, state)  # Charge before the network, including failed requests.
        bound = MAX_ARCHIVE_BYTES if kind == "B" else 2_000_000
        try:
            req = request.Request(url, headers={"Accept":"application/octet-stream" if kind == "B" else "text/html",
                "User-Agent":"RACE-AI-owner-personal-forecast-generation/1", "Cache-Control":"no-store"})
            with self.opener(req, timeout=25) as response:
                raw = response.read(bound + 1)
                _need(response.status == 200 and response.geturl() == url and type(raw) is bytes and
                      0 < len(raw) <= bound, "OFFICIAL_SOURCE_RESPONSE_REJECTED")
                content_type = (response.headers.get("Content-Type") or "").lower()
                _need(not content_type.startswith("text/html") if kind == "B" else content_type.startswith("text/html"),
                      "OFFICIAL_SOURCE_CONTENT_TYPE_REJECTED")
            stamp = _moment(self.clock()).isoformat()
            name = f"source-{state['request_count']:06d}"
            suffix = ".lzh" if kind == "B" else ".html"
            _write(folder, name + suffix, raw)
            meta = dict(url=url, captured_at=stamp, kind=kind, raw_file=name+suffix,
                        source_sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), content_type=content_type)
            metadata = _wire(meta); _write(folder, name + ".json", metadata)
            meta.update(metadata_file=name+".json", metadata_sha256=hashlib.sha256(metadata).hexdigest())
            if kind=='B' and state.get('first_B_capture') is None:state['first_B_capture']=meta
            state["captures"].append(meta); self._save(folder, state)
            self._set_wait(url,None)
            # Retain an already-started response even if its completion crosses
            # a policy boundary. It cannot authorize another GET or inference.
            _guard(automatic_guard)
            _need(automatic_stop_at is None or _moment(self.clock()) < automatic_stop_at,
                  "AUTOMATIC_SESSION_END")
            _need(_moment(stamp).astimezone(JST).date().isoformat() == state["day"], "SOURCE_DAY_BOUNDARY_PASSED")
            return raw, meta
        except error.HTTPError as exc:
            previous=self._waits().get('https://'+urlsplit(url).netloc,{})
            wait=plan_http_wait(exc.code,exc.headers or {},self.clock(),attempt=previous.get('attempts',0)+1,
                                not_yet_published=kind in ('B','beforeinfo'))
            if wait['state']=='WAITING_PUBLICATION' and kind!='B':
                headers=exc.headers or {}
                wait['server_retry_after']=bool(headers.get('Retry-After') or headers.get('retry-after'))
                rid=state.get('active_p1_race')
                if rid:state['publication_waits'][rid]=wait;self._save(folder,state)
            else:self._set_wait(url,wait)
            _raise_wait(wait)
        except (OSError, TimeoutError):
            previous=self._waits().get('https://'+urlsplit(url).netloc,{})
            wait=plan_http_wait(None,{},self.clock(),attempt=previous.get('attempts',0)+1)
            self._set_wait(url,wait);_raise_wait(wait)

    def status(self,day_jst=None):
        """Read current-day counters without collection, inference, or writes.

        Missing or corrupt state beside retained source files is an error,
        never permission to reset the budget. A day never started reports zero
        without creating a day directory or a new state/lock file.
        """
        today=_moment(self.clock()).astimezone(JST).date()
        day=today.isoformat() if day_jst is None else day_jst
        _need(type(day) is str and date.fromisoformat(day).isoformat()==day and date.fromisoformat(day)<=today,
              'SOURCE_STATUS_DAY_REJECTED')
        try:
            with self._locked_day(day, create=False) as folder:
                state = self._state(folder, day) if folder is not None else None
                wait=self._active_wait()
                if state and state['halted_reason']:
                    wait=dict(state='SOURCE_REVIEW_WAIT',reason='LEGACY_SOURCE_REVIEW_REQUIRED',retry_at=None,http_status=None,attempts=0)
                return dict(day_jst=day,requests_used=state['request_count'] if state else 0,
                    halted_reason=state['halted_reason'] if state else None,source_wait=wait,
                    waiting_state=wait['state'] if wait else None,waiting_reason=wait['reason'] if wait else None,
                    retry_at=wait.get('retry_at') if wait else None,next_discovery_at=state.get('next_discovery_at') if state else None,
                    discovery_revision=state.get('discovery_revision') if state else None,
                    next_deadline_at=state.get('next_deadline_at') if state else None,
                    target_window_seconds=[900,600])
        except (OSError, ValueError) as exc:
            if isinstance(exc, CurrentBoatInputError): raise
            raise CurrentBoatInputError("PRIVATE_CURRENT_SOURCE_STATUS_REJECTED") from None

    def collect(self, stage="P0", *, sport="boat", due_only=False, automatic_stop_at=None,
                refresh_discovery=False,preferred_window=False,automatic_guard=None):
        _need(sport == "boat", "CURRENT_SPORT_INPUT_UNCONNECTED")
        _need(stage in ("P0", "P1"), "SUPPORTED_FORECAST_STAGE_REQUIRED")
        _need(type(due_only) is bool, "BOOLEAN_DUE_SELECTION_REQUIRED")
        _need(type(refresh_discovery) is bool and type(preferred_window) is bool,'BOOLEAN_DISCOVERY_POLICY_REQUIRED')
        _guard(automatic_guard)
        now = _moment(self.clock()); day = now.astimezone(JST).date()
        stop = _moment(automatic_stop_at) if automatic_stop_at is not None else None
        if stop is not None:
            start_of_day = datetime.combine(day, datetime.min.time(), tzinfo=JST)
            _need(start_of_day <= stop <= start_of_day + timedelta(days=1),
                  "AUTOMATIC_SESSION_DAY_REJECTED")
            _need(now < stop, "AUTOMATIC_SESSION_END")
        calls = [0]
        try:
            with self._locked_day(day.isoformat()) as folder:
                state = self._state(folder, day.isoformat())
                if state['halted_reason']:
                    wait=dict(state='SOURCE_REVIEW_WAIT',reason='LEGACY_SOURCE_REVIEW_REQUIRED',retry_at=None,http_status=None,attempts=0)
                    self._set_wait(official_url(day,'B'),wait);_raise_wait(wait)
                try:
                    # A crash after the durable raw receipt but before parsing
                    # must not spend another GET or discard the first original.
                    recovered = state["p0_capture"] is None
                    if recovered:
                        saved = [entry for entry in state["captures"] if entry.get("kind") == "B"
                                 and entry.get("url") == official_url(day, "B")]
                        if state.get('first_B_capture'):state['p0_capture']=state['first_B_capture']
                        elif saved: state["p0_capture"] = saved[0]
                    cached = state["p0_capture"] is not None
                    refresh=refresh_discovery and (not state.get('next_discovery_at') or
                        _moment(self.clock())>=_moment(state['next_discovery_at']))
                    if cached and not refresh:
                        meta = state.get('discovery_capture') or state['p0_capture']; raw = self._cached(folder, meta)
                    else:
                        raw, meta = self._fetch(folder, state, official_url(day, "B"), "B", calls,
                                                automatic_stop_at=stop,automatic_guard=automatic_guard)
                    _need(meta["url"] == official_url(day, "B"), "OFFICIAL_B_SOURCE_IDENTITY_REJECTED")
                    inspect_lzh(raw)
                    text = extract_daily_lzh(raw, f"B{day:%y%m%d}.TXT")
                    program = normalize_races(text, day=day, source_url=meta["url"],
                        observed_at=meta["captured_at"], archive_sha256=meta["source_sha256"])
                    if not cached or recovered:
                        state["p0_capture"] = meta; self._save(folder, state)
                    program=self._register_program(program,meta,state,folder)
                    _need(stop is None or _moment(self.clock()) < stop, "AUTOMATIC_SESSION_END")
                    result = self._build(program, meta, stage, folder, state, calls,
                        due_only=due_only,automatic_stop_at=stop,automatic_guard=automatic_guard,preferred_window=preferred_window)
                    self._save(folder,state)
                    result["source_report"] = dict(state="INPUTS_READY" if result["inputs"] else "NO_QUALIFIED_INPUT",
                        day_jst=day.isoformat(), stage=stage, scheduled_races=len(result["schedule"]),
                        ready_races=len(result["inputs"]), source_requests=calls[0], request_count=state["request_count"],
                        request_limit=REQUEST_LIMIT, cache_used=cached, independent_source_verified=False,
                        raw_sources_saved=True,inference_performed=False,due_only=due_only,
                        discovery_revision=state['discovery_revision'],next_discovery_at=state['next_discovery_at'],
                        preferred_window=preferred_window,more_due=False)
                    result['source_report']['conflicted_races']=len(state['discovery_conflicts'])
                    return result
                except (ValueError, KeyError, TypeError, OverflowError, UnicodeError) as exc:
                    if isinstance(exc,SourceWait):raise
                    if str(exc)=='SOURCE_DAY_BOUNDARY_PASSED':
                        _raise_wait(dict(state='DAY_ROLLOVER_WAIT',reason='CURRENT_DAY_CHANGED',retry_at=_moment(self.clock()).isoformat()))
                    transient = isinstance(exc, CurrentBoatInputError) and str(exc) in (
                        "SOURCE_TRANSPORT_UNAVAILABLE", "SOURCE_HTTP_TEMPORARILY_UNAVAILABLE",
                        "AUTOMATIC_SESSION_END")
                    if not state["halted_reason"] and not transient:
                        state["halted_reason"] = "SOURCE_IDENTITY_OR_PARSE_STOP"; self._save(folder, state)
                    if not transient:
                        wait=dict(state='SOURCE_REVIEW_WAIT',reason=str(exc) if isinstance(exc,CurrentBoatInputError) else 'SOURCE_IDENTITY_OR_PARSE_STOP',retry_at=None,http_status=None,attempts=0)
                        self._set_wait(state.get('last_source_url',official_url(day,'B')),wait);_raise_wait(wait)
                    if isinstance(exc, CurrentBoatInputError): raise
                    raise CurrentBoatInputError("OFFICIAL_SOURCE_PARSE_REJECTED") from None
        except (OSError, ValueError) as exc:
            if isinstance(exc, CurrentBoatInputError): raise
            raise CurrentBoatInputError("PRIVATE_CURRENT_SOURCE_REJECTED") from None

    def _register_program(self,program,meta,state,folder):
        checked=set()
        for entry in state['race_registry'].values():
            binding=hashlib.sha256(_wire(dict(row=entry['row'],source=entry['source']))).hexdigest()
            _need(entry.get('row_source_sha256')==binding,'SAVED_PROGRAM_BINDING_CHANGED')
            ident=entry['source']['metadata_sha256']
            if ident not in checked:self._cached(folder,entry['source']);checked.add(ident)
        state['discovery_capture']=meta
        state['next_discovery_at']=(_moment(meta['captured_at'])+timedelta(seconds=DISCOVERY_SECONDS)).isoformat()
        valid={row['race_id']:row for venue in program['venues'] for row in venue['races']}
        for row in program['all_schedule']:
            state['schedule_registry'].setdefault(row['race_id'],dict(row))
        for rid,row in valid.items():
            if rid not in state['race_registry']:
                state['race_registry'][rid]=dict(row=row,source=meta,
                    row_source_sha256=hashlib.sha256(_wire(dict(row=row,source=meta))).hexdigest())
                state['schedule_registry'][rid]=dict(race_id=rid,cutoff_at=row['closed_at'])
            else:
                original=state['race_registry'][rid]['row']
                roster=lambda item:{b['lane']:b['racer_registration_id'] for b in item['boats']}
                if _moment(original['closed_at'])!=_moment(row['closed_at']) or roster(original)!=roster(row):
                    state['discovery_conflicts'][rid]=dict(reason='SAVED_PROGRAM_REVISION_CONFLICT',observed_cutoff_at=row['closed_at'],source_sha256=meta['source_sha256'])
                else:state['discovery_conflicts'].pop(rid,None)
        registry=state['race_registry']
        signature={rid:dict(cutoff=row['cutoff_at'],source=registry[rid]['source']['source_sha256'] if rid in registry else None)
                   for rid,row in sorted(state['schedule_registry'].items())}
        state['discovery_revision']=hashlib.sha256(_wire(dict(schedule=signature,conflicts=state['discovery_conflicts']))).hexdigest()
        return dict(program,all_schedule=sorted(state['schedule_registry'].values(),key=lambda row:(row['cutoff_at'],row['race_id'])),
            venues=[dict(venue='registry',races=[entry['row'] for entry in registry.values()])],
            sources_by_race={rid:entry['source'] for rid,entry in registry.items()},
            blocked_races=[row for row in program['blocked_races'] if row['race_id'] not in registry])

    def _build(self, program, meta, stage, folder, state, calls, *, due_only=False, automatic_stop_at=None,
               automatic_guard=None,preferred_window=False):
        rights = "OWNER_PERSONAL_FORECAST_GENERATION_CURRENT_" + program["date_jst"].replace("-", "")
        source = dict(source_id="official-B-"+program["date_jst"].replace("-", ""), source_url=meta["url"],
            source_sha256=meta["source_sha256"], source_rights_ref=rights, published_at=None,
            captured_at=meta["captured_at"], evidence_basis="CAPTURED_BY_CLAIM")
        schedule = [dict(row, sport="boat", stage=stage) for row in program["all_schedule"]]
        valid = {row["race_id"]:row for venue in program["venues"] for row in venue["races"]}
        for row in schedule:
            row["venue"] = "boatrace-jcd-" + row["race_id"][9:11]
            row["race_no"] = int(row["race_id"][-2:])
            if row["race_id"] in valid:
                row["participants"] = [dict(number=b["lane"], registration_no=b["racer_registration_id"],
                    name=b.get("name")) for b in valid[row["race_id"]]["boats"]]
        blocked = [dict(row, reason="B_LAYOUT_REJECTED") for row in program["blocked_races"]]
        inputs = {}; references = {(meta["url"], rights)}
        candidates = []
        for row in schedule:
            _guard(automatic_guard)
            rid = row["race_id"]
            if rid not in valid: continue
            if rid in state['discovery_conflicts']:
                blocked.append(dict(race_id=rid,reason='SAVED_PROGRAM_REVISION_CONFLICT'));continue
            now = _moment(self.clock())
            _need(now.astimezone(JST).date().isoformat() == program["date_jst"], "SOURCE_DAY_BOUNDARY_PASSED")
            if now + BUFFER >= _moment(row["cutoff_at"]):
                blocked.append(dict(race_id=rid, reason="CUTOFF_BUFFER")); continue
            if stage == "P0":
                original=program.get('sources_by_race',{}).get(rid,meta)
                per_source=dict(source,source_sha256=original['source_sha256'],captured_at=original['captured_at'])
                snap = build_program_snapshot(valid[rid], per_source, event_date_jst=program["date_jst"],
                    as_of=now.isoformat(), race_revision=1)
                inputs[rid] = {stage:{"boat_observed":{"snapshot":snap}}}
            else: candidates.append(row)
        if stage == "P1":
            if preferred_window:
                early=[row for row in candidates if (_moment(row['cutoff_at'])-_moment(self.clock())).total_seconds()>900]
                blocked.extend(dict(race_id=row['race_id'],reason='NOT_IN_CAPTURE_WINDOW') for row in early)
                candidates=[row for row in candidates if row not in early]
            ready = [row for row in candidates if row["race_id"] in state["p1_ready"]]
            pending = []
            for row in candidates:
                rid = row["race_id"]
                if rid in state["p1_ready"]: continue
                final=_final_publication_allowed(state,rid,row['cutoff_at'],_moment(self.clock()),preferred_window)
                publication=state['publication_waits'].get(rid)
                if publication and wait_active(publication,self.clock()) and not final:
                    blocked.append(dict(race_id=rid,reason='SOURCE_PUBLICATION_WAIT'));continue
                last = state["p1_attempted_at"].get(rid)
                if last and _moment(self.clock()) - _moment(last) < timedelta(seconds=180) and not final:
                    blocked.append(dict(race_id=rid, reason="P1_SOURCE_REFRESH_COOLDOWN"))
                else: pending.append(row)
            if due_only or preferred_window:
                # Existing selection authenticates schedule identity/clock
                # claims and uses its unchanged 22-minute capture window.
                # Ready originals and cooling-down observations do not consume
                # that selector's capacity or starve later due races.
                evidence = [dict(race_id=row["race_id"], cutoff_at=row["cutoff_at"],
                    schedule_captured_at=program.get('sources_by_race',{}).get(row['race_id'],meta)["captured_at"],
                    source_sha256=program.get('sources_by_race',{}).get(row['race_id'],meta)["source_sha256"])
                    for row in pending]
                queue = select_due_races(evidence, _moment(self.clock()).isoformat(), max_items=None)
                selected = {row['race_id']:row for row in pending}
                blocked.extend(dict(race_id=row["race_id"], reason=row["reason"])
                    for row in queue["deferred"] + queue["rejected"])
                pending = [selected[row['race_id']] for row in queue['eligible']]
            limit=None if preferred_window else P1_RACE_LIMIT
            for row in ready + pending[:limit]:
                _guard(automatic_guard)
                groups, extra_refs, reason = self._p1(row, program, folder, state, calls, rights,
                    automatic_stop_at=automatic_stop_at,automatic_guard=automatic_guard,preferred_window=preferred_window)
                references.update(extra_refs)
                if groups: inputs[row["race_id"]] = {stage:groups}
                else: blocked.append(dict(race_id=row["race_id"], reason=reason))
            if limit is not None:
                blocked.extend(dict(race_id=row['race_id'],reason='P1_BOUNDED_CALL_NOT_SELECTED') for row in pending[limit:])
        hints=[]
        for row in schedule:
            cutoff=_moment(row['cutoff_at']);now=_moment(self.clock())
            if cutoff-now<=BUFFER:continue
            for point in (cutoff-timedelta(seconds=900),cutoff-timedelta(seconds=600)):
                if point>now:hints.append(point)
        hints.extend(_moment(wait['retry_at']) for wait in state['publication_waits'].values()
                     if wait.get('retry_at') and _moment(wait['retry_at'])>_moment(self.clock()))
        state['next_deadline_at']=min(hints).isoformat() if hints else None
        return dict(schedule=schedule, inputs=inputs, blocked_races=blocked,
                    source_references=[dict(source_ref=url, source_rights_ref=ref) for url,ref in sorted(references)])

    def _p1(self, row, program, folder, state, calls, rights, *, automatic_stop_at=None,
            automatic_guard=None,preferred_window=False):
        from .official_racelist_adapter import endpoint, parse_official_racelist
        from .official_race_updates import endpoint as preview_endpoint, parse_update
        from scripts.boat_ab_future_pilot import motor_top2
        from .boat_observed_pairwise_models import FEATURE_TRANSFORMS
        from .observed_p1_connection import locator
        rid = row["race_id"]; day = _moment(row["cutoff_at"]).astimezone(JST).date()
        _guard(automatic_guard)
        venue, number = rid[9:11], int(rid[-2:]); now = _moment(self.clock())
        if now + BUFFER >= _moment(row["cutoff_at"]):
            return None, set(), "CUTOFF_BUFFER"
        purl = endpoint(day, venue, number); eurl = preview_endpoint(day, venue, number, "beforeinfo")
        ready = state["p1_ready"].get(rid)
        if ready:
            pm, em = ready; praw = self._cached(folder, pm)
        else:
            last = state["p1_attempted_at"].get(rid)
            final=_final_publication_allowed(state,rid,row['cutoff_at'],now,preferred_window)
            if last and now - _moment(last) < timedelta(seconds=180) and not final:
                return None, set(), "P1_SOURCE_REFRESH_COOLDOWN"
            state["p1_attempted_at"][rid] = now.isoformat(); self._save(folder, state)
            state['active_p1_race']=rid
            before=state['request_count']
            try:praw, pm = self._fetch(folder,state,purl,'racelist',calls,
                automatic_stop_at=automatic_stop_at,automatic_guard=automatic_guard)
            finally:
                if final and state['request_count']>before:
                    state['final_publication_attempts'].append(rid);self._save(folder,state)
        _need(pm["url"] == purl, "OFFICIAL_P1_SOURCE_IDENTITY_REJECTED")
        card = parse_official_racelist(praw, day=day, venue=venue, race_no=number,
            source_url=purl, captured_at=pm["captured_at"])
        if card["race_id"] != rid or _moment(card["closed_at"]) != _moment(row["cutoff_at"]):
            return None, set(), "P1_PROGRAM_SCHEDULE_CONFLICT"
        if any(b["entry_status"] != "listed" for b in card["boats"]):
            return None, set(), "P1_ENTRY_WITHDRAWN"
        if _moment(self.clock()) + BUFFER >= _moment(row["cutoff_at"]):
            return None, set(), "CUTOFF_BUFFER"
        if ready: eraw = self._cached(folder, em)
        else:
            try:eraw, em = self._fetch(folder,state,eurl,'beforeinfo',calls,
                automatic_stop_at=automatic_stop_at,automatic_guard=automatic_guard)
            except SourceWait as wait:
                if wait.state=='WAITING_PUBLICATION':return None,set(),wait.reason
                raise
        _need(em["url"] == eurl, "OFFICIAL_P1_SOURCE_IDENTITY_REJECTED")
        preview = parse_update(eraw, kind="beforeinfo", day=day, venue=venue, race_no=number,
            source_url=eurl, captured_at=em["captured_at"], entries=card["boats"])
        if preview["status"] != "AVAILABLE" or preview.get("data") is None:
            wait=plan_http_wait(200,{},self.clock(),not_yet_published=True)
            final_at=_moment(row['cutoff_at'])-timedelta(seconds=600)
            if preferred_window and final_at>_moment(self.clock()):
                wait['retry_at']=min(_moment(wait['retry_at']),final_at).isoformat()
            state['publication_waits'][rid]=wait;self._save(folder,state)
            return None, set(), "EXHIBITION_NOT_FULLY_PUBLISHED"
        _need(preview.get("body_identity_verified") is True, "P1_BODY_IDENTITY_UNVERIFIED")
        boats = sorted(preview["data"]["boats"], key=lambda x:x["lane"])
        if len(boats) != 6 or any(b["display_time"] is None for b in boats):
            return None, set(), "EXHIBITION_TIME_INCOMPLETE"
        _need(_moment(pm["captured_at"]) <= _moment(em["captured_at"]), "P1_CAPTURE_ORDER_REJECTED")
        known = {b["lane"]:b for b in card["boats"]}; motors = motor_top2(praw, card["boats"])
        _need(set(known) == set(range(1,7)) and len(boats) == len({b["lane"] for b in boats}) and
              all(known[b["lane"]]["racer_registration_id"] == b["racer_registration_id"] for b in boats),
              "P1_ROSTER_IDENTITY_REJECTED")
        base = dict(race_id=rid, cutoff_at=row["cutoff_at"], captured_at=em["captured_at"],
            program_source_sha256=pm["source_sha256"], beforeinfo_source_sha256=em["source_sha256"],
            boats=[dict(lane=b["lane"], racer_id=b["racer_registration_id"],
                national_win_rate=known[b["lane"]]["national_win_rate"],
                exhibition_time_seconds=b["display_time"], motor_two_place_rate_percent=motors[b["lane"]]) for b in boats])
        extra = dict(race_id=rid, observed_at=em["captured_at"],
            source_sha256=hashlib.sha256((pm["source_sha256"]+em["source_sha256"]).encode()).hexdigest(),
            participants=[dict(lane=b["lane"], racer_id=b["racer_registration_id"],
                local_win_rate=known[b["lane"]]["local_win_rate"], average_st=known[b["lane"]]["average_st"],
                exhibition_st=b["preview_st"], exhibition_st_status=b["preview_st_status"]) for b in boats])
        sources = [dict(source_id=kind+"-"+rid, source_url=locator(url, kind, rid), source_sha256=meta["source_sha256"],
            source_rights_ref=rights, published_at=None, captured_at=meta["captured_at"], evidence_basis="CAPTURED_BY_CLAIM")
            for kind,url,meta in (("racelist",purl,pm),("beforeinfo",eurl,em))]
        participants = []
        for b, item in zip(base["boats"], extra["participants"]):
            values = dict(national_win_rate=b["national_win_rate"], motor_top2_rate=b["motor_two_place_rate_percent"],
                exhibition_time_seconds=b["exhibition_time_seconds"])
            missing = {k:"NO_PRIOR_SAMPLES" for k in ("recent_mean_finish", "course_mean_finish", "recent_mean_st", "course_mean_st")}
            if item["exhibition_st_status"] == "OK": values["exhibition_start_seconds"] = item["exhibition_st"]
            else: missing["exhibition_start_seconds"] = item["exhibition_st_status"] if item["exhibition_st_status"] in ("F","L") else "NOT_YET_PUBLISHED"
            features = {}
            for name,value in values.items():
                if value is None: missing[name] = "MISSING"; continue
                source = sources[1] if name.startswith("exhibition_") else sources[0]
                features[name] = dict(value=value, sample_n=None, source_id=source["source_id"], transform_id=FEATURE_TRANSFORMS[name])
            participants.append(dict(lane=b["lane"], registration_no=b["racer_id"], features=features, missing=missing))
        now = _moment(self.clock())
        _guard(automatic_guard)
        if now + BUFFER >= _moment(row["cutoff_at"]): return None, set(), "CUTOFF_BUFFER"
        snapshot = dict(schema="RACE_AI_BOAT_OBSERVED_PAIRWISE_V1", scope="OPERATOR_SUPPLIED_RESEARCH",
            race_id=f"boat:{day.isoformat()}:boatrace-jcd-{venue}:{number}", event_date_jst=day.isoformat(),
            venue="boatrace-jcd-"+venue, race_revision=1, sales_cutoff_at=row["cutoff_at"], as_of=now.isoformat(),
            stage="P1", race_source_id=sources[0]["source_id"], sources=sources, participants=participants)
        evidence = [dict(source_ref=url, source_rights_ref=rights, source_sha256=meta["source_sha256"])
                    for url,meta in ((purl,pm),(eurl,em))]
        evidence.append(dict(source_ref=purl, source_rights_ref=rights, source_sha256=extra["source_sha256"]))
        groups = dict(boat_ab=dict(source=base, source_evidence=evidence),
            boat_clite=dict(base_source=base, extra=extra, source_evidence=evidence),
            boat_observed=dict(snapshot=snapshot))
        state["p1_ready"][rid] = [pm,em]; self._save(folder, state)
        state['publication_waits'].pop(rid,None)
        return groups, {(s["source_url"],rights) for s in sources} | {(purl,rights),(eurl,rights)}, None
