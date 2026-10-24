"""Synthetic-only tests. Never fetch, persist, or publish actual official B rows."""
import copy
import unittest

from race_ai.boat_b_feature_bridge import BFeatureBridgeError, candidate_bridge

DAY = "2030-03-17"
SOURCE = "https://www1.mbrace.or.jp/od2/B/203003/b300317.lzh"
RUNNER = ("ability", "recent_form", "start_reliability", "finishing_power",
          "course_compatibility", "stamina", "tactical_adaptability",
          "consistency", "motor_form", "start_timing", "lane_course_fit")
ENV = ("wind_mps", "rain_mm_h", "humidity_pct", "air_temp_c", "surface_wetness",
       "wave_cm", "water_current_strength", "crosswind_factor", "tide_activity")


def fixture():
    rid = "20300317-18-01"
    entries = []
    details = {}
    for lane in range(1, 7):
        racer = str(4000 + lane)
        entries.append({"race_id": rid, "lane": lane, "racer_id": racer})
        details[(rid, lane)] = {
            "racer_registration_id": racer,
            "name": "架空選手",
            "grade": "A2",
            "motor_no": lane + 10,
            "boat_no": lane + 100,
            "national_win_rate": float(lane),
            "local_win_rate": 5.5,
            "motor_top2_rate": 40.0,
            "national_top2_rate": 34.0,
            "local_top2_rate": 20.0,
            "boat_top2_rate": 10.0,
        }
    return entries, details, {rid: DAY + "T12:30:00+09:00"}


def make(*, observed=DAY + "T08:00:00+09:00", **overrides):
    entries, details, deadlines = fixture()
    args = dict(entries=entries, details=details, deadlines=deadlines,
                event_date_jst=DAY, archive_url=SOURCE, archive_sha256="a" * 64,
                observed_at_claimed=observed,
                required_runner_keys=RUNNER, required_environment_keys=ENV)
    args.update(overrides)
    return candidate_bridge(**args)


class BFeatureBridgeTests(unittest.TestCase):
    def test_six_runners_three_evidence_candidates_each_but_no_real_admission(self):
        bundle = make()
        audit = bundle["public_audit"]
        self.assertEqual(audit["complete_parsed_races"], 1)
        self.assertEqual(audit["source_numeric_candidates_created"], 18)
        self.assertEqual(audit["required_per_race"], 75)
        self.assertEqual(audit["model_required_fields_with_no_B_candidate_total"], 57)
        self.assertEqual(audit["required_observations_not_admitted"], 75)
        self.assertEqual(audit["required_observations_admitted_to_model"], 0)
        self.assertFalse(audit["model_prediction_executed"])
        first = bundle["private_candidate_projection"][0]["participants"][0]
        features = {v["feature_key"]: v for v in first["candidates"]}
        self.assertEqual({k: v["normalized_value"] for k, v in features.items()},
                         {"ability": 0.1, "course_compatibility": 0.55, "motor_form": 0.4})
        for item in features.values():
            self.assertIsNone(item["published_at"])
            self.assertIsNone(item["sample_n"])
            self.assertIsNone(item["source_rights_ref"])
            self.assertFalse(item["independently_admitted_for_pr71"])
            self.assertEqual(item["archive_sha256"], "a" * 64)
        self.assertNotIn("private_candidate_projection", str(audit))
        self.assertNotIn("架空選手", str(audit))
        self.assertNotIn("4001", str(audit))

    def test_historical_capture_is_never_elevated_to_pre_cutoff(self):
        result = make(observed=DAY + "T18:30:00+09:00")["public_audit"]
        self.assertEqual(result["captured_at_or_after_scheduled_cutoff_races"], 1)
        self.assertFalse(result["formal_hit_at_8_eligible"])

    def test_source_uri_and_hash_must_match_day(self):
        for kwargs in (
            {"archive_url": "https://evil.test/B/203003/b300317.lzh"},
            {"archive_url": SOURCE.replace("300317", "300318")},
            {"archive_sha256": "f" * 63},
            {"event_date_jst": "2030-03-18"},
            {"observed_at_claimed": "2030-03-17T08:00:00"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(BFeatureBridgeError):
                make(**kwargs)

    def test_incomplete_identity_and_missing_numeric_values_fail_closed(self):
        entries, details, deadlines = fixture()
        variants = [
            dict(entries=entries[:5]),
            dict(details={k: v for k, v in details.items() if k[1] != 6}),
            dict(deadlines={}),
        ]
        for change in variants:
            with self.subTest(keys=list(change)), self.assertRaises(BFeatureBridgeError):
                make(**change)
        for value in (float("nan"), -1, 101, None, True):
            bad = copy.deepcopy(details)
            bad[(entries[0]["race_id"], 1)]["motor_top2_rate"] = value
            with self.subTest(value=repr(value)), self.assertRaises(BFeatureBridgeError):
                make(details=bad)

    def test_model_contract_drift_stops_candidate_mapping(self):
        with self.assertRaisesRegex(BFeatureBridgeError, "no longer match"):
            make(required_runner_keys=("ability", "motor_form"))
        with self.assertRaisesRegex(BFeatureBridgeError, "inventory"):
            make(required_environment_keys=("wind_mps", "wind_mps"))

    def test_duplicate_entrant_and_deadline_wrong_day(self):
        entries, details, deadlines = fixture()
        with self.assertRaises(BFeatureBridgeError):
            make(entries=entries + [entries[0]])
        rid = entries[0]["race_id"]
        with self.assertRaises(BFeatureBridgeError):
            make(deadlines={rid: "2030-03-18T00:01:00+09:00"})


if __name__ == "__main__":
    unittest.main()
