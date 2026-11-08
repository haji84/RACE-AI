"""Only invented source observations are used. No licensed provider claimed."""
import copy
from hashlib import sha256
import unittest

from race_ai.keirin_allowed_delivery import (
    DELIVERY_SCHEMA, ENV_MAP, RIDER_MAP, PermittedDeliveryError,
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


if __name__ == "__main__":
    unittest.main()
