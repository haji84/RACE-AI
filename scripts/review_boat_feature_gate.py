"""Evidence-only independent structural review of BOAT numeric feature requirements.

Uses the pinned PR71 inventory, but does not modify/execute its prediction
logic or pretend model accuracy has been evaluated. The proposed source/tier
classifications are reviewer hypotheses, NOT provider evidence or approval.
"""
from __future__ import annotations

import json

SCHEMA = "RACE_AI_BOAT_FEATURE_GATE_INDEPENDENT_DESIGN_AUDIT_V1"
# Actual B mappings in PR72, imported at runtime to avoid duplicate logic.
SOURCE_CATEGORIES = {
    "ability": ("B_CANDIDATE", "B national win rate / 10; proxy only"),
    "recent_form": ("HISTORICAL_RESULTS_CANDIDATE", "Requires prior dated results and a documented lookback"),
    "start_reliability": ("HISTORICAL_RESULTS_CANDIDATE", "Requires historic valid starts and missing-start handling"),
    "finishing_power": ("HISTORICAL_RESULTS_CANDIDATE", "Requires independently defined historical finish metric"),
    "course_compatibility": ("B_CANDIDATE", "B local win rate / 10; not a lane-specific statistic"),
    "stamina": ("LATENT_UNDEFINED", "No independently defined official direct measurement"),
    "tactical_adaptability": ("LATENT_UNDEFINED", "Requires measured tactical evidence and explicit normalization"),
    "consistency": ("HISTORICAL_RESULTS_CANDIDATE", "Requires a historic variance/dispersion definition"),
    "motor_form": ("B_CANDIDATE", "B motor top-two rate / 100; a proxy"),
    "start_timing": ("HISTORICAL_RESULTS_CANDIDATE", "Requires pre-cutoff historical start-time cohort"),
    "lane_course_fit": ("HISTORICAL_RESULTS_CANDIDATE", "Requires boat-specific lane/course historical samples"),
    "wind_mps": ("METEO_SOURCE_CANDIDATE", "Dated weather observation or forecast, not present in B"),
    "rain_mm_h": ("METEO_SOURCE_CANDIDATE", "Dated weather observation or forecast, not present in B"),
    "humidity_pct": ("METEO_SOURCE_CANDIDATE", "Dated weather observation or forecast, not present in B"),
    "air_temp_c": ("METEO_SOURCE_CANDIDATE", "Dated weather observation or forecast, not present in B"),
    "surface_wetness": ("DERIVED_ENV_CANDIDATE", "Requires measured wetness or documented water-surface semantics"),
    "wave_cm": ("VENUE_MEASUREMENT_CANDIDATE", "Venue-specific measured or forecast wave height at decision time"),
    "water_current_strength": ("VENUE_CONDITIONAL_UNKNOWN", "Hydrodynamics and applicability depend on course"),
    "crosswind_factor": ("DERIVED_ENV_CANDIDATE", "Requires wind direction and relevant course geometry"),
    "tide_activity": ("VENUE_CONDITIONAL_UNKNOWN", "Some venues are not tidally driven; N/A must not equal zero"),
}


class ReviewContractError(ValueError):
    pass


