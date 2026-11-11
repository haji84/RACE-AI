"""Only invented source observations are used. No licensed provider claimed."""
import copy
from hashlib import sha256
import unittest

from race_ai.keirin_allowed_delivery import (
    DELIVERY_SCHEMA, ENV_MAP, RIDER_MAP, RIDER_MAP_DISTINCT_B,
    DISTINCT_B_ID, PermittedDeliveryError,
    assemble_permitted_pre_race,
)
from race_ai.keirin_preflight import expected_keys
from race_ai.comprehensive_four_sport_models import (
    feature_inventory, validate as model_validate,
)
from race_ai.four_sport_model_suite import run_suite, verify_suite
from race_ai.keirin_pr71_model_adapter import run_pr71_for_next_race

RID = "keirin:2030-01-15:fictional-venue:1"
AS_OF = "2030-01-15T09:10:00+09:00"
CHECKED = "2030-01-15T09:15:00+09:00"
ISSUED = "2030-01-15T09:20:00+09:00"
CUTOFF = "2030-01-15T10:00:00+09:00"
NAMES = {n: "fictional-rider-%d" % n for n in range(1, 8)}
STARTERS = list(NAMES)
FAKE = "https://example.invalid/fake-permitted-fixture"
REF = "FAKE_LICENSE_NOT_FOR_REAL_WORLD"


def fixture(full=True):
    model_source_keys = (
        {"race/" + origin for origin, _ in ENV_MAP.values()} |
        {"rider/%d/%s" % (n, origin) for n in STARTERS
         for origin, _ in RIDER_MAP.values()}
    )
    obs = []
    for key in expected_keys(STARTERS):
        if not full and key not in model_source_keys and not (
            key.startswith("race/") and key.split("/")[1] in {
                "race_id_date_venue_no", "event_grade_and_class",
                "race_stage", "advancement_and_points_rules",
                "race_distance", "official_sales_cutoff",
                "all_entrants_and_vehicle_numbers",
                "late_scratches_substitutions_revisions",
                "line_order_all_riders", "line_roles_and_solo_riders",
                "source_access_permission_and_asof", "start_time",
            }
        ) and not (key.startswith("rider/") and key.endswith(
            ("/identity_number_and_grade", "/last_3_races_rank_and_rivals",
             "/athlete_comments_and_intent", "/line_leader_or_follow_role",
             "/style_mark")
        )):
            continue
        if key == "race/race_id_date_venue_no":
            value = {"race_id": RID, "event_date_jst": "2030-01-15",
                     "venue": "fictional-venue"}
        elif key == "race/official_sales_cutoff": value = CUTOFF
        elif key == "race/race_distance": value = 2000
        elif key == "race/all_entrants_and_vehicle_numbers":
            value = [{"number": n, "identity": NAMES[n]} for n in STARTERS]
        elif key == "race/late_scratches_substitutions_revisions":
            value = {"race_revision": 1, "active_numbers": STARTERS}
        elif key == "race/line_order_all_riders":
            value = {"lines": [{"group_id": "L1", "order": [1, 2, 3]},
                               {"group_id": "L2", "order": [4, 5, 6]}],
                     "solos": [7]}
        elif key.endswith("/identity_number_and_grade"):
            n = int(key.split("/")[1])
            value = {"number": n, "identity": NAMES[n], "grade": "fixture"}
        elif key == "race/wind_speed": value = 3
        elif key == "race/rainfall": value = 0
        elif key == "race/air_temperature": value = 20
        elif key == "race/humidity": value = 40
        elif key.endswith("/race_score"): value = 78
        elif key.endswith(("/start_S_count", "/home_H_count", "/back_B_count")):
            value = 4
        elif key in model_source_keys: value = 0.6
        else: value = "fictional fixture observation"
        obs.append({
            "key": key, "value": value, "source_url": FAKE,
            "rights_ref": REF, "published_at": "2030-01-15T08:00:00+09:00",
            "captured_at": "2030-01-15T08:05:00+09:00", "sample_n": 10,
        })
    return {
        "schema": DELIVERY_SCHEMA,
        "race": {
            "race_id": RID, "venue": "fictional-venue",
            "event_date_jst": "2030-01-15",
            "race_kind": "fictional qualifying",
            "race_revision": 1, "distance_m": 2000, "as_of": AS_OF,
            "official_cutoff_at": CUTOFF, "permission_ref": REF,
            "starters": [
                {"number": n, "identity": NAMES[n],
                 "style": ("front", "stalker", "closer", "allround")[n % 4],
                 "group_id": ("L1" if n <= 3 else "L2" if n <= 6 else None)}
                for n in STARTERS
            ],
        }, "observations": obs
    }


