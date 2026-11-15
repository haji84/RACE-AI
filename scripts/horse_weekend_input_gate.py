"""Read-only JRA registration-stage readiness and four-model execution gate.

No HTTP access, external-source rights bypass, fabricated feature values,
new prediction model, auto-bet, source re-publication, or trigger creation.
"""
from __future__ import annotations

HORSE_REQUIRED = (
    "ability", "recent_form", "start_reliability", "finishing_power",
    "course_compatibility", "stamina", "tactical_adaptability", "consistency",
    "speed_figure", "closing_sectional", "jockey_fit", "distance_surface_fit"
)
HORSE_ENV = (
    "wind_mps", "rain_mm_h", "humidity_pct", "air_temp_c", "surface_wetness",
    "going_wetness", "course_cushion", "rail_position", "pace_pressure"
)
EXISTING_FOUR = (
    "multisport-factor-interaction-v1",
    "multisport-scenario-ensemble-v1",
    "multisport-conditional-duel-v1",
    "multisport-race-trajectory-v1",
)


def inspect_registered_audit(audit: dict) -> dict:
    """Inspect a private staged registration audit without inventing horse data.

    This deliberately does not promote an external index or a raw finish rank
    into any of the twelve normalized RACE-AI feature observations.
    """
    if not isinstance(audit, dict) or not isinstance(audit.get("races"), list):
        raise ValueError("registration audit with races[] required")
    seen = set()
    rows = []
    for race in audit["races"]:
        key = race["race_key"]
        if key in seen:
            raise ValueError("duplicate race")
        seen.add(key)
        horses = race.get("runners", [])
        eligible = [h for h in horses if not
                    h.get("eligibility", "").startswith("excluded")]
        missing_by_horse = {}
        for h in eligible:
            real = h.get("verified_RACE_AI_model_features") or {}
            missing_by_horse[h["horse_name"]] = [
                f for f in HORSE_REQUIRED if f not in real
            ]
        meta = race.get("model_input_race") or {}
        environmental_missing = [
            f for f in HORSE_ENV if f in
            meta.get("required_environment_fields_unfilled", HORSE_ENV)
        ]
        reasons = []
        if not meta.get("final_draw_verified"):
            reasons.append("OFFICIAL_DRAW_UNCONFIRMED")
        if not meta.get("sales_cutoff_at_verified"):
            reasons.append("OFFICIAL_CUTOFF_UNCONFIRMED")
        if environmental_missing:
            reasons.append("ENVIRONMENT_REQUIRED_MISSING")
        if any(missing_by_horse.values()):
            reasons.append("HORSE_REQUIRED_FEATURES_MISSING")
        if key == "kyoto_jump":
            reasons.append("JUMP_FEATURES_NOT_SUPPORTED_BY_FLAT_MODEL")
        rows.append({
            "race_key": key, "race_name": race["race_name"],
            "registered": len(horses), "projected_not_final": len(eligible),
            "per_horse_missing_features": missing_by_horse,
            "missing_env": environmental_missing,
            "missing_feature_count": sum(map(len, missing_by_horse.values())),
            "can_execute_4_models": not reasons, "reasons": reasons,
        })
    return {
        "schema": "HORSE_REGISTERED_SOURCE_PREFLIGHT_V1",
        "existing_models": list(EXISTING_FOUR),
        "registration_not_final": True,
        "actual_forecasts_created": 0,
        "races": rows
    }


def execute_native_four(snapshot: dict, *, allow_source=None,
                        discipline: str = "flat") -> dict:
    """Call unchanged existing 4-model suite only after real-source gates pass.

    Research scopes require an independent provider-authorization callback;
    an empty/missing callback can never be treated as approved.
    A returned native suite is uncalibrated research, not a certified win
    probability or an independently timestamped frozen prediction.
    """
    reasons = []
    if discipline != "flat":
        reasons.append("UNVALIDATED_JUMPING_DISCIPLINE")
    race = snapshot.get("race") if isinstance(snapshot, dict) else None
    if not isinstance(race, dict):
        reasons.append("RACE_RECORD_MISSING")
        race = {}
    if race.get("sport") != "horse":
        reasons.append("WRONG_SPORT")
    if not race.get("sales_cutoff_at") or not race.get("as_of"):
        reasons.append("AS_OF_OR_CUTOFF_MISSING")
    env = snapshot.get("environment") if isinstance(snapshot, dict) else None
    if not isinstance(env, dict):
        env = {}
    for k in HORSE_ENV:
        if k not in env:
            reasons.append("ENV_MISSING:" + k)
    entrants = snapshot.get("participants") if isinstance(snapshot, dict) else None
    if not isinstance(entrants, list) or not entrants:
        entrants = []
        reasons.append("PARTICIPANTS_MISSING")
    for h in entrants:
        if not isinstance(h, dict):
            reasons.append("INVALID_PARTICIPANT")
            continue
        name = str(h.get("identity", "UNKNOWN_HORSE"))
        if h.get("number") is None or h.get("draw") is None:
            reasons.append("FINAL_DRAW_MISSING:" + name)
        features = h.get("features") or {}
        for k in HORSE_REQUIRED:
            if k not in features:
                reasons.append("REQUIRED_MISSING:" + name + ":" + k)
    if snapshot.get("scope") != "SYNTHETIC_ONLY" and not callable(allow_source):
        reasons.append("INDEPENDENT_SOURCE_AUTHORISER_MISSING")
    if reasons:
        return {"status": "NO_FORECAST", "reasons": reasons,
                "model_count": 0, "official_prediction": False}

    from race_ai.comprehensive_four_sport_models import (
        COMMON_REQUIRED, SPORT_REQUIRED, ENV_COMMON, ENV_SPORT
    )
    from race_ai.four_sport_model_suite import (
        ALL_MODELS, run_suite, verify_suite
    )
    if (tuple(COMMON_REQUIRED) + tuple(SPORT_REQUIRED["horse"]) != HORSE_REQUIRED
            or tuple(ENV_COMMON) + tuple(ENV_SPORT["horse"]) != HORSE_ENV
            or tuple(ALL_MODELS) != EXISTING_FOUR):
        raise RuntimeError("MODEL_CONTRACT_VERSION_MISMATCH")
    suite = run_suite(snapshot, allow_source=allow_source)
    if not verify_suite(suite):
        raise RuntimeError("NATIVE_OUTPUT_SHA_VERIFICATION_FAILED")
    return {
        "status": "RESEARCH_UNCALIBRATED_NOT_PROVEN",
        "model_count": len(EXISTING_FOUR),
        "input_sha256": suite["input_sha256"],
        "suite_sha256": suite["suite_sha256"],
        "official_prediction": False,
        "calibrated_win_probabilities": None,
        "market_expected_value": None,
        "top8_by_model": {
            k: suite["models"][k]["ordered_top8"] for k in EXISTING_FOUR
        },
        "native_suite": suite,
    }
