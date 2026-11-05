"""Pure, experimental measurements of supplied camera-stabilized boat tracks.

This module does not detect boats, establish identity, calibrate a camera, verify
media playback speed, or promote observations into prediction features. Rates
use supplied media timestamps; finite chords and speed trends are sampled
observations, not instantaneous physical velocity or acceleration. Water-plane
units remain conditional on the caller's supplied calibration evidence.
"""
import math
import re


PHASES = ("turn", "exit", "runup", "straight")
IDENTITIES = ("COLOR_CANDIDATE", "NUMBER_COLOR_AGREEMENT", "REVIEWED")


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _point(value):
    _require(type(value) in (list, tuple) and len(value) == 2
             and all(_finite(v) for v in value), "INVALID_POINT")
    return tuple(float(v) for v in value)


def _calibration(value):
    _require(type(value) is dict, "CALIBRATION_EVIDENCE_REQUIRED")
    _require(value.get("validation_status") == "CALIBRATION_PROVIDED_UNVERIFIED"
             and value.get("ground_plane") is True and value.get("world_units") == "m",
             "INVALID_CALIBRATION_EVIDENCE")
    for key in ("source_sha256", "reference_frame_sha256"):
        _require(type(value.get(key)) is str and re.fullmatch(r"[a-fA-F0-9]{64}", value[key]),
                 "INVALID_CALIBRATION_HASH")
    for key, minimum in (("training_anchor_count", 4), ("independent_check_count", 2)):
        _require(type(value.get(key)) is int and value[key] >= minimum,
                 "INSUFFICIENT_CALIBRATION_ANCHORS")
    error = value.get("max_check_error_m")
    _require(_finite(error) and 0 <= error <= 0.25, "INVALID_CALIBRATION_CHECK_ERROR")
    rows = value.get("per_frame_checks")
    _require(type(rows) is list, "CALIBRATION_FRAME_CHECKS_REQUIRED")
    checks = set()
    for row in rows:
        _require(type(row) is dict, "INVALID_CALIBRATION_FRAME_CHECK")
        for key in ("scene", "frame_index"):
            _require(type(row.get(key)) is int and row[key] >= 0, "INVALID_CALIBRATION_FRAME_CHECK")
        error = row.get("max_check_error_m")
        _require(_finite(error) and 0 <= error <= value["max_check_error_m"], "INVALID_CALIBRATION_FRAME_CHECK")
        key = (row["scene"], row["frame_index"])
        _require(key not in checks, "DUPLICATE_CALIBRATION_FRAME_CHECK")
        checks.add(key)
    return checks


def _gate(value, coordinate_space):
    if value is None:
        return None
    _require(type(value) is dict, "INVALID_START_GATE")
    _require(value.get("coordinate_space", coordinate_space) == coordinate_space,
             "START_GATE_COORDINATE_SPACE_MISMATCH")
    a, b, normal = (_point(value.get(k)) for k in ("a", "b", "normal"))
    tangent = (b[0] - a[0], b[1] - a[1])
    length, norm = math.hypot(*tangent), math.hypot(*normal)
    _require(math.isfinite(length) and math.isfinite(norm) and length > 0 and norm > 0,
             "INVALID_START_GATE")
    tangent = (tangent[0] / length, tangent[1] / length)
    normal = (normal[0] / norm, normal[1] / norm)
    _require(abs(tangent[0] * normal[0] + tangent[1] * normal[1]) <= 1e-6,
             "START_GATE_NORMAL_NOT_PERPENDICULAR")
    return a, tangent, normal, length


def _windows(value, lanes):
    if value is None:
        return {}
    _require(type(value) is dict, "INVALID_PHASE_WINDOWS")
    result = {}
    for lane, phases in value.items():
        _require(type(lane) is str and lane in {str(n) for n in lanes}
                 and type(phases) is dict, "INVALID_PHASE_WINDOW_LANE")
        result[lane] = {}
        for name, interval in phases.items():
            _require(name in PHASES and type(interval) in (list, tuple) and len(interval) == 2
                     and all(_finite(n) for n in interval)
                     and 0 <= interval[0] < interval[1], "INVALID_PHASE_WINDOW")
            result[lane][name] = tuple(float(n) for n in interval)
    return result


