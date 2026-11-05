"""Typed experimental measurements for versions of the existing BOAT models.

This pure adapter checks supplied evidence for internal comparability. Hashes,
reviewer kinds and frame references do not authenticate people, pixels, clocks
or calibration. It never promotes the underlying UNVALIDATED report, assigns a
better/worse direction, normalizes unlike source contexts, or predicts outcomes.
Independent human-held-out validation remains a separate, unsatisfied gate.
"""
from copy import deepcopy
import math
import re

from .actions_contract import digest
from .boat_video_evaluation import _JST, _race_day, _report, _roster, _time
from .boat_video_measurements import measure_tracks


SCHEMA = "RACE_AI_BOAT_VIDEO_MODEL_CONTEXT_V1"
EVIDENCE_SCHEMA = "RACE_AI_BOAT_VIDEO_COMPARISON_EVIDENCE_V1"
# A radius is geometry, not a turn-quality rating. All signs remain untrained.
FEATURE_SCHEMA = (
    ("turn_sampled_radius", "turn", "equivalent_sampled_radius", "px"),
    ("exit_speed_trend", "exit", "sampled_speed_trend", "px/s^2"),
    ("runup_speed_trend", "runup", "sampled_speed_trend", "px/s^2"),
    ("straight_mean_speed", "straight", "mean_interval_speed", "px/s"),
)
FEATURE_IDS = tuple(row[0] for row in FEATURE_SCHEMA)
_ERROR = "BOAT_VIDEO_MODEL_CONTEXT_REJECTED"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_EVIDENCE_FIELDS = {"schema_version", "report_sha256", "media_sha256", "race_id", "cutoff_at",
                    "roster", "created_at", "identities", "comparisons", "heldout_evidence_sha256",
                    "evidence_sha256"}
_IDENTITY_FIELDS = {"lane", "registration_number", "number", "reviewer_kind", "reviewer_id",
                    "method", "track_sha256", "frames"}
_COMPARISON_FIELDS = {"comparison_id", "scene", "frame_indices", "camera_evidence_sha256",
                      "calibration_evidence_sha256", "clock_evidence_sha256", "uncertainty_by_lane"}
_CONTEXT_COMPARISON_FIELDS = _COMPARISON_FIELDS | {"source_pts_seconds", "t_start", "t_end"}
_CONTEXT_FIELDS = set("schema_version race_id cutoff_at as_of report_sha256 media_sha256 evidence_sha256 "
    "source_captured_at analysis_started_at analysis_completed_at evidence_created_at dataset_status "
    "media_duration_seconds "
    "raw_report_validation_status feature_schema coordinate_space time_basis comparison_scope "
    "default_coefficients learned_direction normalization_status identity_reviewer_kinds "
    "identity_evidence_authentication independent_human_heldout_verified heldout_evidence_status "
    "heldout_evidence_sha256 validation_gaps prediction_eligible production_eligible performance_rating "
    "comparisons participants eligible_for_research missing_reasons context_sha256".split())
_CELL_FIELDS = {"feature_id", "phase", "metric_name", "unit", "value", "uncertainty", "status",
                "missing_reason", "comparison_id", "scene", "t_start", "t_end"}


def _need(condition):
    if not condition:
        raise ValueError(_ERROR)


def _sha(value, *, optional=False):
    _need(optional and value is None or type(value) is str and _SHA.fullmatch(value) is not None)