def structural_review(inventory, b_mappings):
    """Review all model-required slots, never infer values or predict."""
    if not isinstance(inventory, dict) or set(inventory) < {
        "common_required", "sport_required", "environment_required"
    }:
        raise ReviewContractError("pinned model inventory unavailable")
    groups = (
        ("common_required", tuple(inventory["common_required"])),
        ("boat_required", tuple(inventory["sport_required"])),
        ("environment_required", tuple(inventory["environment_required"])),
    )
    if any(not values or len(values) != len(set(values)) for _, values in groups):
        raise ReviewContractError("duplicate or missing keys in model inventory")
    all_names = [name for _, names in groups for name in names]
    if len(set(all_names)) != len(all_names) or set(all_names) != set(SOURCE_CATEGORIES):
        raise ReviewContractError("model inventory changed; re-review exact fields before approval")
    if not isinstance(b_mappings, (tuple, list)) or any(len(x) != 5 for x in b_mappings):
        raise ReviewContractError("B feature mapping schema drift")
    mapped = [x[1] for x in b_mappings]
    if len(set(mapped)) != len(mapped) or set(mapped) != {
        key for key, (category, _) in SOURCE_CATEGORIES.items() if category == "B_CANDIDATE"
    }:
        raise ReviewContractError("actual B converter and audit disagree")
    rows = []
    for group, names in groups:
        for name in names:
            category, assessment = SOURCE_CATEGORIES[name]
            rows.append({
                "key": name,
                "current_contract": "HARD_REQUIRED",
                "group": group,
                "source_route_hypothesis": category,
                "source_evidence_admitted": False,
                "required_for_predictive_accuracy_proven": False,
                "suggested_change": (
                    "TEST_OPTIONAL_IN_NEW_MODEL_VERSION" if category != "B_CANDIDATE"
                    else "VERIFY_PROVENANCE_BEFORE_B_BASELINE_EXPERIMENT"
                ),
                "review_reason": assessment,
            })
    runner_count = len(groups[0][1]) + len(groups[1][1])
    environment_count = len(groups[2][1])
    per_race = 6 * runner_count + environment_count
    b_candidate_slots = 6 * len(mapped)
    return {
        "schema": SCHEMA,
        "review_nature": "INDEPENDENT_CODE_CONTRACT_AUDIT_NOT_SEPARATE_AI",
        "policy_status": "PROPOSAL_ONLY_NO_MODEL_CHANGE",
        "boat_participants": 6,
        "distinct_required_keys": len(all_names),
        "required_runner_keys_per_participant": runner_count,
        "required_environment_keys_per_race": environment_count,
        "required_slots_per_race": per_race,
        "distinct_uncovered_by_B_keys": len(all_names) - len(mapped),
        "B_candidate_keys": mapped,
        "B_candidate_slots_per_race": b_candidate_slots,
        "B_absent_candidate_slots_per_race": per_race - b_candidate_slots,
        "validated_actual_race_inputs_available": False,
        "numeric_required_model_version_changed": False,
        "model_inference_tested_by_review": False,
        "model_accuracy_change_proven": False,
        "blocking_risks": [
            "CURRENT_VALIDATE_REJECTS_ANY_MISSING_RUNNER_REQUIRED_KEY",
            "CURRENT_VALIDATE_REJECTS_ANY_MISSING_ENVIRONMENT_REQUIRED_KEY",
            "CURRENT_UTILITY_DIRECTLY_INDEXES_REQUIRED_FEATURES_AND_ENV",
            "CURRENT_OBSERVATION_REQUIRES_SAMPLE_N_EVEN_FOR_INSTANTANEOUS_WEATHER",
            "B_ONLY_DOES_NOT_PROVE_PUBLISHED_AT_SAMPLE_N_RIGHTS_OR_PRE_CUTOFF_CAPTURE",
            "NO_EMPIRICAL_ABLATION_OR_PROSPECTIVE_MODEL_COMPARISON",
        ],
        "feature_reviews": rows,
    }


def main():
    """Requires pinned PR71 model checkout; safe aggregate output only."""
    from pathlib import Path
    import sys
    here = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(here))
    import race_ai
    model_ref = here / "pr71-feature-review-reference" / "race_ai"
    if not (model_ref / "comprehensive_four_sport_models.py").is_file():
        raise ReviewContractError("pinned PR71 model checkout missing")
    race_ai.__path__.append(str(model_ref))
    from race_ai.comprehensive_four_sport_models import feature_inventory
    from race_ai.boat_b_feature_bridge import MAPPING
    audit = structural_review(feature_inventory("boat"), MAPPING)
    # Do not pretend proposed source routes or reviewed statuses are measured.
    print(json.dumps(audit, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
