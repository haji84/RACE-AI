"""First-party state transitions are only offline candidates, not licenses."""
import copy
import unittest
from race_ai.four_sport_publication_transition import compare_first_party_snapshots
from race_ai.four_sport_presentation_trigger import PresentationEvidenceError

T="2030-04-01T14:12:00+09:00"
def sample(sport,kind,status,captured="2030-04-01T14:01:00+09:00"):
    return {
       "sport":sport,"race_id":f"test:20300401:{sport}:01",
       "trigger_kind":kind,"source_status":status,
       "source_url":"https://example.org/fictional-official-race-document",
       "source_sha256":"a"*64 if status=="PENDING" else "b"*64,
       "source_captured_at":captured,"scheduled_cutoff_at":"2030-04-01T14:45:00+09:00",
       "race_identity_matched":True,"participant_ids_matched":True,
       "observed_feature_names":["trial_time"] if kind=="trial_run" and status!="PENDING" else [],
       "absent_feature_names":["trial_time"] if kind=="trial_run" and status=="PENDING" else [],
    }
class TransitionTests(unittest.TestCase):
    def test_four_sports_event_emitted_when_published_without_ten_minute_cap(self):
        for sport,kind in (("boat","exhibition"),("autorace","trial_run"),
                           ("keirin","rider_introduction"),("horse","paddock"),
                           ("horse","race_day_bodyweight")):
            with self.subTest(sport=sport,kind=kind):
                a=sample(sport,kind,"PENDING")
                b=sample(sport,kind,"AVAILABLE","2030-04-01T14:11:00+09:00")
                r=compare_first_party_snapshots(a,b,now=T)
                self.assertTrue(r["would_enqueue_input_check"])
                self.assertFalse(r["source_rights_for_model_admitted"])
                self.assertFalse(r["official_prediction"])
                self.assertFalse(r["provider_monitor_started"])
    def test_replay_suppression_by_exact_source_digest(self):
        a=sample("boat","exhibition","PENDING")
        b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:11:00+09:00")
        first=compare_first_party_snapshots(a,b,now=T)
        second=compare_first_party_snapshots(a,b,now=T,
                    already_issued=[first["transition_sha256"]])
        self.assertFalse(second["would_enqueue_input_check"])
        self.assertTrue(second["already_issued"])
    def test_available_to_available_no_new_event(self):
        a=sample("horse","race_day_bodyweight","AVAILABLE")
        b=sample("horse","race_day_bodyweight","AVAILABLE","2030-04-01T14:11:00+09:00")
        r=compare_first_party_snapshots(a,b,now=T)
        self.assertFalse(r["would_enqueue_input_check"])
    def test_cross_race_rejected(self):
        a=sample("keirin","rider_introduction","PENDING")
        b=sample("keirin","rider_introduction","AVAILABLE")
        b["race_id"]="another:20300401:keirin:02"
        with self.assertRaisesRegex(PresentationEvidenceError,"cross-race"):
            compare_first_party_snapshots(a,b,now=T)
    def test_capture_regression_rejected(self):
        a=sample("autorace","trial_run","PENDING","2030-04-01T14:11:00+09:00")
        b=sample("autorace","trial_run","AVAILABLE","2030-04-01T14:01:00+09:00")
        with self.assertRaisesRegex(PresentationEvidenceError,"regressed"):
            compare_first_party_snapshots(a,b,now=T)
    def test_revised_cutoff_requires_new_audit(self):
        a=sample("horse","paddock","PENDING")
        b=sample("horse","paddock","AVAILABLE","2030-04-01T14:11:00+09:00")
        b["scheduled_cutoff_at"]="2030-04-01T14:50:00+09:00"
        with self.assertRaisesRegex(PresentationEvidenceError,"revision"):
            compare_first_party_snapshots(a,b,now=T)
    def test_out_of_time_does_not_emit_event(self):
        a=sample("horse","paddock","PENDING")
        b=sample("horse","paddock","AVAILABLE","2030-04-01T14:46:00+09:00")
        r=compare_first_party_snapshots(a,b,now="2030-04-01T14:46:01+09:00")
        self.assertFalse(r["would_enqueue_input_check"])
    def test_keirin_schedule_cannot_manufacture_presentation(self):
        a=sample("keirin","rider_introduction","PENDING")
        b=sample("keirin","rider_introduction","PENDING","2030-04-01T14:11:00+09:00")
        r=compare_first_party_snapshots(a,b,now=T)
        self.assertFalse(r["newly_published_observed"])
if __name__=="__main__":unittest.main()