def _tracks(value):
    _require(type(value) is list, "INVALID_TRACKS")
    result = []
    lanes = set()
    for track in value:
        _require(type(track) is dict and type(track.get("lane")) is int
                 and 1 <= track["lane"] <= 6 and track["lane"] not in lanes, "INVALID_TRACK_LANE")
        lanes.add(track["lane"])
        rows = track.get("samples")
        _require(type(rows) is list, "INVALID_TRACK_SAMPLES")
        previous_t = previous_frame = -1
        for row in rows:
            _require(type(row) is dict, "INVALID_SAMPLE")
            _require(type(row.get("valid")) is bool, "INVALID_SAMPLE_VALIDITY")
            _require(_finite(row.get("t")), "NONFINITE_SAMPLE")
            for key in ("x", "y"):
                _require(key in row and (_finite(row[key]) or
                         (row["valid"] is False and row[key] is None)), "NONFINITE_SAMPLE")
            _require(row["t"] >= 0 and row["t"] > previous_t, "UNORDERED_SAMPLE_TIME")
            _require(type(row.get("frame_index")) is int and row["frame_index"] > previous_frame,
                     "UNORDERED_SAMPLE_FRAME")
            _require(type(row.get("scene")) is int and row["scene"] >= 0, "INVALID_SAMPLE_SCENE")
            if "position_error" in row:
                error = row["position_error"]
                _require((_finite(error) and error >= 0) or
                         (row["valid"] is False and error is None), "INVALID_POSITION_ERROR")
            previous_t, previous_frame = row["t"], row["frame_index"]
        result.append(track)
    return result


def _distance(a, b):
    distance = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
    _require(math.isfinite(distance), "NONFINITE_DERIVED_GEOMETRY")
    return distance


def _segments(rows, max_gap):
    chunks = []
    current = []
    for row in rows:
        if not row["valid"]:
            if current:
                chunks.append(current)
                current = []
            continue
        if current and (row["scene"] != current[-1]["scene"]
                        or row["t"] - current[-1]["t"] > max_gap + 1e-12):
            chunks.append(current)
            current = []
        current.append(row)
    if current:
        chunks.append(current)
    return chunks


def _heading_changes(rows):
    changes = []
    for a, b, c in zip(rows, rows[1:], rows[2:]):
        if _distance(a, b) <= 1e-12 or _distance(b, c) <= 1e-12:
            changes.append(None)
            continue
        first = math.atan2(b["y"] - a["y"], b["x"] - a["x"])
        second = math.atan2(c["y"] - b["y"], c["x"] - b["x"])
        changes.append(math.atan2(math.sin(second - first), math.cos(second - first)))
    return changes


def _automatic_turn(chunks):
    candidates = []
    for rows in chunks:
        changes = _heading_changes(rows)
        start = None
        sign = 0
        for i in range(len(changes) + 1):
            angle = changes[i] if i < len(changes) else None
            # Only suppress floating point direction noise. A per-frame degree
            # threshold would miss the same arc when sampled more frequently.
            current_sign = (1 if angle > 0 else -1) if angle is not None and abs(angle) > 1e-9 else 0
            if start is not None and current_sign != sign:
                section = changes[start:i]
                total = abs(sum(section))
                if len(section) >= 3 and total >= math.radians(45) - 1e-12:
                    candidates.append((total, rows[start:i + 2]))
                start = None
            if current_sign and start is None:
                start, sign = i, current_sign
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _straight_supported(rows):
    """Conservative whole-window image geometry, not a validated phase classifier.

    Test a maximal candidate as a whole: do not rescue short slices from a
    gently bending arc merely because each individual heading change is small.
    """
    if len(rows) < 3:
        return False
    changes = _heading_changes(rows)
    if any(angle is None for angle in changes):
        return False
    headings = [0.0]
    for angle in changes:
        headings.append(headings[-1] + angle)
    if (max(headings) - min(headings) > math.radians(5) + 1e-12
            or sum(abs(angle) for angle in changes) > math.radians(10) + 1e-12):
        return False
    chord = _distance(rows[0], rows[-1])
    path = sum(_distance(a, b) for a, b in zip(rows, rows[1:]))
    if chord <= 1e-12 or path > chord * 1.005:
        return False
    dx = (rows[-1]["x"] - rows[0]["x"]) / chord
    dy = (rows[-1]["y"] - rows[0]["y"]) / chord
    max_offset = max(abs((row["x"] - rows[0]["x"]) * dy
                         - (row["y"] - rows[0]["y"]) * dx) for row in rows)
    return max_offset <= chord * 0.02


def _automatic_straight(chunks):
    candidates = []
    for rows in chunks:
        start = 0
        for i, angle in enumerate(_heading_changes(rows)):
            if angle is None or abs(angle) > math.radians(3):
                if i + 2 - start >= 3:
                    candidates.append(rows[start:i + 2])
                start = i + 1
        if len(rows) - start >= 3:
            candidates.append(rows[start:])
    candidates = [rows for rows in candidates if _straight_supported(rows)]
    # Stable input ordering breaks ties without favouring a later camera scene.
    return max(candidates, key=lambda rows: round(rows[-1]["t"] - rows[0]["t"], 12)) if candidates else None


