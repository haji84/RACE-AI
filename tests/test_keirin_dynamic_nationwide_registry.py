"""No real source attestations here: synthetic callback contracts ONLY."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from race_ai import keirin_dynamic_nationwide_registry as dyn

DAY="2026-11-18"
REGISTRY=(Path(__file__).resolve().parents[1]/
  "docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json")
STAMP="2026-11-18T07:30:00+09:00"


def fake_blocks():
    registered=json.loads(REGISTRY.read_text(encoding="utf-8"))
    return [
        {"venue":v["name"],"venue_code":v["code"],"grade":v["grade"],
         "source_url":v["source"],
         "source_bytes_sha256":v["code"]*32,
         "source_available_at":"2026-11-18T06:00:00+09:00",
         "race_numbers":list(range(1,v["count"]+1)),
         "source_race_day":DAY}
        for v in registered["venues"]]


def make(blocks=None,universe=None,venue=lambda x:True,day=lambda *args:True):
    x=blocks if blocks is not None else fake_blocks()
    u=universe if universe is not None else [row["venue_code"] for row in x]
    return dyn.create_day(
        day_jst=DAY,registered_at=STAMP,venue_snapshots=x,
        expected_venue_codes=u,
        independently_verify_venue_snapshot=venue,
        independently_verify_whole_day=day)


class DynamicNationwideCalendar(unittest.TestCase):
    def test_actual_day_79_roster_can_be_admitted_through_explicit_universe(self):
        v=make()
        dyn.checked_day(v)
        self.assertEqual(v["captured_race_count"],79)
        self.assertEqual(v["captured_venue_count"],8)
        self.assertTrue(v["nationwide_coverage_independently_verified"])
        self.assertTrue(v["source_free_and_private_values_not_published"])
        self.assertFalse(v["old_PR71_four_model_dependency"])

    def test_absent_morning_or_midnight_is_never_silently_called_complete(self):
        sources=[s for s in fake_blocks() if s["venue_code"] not in ("24","74")]
        v=make(blocks=sources)
        self.assertEqual(v["captured_race_count"],61)
        self.assertTrue(v["nationwide_coverage_independently_verified"])
        self.assertFalse(v["national_universe_unverified_hold"])
        # A self-selected set of venues is NOT proof of the full universe.
        v=make(blocks=sources,day=None)
        self.assertFalse(v["nationwide_coverage_independently_verified"])
        self.assertTrue(v["national_universe_unverified_hold"])

    def test_expected_eight_but_source_has_six_rejected(self):
        codes=[s["venue_code"] for s in fake_blocks()]
        sources=fake_blocks()[:6]
        with self.assertRaisesRegex(dyn.DynamicDayError,"MISSING_AN_EXPECTED"):
            make(blocks=sources,universe=codes)

    def test_different_day_and_venues_not_hardcoded_to_79(self):
        blocks=[{"venue":"架空競輪場","venue_code":"01",
            "grade":"F2","source_url":"https://example.org/public-race-day",
            "source_bytes_sha256":"a"*64,
            "source_available_at":"2026-11-19T06:00:00+09:00",
            "race_numbers":[1,2,3,4,5,6,7],
            "source_race_day":"2026-11-19"}]
        reg=dyn.create_day(
            day_jst="2026-11-19",registered_at="2026-11-19T06:30:00+09:00",
            venue_snapshots=blocks,expected_venue_codes=["01"],
            independently_verify_venue_snapshot=lambda x:True,
            independently_verify_whole_day=lambda *args:True)
        self.assertEqual(reg["captured_race_count"],7)
        dyn.checked_day(reg)
        self.assertEqual(reg["races"][0]["race_id"],"202611190101")
        self.assertEqual(reg["races"][-1]["race_id"],"202611190107")

    def test_missing_independent_source_bytes_refused(self):
        with self.assertRaisesRegex(dyn.DynamicDayError,
                                    "NOT_INDEPENDENTLY_AUTHENTICATED"):
            make(venue=None)

    def test_no_verified_whole_day_is_HOLD_not_claim_of_complete(self):
        r=make(day=None)
        self.assertFalse(r["nationwide_coverage_independently_verified"])
        self.assertTrue(r["national_universe_unverified_hold"])
        self.assertEqual(r["captured_race_count"],79)

    def test_source_not_available_at_registration_refused(self):
        b=fake_blocks()
        b[0]["source_available_at"]="2026-11-18T07:31:00+09:00"
        with self.assertRaisesRegex(dyn.DynamicDayError,
                                    "SOURCE_NOT_AVAILABLE_BEFORE"):
            make(blocks=b)

    def test_registration_digest_detects_later_race_insertion(self):
        reg=make()
        reg["races"][0]["A_forecast"]="FORGED_HIT_AFTER_RESULT"
        with self.assertRaisesRegex(dyn.DynamicDayError,
                                    "IMMUTABLE_SHA_CHANGED"):
            dyn.checked_day(reg)

    def test_duplicate_venue_or_race_cannot_enter(self):
        blocks=fake_blocks()
        blocks[1]["venue_code"]=blocks[0]["venue_code"]
        with self.assertRaisesRegex(dyn.DynamicDayError,
                                    "VENUE_SOURCE_CODE_RACE_UNIVERSE_INVALID"):
            make(blocks=blocks)

    def test_guest_unknown_source_does_not_create_false_A_or_B_predictions(self):
        doc=make()
        self.assertEqual(doc["actual_forecasts_created_by_registration"],0)
        self.assertTrue(all(row["A_forecast"]=="NO_FORECAST" and
                            row["B_six_phase_forecast"]=="NO_FORECAST"
                            for row in doc["races"]))


if __name__=="__main__":
    unittest.main()
