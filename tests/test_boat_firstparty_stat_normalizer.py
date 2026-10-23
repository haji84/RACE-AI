"""All numeric rows are FICTIONAL; no real website or source license in tests."""
import copy
import math
import unittest
from race_ai.boat_firstparty_stat_normalizer import (
    candidate_features,NormalizeError,SCHEMA,SOURCE,MUST_BE_PRE_REVIEW
)

def fake():
    return {"schema":SCHEMA,"race_id":"boat:2030-01-15:boatrace-jcd-11:1",
            "source_url":SOURCE,"observed_at_claimed":"2030-01-15T08:14:52+09:00",
            "source_view_event_date_jst":"2030-01-15","source_view_race_no":1,
            "source_published_at":None,"source_terms_basis":MUST_BE_PRE_REVIEW,
            "entrants":[{"lane":i,"registration_no":4000+i,"national_score":5.0+i/10,
                         "local_score":4.0+i/10,"motor_number":i,
                         "motor_two_rate_percent":30.0+i}
                        for i in range(1,7)]}
ROSTER=list(range(4001,4007))

class NormalizationTests(unittest.TestCase):
    def test_explicit_three_unit_conversions_each_runner(self):
        report=candidate_features(fake(),expected_registration_numbers=ROSTER)
        self.assertEqual(report["candidate_normalized_value_count"],18)
        x=report["candidates"][0]["candidates"]
        self.assertEqual({v["feature_key"]:v["normalized_value"] for v in x},
                         {"ability":0.51,"course_compatibility":0.41,"motor_form":0.31})
        self.assertFalse(report["eligible_for_pr71_model"])
        self.assertFalse(report["source_access_authorized_by_this_code"])
        self.assertTrue(all(v["published_at"] is None and v["sample_n"] is None
                            and v["admitted_as_pre_cutoff_model_feature"] is False
                            for r in report["candidates"] for v in r["candidates"]))
    def test_forged_roster_or_lanes_rejected(self):
        sample=fake()
        sample["entrants"][1]["registration_no"]=9999
        with self.assertRaisesRegex(NormalizeError,"registration"):
            candidate_features(sample,expected_registration_numbers=ROSTER)
        sample=fake()
        sample["entrants"][1]["lane"]=1
        with self.assertRaisesRegex(NormalizeError,"lane"):
            candidate_features(sample,expected_registration_numbers=ROSTER)
    def test_odds_or_fabricated_source_publication_time_rejected(self):
        sample=fake();sample["entrants"][0]["odds"]=2.4
        with self.assertRaisesRegex(NormalizeError,"stats row"):
            candidate_features(sample,expected_registration_numbers=ROSTER)
        sample=fake();sample["source_published_at"]="2030-01-15T08:00:00+09:00"
        with self.assertRaisesRegex(NormalizeError,"independently verified"):
            candidate_features(sample,expected_registration_numbers=ROSTER)
    def test_units_and_nan_bounds(self):
        for key,value in (("national_score",11),
                          ("local_score",-1),
                          ("motor_two_rate_percent",101),
                          ("motor_two_rate_percent",float("nan"))):
            sample=fake();sample["entrants"][0][key]=value
            with self.subTest(key=key,value=str(value)),self.assertRaisesRegex(NormalizeError,"numeric"):
                candidate_features(sample,expected_registration_numbers=ROSTER)
    def test_stale_rotating_venue_homepage_must_not_be_used_for_other_day(self):
        for name,value in (("source_view_event_date_jst","2030-01-14"),
                           ("source_view_race_no",6)):
            case=fake()
            case[name]=value
            with self.subTest(name=name),self.assertRaisesRegex(NormalizeError,"stale/mismatched"):
                candidate_features(case,expected_registration_numbers=ROSTER)

    def test_spoofed_web_hosts_and_fake_rights_rejected(self):
        for key,value in (("source_url","https://boatrace-biwako.jp.attacker.invalid/sp/"),
                          ("source_terms_basis","APPROVED"),
                          ("observed_at_claimed","2030-01-15T08:14:52")):
            sample=fake();sample[key]=value
            with self.subTest(key=key),self.assertRaises(NormalizeError):
                candidate_features(sample,expected_registration_numbers=ROSTER)

if __name__=="__main__":
    unittest.main()