def _nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _evidence(value, report, target_roster):
    _need(type(value) is dict and set(value) == _EVIDENCE_FIELDS)
    value = deepcopy(value)
    _need(value["schema_version"] == EVIDENCE_SCHEMA)
    _sha(value["evidence_sha256"])
    _need(value["evidence_sha256"] == digest({k: v for k, v in value.items() if k != "evidence_sha256"}))
    _need(value["report_sha256"] == report["report_sha256"] and
          value["media_sha256"] == report["source"]["media_sha256"] and
          value["race_id"] == report["race_id"] and value["cutoff_at"] == report["cutoff_at"] and
          _roster(value["roster"]) == target_roster)
    _time(value["created_at"])
    _sha(value["heldout_evidence_sha256"], optional=True)
    identities = value["identities"]
    _need(type(identities) is list and len(identities) == 6)
    tracks = {row["lane"]: row for row in report["tracking"]["tracks"]}
    by_lane, frame_hashes = {}, {}
    for row in identities:
        _need(type(row) is dict and set(row) == _IDENTITY_FIELDS)
        lane = row["lane"]
        _need(type(lane) is int and lane in target_roster and lane not in by_lane and
              type(row["number"]) is int and row["number"] == lane and
              row["registration_number"] == target_roster[lane])
        _need(row["method"] == "INDEPENDENT_HULL_NUMBER_READ" and
              row["reviewer_kind"] in ("HUMAN_MANUAL", "AGENT", "AUTOMATED_DETECTOR") and
              type(row["reviewer_id"]) is str and _LABEL.fullmatch(row["reviewer_id"]) is not None)
        _need(row["track_sha256"] == digest(tracks[lane]))
        frames = row["frames"]
        _need(type(frames) is list and 1 <= len(frames) <= 20000)
        observed = {sample["frame_index"]: sample for sample in tracks[lane]["samples"] if sample["valid"]}
        previous = -1
        for frame in frames:
            _need(type(frame) is dict and set(frame) == {"frame_index", "frame_sha256"})
            index = frame["frame_index"]
            _need(type(index) is int and index > previous and index in observed)
            previous = index
            _sha(frame["frame_sha256"])
            if "frame_sha256" in observed[index]:
                _sha(observed[index]["frame_sha256"])
                _need(frame["frame_sha256"] == observed[index]["frame_sha256"])
            _need(index not in frame_hashes or frame_hashes[index] == frame["frame_sha256"])
            frame_hashes[index] = frame["frame_sha256"]
        by_lane[lane] = row
    _need(set(by_lane) == set(range(1, 7)))
    comparisons = value["comparisons"]
    _need(type(comparisons) is dict and set(comparisons) <= {row[1] for row in FEATURE_SCHEMA})
    for comparison in comparisons.values():
        _need(type(comparison) is dict and set(comparison) == _COMPARISON_FIELDS)
        _need(type(comparison["comparison_id"]) is str and _LABEL.fullmatch(comparison["comparison_id"]) is not None)
        _need(type(comparison["scene"]) is int and comparison["scene"] >= 0)
        indices = comparison["frame_indices"]
        _need(type(indices) is list and 3 <= len(indices) <= 20000 and
              all(type(i) is int and i >= 0 for i in indices) and indices == sorted(set(indices)))
        for key in ("camera_evidence_sha256", "calibration_evidence_sha256", "clock_evidence_sha256"):
            _sha(comparison[key], optional=True)
        uncertainty = comparison["uncertainty_by_lane"]
        _need(type(uncertainty) is dict and set(uncertainty) == set(map(str, range(1, 7))) and
              all(_nonnegative(error) for error in uncertainty.values()))
    return value, by_lane


def _comparison_window(report, comparison):
    """Derive one shared source-PTS interval from the exact six track samples."""
    result = deepcopy(comparison)
    result.update(source_pts_seconds=None, t_start=None, t_end=None)
    common = None
    frame_indices = set(comparison["frame_indices"])
    for track in report["tracking"]["tracks"]:
        rows = [sample for sample in track["samples"] if sample["frame_index"] in frame_indices]
        if ([sample["frame_index"] for sample in rows] != comparison["frame_indices"] or
                not all(sample["valid"] and sample["scene"] == comparison["scene"] for sample in rows)):
            return result
        points = [sample["t"] for sample in rows]
        if common is not None and points != common:
            return result
        common = points
    if common is not None:
        result.update(source_pts_seconds=common, t_start=common[0], t_end=common[-1])
    return result


