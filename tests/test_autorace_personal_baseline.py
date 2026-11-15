"""Reproducible fictional figures; NOT real driver records or verified odds."""
import copy
from datetime import datetime
import itertools
import math
import os
from pathlib import Path
import tempfile
import unittest

from race_ai.autorace_personal_baseline import (
    SOURCE_SCHEMA, MODEL_ID, ObservedInputError, predict_personal,
    preview_personal_result,
)
from race_ai.autorace_ab_pdca import PHASES
from race_ai.comprehensive_four_sport_models import digest


def sample(phase=PHASES[0], count=8):
    stage_b = phase == PHASES[1]
    return {
        "schema": SOURCE_SCHEMA,
        "entry_kind": "USER_OBSERVED_MANUAL",
        "race": {
            "race_id": "autorace:2030-01-15:fictional-track:1",
            "venue": "fictional-track",
            "race_no": 1,
            "event_date_jst": "2030-01-15",
            "sales_cutoff_at": "2030-01-15T10:00:00+09:00",
            "as_of_at": "2030-01-15T09:19:00+09:00" if stage_b
                        else "2030-01-15T09:10:00+09:00",
            "phase": phase,
            "source_url": "https://example.test/fictional-program",
            "source_captured_at": "2030-01-15T09:11:00+09:00" if stage_b
                                  else "2030-01-15T09:01:00+09:00",
        },
        "drivers": [
            {
                "car_no": n,
                "handicap_m": (n - 1) * 10,
                "recent_finishes": [1 + (n + j) % 8 for j in range(5)],
                "trial_seconds": round(3.19 + (9 - n)*.025, 3) if stage_b else None,
                "trial_observed_at": "2030-01-15T09:16:00+09:00"
                                     if stage_b else None,
            }
            for n in range(1, count + 1)
        ],
    }


