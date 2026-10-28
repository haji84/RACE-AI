"""Measured historical BOAT course/ST projection, never a model or authority.

Rows and hashes are supplied metadata, not authenticated source bytes. Unknown
publication is diagnostic only. No source request, store, rating or imputation.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.util
import math
from pathlib import Path
import re
import sys
import types

PIN = "761247bee0209e37b1af6b8885e92cad3e9260a5"
CORE_SHA256 = "6684c7ee0b58fe40e210d6e8840391b74720f44bb579b266eee84956871db191"
SCHEMA = "RACE_AI_BOAT_OBSERVED_COURSE_HISTORY_V1"
STATES = ("OK", "F", "L", "MISSING", "ABSENT")
SOURCE_FIELDS = {"event_date_jst", "source_url", "source_sha256", "published_at", "captured_at"}
ROW_FIELDS = {"race_id", "lane", "racer_id", "course", "st", "st_status", "finish", "race_at", "source_sha256"}
RACE = re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")


def _fail():
    raise ValueError("BOAT_OBSERVED_HISTORY_REJECTED") from None


def _load_core():
    """Import the verified complete fixed core bytes in a separate namespace."""
    path = Path(__file__).resolve().parents[1] / "pr64-existing-reference" / "race_ai" / "core.py"
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        _fail()
    code = raw.replace(b"\r\n", b"\n")
    if hashlib.sha256(code).hexdigest() != CORE_SHA256:
        _fail()
    spec = importlib.util.spec_from_loader("_race_ai_pr64_measurements_761247", loader=None, origin=str(path))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    exec(compile(code, str(path), "exec"), module.__dict__)
    # Never accidentally rely on a different race_ai.core installed by a caller.
    prior = sys.modules.get("race_ai.core")
    if prior is not None:
        supplied = getattr(prior, "summarize", None)
        actual = module.summarize
        if (type(supplied) is not types.FunctionType or supplied.__code__.co_code != actual.__code__.co_code
                or supplied.__code__.co_consts != actual.__code__.co_consts
                or supplied.__code__.co_names != actual.__code__.co_names):
            _fail()
    return module


def _exact(value, fields):
    if type(value) is not dict or len(value) != len(fields) or set(value) != fields:
        _fail()


def _day(value):
    if type(value) is not str or len(value) != 10:
        _fail()
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        _fail()
    return result


def _time(value):
    if (type(value) is not str or len(value) > 40 or re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value) is None):
        _fail()
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        _fail()
    return result.astimezone(timezone.utc)


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _fail()
    return value


def _integer(value, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        _fail()


def _sources(records, asof):
    if type(records) is not list or len(records) > 60:
        _fail()
    by_sha, by_day = {}, {}
    for item in records:
        _exact(item, SOURCE_FIELDS)
        day = _day(item["event_date_jst"])
        if (type(item["source_url"]) is not str or len(item["source_url"]) > 256
                or item["source_url"] != f"https://www1.mbrace.or.jp/od2/K/{day:%Y%m}/k{day:%y%m%d}.lzh"):
            _fail()
        sha = _sha(item["source_sha256"])
        captured = _time(item["captured_at"])
        lower = datetime(day.year, day.month, day.day, tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc)
        publication = _time(item["published_at"]) if item["published_at"] is not None else None
        if captured < lower or publication is not None and not lower <= publication <= captured:
            _fail()
        owned = dict(item)
        if sha in by_sha:
            if by_sha[sha] != owned:
                _fail()
            continue
        by_sha[sha] = owned
        by_day.setdefault(item["event_date_jst"], []).append((captured, sha))
    selected = {}
    for day, versions in by_day.items():
        visible = sorted(v for v in versions if v[0] <= asof)
        if len({at for at, _ in visible}) != len(visible):
            _fail()  # Different content with tied capture has no latest order.
        if visible:
            selected[day] = visible[-1][1]
    return by_sha, selected


def _rows(rows, sources):
    if type(rows) is not list or len(rows) > 100000:
        _fail()
    unique, racer_slots, courses = {}, {}, {}
    for row in rows:
        _exact(row, ROW_FIELDS)
        match = RACE.fullmatch(row["race_id"]) if type(row["race_id"]) is str else None
        if match is None:
            _fail()
        day = _day(match[1][:4] + "-" + match[1][4:6] + "-" + match[1][6:8])
        sha = _sha(row["source_sha256"])
        if sha not in sources or sources[sha]["event_date_jst"] != day.isoformat():
            _fail()
        if _time(row["race_at"]) != datetime(day.year, day.month, day.day, tzinfo=timezone.utc):
            _fail()  # PR64's date sentinel is never an actual event timestamp.
        _integer(row["lane"], 1, 6)
        if type(row["racer_id"]) is not str or re.fullmatch(r"\d{4}", row["racer_id"]) is None:
            _fail()
        if type(row["st_status"]) is not str or row["st_status"] not in STATES:
            _fail()
        if row["st_status"] != "ABSENT":
            _integer(row["course"], 1, 6)
        if row["st_status"] == "ABSENT" and (row["course"] is not None or row["finish"] is not None):
            _fail()
        if row["st_status"] == "OK":
            if type(row["st"]) not in (int, float) or not 0 <= row["st"] <= 1 or not math.isfinite(row["st"]):
                _fail()
        elif row["st"] is not None:
            _fail()
        if row["finish"] is not None:
            _integer(row["finish"], 1, 6)
        key = (sha, row["race_id"], row["lane"])
        owned = dict(row)
        if key in unique:
            if unique[key] != owned or any(type(unique[key][k]) is not type(owned[k]) for k in ROW_FIELDS):
                _fail()
            continue
        racer_key = (sha, row["race_id"], row["racer_id"])
        course_key = (sha, row["race_id"], row["course"])
        if racer_key in racer_slots or row["course"] is not None and course_key in courses:
            _fail()
        racer_slots[racer_key] = row["lane"]
        if row["course"] is not None:
            courses[course_key] = row["lane"]
        unique[key] = owned
    return list(unique.values())


def _window(rows, count, core, withheld=False):
    if withheld:
        return {"status": "WITHHELD_AMBIGUOUS_ORDER", "requested": count, "summary": None,
                "valid_finish_n": None, "full_window": None, "status_counts": None, "row_refs": []}
    chosen = rows[:count]
    summary = core.summarize(rows, count)
    return {"status": "MEASURED" if chosen else "EMPTY_ELIGIBLE_HISTORY", "requested": count,
        "summary": summary, "valid_finish_n": sum(r["finish"] is not None for r in chosen),
        "full_window": len(chosen) == count, "status_counts": {s: sum(r["st_status"] == s for r in chosen) for s in STATES},
        "row_refs": [{k: r[k] for k in ("race_id", "lane", "source_sha256", "published_at", "captured_at")} for r in chosen]}


def project_boat_course_history(rows, source_records, *, event_date_jst, as_of, racer_ids):
    """Return private descriptive measurements, never a qualified model input."""
    try:
        day, at = _day(event_date_jst), _time(as_of)
        if (type(racer_ids) not in (list, tuple) or len(racer_ids) != 6
                or any(type(v) is not str or re.fullmatch(r"\d{4}", v) is None for v in racer_ids)
                or len(set(racer_ids)) != 6):
            _fail()
        core = _load_core()
        sources, selected = _sources(source_records, at)
        normalized = _rows(rows, sources)
        groups = {r: [] for r in sorted(racer_ids)}
        for row in normalized:
            if row["racer_id"] not in groups:
                continue
            src = sources[row["source_sha256"]]
            source_day = src["event_date_jst"]
            if _day(source_day) >= day:
                reason = "TARGET_DAY_OR_FUTURE"
            elif _time(src["captured_at"]) > at:
                reason = "CAPTURE_AFTER_AS_OF"
            elif selected.get(source_day) != row["source_sha256"]:
                reason = "SUPERSEDED_SOURCE"
            elif src["published_at"] is None:
                reason = "UNKNOWN_PUBLICATION"
            elif row["st_status"] == "ABSENT":
                reason = "ABSENT"
            else:
                reason = "QUALIFIED_HISTORY"
            groups[row["racer_id"]].append({**row, "published_at": src["published_at"],
                "captured_at": src["captured_at"], "disposition": reason})
        racers, qualified = [], 0
        for pid, observations in groups.items():
            observations.sort(key=lambda r: (r["race_id"], r["source_sha256"], r["lane"]))
            eligible = sorted((r for r in observations if r["disposition"] == "QUALIFIED_HISTORY"),
                              key=lambda r: r["race_id"], reverse=True)
            venues = {}
            for r in eligible:
                venues.setdefault(r["race_id"][:8], set()).add(r["race_id"][9:11])
            withheld = any(len(values) > 1 for values in venues.values())
            qualified += len(eligible)
            racers.append({"racer_id": pid, "observations": observations,
                "overall_10": _window(eligible, 10, core, withheld),
                "by_lane_10": {str(lane): _window([r for r in eligible if r["lane"] == lane], 10, core, withheld) for lane in range(1, 7)},
                "by_actual_course": {str(course): {str(n): _window([r for r in eligible if r["course"] == course], n, core, withheld)
                    for n in (5, 10, 20)} for course in range(1, 7)}})
        return {"schema": SCHEMA, "scope": "DESCRIPTIVE_MEASUREMENTS_NOT_FORECAST", "event_date_jst": event_date_jst,
            "as_of": as_of, "pr64_source_sha40": PIN, "pr64_core_sha256": CORE_SHA256,
            "ordering": "DATE_AND_RACE_NO_NOT_EVENT_TIME", "evidence_status": "SUPPLIED_METADATA_CONSISTENCY_ONLY",
            "source_records": sorted(sources.values(), key=lambda s: (s["event_date_jst"], _time(s["captured_at"]), s["source_sha256"])),
            "selected_sources": [dict(sources[sha]) for _, sha in sorted(selected.items())],
            "input_row_count": len(rows), "deduplicated_row_count": len(normalized), "qualified_row_count": qualified,
            "racers": racers, **dict.fromkeys(("source_bytes_authenticated", "publication_authenticated", "source_rights_verified",
                "model_admission", "forecast_generated", "official_prediction"), False)}
    except Exception:
        _fail()
