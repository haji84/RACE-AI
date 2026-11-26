"""The public results radar preserves observed samples and archive boundaries."""
from copy import deepcopy
from hashlib import sha256
import json
import unittest

from race_ai import keirin_dossier_ability as radar


def period(finishes, first, last, start=None):
    result = {
        "observed_count": len(finishes),
        "finish_counts": {str(rank): finishes.count(rank) for rank in range(1, 10)},
        "first_observed_day": first,
        "latest_observed_day": last,
    }
    if start is not None:
        result["start_day_inclusive"] = start
    return result


def directory():
    return {
        "schema": "RACE_AI_KEIRIN_PUBLIC_RIDER_DIRECTORY_V1",
        "as_of": "2026-11-25",
        "history_start_day": "2025-10-01",
        "history_end_day": "2026-11-22",
        "riders": [{
            "registration": "012345",
            "name": "架空選手",
            "history": period([1, 1, 2, 3, 4, 5, 6], "2025-10-08", "2026-11-12"),
            "history_windows": {
                "1_year": period([1, 1, 2, 3, 5, 6], "2025-12-03", "2026-11-12", "2025-11-25"),
                "4_months": period([2, 3, 5, 6], "2026-08-01", "2026-11-12", "2026-07-25"),
                "1_month": period([3, 6], "2026-11-01", "2026-11-12", "2026-10-25"),
            },
        }],
    }


def project(document):
    raw = json.dumps(document).encode()
    return radar.project_verified_results_radars(raw, expected_sha256=sha256(raw).hexdigest())


class ResultsRadarTests(unittest.TestCase):
    def test_exact_six_axes_and_window_boundaries(self):
        row = project(directory())["012345"]
        self.assertEqual(row["scope"], "OBSERVED_FINISHES_ONLY")
        self.assertEqual([(axis["label"], axis["numerator"], axis["denominator"]) for axis in row["axes"]], [
            ("1年・1着", 2, 6), ("1年・2着以内", 3, 6), ("1年・3着以内", 4, 6),
            ("4か月・3着以内", 2, 4), ("4か月・2着以内", 1, 4), ("4か月・1着", 0, 4),
        ])
        self.assertEqual(row["history_end_day"], "2026-11-22")
        self.assertEqual(row["axes"][0]["start_day_inclusive"], "2025-11-25")
        self.assertEqual(row["axes"][0]["latest_observed_day"], "2026-11-12")
        self.assertEqual(row["axes"][5]["first_observed_day"], "2026-08-01")
        self.assertNotIn("name", row)

    def test_missing_sample_is_distinct_from_observed_zero(self):
        doc = directory()
        profile = doc["riders"][0]
        profile["history"]["latest_observed_day"] = "2026-06-30"
        profile["history_windows"]["1_year"]["latest_observed_day"] = "2026-06-30"
        profile["history_windows"]["4_months"] = period([], None, None, "2026-07-25")
        profile["history_windows"]["1_month"] = period([], None, None, "2026-10-25")
        axes = project(doc)["012345"]["axes"]
        self.assertEqual([(axis["numerator"], axis["denominator"]) for axis in axes[3:]],
                         [(None, 0)] * 3)
        self.assertIsNone(axes[3]["latest_observed_day"])

    def test_legacy_directory_can_supply_no_measured_axes(self):
        doc = directory()
        doc["riders"][0].pop("history_windows")
        self.assertIsNone(project(doc)["012345"])

    def test_rejects_window_that_omits_a_known_in_range_finish(self):
        doc = directory()
        windows = doc["riders"][0]["history_windows"]
        windows["4_months"] = period([], None, None, "2026-07-25")
        windows["1_month"] = period([], None, None, "2026-10-25")
        with self.assertRaisesRegex(ValueError, "RADAR_WINDOW_CONTAINMENT"):
            project(doc)

    def test_rejects_wrong_digest_duplicate_ids_and_impossible_window(self):
        doc = directory()
        raw = json.dumps(doc).encode()
        with self.assertRaisesRegex(ValueError, "RADAR_DIRECTORY_SHA"):
            radar.project_verified_results_radars(raw, expected_sha256="0" * 64)
        duplicates = deepcopy(doc)
        duplicates["riders"] *= 2
        with self.assertRaisesRegex(ValueError, "RADAR_REGISTRATION"):
            project(duplicates)
        doc["riders"][0]["history_windows"]["4_months"]["finish_counts"]["1"] = 4
        with self.assertRaisesRegex(ValueError, "RADAR_FINISH_COUNTS"):
            project(doc)
        nested = directory()
        window = nested["riders"][0]["history_windows"]["4_months"]
        window["finish_counts"].update({"1": 3, "5": 0, "6": 0})
        window["observed_count"] = 5
        with self.assertRaisesRegex(ValueError, "RADAR_WINDOW_CONTAINMENT"):
            project(nested)
