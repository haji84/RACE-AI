"""Append-only private BOAT observations, separate from forecast originals.

Readers validate bounded, content-addressed JSON without fetching race sources,
running models, or changing any saved forecast. A local capture timestamp is
an observation claim, not an independent receipt or publication-time witness.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import parse_qs, urlsplit

from .private_cycle_capture import _parent_handle, _write_at


SCHEMA = "RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1"
_ERROR = "BOAT_SUPPLEMENTAL_CONTEXT_REJECTED"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_FILE = re.compile(r"([a-f0-9]{64})\.json\Z")
_RACE = re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")
_REGISTRATION = re.compile(r"[0-9]{4}\Z")
_MAX_FILE = 4 * 1024 * 1024
_MAX_FILES = 50000
_MAX_TOTAL = 64 * 1024 * 1024
_JST = timezone(timedelta(hours=9))
_FIELDS = {"schema", "race_id", "cutoff_at", "roster", "beforeinfo", "pitreport",
           "entry_history", "forecast_inputs_used"}
_COLLECTION_STATUSES = {"DEFERRED_TO_PRESERVE_FORECAST_TIME", "SOURCE_WAIT", "WORKER_HANDOFF",
                        "SOURCE_OR_LAYOUT_REJECTED", "PARSED", "NOT_OFFERED",
                        "UNSUPPORTED_STRUCTURE"}
_PROFILE_FIELDS = {"schema", "racer_id", "as_of", "sample_races", "race_ids",
                   "conditional_buckets", "actual_course_when_inward_mover_present",
                   "source_proofs", "derived_from_verified_results_only",
                   "source_authenticity_independently_verified", "description"}
_CONDITIONS = {"inward", "outer_to_inner3", "displaced", "crossed_by_outer_frame",
               "any_inward_mover_present"}
_COUNTS = ("starts", "wins", "top2", "top3", "denominator")
_RATES = (("win_rate", "wins"), ("top2_rate", "top2"), ("top3_rate", "top3"))


def _need(condition):
    if not condition:
        raise ValueError(_ERROR)


def _wire(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _time(value):
    _need(type(value) is str and 1 <= len(value) <= 50)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _need(parsed.utcoffset() is not None)
    return parsed


def _day(value):
    _need(type(value) is str and date.fromisoformat(value).isoformat() == value)
    return value


def _text(value, limit):
    return type(value) is str and len(value) <= limit and not any(ord(c) < 32 for c in value)


def _roster(value, *, view=False):
    _need(type(value) is list and len(value) == 6)
    result = {}
    for row in value:
        _need(type(row) is dict)
        lane = row.get("number" if view else "lane")
        registration = row.get("registration_no" if view else "registration_number")
        _need(type(lane) is int and 1 <= lane <= 6 and lane not in result and
              type(registration) is str and _REGISTRATION.fullmatch(registration))
        result[lane] = registration
    _need(set(result) == set(range(1, 7)) and len(set(result.values())) == 6)
    return result


def _source(source, race, kind):
    _need(type(source) is dict)
    required = {"source_url", "sha256", "captured_at", "published_at",
                "published_time_raw", "freshness_status"}
    _need(required <= source.keys() and type(source["sha256"]) is str and
          _SHA.fullmatch(source["sha256"]))
    captured = _time(source["captured_at"])
    published = source["published_at"]
    _need(published is None or _time(published) <= captured)
    _need(source["published_time_raw"] is None or _text(source["published_time_raw"], 300))
    _need(_text(source["freshness_status"], 100) and source["freshness_status"])
    _need(_text(source["source_url"], 2048))
    url = urlsplit(source["source_url"])
    _need(url.scheme == "https" and url.netloc == "www.boatrace.jp" and not url.fragment and
          url.path == "/owpc/pc/race/" + kind)
    query = parse_qs(url.query, keep_blank_values=True)
    day, venue, number = _RACE.fullmatch(race).groups()
    _need(set(query) == {"hd", "jcd", "rno"} and query["hd"] == [day] and
          query["jcd"] == [venue] and query["rno"] in ([str(int(number))], [number]))
    return captured


def _proof(proof, kind, day):
    _need(type(proof) is dict and set(proof) ==
          {"source_url", "source_sha256", "captured_at", "extracted_text_sha256"})
    _need(type(proof["source_sha256"]) is str and _SHA.fullmatch(proof["source_sha256"]))
    if "extracted_text_sha256" in proof:
        _need(type(proof["extracted_text_sha256"]) is str and _SHA.fullmatch(proof["extracted_text_sha256"]))
    moment = date.fromisoformat(day)
    expected = f"https://www1.mbrace.or.jp/od2/{kind}/{moment:%Y%m}/{kind.lower()}{moment:%y%m%d}.lzh"
    _need(proof["source_url"] == expected)
    return _time(proof["captured_at"])


def _bucket(bucket, sample):
    _need(type(bucket) is dict and set(bucket) == set(_COUNTS) | {field for field, _ in _RATES})
    _need(all(type(bucket[field]) is int for field in _COUNTS))
    _need(0 <= bucket["wins"] <= bucket["top2"] <= bucket["top3"] <= bucket["starts"] <= sample and
          bucket["denominator"] == bucket["starts"])
    for rate, count in _RATES:
        if bucket["starts"] == 0:
            _need(bucket[rate] is None)
        else:
            _need(type(bucket[rate]) in (int, float) and 0 <= bucket[rate] <= 1 and
                  bucket[rate] == bucket[count] / bucket["starts"])


def _profile(profile, roster, race_day):
    """Check descriptive counts and lineage, without asserting source authenticity."""
    _need(type(profile) is dict and set(profile) == _PROFILE_FIELDS and
          profile["schema"] == "RACE_AI_BOAT_ENTRY_CONDITIONAL_PROFILE_V1" and
          profile["racer_id"] in roster.values() and
          profile["derived_from_verified_results_only"] is True and
          profile["source_authenticity_independently_verified"] is False and
          type(profile["description"]) is str)
    as_of = _time(profile["as_of"])
    sample, races, proofs = profile["sample_races"], profile["race_ids"], profile["source_proofs"]
    _need(type(sample) is int and sample >= 0 and type(races) is list and len(races) == sample and
          type(proofs) is list and len(proofs) <= 10000)
    captures, days = [], set()
    for proof in proofs:
        _need(type(proof) is dict and set(proof) == {"date_jst", "B", "K"})
        day = _day(proof["date_jst"])
        _need(day not in days and day <= race_day and day <= as_of.astimezone(_JST).date().isoformat())
        days.add(day)
        for kind in ("B", "K"):
            captured = _proof(proof[kind], kind, day)
            _need(captured < as_of)
            if kind == "K":
                _need(captured.astimezone(_JST).date().isoformat() >= day)
            captures.append(captured)
    seen = set()
    for race in races:
        _need(type(race) is str and _RACE.fullmatch(race) and race not in seen)
        seen.add(race)
        day = datetime.strptime(race[:8], "%Y%m%d").date().isoformat()
        _need(day in days)
    _need(sample == 0 or bool(days))
    conditions, courses = profile["conditional_buckets"], profile["actual_course_when_inward_mover_present"]
    _need(type(conditions) is dict and set(conditions) == _CONDITIONS and
          type(courses) is dict and set(courses) == {str(n) for n in range(1, 7)})
    for bucket in [*conditions.values(), *courses.values()]:
        _bucket(bucket, sample)
    any_mover = conditions["any_inward_mover_present"]
    for field in _COUNTS:
        _need(sum(bucket[field] for bucket in courses.values()) == any_mover[field])
        _need(conditions["outer_to_inner3"][field] <= conditions["inward"][field] and
              conditions["inward"][field] + conditions["displaced"][field] <= any_mover[field] and
              conditions["crossed_by_outer_frame"][field] <= any_mover[field])
    return as_of, captures


def _context(value):
    """Validate identity and derive capture admission without touching the input."""
    _need(type(value) is dict and _FIELDS <= value.keys() and
          value.keys() <= _FIELDS | {"pitreport_collection_status"} and value.get("schema") == SCHEMA and
          value.get("forecast_inputs_used") is False)
    result = deepcopy(value)
    race = result["race_id"]
    _need(type(race) is str and _RACE.fullmatch(race))
    race_day = datetime.strptime(race[:8], "%Y%m%d").date().isoformat()
    cutoff = _time(result["cutoff_at"])
    _need(cutoff.astimezone(_JST).date().isoformat() == race_day)
    if "pitreport_collection_status" in result:
        _need(result["pitreport_collection_status"] in _COLLECTION_STATUSES)
    roster = _roster(result["roster"])
    captures = []
    for kind in ("beforeinfo", "pitreport"):
        parser = result[kind]
        if parser is None:
            continue
        _need(type(parser) is dict and parser.get("race_id") == race and
              parser.get("schema") == "RACE_AI_BOAT_OBSERVATION_CONTEXT_V1" and parser.get("kind") == kind and
              parser.get("event_date_jst") == race_day and parser.get("venue_code") == race[9:11] and
              type(parser.get("race_no")) is int and parser["race_no"] == int(race[-2:]) and
              parser.get("body_identity_verified") is True and parser.get("forecast_inputs_used", False) is False)
        _need(_time(parser.get("source_cutoff_at")).astimezone(_JST).date().isoformat() == race_day)
        captured = _source(parser.get("source"), race, kind)
        captures.append(captured)
        participants = parser.get("participants")
        _need(type(participants) is list and len(participants) <= 6)
        known = {}
        for row in participants:
            _need(type(row) is dict and type(row.get("lane")) is int and row["lane"] in roster and
                  row["lane"] not in known and row.get("registration_number") in (None, roster[row["lane"]]))
            known[row["lane"]] = row.get("registration_number")
        from .boat_observation_context import eligibility_for_cutoff
        _need(parser.get("roster_binding_status") in ("VERIFIED", "NOT_PUBLISHED") and
              parser.get("status") in ("PARSED", "NOT_OFFERED", "UNSUPPORTED_STRUCTURE"))
        if parser.get("roster_binding_status") == "VERIFIED":
            _need(known == roster)
        eligibility = eligibility_for_cutoff(parser, cutoff_at=result["cutoff_at"])
        parser["cutoff_eligibility"] = eligibility
        # Some pure parser callers place the eligibility fields directly on the
        # parser result. Retain that shape while rejecting a late admission.
        for field in eligibility:
            if field in parser:
                parser[field] = eligibility[field]
    history = result["entry_history"]
    if history is not None:
        _need(type(history) is dict and type(history.get("profiles")) is list and len(history["profiles"]) <= 6)
        seen = set()
        history_captures, profile_times = [], []
        for profile in history["profiles"]:
            as_of, profile_captures = _profile(profile, roster, race_day)
            _need(profile["racer_id"] not in seen)
            seen.add(profile["racer_id"])
            profile_times.append(as_of)
            history_captures.extend(profile_captures)
        captures.extend(history_captures)
        early = bool(history_captures) and max(history_captures) < cutoff
        eligible = early and all(as_of <= cutoff for as_of in profile_times)
        history["cutoff_eligibility"] = dict(captured_before_cutoff=early,
            pre_cutoff_eligible=eligible,
            reason="CAPTURED_BEFORE_CUTOFF" if eligible else "RETROSPECTIVE_HISTORY_CONTEXT")
    _need(captures)
    raw = _wire(result)
    _need(0 < len(raw) <= _MAX_FILE)
    return result, max(captures)


@contextmanager
def _directory(private_root, *, create):
    root = Path(private_root).expanduser()
    _need(os.name == "posix" and root.is_absolute() and ".." not in root.parts)
    with _parent_handle(root) as parent:
        info = os.fstat(parent)
        _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
        if create:
            try:
                os.mkdir("boat-context", 0o700, dir_fd=parent)
            except FileExistsError:
                pass
        fd = os.open("boat-context", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(fd)
            _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
            yield fd
        finally:
            os.close(fd)


def _read(fd, name):
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
          stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and 0 < info.st_size <= _MAX_FILE)
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(descriptor, "rb") as stream:
        actual = os.fstat(stream.fileno())
        _need((actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino) and
              stat.S_ISREG(actual.st_mode) and actual.st_uid == os.getuid() and
              actual.st_nlink == 1 and stat.S_IMODE(actual.st_mode) == 0o600)
        raw = stream.read(_MAX_FILE + 1)
    _need(len(raw) <= _MAX_FILE)
    return raw


def _decode(raw, ident):
    _need(sha256(raw).hexdigest() == ident)
    def unique(pairs):
        out = {}
        for key, value in pairs:
            _need(key not in out)
            out[key] = value
        return out
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: _need(False))
    checked, captured = _context(value)
    _need(_wire(checked) == raw)
    return checked, captured


def save_context(private_root, context):
    """Save a new immutable 0600 version under an existing private 0700 root."""
    try:
        checked, _ = _context(context)
        raw = _wire(checked)
        ident = sha256(raw).hexdigest()
        name = ident + ".json"
        with _directory(private_root, create=True) as fd:
            try:
                existing = _read(fd, name)
            except FileNotFoundError:
                try:
                    _write_at(fd, name, raw)
                except FileExistsError:
                    _need(_read(fd, name) == raw)
                os.fsync(fd)
            else:
                _need(existing == raw)
        return ident
    except (KeyError, TypeError, OverflowError, RecursionError, UnicodeError, ValueError):
        raise ValueError(_ERROR) from None


def _profile_clock(profile):
    availability = [_time(proof[kind]["captured_at"])
                    for proof in profile["source_proofs"] for kind in ("B", "K")]
    return (max(availability, default=datetime.min.replace(tzinfo=timezone.utc)),
            _time(profile["as_of"]), sha256(_wire(profile)).hexdigest())


def _merge_versions(values):
    """Preserve separately captured components within one saved race identity."""
    races = {}
    for value in values:
        checked, captured = _context(value)
        races.setdefault(checked["race_id"], []).append((captured, sha256(_wire(checked)).hexdigest(), checked))
    contexts = {}
    for race, versions in races.items():
        _, _, anchor = max(versions, key=lambda item: item[:2])
        roster, cutoff = _roster(anchor["roster"]), _time(anchor["cutoff_at"])
        compatible = [value for _, _, value in versions
                      if _roster(value["roster"]) == roster and _time(value["cutoff_at"]) == cutoff]
        merged = deepcopy(anchor)
        for kind in ("beforeinfo", "pitreport"):
            candidates = [value for value in compatible if value[kind] is not None]
            if not candidates:
                continue
            selected = max(candidates, key=lambda value: (
                _time(value[kind]["source"]["captured_at"]), sha256(_wire(value[kind])).hexdigest()))
            merged[kind] = deepcopy(selected[kind])
            if kind == "pitreport" and any("pitreport_collection_status" in value for value in compatible):
                merged["pitreport_collection_status"] = selected.get("pitreport_collection_status", selected[kind]["status"])
        histories = [value["entry_history"] for value in compatible if value["entry_history"] is not None]
        if histories:
            profiles = {}
            for history in histories:
                for profile in history["profiles"]:
                    key = profile["racer_id"]
                    if key not in profiles or _profile_clock(profile) > _profile_clock(profiles[key]):
                        profiles[key] = profile
            merged["entry_history"] = {"profiles": [deepcopy(profiles[registration])
                for _, registration in sorted(roster.items()) if registration in profiles]}
        # Derived admission flags describe this composition; source clocks and
        # immutable version files remain unchanged.
        contexts[race], _ = _context(merged)
    return contexts


def read_contexts(private_root, *, day):
    """Verify immutable versions and compose matching, independently timed facts."""
    try:
        _day(day)
        values, versions = [], []
        try:
            with _directory(private_root, create=False) as fd:
                names = os.listdir(fd)
                _need(len(names) <= _MAX_FILES)
                total = 0
                for name in sorted(names):
                    match = _FILE.fullmatch(name)
                    _need(match is not None)
                    raw = _read(fd, name)
                    total += len(raw)
                    _need(total <= _MAX_TOTAL)
                    value, _ = _decode(raw, match.group(1))
                    if value["race_id"][:8] != day.replace("-", ""):
                        continue
                    ident = match.group(1)
                    versions.append(ident)
                    values.append(value)
        except FileNotFoundError:
            # An absent store is normal. An absent version during a read is an
            # integrity failure, rather than permission to drop its context.
            _need(not values and not versions)
        contexts = _merge_versions(values)
        return {"contexts": contexts,
                "revision": sha256(_wire(dict(versions=versions, contexts=contexts))).hexdigest()}
    except (KeyError, TypeError, OverflowError, RecursionError, UnicodeError, ValueError):
        raise ValueError(_ERROR) from None


def merge_contexts(*snapshots):
    """Combine native/workflow components without crossing roster or cutoff."""
    values = []
    for snapshot in snapshots:
        _need(type(snapshot) is dict and type(snapshot.get("contexts")) is dict)
        for race, value in snapshot["contexts"].items():
            checked, _ = _context(value)
            _need(race == checked["race_id"])
            values.append(checked)
    contexts = _merge_versions(values)
    revision = sha256(_wire(contexts)).hexdigest()
    return {"contexts": contexts, "revision": revision}


def attach_contexts(view, snapshot):
    """Add only matched optional observations; return their display revision."""
    attached = {}
    for row in view.get("records", []):
        if row.get("sport") != "boat":
            continue
        value = snapshot.get("contexts", {}).get(row.get("race_id"))
        if value is None:
            continue
        try:
            checked, _ = _context(value)
            cutoff = _time(row.get("cutoff_at"))
            _need(cutoff == _time(checked["cutoff_at"]) and
                  _roster(row.get("participants"), view=True) == _roster(checked["roster"]))
            for field in ("saved_cutoff_variants", "saved_schedule_cutoff_variants"):
                _need(all(_time(value) == cutoff for value in row.get(field, [])))
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            continue
        row["boat_observation_context"] = checked
        attached[row["race_id"]] = sha256(_wire(checked)).hexdigest()
    return sha256(_wire(attached)).hexdigest() if attached else None