def _crossings(chunks, gate):
    if gate is None:
        return []
    origin, tangent, normal, length = gate
    crossings = []
    for rows in chunks:
        for a, b in zip(rows, rows[1:]):
            da = (a["x"] - origin[0]) * normal[0] + (a["y"] - origin[1]) * normal[1]
            db = (b["x"] - origin[0]) * normal[0] + (b["y"] - origin[1]) * normal[1]
            if not da < 0 <= db:
                continue
            fraction = -da / (db - da)
            x = a["x"] + fraction * (b["x"] - a["x"])
            y = a["y"] + fraction * (b["y"] - a["y"])
            along = (x - origin[0]) * tangent[0] + (y - origin[1]) * tangent[1]
            if -1e-12 <= along <= length + 1e-12:
                crossing_t = a["t"] + fraction * (b["t"] - a["t"])
                crossings.append((crossing_t, rows, (a["frame_index"], b["frame_index"])))
    return crossings


def _missing(reason, source="NOT_DETERMINED", rows=None):
    rows = rows or []
    return {"status": "MISSING", "reason": reason, "metrics": [], "sample_count": len(rows),
            "t_start": rows[0]["t"] if rows else None, "t_end": rows[-1]["t"] if rows else None,
            "window_source": source, "validation_status": "UNVALIDATED", "identity_validated": False}


def _quality(rows, max_gap, frame_checks):
    if len(rows) < 3:
        return "INSUFFICIENT_SAMPLES"
    if any(not row["valid"] for row in rows):
        return "OCCLUDED_OR_INVALID_SAMPLE"
    if any(row["scene"] != rows[0]["scene"] for row in rows):
        return "CAMERA_SCENE_CHANGE"
    if any(b["t"] - a["t"] > max_gap + 1e-12 for a, b in zip(rows, rows[1:])):
        return "SAMPLE_GAP"
    if frame_checks is not None and any((r["scene"], r["frame_index"]) not in frame_checks for r in rows):
        return "CALIBRATION_FRAME_CHECK_MISSING"
    if not any(_distance(a, b) > 1e-12 for a, b in zip(rows, rows[1:])):
        return "NO_MEASURABLE_DISPLACEMENT"
    # Supplied errors are unverified, but cannot be ignored when they already
    # mask a measured interval. This is a rejection rule, not certification of
    # displacement or heading accuracy when the rule passes.
    for a, b in zip(rows, rows[1:]):
        if "position_error" in a and "position_error" in b:
            error = a["position_error"] + b["position_error"]
            if error > 0 and _distance(a, b) <= error:
                return "POSITION_DISPLACEMENT_UNRESOLVED"
    return None


