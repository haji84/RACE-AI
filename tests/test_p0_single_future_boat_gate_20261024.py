"""Only fictional response bytes and an injected parser. No external network."""
from datetime import datetime, timezone
import unittest

from scripts.p0_single_future_boat_gate_20261024 import (
    BRANCH, TOKEN, DAY, RACE, TARGET, EXPECTED_REGISTRATIONS,
    EXPECTED_PUBLISHED_SCHEDULE, pre_cutoff_gate,
)

GOOD_ENV = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": BRANCH,
            "RACE_AI_B_LIVE_ONE_SHOT": TOKEN, "GITHUB_SHA": "a" * 40}
BEFORE = datetime.fromisoformat("2026-10-24T12:00:00+09:00")
AFTER = datetime.fromisoformat("2026-10-24T15:11:00+09:00")


class DummyResponse:
    status = 200
    headers = {"Date": "Sat, 24 Oct 2026 02:00:00 GMT"}

    def geturl(self):
        return TARGET

    def read(self, size):
        return b"\x16\x00-lh5-" + b"X" * 100

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DummyClient:
    def __init__(self):
        self.count = 0

    def open(self, req, timeout):
        assert req.full_url == TARGET and timeout == 10
        self.count += 1
        return DummyResponse()


def parser(_bytes):
    entrants = [{"race_id": RACE, "lane": i, "racer_id": racer}
                for i, racer in enumerate(EXPECTED_REGISTRATIONS, 1)]
    details = {(RACE, i): {"racer_registration_id": racer,
                          "motor_no": i + 11, "boat_no": i + 21,
                          "national_win_rate": 5.1 + .1 * i,
                          "local_win_rate": 4.4 + .1 * i,
                          "motor_top2_rate": 28.0 + i}
               for i, racer in enumerate(EXPECTED_REGISTRATIONS, 1)}
    return entrants, details, {RACE: EXPECTED_PUBLISHED_SCHEDULE}


class FutureSourceGateTests(unittest.TestCase):
    def test_exact_injected_one_get_and_no_forecast_when_metadata_unknown(self):
        client = DummyClient()
        result = pre_cutoff_gate(env=GOOD_ENV, opener=client,
                                 extractor=lambda _raw, _name: b"fixture",
                                 parser=parser, now=BEFORE)
        self.assertEqual(client.count, 1)
        self.assertEqual(result["status"], "NO_FORECAST_B_LITE_INPUT_EVIDENCE_INSUFFICIENT")
        self.assertEqual(result["real_B_candidate_count_for_selected_race"], 18)
        self.assertEqual(result["real_B_feature_admitted_count"], 0)
        self.assertIsNone(result["prediction_sha256"])
        self.assertFalse(result["external_freeze_verified"])
        self.assertFalse(result["formal_hit_at_8_eligible"])

    def test_if_gate_starts_late_no_provider_request(self):
        client = DummyClient()
        result = pre_cutoff_gate(env=GOOD_ENV, opener=client, parser=parser, now=AFTER)
        self.assertEqual(client.count, 0)
        self.assertIn("AFTER_PUBLISHED_CUTOFF", result["status"])

    def test_invalid_branch_rejects_before_network(self):
        client = DummyClient()
        invalid = dict(GOOD_ENV)
        invalid["GITHUB_REF"] = "refs/heads/main"
        with self.assertRaisesRegex(ValueError, "one-shot"):
            pre_cutoff_gate(env=invalid, opener=client, now=BEFORE)
        self.assertEqual(client.count, 0)

    def test_wrong_race_identity_or_cutoff_does_not_create_prediction(self):
        client = DummyClient()
        def wrong(_):
            entrants, details, cutoff = parser(_)
            return entrants, details, {RACE: "2026-10-24T15:10:00+09:00"}
        report = pre_cutoff_gate(env=GOOD_ENV, opener=client,
                                  extractor=lambda *_: b"fixture",
                                  parser=wrong, now=BEFORE)
        self.assertEqual(client.count, 1)
        self.assertEqual(report["status"], "NO_FORECAST_SOURCE_OR_IDENTITY_VALIDATION_FAILED")
        self.assertIsNone(report["prediction_sha256"])

    def test_wrong_registration_rejected(self):
        client = DummyClient()
        def wrong(_):
            entrants, details, cutoff = parser(_)
            entrants[0] = dict(entrants[0], racer_id="9999")
            return entrants, details, cutoff
        result = pre_cutoff_gate(env=GOOD_ENV, opener=client,
                                  extractor=lambda *_: b"fixture", parser=wrong,
                                  now=BEFORE)
        self.assertFalse(result.get("official_racelist_consistency", True))
        self.assertIsNone(result["prediction_sha256"])


if __name__ == "__main__":
    unittest.main()