def _phase_reason(report, identities, phase, comparison):
    if comparison is None:
        return "PAIRED_COMPARISON_EVIDENCE_MISSING"
    for field, reason in (("camera_evidence_sha256", "CAMERA_COMPENSATION_UNVERIFIED"),
                          ("calibration_evidence_sha256", "COMPARISON_CALIBRATION_UNVERIFIED"),
                          ("clock_evidence_sha256", "COMMON_CLOCK_UNVERIFIED")):
        if comparison[field] is None:
            return reason
    if comparison["source_pts_seconds"] is None:
        return "COMMON_FRAME_CONTEXT_MISMATCH"
    tracks = {track["lane"]: track for track in report["tracking"]["tracks"]}
    common_timestamps = None
    for lane in report["measurements"]["lanes"]:
        measurement = lane["phases"][phase]
        if measurement["status"] != "MEASURED":
            return measurement["reason"]
        if (measurement["t_start"], measurement["t_end"]) != (comparison["t_start"], comparison["t_end"]):
            return "NON_COMMON_PHASE_WINDOW"
        rows = [sample for sample in tracks[lane["lane"]]["samples"]
                if measurement["t_start"] - 1e-12 <= sample["t"] <= measurement["t_end"] + 1e-12]
        indices = [sample["frame_index"] for sample in rows]
        timestamps = [sample["t"] for sample in rows]
        if (indices != comparison["frame_indices"] or not all(sample["valid"] and
                sample["scene"] == comparison["scene"] for sample in rows) or
                common_timestamps is not None and timestamps != common_timestamps):
            return "COMMON_FRAME_CONTEXT_MISMATCH"
        common_timestamps = timestamps
        if not set(indices).intersection(frame["frame_index"] for frame in identities[lane["lane"]]["frames"]):
            return "PHASE_NUMBER_EVIDENCE_MISSING"
    return None


