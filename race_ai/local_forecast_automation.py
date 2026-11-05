"""App-owned bounded rounds using the existing writer's policy constants.

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

SCHEMA = "RACE_AI_LOCAL_FORECAST_AUTOMATION_V1"
_HASH = "local_session_sha256"
_TRANSIENT = frozenset(("SOURCE_TRANSPORT_UNAVAILABLE", "SOURCE_HTTP_TEMPORARILY_UNAVAILABLE"))
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
# Shutdown must let a charged/captured source and its local checkpoint finish.
# The current provider admits one B plus at most three two-GET P1 races; each
# request uses a 25-second timeout. This is a shutdown wait ceiling, not extra
# source/round/session allowance. Unfinished shutdown is an explicit failure.
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
        self._root_identity = None
        self._day = None
        self._state = None
        self._snapshot = dict(enabled=True, state="NOT_STARTED", round_no=0,
            next_run_at=None, last_completed_at=None, halted_reason=None,
            interval_seconds=POLL_SECONDS, stop_at=None, p0_completed=False,
            requests_used=0, source_limit=SOURCE_LIMIT, max_rounds=MAX_ROUNDS, local_completion_only=True)

    def status(self):
        """Only cached scalars: safe while the service's own lock is held."""
        with self._mutex:
            return deepcopy(self._snapshot)

    def _publish(self):
        if self._state is None: return
        fields = ("state", "day_jst", "started_at", "round_no", "next_run_at",
            "last_started_at", "last_completed_at", "halted_reason", "stop_at",
            "p0_completed", "requests_used", "last_error_code", "last_summary")
        snapshot = {k: deepcopy(self._state.get(k)) for k in fields}
        snapshot.update(enabled=True, interval_seconds=POLL_SECONDS,
                        source_limit=SOURCE_LIMIT, max_rounds=MAX_ROUNDS, local_completion_only=True)
        if self._stop_event.is_set() and snapshot["state"] in ("RUNNING", "WAITING"):
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
        return "automatic-" + self._day + ".json"

    def _save(self, *, first=False):
        self._state["source_limit"] = SOURCE_LIMIT
        unsigned = {k:v for k,v in self._state.items() if k != _HASH}
        document = dict(unsigned, **{_HASH: hashlib.sha256(_wire(unsigned)).hexdigest()})
        body = _wire(document) + b"\n"
        with self._root() as root:
            self._check_root(root)
            name = self._name()
            if not first:
                _private(os.stat(name, dir_fd=root, follow_symlinks=False))
            temporary = name if first else "automatic-tmp-" + uuid.uuid4().hex + ".json"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=root)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body); stream.flush(); os.fsync(stream.fileno())
            if not first: os.replace(temporary, name, src_dir_fd=root, dst_dir_fd=root)
            os.fsync(root)
        self._publish()

    def _read(self):
        with self._root() as root:
            self._check_root(root)
            fd = os.open(self._name(), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root)
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
        start = _moment(value["started_at"])
        midnight = start.astimezone(JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        if not (value["schema"] == SCHEMA and value["day_jst"] == self._day and
                start.astimezone(JST).date().isoformat() == self._day and
                _moment(value["stop_at"]) == min(start+timedelta(seconds=MAX_SECONDS),midnight) and
                type(value["round_no"]) is int and 0 <= value["round_no"] <= MAX_ROUNDS and
                type(value["p0_completed"]) is bool and type(value["round_in_progress"]) is bool and
                type(value["requests_used"]) is int and value["requests_used"] >= 0 and
                value["interval_seconds"] == POLL_SECONDS and value["max_rounds"] == MAX_ROUNDS and
                value["state"] in ("WAITING", "RUNNING", "PAUSED", "STOPPED")):
            raise ValueError("AUTOMATIC_STATE_REJECTED")
        _moment(value["last_observed_at"]); _moment(value["next_run_at"])
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
            fd = os.open("automatic.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                         0o600, dir_fd=root)
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
        if self._day is None: self._day = now.astimezone(JST).date().isoformat()
        try:
            self._state = self._read()
        except FileNotFoundError:
            midnight = now.astimezone(JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
            self._state = dict(schema=SCHEMA, day_jst=self._day, state="WAITING",
                started_at=now.isoformat(), stop_at=min(now+timedelta(seconds=MAX_SECONDS),midnight).isoformat(),
                round_no=0, round_in_progress=False, p0_completed=False,
                next_run_at=now.isoformat(), last_started_at=None, last_completed_at=None,
                last_observed_at=now.isoformat(), requests_used=0, halted_reason=None,
                last_error_code=None, last_summary={}, interval_seconds=POLL_SECONDS, max_rounds=MAX_ROUNDS)
            self._save(first=True)
        if self._state["round_in_progress"]:
            self._halt("INTERRUPTED_ROUND_REQUIRES_REVIEW", now)
        self._publish()
        return True

    def _halt(self, reason, now):
        self._state.update(state="STOPPED", halted_reason=reason,
                           last_observed_at=now.isoformat(), round_in_progress=False)
        self._save()

    def _limits(self, now, *, after=False):
        reason = self._state["halted_reason"]
        if now.astimezone(JST).date().isoformat() != self._day: reason = reason or "DAY_CHANGED"
        if now < _moment(self._state["last_observed_at"]): reason = reason or "CLOCK_REVERSED"
        if now >= _moment(self._state["stop_at"]): reason = reason or "BOUNDED_SESSION_END"
        if self._state["round_no"] >= MAX_ROUNDS and (after or not self._state["round_in_progress"]):
            reason = reason or "MAX_ROUNDS_REACHED"
        if reason:
            self._halt(reason, now); return False
        return True

    def _source(self, now):
        try:
            value = self.service.automatic_source_status()
            used = value["requests_used"]
            if (value["day_jst"] != self._day or type(used) is not int or
                    used < self._state["requests_used"]):
                raise ValueError("AUTOMATIC_SOURCE_STATUS_REJECTED")
        except Exception:
            self._halt("AUTOMATIC_SOURCE_STATUS_REJECTED", now); return False
        self._state["requests_used"] = used
        reason = value.get("halted_reason")
        if reason:
            self._halt(reason if type(reason) is str and _CODE.fullmatch(reason) else "SOURCE_HALTED",now)
            return False
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
                if now < _moment(self._state["next_run_at"]):
                    self._state["state"] = "WAITING"; self._publish(); return self.status()
                if not self._source(now): return self.status()
                self._state.update(state="RUNNING", round_no=self._state["round_no"]+1,
                    round_in_progress=True, last_started_at=now.isoformat(),
                    last_observed_at=now.isoformat(), last_error_code=None, last_summary={},
                    next_run_at=(now+timedelta(seconds=POLL_SECONDS)).isoformat())
                self._save()
                stages = (["P0"] if not self._state["p0_completed"] else []) + ["P1"]
                for stage in stages:
                    if self._stop_event.is_set(): break
                    before = _moment(self.clock())
                    if not self._limits(before) or not self._source(before): break
                    try:
                        value = self.service.generate_auto("boat", stage)
                        self._state["last_summary"][stage] = self._summary(value)
                        if stage == "P0": self._state["p0_completed"] = True
                        self._save()
                    except Exception as error:
                        at = _moment(self.clock())
                        if not self._source(at): break
                        if self._stop_event.is_set(): break
                        if not self._limits(at): break
                        transient = isinstance(error, (OSError, TimeoutError)) or str(error) in _TRANSIENT
                        if transient:
                            self._state["last_error_code"] = "TRANSIENT_SOURCE_UNAVAILABLE"
                        else:
                            self._halt("AUTOMATIC_GENERATION_REJECTED",at)
                        break
                    at = _moment(self.clock())
                    if not self._limits(at) or not self._source(at): break
                at = _moment(self.clock())
                self._state.update(round_in_progress=False, last_completed_at=at.isoformat(),
                                   last_observed_at=at.isoformat())
                if self._state["state"] != "STOPPED":
                    self._state["state"] = "WAITING"
                    self._limits(at, after=True)
                self._save()
            except Exception:
                # Never include source exception text, paths, inputs or picks.
                # Do not let shutdown write stale cached state over an invalid
                # durable record whose hash or directory identity just failed.
                if self._state is not None:
                    self._state.update(state="STOPPED", halted_reason="AUTOMATIC_STATE_UNAVAILABLE")
                with self._mutex:
                    self._snapshot.update(state="STOPPED", halted_reason="AUTOMATIC_STATE_UNAVAILABLE")
            finally:
                if self._stop_event.is_set(): self._pause()
                if self.status()["state"] == "STOPPED": self._release()
            return self.status()

    def _pause(self):
        # The worker may already have checkpointed and released the profile.
        # An idempotent close must not overwrite a successor's durable state
        # using this instance's stale cached copy after releasing the lock.
        if self._lock_fd is None: return
        if self._state is not None and self._state["state"] != "STOPPED":
            try:
                self._state.update(state="PAUSED", round_in_progress=False)
                self._save()
            except Exception:
                with self._mutex:
                    self._snapshot.update(state="STOPPED", halted_reason="AUTOMATIC_STATE_UNAVAILABLE")
        self._release()

    def _run(self):
        try:
            while not self._stop_event.is_set():
                state = self.tick()
                if state["state"] in ("STOPPED", "ALREADY_RUNNING"): break
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
            if self._snapshot["state"] not in ("STOPPED", "PAUSED", "NOT_STARTED", "ALREADY_RUNNING"):
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