def granted(*args):
    return True


def assemble(value, grant=granted):
    return assemble_permitted_pre_race(
        value, grant_check=grant, checked_at=CHECKED
    )


class AllowedFeedTests(unittest.TestCase):
    def test_all_347_observations_and_existing_model_receive_values(self):
        out = assemble(fixture(full=True))
        status = out["status"]
        self.assertEqual(status["checked_count"], 347)
        self.assertEqual(status["verified_items"], 347)
        self.assertEqual(status["unavailable_items"], 0)
        self.assertEqual(status["model_inputs_generated"], 205)
        self.assertGreater(status["verified_audit_only_items"], 0)
        self.assertEqual(
            status["verified_audit_only_items"] +
            status["unique_verified_source_items_consumed"], 347
        )
        self.assertEqual(status["state"],
                         "PRIVATE_PR71_INPUT_READY_RIGHTS_AND_FREEZE_STILL_EXTERNAL")
        self.assertEqual(status["model_status"], "READY_NOT_EXECUTED")
        self.assertFalse(status["rights_certified_by_this_module"])
        self.assertEqual(status["network_requests"], 0)
        snap = out["private_snapshot"]
        self.assertEqual(len(snap["facts"]["keirin_pre_race_audit_v1"]["items"]),347)
        evidence = snap["facts"]["pr71_evidenced_snapshot"]
        # Source rights stub returns True ONLY for an obviously fake fixture.
        approved = model_validate(evidence, allow_source=lambda *_: True)
        self.assertEqual(approved["sport"], "keirin")
        for p in evidence["participants"]:
            fields = set(p["features"])
            self.assertTrue(set(feature_inventory("keirin")["common_required"]) <= fields)
            self.assertTrue(set(feature_inventory("keirin")["sport_required"]) <= fields)
        self.assertEqual(set(evidence["environment"]),
                         set(feature_inventory("keirin")["environment_required"]))
        # This is the ACTUAL existing untrained PR71 model implementation.
        actual = run_pr71_for_next_race(
            snap, run_suite=run_suite, verify_suite=verify_suite,
            source_admission=lambda *_: True,
            model_id="multisport-scenario-ensemble-v1", issued_at=ISSUED
        )
        self.assertEqual(actual["race_id"], RID)
        self.assertEqual(len(actual["top8"]), 8)
        self.assertFalse(actual["trained"])
        self.assertTrue(len(out["consumed_feature_origins"]) > 80)

    def test_every_field_inspected_but_missing_is_not_zero(self):
        out = assemble(fixture(full=False))
        self.assertEqual(out["status"]["checked_count"], 347)
        self.assertGreater(out["status"]["unavailable_items"], 0)
        self.assertEqual(out["status"]["missing_model_inputs"], [])
        self.assertIsNotNone(out["private_snapshot"])
        self.assertEqual(out["private_snapshot"]["facts"][
            "keirin_pre_race_audit_v1"]["items"][0]["key"],
            "race/race_id_date_venue_no")

    def test_missing_critical_suppresses_model_snapshot(self):
        data = fixture()
        data["observations"] = [o for o in data["observations"]
                                if o["key"] != "race/line_order_all_riders"]
        out = assemble(data)
        self.assertIsNone(out["private_snapshot"])
        self.assertIn("race/line_order_all_riders",
                      out["status"]["unverified_critical_keys"])

    def test_missing_required_model_input_suppresses_snapshot(self):
        data = fixture()
        data["observations"] = [o for o in data["observations"]
                                if o["key"] != "rider/1/race_score"]
        out = assemble(data)
        self.assertIsNone(out["private_snapshot"])
        self.assertIn("rider/1/ability", out["status"]["missing_model_inputs"])

    def test_rights_not_self_certified_from_bundle(self):
        out = assemble(fixture(), grant=lambda *_: False)
        self.assertIsNone(out["private_snapshot"])
        self.assertEqual(out["status"]["verified_items"], 0)
        self.assertEqual(out["audit"]["items"][0]["status"], "rights_blocked")

    def test_late_data_marked_stale(self):
        data = fixture()
        data["observations"][0]["captured_at"] = "2030-01-15T09:20:00+09:00"
        out = assemble(data)
        self.assertIsNone(out["private_snapshot"])
        self.assertEqual(out["audit"]["items"][0]["status"], "stale")

    def test_line_topology_mismatch_never_reaches_model(self):
        data = fixture()
        row = next(x for x in data["observations"]
                   if x["key"] == "race/line_order_all_riders")
        row["value"]["lines"][0]["order"] = [1, 2, 4]
        with self.assertRaisesRegex(PermittedDeliveryError,
                                    "LINE_GROUP_DISAGREEMENT"):
            assemble(data)

    def test_changed_roster_rejected(self):
        data = fixture()
        data["race"]["starters"][0]["identity"] = "forged"
        with self.assertRaisesRegex(PermittedDeliveryError,
                                    "SOURCE_ENTRANT_LIST_DISAGREEMENT"):
            assemble(data)

    def test_changed_cutoff_rejected(self):
        data = fixture()
        row = next(x for x in data["observations"]
                   if x["key"] == "race/official_sales_cutoff")
        row["value"] = "2030-01-15T10:30:00+09:00"
        with self.assertRaisesRegex(PermittedDeliveryError,
                                    "RACE_SOURCE_TIMING_OR_DISTANCE_MISMATCH"):
            assemble(data)

    def test_odds_and_outcomes_rejected_even_as_extra_source(self):
        data = fixture()
        data["observations"][0]["value"] = {"odds": 3.1}
        with self.assertRaises(ValueError):
            assemble(data)

    def test_duplicate_source_key_rejected(self):
        data = fixture()
        data["observations"].append(copy.deepcopy(data["observations"][0]))
        with self.assertRaisesRegex(PermittedDeliveryError, "TOO_MANY"):
            assemble(data)

    def test_uncapped_competition_scores_are_monotone_and_reach_model(self):
        # The user requested no hard ceiling, including >100, >200.
        previous = -1
        for points in (0, 79.25, 100, 121.33, 200, 201, 999.99, 1000000):
            with self.subTest(points=points):
                data = fixture()
                row = next(o for o in data["observations"]
                           if o["key"] == "rider/1/race_score")
                row["value"] = points
                result = assemble(data)
                self.assertIsNotNone(result["private_snapshot"])
                participant = next(p for p in result["private_snapshot"]["facts"][
                    "pr71_evidenced_snapshot"]["participants"]
                    if p["number"] == 1)
                numeric = participant["features"]["ability"]["value"]
                self.assertAlmostEqual(numeric, points / (points + 100))
                self.assertEqual(
                    participant["features"]["ability"]["transform_id"],
                    "keirin-audit-score_open_v2-v1")
                self.assertGreater(numeric, previous)
                self.assertLess(numeric, 1)
                previous = numeric

    def test_no_score_maximum_even_large_integer(self):
        data = fixture()
        row = next(o for o in data["observations"]
                   if o["key"] == "rider/1/race_score")
        row["value"] = 10 ** 100
        result = assemble(data)
        self.assertIsNotNone(result["private_snapshot"])
        self.assertEqual(
            next(p for p in result["private_snapshot"]["facts"][
                "pr71_evidenced_snapshot"]["participants"]
                 if p["number"] == 1)["features"]["ability"]["value"], 1.0)
        # Float precision at astronomical magnitudes is expected; this is
        # not a hard eligibility cutoff for any athlete.

    def test_above_200_race_score_reaches_existing_pr71_eight_pick_model(self):
        data = fixture()
        for n, points in ((1, 125.75), (2, 217.50), (3, 305.99)):
            row = next(o for o in data["observations"]
                       if o["key"] == "rider/%d/race_score" % n)
            row["value"] = points
        assembled = assemble(data)
        snapshot = assembled["private_snapshot"]
        self.assertIsNotNone(snapshot)
        self.assertEqual(assembled["status"]["missing_model_inputs"], [])
        existing = run_pr71_for_next_race(
            snapshot, run_suite=run_suite, verify_suite=verify_suite,
            source_admission=lambda *_: True,
            model_id="multisport-scenario-ensemble-v1", issued_at=ISSUED)
        self.assertEqual(len(existing["top8"]), 8)
        self.assertFalse(existing["trained"])
        self.assertEqual(assembled["status"]["checked_count"], 347)

    def test_negative_nonfinite_or_non_numeric_scores_rejected(self):
        for invalid in (-1, float("inf"), float("-inf"), float("nan"),
                        "120", True, None):
            with self.subTest(invalid=str(invalid)):
                data = fixture()
                row = next(o for o in data["observations"]
                           if o["key"] == "rider/1/race_score")
                row["value"] = invalid
                with self.assertRaisesRegex(
                        PermittedDeliveryError,
                        "RACE_SCORE_NONNEGATIVE_FINITE_REQUIRED"):
                    assemble(data)

    def test_rakuten_observation_is_never_admitted_even_with_grant_callback(self):
        data = fixture()
        data["observations"][0]["source_url"] = (
            "https://keirin.kdreams.jp/odawara/racecard/forbidden"
        )
        out = assemble(data, grant=lambda *_: True)
        self.assertIsNone(out["private_snapshot"])
        self.assertEqual(out["audit"]["items"][0]["status"], "rights_blocked")
        self.assertEqual(out["audit"]["items"][0]["reason"],
                         "RAKUTEN_SOURCE_EXCLUDED_BY_OWNER")

    def test_unjustified_winning_probability_rejected(self):
        data = fixture()
        row = next(o for o in data["observations"]
                   if o["key"] == "rider/1/top_three_rate")
        row["value"] = 67  # 67% must be explicitly normalized before ingest
        with self.assertRaisesRegex(PermittedDeliveryError,
                                    "NONFINITE_OR_UNDOCUMENTED_NORMALIZATION"):
            assemble(data)

    def test_market_term_cannot_enter_as_hidden_object(self):
        data = fixture()
        data["race"]["betting"] = {"odds": 42}
        with self.assertRaises(ValueError):
            assemble(data)