def prepare_video_context(report, identity_evidence, *, race_id, cutoff_at, roster, as_of):
    """Return six rows of four raw typed cells, or explicit missing reasons.

    ``identity_evidence`` is a sealed COMPARISON_EVIDENCE_V1 envelope. Its six
    numbered identity rows bind complete tracks and reference frame hashes;
    each phase comparison binds one scene, identical observed frames/times,
    camera/calibration/clock references, and same-unit per-lane error bounds.
    References are declarations, not independently authenticated evidence.

    ``eligible_for_research`` means at least two comparable numeric cells in a
    phase, usable only for experimental versions of existing models. It does
    not grant forecast eligibility or independent human-held-out validation.
    No coefficient, sign, probability, strength or official time is inferred.
    """
    try:
        raw = _report(report)
        target_roster = _roster(roster)
        instant, cutoff = _time(as_of), _time(cutoff_at)
        _need(raw["race_id"] == race_id and raw["cutoff_at"] == cutoff_at and
              _roster(raw["roster"]) == target_roster)
        parameters = raw["analysis_parameters"]
        recomputed = measure_tracks(raw["tracking"]["tracks"], coordinate_space="REFERENCE_IMAGE_PX",
            phase_windows=parameters.get("phase_windows"), start_gate=parameters.get("start_gate"),
            max_gap_seconds=parameters.get("max_gap_seconds", .3))
        _need(digest(recomputed) == digest(raw["measurements"]))
        evidence, identities = (None, {}) if identity_evidence is None else _evidence(identity_evidence, raw, target_roster)
        reason = None
        if instant >= cutoff or not raw["pre_cutoff_available"]:
            reason = "POST_CUTOFF_ONLY"
        elif _time(raw["analysis_completed_at"]) > instant:
            reason = "ANALYSIS_NOT_AVAILABLE_AS_OF"
        elif raw["dataset_status"] == "SYNTHETIC_ONLY":
            reason = "SYNTHETIC_ONLY"
        elif evidence is None:
            reason = "INDEPENDENT_NUMBER_EVIDENCE_MISSING"
        elif _time(evidence["created_at"]) > instant:
            reason = "EVIDENCE_NOT_AVAILABLE_AS_OF"
        elif _time(evidence["created_at"]) < _time(raw["analysis_completed_at"]):
            reason = "EVIDENCE_PRECEDES_ANALYSIS"
        heldout_ref = evidence["heldout_evidence_sha256"] if evidence else None
        comparisons = {phase: _comparison_window(raw, comparison) for phase, comparison in
                       evidence["comparisons"].items()} if evidence else {}
        out = {"schema_version": SCHEMA, "race_id": race_id, "cutoff_at": cutoff_at, "as_of": as_of,
            "report_sha256": raw["report_sha256"], "media_sha256": raw["source"]["media_sha256"],
            "evidence_sha256": evidence["evidence_sha256"] if evidence else None,
            "source_captured_at": raw["source"]["captured_at"],
            "analysis_started_at": raw["analysis_started_at"], "analysis_completed_at": raw["analysis_completed_at"],
            "evidence_created_at": evidence["created_at"] if evidence else None,
            "dataset_status": raw["dataset_status"],
            "media_duration_seconds": raw["tracking"]["duration_seconds"],
            "raw_report_validation_status": raw["validation_status"],
            "feature_schema": [{"feature_id": feature, "phase": phase, "metric_name": metric, "unit": unit}
                               for feature, phase, metric, unit in FEATURE_SCHEMA],
            "coordinate_space": "REFERENCE_IMAGE_PX", "time_basis": "MEDIA_TIMELINE_SECONDS",
            "comparison_scope": "SUPPLIED_COMMON_FRAME_CONTEXT_NOT_FIELD_CERTIFICATION",
            "default_coefficients": dict.fromkeys(FEATURE_IDS, 0.), "learned_direction": "UNTRAINED",
            "normalization_status": "DEFERRED_TO_EXISTING_VERSIONED_TRAINING",
            "identity_reviewer_kinds": sorted({row["reviewer_kind"] for row in identities.values()}),
            "identity_evidence_authentication": "NOT_ESTABLISHED",
            "independent_human_heldout_verified": False,
            "heldout_evidence_status": "REFERENCE_SUPPLIED_NOT_AUTHENTICATED" if heldout_ref else "NOT_SUPPLIED",
            "heldout_evidence_sha256": heldout_ref,
            "validation_gaps": ["INDEPENDENT_HUMAN_HELDOUT_AUTHENTICATION_MISSING" if heldout_ref else
                                "INDEPENDENT_HUMAN_HELDOUT_VALIDATION_MISSING"],
            "prediction_eligible": False, "production_eligible": False, "performance_rating": "NOT_COMPUTED",
            "comparisons": comparisons, "participants": []}
        participants = {lane: {"lane": lane, "registration_number": target_roster[lane], "feature_cells": {}}
                        for lane in range(1, 7)}
        measurements = {lane["lane"]: lane for lane in raw["measurements"]["lanes"]}
        for feature, phase, metric, unit in FEATURE_SCHEMA:
            comparison = comparisons.get(phase)
            phase_reason = reason or _phase_reason(raw, identities, phase, comparison)
            cells = []
            for lane, participant in participants.items():
                measurement = measurements[lane]["phases"][phase]
                cell = {"feature_id": feature, "phase": phase, "metric_name": metric, "unit": unit,
                        "value": None, "uncertainty": None, "status": "MISSING", "missing_reason": phase_reason,
                        "comparison_id": comparison["comparison_id"] if comparison else None,
                        "scene": comparison["scene"] if comparison else None,
                        "t_start": measurement["t_start"], "t_end": measurement["t_end"]}
                participant["feature_cells"][feature] = cell
                cells.append(cell)
                if phase_reason:
                    continue
                metrics = {item["name"]: item for item in measurement["metrics"]}
                _need(metric in metrics and metrics[metric]["unit"] == unit)
                uncertainty = comparison["uncertainty_by_lane"][str(lane)]
                if phase in ("exit", "runup") and "sampled_speed_trend_error_bound" in metrics:
                    bound = metrics["sampled_speed_trend_error_bound"]
                    _need(bound["unit"] == unit and _nonnegative(bound["value"]))
                    uncertainty = max(uncertainty, bound["value"])
                value = metrics[metric]["value"]
                cell["uncertainty"] = uncertainty
                if uncertainty > 0 and uncertainty >= abs(value):
                    cell["missing_reason"] = "MEASUREMENT_UNCERTAINTY_EXCEEDS_SIGNAL"
                else:
                    cell.update(value=value, status="EXPERIMENTAL_COMPARABLE", missing_reason=None)
            if sum(cell["value"] is not None for cell in cells) == 1:
                for cell in cells:
                    if cell["value"] is not None:
                        cell.update(value=None, status="MISSING", missing_reason="INSUFFICIENT_COMPARABLE_PARTICIPANTS")
        out["participants"] = list(participants.values())
        all_cells = [cell for participant in participants.values() for cell in participant["feature_cells"].values()]
        out["eligible_for_research"] = any(cell["value"] is not None for cell in all_cells)
        out["missing_reasons"] = sorted({cell["missing_reason"] for cell in all_cells if cell["missing_reason"]})
        out["context_sha256"] = digest(out)
        return out
    except (KeyError, TypeError, OverflowError, RecursionError, ValueError):
        raise ValueError(_ERROR) from None


