"""All fictional 2030 events; no official site access, payments or real forecasts."""
from copy import deepcopy
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import Mock

from race_ai.autorace_ab_pdca import (tick, audit_cycle, PHASES, _tickets)
from tests.test_comprehensive_four_sport_models import sample, obs


class AutoraceTwoStageTests(TestCase):
    def setUp(self):
        self.a = sample("autorace", size=8, scope="OPERATOR_SUPPLIED_RESEARCH")
        self.b = deepcopy(self.a)
        self.b["race"]["as_of"] = "2030-01-15T09:20:00+09:00"
        for p in self.b["participants"]:
            value = obs(.30 + p["number"] * .06)
            value["published_at"] = "2030-01-15T09:14:00+09:00"
            value["captured_at"] = "2030-01-15T09:15:00+09:00"
            p["features"]["trial_time_quality"] = value
        self.row = {
            "race_id": self.a["race"]["race_id"], "sport": "autorace",
            "venue": self.a["race"]["venue"], "race_no": 1,
            "cutoff_at": self.a["race"]["sales_cutoff_at"],
            "cutoff_verified": True, "source_permission_approved": True,
            "entrants": list(range(1, 9)), "trifecta_offered": True,
        }
        self.now = datetime.fromisoformat("2030-01-15T09:22:00+09:00")
        self.claims = {}
        self.saved = {}
        self.audits = []
        self.authorize = lambda ref, rights, purpose: (
            ref == "synthetic://fixture" and rights == "synthetic-fixture"
            and purpose == "analysis")
        self.acquire = Mock(side_effect=self._acquire)
        self.submit = Mock(side_effect=self._submit)

    def _acquire(self, race, phase):
        return {"status": "AVAILABLE", "snapshot": deepcopy(
                    self.a if phase == PHASES[0] else self.b),
                "source_rights_verified": True, "participant_ids_matched": True,
                "trial_race_bound_verified": phase == PHASES[1],
                "trial_not_published_verified": phase == PHASES[0]}

    def _readback(self, race, phase):
        return {"state": self.claims.get((race["race_id"], phase), "ABSENT")}

    def _claim(self, race, phase, forecast):
        key = (race["race_id"], phase)
        if key in self.claims:
            return {"state": "EXISTS"}
        self.claims[key] = "CLAIMED"
        return {"state": "CREATED"}

    def _submit(self, race, phase, forecast):
        key = (race["race_id"], phase)
        self.saved[key] = deepcopy(forecast)
        self.claims[key] = "UNRESOLVED_POST"
        return {"state": "SUBMITTED"}

    def _verify(self, race, phase, forecast):
        key = (race["race_id"], phase)
        if self.saved.get(key) != forecast:
            return False
        self.claims[key] = "VERIFIED"
        return True

    def run_tick(self, records=None, **kwargs):
        return tick([self.row] if records is None else records,
            clock=lambda: self.now, readback=self._readback, acquire=self.acquire,
            claim=self._claim, submit=self.submit, verify=self._verify,
            authorize_feature=self.authorize, **kwargs)

    def test_a_b_separate_real_model_suite_and_8_plus_4(self):
        result = self.run_tick()
        self.assertEqual(result["source_acquire_calls"], 2)
        self.assertEqual([s["state"] for s in result["states"]],
                         ["FROZEN_READBACK_VERIFIED_BY_ADAPTER"] * 2)
        self.assertEqual(set(self.saved), {(self.row["race_id"], p) for p in PHASES})
        pa, pb = (self.saved[(self.row["race_id"], phase)] for phase in PHASES)
        self.assertEqual(len(pa["ordered_top8"]), 8)
        self.assertEqual(len(pb["ordered_top8"]), 8)
        self.assertEqual(len(pa["supplemental_four"]), 4)
        self.assertNotEqual(pa["input_sha256"], pb["input_sha256"])
        self.assertNotEqual(pa["prediction_sha256"], pb["prediction_sha256"])
        self.assertNotIn("validated_hit_probability", pa)
        self.assertFalse(pa["estimated_probabilities_calibrated"])
        self.assertFalse(pa["formal_hit_at_8_eligible"])
        self.assertFalse(result["real_provider_polling_enabled"])
        self.assertEqual([s["state"] for s in self.run_tick()["states"]],
                         ["ALREADY_FROZEN", "ALREADY_FROZEN"])
        self.assertEqual(self.submit.call_count, 2)

    def test_unknown_source_rights_and_admission_stop_before_submit(self):
        self.acquire.side_effect = lambda row, phase: {
            **self._acquire(row, phase), "source_rights_verified": False}
        result = self.run_tick()
        self.assertEqual([x["state"] for x in result["states"]],
                         ["SOURCE_RIGHTS_OR_IDENTITY_NOT_VERIFIED"] * 2)
        self.submit.assert_not_called()

    def test_denied_independent_feature_verifier_is_not_auto_license(self):
        self.authorize = lambda *_: False
        result = self.run_tick()
        self.assertEqual([x["state"] for x in result["states"]],
                         ["MODEL_OR_PERMISSION_REJECTED"] * 2)
        self.submit.assert_not_called()

    def test_trial_must_be_participant_bound_not_page_title(self):
        self.b = deepcopy(self.a)
        result = self.run_tick()
        self.assertEqual(result["states"][1]["state"],
                         "INCOMPLETE_OR_WRONG_PHASE_SNAPSHOT")
        self.assertEqual(self.submit.call_count, 1)

    def test_a_not_issued_when_trial_publication_is_unverified(self):
        self.acquire.side_effect = lambda row, phase: {
            **self._acquire(row, phase), "trial_not_published_verified": False}
        result = self.run_tick()
        self.assertEqual(result["states"][0]["state"],
                         "PRE_TRIAL_PUBLICATION_STATE_NOT_VERIFIED")
        self.assertEqual(self.submit.call_count, 1)

    def test_pre_trial_refuses_post_trial_feature(self):
        self.a = deepcopy(self.b)
        result = self.run_tick()
        self.assertEqual(result["states"][0]["state"],
                         "INCOMPLETE_OR_WRONG_PHASE_SNAPSHOT")
        self.assertEqual(self.submit.call_count, 1)

    def test_partial_trial_missing_one_car_is_rejected(self):
        del self.b["participants"][7]["features"]["trial_time_quality"]
        result = self.run_tick()
        self.assertEqual(result["states"][1]["state"],
                         "INCOMPLETE_OR_WRONG_PHASE_SNAPSHOT")

    def test_cutoff_buffer_blocks_both(self):
        self.now = datetime.fromisoformat(self.row["cutoff_at"]) - timedelta(seconds=90)
        result = self.run_tick()
        self.assertEqual([x["state"] for x in result["states"]],
                         ["TOO_LATE_FOR_SAFE_FORECAST"] * 2)
        self.acquire.assert_not_called()

    def test_uncertain_send_does_not_resubmit_on_next_tick(self):
        self.submit.side_effect = OSError("ambiguous network response")
        first = self.run_tick()
        self.assertEqual([x["state"] for x in first["states"]],
                         ["POST_UNCERTAIN_DO_NOT_RETRY"] * 2)
        second = self.run_tick()
        self.assertEqual([x["state"] for x in second["states"]],
                         ["UNCERTAIN_OR_RESERVED_DO_NOT_REPOST"] * 2)
        self.assertEqual(self.submit.call_count, 2)

    def test_source_budget_and_unverified_cutoff_are_visible(self):
        res = self.run_tick(max_collect=1)
        self.assertEqual(res["states"][1]["state"], "SOURCE_BUDGET_DEFERRED")
        self.row["cutoff_verified"] = False
        res = self.run_tick()
        self.assertEqual([x["state"] for x in res["states"]],
                         ["SALES_CUTOFF_UNVERIFIED"] * 2)

    def _result(self, ticket, revision=1):
        return {"race_id": self.row["race_id"], "status": "FINAL_NORMAL",
                "published_at": "2030-01-15T10:05:00+09:00",
                "captured_at": "2030-01-15T10:06:00+09:00",
                "winning_triples": [ticket], "revision": revision,
                "source_sha256": ("a" if revision == 1 else "b") * 64}

    def _append(self, audit):
        self.audits.append(deepcopy(audit))
        return True

    def _latest(self, _rid):
        return deepcopy(self.audits[-1]) if self.audits else None

    def _read(self, _rid, rev):
        return deepcopy(self.audits[rev - 1])

    def run_audit(self, result, verify_forecast=None, verify_result=None):
        return audit_cycle([self.row], clock=lambda: self.now,
            load_forecast=lambda row, phase: deepcopy(
                self.saved.get((row["race_id"], phase))),
            load_result=lambda row: deepcopy(result),
            verify_forecast=verify_forecast or (lambda *args: True),
            verify_result=verify_result or (lambda *args: True),
            latest_audit=self._latest, append_audit=self._append,
            read_audit=self._read)

    def test_result_pdca_and_corrected_result_create_append_only_revision(self):
        self.run_tick()
        self.now = datetime.fromisoformat("2030-01-15T11:00:00+09:00")
        pick = self.saved[(self.row["race_id"], PHASES[0])]["ordered_top8"][0]
        r1 = self.run_audit(self._result(pick))
        self.assertEqual(r1["events"][0]["state"], "AUDIT_APPENDED_AND_READBACK")
        self.assertEqual(r1["kpis"][PHASES[0]]["evaluable_races"], 1)
        self.assertEqual(r1["kpis"][PHASES[0]]["hit1_all"], 1)
        self.assertEqual(r1["kpis"][PHASES[0]]["hit8_all"], 1)
        self.assertEqual(r1["kpis"][PHASES[0]]["hit12_all_experimental"], 1)
        self.assertEqual(self.run_audit(self._result(pick))["events"][0]["state"],
                         "ALREADY_SAVED")
        other = [8, 7, 6] if pick != [8, 7, 6] else [7, 6, 5]
        r2 = self.run_audit(self._result(other, revision=2))
        self.assertEqual(r2["events"][0]["revision"], 2)
        self.assertEqual(len(self.audits), 2)
        self.assertEqual(self.audits[1]["previous_sha256"], self.audits[0]["sha256"])
        self.assertEqual(len(self.saved), 2)  # A/B originals never change
        self.assertFalse(r2["events"][0]["report"]["automatic_model_promoted"])

    def test_missing_b_is_counted_in_all_evaluable_races(self):
        self.run_tick(max_collect=1)  # Only A
        self.now = datetime.fromisoformat("2030-01-15T11:00:00+09:00")
        r = self.run_audit(self._result([8, 7, 6]))
        self.assertEqual(r["kpis"][PHASES[1]]["evaluable_races"], 1)
        self.assertEqual(r["kpis"][PHASES[1]]["hit8_all"], 0)
        self.assertEqual(r["events"][0]["report"]["B"]["status"], "NO_FORECAST")

    def test_unverified_result_and_pre_cutoff_result_never_scored(self):
        self.run_tick()
        self.now = datetime.fromisoformat("2030-01-15T11:00:00+09:00")
        bad = self.run_audit(self._result([8,7,6]),
                             verify_result=lambda *args: False)
        self.assertEqual(bad["events"][0]["state"], "RESULT_OR_AUDIT_UNVERIFIED_NO_REPOST")
        self.assertEqual(bad["kpis"][PHASES[0]]["evaluable_races"], 0)
        forged = self._result([8,7,6])
        forged["published_at"] = "2030-01-15T09:59:00+09:00"
        self.assertEqual(self.run_audit(forged)["events"][0]["state"],
                         "RESULT_OR_AUDIT_UNVERIFIED_NO_REPOST")

    def test_unverified_freeze_cannot_be_promoted_to_a_hit(self):
        self.run_tick()
        self.now = datetime.fromisoformat("2030-01-15T11:00:00+09:00")
        choice = self.saved[(self.row["race_id"], PHASES[0])]["ordered_top8"][0]
        report = self.run_audit(self._result(choice), verify_forecast=lambda *args: False)
        self.assertEqual(report["kpis"][PHASES[0]]["hit8_all"], 0)
        self.assertEqual(report["events"][0]["report"]["A"]["status"],
                         "UNVERIFIED_FREEZE_RECEIPT")

    def test_result_pending_not_a_missed_forecast(self):
        self.run_tick()
        self.now = datetime.fromisoformat("2030-01-15T11:00:00+09:00")
        pending = self._result([8,7,6])
        pending["status"] = "PENDING"
        pending["winning_triples"] = []
        result = self.run_audit(pending)
        self.assertEqual(result["kpis"][PHASES[0]]["evaluable_races"], 0)
        self.assertEqual(result["events"][0]["report"]["A"]["hit8"], None)


if __name__ == "__main__":
    import unittest
    unittest.main()
