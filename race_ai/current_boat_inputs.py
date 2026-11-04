"""Bounded, current-day official BOAT input collection for private generation.

This provider performs no model inference. Exact originals are retained before
parsing; trusted application code separately admits personal analysis/private
storage. Source hashes and a local capture clock are not external attestation.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib import error, request
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

JST = timezone(timedelta(hours=9))
REQUEST_LIMIT = 240
CALL_REQUEST_LIMIT = 45
P1_RACE_LIMIT = 3
BUFFER = timedelta(seconds=210)
STATE_SCHEMA = "RACE_AI_CURRENT_BOAT_SOURCE_STATE_V1"
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class CurrentBoatInputError(ValueError):
    """A fixed safe reason; no source bodies, private paths or tickets."""


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


class _NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CurrentBoatInputError("OFFICIAL_SOURCE_REDIRECT_REJECTED")


def _default_open(req, *, timeout):
    return request.build_opener(_NoRedirects()).open(req, timeout=timeout)


class CurrentBoatInputs:
    """One explicit collection, fixed current JST day, no background polling.

    The private root is application-owned, outside Git and never selected by a
    browser request. A process lock and durable attempt counter survive restart.
    The 240/day limit is shared by P0/P1; no retry or alternate endpoint occurs
    after HTTP4xx, redirect, or source identity/parse failure.
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
            state = _json(_read(folder, "state.json", 1024 * 1024))
        except FileNotFoundError:
            _need(not os.listdir(folder), "PRIVATE_SOURCE_STATE_MISSING")
            state = dict(schema=STATE_SCHEMA, day=day, request_count=0, halted_reason=None,
                         captures=[], p0_capture=None, p1_ready={}, p1_attempted_at={})
        _need(type(state) is dict and state.get("schema") == STATE_SCHEMA and state.get("day") == day
              and type(state.get("request_count")) is int and 0 <= state["request_count"] <= REQUEST_LIMIT
              and type(state.get("captures")) is list and len(state["captures"]) <= state["request_count"]
              and type(state.get("p1_ready")) is dict and type(state.get("p1_attempted_at")) is dict,
              "PRIVATE_SOURCE_STATE_REJECTED")
        return state

    def _save(self, folder, state):
        temporary = "state-" + uuid.uuid4().hex + ".json"
        _write(folder, temporary, _wire(state))
        try: os.stat("state.json", dir_fd=folder, follow_symlinks=False)
        except FileNotFoundError: pass
        else: _private_file(os.stat("state.json", dir_fd=folder, follow_symlinks=False))
        os.replace(temporary, "state.json", src_dir_fd=folder, dst_dir_fd=folder); os.fsync(folder)

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

    def _fetch(self, folder, state, url, kind, calls, *, automatic_stop_at=None):
        # The server owns this boundary. Check before charging or opening each
        # source; a request already in flight may finish and retain its bytes.
        _need(automatic_stop_at is None or _moment(self.clock()) < automatic_stop_at,
              "AUTOMATIC_SESSION_END")
        _need(not state["halted_reason"], "SOURCE_SESSION_HALTED")
        _need(state["request_count"] < REQUEST_LIMIT and calls[0] < CALL_REQUEST_LIMIT,
              "SOURCE_GET_BUDGET_EXHAUSTED")
        state["request_count"] += 1; calls[0] += 1
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
            state["captures"].append(meta); self._save(folder, state)
            # Retain an already-started response even if its completion crosses
            # a policy boundary. It cannot authorize another GET or inference.
            _need(automatic_stop_at is None or _moment(self.clock()) < automatic_stop_at,
                  "AUTOMATIC_SESSION_END")
            _need(_moment(stamp).astimezone(JST).date().isoformat() == state["day"], "SOURCE_DAY_BOUNDARY_PASSED")
            return raw, meta
        except error.HTTPError as exc:
            if 400 <= exc.code < 500:
                state["halted_reason"] = "SOURCE_HTTP_4XX_STOP"; self._save(folder, state)
            if 500 <= exc.code < 600:
                raise CurrentBoatInputError("SOURCE_HTTP_TEMPORARILY_UNAVAILABLE") from None
            raise CurrentBoatInputError("SOURCE_HTTP_UNAVAILABLE") from None
        except (OSError, TimeoutError):
            raise CurrentBoatInputError("SOURCE_TRANSPORT_UNAVAILABLE") from None

    def status(self):
        """Read current-day counters without collection, inference, or writes.

        Missing or corrupt state beside retained source files is an error,
        never permission to reset the budget. A day never started reports zero
        without creating a day directory or a new state/lock file.
        """
        day = _moment(self.clock()).astimezone(JST).date().isoformat()
        try:
            with self._locked_day(day, create=False) as folder:
                state = self._state(folder, day) if folder is not None else None
                return dict(day_jst=day, requests_used=state["request_count"] if state else 0,
                            halted_reason=state["halted_reason"] if state else None)
        except (OSError, ValueError) as exc:
            if isinstance(exc, CurrentBoatInputError): raise
            raise CurrentBoatInputError("PRIVATE_CURRENT_SOURCE_STATUS_REJECTED") from None

    def collect(self, stage="P0", *, sport="boat", due_only=False, automatic_stop_at=None):
        _need(sport == "boat", "CURRENT_SPORT_INPUT_UNCONNECTED")
        _need(stage in ("P0", "P1"), "SUPPORTED_FORECAST_STAGE_REQUIRED")
        _need(type(due_only) is bool, "BOOLEAN_DUE_SELECTION_REQUIRED")
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
                _need(not state["halted_reason"], "SOURCE_SESSION_HALTED")
                try:
                    # A crash after the durable raw receipt but before parsing
                    # must not spend another GET or discard the first original.
                    recovered = state["p0_capture"] is None
                    if recovered:
                        saved = [entry for entry in state["captures"] if entry.get("kind") == "B"
                                 and entry.get("url") == official_url(day, "B")]
                        if saved: state["p0_capture"] = saved[0]
                    cached = state["p0_capture"] is not None
                    if cached:
                        meta = state["p0_capture"]; raw = self._cached(folder, meta)
                    else:
                        raw, meta = self._fetch(folder, state, official_url(day, "B"), "B", calls,
                                                automatic_stop_at=stop)
                    _need(meta["url"] == official_url(day, "B"), "OFFICIAL_B_SOURCE_IDENTITY_REJECTED")
                    inspect_lzh(raw)
                    text = extract_daily_lzh(raw, f"B{day:%y%m%d}.TXT")
                    program = normalize_races(text, day=day, source_url=meta["url"],
                        observed_at=meta["captured_at"], archive_sha256=meta["source_sha256"])
                    if not cached or recovered:
                        state["p0_capture"] = meta; self._save(folder, state)
                    _need(stop is None or _moment(self.clock()) < stop, "AUTOMATIC_SESSION_END")
                    result = self._build(program, meta, stage, folder, state, calls,
                                         due_only=due_only, automatic_stop_at=stop)
                    result["source_report"] = dict(state="INPUTS_READY" if result["inputs"] else "NO_QUALIFIED_INPUT",
                        day_jst=day.isoformat(), stage=stage, scheduled_races=len(result["schedule"]),
                        ready_races=len(result["inputs"]), source_requests=calls[0], request_count=state["request_count"],
                        request_limit=REQUEST_LIMIT, cache_used=cached, independent_source_verified=False,
                        raw_sources_saved=True, inference_performed=False, due_only=due_only)
                    return result
                except (ValueError, KeyError, TypeError, OverflowError, UnicodeError) as exc:
                    transient = isinstance(exc, CurrentBoatInputError) and str(exc) in (
                        "SOURCE_TRANSPORT_UNAVAILABLE", "SOURCE_HTTP_TEMPORARILY_UNAVAILABLE",
                        "AUTOMATIC_SESSION_END")
                    if not state["halted_reason"] and not transient:
                        state["halted_reason"] = "SOURCE_IDENTITY_OR_PARSE_STOP"; self._save(folder, state)
                    if isinstance(exc, CurrentBoatInputError): raise
                    raise CurrentBoatInputError("OFFICIAL_SOURCE_PARSE_REJECTED") from None
        except (OSError, ValueError) as exc:
            if isinstance(exc, CurrentBoatInputError): raise
            raise CurrentBoatInputError("PRIVATE_CURRENT_SOURCE_REJECTED") from None

    def _build(self, program, meta, stage, folder, state, calls, *, due_only=False, automatic_stop_at=None):
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
            rid = row["race_id"]
            if rid not in valid: continue
            now = _moment(self.clock())
            _need(now.astimezone(JST).date().isoformat() == program["date_jst"], "SOURCE_DAY_BOUNDARY_PASSED")
            if now + BUFFER >= _moment(row["cutoff_at"]):
                blocked.append(dict(race_id=rid, reason="CUTOFF_BUFFER")); continue
            if stage == "P0":
                snap = build_program_snapshot(valid[rid], source, event_date_jst=program["date_jst"],
                    as_of=now.isoformat(), race_revision=1)
                inputs[rid] = {stage:{"boat_observed":{"snapshot":snap}}}
            else: candidates.append(row)
        if stage == "P1":
            ready = [row for row in candidates if row["race_id"] in state["p1_ready"]]
            pending = []
            for row in candidates:
                rid = row["race_id"]
                if rid in state["p1_ready"]: continue
                last = state["p1_attempted_at"].get(rid)
                if last and _moment(self.clock()) - _moment(last) < timedelta(seconds=180):
                    blocked.append(dict(race_id=rid, reason="P1_SOURCE_REFRESH_COOLDOWN"))
                else: pending.append(row)
            if due_only:
                # Existing selection authenticates schedule identity/clock
                # claims and uses its unchanged 22-minute capture window.
                # Ready originals and cooling-down observations do not consume
                # that selector's capacity or starve later due races.
                evidence = [dict(race_id=row["race_id"], cutoff_at=row["cutoff_at"],
                    schedule_captured_at=meta["captured_at"], source_sha256=meta["source_sha256"])
                    for row in pending]
                queue = select_due_races(evidence, _moment(self.clock()).isoformat(), max_items=24)
                selected = {row["race_id"] for row in queue["eligible"]}
                blocked.extend(dict(race_id=row["race_id"], reason=row["reason"])
                    for row in queue["deferred"] + queue["rejected"])
                pending = [row for row in pending if row["race_id"] in selected]
            for row in ready + pending[:P1_RACE_LIMIT]:
                groups, extra_refs, reason = self._p1(row, program, folder, state, calls, rights,
                                                    automatic_stop_at=automatic_stop_at)
                references.update(extra_refs)
                if groups: inputs[row["race_id"]] = {stage:groups}
                else: blocked.append(dict(race_id=row["race_id"], reason=reason))
            blocked.extend(dict(race_id=row["race_id"], reason="P1_BOUNDED_CALL_NOT_SELECTED") for row in pending[P1_RACE_LIMIT:])
        return dict(schedule=schedule, inputs=inputs, blocked_races=blocked,
                    source_references=[dict(source_ref=url, source_rights_ref=ref) for url,ref in sorted(references)])

    def _p1(self, row, program, folder, state, calls, rights, *, automatic_stop_at=None):
        from .official_racelist_adapter import endpoint, parse_official_racelist
        from .official_race_updates import endpoint as preview_endpoint, parse_update
        from scripts.boat_ab_future_pilot import motor_top2
        from .boat_observed_pairwise_models import FEATURE_TRANSFORMS
        from .observed_p1_connection import locator
        rid = row["race_id"]; day = _moment(row["cutoff_at"]).astimezone(JST).date()
        venue, number = rid[9:11], int(rid[-2:]); now = _moment(self.clock())
        if now + BUFFER >= _moment(row["cutoff_at"]):
            return None, set(), "CUTOFF_BUFFER"
        purl = endpoint(day, venue, number); eurl = preview_endpoint(day, venue, number, "beforeinfo")
        ready = state["p1_ready"].get(rid)
        if ready:
            pm, em = ready; praw = self._cached(folder, pm)
        else:
            last = state["p1_attempted_at"].get(rid)
            if last and now - _moment(last) < timedelta(seconds=180):
                return None, set(), "P1_SOURCE_REFRESH_COOLDOWN"
            state["p1_attempted_at"][rid] = now.isoformat(); self._save(folder, state)
            praw, pm = self._fetch(folder, state, purl, "racelist", calls,
                                   automatic_stop_at=automatic_stop_at)
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
        else: eraw, em = self._fetch(folder, state, eurl, "beforeinfo", calls,
                                    automatic_stop_at=automatic_stop_at)
        _need(em["url"] == eurl, "OFFICIAL_P1_SOURCE_IDENTITY_REJECTED")
        preview = parse_update(eraw, kind="beforeinfo", day=day, venue=venue, race_no=number,
            source_url=eurl, captured_at=em["captured_at"], entries=card["boats"])
        if preview["status"] != "AVAILABLE" or preview.get("data") is None:
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
        return groups, {(s["source_url"],rights) for s in sources} | {(purl,rights),(eurl,rights)}, None
