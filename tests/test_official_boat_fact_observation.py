"""Actual public BOAT RACE facts are metadata, NOT a frozen forecast.

Fictional manipulation tests demonstrate strict boundary behavior.
"""
import copy,json,unittest
from pathlib import Path
from race_ai.official_boat_fact_observation import convert,IntakeError

REAL=Path(__file__).resolve().parents[1]/"docs/evidence/2026-10-24-biwako-1r-official-facts.json"

class RealFactObservationTests(unittest.TestCase):
    def setUp(self):
        self.observation=json.loads(REAL.read_text(encoding="utf-8"))
    def test_real_source_20261024_biwako_1r_to_audit_only(self):
        output=convert(self.observation)
        self.assertEqual(output["schema"],"RACE_AI_FORECAST_AUDIT_V1")
        self.assertEqual(output["dataset_status"],"AUDIT_ONLY")
        self.assertEqual(len(output["records"]),1)
        self.assertEqual(output["records"][0]["race_id"],
                         "boat:2026-10-24:boatrace-jcd-11:1")
        self.assertEqual(output["records"][0]["sales_cutoff_at"],
                         "2026-10-24T10:24:00+09:00")
        self.assertEqual(output["actual_public_observation"]["entrant_registration_numbers"],
                         [5301,5204,3761,3596,3994,4728])
        self.assertIsNone(output["records"][0]["prediction"])
        self.assertFalse(output["records"][0]["cutoff_verified"])
        self.assertFalse(output["actual_public_observation"]["eligible_for_kpi"])
        self.assertFalse(output["actual_public_observation"]["prediction_generated"])
        self.assertFalse(output["actual_public_observation"]["source_access_approved_for_auto_fetch"])
    def test_synthetically_forged_domain_rejected(self):
        p=copy.deepcopy(self.observation)
        p["official_racelist_url"]=p["official_racelist_url"].replace(
            "boatrace.jp","boatrace.jp.attacker.invalid")
        with self.assertRaisesRegex(IntakeError,"source"):
            convert(p)
    def test_synthetically_wrong_race_or_date_rejected(self):
        for field,value in (("race_no",2),("venue_jcd","12"),("event_date_jst","2026-10-25")):
            p=copy.deepcopy(self.observation);p[field]=value
            with self.subTest(field=field),self.assertRaises(IntakeError):convert(p)
    def test_synthetically_duplicate_or_missing_entrant_rejected(self):
        for nums in ([5301]*6,[5301,5204,3761,3596,3994]):
            p=copy.deepcopy(self.observation)
            p["entrant_registration_numbers"]=nums
            with self.subTest(numbers=nums),self.assertRaisesRegex(IntakeError,"six distinct"):
                convert(p)
    def test_no_automatic_web_approval_from_public_view(self):
        p=copy.deepcopy(self.observation)
        p["source_access_basis"]="APPROVED"
        with self.assertRaisesRegex(IntakeError,"authorization"):
            convert(p)
if __name__=="__main__":unittest.main()
