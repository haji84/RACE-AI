"""Independent AUTORACE baseline for personally observed pre-race figures.

This *pure* observed-only reference does not call providers, use official AI
predictions, fabricate unavailable required features, learn coefficients,
or claim true win probabilities. The static weights are heuristic assumptions.
Manual observation is not proof of first publication or immutable cutoff time.
The existing full-feature four-sport models remain separate and unchanged.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
import itertools
import math
from urllib.parse import urlsplit

from .comprehensive_four_sport_models import digest
from .autorace_ab_pdca import PHASES, SCHEMA as FORECAST_SCHEMA

SOURCE_SCHEMA = "RACE_AI_AUTORACE_PERSONAL_OBSERVED_V1"
MODEL_ID = "autorace-personal-observed-baseline-v1"
MODEL_VERSION = "0.1.0-HEURISTIC-UNTRAINED"
JST = timezone(timedelta(hours=9))
RACE_FIELDS = {
    "race_id", "venue", "race_no", "event_date_jst", "sales_cutoff_at",
    "as_of_at", "phase", "source_url", "source_captured_at"
}
DRIVER_FIELDS = {
    "car_no", "handicap_m", "recent_finishes", "trial_seconds", "trial_observed_at"
}


class ObservedInputError(ValueError):
    pass


def _need(ok, why):
    if not ok:
        raise ObservedInputError(why)


def _time(value):
    _need(type(value) is str, "OFFSET_AWARE_TIME_REQUIRED")
    try:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(value.utcoffset() is not None, "OFFSET_AWARE_TIME_REQUIRED")
        return value
    except ValueError:
        raise ObservedInputError("INVALID_TIME") from None


def _source(url):
    _need(type(url) is str and 1 <= len(url) <= 1024, "SOURCE_URL_REQUIRED")
    try:
        p = urlsplit(url)
        _need(p.scheme == "https" and bool(p.hostname) and p.username is None
              and p.password is None and p.port is None and not p.fragment,
              "SOURCE_URL_INVALID")
    except ValueError:
        raise ObservedInputError("SOURCE_URL_INVALID") from None


def _check(snapshot, generated_at):
    _need(type(snapshot) is dict and set(snapshot) == {
        "schema", "entry_kind", "race", "drivers"}, "SNAPSHOT_SCHEMA")
    _need(snapshot["schema"] == SOURCE_SCHEMA and
          snapshot["entry_kind"] == "USER_OBSERVED_MANUAL", "NOT_MANUAL_OBSERVATION")
    race = snapshot["race"]
    _need(type(race) is dict and set(race) == RACE_FIELDS, "RACE_SCHEMA")
    phase = race["phase"]
    _need(phase in PHASES, "PHASE")
    _need(type(race["race_id"]) is str and 8 <= len(race["race_id"]) <= 200,
          "RACE_ID")
    _need(type(race["venue"]) is str and bool(race["venue"]), "VENUE")
    _need(type(race["race_no"]) is int and 1 <= race["race_no"] <= 12,
          "RACE_NUMBER")
    _source(race["source_url"])
    try:
        day = date.fromisoformat(race["event_date_jst"])
        _need(day.isoformat() == race["event_date_jst"], "EVENT_DAY")
    except (TypeError, ValueError):
        raise ObservedInputError("EVENT_DAY") from None
    cutoff, as_of, capture, generated = (
        _time(race["sales_cutoff_at"]), _time(race["as_of_at"]),
        _time(race["source_captured_at"]), _time(generated_at)
    )
    _need(cutoff.astimezone(JST).date() == day, "RACE_DAY_CUTOFF_MISMATCH")
    # A local clock/capture time is only a research claim. Keep 2-minute
    # guard against knowingly late snapshots and never backdate generated_at.
    _need(capture <= as_of <= generated and
          generated + timedelta(minutes=2) < cutoff, "AFTER_CUTOFF_OR_CAPTURE")
    drivers = snapshot["drivers"]
    _need(type(drivers) is list and 3 <= len(drivers) <= 8, "CAR_COUNT")
    ids = []
    for d in drivers:
        _need(type(d) is dict and set(d) == DRIVER_FIELDS, "DRIVER_SCHEMA")
        car = d["car_no"]
        _need(type(car) is int and 1 <= car <= 8, "CAR_NUMBER")
        ids.append(car)
        _need(type(d["handicap_m"]) is int and
              0 <= d["handicap_m"] <= 200 and d["handicap_m"] % 10 == 0,
              "HANDICAP_NOT_OBSERVED")
        recent = d["recent_finishes"]
        _need(type(recent) is list and 3 <= len(recent) <= 10 and
              all(type(n) is int and 1 <= n <= 8 for n in recent),
              "RECENT_RESULTS_MISSING")
        trial, observed = d["trial_seconds"], d["trial_observed_at"]
        if phase == PHASES[0]:
            _need(trial is None and observed is None,
                  "TRIAL_CANNOT_ENTER_PRE_TRIAL_INPUT")
        else:
            _need(type(trial) in (int, float) and
                  math.isfinite(trial) and 3.0 <= trial <= 4.5,
                  "COMPLETE_TRIAL_REQUIRED")
            _need(observed is not None and
                  capture <= _time(observed) <= as_of,
                  "TRIAL_CAPTURE_TIME_REQUIRED")
    _need(len(set(ids)) == len(ids), "DUPLICATE_CAR")
    return sorted(ids), race, generated


def predict_personal(snapshot, *, generated_at):
    """Full ordered-trifecta rank with 8 fixed + 4 *experimental* extras.

    Only handicap, actual prior finish positions and participant-bound trial
    seconds influence ranks. More evidence-rich models may outperform this
    untrained baseline; no accuracy guarantee or calibration is implied.
    """
    ids, race, generated = _check(snapshot, generated_at)
    pre = race["phase"] == PHASES[0]
    drivers = {x["car_no"]: x for x in snapshot["drivers"]}
    trials = [x["trial_seconds"] for x in drivers.values()] if not pre else []
    min_trial, max_trial = (min(trials), max(trials)) if trials else (None, None)
    utility = {}
    for car in ids:
        d = drivers[car]
        # 1st = 1.0, 8th = .125. Observed finish values only.
        recent = math.fsum((9 - pos)/8 for pos in d["recent_finishes"])
        recent /= len(d["recent_finishes"])
        # Fixed explicit engineering assumptions, NOT learned coefficients.
        score = 1.20 * recent - .01*d["handicap_m"]
        if not pre:
            # Relative same-race trial performance. Ties add no preference.
            relative = ((max_trial - d["trial_seconds"]) /
                        (max_trial - min_trial)) if max_trial > min_trial else 0.0
            score += .90 * relative
        utility[car] = score
    # Plackett-Luce selection without replacement. These are mathematical
    # relative weights, NOT verified chances of a winning combination.
    weights = {car: math.exp(utility[car]) for car in ids}
    total = math.fsum(weights.values())
    first = {k: weights[k] / total for k in ids}
    rows = []
    for a, b, c in itertools.permutations(ids, 3):
        w = weights
        v = first[a] * w[b] / (total - w[a])
        v *= w[c] / (total - w[a] - w[b])
        rows.append({"combination": [a,b,c], "relative_weight": v})
    rows.sort(key=lambda x: (-x["relative_weight"], x["combination"]))
    z = math.fsum(row["relative_weight"] for row in rows)
    _need(math.isfinite(z) and abs(z-1) < 1e-9, "INVALID_RANKING_WEIGHTS")
    base = [r["combination"] for r in rows[:8]]
    extra = [r["combination"] for r in rows[8:12]]
    forecast = {
        "schema": FORECAST_SCHEMA,
        "record_type": "PERSONAL_MANUAL_RESEARCH_FORECAST",
        "race_id": race["race_id"], "venue": race["venue"], "race_no": race["race_no"],
        "phase": race["phase"], "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "generated_at": generated.isoformat(), "as_of": race["as_of_at"],
        "cutoff_at": race["sales_cutoff_at"],
        "entrants": ids, "input_sha256": digest(snapshot),
        "source_url": race["source_url"],
        "source_capture_kind": "USER_OBSERVED_MANUAL",
        "source_first_publication_verified": False,
        "ordered_top8": base, "supplemental_four": extra,
        "candidate_count": len(rows), "ranked_relative_weights": rows,
        "estimated_probabilities_calibrated": False,
        "supplemental_four_counts_towards_hit_at_8": False,
        "external_pre_cutoff_receipt": None, "formal_hit_at_8_eligible": False,
        "official_prediction": False, "purchase_decision": "NO_BET",
    }
    forecast["prediction_sha256"] = digest(forecast)
    return forecast


def preview_personal_result(forecast, result, *, observed_at):
    """Unverified personal comparison, never a formal Hit@8 measurement.

    Result input is intentionally separate from the pre-race prediction. Caller
    must independently verify official results and receipts for formal metrics.
    """
    _need(type(forecast) is dict and
          forecast.get("record_type") == "PERSONAL_MANUAL_RESEARCH_FORECAST" and
          forecast.get("prediction_sha256") == digest({
            k:v for k,v in forecast.items() if k!="prediction_sha256"}),
          "FORECAST_NOT_INTACT")
    _need(type(result) is dict and set(result) == {
        "race_id","winning_order","source_url","captured_at"}, "RESULT_SCHEMA")
    _source(result["source_url"])
    _need(result["race_id"] == forecast["race_id"], "RESULT_RACE_MISMATCH")
    _need(_time(forecast["cutoff_at"]) <
          _time(result["captured_at"]) <= _time(observed_at),
          "RESULT_PRE_CUTOFF_OR_CLOCK_INVALID")
    triple = result["winning_order"]
    _need(type(triple) is list and len(triple) == 3 and
          all(type(n) is int and n in forecast["entrants"] for n in triple)
          and len(set(triple)) == 3, "WINNING_ORDER_INVALID")
    base, extra = forecast["ordered_top8"], forecast["supplemental_four"]
    n = len(forecast["entrants"])
    expected = min(8, n*(n-1)*(n-2))
    _need(len(base) == expected and len(extra) == min(4, n*(n-1)*(n-2)-expected) and
          len({tuple(v) for v in base+extra}) == len(base+extra),
          "PICK_COUNT_OR_DUPLICATION")
    return {
        "schema": "RACE_AI_AUTORACE_PERSONAL_PREVIEW_V1",
        "race_id": forecast["race_id"], "phase": forecast["phase"],
        "model_id": forecast["model_id"],
        "prediction_sha256": forecast["prediction_sha256"],
        "result_input_sha256": digest(result),
        "hit1_personal": int(triple == base[0]),
        "hit8_personal": int(triple in base),
        "hit12_personal_experimental": int(triple in base+extra),
        "formal_hit_at_8_eligible": False,
        "external_receipt_verified": False,
        "official_result_independently_verified": False,
        "classification": "USER_RECORDED_UNVERIFIED_RESEARCH",
    }
