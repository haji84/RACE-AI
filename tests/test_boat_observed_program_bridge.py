"""Fictional B facts; no provider fetch, private originals or model inference."""
from copy import deepcopy
import importlib
import unittest

DAY = "2030-03-17"
ASOF = DAY + "T08:00:00+09:00"
URL = "https://www1.mbrace.or.jp/od2/B/203003/b300317.lzh"


def fixture():
    race = {"race_id": "20300317-18-01", "closed_at": DAY + "T12:30:00+09:00",
            "preview_available": False, "boats": []}
    for lane in range(1, 7):
        race["boats"].append({"lane": lane, "racer_registration_id": str(4000 + lane),
            "motor_no": 10 + lane, "boat_no": 100 + lane, "name": "FICTIONAL",
            "grade": "A2", "national_win_rate": 5.25, "motor_top2_rate": 41.5,
            "local_win_rate": 4.0, "national_top2_rate": 33.0, "local_top2_rate": 20.0,
            "boat_top2_rate": 31.0, "average_st": None, "display_time": None,
            "preview_course": None})
    source = {"source_id": "b-program", "source_url": URL, "source_sha256": "a" * 64,
        "source_rights_ref": "fictional-test-rights", "published_at": None,
        "captured_at": DAY + "T07:59:00+09:00", "evidence_basis": "CAPTURED_BY_CLAIM"}
    return race, source


class ObservedProgramBridgeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.boat_observed_program_bridge"),
                             "new measured B to observed-pairwise bridge is missing")
        self.api = importlib.import_module("race_ai.boat_observed_program_bridge")

    def build(self, race=None, source=None, **kwargs):
        original, evidence = fixture()
        options = {"event_date_jst": DAY, "as_of": ASOF, "race_revision": 1}
        options.update(kwargs)
        return self.api.build_program_snapshot(original if race is None else race,
            evidence if source is None else source, **options)

    def test_raw_rates_and_unknown_denominators_reach_exact_flat_research_schema(self):
        result = self.build()
        self.assertEqual(set(result), {"schema", "scope", "race_id", "event_date_jst", "venue",
            "race_revision", "race_source_id", "sales_cutoff_at", "as_of", "stage", "sources", "participants"})
        self.assertEqual(result["scope"], "OPERATOR_SUPPLIED_RESEARCH")
        self.assertEqual(result["schema"], "RACE_AI_BOAT_OBSERVED_PAIRWISE_V1")
        self.assertEqual(result["race_id"], "boat:2030-03-17:boatrace-jcd-18:1")
        self.assertEqual(result["stage"], "P0")
        self.assertEqual(result["race_source_id"], "b-program")
        self.assertEqual(result["participants"][0]["features"], {
            "national_win_rate": {"value": 5.25, "sample_n": None, "source_id": "b-program",
                "transform_id": "official_B_national_win_rate_points_v1"},
            "motor_top2_rate": {"value": 41.5, "sample_n": None, "source_id": "b-program",
                "transform_id": "official_B_motor_top2_percent_v1"}})
        self.assertIsNone(result["sources"][0]["published_at"])
        self.assertEqual(result["sources"][0]["evidence_basis"], "CAPTURED_BY_CLAIM")

    def test_missing_b_values_do_not_fill_or_cancel_any_entrant(self):
        race, source = fixture()
        race["boats"][0]["national_win_rate"] = None
        del race["boats"][1]["motor_top2_rate"]
        result = self.build(race, source)
        self.assertEqual(len(result["participants"]), 6)
        self.assertNotIn("national_win_rate", result["participants"][0]["features"])
        self.assertEqual(result["participants"][0]["missing"]["national_win_rate"], "MISSING")
        self.assertNotIn("motor_top2_rate", result["participants"][1]["features"])
        self.assertEqual(result["participants"][1]["missing"]["motor_top2_rate"], "MISSING")
        for person in result["participants"]:
            self.assertEqual(person["missing"]["course_mean_finish"], "NO_VERIFIED_COURSE")
            self.assertEqual(person["missing"]["course_mean_st"], "NO_VERIFIED_COURSE")
            self.assertEqual(person["missing"]["recent_mean_finish"], "NO_PRIOR_SAMPLES")
            self.assertEqual(person["missing"]["exhibition_time_seconds"], "MISSING")
            self.assertEqual(len(person["features"]) + len(person["missing"]), 8)

    def test_zero_is_real_and_unsupported_rate_values_are_rejected(self):
        race, source = fixture()
        race["boats"][0]["national_win_rate"] = 0
        self.assertEqual(self.build(race, source)["participants"][0]["features"]["national_win_rate"]["value"], 0)
        for feature, invalid in (("national_win_rate", 10.01), ("motor_top2_rate", 100.01),
                                 ("national_win_rate", -1), ("national_win_rate", True),
                                 ("motor_top2_rate", float("nan")), ("motor_top2_rate", "41.5")):
            bad = deepcopy(race)
            bad["boats"][0][feature] = invalid
            with self.subTest(feature=feature, invalid=repr(invalid)), self.assertRaises(self.api.ProgramBridgeError):
                self.build(bad, source)

    def test_fresh_current_b_revision_never_copies_unknown_extra_or_preview_features(self):
        race, source = fixture()
        for key, value in (("odds", 1.2), ("result", [1, 2, 3]), ("unrecognized", 1)):
            bad = deepcopy(race)
            bad["boats"][0][key] = value
            with self.subTest(key=key), self.assertRaises(self.api.ProgramBridgeError):
                self.build(bad, source)
        for key in ("average_st", "display_time", "preview_course"):
            bad = deepcopy(race)
            bad["boats"][0][key] = .15 if key == "average_st" else 1
            with self.subTest(key=key), self.assertRaises(self.api.ProgramBridgeError):
                self.build(bad, source)

    def test_roster_conflicts_withdrawal_and_nonready_are_explicit_holds(self):
        race, source = fixture()
        changes = []
        bad = deepcopy(race); bad["boats"].pop(); changes.append(bad)
        bad = deepcopy(race); bad["boats"][1]["lane"] = 1; changes.append(bad)
        bad = deepcopy(race); bad["boats"][1]["racer_registration_id"] = "4001"; changes.append(bad)
        bad = deepcopy(race); bad["boats"][0]["lane"] = True; changes.append(bad)
        bad = deepcopy(race); bad["boats"][0]["entry_status"] = "withdrawn"; changes.append(bad)
        bad = deepcopy(race); bad["status"] = "CANCELLED"; changes.append(bad)
        bad = deepcopy(race); bad["preview_available"] = True; changes.append(bad)
        bad = deepcopy(race); bad["boats"][1]["motor_no"] = 11; changes.append(bad)
        for bad in changes:
            with self.subTest(bad=bad), self.assertRaises(self.api.ProgramBridgeError):
                self.build(bad, source)
        with self.assertRaises(self.api.ProgramBridgeError):
            self.build(race_revision=True)
        with self.assertRaises(self.api.ProgramBridgeError):
            self.build(race_revision=0)

    def test_inconsistent_race_source_day_hash_publication_and_deadline_rejected(self):
        race, source = fixture()
        for key, value in (("source_url", URL + "?x=1"), ("source_url", URL.replace("300317", "300318")),
            ("source_sha256", "z" * 64), ("source_rights_ref", ""), ("source_id", []),
            ("published_at", DAY + "T07:00:00+09:00"), ("evidence_basis", "SOURCE_PUBLISHED_AT_CLAIM"),
            ("captured_at", DAY + "T08:01:00+09:00")):
            bad = dict(source); bad[key] = value
            with self.subTest(key=key), self.assertRaises(self.api.ProgramBridgeError):
                self.build(race, bad)
        for kwargs in ({"event_date_jst": "2030-03-18"}, {"as_of": DAY + "T12:30:00+09:00"},
                       {"as_of": DAY + "T08:00:00"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(self.api.ProgramBridgeError):
                self.build(**kwargs)
        bad = deepcopy(race); bad["closed_at"] = "2030-03-18T12:30:00+09:00"
        with self.assertRaises(self.api.ProgramBridgeError):
            self.build(bad, source)

    def test_output_is_deterministic_detached_from_parser_inputs(self):
        race, source = fixture()
        race["boats"].reverse()
        before = deepcopy((race, source))
        result = self.build(race, source)
        self.assertEqual(result, self.build())
        self.assertEqual((race, source), before)
        result["sources"][0]["source_id"] = "changed"
        result["participants"][0]["features"]["national_win_rate"]["value"] = 0
        self.assertEqual((race, source), before)


if __name__ == "__main__":
    unittest.main()
