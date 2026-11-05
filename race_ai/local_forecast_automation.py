"""App-owned continuous rounds using the existing writer's polling policy.

Local operation completion is not a GitHub artifact receipt. This controller
creates no workflow, cron, model family, external freeze or automatic promotion.
Its single worker exists only for the lifetime of the existing local app.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import uuid

from .private_cycle_capture import _parent_handle
from .repeated_cycle import JST, POLL_SECONDS, MAX_ROUNDS, MAX_SECONDS, SOURCE_LIMIT
from .source_retry_policy import SourceWait, plan_http_wait, wait_active

SCHEMA = "RACE_AI_LOCAL_FORECAST_AUTOMATION_V2"
LEGACY_SCHEMA = "RACE_AI_LOCAL_FORECAST_AUTOMATION_V1"
_NORMAL_ENDS = frozenset(("BOUNDED_SESSION_END", "MAX_ROUNDS_REACHED", "DAY_CHANGED", "DAY_HANDOFF",
                         "SOURCE_BUDGET_EXHAUSTED", "SESSION_SOURCE_BUDGET_EXHAUSTED"))
_HASH = "local_session_sha256"
_TRANSIENT = frozenset(("SOURCE_TRANSPORT_UNAVAILABLE", "SOURCE_HTTP_TEMPORARILY_UNAVAILABLE"))
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_LOCK_MARKER = b"RACE_AI_CONTINUOUS_STATE_INITIALIZED_V2\n"
# Shutdown must let a charged/captured source and its local checkpoint finish.
# The provider checks the trusted STOPPING guard between its 25-second GETs.
# This is a shutdown wait ceiling, not permission to continue collecting.
# Unfinished shutdown is an explicit failure.
SHUTDOWN_GRACE_SECONDS = 240


def _moment(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("AWARE_AUTOMATIC_CLOCK_REQUIRED")
    return result


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def _private(info):
    if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
            info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600):
        raise ValueError("PRIVATE_AUTOMATIC_FILE_REQUIRED")


class ForecastAutomation:
    def __init__(self, service, clock=None):
        self.service = service
        self.root = Path(service.root)
        self.clock = clock or service.clock
        self._mutex = threading.Lock()
        self._tick_mutex = threading.Lock()
        self._start_mutex = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._lock_fd = None
        self._new_lock = False
        self._initialized = False
        self._root_identity = None
        self._day = None
        self._state = None
        self._durable_valid = True
        self._timing = {}
        self._snapshot = dict(enabled=True, continuous=True, state="NOT_STARTED", round_no=0,
            next_run_at=None, last_completed_at=None, halted_reason=None,
            interval_seconds=POLL_SECONDS, stop_at=None, p0_completed=False,
            requests_used=0, requests_total=0, source_wait=None,
            source_limit=SOURCE_LIMIT, max_rounds=MAX_ROUNDS, local_completion_only=True)

    def status(self):
        """Only cached scalars: safe while the service's own lock is held."""
        with self._mutex:
            return deepcopy(self._snapshot)

    def _publish(self):
        if self._state is None: return
        fields = ("state", "day_jst", "started_at", "round_no", "next_run_at",
            "last_started_at", "last_completed_at", "halted_reason", "stop_at",
            "p0_completed", "requests_used", "requests_total", "source_wait", "last_error_code", "last_summary")
        snapshot = {k: deepcopy(self._state.get(k)) for k in fields}
        snapshot.update(enabled=True, continuous=True, interval_seconds=POLL_SECONDS,
                        source_limit=SOURCE_LIMIT, max_rounds=MAX_ROUNDS, local_completion_only=True)
        waiting=snapshot["source_wait"] or {}
        snapshot.update(waiting_reason=waiting.get("reason"),waiting_state=waiting.get("state"),
                        retry_at=waiting.get("retry_at"),next_deadline_at=self._timing.get("next_deadline_at"))
        if self._stop_event.is_set() and snapshot["state"] in ("RUNNING", "WAITING", "SOURCE_WAIT"):
            snapshot["state"] = "STOPPING"
        with self._mutex: self._snapshot = snapshot

    def _root(self):
        return _parent_handle(self.root)

    def _check_root(self, fd):
        info = os.fstat(fd)
        identity = info.st_dev, info.st_ino
        if not (info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700 and
                (self._root_identity is None or identity == self._root_identity)):
            raise ValueError("PRIVATE_AUTOMATIC_ROOT_REQUIRED")
        self._root_identity = identity
        if self._lock_fd is not None:
            current = os.stat("automatic.lock", dir_fd=fd, follow_symlinks=False)
            held = os.fstat(self._lock_fd)
            _private(current); _private(held)
            if (current.st_dev,current.st_ino) != (held.st_dev,held.st_ino):
                raise ValueError("PRIVATE_AUTOMATIC_LOCK_CHANGED")

    def _name(self):
        return "automatic-continuous.json"

    def _write_document(self, name, value, *, first=False):
        unsigned = {k:v for k,v in value.items() if k != _HASH}
        document = dict(unsigned, **{_HASH: hashlib.sha256(_wire(unsigned)).hexdigest()})
        body = _wire(document) + b"\n"
        with self._root() as root:
            self._check_root(root)
            if not first:
                _private(os.stat(name, dir_fd=root, follow_symlinks=False))
            temporary = name if first else "automatic-tmp-" + uuid.uuid4().hex + ".json"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=root)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body); stream.flush(); os.fsync(stream.fileno())
            if not first: os.replace(temporary, name, src_dir_fd=root, dst_dir_fd=root)
            os.fsync(root)
    def _save(self, *, first=False):
        self._state["source_limit"] = SOURCE_LIMIT
        if first:self._mark_initialized()
        self._write_document(self._name(),self._state,first=first)
        self._publish()

    def _mark_initialized(self):
        if self._initialized:return
        with self._root() as root:self._check_root(root)
        if os.pwrite(self._lock_fd,_LOCK_MARKER,0)!=len(_LOCK_MARKER):
            raise ValueError("AUTOMATIC_LOCK_MARKER_WRITE")
        os.ftruncate(self._lock_fd,len(_LOCK_MARKER));os.fsync(self._lock_fd)
        self._initialized=True

    def _document(self, name):
        with self._root() as root:
            self._check_root(root)
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno()); _private(info)
                if not 0 < info.st_size <= 128*1024: raise ValueError("AUTOMATIC_STATE_SIZE")
                raw = stream.read(128*1024+1)
                if len(raw) != info.st_size: raise ValueError("AUTOMATIC_STATE_CHANGED")
        def pairs(items):
            value = {}
            for key,item in items:
                if key in value: raise ValueError("AUTOMATIC_DUPLICATE_FIELD")
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("AUTOMATIC_CONSTANT")))
        claimed = value.pop(_HASH)
        if claimed != hashlib.sha256(_wire(value)).hexdigest(): raise ValueError("AUTOMATIC_STATE_HASH")
        return value,hashlib.sha256(raw).hexdigest()

    def _read(self):
        value,_ = self._document(self._name())
        start = _moment(value["started_at"])
        if not (value["schema"] == SCHEMA and
                re.fullmatch(r"\d{4}-\d{2}-\d{2}",value["day_jst"]) and
                start.astimezone(JST).date().isoformat() <= value["day_jst"] and
                value["stop_at"] is None and value["max_rounds"] is None and
                type(value["round_no"]) is int and value["round_no"] >= 0 and
                type(value["p0_completed"]) is bool and type(value["round_in_progress"]) is bool and
                type(value["requests_used"]) is int and value["requests_used"] >= 0 and
                type(value["requests_total"]) is int and value["requests_total"] >= value["requests_used"] and
                value["interval_seconds"] == POLL_SECONDS and
                value["state"] in ("WAITING", "RUNNING", "PAUSED", "REVIEW_WAIT", "SOURCE_WAIT")):
            raise ValueError("AUTOMATIC_STATE_REJECTED")
        _moment(value["last_observed_at"]); _moment(value["next_run_at"])
        wait_active(value.get("source_wait"),_moment(value["last_observed_at"]))
        return value

    def _initial(self, now):
        day=now.astimezone(JST).date().isoformat()
        value=dict(schema=SCHEMA,day_jst=day,state="WAITING",started_at=now.isoformat(),stop_at=None,
            round_no=0,round_in_progress=False,p0_completed=False,next_run_at=now.isoformat(),
            last_started_at=None,last_completed_at=None,last_observed_at=now.isoformat(),
            requests_used=0,requests_total=0,halted_reason=None,source_wait=None,
            last_error_code=None,last_summary={},interval_seconds=POLL_SECONDS,max_rounds=None,
            legacy_predecessors=[])
        with self._root() as root:
            entries=os.listdir(root)
            if self._initialized or any(re.fullmatch(r"automatic-day-\d{4}-\d{2}-\d{2}\.json",name) for name in entries):
                raise ValueError("AUTOMATIC_CONTINUITY_CHECKPOINT_MISSING")
            names=sorted(name for name in entries if re.fullmatch(r"automatic-\d{4}-\d{2}-\d{2}\.json",name))
            if not names and not self._new_lock:
                raise ValueError("AUTOMATIC_CONTINUITY_CHECKPOINT_MISSING")
        for name in names:
            old,digest=self._document(name)
            oldday=name[10:-5]
            start=_moment(old["started_at"])
            midnight=start.astimezone(JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
            if not (old["schema"]==LEGACY_SCHEMA and old["day_jst"]==oldday and oldday<=day and
                    start.astimezone(JST).date().isoformat()==oldday and
                    _moment(old["stop_at"])==min(start+timedelta(minutes=65),midnight) and
                    old["max_rounds"]==24 and old["interval_seconds"]==POLL_SECONDS and
                    type(old["round_no"]) is int and 0<=old["round_no"]<=24 and
                    type(old["requests_used"]) is int and old["requests_used"]>=0 and
                    type(old["round_in_progress"]) is bool and type(old["p0_completed"]) is bool):
                raise ValueError("AUTOMATIC_LEGACY_STATE_REJECTED")
            _moment(old["last_observed_at"]);_moment(old["next_run_at"])
            value["last_observed_at"]=max(_moment(value["last_observed_at"]),_moment(old["last_observed_at"])).isoformat()
            value["legacy_predecessors"].append(dict(name=name,sha256=digest,
                halted_reason=old.get("halted_reason"),round_no=old["round_no"],requests_used=old["requests_used"]))
            value["started_at"]=min(_moment(value["started_at"]),start).isoformat()
            value["round_no"]+=old["round_no"]
            value["requests_total"]+=old["requests_used"]
            if oldday==day:
                value.update(requests_used=old["requests_used"],p0_completed=old["p0_completed"],
                    next_run_at=max(now,_moment(old["next_run_at"])).isoformat(),
                    last_started_at=old.get("last_started_at"),last_completed_at=old.get("last_completed_at"))
            reason="INTERRUPTED_ROUND_REQUIRES_REVIEW" if old["round_in_progress"] else old.get("halted_reason")
            if reason and reason not in _NORMAL_ENDS:
                value.update(state="REVIEW_WAIT",halted_reason=reason)
        return value

    def _release(self):
        if self._lock_fd is not None:
            fd, self._lock_fd = self._lock_fd, None
            try: fcntl.flock(fd, fcntl.LOCK_UN)
            finally: os.close(fd)

    def _ensure(self, now):
        if self._lock_fd is not None:
            with self._root() as root: self._check_root(root)
            return True
        with self._root() as root:
            self._check_root(root)
            try:
                fd = os.open("automatic.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=root)
                self._new_lock=True
            except FileExistsError:
                fd = os.open("automatic.lock",os.O_RDWR | os.O_NOFOLLOW,dir_fd=root)
                self._new_lock=False
            try:
                _private(os.fstat(fd))
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                with self._mutex:
                    self._snapshot.update(state="ALREADY_RUNNING",
                        halted_reason="ANOTHER_AUTOMATIC_WRITER_ACTIVE")
                return False
            except BaseException:
                os.close(fd); raise
            self._lock_fd = fd
            marker=os.pread(fd,128,0)
            if marker not in (b"",_LOCK_MARKER):raise ValueError("AUTOMATIC_LOCK_MARKER_REJECTED")
            self._initialized=marker==_LOCK_MARKER
        try:
            self._state = self._read()
        except FileNotFoundError:
            self._state = self._initial(now)
            self._save(first=True)
        self._mark_initialized()
        self._day = self._state["day_jst"]
        if self._state["round_in_progress"]:
            self._halt("INTERRUPTED_ROUND_REQUIRES_REVIEW", now)
        self._publish()
        return True

    def _halt(self, reason, now):
        self._state.update(state="REVIEW_WAIT", halted_reason=reason,
                           next_run_at=(now+timedelta(seconds=POLL_SECONDS)).isoformat(),
                           last_observed_at=max(now,_moment(self._state["last_observed_at"])).isoformat(),
                           round_in_progress=False)
        self._save()

    def _limits(self, now, *, after=False):
        if self._state["halted_reason"]:
            self._state.update(state="REVIEW_WAIT",next_run_at=(now+timedelta(seconds=POLL_SECONDS)).isoformat())
            self._publish();return False
        if now < _moment(self._state["last_observed_at"]) or now.astimezone(JST).date().isoformat()<self._day:
            self._halt("CLOCK_REVERSED", now); return False
        return True

    def _waiting(self, waiting, now):
        wait_active(waiting,now)
        self._state.update(source_wait=deepcopy(waiting),state="SOURCE_WAIT",
            next_run_at=waiting.get("retry_at") or (now+timedelta(seconds=POLL_SECONDS)).isoformat(),
            last_error_code=waiting["reason"],last_observed_at=now.isoformat())
        self._save()

    def _source(self, now, *, historical=False):
        try:
            value = (self.service.automatic_source_status(day_jst=self._day) if historical
                     else self.service.automatic_source_status())
            used = value["requests_used"]
            if (value["day_jst"] != self._day or type(used) is not int or
                    used < self._state["requests_used"]):
                raise ValueError("AUTOMATIC_SOURCE_STATUS_REJECTED")
            waiting=value.get("source_wait")
            wait_active(waiting,now)
        except Exception:
            self._halt("AUTOMATIC_SOURCE_STATUS_REJECTED", now); return False
        self._state["requests_total"]+=used-self._state["requests_used"]
        self._state["requests_used"] = used
        reason = value.get("halted_reason")
        if reason:
            self._halt(reason if type(reason) is str and _CODE.fullmatch(reason) else "SOURCE_HALTED",now)
            return False
        previous=self._state.get("source_wait")
        if waiting is None and wait_active(previous,now):waiting=previous
        self._state["source_wait"]=deepcopy(waiting)
        self._timing={k:value.get(k) for k in ("next_deadline_at","next_discovery_at")}
        if wait_active(waiting,now):
            if not historical:self._waiting(waiting,now)
            return historical
        return True

    def _next(self, now):
        started=_moment(self._state["last_started_at"]) if self._state.get("last_started_at") else now
        ready=max(now+timedelta(seconds=1),started+timedelta(seconds=POLL_SECONDS))
        for value in self._timing.values():
            if value is None:continue
            when=_moment(value)
            ready=min(ready,when if when>now else now+timedelta(seconds=60))
        waiting=self._state.get("source_wait")
        if wait_active(waiting,now):
            ready=max(ready,_moment(waiting["retry_at"])) if waiting.get("retry_at") else now+timedelta(seconds=POLL_SECONDS)
        return ready.isoformat()

    def _roll(self, now):
        day=now.astimezone(JST).date().isoformat()
        if day==self._day:return True
        if self._state["round_in_progress"]:raise ValueError("AUTOMATIC_ROLLOVER_IN_PROGRESS")
        if not self._source(now,historical=True):return False
        archive_name="automatic-day-"+self._day+".json"
        archive=deepcopy(self._state)
        try:
            previous,_=self._document(archive_name)
            if previous!=archive:raise ValueError("AUTOMATIC_DAY_ARCHIVE_CONFLICT")
        except FileNotFoundError:self._write_document(archive_name,archive,first=True)
        self._day=day
        self._state.update(day_jst=day,requests_used=0,p0_completed=False,state="WAITING",
                           next_run_at=now.isoformat(),last_observed_at=now.isoformat())
        self._timing={}
        self._save()
        return True

    @staticmethod
    def _summary(result):
        value = result["summary"]
        answer = {key:value[key] for key in ("generated", "reused", "missing")}
        if any(type(n) is not int or not 0 <= n <= 10_000_000 for n in answer.values()):
            raise ValueError("AUTOMATIC_SUMMARY_REJECTED")
        return answer

    def tick(self):
        with self._tick_mutex:
            if self._stop_event.is_set(): return self.status()
            try:
                now = _moment(self.clock())
                if not self._ensure(now): return self.status()
                if not self._limits(now): return self.status()
                if not self._roll(now): return self.status()
                if not self._source(now): return self.status()
                if now < _moment(self._state["next_run_at"]):
                    self._state["state"] = "WAITING"; self._publish(); return self.status()
                self._state.update(state="RUNNING", round_no=self._state["round_no"]+1,
                    round_in_progress=True, last_started_at=now.isoformat(),
                    last_observed_at=now.isoformat(), last_error_code=None, last_summary={},
                    next_run_at=(now+timedelta(seconds=POLL_SECONDS)).isoformat())
                self._save()
                # Discovery is TTL-controlled by the provider. Native journal
                # slots reuse originals, so a newly discovered race receives
                # its missing P0 without reissuing existing predictions.
                for stage in ("P0","P1"):
                    if self._stop_event.is_set(): break
                    before = _moment(self.clock())
                    if before.astimezone(JST).date().isoformat()!=self._day:break
                    if not self._limits(before) or not self._source(before): break
                    try:
                        value = self.service.generate_auto("boat", stage)
                        self._state["last_summary"][stage] = self._summary(value)
                        if stage == "P0": self._state["p0_completed"] = True
                        self._save()
                    except Exception as error:
                        at = _moment(self.clock())
                        if self._stop_event.is_set(): break
                        if at.astimezone(JST).date().isoformat()!=self._day:break
                        if not self._source(at): break
                        if not self._limits(at): break
                        if isinstance(error,SourceWait):
                            self._waiting(dict(reason=error.reason,retry_at=error.retry_at,state=error.state,
                                               http_status=None,attempts=1),at)
                            break
                        transient = isinstance(error, (OSError, TimeoutError)) or str(error) in _TRANSIENT
                        if transient:
                            previous=self._state.get("source_wait") or {}
                            self._waiting(plan_http_wait(None,{},at,attempt=previous.get("attempts",0)+1),at)
                        else:
                            self._halt("AUTOMATIC_GENERATION_REJECTED",at)
                        break
                    at = _moment(self.clock())
                    if at.astimezone(JST).date().isoformat()!=self._day:break
                    if not self._limits(at) or not self._source(at): break
                at = _moment(self.clock())
                self._state.update(round_in_progress=False, last_completed_at=at.isoformat(),
                                   last_observed_at=at.isoformat())
                if self._state["state"] not in ("REVIEW_WAIT","SOURCE_WAIT"):
                    self._state["state"] = "WAITING"
                if self._limits(at, after=True):
                    self._roll(at)
                    self._state["next_run_at"]=self._next(at)
                self._save()
            except Exception:
                # Never include source exception text, paths, inputs or picks.
                # Do not let shutdown write stale cached state over an invalid
                # durable record whose hash or directory identity just failed.
                self._durable_valid=False
                if self._state is not None:
                    self._state.update(state="REVIEW_WAIT", halted_reason="AUTOMATIC_STATE_UNAVAILABLE")
                with self._mutex:
                    self._snapshot.update(state="REVIEW_WAIT", halted_reason="AUTOMATIC_STATE_UNAVAILABLE",
                        next_run_at=(_moment(self.clock())+timedelta(seconds=POLL_SECONDS)).isoformat())
            finally:
                if self._stop_event.is_set(): self._pause()
                if not self._durable_valid:self._release()
            return self.status()

    def _pause(self):
        # The worker may already have checkpointed and released the profile.
        # An idempotent close must not overwrite a successor's durable state
        # using this instance's stale cached copy after releasing the lock.
        if self._lock_fd is None: return
        if self._durable_valid and self._state is not None and self._state["state"] != "REVIEW_WAIT":
            try:
                self._state.update(state="PAUSED", round_in_progress=False)
                self._save()
            except Exception:
                with self._mutex:
                    self._snapshot.update(state="REVIEW_WAIT", halted_reason="AUTOMATIC_STATE_UNAVAILABLE")
        self._release()

    def _run(self):
        try:
            while not self._stop_event.is_set():
                state = self.tick()
                if state["state"] == "ALREADY_RUNNING": break
                delay = max(0.05, (_moment(state["next_run_at"])-_moment(self.clock())).total_seconds())
                self._stop_event.wait(min(delay,30))
        finally:
            with self._tick_mutex: self._pause()

    def start(self):
        with self._start_mutex:
            if self._thread is not None and self._thread.is_alive(): return True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="race-ai-existing-automatic-rounds", daemon=True)
            self._thread.start()
            return True

    def stop(self):
        self._stop_event.set()
        thread = self._thread
        with self._mutex:
            if self._snapshot["state"] not in ("REVIEW_WAIT", "PAUSED", "NOT_STARTED", "ALREADY_RUNNING"):
                self._snapshot["state"] = "STOPPING"
        if thread is threading.current_thread():
            # A callback may request stop; the worker's finally owns its own
            # checkpoint. Waiting for itself here would deadlock.
            return
        if thread is not None:
            thread.join(timeout=SHUTDOWN_GRACE_SECONDS)
            if thread.is_alive():
                raise ValueError("AUTOMATIC_SHUTDOWN_INCOMPLETE")
        # Covers deterministic tick() and a source call made by a test/worker
        # without start(). Never release its profile lock while it is active.
        if not self._tick_mutex.acquire(timeout=SHUTDOWN_GRACE_SECONDS):
            raise ValueError("AUTOMATIC_SHUTDOWN_INCOMPLETE")
        try: self._pause()
        finally: self._tick_mutex.release()
