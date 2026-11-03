"""Cross-sport presentation and published-bodyweight state tests, no network."""
import copy
import unittest
from race_ai.four_sport_presentation_trigger import (
    PresentationEvidenceError, inspect_presentation_observation,
    select_published_candidate, TRIGGERS
)

NOW="2030-04-01T14:01:00+09:00"
CAPTURED="2030-04-01T14:00:00+09:00"
CUTOFF="2030-04-01T14:42:00+09:00"
SPORT_CASES=(
    ("boat","exhibition",["exhibition_time","exhibition_st"]),
    ("autorace","trial_run",["trial_time"]),
    ("keirin","rider_introduction",["observed_line_order"]),
    ("horse","paddock",["paddock_condition"]),
    ("horse","race_day_bodyweight",["official_bodyweight"]),
)
def evidence(sport="boat",kind="exhibition",features=None):
    return {
        "sport":sport,"race_id":f"test:20300401:{sport}:race01",
        "trigger_kind":kind,"source_status":"AVAILABLE",
        "source_url":"https://example.org/fictional-official-document",
        "source_sha256":"a"*64,
        "source_captured_at":CAPTURED,
        "scheduled_cutoff_at":CUTOFF,
        "race_identity_matched":True,"participant_ids_matched":True,
        "observed_feature_names":features if features is not None else ["race_preview"],
        "absent_feature_names":[],
    }

class CrossSportPresentationTests(unittest.TestCase):
    def test_each_pre_race_observed_trigger_selects_even_41_minutes_before_cutoff(self):
        for sport,kind,features in SPORT_CASES:
            with self.subTest(sport=sport,kind=kind):
                r=inspect_presentation_observation(evidence(sport,kind,features),now=NOW)
                self.assertTrue(r["published_observed_trigger"])
                self.assertEqual(r["status"],"PRESENTATION_PUBLISHED")
                self.assertFalse(r["all_PR71_required_features_admitted"])
                self.assertFalse(r["PR71_model_executed"])
                self.assertFalse(r["official_prediction"])

    def test_keirin_presentation_not_numeric_trial_run_and_bodyweight_not_paddock(self):
        for sport,kind in (("keirin","trial_run"),("horse","trial_run"),
                           ("boat","race_day_bodyweight"),
                           ("autorace","paddock")):
            with self.subTest(sport=sport,kind=kind),self.assertRaisesRegex(
                PresentationEvidenceError,"different sport"):
                inspect_presentation_observation(evidence(sport,kind),now=NOW)
        a=inspect_presentation_observation(evidence("horse","race_day_bodyweight"),now=NOW)
        self.assertEqual(a["trigger_kind"],"race_day_bodyweight")
        self.assertFalse(a["all_PR71_required_features_admitted"])

    def test_pending_and_unavailable_are_not_triggered(self):
        for status in ("PENDING","UNAVAILABLE","ERROR"):
            row=evidence("autorace","trial_run")
            row["source_status"]=status
            r=inspect_presentation_observation(row,now=NOW)
            self.assertFalse(r["published_observed_trigger"])
            self.assertFalse(r["official_prediction"])

    def test_partial_exhibition_does_not_impute_ST(self):
        row=evidence()
        row["source_status"]="PARTIAL"
        row["observed_feature_names"]=["exhibition_time"]
        row["absent_feature_names"]=["exhibition_st"]
        r=inspect_presentation_observation(row,now=NOW)
        self.assertTrue(r["published_observed_trigger"])
        self.assertEqual(r["status"],"PRESENTATION_PUBLISHED_PARTIAL")
        self.assertEqual(r["absent_feature_names"],["exhibition_st"])
        self.assertFalse(r["all_PR71_required_features_admitted"])

    def test_video_only_keirin_without_structured_lines_not_model_admitted(self):
        row=evidence("keirin","rider_introduction",["video_view_available"])
        row["absent_feature_names"]=["verified_line_position"]
        r=inspect_presentation_observation(row,now=NOW)
        self.assertTrue(r["published_observed_trigger"])
        self.assertFalse(r["all_PR71_required_features_admitted"])

    def test_expired_or_capture_after_cutoff_is_not_eligible(self):
        r=evidence()
        self.assertFalse(inspect_presentation_observation(r,
             now="2030-04-01T14:42:00+09:00")["published_observed_trigger"])
        r["source_captured_at"]="2030-04-01T14:43:00+09:00"
        self.assertFalse(inspect_presentation_observation(r,
             now="2030-04-01T14:44:00+09:00")["published_observed_trigger"])

    def test_mismatched_sport_and_athlete_identity_blocks(self):
        r=evidence()
        r["participant_ids_matched"]=False
        self.assertEqual(inspect_presentation_observation(r,now=NOW)["status"],
                         "UNVERIFIED_RACE_OR_PARTICIPANT_IDENTITY")

    def test_unknown_first_publication_remains_unverified(self):
        r=inspect_presentation_observation(evidence("autorace","trial_run"),now=NOW)
        self.assertFalse(r["source_first_published_at_independently_verified"])
        self.assertFalse(r["source_purpose_rights_independently_verified"])
        self.assertFalse(r["formal_hit_at_8_eligible"])

    def test_odds_and_results_fields_never_enter_market_free_input(self):
        record=evidence()
        record["observed_feature_names"]=["odds_market"]
        with self.assertRaisesRegex(PresentationEvidenceError,"market"):
            inspect_presentation_observation(record,now=NOW)
        record=evidence()
        record["race_result"]={"winner":1}
        with self.assertRaises(PresentationEvidenceError):
            inspect_presentation_observation(record,now=NOW)

    def test_empty_or_fake_capture_timestamp_rejected(self):
        record=evidence()
        record["source_captured_at"]=None
        with self.assertRaises(PresentationEvidenceError):
            inspect_presentation_observation(record,now=NOW)
        record=evidence()
        record["source_sha256"]="not_hash"
        with self.assertRaises(PresentationEvidenceError):
            inspect_presentation_observation(record,now=NOW)

    def test_only_observed_published_earliest_cutoff_is_selected(self):
        a=evidence("boat","exhibition")
        a["race_id"]="boat:20300401:venue01:race01"
        a["scheduled_cutoff_at"]="2030-04-01T14:25:00+09:00"
        b=evidence("autorace","trial_run")
        b["scheduled_cutoff_at"]="2030-04-01T14:15:00+09:00"
        c=evidence("horse","paddock")
        c["scheduled_cutoff_at"]="2030-04-01T14:10:00+09:00"
        c["source_status"]="PENDING"
        r=select_published_candidate([a,b,c],now=NOW)
        self.assertEqual(r["selected"]["sport"],"autorace")
        self.assertEqual(len(r["published_trigger_candidates"]),2)
        self.assertFalse(r["model_input_admitted"])

if __name__=="__main__":
    unittest.main()
