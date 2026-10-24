"""Separate, sparse BOAT trifecta RESEARCH shadow models (NOT PR71 FULL).

No networking, storage, odds, results, betting, learned coefficients or
production authorization. Every present input needs chronological evidence.
Absent optional features are explicit states, not manufactured zeroes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
import math
import re

LITE_ID = "boat-b-lite-v1-untrained"
ENRICHED_ID = "boat-enriched-v1-untrained"
SCHEMA = "RACE_AI_BOAT_SPARSE_EVIDENCED_RESEARCH_V1"
SYNTHETIC = "SYNTHETIC_ONLY"
RESEARCH = "OPERATOR_SUPPLIED_RESEARCH"
CORE = ("ability", "course_compatibility", "motor_form")
EXTRA = ("recent_form", "start_reliability", "finishing_power", "consistency",
         "start_timing", "lane_course_fit", "wind_response", "wave_response")
ENVIRONMENT = ("wind_mps", "wave_cm")
MISSING = ("MISSING", "NOT_YET_PUBLISHED", "NOT_APPLICABLE",
           "RIGHTS_BLOCKED", "SOURCE_UNAVAILABLE")
KINDS = ("aggregate_stat", "instantaneous", "forecast", "derived")
BASE_WEIGHTS = {"ability": 1.35, "course_compatibility": .85, "motor_form": .95}
EXTRA_WEIGHTS = {"recent_form": 1.05, "start_reliability": .4,
                 "finishing_power": .75, "consistency": .4,
                 "start_timing": .62, "lane_course_fit": .75,
                 "wind_response": .12, "wave_response": .12}
JST = timezone(timedelta(hours=9))
RACE_ID = re.compile(r"boat:(\d{4}-\d\d-\d\d):boatrace-jcd-(0[1-9]|1\d|2[0-4]):([1-9]|1[0-2])\Z")
FORBIDDEN = ("odds", "payout", "dividend", "market", "popularity",
             "actual_finish", "race_result", "winning", "確定", "人気", "配当")


class SparseModelError(ValueError):
    pass


def _exact(obj, keys, label):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise SparseModelError(label + " unexpected/missing field")


def _stamp(x):
    if not isinstance(x, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", x
    ):
        raise SparseModelError("exact offset-aware timestamp required")
    try:
        out = datetime.fromisoformat(x.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SparseModelError("invalid date/time") from exc
    if out.utcoffset() is None:
        raise SparseModelError("naive time")
    return out


def _number(x, lo=0, hi=1):
    if type(x) not in (int, float) or not math.isfinite(x) or not lo <= x <= hi:
        raise SparseModelError("missing/invalid numeric observation")
    return float(x)


def _evidence(item, key, *, asof, scope, allow_source, is_environment=False):
    _exact(item, {"value", "published_at", "captured_at", "valid_for_at",
                  "source_ref", "source_rights_ref", "transform_id",
                  "sample_n", "observation_kind"}, "feature observation")
    if any(token in key.lower() for token in FORBIDDEN):
        raise SparseModelError("market or result data not permitted")
    limits = {"wind_mps": (0, 40), "wave_cm": (0, 250)}
    value = _number(item["value"], *(limits.get(key, (0, 1))))
    publish, capture = _stamp(item["published_at"]), _stamp(item["captured_at"])
    if not publish <= capture <= asof:
        raise SparseModelError("observation not known by forecast as_of")
    kind = item["observation_kind"]
    if kind not in KINDS:
        raise SparseModelError("observation_kind invalid")
    n = item["sample_n"]
    if kind in ("aggregate_stat", "derived"):
        if type(n) is not int or not 1 <= n <= 10_000_000:
            raise SparseModelError("historical aggregate sample_n not proven")
    elif n is not None:
        raise SparseModelError("instantaneous/forecast must not invent a sample_n")
    if kind == "forecast":
        valid_for = _stamp(item["valid_for_at"])
        if valid_for < publish:
            raise SparseModelError("forecast target precedes issuance")
    elif item["valid_for_at"] is not None:
        raise SparseModelError("only forecasts have valid_for_at")
    for field in ("source_ref", "source_rights_ref", "transform_id"):
        x = item[field]
        if not isinstance(x, str) or not 1 <= len(x) <= 256:
            raise SparseModelError("source, rights or transform evidence absent")
    if scope == RESEARCH:
        if not item["source_ref"].startswith("https://"):
            raise SparseModelError("research source URL must be HTTPS")
        if allow_source is None or allow_source(
            item["source_ref"], item["source_rights_ref"], "analysis"
        ) is not True:
            raise SparseModelError("source purpose rights unverified")
    if is_environment and kind == "aggregate_stat":
        # Aggregates can be used but their provenance must still be explicit.
        pass
    return value


def validate_snapshot(snapshot, *, allow_source=None):
    """Strict source/time checks; does NOT attest real rights or freeze."""
    _exact(snapshot, {"schema", "scope", "race", "participants", "environment"}, "snapshot")
    if snapshot["schema"] != SCHEMA or snapshot["scope"] not in (SYNTHETIC, RESEARCH):
        raise SparseModelError("unrecognized snapshot scope")
    race = snapshot["race"]
    _exact(race, {"race_id", "venue", "event_date_jst", "as_of", "scheduled_cutoff_at",
                  "distance_m", "race_revision"}, "race")
    match = RACE_ID.fullmatch(race["race_id"]) if isinstance(race["race_id"], str) else None
    if match is None or match.group(1) != race["event_date_jst"]:
        raise SparseModelError("race ID/date inconsistency")
    if race["venue"] != "boatrace-jcd-" + match.group(2):
        raise SparseModelError("race ID/venue inconsistency")
    asof, cutoff = _stamp(race["as_of"]), _stamp(race["scheduled_cutoff_at"])
    if asof >= cutoff or cutoff.astimezone(JST).date().isoformat() != race["event_date_jst"]:
        raise SparseModelError("race as_of must be before declared scheduled cutoff")
    _number(race["distance_m"], 100, 10000)
    if type(race["race_revision"]) is not int or race["race_revision"] < 1:
        raise SparseModelError("race revision missing")
    participants = snapshot["participants"]
    if not isinstance(participants, list) or len(participants) != 6:
        raise SparseModelError("exactly six boat participants required")
    prepared = {}
    for p in participants:
        _exact(p, {"number", "registration_no", "features", "missing"}, "participant")
        number = p["number"]
        if type(number) is not int or not 1 <= number <= 6 or number in prepared:
            raise SparseModelError("invalid duplicate lane")
        racer = p["registration_no"]
        if not isinstance(racer, str) or not re.fullmatch(r"\d{4}", racer):
            raise SparseModelError("invalid racer registration ID")
        features, missing = p["features"], p["missing"]
        if not isinstance(features, dict) or not isinstance(missing, dict):
            raise SparseModelError("feature/missing maps required")
        if not set(CORE) <= set(features) or set(features) - set(CORE + EXTRA):
            raise SparseModelError("missing core or forbidden participant feature")
        if set(missing) != set(EXTRA) - set(features) or any(v not in MISSING for v in missing.values()):
            raise SparseModelError("missing reason required for each absent optional feature")
        values = {key: _evidence(v, key, asof=asof, scope=snapshot["scope"],
                    allow_source=allow_source) for key, v in features.items()}
        prepared[number] = {"number": number, "registration_no": racer,
                            "values": values, "missing": missing}
    if len({p["registration_no"] for p in prepared.values()}) != 6:
        raise SparseModelError("repeated racer registration")
    env = snapshot["environment"]
    _exact(env, {"features", "missing"}, "environment")
    if not isinstance(env["features"], dict) or not isinstance(env["missing"], dict):
        raise SparseModelError("environment values/missing maps required")
    if (set(env["features"]) - set(ENVIRONMENT)
        or set(env["missing"]) != set(ENVIRONMENT) - set(env["features"])
        or any(v not in MISSING for v in env["missing"].values())):
        raise SparseModelError("environment missing or prohibited keys")
    environment = {key: _evidence(v, key, asof=asof, scope=snapshot["scope"],
                   allow_source=allow_source, is_environment=True)
                   for key, v in env["features"].items()}
    return {"race": race, "participants": prepared, "environment": environment,
            "environment_missing": env["missing"]}


def _distribution(strengths):
    total = math.fsum(strengths.values())
    if total <= 0:
        raise SparseModelError("zero model strength")
    candidates = []
    for a, b, c in itertools.permutations(range(1, 7), 3):
        a_val, b_val, c_val = strengths[a], strengths[b], strengths[c]
        value = (a_val / total *
                 b_val / (total - a_val) *
                 c_val / (total - a_val - b_val))
        candidates.append(((a, b, c), value))
    denom = math.fsum(v for _, v in candidates)
    return sorted(((t, v / denom) for t, v in candidates),
                  key=lambda v: (-v[1], v[0]))


def _stable_hash(data):
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _forecast(model_id, snapshot, prepared, *, weights, used_optional, used_environment=()):
    strength = {}
    for lane, row in prepared["participants"].items():
        values = row["values"]
        weighted = math.fsum(weights[key] * values[key] for key in weights)
        # A common set of present optional keys is used across all 6 boats.
        # No absent per-boat feature is filled with zero or a synthetic mean.
        score = weighted / math.fsum(weights.values())
        strength[lane] = math.exp(2.0 * score)
    ranking = _distribution(strength)
    model_output = {
        "schema": "RACE_AI_BOAT_SPARSE_SHADOW_OUTPUT_V1",
        "scope": snapshot["scope"],
        "model_id": model_id,
        "model_version": "0.1.0-UNTRAINED",
        "race_id": snapshot["race"]["race_id"],
        "as_of": snapshot["race"]["as_of"],
        "scheduled_cutoff_at": snapshot["race"]["scheduled_cutoff_at"],
        "input_sha256": _stable_hash(snapshot),
        "trained": False,
        "calibrated": False,
        "official_prediction": False,
        "external_pre_cutoff_receipt": None,
        "official_result": None,
        "purchase_decision": "NO_BET",
        "odds_independent": True,
        "confidence_level": "UNVERIFIED",
        "used_optional_keys": sorted(used_optional),
        "used_environment_keys": sorted(used_environment),
        "excluded_incomplete_optional_keys": sorted(set(EXTRA) - set(used_optional)),
        "missing_optional_reasons_by_lane": {
            str(lane): dict(sorted(row["missing"].items()))
            for lane, row in sorted(prepared["participants"].items())
        },
        "missing_environment_reasons": snapshot["environment"]["missing"],
        "candidate_count": len(ranking),
        "candidates": [{"combination": list(ticket), "score": score}
                       for ticket, score in ranking],
        "ordered_top8": [list(ticket) for ticket, _ in ranking[:8]],
        "probability_calibration_status": "NOT_VALIDATED_DO_NOT_REPORT_AS_CALIBRATED",
        "result_or_cutoff_proof_eligible": False
    }
    model_output["prediction_sha256"] = _stable_hash(model_output)
    return model_output


def predict_shadow_pair(snapshot, *, allow_source=None):
    """Only research/synthetic forecasts; never a live officially frozen ticket.

    Lite = three source-backed B-compatible scores.
    Enriched = same baseline plus *fully observed* optional participant keys.
    A partial optional participant key is excluded for every lane with an
    explicit quality warning instead of imputing the missing entries.
    """
    prepared = validate_snapshot(snapshot, allow_source=allow_source)
    entries = prepared["participants"]
    lite = _forecast(LITE_ID, snapshot, prepared, weights=BASE_WEIGHTS,
                     used_optional=())
    eligible_extra = [
        key for key in EXTRA
        if all(key in entries[lane]["values"] for lane in range(1, 7))
    ]
    excluded_partial = [
        key for key in EXTRA
        if any(key in entries[lane]["values"] for lane in range(1, 7))
        and key not in eligible_extra
    ]
    if eligible_extra:
        weights = dict(BASE_WEIGHTS)
        weights.update({key: EXTRA_WEIGHTS[key] for key in eligible_extra})
        observed_environment = prepared["environment"]
        used_environment = []
        # Meteorological context only modifies a genuinely observed, per-boat
        # resilience signal. It never substitutes a missing resilience score.
        if "wind_response" in eligible_extra and "wind_mps" in observed_environment:
            weights["wind_response"] += .35 * min(1, observed_environment["wind_mps"] / 20)
            used_environment.append("wind_mps")
        if "wave_response" in eligible_extra and "wave_cm" in observed_environment:
            weights["wave_response"] += .35 * min(1, observed_environment["wave_cm"] / 60)
            used_environment.append("wave_cm")
        enriched = _forecast(ENRICHED_ID, snapshot, prepared, weights=weights,
                             used_optional=eligible_extra, used_environment=used_environment)
        enriched["excluded_partially_observed_keys"] = sorted(excluded_partial)
        enriched["prediction_sha256"] = _stable_hash(
            {k: v for k, v in enriched.items() if k != "prediction_sha256"}
        )
    else:
        enriched = {
            "model_id": ENRICHED_ID, "race_id": snapshot["race"]["race_id"],
            "status": "NO_FORECAST_NO_COMPLETE_ENRICHMENT",
            "ordered_top8": None, "official_prediction": False,
            "external_pre_cutoff_receipt": None,
            "excluded_partially_observed_keys": sorted(excluded_partial),
            "prediction_sha256": None,
        }
    return {"schema": "RACE_AI_BOAT_SHADOW_PAIR_V1",
            "research_only": True, "formal_hit_at_8_eligible": False,
            "primary_model_id": LITE_ID, "lite": lite, "enriched": enriched}