def _measure(name, rows, source, distance_unit):
    elapsed = rows[-1]["t"] - rows[0]["t"]
    distances = [_distance(a, b) for a, b in zip(rows, rows[1:])]
    durations = [b["t"] - a["t"] for a, b in zip(rows, rows[1:])]
    speeds = [d / t for d, t in zip(distances, durations)]
    midpoints = [a["t"] + dt / 2 for a, dt in zip(rows, durations)]
    changes = _heading_changes(rows)
    speed_unit = distance_unit + "/s"
    trend_unit = distance_unit + "/s^2"
    metrics = [{"name": "window_duration", "value": elapsed, "unit": "s"}]
    result = {"status": "MEASURED", "reason": None, "metrics": metrics, "sample_count": len(rows),
              "t_start": rows[0]["t"], "t_end": rows[-1]["t"], "scene": rows[0]["scene"],
              "window_source": source, "validation_status": "UNVALIDATED", "identity_validated": False,
              "measurement_scope": "SAMPLED_CHORDS_AND_MEDIA_TIMELINE_ONLY",
              "instantaneous_acceleration": "NOT_ESTIMATED"}

    def add(key, value, unit):
        _require(math.isfinite(value), "NONFINITE_DERIVED_MEASUREMENT")
        metrics.append({"name": key, "value": value, "unit": unit})

    if name == "turn":
        if any(angle is None for angle in changes):
            return _missing("UNRESOLVED_HEADING", source, rows)
        heading_change = abs(sum(changes))
        if heading_change <= 1e-9:
            return _missing("NO_OBSERVED_TURN", source, rows)
        add("sampled_heading_change", math.degrees(heading_change), "deg")
        add("sampled_absolute_heading_change", math.degrees(sum(abs(a) for a in changes)), "deg")
        add("sampled_path_length", sum(distances), distance_unit)
        add("equivalent_sampled_radius", sum(distances) / heading_change, distance_unit)
        result["radius_scope"] = "SAMPLED_CHORD_LENGTH_DIVIDED_BY_NET_SAMPLED_HEADING_CHANGE_NOT_INSTANTANEOUS_RADIUS"
    elif name in ("exit", "runup"):
        center_t = sum(midpoints) / len(midpoints)
        center_speed = sum(speeds) / len(speeds)
        denominator = sum((t - center_t) ** 2 for t in midpoints)
        _require(denominator > 0, "INSUFFICIENT_TIME_SEPARATION")
        slope = sum((t - center_t) * (speed - center_speed) for t, speed in zip(midpoints, speeds)) / denominator
        residuals = [speed - (center_speed + slope * (t - center_t)) for t, speed in zip(midpoints, speeds)]
        add("sampled_speed_trend", slope, trend_unit)
        add("first_interval_speed", speeds[0], speed_unit)
        add("last_interval_speed", speeds[-1], speed_unit)
        add("interval_speed_change", speeds[-1] - speeds[0], speed_unit)
        add("speed_trend_residual_rms", math.sqrt(sum(r * r for r in residuals) / len(residuals)), speed_unit)
        result["speed_trend_scope"] = "LEAST_SQUARES_TREND_OF_INTERVAL_AVERAGED_CHORD_SPEED_VERSUS_MEDIA_TIME_MIDPOINT"
        provided = ["position_error" in row for row in rows]
        if all(provided):
            errors = [(a["position_error"] + b["position_error"]) / dt
                      for a, b, dt in zip(rows, rows[1:], durations)]
            add("max_supplied_interval_speed_error", max(errors), speed_unit)
            add("sampled_speed_trend_error_bound", sum(abs(t - center_t) * error
                for t, error in zip(midpoints, errors)) / denominator, trend_unit)
            result["uncertainty_scope"] = "SUPPLIED_POSITION_ERROR_ONLY_UNCERTIFIED"
        else:
            result["uncertainty_scope"] = ("INCOMPLETE_POSITION_ERROR_NOT_BOUNDED" if any(provided)
                                           else "POSITION_ERROR_NOT_PROVIDED")
    else:
        chord = _distance(rows[0], rows[-1])
        if chord <= 1e-12:
            return _missing("STRAIGHT_AXIS_UNRESOLVED", source, rows)
        dx = (rows[-1]["x"] - rows[0]["x"]) / chord
        dy = (rows[-1]["y"] - rows[0]["y"]) / chord
        offsets = [abs((row["x"] - rows[0]["x"]) * dy - (row["y"] - rows[0]["y"]) * dx)
                   for row in rows]
        add("mean_interval_speed", sum(distances) / elapsed, speed_unit)
        add("max_lateral_deviation", max(offsets), distance_unit)
        add("rms_lateral_deviation", math.sqrt(sum(d * d for d in offsets) / len(offsets)), distance_unit)
        result["mean_speed_scope"] = "DURATION_WEIGHTED_INTERVAL_CHORD_SPEED"
        result["lateral_axis"] = "FIRST_TO_LAST_OBSERVED_POSITION"
    return result


