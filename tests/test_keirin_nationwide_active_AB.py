"""Source-free nationwide test. All lineups/results/callback approvals here are FAKE.

The real full-day roster is the 2026-11-18 79-race registered JSON. Tests
do not claim 79 real forecasts or 79 result settlements.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from race_ai import keirin_nationwide_active_AB as nationwide

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json"
AT="2026-11-18T07:25:00+09:00"
CUT="2026-11-18T20:45:00+09:00"
RACE="202611182401"  # Utsunomiya1R, 6 riders in actual event.


def data():
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def ready(registry=None, **changes):
    kw={
        "registry":registry or data(),"race_id":RACE,"inspected_at":AT,
        "source_input_sha256":"a"*64,
        "source_available_at":"2026-11-18T07:10:00+09:00",
        "official_cutoff_at":CUT,
        "verified_field_count":21,
        "starters":[1,2,3,4,5,6],
        "competition":"CHALLENGE",
        "independent_source_admission":lambda *args:True,
        "independent_cutoff_admission":lambda *args:True,
    }
    kw.update(changes)
    return nationwide.register_source_ready_receipt(**kw)


class NationwideAllRacesContract(unittest.TestCase):
    def test_real_roster_79_eight_venues_including_29_missing_from_standard_index(self):
        x=data()
        self.assertIs(nationwide.checked_registry(x),x)
        self.assertEqual(len(x["records"]),79)
        self.assertEqual(
            {k:sum(r["venue_code"]==k for r in x["records"])
             for k in nationwide.EXPECTED},
            {k:n for k,(_,n) in nationwide.EXPECTED.items()})
        self.assertEqual(sum(x["records"][i]["session"]=="MIDNIGHT"
                             for i in range(79)),18)
        self.assertEqual(sum(r["venue_code"]=="38" for r in x["records"]),11)
        self.assertEqual(
            sum(r["venue_code"] in {"38","24","74"} for r in x["records"]),29)
        self.assertFalse(x["old_four_model_PR71_required"])

    def test_50_standard_only_is_not_nationwide(self):
        x=data()
        x["records"]=[v for v in x["records"]
                      if v["venue_code"] not in ("38","24","74")]
        x["scope_race_count"]=50
        with self.assertRaisesRegex(
                nationwide.NationwideABError,"NATIONWIDE_REGISTRY"):
            nationwide.checked_registry(x)

    def test_all_79_have_a_persistent_HOLD_even_without_models(self):
        x=data()
        report=nationwide.summarize_all(registry=x,verified_receipts=[])
        self.assertEqual(report["cohort_race_count"],79)
        self.assertEqual(report["unreported_races"],79)
        self.assertEqual(report["statuses"],{"HOLD_UNREPORTED":79})
        self.assertTrue(report["unreported_or_held_never_counted_as_miss"])
        self.assertFalse(report["PR71_shared_four_models_required"])

    def test_six_rider_and_girls_supported_as_RACE_NOT_A_PREDICTION(self):
        result=ready()
        self.assertEqual(result["state"],"VERIFIED_SOURCE_READY_FOR_NEW_A_AND_B")
        self.assertEqual(result["starter_count"],6)
        self.assertFalse(result["is_model_A_generated"])
        self.assertFalse(result["is_model_B_generated"])
        result=ready(race_id="202611188103",
                     starters=list(range(1,8)),competition="GIRLS")
        self.assertEqual(result["state"],"VERIFIED_SOURCE_READY_FOR_NEW_A_AND_B")
        self.assertEqual(result["competition"],"GIRLS")

    def test_cutoff_missing_keeps_all_79_and_does_not_guess(self):
        result=ready(official_cutoff_at=None)
        self.assertEqual(result["state"],"HOLD_NO_INDEPENDENT_CUTOFF")
        report=nationwide.summarize_all(registry=data(),verified_receipts=[result])
        self.assertEqual(report["statuses"],
                         {"HOLD_NO_INDEPENDENT_CUTOFF":1,"HOLD_UNREPORTED":78})

    def test_source_not_verified_or_missing_is_not_forecast(self):
        for flags in (
            {"independent_source_admission":None},
            {"source_input_sha256":"not-sha"},
            {"starters":[]},
            {"verified_field_count":0},
        ):
            with self.subTest(flags=flags):
                result=ready(**flags)
                self.assertEqual(result["state"],"HOLD_MISSING_RACE_INPUT")
                self.assertFalse(result["eligible_to_attempt_AB"])

    def test_deadline_65_seconds_and_source_time_cut(self):
        result=ready(inspected_at="2026-11-18T20:44:00+09:00")
        self.assertEqual(result["state"],"HOLD_AFTER_DEADLINE")
        result=ready(source_available_at="2026-11-18T21:00:00+09:00")
        self.assertEqual(result["state"],"HOLD_AFTER_DEADLINE")

    def test_wrong_race_duplicate_and_changed_venue_cannot_be_admitted(self):
        x=data()
        x["records"][-1]["race_id"]=x["records"][0]["race_id"]
        with self.assertRaisesRegex(
                nationwide.NationwideABError,"RACE_ID_VENUE_DAY_MISMATCH"):
            nationwide.checked_registry(x)
        with self.assertRaisesRegex(
                nationwide.NationwideABError,"SOURCE_RACE_OUTSIDE"):
            ready(race_id="202611189901")

    def test_truth_requires_external_reader_after_source_ready(self):
        candidate=ready()
        out=nationwide.summarize_all(
            registry=data(),verified_receipts=[candidate])
        self.assertEqual(
            out["statuses"]["HOLD_RECEIPT_NOT_INDEPENDENTLY_VERIFIED"],1)
        verified=nationwide.summarize_all(
            registry=data(),verified_receipts=[candidate],
            independent_receipt_reader=lambda r:True)
        self.assertEqual(
            verified["statuses"]["VERIFIED_SOURCE_READY_A_B_NOT_YET_GENERATED"],1)
        self.assertEqual(verified["statuses"]["HOLD_UNREPORTED"],78)

    def test_fabricated_model_success_requires_independent_proof(self):
        row=ready()
        row["state"]="A_B_SETTLED_OFFICIAL"
        out=nationwide.summarize_all(
            registry=data(),verified_receipts=[row])
        self.assertEqual(
            out["statuses"]["HOLD_RECEIPT_NOT_INDEPENDENTLY_VERIFIED"],1)
        self.assertNotIn("A_B_SETTLED_OFFICIAL",out["statuses"])

    def test_duplicate_reports_cannot_hide_an_omitted_race(self):
        row=ready()
        with self.assertRaisesRegex(
                nationwide.NationwideABError,"DUPLICATE"):
            nationwide.summarize_all(
                registry=data(),verified_receipts=[row,row])


if __name__=="__main__":
    unittest.main()
