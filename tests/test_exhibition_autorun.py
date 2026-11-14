"""Synthetic-only fail-closed tests for post-exhibition runner orchestration.

The fabricated OPERATOR_SUPPLIED_RESEARCH data are TEST DOUBLES, not licensed
provider observations. No real data, external clock, cloud writes or money.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock

from race_ai.exhibition_autorun import tick, MARGIN
from race_ai.cutoff_job_queue import QueueError
from tests.test_boat_multi_feature_models import fixture


class ExhibitionTickTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = fixture()
        # Test-mode stand-in for the future approved input adapter. The test
        # does NOT authenticate actual source rights or provider publication.
        self.snapshot["scope"] = "OPERATOR_SUPPLIED_RESEARCH"
        self.race = {"sport": "boat", "race_id": self.snapshot["race_id"],
                     "cutoff_at": self.snapshot["sales_cutoff_at"],
                     "cutoff_verified": True,
                     "source_permission_approved": True}
        self.now = datetime.fromisoformat("2030-04-01T10:43:00+09:00")
        self.clock = Mock(side_effect=lambda: self.now)
        self.readback = Mock(return_value={"state": "ABSENT"})
        self.acquire = Mock(return_value=self.available())
        self.claim = Mock(return_value={"state": "CREATED"})
        self.submit = Mock(return_value={"state": "SUBMITTED"})
        self.verify = Mock(return_value=True)

    def available(self):
        return {"status": "AVAILABLE", "snapshot": self.snapshot,
                "source_rights_verified": True,
                "exhibition_identity_verified": True}

    def call(self, rows=None, **kwargs):
        return tick(rows if rows is not None else [self.race],
                    clock=self.clock, readback=self.readback,
                    acquire=self.acquire, claim=self.claim,
                    submit=self.submit, verify=self.verify, **kwargs)

    def state(self, data):
        return data["results"][0]["state"]

    def test_one_synthetic_e2e_reuses_existing_odds_free_model(self):
        output = self.call()
        self.assertEqual(self.state(output), "FROZEN_READBACK_VERIFIED")
        self.assertEqual(output["source_fetch_count"], 1)
        self.assertEqual(output["total_races"], 1)
        result = output["results"][0]
        self.assertEqual(len(result["ordered_top8"]), 8)
        self.assertEqual(len({tuple(x) for x in result["ordered_top8"]}), 8)
        self.assertRegex(result["prediction_sha256"], r"^[0-9a-f]{64}$")
        self.assertIs(result["prediction_probabilities_calibrated"], False)
        self.assertIs(output["live_scheduling_enabled"], False)
        self.claim.assert_called_once()
        self.submit.assert_called_once()
        self.verify.assert_called_once()

    def test_pending_and_absent_exhibition_are_not_predictions(self):
        for status, expected in (("PENDING", "EXHIBITION_PENDING"),
                                 ("UNAVAILABLE", "EXHIBITION_UNAVAILABLE"),
                                 ("RIGHTS_BLOCKED", "EXHIBITION_RIGHTS_BLOCKED")):
            with self.subTest(status=status):
                self.acquire.return_value = {"status": status}
                self.assertEqual(self.state(self.call()), expected)
                self.claim.assert_not_called()
                self.submit.assert_not_called()
        self.acquire.return_value = self.available()
        self.snapshot["entrants"][0]["features"]["exhibition_time_seconds"] = None
        self.assertEqual(self.state(self.call()), "EXHIBITION_INCOMPLETE")
        self.submit.assert_not_called()

    def test_no_second_attempt_after_reserved_or_ambiguous_post(self):
        self.submit.side_effect = OSError("unacknowledged transport")
        self.assertEqual(self.state(self.call()), "POST_UNCERTAIN_DO_NOT_RETRY")
        self.assertEqual(self.submit.call_count, 1)
        self.readback.return_value = {"state": "UNRESOLVED_POST"}
        self.assertEqual(self.state(self.call()), "UNCERTAIN_OR_RESERVED_DO_NOT_REPOST")
        self.assertEqual(self.submit.call_count, 1)

    def test_existing_frozen_is_not_regenerated_or_posted(self):
        for state, expected in (("VERIFIED", "ALREADY_FROZEN"),
                                ("CLAIMED", "UNCERTAIN_OR_RESERVED_DO_NOT_REPOST")):
            with self.subTest(state=state):
                self.readback.return_value = {"state": state}
                self.assertEqual(self.state(self.call()), expected)
                self.acquire.assert_not_called()
                self.submit.assert_not_called()

    def test_unreadable_receipt_never_posts(self):
        self.readback.side_effect = OSError("down")
        self.assertEqual(self.state(self.call()), "READBACK_UNAVAILABLE")
        self.acquire.assert_not_called()
        self.submit.assert_not_called()

    def test_permissions_identity_and_synthetic_scope_rejected(self):
        for field in ("source_rights_verified", "exhibition_identity_verified"):
            with self.subTest(field=field):
                self.acquire.return_value = {**self.available(), field: False}
                self.assertEqual(self.state(self.call()), "SOURCE_EVIDENCE_NOT_VERIFIED")
                self.submit.assert_not_called()
        self.acquire.return_value = self.available()
        self.snapshot["scope"] = "SYNTHETIC_ONLY"
        self.assertEqual(self.state(self.call()), "SOURCE_RACE_OR_CLOCK_MISMATCH")
        self.submit.assert_not_called()

    def test_market_data_or_invalid_source_identity_never_posts(self):
        self.snapshot["entrants"][0]["features"]["odds"] = 2.4
        self.assertEqual(self.state(self.call()), "MODEL_INPUT_REJECTED")
        self.submit.assert_not_called()
        del self.snapshot["entrants"][0]["features"]["odds"]
        self.snapshot["race_id"] = "boat:2030-04-01:synthetic:2"
        self.assertEqual(self.state(self.call()), "SOURCE_RACE_OR_CLOCK_MISMATCH")
        self.submit.assert_not_called()

    def test_cutoff_margin_blocks_late_dispatched_and_late_claimed(self):
        self.now = datetime.fromisoformat(self.race["cutoff_at"]) - MARGIN
        self.assertEqual(self.state(self.call()), "TOO_LATE_FOR_SAFE_FORECAST")
        self.acquire.assert_not_called()
        self.submit.assert_not_called()
        self.now = datetime.fromisoformat("2030-04-01T10:43:00+09:00")
        def consume_margin(_race, _forecast):
            self.now = datetime.fromisoformat(self.race["cutoff_at"]) - MARGIN
            return {"state": "CREATED"}
        self.claim.side_effect = consume_margin
        self.assertEqual(self.state(self.call()), "CLAIMED_BUT_TOO_LATE_NO_POST")
        self.submit.assert_not_called()

    def test_multiple_cutoffs_run_earliest_first_and_finite_budget(self):
        first = deepcopy(self.race)
        first["race_id"] = "boat:2030-04-01:synthetic:2"
        first["cutoff_at"] = "2030-04-01T10:50:00+09:00"
        self.acquire.return_value = {"status": "PENDING"}
        res = self.call([self.race, first], max_collect=1)
        self.assertEqual([r["race_id"] for r in res["results"]],
                         [first["race_id"], self.race["race_id"]])
        self.assertEqual([r["state"] for r in res["results"]],
                         ["EXHIBITION_PENDING", "FETCH_BUDGET_EXCEEDED"])
        self.assertEqual(res["source_fetch_count"], 1)
        self.assertEqual(self.acquire.call_count, 1)
        self.submit.assert_not_called()

    def test_reject_duplicate_races_and_unverified_cutoff(self):
        with self.assertRaises(QueueError):
            self.call([self.race, self.race])
        self.race["cutoff_verified"] = False
        self.assertEqual(self.state(self.call()), "SALES_CUTOFF_UNVERIFIED")
        self.readback.assert_not_called()
        self.submit.assert_not_called()

    def test_unverified_model_probability_cannot_be_advertised_as_calibrated(self):
        out = self.call()
        self.assertIs(out["results"][0]["prediction_probabilities_calibrated"], False)
        self.assertNotIn("validated_hit_probability", out["results"][0])


if __name__ == "__main__":
    unittest.main()
