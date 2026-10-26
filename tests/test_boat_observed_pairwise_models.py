"""Fictional observations only; no source authenticity or performance claim."""
from copy import deepcopy
import importlib
import itertools
import math
import unittest

from race_ai.actions_contract import digest
from race_ai.legacy_boat_rank import plackett_luce

try:
    model = importlib.import_module("race_ai.boat_observed_pairwise_models")
except ModuleNotFoundError:
    model = None


FIELDS = (
    "national_win_rate", "motor_top2_rate", "recent_mean_finish",
    "course_mean_finish", "recent_mean_st", "course_mean_st",
    "exhibition_time_seconds", "exhibition_start_seconds",
)
TRANSFORMS = (
    "official_B_national_win_rate_points_v1", "official_B_motor_top2_percent_v1",
    "strict_numeric_finish_mean_v1", "strict_numeric_finish_mean_v1",
    "strict_ok_start_mean_seconds_v1", "strict_ok_start_mean_seconds_v1",
    "official_exhibition_time_seconds_v1", "official_exhibition_start_seconds_v1",
)


def fixture(stage="P0", *, all_missing=False, research=False):
    rows = []
    for lane in range(1, 7):
        values = [lane, 10 * lane, lane, 7 - lane, lane / 10,
                  (7 - lane) / 10, 6 + lane / 10, lane / 10]
        features, missing = {}, {}
        for index, name in enumerate(FIELDS):
            if all_missing or (stage == "P0" and index >= 6):
                missing[name] = "NOT_YET_PUBLISHED" if index >= 6 else "MISSING"
                continue
            feature = {"value": values[index], "sample_n": None,
                       "source_id": "fixture-program", "transform_id": TRANSFORMS[index]}
            if 2 <= index <= 5:
                feature["sample_n"] = 4
                feature["history"] = {"window_id": "fictional-" + name + "-window-" + str(lane),
                                      "total_n": 4, "ok_n": 4, "f_n": 0, "l_n": 0,
                                      "missing_n": 0, "unresolved_n": 0}
            features[name] = feature
        rows.append({"lane": lane, "registration_no": str(4000 + lane),
                     "features": features, "missing": missing})
    return {
        "schema": "RACE_AI_BOAT_OBSERVED_PAIRWISE_V1",
        "scope": "OPERATOR_SUPPLIED_RESEARCH" if research else "SYNTHETIC_ONLY",
        "race_id": "boat:2030-04-01:boatrace-jcd-01:1",
        "event_date_jst": "2030-04-01", "venue": "boatrace-jcd-01",
        "race_revision": 1, "sales_cutoff_at": "2030-04-01T10:59:00+09:00",
        "as_of": "2030-04-01T10:42:00+09:00", "stage": stage,
        "race_source_id": "fixture-program",
        "sources": [{"source_id": "fixture-program",
                     "source_url": "https://example.test/program" if research else "synthetic://fixture",
                     "source_sha256": "a" * 64, "source_rights_ref": "fictional-test-rights",
                     "published_at": "2030-04-01T09:00:00+09:00",
                     "captured_at": "2030-04-01T10:00:00+09:00",
                     "evidence_basis": "SOURCE_PUBLISHED_AT_CLAIM"}],
        "participants": rows,
    }


def absent(snapshot, lane, field, reason="MISSING"):
    row = snapshot["participants"][lane - 1]
    row["features"].pop(field, None)
    row["missing"][field] = reason


class ObservedPairwiseTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(model, "missing observed-pairwise implementation")

    def predict(self, snapshot, **kwargs):
        return model.predict_pair(snapshot, **kwargs)

    def assert_rejected(self, snapshot, **kwargs):
        with self.assertRaises(model.ObservedPairwiseError):
            self.predict(snapshot, **kwargs)

    def test_complete_data_equals_independent_fixed_utility_pl(self):
        snapshot = fixture("P1")
        output = self.predict(snapshot)
        weights = ((1.25, .75, 1, .65, .35, .2, .35, .2),
                   (.75, .5, .8, .35, .9, .35, .7, .5))
        for result, w in zip(output["models"].values(), weights):
            strengths = {}
            for lane in range(1, 7):
                # Independent hand-stated normalization of this fixture.
                z = [lane / 10, lane / 10, (6 - lane) / 5, (lane - 1) / 5,
                     1 - lane / 10, 1 - (7 - lane) / 10,
                     (14 - lane / 10) / 19, 1 - lane / 10]
                strengths[lane] = math.exp(math.fsum(a * b for a, b in zip(w, z)))
            expected = {tuple(row["combination"]): row["probability"]
                        for row in plackett_luce(strengths)["triples"]}
            for candidate in result["candidates"]:
                self.assertAlmostEqual(candidate["score"],
                                       expected[tuple(candidate["combination"])], places=14)
            for row in result["utilities"]:
                self.assertEqual(row["completion_lower"], row["utility"])
                self.assertEqual(row["completion_upper"], row["utility"])

    def test_each_optional_feature_absence_preserves_output_and_diagnostics(self):
        for lane, field in itertools.product(range(1, 7), FIELDS):
            with self.subTest(lane=lane, field=field):
                snapshot = fixture("P1")
                absent(snapshot, lane, field, "SOURCE_UNAVAILABLE")
                output = self.predict(snapshot)
                self.assertEqual(output["coverage"]["observed_feature_counts"][field], 5)
                self.assertEqual(output["coverage"]["observed_pair_counts"][field], 10)
                self.assertEqual(output["observations"][lane - 1]["missing"][field], "SOURCE_UNAVAILABLE")
                for result in output["models"].values():
                    self.assertEqual(len(result["ordered_top8"]), 8)

    def test_entire_entrant_can_be_missing_without_inventing_observations(self):
        snapshot = fixture("P1")
        for field in FIELDS:
            absent(snapshot, 3, field)
        output = self.predict(snapshot)
        self.assertEqual(output["observations"][2]["features"], {})
        for result in output["models"].values():
            row = result["utilities"][2]
            self.assertEqual(row["utility"], 0)
            self.assertEqual(row["observed_comparisons"], 0)
            self.assertLess(row["completion_lower"], 0)
            self.assertGreater(row["completion_upper"], 0)

    def test_all_missing_is_uniform_uninformative_with_completion_uncertainty(self):
        output = self.predict(fixture(all_missing=True))
        self.assertEqual(output["coverage"]["observed_pair_count"], 0)
        expected_top8 = [[1, 2, 3], [1, 2, 4], [1, 2, 5], [1, 2, 6],
                         [1, 3, 2], [1, 3, 4], [1, 3, 5], [1, 3, 6]]
        for result, total_weight in zip(output["models"].values(), (4.75, 4.85)):
            self.assertEqual(result["status"], "UNINFORMATIVE_TIE_BREAK")
            self.assertFalse(result["score_discriminating"])
            self.assertEqual(result["ordered_top8"], expected_top8)
            self.assertTrue(all(row["score"] == 1 / 120 for row in result["candidates"]))
            for row in result["utilities"]:
                self.assertEqual(row["utility"], 0)
                self.assertAlmostEqual(row["completion_lower"], -total_weight * 5 / 6)
                self.assertAlmostEqual(row["completion_upper"], total_weight * 5 / 6)

    def test_equal_observed_values_are_uninformative_despite_full_coverage(self):
        snapshot = fixture("P1")
        for row in snapshot["participants"][1:]:
            row["features"] = deepcopy(snapshot["participants"][0]["features"])
        output = self.predict(snapshot)
        self.assertEqual(output["coverage"]["observed_pair_count"], 120)
        self.assertEqual(output["coverage"]["discriminating_pair_count"], 0)
        for result in output["models"].values():
            self.assertEqual(result["status"], "UNINFORMATIVE_TIE_BREAK")
            self.assertFalse(result["score_discriminating"])

    def test_opposing_features_can_cancel_despite_discriminating_pairs(self):
        snapshot = fixture(all_missing=True)
        for row in snapshot["participants"]:
            high = row["lane"] <= 3
            for field, value, transform in ((FIELDS[0], 6 if high else 0, TRANSFORMS[0]),
                                             (FIELDS[1], 0 if high else 100, TRANSFORMS[1])):
                row["missing"].pop(field)
                row["features"][field] = {"value": value, "sample_n": None,
                                          "source_id": "fixture-program", "transform_id": transform}
        output = self.predict(snapshot)
        self.assertEqual(output["coverage"]["discriminating_pair_count"], 18)
        factor, start = output["models"].values()
        self.assertEqual(factor["status"], "UNINFORMATIVE_TIE_BREAK")
        self.assertFalse(factor["score_discriminating"])
        self.assertTrue(start["score_discriminating"])

    def test_known_unknown_bounds_and_fixed_six_divisor(self):
        snapshot = fixture(all_missing=True)
        for row in snapshot["participants"]:
            row["features"][FIELDS[0]] = {"value": 10 if row["lane"] == 1 else 0,
                                         "sample_n": None, "source_id": "fixture-program",
                                         "transform_id": TRANSFORMS[0]}
            row["missing"].pop(FIELDS[0])
        complete = self.predict(snapshot)
        self.assertAlmostEqual(next(iter(complete["models"].values()))["utilities"][0]["utility"], 1.25 * 5 / 6)
        for lane in range(3, 7):
            absent(snapshot, lane, FIELDS[0])
        partial = self.predict(snapshot)
        factor = next(iter(partial["models"].values()))
        self.assertAlmostEqual(factor["utilities"][0]["utility"], 1.25 / 6)
        self.assertAlmostEqual(factor["utilities"][1]["utility"], -1.25 / 6)
        self.assertEqual(partial["coverage"]["observed_pair_count"], 1)
        # Other seven dimensions contribute [-3.5*5/6, 3.5*5/6].
        self.assertAlmostEqual(factor["utilities"][0]["completion_lower"], (1.25 - 3.5 * 5) / 6)
        self.assertAlmostEqual(factor["utilities"][0]["completion_upper"], (1.25 * 5 + 3.5 * 5) / 6)
        self.assertAlmostEqual(factor["utilities"][2]["completion_lower"], (-1.25 * 4 - 3.5 * 5) / 6)
        self.assertAlmostEqual(factor["utilities"][2]["completion_upper"], (1.25 * 4 + 3.5 * 5) / 6)

    def test_p0_rejects_exhibition_and_p1_requires_one_present_value(self):
        snapshot = fixture("P1")
        snapshot["stage"] = "P0"
        self.assert_rejected(snapshot)
        snapshot = fixture()
        snapshot["stage"] = "P1"
        self.assert_rejected(snapshot)
        snapshot = fixture("P1", all_missing=True)
        feature = deepcopy(fixture("P1")["participants"][0]["features"][FIELDS[6]])
        snapshot["participants"][0]["features"][FIELDS[6]] = feature
        snapshot["participants"][0]["missing"].pop(FIELDS[6])
        output = self.predict(snapshot)
        self.assertEqual(output["coverage"]["observed_feature_counts"][FIELDS[6]], 1)
        self.assertTrue(all(r["status"] == "UNINFORMATIVE_TIE_BREAK" for r in output["models"].values()))

    def test_finish_means_reject_unknown_or_nonnumeric_dispositions(self):
        for field in FIELDS[2:4]:
            for count in ("f_n", "l_n", "missing_n", "unresolved_n"):
                with self.subTest(field=field, count=count):
                    snapshot = fixture()
                    history = snapshot["participants"][0]["features"][field]["history"]
                    history[count] = 1
                    history["total_n"] = 5
                    self.assert_rejected(snapshot)

    def test_st_mean_preserves_f_l_missing_counts_and_zero(self):
        snapshot = fixture()
        feature = snapshot["participants"][0]["features"][FIELDS[4]]
        feature["value"] = 0
        feature["history"].update(total_n=10, f_n=1, l_n=2, missing_n=3)
        output = self.predict(snapshot)
        self.assertEqual(output["observations"][0]["features"][FIELDS[4]], feature)
        for reason in ("F", "L", "UNRESOLVED_DISPOSITION", "NO_PRIOR_SAMPLES", "NO_VERIFIED_COURSE", "RIGHTS_BLOCKED"):
            absent(snapshot, 2, FIELDS[4], reason)
            self.assertEqual(self.predict(snapshot)["observations"][1]["missing"][FIELDS[4]], reason)

    def test_history_metadata_must_be_complete_consistent_and_nonfabricated(self):
        for mutate in (
            lambda f: f.pop("history"),
            lambda f: f["history"].update(window_id=""),
            lambda f: f["history"].update(total_n=5),
            lambda f: f["history"].update(ok_n=3, missing_n=1),
            lambda f: f["history"].update(total_n=5, unresolved_n=1),
            lambda f: f["history"].update(f_n=True),
            lambda f: f.update(sample_n=None),
            lambda f: f.update(sample_n=0),
        ):
            snapshot = fixture()
            mutate(snapshot["participants"][0]["features"][FIELDS[4]])
            self.assert_rejected(snapshot)

    def test_same_history_provenance_cannot_assert_conflicting_measurements(self):
        for recent, course in ((FIELDS[2], FIELDS[3]), (FIELDS[4], FIELDS[5])):
            for conflict in ("value", "sample_n", "excluded_counts"):
                if recent.endswith("finish") and conflict == "excluded_counts":
                    continue  # Such finish exclusions already fail the individual feature contract.
                with self.subTest(feature=recent, conflict=conflict):
                    snapshot = fixture()
                    features = snapshot["participants"][0]["features"]
                    features[course] = deepcopy(features[recent])
                    if conflict == "value":
                        features[course]["value"] = 2 if recent.endswith("finish") else .2
                    elif conflict == "sample_n":
                        features[course]["sample_n"] = 5
                        features[course]["history"].update(total_n=5, ok_n=5)
                    else:
                        features[course]["history"].update(total_n=5, f_n=1)
                    with self.assertRaisesRegex(model.ObservedPairwiseError, "conflicting history provenance"):
                        self.predict(snapshot)

    def test_reused_history_claim_must_match_only_within_same_provenance_tuple(self):
        snapshot = fixture()
        first = snapshot["participants"][0]["features"]
        first[FIELDS[3]] = deepcopy(first[FIELDS[2]])
        first[FIELDS[5]] = deepcopy(first[FIELDS[4]])
        self.predict(snapshot)  # Same exact claim can serve both relevant features.
        # The same window label for another participant does not identify the same measurement.
        other = snapshot["participants"][1]["features"][FIELDS[2]]
        other["history"]["window_id"] = first[FIELDS[2]]["history"]["window_id"]
        self.predict(snapshot)
        # Distinct transforms of one claimed window are different measurements.
        first[FIELDS[4]]["history"]["window_id"] = first[FIELDS[2]]["history"]["window_id"]
        self.predict(snapshot)
        # Distinct source evidence can identify different underlying windows with the same label.
        source = deepcopy(snapshot["sources"][0])
        source.update(source_id="other-history", source_url="https://example.test/other",
                      source_sha256="b" * 64)
        snapshot["sources"].append(source)
        first[FIELDS[3]].update(value=6, source_id="other-history")
        self.predict(snapshot)

    def test_rates_allow_unknown_denominator_exhibition_requires_no_sample_count(self):
        snapshot = fixture("P1")
        self.predict(snapshot)
        snapshot["participants"][0]["features"][FIELDS[0]]["sample_n"] = 100
        self.predict(snapshot)
        for value in (0, -1, True, 1.5, "100"):
            snapshot["participants"][0]["features"][FIELDS[0]]["sample_n"] = value
            self.assert_rejected(snapshot)
        snapshot = fixture("P1")
        snapshot["participants"][0]["features"][FIELDS[6]]["sample_n"] = 1
        self.assert_rejected(snapshot)

    def test_finite_numeric_ranges_and_transforms_are_strict(self):
        for field in FIELDS:
            for bad in (None, True, "0.1", float("nan"), float("inf"), -1, 101):
                with self.subTest(field=field, value=bad):
                    snapshot = fixture("P1")
                    snapshot["participants"][0]["features"][field]["value"] = bad
                    self.assert_rejected(snapshot)
            snapshot = fixture("P1")
            snapshot["participants"][0]["features"][field]["transform_id"] = "invented-rating"
            self.assert_rejected(snapshot)

    def test_exact_schema_rejects_odds_results_and_formal_promotion_flags(self):
        for injected in ("odds", "actual_finish", "result", "official_prediction", "proof_eligible", "source_rights_granted"):
            for target in ("root", "participant", "feature", "source", "history"):
                with self.subTest(field=injected, target=target):
                    snapshot = fixture()
                    location = {"root": snapshot, "participant": snapshot["participants"][0],
                                "feature": snapshot["participants"][0]["features"][FIELDS[0]],
                                "source": snapshot["sources"][0],
                                "history": snapshot["participants"][0]["features"][FIELDS[2]]["history"]}[target]
                    location[injected] = True
                    self.assert_rejected(snapshot)

    def test_feature_and_missing_maps_exactly_partition_allowlist(self):
        for mutate in (lambda s: s["participants"][0]["missing"].update(national_win_rate="MISSING"),
                       lambda s: s["participants"][0]["features"].pop(FIELDS[0]),
                       lambda s: s["participants"][0]["missing"].update(odds="MISSING"),
                       lambda s: s["participants"][0]["missing"].update(exhibition_start_seconds="NONE")):
            snapshot = fixture()
            mutate(snapshot)
            self.assert_rejected(snapshot)

    def test_identity_dates_revisions_and_unique_six_boats(self):
        mutations = [lambda s: s.update(race_revision=True), lambda s: s.update(race_revision=0),
                     lambda s: s.update(race_id="boat:2030-04-02:boatrace-jcd-01:1"),
                     lambda s: s.update(venue="boatrace-jcd-02"),
                     lambda s: s.update(race_id="boat:2030-04-01:boatrace-jcd-25:1"),
                     lambda s: s.update(race_id="boat:2030-04-01:boatrace-jcd-01:13"),
                     lambda s: s.update(event_date_jst="20300401"),
                     lambda s: s.update(stage="P2"), lambda s: s["participants"].pop(),
                     lambda s: s["participants"][0].update(lane=True),
                     lambda s: s["participants"][1].update(lane=1),
                     lambda s: s["participants"][1].update(registration_no="4001"),
                     lambda s: s["participants"][0].update(registration_no=4001)]
        for mutate in mutations:
            snapshot = fixture()
            mutate(snapshot)
            self.assert_rejected(snapshot)

    def test_sources_require_unique_ids_urls_hashes_and_referenced_source(self):
        for change in ({"source_id": "fixture-program", "source_sha256": "b" * 64,
                        "source_url": "https://example.test/other"},
                       {"source_id": "other", "source_sha256": "b" * 64},
                       {"source_id": "other", "source_url": "https://example.test/other"}):
            snapshot = fixture()
            duplicate = deepcopy(snapshot["sources"][0])
            duplicate.update(change)
            snapshot["sources"].append(duplicate)
            self.assert_rejected(snapshot)
        snapshot = fixture()
        snapshot["participants"][0]["features"][FIELDS[0]]["source_id"] = "unknown"
        self.assert_rejected(snapshot)
        snapshot = fixture()
        snapshot["race_source_id"] = "unknown"
        self.assert_rejected(snapshot)
        for value in ("", "A" * 64, "a" * 63, None):
            snapshot = fixture()
            snapshot["sources"][0]["source_sha256"] = value
            self.assert_rejected(snapshot)

    def test_source_url_rejects_unreviewed_schemes_credentials_queries_fragments(self):
        for value in ("http://example.test/a", "https://u:p@example.test/a",
                      "https://example.test/a?token=x", "https://example.test/a#fragment",
                      "https://", "https://example.test/ bad", "synthetic://other"):
            snapshot = fixture()
            snapshot["sources"][0]["source_url"] = value
            self.assert_rejected(snapshot)
        snapshot = fixture(research=True)
        snapshot["sources"][0]["source_url"] = "synthetic://fixture"
        self.assert_rejected(snapshot, allow_source=lambda *_: True)

    def test_claimed_source_times_and_basis_do_not_grant_verified_timing(self):
        snapshot = fixture()
        snapshot["sources"][0].update(published_at=None, evidence_basis="CAPTURED_BY_CLAIM")
        output = self.predict(snapshot)
        self.assertEqual(output["source_evidence"], snapshot["sources"])
        self.assertFalse(output["independent_availability_verified"])
        for changes in ({"published_at": None}, {"evidence_basis": "CAPTURED_BY_CLAIM"},
                        {"captured_at": "2030-04-01T10:43:00+09:00"},
                        {"published_at": "2030-04-01T10:01:00+09:00"},
                        {"captured_at": "2030-04-01T10:00:00"}):
            snapshot = fixture()
            snapshot["sources"][0].update(changes)
            self.assert_rejected(snapshot)
        for changes in ({"as_of": "2030-04-01T10:59:00+09:00"},
                        {"sales_cutoff_at": "2030-04-02T10:59:00+09:00"}):
            snapshot = fixture()
            snapshot.update(changes)
            self.assert_rejected(snapshot)

    def test_research_permission_callback_requires_exact_true_and_analysis_scope(self):
        snapshot = fixture(research=True)
        for permission in (None, lambda *_: False, lambda *_: 1, lambda *_: "True"):
            self.assert_rejected(snapshot, allow_source=permission)
        calls = []
        def allowed(url, rights, purpose):
            calls.append((url, rights, purpose))
            return True
        result = self.predict(snapshot, allow_source=allowed)
        self.assertEqual(calls, [("https://example.test/program", "fictional-test-rights", "analysis")])
        self.assertFalse(result["official_prediction"])
        def failed(*_):
            raise RuntimeError("denied")
        self.assert_rejected(snapshot, allow_source=failed)

    def test_callback_cannot_mutate_bound_copy_or_returned_evidence(self):
        snapshot = fixture(research=True)
        expected = deepcopy(snapshot)
        def mutating_callback(*_):
            snapshot["participants"][0]["features"][FIELDS[0]]["value"] = 10
            snapshot["sources"][0]["source_rights_ref"] = "replaced"
            snapshot["stage"] = "P1"
            return True
        output = self.predict(snapshot, allow_source=mutating_callback)
        self.assertEqual(output["snapshot_sha256"], digest(expected))
        self.assertEqual(output["observations"], expected["participants"])
        self.assertEqual(output["source_evidence"], expected["sources"])
        self.assertEqual(output["stage"], "P0")

    def test_hashes_determinism_no_input_mutation_and_research_only_flags(self):
        snapshot = fixture("P1")
        original = deepcopy(snapshot)
        output = self.predict(snapshot)
        self.assertEqual(snapshot, original)
        self.assertEqual(output, self.predict(snapshot))
        self.assertEqual(tuple(output["models"]), ("boat-observed-pairwise-factor-v1", "boat-observed-pairwise-start-v1"))
        self.assertEqual(output["suite_sha256"], digest({k: v for k, v in output.items() if k != "suite_sha256"}))
        for result in [output, *output["models"].values()]:
            for field in ("trained", "calibrated", "official_prediction", "source_authentication",
                          "independent_availability_verified", "result_or_cutoff_proof_eligible"):
                self.assertIs(result[field], False)
            self.assertEqual(result["purchase_decision"], "NO_BET")
            self.assertEqual(result["snapshot_sha256"], digest(snapshot))
            self.assertEqual(result["race_revision"], 1)
            self.assertEqual(result["stage"], "P1")
        for result in output["models"].values():
            self.assertEqual(result["prediction_sha256"], digest({k: v for k, v in result.items() if k != "prediction_sha256"}))
            self.assertEqual(result["model_spec_sha256"], output["model_spec_sha256"])
            self.assertEqual(len(result["candidates"]), 120)
            self.assertEqual(len({tuple(r["combination"]) for r in result["candidates"]}), 120)
            self.assertAlmostEqual(math.fsum(r["score"] for r in result["candidates"]), 1, places=14)
            self.assertEqual(result["candidates"], sorted(result["candidates"], key=lambda r: (-r["score"], r["combination"])))
        output["observations"][0]["features"][FIELDS[0]]["value"] = 99
        self.assertEqual(snapshot, original)

    def test_returned_model_spec_cannot_change_future_inference(self):
        original_ranges = deepcopy(model.FEATURE_RANGES)
        original_transforms = deepcopy(model.FEATURE_TRANSFORMS)
        try:
            for section, replacement in (("feature_ranges", (0, 100)),
                                         ("feature_transforms", "caller-overwrite")):
                with self.subTest(section=section):
                    snapshot = fixture()
                    expected = self.predict(snapshot)
                    exposed = self.predict(snapshot)
                    exposed["model_spec"][section][FIELDS[0]] = replacement
                    try:
                        actual = self.predict(snapshot)
                    except model.ObservedPairwiseError as exc:
                        self.fail("returned metadata poisoned later validation: " + str(exc))
                    self.assertEqual(actual, expected)
        finally:
            # Keep a failing aliasing regression from contaminating later tests.
            model.FEATURE_RANGES.clear()
            model.FEATURE_RANGES.update(original_ranges)
            model.FEATURE_TRANSFORMS.clear()
            model.FEATURE_TRANSFORMS.update(original_transforms)


if __name__ == "__main__":
    unittest.main()