def measure_tracks(tracks, *, coordinate_space, phase_windows=None, start_gate=None,
                   calibration_evidence=None, max_gap_seconds=0.3):
    """Measure experimental candidate phases without filling absent evidence.

    ``phase_windows`` maps string lane numbers to phase names and [start, end]
    media times. Unconfigured phases use conservative geometric candidates:
    sustained cumulative turn, whole-window straightness, and a stable-heading
    observed post-turn exit. These are experimental geometry rules, not field
    validated phase labels. Supplied errors that mask an interval reject it.
    A runup always needs a directionally observed crossing of ``start_gate``
    (``a``, ``b``, ``normal`` two-coordinate vectors in the selected space).
    Invalid samples may carry null coordinates/error; their timestamp, frame
    and scene remain mandatory and preserve an explicit continuity break.
    No points are interpolated into measurement windows. A gate crossing time
    is explicitly a linear estimate between its two observed bracket frames.

    Metres require typed calibration references plus a supplied check for every
    frame used. Their authenticity and physical clock correspondence cannot be
    established by this pure function; all results remain UNVALIDATED.
    """
    _require(coordinate_space in ("REFERENCE_IMAGE_PX", "WATER_PLANE_METRES"), "INVALID_COORDINATE_SPACE")
    _require(_finite(max_gap_seconds) and max_gap_seconds > 0, "INVALID_MAX_GAP_SECONDS")
    tracks = _tracks(tracks)
    windows = _windows(phase_windows, [track["lane"] for track in tracks])
    gate = _gate(start_gate, coordinate_space)
    frame_checks = _calibration(calibration_evidence) if coordinate_space == "WATER_PLANE_METRES" else None
    distance_unit = "m" if frame_checks is not None else "px"
    result = {"schema_version": "RACE_AI_BOAT_VIDEO_MEASUREMENTS_V1", "coordinate_space": coordinate_space,
              "time_basis": "MEDIA_TIMELINE_SECONDS", "model_eligible": False, "validation_status": "UNVALIDATED",
              "identity_validated": False, "candidate_measurements": True,
              "calibration_status": "CONDITIONAL_ON_SUPPLIED_CALIBRATION" if frame_checks is not None else "IMAGE_COORDINATES_ONLY",
              "physical_velocity": "NOT_ESTABLISHED", "lanes": []}
    for track in tracks:
        identity = track.get("identity_status")
        identity = identity if identity in IDENTITIES else "UNRESOLVED"
        lane = {"lane": track["lane"], "identity_status": identity, "identity_validated": False, "phases": {}}
        result["lanes"].append(lane)
        if identity == "UNRESOLVED":
            lane["phases"] = {name: _missing("IDENTITY_UNRESOLVED") for name in PHASES}
            continue
        rows = track["samples"]
        chunks = _segments(rows, max_gap_seconds)
        automatic_turn = _automatic_turn(chunks)
        automatic_straight = _automatic_straight(chunks)
        crossings = _crossings(chunks, gate)
        configured = windows.get(str(track["lane"]), {})
        for name in PHASES:
            source = "CONFIGURED" if name in configured else "AUTOMATIC_CANDIDATE"
            selected = None
            crossing = None
            reason = None
            if name == "runup" and gate is None:
                reason = "START_REFERENCE_REQUIRED"
            elif name == "runup" and not crossings:
                reason = "START_GATE_CROSSING_NOT_OBSERVED"
            elif name in configured:
                start, end = configured[name]
                selected = [row for row in rows if start - 1e-12 <= row["t"] <= end + 1e-12]
                if not rows or rows[0]["t"] > start + 1e-12 or rows[-1]["t"] < end - 1e-12:
                    reason = "INSUFFICIENT_WINDOW_COVERAGE"
            elif name == "turn":
                selected = automatic_turn
            elif name == "straight":
                selected = automatic_straight
            elif name == "exit" and automatic_turn:
                if _quality(automatic_turn, max_gap_seconds, frame_checks):
                    reason = "TURN_PHASE_NOT_RESOLVED"
                else:
                    last = automatic_turn[-1]
                    chunk = next(chunk for chunk in chunks if any(row is last for row in chunk))
                    selected = [row for row in chunk if last["t"] <= row["t"] <= last["t"] + 1.5]
            elif name == "runup":
                crossing = crossings[0]
                selected = [row for row in crossing[1] if crossing[0] - 3 <= row["t"] <= crossing[0] + 1e-12]
            if reason:
                lane["phases"][name] = _missing(reason, source, selected)
                continue
            if selected is None:
                lane["phases"][name] = _missing("PHASE_NOT_OBSERVED", source)
                continue
            reason = _quality(selected, max_gap_seconds, frame_checks)
            if not reason and name == "exit" and name not in configured and not _straight_supported(selected):
                reason = "POST_TURN_HEADING_NOT_STABLE"
            if not reason and name == "runup":
                crossing = crossing or next((c for c in crossings
                    if selected[-1]["t"] <= c[0] + 1e-12 and selected[0]["t"] >= c[0] - 3 - 1e-12
                    and all(any(r is selected_row for r in c[1]) for selected_row in selected)), None)
                if crossing is None:
                    reason = "WINDOW_NOT_BEFORE_OBSERVED_START_CROSSING"
                elif frame_checks is not None and any((selected[0]["scene"], index) not in frame_checks for index in crossing[2]):
                    reason = "CALIBRATION_FRAME_CHECK_MISSING"
            measured = _missing(reason, source, selected) if reason else _measure(name, selected, source, distance_unit)
            if name == "runup" and measured["status"] == "MEASURED":
                measured["gate_crossing_t"] = crossing[0]
                measured["gate_crossing_scope"] = "LINEAR_INTERPOLATION_BETWEEN_OBSERVED_BRACKET_FRAMES"
                measured["gate_crossing_frame_indices"] = list(crossing[2])
            lane["phases"][name] = measured
    return result