class PersonalObservedTests(unittest.TestCase):
    def test_a_b_independent_and_all_combinations_ranked(self):
        a = sample()
        b = sample(PHASES[1])
        before_a, before_b = copy.deepcopy(a), copy.deepcopy(b)
        first = predict_personal(a, generated_at="2030-01-15T09:22:00+09:00")
        second = predict_personal(b, generated_at="2030-01-15T09:22:00+09:00")
        self.assertEqual(a, before_a)
        self.assertEqual(b, before_b)
        self.assertEqual(first["model_id"], MODEL_ID)
        self.assertEqual(first["phase"], PHASES[0])
        self.assertEqual(second["phase"], PHASES[1])
        self.assertNotEqual(first["input_sha256"], second["input_sha256"])
        self.assertNotEqual(first["prediction_sha256"], second["prediction_sha256"])
        self.assertEqual(first["candidate_count"], 8*7*6)
        self.assertEqual(len(first["ranked_relative_weights"]), 8*7*6)
        self.assertEqual({tuple(x["combination"])
                          for x in first["ranked_relative_weights"]},
                         set(itertools.permutations(range(1,9), 3)))
        self.assertAlmostEqual(math.fsum(
            x["relative_weight"] for x in first["ranked_relative_weights"]), 1)
        for forecast in [first,second]:
            self.assertEqual(len(forecast["ordered_top8"]), 8)
            self.assertEqual(len(forecast["supplemental_four"]), 4)
            self.assertEqual(len({tuple(x) for x in forecast["ordered_top8"] +
                                  forecast["supplemental_four"]}),12)
            self.assertFalse(forecast["formal_hit_at_8_eligible"])
            self.assertFalse(forecast["estimated_probabilities_calibrated"])
            self.assertIsNone(forecast["external_pre_cutoff_receipt"])
            self.assertFalse(forecast["source_first_publication_verified"])
            self.assertFalse(forecast["official_prediction"])
            self.assertEqual(forecast["prediction_sha256"], digest({
                k:v for k,v in forecast.items() if k!="prediction_sha256"
            }))
            self.assertNotIn("odds", str(forecast))
            self.assertNotIn("official_ai", str(forecast))

    def test_no_trial_for_a_full_trial_required_for_b(self):
        raw = sample()
        raw["drivers"][0]["trial_seconds"] = 3.21
        with self.assertRaisesRegex(ObservedInputError, "TRIAL_CANNOT"):
            predict_personal(raw,generated_at="2030-01-15T09:22:00+09:00")
        b=sample(PHASES[1])
        b["drivers"][-1]["trial_seconds"] = None
        with self.assertRaisesRegex(ObservedInputError, "COMPLETE_TRIAL"):
            predict_personal(b,generated_at="2030-01-15T09:22:00+09:00")

    def test_wrong_dates_missing_history_duplicate_and_unwanted_features(self):
        for change in (
            lambda s: s["race"].update(event_date_jst="2030-01-14"),
            lambda s: s["drivers"][0].update(recent_finishes=[]),
            lambda s: s["drivers"][0].update(car_no=2),
            lambda s: s["drivers"][0].update(odds=2.5),
            lambda s: s["race"].update(official_ai_picks=[1,2,3]),
            lambda s: s.update(results={"1": [1,2,3]}),
        ):
            raw=sample()
            change(raw)
            with self.subTest(change=change):
                with self.assertRaises(ObservedInputError):
                    predict_personal(raw,generated_at="2030-01-15T09:22:00+09:00")

    def test_deadline_and_out_of_order_evidence(self):
        for time in ("2030-01-15T10:00:00+09:00",
                     "2030-01-15T09:59:00+09:00",
                     "2030-01-15T09:05:00+09:00"):
            with self.subTest(time=time):
                with self.assertRaises(ObservedInputError):
                    predict_personal(sample(),generated_at=time)
        bad=sample(PHASES[1])
        bad["drivers"][0]["trial_observed_at"]="2030-01-15T09:23:00+09:00"
        with self.assertRaisesRegex(ObservedInputError, "TRIAL_CAPTURE_TIME"):
            predict_personal(bad,generated_at="2030-01-15T09:22:00+09:00")

    def test_ties_and_small_fields_are_handled_without_fake_numbers(self):
        data=sample(PHASES[1],count=3)
        for row in data["drivers"]: row["trial_seconds"]=3.33
        out=predict_personal(data,generated_at="2030-01-15T09:22:00+09:00")
        self.assertEqual(out["candidate_count"],6)
        self.assertEqual(len(out["ordered_top8"]),6)
        self.assertEqual(out["supplemental_four"],[])

    def test_result_is_separate_and_only_personal_unverified_preview(self):
        pred=predict_personal(sample(),generated_at="2030-01-15T09:22:00+09:00")
        result={"race_id":pred["race_id"],"winning_order":pred["ordered_top8"][0],
                "source_url":"https://example.test/fictional-results",
                "captured_at":"2030-01-15T10:10:00+09:00"}
        original=copy.deepcopy(pred)
        evaluated=preview_personal_result(pred,result,observed_at="2030-01-15T10:12:00+09:00")
        self.assertEqual(evaluated["hit1_personal"],1)
        self.assertEqual(evaluated["hit8_personal"],1)
        self.assertEqual(evaluated["hit12_personal_experimental"],1)
        self.assertEqual(evaluated["classification"],"USER_RECORDED_UNVERIFIED_RESEARCH")
        self.assertFalse(evaluated["formal_hit_at_8_eligible"])
        self.assertEqual(original,pred)
        altered=copy.deepcopy(pred)
        altered["ordered_top8"][0]=[8,7,6]
        with self.assertRaisesRegex(ObservedInputError,"FORECAST_NOT_INTACT"):
            preview_personal_result(altered,result,observed_at="2030-01-15T10:12:00+09:00")
        result["captured_at"]="2030-01-15T09:59:00+09:00"
        with self.assertRaisesRegex(ObservedInputError,"RESULT_PRE_CUTOFF"):
            preview_personal_result(pred,result,observed_at="2030-01-15T10:12:00+09:00")

    @unittest.skipUnless(os.name == "posix","POSIX private filesystem required")
    def test_baseline_stores_in_existing_private_journal_without_fake_attestation(self):
        from race_ai.autorace_private_store import LocalPrivateJournal
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"private"
            journal=LocalPrivateJournal(p/"journal.sqlite")
            a=predict_personal(sample(),generated_at="2030-01-15T09:22:00+09:00")
            b=predict_personal(sample(PHASES[1]),generated_at="2030-01-15T09:22:00+09:00")
            for original in (a,b):
                phase=original["phase"]
                self.assertEqual(journal.claim(original["race_id"],phase,original)["state"],"CREATED")
                self.assertEqual(journal.submit_once(original["race_id"],phase,original)["state"],"SUBMITTED")
                self.assertEqual(journal.original(original["race_id"],phase,MODEL_ID),original)
                self.assertEqual(journal.readback(original["race_id"],phase,MODEL_ID)["state"],
                                 "UNRESOLVED_POST")
                self.assertEqual(journal.claim(original["race_id"],phase,original)["state"],"EXISTS")
                self.assertFalse(journal.attest(original["race_id"],phase,original,
                                                {"fake":True},lambda *args: False))
                with self.assertRaises(ValueError):
                    journal.submit_once(original["race_id"],phase,original)
            restarted=LocalPrivateJournal(p/"journal.sqlite")
            self.assertEqual(restarted.original(a["race_id"],PHASES[0],MODEL_ID),a)
            self.assertEqual(restarted.original(b["race_id"],PHASES[1],MODEL_ID),b)


if __name__=="__main__":
    unittest.main()
