"""Six-phase scoring overlay for the EXISTING PR71 + video evidence pipelines.

This module does not forecast races, detect riders in pixels, fetch sources,
create training labels, or replace the existing result/video PDCA engines.
It accepts a private, before-cutoff PR71-bound sidecar and separately reviewed
frames from the existing PR102 clip admission; missing vision is UNKNOWN.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import math
import os
import re

PHASE_SCHEMA = "RACE_AI_KEIRIN_PR71_PHASE_FORECAST_V1"
SCORE_SCHEMA = "RACE_AI_KEIRIN_PHASE_COMPARISON_V1"
ADMISSION_SCHEMA = "RACE_AI_KEIRIN_CLIP_TRAINING_ADMISSION_V1"
STAGES = (("INITIAL", 10), ("BELL", 15), ("FINAL_HOME", 15),
          ("FINAL_BACK", 20), ("FOURTH_CORNER", 15), ("GOAL", 25))
PARTS = (("leader", 25), ("top3", 35), ("line_groups", 15),
         ("second_wheel", 15), ("attack", 10))
KNOWN_PR71 = frozenset((
    "multisport-factor-interaction-v1",
    "multisport-scenario-ensemble-v1",
    "multisport-conditional-duel-v1",
    "multisport-race-trajectory-v1",
))
ATTACKS = frozenset(("NIGE", "MAKURI", "SASHI", "MAKURI_SASHI",
                     "LINE_SPLIT", "POSITION_GAIN", "OTHER"))
UNKNOWN = "UNKNOWN"
HEX = re.compile(r"^[a-f0-9]{64}$")
RACE = re.compile(r"^\d{12}$")


class PhaseError(ValueError):
    pass


def need(value, code):
    if not value:
        raise PhaseError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def valid_sha(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def when(value):
    need(type(value) is str, "TIMESTAMP_REQUIRED")
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PhaseError("INVALID_TIMESTAMP") from None
    need(t.utcoffset() is not None, "TIMEZONE_REQUIRED")
    return t.astimezone(timezone.utc)


def car(value):
    return type(value) is int and 1 <= value <= 9


def checked_parts(parts):
    """Require every slot explicitly, with UNKNOWN rather than inferred zero."""
    need(type(parts) is dict and set(parts) == {key for key, _ in PARTS},
         "PHASE_FIELDS_INCOMPLETE")
    for key in ("leader", "second_wheel"):
        need(car(parts[key]) or parts[key] == UNKNOWN,
             "INVALID_PHASE_RIDER")
    order = parts["top3"]
    need(order == UNKNOWN or
         (type(order) is list and len(order) == 3 and
          all(car(x) for x in order) and len(set(order)) == 3),
         "INVALID_PHASE_TOP3")
    lines = parts["line_groups"]
    if lines != UNKNOWN:
        need(type(lines) is list and len(lines) > 0 and len(lines) <= 9,
             "INVALID_PHASE_LINES")
        used = []
        for line in lines:
            need(type(line) is list and 1 <= len(line) <= 9 and
                 all(car(x) for x in line), "INVALID_PHASE_LINES")
            used.extend(line)
        need(len(used) == len(set(used)), "DUPLICATE_RIDER_IN_LINES")
    attack = parts["attack"]
    if attack != UNKNOWN:
        need(type(attack) is dict and set(attack) == {
            "rider", "kind", "success"} and car(attack["rider"]) and
            attack["kind"] in ATTACKS and type(attack["success"]) is bool,
            "INVALID_PHASE_ATTACK")
    return parts


def checked_forecast(doc):
    need(type(doc) is dict and set(doc) == {
        "schema", "race_id", "model_id", "parent_prediction_sha256",
        "pre_race_input_sha256", "parent_saved_at", "frozen_at",
        "official_cutoff_at", "stage_predictions", "phase_forecast_sha256"},
        "INVALID_PHASE_FORECAST_SCHEMA")
    need(doc["schema"] == PHASE_SCHEMA, "UNKNOWN_PHASE_FORECAST_VERSION")
    need(type(doc["race_id"]) is str and RACE.fullmatch(doc["race_id"]),
         "INVALID_RACE_ID")
    need(doc["model_id"] in KNOWN_PR71, "EXISTING_PR71_MODEL_REQUIRED")
    for field in ("parent_prediction_sha256", "pre_race_input_sha256"):
        need(valid_sha(doc[field]), "PARENT_OR_INPUT_SHA_REQUIRED")
    parent = when(doc["parent_saved_at"])
    frozen = when(doc["frozen_at"])
    cutoff = when(doc["official_cutoff_at"])
    need(parent <= frozen and (cutoff - frozen).total_seconds() >= 65,
         "MISSING_PRE_CUTOFF_PHASE_FREEZE")
    stages = doc["stage_predictions"]
    need(type(stages) is dict and set(stages) == {key for key, _ in STAGES},
         "ALL_SIX_STAGES_REQUIRED")
    for entry in stages.values():
        checked_parts(entry)
    before = {key: val for key, val in doc.items()
              if key != "phase_forecast_sha256"}
    need(valid_sha(doc["phase_forecast_sha256"]) and
         doc["phase_forecast_sha256"] == digest(before),
         "PHASE_FORECAST_TAMPERED")
    return doc


def build_phase_forecast(*, race_id, model_id, parent_prediction_sha256,
                         pre_race_input_sha256, parent_saved_at,
                         official_cutoff_at, stage_predictions, clock):
    """Prepare an append-only PRIVATE sidecar. Does not assert model authority.

    Caller must obtain stage hypotheses from existing trusted PR71 research
    inference BEFORE cutoff. Never reconstruct them from post-race footage.
    """
    need(callable(clock), "TRUSTED_CLOCK_REQUIRED")
    now = clock()
    need(isinstance(now, datetime) and now.utcoffset() is not None,
         "AWARE_RUNNER_CLOCK_REQUIRED")
    doc = {
        "schema": PHASE_SCHEMA,
        "race_id": race_id,
        "model_id": model_id,
        "parent_prediction_sha256": parent_prediction_sha256,
        "pre_race_input_sha256": pre_race_input_sha256,
        "parent_saved_at": parent_saved_at,
        "frozen_at": now.isoformat(),
        "official_cutoff_at": official_cutoff_at,
        "stage_predictions": stage_predictions,
    }
    doc["phase_forecast_sha256"] = digest(doc)
    return checked_forecast(doc)


def freeze_private_once(path, doc):
    """No overwrite, no symlinks; return byte SHA after independent disk read."""
    checked_forecast(doc)
    p = Path(path)
    need(p.parent.is_dir() and not p.parent.is_symlink() and
         not p.exists() and not p.is_symlink(), "PRIVATE_FREEZE_PATH_UNSAFE_OR_EXISTS")
    payload = (canonical(doc) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(p, flags, 0o600)
    except OSError:
        raise PhaseError("PRIVATE_PHASE_FREEZE_FAILED") from None
    with os.fdopen(fd, "wb") as sink:
        sink.write(payload)
        sink.flush()
        os.fsync(sink.fileno())
    need(p.read_bytes() == payload, "PRIVATE_PHASE_READBACK_CHANGED")
    return sha256(payload).hexdigest()


def checked_admission(admission, race_id):
    """Consume the digest-bound EXISTING PR102 video clip admission report."""
    need(type(admission) is dict and
         admission.get("schema") == ADMISSION_SCHEMA and
         admission.get("race_id") == race_id and
         valid_sha(admission.get("recording_sha256")) and
         valid_sha(admission.get("admission_sha256")),
         "EXISTING_VIDEO_ADMISSION_REQUIRED")
    before = {key: val for key, val in admission.items()
              if key != "admission_sha256"}
    need(digest(before) == admission["admission_sha256"],
         "VIDEO_ADMISSION_TAMPERED")
    need(admission.get("admitted_coverage") in (
         "NONE", "PARTIAL_HIGHLIGHTS", "FULL_FOUR_LAPS") and
         admission.get("source_kind") in (
         "WINTICKET_PAST_REPLAY", "WINTICKET_LIVE",
         "AUTHORIZED_OTHER", "SYNTHETIC_FIXTURE"),
         "INVALID_VIDEO_ADMISSION")
    dur = admission.get("duration_s")
    need(type(dur) in (int, float) and math.isfinite(dur) and
         10 <= dur <= 14400, "INVALID_VIDEO_DURATION")
    need(type(admission.get("reviewed_scene_frames")) is list,
         "REVIEWED_VIDEO_FRAMES_REQUIRED")
    when(admission.get("reviewed_at"))
    return admission


def checked_observation(obs, admission):
    need(type(obs) is dict and set(obs) == {
        "phase", "recording_sec", "scene", "frame_sha256",
        "review_refs", "measured"}, "INVALID_PHASE_OBSERVATION")
    need(obs["phase"] in {key for key, _ in STAGES},
         "INVALID_OBSERVED_PHASE")
    need(type(obs["recording_sec"]) in (int, float) and
         math.isfinite(obs["recording_sec"]) and
         0 <= obs["recording_sec"] <= admission["duration_s"],
         "INVALID_OBSERVED_TIME")
    need(obs["scene"] in ("LIVE", "REPLAY", "UNKNOWN"),
         "INVALID_OBSERVED_SCENE")
    need(type(obs["frame_sha256"]) is list and
         2 <= len(obs["frame_sha256"]) <= 12 and
         all(valid_sha(x) for x in obs["frame_sha256"]) and
         len(set(obs["frame_sha256"])) == len(obs["frame_sha256"]),
         "INDEPENDENT_FRAME_PAIRS_REQUIRED")
    need(type(obs["review_refs"]) is list and
         len(obs["review_refs"]) == len(obs["frame_sha256"]) and
         all(type(x) is str and len(x) >= 6 for x in obs["review_refs"]),
         "INDEPENDENT_REVIEW_REFERENCES_REQUIRED")
    checked_parts(obs["measured"])
    # Every scored frame must already exist in the PR102 independently
    # reviewed scene receipt. The phase model cannot invent frame hashes.
    receipt = {(x.get("frame_sha256"), x.get("review_ref")): x
               for x in admission["reviewed_scene_frames"]
               if type(x) is dict}
    for frame, ref in zip(obs["frame_sha256"], obs["review_refs"]):
        need((frame, ref) in receipt, "PHASE_FRAME_NOT_IN_VIDEO_ADMISSION")
        matched = receipt[frame, ref]
        frame_time = matched.get("time_s")
        need(type(frame_time) in (int, float) and math.isfinite(frame_time) and
             abs(frame_time - obs["recording_sec"]) <= 5,
             "PHASE_FRAME_TIME_NOT_ATTESTED")
        if obs["scene"] == "LIVE":
            need(matched.get("label") != "REPLAY",
                 "REPLAY_FRAME_CANNOT_PROVE_LIVE_PHASE")
    return obs


def _match(key, proposed, measured):
    if key == "top3":
        return sum(x == y for x, y in zip(proposed, measured)) / 3
    return float(proposed == measured)


def _confirmed(cb, *args):
    if not callable(cb):
        return False
    try:
        return cb(*args) is True
    except Exception:
        return False


def score_six_phases(forecast, admission, observations, *,
                     visual_verifier=None, frozen_original_verifier=None,
                     rights_verifier=None, official_result=None,
                     official_result_verifier=None,
                     prospective_window_verifier=None):
    """Score only attested visual components. No model learning or mutation.

    The independent callbacks must check actual private recording bytes,
    frame provenance, forecast original, and provider rights, not metadata flags
    supplied by this function's caller. Synthetic fixtures never go formal.
    """
    checked_forecast(forecast)
    checked_admission(admission, forecast["race_id"])
    need(type(observations) is list and len(observations) <= 6,
         "INVALID_STAGE_OBSERVATION_BATCH")
    need(when(admission["reviewed_at"]) >= when(forecast["official_cutoff_at"]),
         "POST_RACE_VIDEO_REVIEW_REQUIRED")
    by_stage = {}
    used = set()
    prev = -1.0
    phase_position = {name: i for i, (name, _) in enumerate(STAGES)}
    previous_phase_position = -1
    for obs in observations:
        checked_observation(obs, admission)
        need(obs["phase"] not in by_stage, "DUPLICATE_STAGE_OBSERVATION")
        need(phase_position[obs["phase"]] > previous_phase_position,
             "STAGES_NOT_IN_PHASE_ORDER")
        previous_phase_position = phase_position[obs["phase"]]
        need(obs["recording_sec"] > prev, "STAGES_NOT_IN_VIDEO_TIME_ORDER")
        prev = obs["recording_sec"]
        for frame in obs["frame_sha256"]:
            need(frame not in used, "DUPLICATE_STAGE_FRAME")
            used.add(frame)
        by_stage[obs["phase"]] = obs

    synthetic = admission["source_kind"] == "SYNTHETIC_FIXTURE"
    owner_rights = _confirmed(rights_verifier, admission, "private_keirin_phase_scoring")
    video_allowed = (synthetic or (
        admission.get("training_eligible") is True and
        admission["admitted_coverage"] != "NONE" and owner_rights))
    original_ok = _confirmed(frozen_original_verifier, forecast)
    # Reuse the existing live_15min_proof gate via a trusted caller. The
    # SHA/clock in this sidecar alone is NOT an external schedule receipt.
    prospective_ok = _confirmed(prospective_window_verifier, forecast)
    result_ok = False
    official_order = None
    if official_result is not None:
        need(type(official_result) is dict and
             official_result.get("race_id") == forecast["race_id"] and
             valid_sha(official_result.get("source_result_sha256")),
             "OFFICIAL_RESULT_SOURCE_REQUIRED")
        order = official_result.get("ordered_top3")
        need(type(order) is list and len(order) == 3 and
             len(set(order)) == 3 and all(car(i) for i in order),
             "INVALID_OFFICIAL_RESULT")
        need(when(official_result.get("published_at")) >
             when(forecast["official_cutoff_at"]),
             "POST_CUTOFF_OFFICIAL_RESULT_REQUIRED")
        official_order = order
        result_ok = _confirmed(official_result_verifier, official_result)

    observed_weight = 0.0
    comparable_weight = 0.0
    scored_weight = 0.0
    stages = []
    missed = []
    accepted_visual = {}
    for phase, weight in STAGES:
        obs = by_stage.get(phase)
        visual = (bool(obs) and obs["scene"] == "LIVE" and
                  video_allowed and _confirmed(visual_verifier, obs, admission))
        accepted_visual[phase] = bool(visual)
        proposed = forecast["stage_predictions"][phase]
        measures = obs["measured"] if visual else None
        possible, comparable, scored = 0.0, 0.0, 0.0
        outcomes = {}
        for key, share in PARTS:
            portion = weight * share / 100
            if measures is None or measures[key] == UNKNOWN:
                outcomes[key] = "UNKNOWN"
                continue
            possible += portion
            if proposed[key] == UNKNOWN:
                outcomes[key] = "FORECAST_UNKNOWN"
                continue
            comparable += portion
            fraction = _match(key, proposed[key], measures[key])
            scored += portion * fraction
            outcomes[key] = ("MATCH" if fraction == 1 else
                             "PARTIAL" if fraction > 0 else "MISS")
            if fraction != 1:
                missed.append({"phase": phase, "component": key,
                               "outcome": outcomes[key]})
        observed_weight += possible
        comparable_weight += comparable
        scored_weight += scored
        stages.append({
            "phase": phase, "maximum_points": weight,
            "status": "VERIFIED_VISUAL_COMPONENTS" if visual else "UNKNOWN",
            "verified_observation_points": round(possible, 6),
            "comparable_points": round(comparable, 6),
            "earned_points": round(scored, 6),
            "component_outcomes": outcomes,
        })

    goal_conflict = (result_ok and accepted_visual["GOAL"] and
                     by_stage["GOAL"]["measured"]["top3"] != UNKNOWN and
                     by_stage["GOAL"]["measured"]["top3"] != official_order)
    formal = (not synthetic and video_allowed and original_ok and
              prospective_ok and result_ok and comparable_weight > 0 and
              not goal_conflict)
    if goal_conflict:
        status = "HOLD_GOAL_VIDEO_OFFICIAL_RESULT_CONFLICT"
    elif not comparable_weight:
        status = "HOLD_NO_INDEPENDENTLY_COMPARABLE_PHASES"
    elif formal:
        status = "FORMAL_INPUT_ATTESTED_RESEARCH_SCORE"
    else:
        status = "RESEARCH_SCORE_ONLY_NOT_FORMAL"
    result = {
        "schema": SCORE_SCHEMA,
        "race_id": forecast["race_id"],
        "model_id": forecast["model_id"],
        "parent_prediction_sha256": forecast["parent_prediction_sha256"],
        "phase_forecast_sha256": forecast["phase_forecast_sha256"],
        "recording_sha256": admission["recording_sha256"],
        "video_admission_sha256": admission["admission_sha256"],
        "source_result_sha256": (official_result["source_result_sha256"]
                                 if official_result is not None else None),
        "status": status,
        "weight_total": 100,
        "visual_observation_coverage_pct": round(observed_weight, 3),
        "comparison_coverage_pct": round(comparable_weight, 3),
        "earned_points_out_of_100_possible": round(scored_weight, 3),
        "accuracy_on_comparable_components_pct": (
            round(100 * scored_weight / comparable_weight, 3)
            if comparable_weight > 0 else None),
        "phases": stages,
        "missed_component_candidates": missed,
        "independent_frozen_original_attested": original_ok,
        "independent_prospective_window_attested": prospective_ok,
        "independent_video_rights_attested": bool(owner_rights and not synthetic),
        "official_result_independently_attested": result_ok,
        "formal_evaluation_inputs_attested": formal,
        "unverified_video_never_scores_zero": True,
        "missing_predictions_never_score_full": True,
        "learning_candidate_only": True,
        "model_parameters_updated": False,
        "official_accuracy_or_roi_updated": False,
        "automatic_model_promotion": False,
        "source_outcome_used_as_pre_race_input": False,
    }
    result["comparison_sha256"] = digest(result)
    return result
