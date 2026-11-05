"""Experimental video observations, sealed separately from forecast originals.

Source identity and capture times are caller declarations, never independent
authentication. Reading these private reports performs no media extraction,
network access, inference, training, or forecast replacement. Image-space
measurements do not establish physical speed or race prediction accuracy.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
from urllib.parse import parse_qs, urlsplit

from .boat_video_measurements import PHASES, _gate, _tracks, _windows, measure_tracks
from .private_cycle_capture import _parent_handle, _write_at


JOB_SCHEMA = "RACE_AI_BOAT_VIDEO_JOB_V1"
SCHEMA = "RACE_AI_BOAT_VIDEO_EVALUATION_V1"
_ERROR = "BOAT_VIDEO_EVALUATION_REJECTED"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_FILE = re.compile(r"([a-f0-9]{64})\.json\Z")
_RACE = re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                        r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z")
_JST = timezone(timedelta(hours=9))
_MAX_FILE = 32 * 1024 * 1024
_MAX_MEDIA = 256 * 1024 * 1024
_MAX_FILES = 50000
_MAX_TOTAL = 256 * 1024 * 1024
_JOB_REQUIRED = {"schema_version", "race_id", "cutoff_at", "roster", "source"}
_PARAMETERS = {"options", "phase_windows", "start_gate", "max_gap_seconds"}
_REPORT_FIELDS = {"schema_version", "report_sha256", "race_id", "cutoff_at", "roster", "source",
                  "analysis_started_at", "analysis_completed_at", "analysis_parameters", "media",
                  "tracking", "measurements", "pre_cutoff_available", "model_eligible",
                  "validation_status", "dataset_status"}


def _need(condition):
    if not condition:
        raise ValueError(_ERROR)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _wire(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _time(value):
    _need(type(value) is str and _TIMESTAMP.fullmatch(value))
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _need(parsed.utcoffset() is not None)
    return parsed


def _race_day(race):
    _need(type(race) is str)
    match = _RACE.fullmatch(race)
    _need(match is not None)
    day = datetime.strptime(match.group(1), "%Y%m%d").date()
    _need(day.strftime("%Y%m%d") == match.group(1))
    return day


def _roster(value, *, view=False):
    _need(type(value) is list and len(value) == 6)
    result = {}
    for row in value:
        _need(type(row) is dict)
        if not view:
            _need(set(row) == {"lane", "registration_number"})
        lane = row.get("number" if view else "lane")
        registration = row.get("registration_no" if view else "registration_number")
        _need(type(lane) is int and 1 <= lane <= 6 and lane not in result and
              type(registration) is str and re.fullmatch(r"[0-9]{4}", registration))
        result[lane] = registration
    _need(len(set(result.values())) == 6)
    return result


def _tree(value, *, depth=0):
    """Bound JSON evidence and refuse hidden eligibility or private URLs/paths."""
    _need(depth <= 24)
    if type(value) is dict:
        _need(len(value) <= 1000)
        for key, child in value.items():
            _need(type(key) is str and 0 < len(key) <= 100)
            lowered = key.lower()
            _need(not re.search(r"(?:^|_)(?:path|paths|pathname|filename|filepath|url|uri)(?:$|_)", lowered))
            if key in ("model_eligible", "identity_validated", "source_authenticity_independently_verified"):
                _need(child is False)
            if key == "validation_status":
                _need(child == "UNVALIDATED")
            _tree(child, depth=depth + 1)
    elif type(value) is list:
        _need(len(value) <= 500000)
        for child in value:
            _tree(child, depth=depth + 1)
    elif type(value) is str:
        _need(len(value) <= 4096 and not any(ord(c) < 32 for c in value))
        _need(not value.startswith(("/", "\\", "~")) and
              not re.search(r"(?:https?|file|s3)://", value, re.IGNORECASE))
    elif type(value) in (int, float):
        _need(_finite(value))
    else:
        _need(value is None or type(value) is bool)


def _source(value, race):
    required = {"kind", "media_sha256", "captured_at", "identity_status"}
    _need(type(value) is dict and required <= value.keys() <= required |
          {"public_page_url", "source_metadata_sha256"})
    kind, identity = value["kind"], value["identity_status"]
    _need(kind in ("OWNER_LOCAL", "OFFICIAL_BROWSER_CAPTURE", "SYNTHETIC_TEST"))
    _need(identity in ({"SYNTHETIC"} if kind == "SYNTHETIC_TEST" else
                      {"OWNER_DECLARED"} if kind == "OWNER_LOCAL" else
                      {"OWNER_DECLARED", "SOURCE_METADATA_LINKED"}))
    _need(type(value["media_sha256"]) is str and _SHA.fullmatch(value["media_sha256"]))
    captured = _time(value["captured_at"])
    _need(captured.astimezone(_JST).date() >= _race_day(race))
    if identity == "SOURCE_METADATA_LINKED":
        _need("source_metadata_sha256" in value)
    if "source_metadata_sha256" in value:
        _need(type(value["source_metadata_sha256"]) is str and _SHA.fullmatch(value["source_metadata_sha256"]))
    if "public_page_url" in value:
        public = value["public_page_url"]
        _need(type(public) is str and 1 <= len(public) <= 2048 and not any(ord(c) < 33 for c in public))
        parsed = urlsplit(public)
        _need(parsed.scheme == "https" and parsed.netloc == "www.boatrace.jp" and
              parsed.username is None and parsed.password is None and not parsed.fragment and
              re.fullmatch(r"/owpc/(?:pc|sp)/race/[a-z]+", parsed.path))
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        day, venue, number = _RACE.fullmatch(race).groups()
        _need(set(query) == {"hd", "jcd", "rno"} and query["hd"] == [day] and
              query["jcd"] == [venue] and query["rno"] in ([str(int(number))], [number]))
    return captured


def _parameters(value):
    _need(type(value) is dict and set(value) <= _PARAMETERS)
    _tree(value)
    from .boat_video_tracking import _options
    _options(value.get("options"))
    gap = value.get("max_gap_seconds", 0.3)
    _need(_finite(gap) and gap > 0)
    # Validate shapes without running phase discovery, especially on reads.
    _windows(value.get("phase_windows"), range(1, 7))
    _gate(value.get("start_gate"), "REFERENCE_IMAGE_PX")
    return value


def _job(value):
    _need(type(value) is dict and _JOB_REQUIRED <= value.keys() <= _JOB_REQUIRED | _PARAMETERS)
    _need(value["schema_version"] == JOB_SCHEMA)
    race_day = _race_day(value["race_id"])
    _need(_time(value["cutoff_at"]).astimezone(_JST).date() == race_day)
    _roster(value["roster"])
    _source(value["source"], value["race_id"])
    _parameters({key: value[key] for key in _PARAMETERS if key in value})
    return deepcopy(value)


def _tracking(value, digest):
    _need(type(value) is dict and value.get("schema_version") == "RACE_AI_BOAT_VIDEO_TRACKS_V1")
    _tree(value)
    _need(value.get("model_eligible") is False and value.get("validation_status") == "UNVALIDATED" and
          value.get("coordinate_space") == "REFERENCE_IMAGE_PX" and
          value.get("media_sha256") == digest and value.get("timeline_source") == "MEDIA_PTS")
    for key in ("width", "height"):
        _need(type(value.get(key)) is int and 0 < value[key] <= 16384)
    duration = value.get("duration_seconds")
    _need(_finite(duration) and duration >= 0)
    _need(type(value.get("quality")) is dict and type(value.get("tracks")) is list)
    _need({track.get("lane") for track in value["tracks"] if type(track) is dict} == set(range(1, 7))
          and len(value["tracks"]) == 6)
    # Validation retains null invalid points and all unrecognized quality evidence.
    _tracks(value["tracks"])
    for track in value["tracks"]:
        _need(all(row["t"] <= duration + 1e-6 for row in track["samples"]))
    return value


def _media(value):
    return {"sha256": value["media_sha256"], "width": value["width"], "height": value["height"],
            "duration_seconds": value["duration_seconds"], "timeline_source": value["timeline_source"]}


def _measurement(value, tracking):
    _need(type(value) is dict and value.get("schema_version") == "RACE_AI_BOAT_VIDEO_MEASUREMENTS_V1")
    _tree(value)
    _need(value.get("coordinate_space") == "REFERENCE_IMAGE_PX" and value.get("model_eligible") is False and
          value.get("identity_validated") is False and value.get("validation_status") == "UNVALIDATED" and
          value.get("time_basis") == "MEDIA_TIMELINE_SECONDS" and value.get("candidate_measurements") is True and
          value.get("calibration_status") == "IMAGE_COORDINATES_ONLY" and
          value.get("physical_velocity") == "NOT_ESTABLISHED")
    lanes = value.get("lanes")
    _need(type(lanes) is list and len(lanes) == 6)
    identities = {track["lane"]: track.get("identity_status") for track in tracking["tracks"]}
    seen = set()
    for lane in lanes:
        _need(type(lane) is dict and type(lane.get("lane")) is int and
              lane["lane"] in identities and lane["lane"] not in seen)
        seen.add(lane["lane"])
        _need(lane.get("identity_validated") is False and
              lane.get("identity_status") == (identities[lane["lane"]] if identities[lane["lane"]] in
                ("COLOR_CANDIDATE", "NUMBER_COLOR_AGREEMENT", "REVIEWED") else "UNRESOLVED"))
        phases = lane.get("phases")
        _need(type(phases) is dict and set(phases) == set(PHASES))
        for phase in phases.values():
            _need(type(phase) is dict and phase.get("status") in ("MEASURED", "MISSING") and
                  type(phase.get("sample_count")) is int and phase["sample_count"] >= 0 and
                  type(phase.get("metrics")) is list and phase.get("identity_validated") is False and
                  phase.get("validation_status") == "UNVALIDATED")
            if phase["status"] == "MISSING":
                _need(type(phase.get("reason")) is str and phase["reason"] and not phase["metrics"])
            else:
                _need(phase.get("reason") is None and phase["sample_count"] >= 3 and
                      _finite(phase.get("t_start")) and _finite(phase.get("t_end")) and
                      0 <= phase["t_start"] < phase["t_end"] <= tracking["duration_seconds"] + 1e-6)
            for metric in phase["metrics"]:
                _need(type(metric) is dict and set(metric) == {"name", "value", "unit"} and
                      type(metric["name"]) is str and _finite(metric["value"]) and
                      metric["unit"] in ("px", "px/s", "px/s^2", "s", "deg"))


def _report(value):
    _need(type(value) is dict and set(value) == _REPORT_FIELDS and value["schema_version"] == SCHEMA)
    _need(type(value["report_sha256"]) is str and _SHA.fullmatch(value["report_sha256"]))
    body = {key: child for key, child in value.items() if key != "report_sha256"}
    _need(sha256(_wire(body)).hexdigest() == value["report_sha256"])
    _job({"schema_version": JOB_SCHEMA, **{key: value[key] for key in
          ("race_id", "cutoff_at", "roster", "source")}, **_parameters(value["analysis_parameters"])})
    captured = _source(value["source"], value["race_id"])
    start, end, cutoff = (_time(value[key]) for key in
                          ("analysis_started_at", "analysis_completed_at", "cutoff_at"))
    _need(captured <= start <= end)
    _need(type(value["pre_cutoff_available"]) is bool and
          value["pre_cutoff_available"] == (captured <= start <= end < cutoff))
    _need(value["model_eligible"] is False and value["validation_status"] == "UNVALIDATED" and
          value["dataset_status"] == ("SYNTHETIC_ONLY" if value["source"]["kind"] == "SYNTHETIC_TEST" else "REAL_REPORTED"))
    tracking = _tracking(value["tracking"], value["source"]["media_sha256"])
    _need(_wire(value["media"]) == _wire(_media(tracking)))
    _measurement(value["measurements"], tracking)
    _need(0 < len(_wire(value)) <= _MAX_FILE)
    return deepcopy(value)


def _local_digest(path):
    raw = os.fspath(path)
    _need(type(raw) is str and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw) and not raw.startswith("//"))
    candidate = Path(raw).absolute()
    _need(not any(part.is_symlink() for part in (candidate, *candidate.parents)))
    descriptor = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= _MAX_MEDIA)
        digest = sha256()
        total = 0
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _need(total <= _MAX_MEDIA)
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        _need((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) ==
              (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
    return digest.hexdigest()


def _now(clock):
    value = clock()
    _need(type(value) is datetime and value.utcoffset() is not None)
    return value


def analyze_video(path, job, *, clock=None, extractor=None):
    """Analyze explicitly bound local media; seal true processing availability.

    An injected extractor is a test/integration boundary, not a replacement for
    measurement math. Input identity claims never become verified boat identity.
    """
    try:
        specification = _job(job)
        now = clock if clock is not None else lambda: datetime.now(timezone.utc)
        start = _now(now)
        _need(_time(specification["source"]["captured_at"]) <= start)
        digest = _local_digest(path)
        _need(digest == specification["source"]["media_sha256"])
        if extractor is None:
            from .boat_video_tracking import extract_tracks
            extractor = extract_tracks
        parameters = {key: specification[key] for key in _PARAMETERS if key in specification}
        tracking = _tracking(extractor(path, options=parameters.get("options")), digest)
        measured = measure_tracks(tracking["tracks"], coordinate_space="REFERENCE_IMAGE_PX",
            phase_windows=parameters.get("phase_windows"), start_gate=parameters.get("start_gate"),
            max_gap_seconds=parameters.get("max_gap_seconds", 0.3))
        end = _now(now)
        _need(end >= start)
        report = {"schema_version": SCHEMA, **{key: specification[key] for key in
                  ("race_id", "cutoff_at", "roster", "source")},
                  "analysis_started_at": start.isoformat(), "analysis_completed_at": end.isoformat(),
                  "analysis_parameters": parameters, "media": _media(tracking), "tracking": tracking,
                  "measurements": measured, "pre_cutoff_available": end < _time(specification["cutoff_at"]),
                  "model_eligible": False, "validation_status": "UNVALIDATED",
                  "dataset_status": "SYNTHETIC_ONLY" if specification["source"]["kind"] == "SYNTHETIC_TEST" else "REAL_REPORTED"}
        report["report_sha256"] = sha256(_wire(report)).hexdigest()
        return _report(report)
    except (KeyError, TypeError, OverflowError, RecursionError, UnicodeError, ValueError):
        raise ValueError(_ERROR) from None


@contextmanager
def _directory(private_root, *, create):
    root = Path(private_root).expanduser()
    _need(os.name == "posix" and root.is_absolute() and ".." not in root.parts)
    with _parent_handle(root) as parent:
        info = os.fstat(parent)
        _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
        if create:
            try:
                os.mkdir("video-evaluations", 0o700, dir_fd=parent)
            except FileExistsError:
                pass
        descriptor = os.open("video-evaluations", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(descriptor)
            _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
            yield descriptor
        finally:
            os.close(descriptor)


def _read(descriptor, name):
    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1 and
          stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= _MAX_FILE)
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
    with os.fdopen(opened, "rb") as stream:
        actual = os.fstat(stream.fileno())
        _need((actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino) and
              stat.S_ISREG(actual.st_mode) and actual.st_uid == os.getuid() and
              actual.st_nlink == 1 and stat.S_IMODE(actual.st_mode) == 0o600)
        raw = stream.read(_MAX_FILE + 1)
    _need(0 < len(raw) <= _MAX_FILE)
    return raw


def _decode(raw, digest):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _need(key not in result)
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: _need(False))
    report = _report(value)
    _need(report["report_sha256"] == digest and _wire(report) == raw)
    return report


def save_evaluation(private_root, report):
    """Append an immutable 0600 sealed version below an existing 0700 root."""
    try:
        checked = _report(report)
        digest, raw = checked["report_sha256"], _wire(checked)
        name = digest + ".json"
        with _directory(private_root, create=True) as descriptor:
            try:
                existing = _read(descriptor, name)
            except FileNotFoundError:
                try:
                    _write_at(descriptor, name, raw)
                except FileExistsError:
                    _need(_read(descriptor, name) == raw)
                os.fsync(descriptor)
            else:
                _need(existing == raw)
        return digest
    except (KeyError, TypeError, OverflowError, RecursionError, UnicodeError, ValueError):
        raise ValueError(_ERROR) from None


def read_evaluations(private_root, *, day=None):
    """Read and validate reports without accessing media or forecast models."""
    try:
        if day is not None:
            _need(type(day) is str and date.fromisoformat(day).isoformat() == day)
        reports, opened = [], False
        try:
            with _directory(private_root, create=False) as descriptor:
                opened = True
                names = os.listdir(descriptor)
                _need(len(names) <= _MAX_FILES)
                total = 0
                for name in sorted(names):
                    match = _FILE.fullmatch(name)
                    _need(match is not None)
                    raw = _read(descriptor, name)
                    total += len(raw)
                    _need(total <= _MAX_TOTAL)
                    report = _decode(raw, match.group(1))
                    if day is None or _race_day(report["race_id"]).isoformat() == day:
                        reports.append(report)
        except FileNotFoundError:
            _need(not opened)
        return reports
    except (KeyError, TypeError, OverflowError, RecursionError, UnicodeError, ValueError):
        raise ValueError(_ERROR) from None


def enrich_view(view, reports):
    """Copy a live view, adding only sealed exact-identity observation reports.

    Late processing remains visible as post-cutoff evidence. It never rewrites
    saved prediction inputs, ordering, results, or their timestamps.
    """
    try:
        _need(type(view) is dict and type(reports) is list)
        checked = [_report(report) for report in reports]
        result = deepcopy(view)
        for row in result.get("records", []):
            if type(row) is not dict or row.get("sport") != "boat":
                continue
            try:
                cutoff, roster = _time(row.get("cutoff_at")), _roster(row.get("participants"), view=True)
                for field in ("saved_cutoff_variants", "saved_schedule_cutoff_variants"):
                    _need(all(_time(value) == cutoff for value in row.get(field, [])))
            except (ValueError, TypeError, KeyError):
                continue
            matching = [report for report in checked if report["race_id"] == row.get("race_id") and
                _time(report["cutoff_at"]) == cutoff and _roster(report["roster"]) == roster and
                report["dataset_status"] == "REAL_REPORTED"]
            if matching:
                row["boat_video_evaluations"] = sorted(matching, key=lambda report:
                    (_time(report["analysis_completed_at"]), report["report_sha256"]))
        return result
    except (KeyError, TypeError, OverflowError, RecursionError, UnicodeError, ValueError):
        raise ValueError(_ERROR) from None