def validate_video_context(context, *, race_id, cutoff_at, roster, as_of):
    """Check a sealed context's strict types, target identity and derived claims.

    This verifies structural integrity only. A caller admitting these bytes to
    learning/inference must separately authenticate an external receipt binding
    their exact hash and pre-cutoff availability. For source replay, reconstruct
    with ``prepare_video_context`` from the original report and evidence.
    """
    try:
        _need(type(context) is dict and set(context) == _CONTEXT_FIELDS)
        value = deepcopy(context)
        _sha(value["context_sha256"])
        _need(value["context_sha256"] == digest({k: v for k, v in value.items() if k != "context_sha256"}))
        _need(value["schema_version"] == SCHEMA and value["race_id"] == race_id and
              value["cutoff_at"] == cutoff_at and value["as_of"] == as_of)
        target = _roster(roster)
        instant, cutoff = _time(as_of), _time(cutoff_at)
        day = _race_day(race_id)
        _need(cutoff.astimezone(_JST).date() == day)
        captured, started, completed = (_time(value[key]) for key in
                                        ("source_captured_at", "analysis_started_at", "analysis_completed_at"))
        _need(captured <= started <= completed and captured.astimezone(_JST).date() >= day)
        evidence_at = _time(value["evidence_created_at"]) if value["evidence_created_at"] is not None else None
        for key in ("report_sha256", "media_sha256"):
            _sha(value[key])
        _sha(value["evidence_sha256"], optional=True)
        _sha(value["heldout_evidence_sha256"], optional=True)
        _need(value["raw_report_validation_status"] == "UNVALIDATED" and
              value["prediction_eligible"] is False and value["production_eligible"] is False and
              value["independent_human_heldout_verified"] is False and
              value["identity_evidence_authentication"] == "NOT_ESTABLISHED" and
              value["performance_rating"] == "NOT_COMPUTED" and value["learned_direction"] == "UNTRAINED")
        _need(value["coordinate_space"] == "REFERENCE_IMAGE_PX" and value["time_basis"] == "MEDIA_TIMELINE_SECONDS" and
              value["comparison_scope"] == "SUPPLIED_COMMON_FRAME_CONTEXT_NOT_FIELD_CERTIFICATION" and
              value["normalization_status"] == "DEFERRED_TO_EXISTING_VERSIONED_TRAINING")
        _need(value["feature_schema"] == [{"feature_id": feature, "phase": phase, "metric_name": metric, "unit": unit}
                                        for feature, phase, metric, unit in FEATURE_SCHEMA])
        coefficients = value["default_coefficients"]
        _need(type(coefficients) is dict and set(coefficients) == set(FEATURE_IDS) and
              all(type(weight) in (float, int) and weight == 0 for weight in coefficients.values()))
        kinds = value["identity_reviewer_kinds"]
        _need(type(kinds) is list and kinds == sorted(set(kinds)) and
              all(kind in ("HUMAN_MANUAL", "AGENT", "AUTOMATED_DETECTOR") for kind in kinds))
        has_heldout = value["heldout_evidence_sha256"] is not None
        _need(value["heldout_evidence_status"] == ("REFERENCE_SUPPLIED_NOT_AUTHENTICATED" if has_heldout else "NOT_SUPPLIED") and
              value["validation_gaps"] == ["INDEPENDENT_HUMAN_HELDOUT_AUTHENTICATION_MISSING" if has_heldout else
                                           "INDEPENDENT_HUMAN_HELDOUT_VALIDATION_MISSING"])
        _need(value["dataset_status"] in ("REAL_REPORTED", "SYNTHETIC_ONLY"))
        duration = value["media_duration_seconds"]
        _need(_nonnegative(duration))
        comparisons = value["comparisons"]
        _need(type(comparisons) is dict and set(comparisons) <= {row[1] for row in FEATURE_SCHEMA})
        for comparison in comparisons.values():
            _need(type(comparison) is dict and set(comparison) == _CONTEXT_COMPARISON_FIELDS)
            _need(type(comparison["comparison_id"]) is str and _LABEL.fullmatch(comparison["comparison_id"]) is not None)
            _need(type(comparison["scene"]) is int and comparison["scene"] >= 0)
            indices = comparison["frame_indices"]
            _need(type(indices) is list and 3 <= len(indices) <= 20000 and
                  all(type(i) is int and i >= 0 for i in indices) and indices == sorted(set(indices)))
            points = comparison["source_pts_seconds"]
            if points is None:
                _need(comparison["t_start"] is None and comparison["t_end"] is None)
            else:
                _need(type(points) is list and len(points) == len(indices) and
                      all(_nonnegative(point) and point <= duration for point in points) and
                      all(left < right for left, right in zip(points, points[1:])) and
                      type(comparison["t_start"]) in (int, float) and type(comparison["t_end"]) in (int, float) and
                      comparison["t_start"] == points[0] and comparison["t_end"] == points[-1])
            for key in ("camera_evidence_sha256", "calibration_evidence_sha256", "clock_evidence_sha256"):
                _sha(comparison[key], optional=True)
            errors = comparison["uncertainty_by_lane"]
            _need(type(errors) is dict and set(errors) == set(map(str, range(1, 7))) and
                  all(_nonnegative(error) for error in errors.values()))
        participants = value["participants"]
        _need(type(participants) is list and len(participants) == 6)
        found, reasons, numeric_by_feature = {}, set(), dict.fromkeys(FEATURE_IDS, 0)
        for participant in participants:
            _need(type(participant) is dict and set(participant) == {"lane", "registration_number", "feature_cells"})
            lane = participant["lane"]
            _need(type(lane) is int and lane in target and lane not in found and participant["registration_number"] == target[lane])
            found[lane] = participant["registration_number"]
            cells = participant["feature_cells"]
            _need(type(cells) is dict and set(cells) == set(FEATURE_IDS))
            for feature, phase, metric, unit in FEATURE_SCHEMA:
                cell = cells[feature]
                _need(type(cell) is dict and set(cell) == _CELL_FIELDS and cell["feature_id"] == feature and
                      cell["phase"] == phase and cell["metric_name"] == metric and cell["unit"] == unit)
                comparison = comparisons.get(phase)
                _need(cell["comparison_id"] == (comparison["comparison_id"] if comparison else None) and
                      cell["scene"] == (comparison["scene"] if comparison else None))
                _need(cell["uncertainty"] is None or _nonnegative(cell["uncertainty"]))
                for key in ("t_start", "t_end"):
                    _need(cell[key] is None or _nonnegative(cell[key]) and cell[key] <= duration)
                if cell["value"] is None:
                    _need(cell["status"] == "MISSING" and type(cell["missing_reason"]) is str and
                          _LABEL.fullmatch(cell["missing_reason"]) is not None)
                    reasons.add(cell["missing_reason"])
                    continue
                number = cell["value"]
                _need(type(number) in (float, int) and math.isfinite(number) and
                      cell["status"] == "EXPERIMENTAL_COMPARABLE" and cell["missing_reason"] is None and
                      cell["t_start"] is not None and cell["t_end"] is not None and cell["t_start"] < cell["t_end"] and
                      cell["uncertainty"] is not None and
                      (cell["uncertainty"] == 0 or cell["uncertainty"] < abs(number)))
                _need(phase not in ("turn", "straight") or number >= 0)
                _need(comparison is not None and all(comparison[key] is not None for key in
                    ("camera_evidence_sha256", "calibration_evidence_sha256", "clock_evidence_sha256")))
                _need(comparison["source_pts_seconds"] is not None and
                      (cell["t_start"], cell["t_end"]) == (comparison["t_start"], comparison["t_end"]))
                _need(cell["uncertainty"] >= comparison["uncertainty_by_lane"][str(lane)])
                numeric_by_feature[feature] += 1
        _need(found == target and all(count != 1 for count in numeric_by_feature.values()))
        eligible = any(numeric_by_feature.values())
        _need(type(value["eligible_for_research"]) is bool and value["eligible_for_research"] == eligible and
              value["missing_reasons"] == sorted(reasons))
        if eligible:
            _need(value["dataset_status"] == "REAL_REPORTED" and value["evidence_sha256"] is not None and kinds and
                  evidence_at is not None and completed <= evidence_at <= instant < cutoff)
        return value
    except (KeyError, TypeError, OverflowError, RecursionError, ValueError):
        raise ValueError(_ERROR) from None