class SeparateEvidenceProfileTests(unittest.TestCase):
    """Only fictional pre-cutoff sources; A must stay untouched, B is a candidate."""

    def distinct_packet(self):
        packet = fixture(full=True)
        altered = {
            "rider/1/last_lap_acceleration": 0.91,
            "rider/1/late_lap_and_agari_time": 0.19,
            "rider/1/venue_and_distance_compatibility": 0.84,
            "rider/1/bank_positioning_and_traffic": 0.14,
        }
        for row in packet["observations"]:
            if (row["key"].endswith("/late_lap_and_agari_time")
                    or row["key"].endswith("/bank_positioning_and_traffic")):
                row["value"] = 0.60
            if row["key"] in altered:
                row["value"] = altered[row["key"]]
        return packet

    def test_distinct_B_origins_have_no_double_counted_source(self):
        self.assertEqual(len(RIDER_MAP), 28)
        self.assertEqual(len(RIDER_MAP_DISTINCT_B), 22)
        self.assertEqual(len(set(src for src, _ in RIDER_MAP_DISTINCT_B.values())),
                         len(RIDER_MAP_DISTINCT_B))
        self.assertEqual(RIDER_MAP_DISTINCT_B["finishing_power"][0],
                         "late_lap_and_agari_time")
        self.assertEqual(RIDER_MAP_DISTINCT_B["sprint_acceleration"][0],
                         "last_lap_acceleration")
        self.assertEqual(RIDER_MAP_DISTINCT_B["course_compatibility"][0],
                         "bank_positioning_and_traffic")
        self.assertEqual(RIDER_MAP_DISTINCT_B["bank_fit"][0],
                         "venue_and_distance_compatibility")
        self.assertNotIn("recent_points", RIDER_MAP_DISTINCT_B)
        self.assertNotIn("last_lap_kick", RIDER_MAP_DISTINCT_B)
        self.assertNotIn("teammate_synergy", RIDER_MAP_DISTINCT_B)

    def test_same_fictional_pre_race_sources_a_vs_b_all_four_original_models(self):
        from race_ai.four_sport_model_suite import ALL_MODELS
        packet = self.distinct_packet()
        a = assemble_permitted_pre_race(
            packet, grant_check=granted, checked_at=CHECKED)
        explicit_a = assemble_permitted_pre_race(
            packet, grant_check=granted, checked_at=CHECKED,
            feature_source_profile="legacy_a")
        self.assertEqual(a, explicit_a)
        b = assemble_permitted_pre_race(
            packet, grant_check=granted, checked_at=CHECKED,
            feature_source_profile=DISTINCT_B_ID)
        self.assertIsNotNone(a["private_snapshot"])
        self.assertIsNotNone(b["private_snapshot"])
        self.assertEqual(a["status"]["feature_source_profile"], "legacy_a")
        self.assertEqual(b["status"]["feature_source_profile"], DISTINCT_B_ID)
        self.assertEqual(a["status"]["model_inputs_generated"], 205)
        self.assertEqual(b["status"]["model_inputs_generated"], 163)
        self.assertEqual(b["status"]["checked_count"], 347)
        self.assertFalse(a["status"]["legacy_double_counting_removed_in_B"])
        self.assertTrue(b["status"]["legacy_double_counting_removed_in_B"])
        a_features = a["private_snapshot"]["facts"]["pr71_evidenced_snapshot"][
            "participants"][0]["features"]
        b_features = b["private_snapshot"]["facts"]["pr71_evidenced_snapshot"][
            "participants"][0]["features"]
        self.assertAlmostEqual(a_features["finishing_power"]["value"], .91)
        self.assertAlmostEqual(a_features["sprint_acceleration"]["value"], .91)
        self.assertAlmostEqual(b_features["finishing_power"]["value"], .19)
        self.assertAlmostEqual(b_features["sprint_acceleration"]["value"], .91)
        self.assertAlmostEqual(a_features["course_compatibility"]["value"], .84)
        self.assertAlmostEqual(b_features["course_compatibility"]["value"], .14)
        self.assertAlmostEqual(b_features["bank_fit"]["value"], .84)
        self.assertEqual(
            b["consumed_feature_origins"]["rider/1/finishing_power"],
            "rider/1/late_lap_and_agari_time")
        self.assertEqual(
            b["consumed_feature_origins"]["rider/1/course_compatibility"],
            "rider/1/bank_positioning_and_traffic")
        self.assertNotIn("last_lap_kick", b_features)
        a_suite = run_suite(a["private_snapshot"]["facts"]["pr71_evidenced_snapshot"],
                            allow_source=lambda *_: True)
        b_suite = run_suite(b["private_snapshot"]["facts"]["pr71_evidenced_snapshot"],
                            allow_source=lambda *_: True)
        self.assertTrue(verify_suite(a_suite))
        self.assertTrue(verify_suite(b_suite))
        self.assertEqual(set(a_suite["models"]), set(ALL_MODELS))
        self.assertEqual(set(b_suite["models"]), set(ALL_MODELS))
        for model_id in ALL_MODELS:
            a_model = a_suite["models"][model_id]
            b_model = b_suite["models"][model_id]
            self.assertEqual(a_model["candidate_count"], 210)
            self.assertEqual(b_model["candidate_count"], 210)
            self.assertNotEqual(a_model["prediction_sha256"],
                                b_model["prediction_sha256"])
            self.assertEqual(len(b_model["ordered_top8"]), 8)
            self.assertFalse(b_model["trained"])
        # No results, bets or observed model improvement can be inferred here.

    def test_missing_distinct_B_sources_fail_closed_not_fabricated(self):
        packet = self.distinct_packet()
        packet["observations"] = [
            row for row in packet["observations"]
            if row["key"] not in {
                "rider/1/late_lap_and_agari_time",
                "rider/2/bank_positioning_and_traffic",
            }
        ]
        a = assemble_permitted_pre_race(
            packet, grant_check=granted, checked_at=CHECKED)
        b = assemble_permitted_pre_race(
            packet, grant_check=granted, checked_at=CHECKED,
            feature_source_profile=DISTINCT_B_ID)
        self.assertIsNotNone(a["private_snapshot"])
        self.assertIsNone(b["private_snapshot"])
        self.assertIn("rider/1/finishing_power",
                      b["status"]["missing_model_inputs"])
        self.assertIn("rider/2/course_compatibility",
                      b["status"]["missing_model_inputs"])
        self.assertEqual(b["status"]["state"],
                         "BLOCKED_MISSING_CRITICAL_OR_MODEL_INPUTS")

    def test_agari_seconds_not_pretended_to_be_normalized_ratio(self):
        packet = self.distinct_packet()
        row = next(
            row for row in packet["observations"]
            if row["key"] == "rider/1/late_lap_and_agari_time")
        row["value"] = 12.6   # Actual half-lap *seconds*, not normalized rank
        with self.assertRaisesRegex(PermittedDeliveryError,
                                    "NONFINITE_OR_UNDOCUMENTED_NORMALIZATION"):
            assemble_permitted_pre_race(
                packet, grant_check=granted, checked_at=CHECKED,
                feature_source_profile=DISTINCT_B_ID)

    def test_profile_is_not_a_source_rights_grant(self):
        out = assemble_permitted_pre_race(
            self.distinct_packet(), grant_check=lambda *_: False,
            checked_at=CHECKED, feature_source_profile=DISTINCT_B_ID)
        self.assertIsNone(out["private_snapshot"])
        self.assertEqual(out["status"]["verified_items"], 0)
        self.assertFalse(out["status"]["rights_certified_by_this_module"])
        with self.assertRaisesRegex(PermittedDeliveryError,
                                    "UNKNOWN_FEATURE_SOURCE_PROFILE"):
            assemble_permitted_pre_race(
                self.distinct_packet(), grant_check=granted,
                checked_at=CHECKED, feature_source_profile="make_up_winner")


if __name__ == "__main__":
    unittest.main()
