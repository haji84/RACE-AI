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
                    already_issued=[first["issued_event_key"]])
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

    def test_equal_capture_times_cannot_prove_publication(self):
        a=sample("boat","exhibition","PENDING")
        b=sample("boat","exhibition","AVAILABLE",a["source_captured_at"])
        with self.assertRaisesRegex(PresentationEvidenceError,"later|ordered"):
            compare_first_party_snapshots(a,b,now=T)

    def test_unverified_pending_identity_cannot_prove_publication(self):
        for field in ("race_identity_matched","participant_ids_matched"):
            for unverified in (False,1):
                with self.subTest(field=field,unverified=unverified):
                    a=sample("boat","exhibition","PENDING")
                    b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:11:00+09:00")
                    a[field]=unverified
                    result=compare_first_party_snapshots(a,b,now=T)
                    self.assertFalse(result["newly_published_observed"])
                    self.assertFalse(result["would_enqueue_input_check"])

    def test_future_pending_capture_cannot_be_used_as_publication_evidence(self):
        a=sample("boat","exhibition","PENDING","2030-04-01T14:13:00+09:00")
        b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:14:00+09:00")
        with self.assertRaisesRegex(PresentationEvidenceError,"future"):
            compare_first_party_snapshots(a,b,now=T)

    def test_both_observations_after_cutoff_cannot_enqueue(self):
        a=sample("boat","exhibition","PENDING","2030-04-01T14:46:00+09:00")
        b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:47:00+09:00")
        result=compare_first_party_snapshots(a,b,now="2030-04-01T14:48:00+09:00")
        self.assertFalse(result["newly_published_observed"])
        self.assertFalse(result["would_enqueue_input_check"])

    def test_identical_source_bytes_cannot_prove_status_change(self):
        for status in ("AVAILABLE","PARTIAL"):
            with self.subTest(status=status):
                a=sample("boat","exhibition","PENDING")
                b=sample("boat","exhibition",status,"2030-04-01T14:11:00+09:00")
                b["source_sha256"]=a["source_sha256"]
                with self.assertRaisesRegex(PresentationEvidenceError,"unchanged|different"):
                    compare_first_party_snapshots(a,b,now=T)

    def test_recaptured_published_bytes_do_not_enqueue_against_stale_pending(self):
        a=sample("boat","exhibition","PENDING")
        b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:10:00+09:00")
        first=compare_first_party_snapshots(a,b,now=T)
        later=copy.deepcopy(b)
        later["source_captured_at"]="2030-04-01T14:11:00+09:00"
        repeated=compare_first_party_snapshots(a,later,now=T,
            already_issued=[first["issued_event_key"]])
        self.assertFalse(repeated["would_enqueue_input_check"])
        self.assertTrue(repeated["already_issued"])
        self.assertEqual(first["transition_sha256"],repeated["transition_sha256"])
        self.assertNotEqual(first["captured_at"],repeated["captured_at"])

    def test_v2_issued_key_is_explicitly_versioned(self):
        a=sample("boat","exhibition","PENDING")
        b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:11:00+09:00")
        result=compare_first_party_snapshots(a,b,now=T)
        self.assertEqual(result.get("schema"),"RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V2")
        self.assertEqual(result.get("issued_event_key"),
            "RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V2:"+result["transition_sha256"])
        self.assertEqual(result.get("previous_captured_at"),a["source_captured_at"])

    def test_legacy_bare_or_v1_issued_records_fail_closed(self):
        a=sample("boat","exhibition","PENDING")
        b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:11:00+09:00")
        for legacy in ("a"*64,
                       "RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V1:"+"a"*64,
                       {"schema":"RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V1",
                        "transition_sha256":"a"*64}):
            with self.subTest(legacy=legacy):
                with self.assertRaisesRegex(PresentationEvidenceError,"legacy|version|migration"):
                    compare_first_party_snapshots(a,b,now=T,already_issued=[legacy])

    def test_invalid_issued_keys_cannot_be_ignored_as_new_events(self):
        a=sample("boat","exhibition","PENDING")
        b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:11:00+09:00")
        for invalid in (None,True,17,"", "RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V2:not-a-sha"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(PresentationEvidenceError):
                    compare_first_party_snapshots(a,b,now=T,already_issued=[invalid])

    def test_equivalent_cutoff_offsets_have_one_publication_identity(self):
        a=sample("boat","exhibition","PENDING")
        b=sample("boat","exhibition","AVAILABLE","2030-04-01T14:11:00+09:00")
        first=compare_first_party_snapshots(a,b,now=T)
        a["scheduled_cutoff_at"]=b["scheduled_cutoff_at"]="2030-04-01T05:45:00Z"
        equivalent=compare_first_party_snapshots(a,b,now=T)
        self.assertEqual(first["transition_sha256"],equivalent["transition_sha256"])
        self.assertEqual(equivalent["scheduled_cutoff_at"],"2030-04-01T05:45:00Z")

    def test_partial_changed_source_can_trigger_without_claiming_model_readiness(self):
        a=sample("autorace","trial_run","PENDING")
        b=sample("autorace","trial_run","PARTIAL","2030-04-01T14:11:00+09:00")
        b["absent_feature_names"]=["machine_condition"]
        original=copy.deepcopy((a,b))
        result=compare_first_party_snapshots(a,b,now=T)
        self.assertTrue(result["would_enqueue_input_check"])
        for flag in ("source_rights_for_model_admitted","full_PR71_features_admitted",
                     "official_prediction","provider_monitor_started",
                     "original_provider_published_at_verified"):
            self.assertIs(result[flag],False)
        self.assertEqual((a,b),original)

    def test_stable_identity_keeps_distinct_source_race_kind_and_cutoff(self):
        a=sample("horse","paddock","PENDING")
        b=sample("horse","paddock","AVAILABLE","2030-04-01T14:11:00+09:00")
        first=compare_first_party_snapshots(a,b,now=T)
        variants=[]
        for field,value in (("race_id","test:20300401:horse:02"),
                            ("trigger_kind","race_day_bodyweight"),
                            ("scheduled_cutoff_at","2030-04-01T14:50:00+09:00")):
            before,after=copy.deepcopy((a,b))
            before[field]=after[field]=value
            variants.append(compare_first_party_snapshots(before,after,now=T))
        changed=copy.deepcopy(b)
        changed["source_sha256"]="c"*64
        variants.append(compare_first_party_snapshots(a,changed,now=T))
        keys=[first["transition_sha256"]]+[v["transition_sha256"] for v in variants]
        self.assertEqual(len(set(keys)),5)
if __name__=="__main__":unittest.main()
