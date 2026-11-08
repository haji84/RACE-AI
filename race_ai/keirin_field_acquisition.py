"""Separate *collectable source facts* from calculated and conditional items.

The 347/437 checklist consists of field checks, NOT 347 publicly obtainable
independent raw facts. A scenario is a model hypothesis, not a web data field.
"""
from __future__ import annotations

from collections import Counter

from .keirin_preflight import RACE_ITEMS, RIDER_ITEMS, expected_keys

RACE_HYPOTHESIS = frozenset({
    "line_competition_and_lead_candidates",
    "early_position_scenarios",
    "front_race_and_breakaway_scenarios",
    "late_attack_scenarios",
    "line_break_and_mixed_finish_scenarios",
    "same_day_lane_or_style_bias",
})
RACE_DERIVED = frozenset({
    "track_weather_effect_history",
    "venue_distance_style_effect",
})
RACE_CONDITIONAL = frozenset({
    "track_surface_and_condition", "surface_wetness",
    "wind_speed", "wind_direction", "rainfall",
    "air_temperature", "humidity", "race_formation_comments",
})
RIDER_DERIVED = frozenset({
    "opponent_strength_adjustment",
    "recent_strength_or_form_change",
    "lead_attempt_and_success",
    "makuri_attempt_and_success",
    "sashi_attempt_and_success",
    "last_lap_acceleration",
    "front_positioning_preference",
    "bank_positioning_and_traffic",
    "stamina_and_pace_resilience",
    "second_rider_tracking_and_pass",
    "third_rider_tracking_and_gap",
    "teammate_pair_history",
    "same_line_three_way_history",
    "direct_head_to_head",
    "opponent_style_matchup",
    "venue_and_distance_compatibility",
    "wind_and_surface_compatibility",
    "start_or_line_reliability",
    "position_flexibility_and_solo_behavior",
})
RIDER_CONDITIONAL = frozenset({
    "recent_race_video_observations",
    "injury_illness_and_recovery",
    "absence_reason_and_return_state",
    "athlete_comments_and_intent",
    "equipment_or_mechanical_issues",
    "rest_days_and_fatigue",
    "gear_ratio_and_changes",
})


def kind(key):
    parts = key.split("/")
    if len(parts) == 2 and parts[0] == "race" and parts[1] in RACE_ITEMS:
        k = parts[1]
        if k in RACE_HYPOTHESIS:
            return "forecast_hypothesis_not_raw_data"
        if k in RACE_DERIVED:
            return "derived_only_with_prior_evidence"
        if k in RACE_CONDITIONAL:
            return "source_available_only_if_published_at_race_time"
        return "pre_race_source_fact"
    if (len(parts) == 3 and parts[0] == "rider" and
            parts[1].isdigit() and int(parts[1]) in range(1,10) and
            parts[2] in RIDER_ITEMS):
        k = parts[2]
        if k in RIDER_DERIVED:
            return "derived_only_with_prior_evidence"
        if k in RIDER_CONDITIONAL:
            return "source_available_only_if_published_at_race_time"
        return "pre_race_source_fact"
    raise ValueError("UNKNOWN_KEIRIN_FIELD")


def acquisition_summary(starters):
    """Exact count of key types, not a claim that values are available."""
    keys = expected_keys(starters)
    grouped = Counter(kind(key) for key in keys)
    return {
        "schema": "RACE_AI_KEIRIN_FIELD_ACQUISITION_TYPES_V1",
        "checked_items": len(keys),
        "categories": dict(sorted(grouped.items())),
        "every_field_is_public": False,
        "every_field_can_be_fetched": False,
        "source_rights_independently_confirmed": False,
    }
