"""Synthetic fixtures ONLY. No real reviewer identity is asserted in these tests."""
from copy import deepcopy
import unittest

from race_ai import keirin_observed_follow_admission as gate
from race_ai import keirin_line_cohesion as existing


def fixture():
    frames=[
        {"frame_sha256":str(i+1)*64,"video_second":50+2*i,
         "phase":"FINAL_BACK","leader_car":5,"follower_car":3,
         "relative_relation":"FOLLOWING"}
        for i in range(3)]
    return {
        "schema":gate.PACKET_SCHEMA,
        "race_id":"202611098402",
        "source_video_sha256":"a"*64,
        "event_ended_at":"2026-11-09T13:10:00+09:00",
        "source_published_at":"2026-11-09T13:20:00+09:00",
        "available_at":"2026-11-10T12:00:00+09:00",
        "leader_athlete_id":"015709",
        "follower_athlete_id":"014525",
        "leader_car":5,"follower_car":3,
        "role":"SECOND_WHEEL","competition":"A1_A2",
        "round_stage":"SEMI_FINAL","leader_tactic":"NIGE",
        "phase":"FINAL_BACK","outcome":"HELD",
        "observed_frames":frames,
        "reviews":[
            {"reviewer_id":"reviewer_user_one",
             "reviewed_at":"2026-11-10T10:00:00+09:00",
             "signed_review_receipt_sha256":"d"*64,
             "source_video_sha256":"a"*64,
             "frame_sha256s":[f["frame_sha256"] for f in frames],
             "outcome":"HELD"},
            {"reviewer_id":"reviewer_user_two",
             "reviewed_at":"2026-11-10T11:00:00+09:00",
             "signed_review_receipt_sha256":"e"*64,
             "source_video_sha256":"a"*64,
             "frame_sha256s":[f["frame_sha256"] for f in frames],
             "outcome":"HELD"},
        ]}


def run(packet=None,*,video=lambda x:True,roster=lambda x:True,
        signed=lambda x:True):
    return gate.admit_for_C(
        packet=packet if packet is not None else fixture(),
        verify_owner_source_video=video,
        verify_roster_id_mapping=roster,
        verify_independent_signed_reviewers=signed)


class VerifiedFollowIntakeContract(unittest.TestCase):
    def test_trusted_external_review_translates_to_existing_C_label(self):
        out=run()
        row=out["private_historical_label"]
        existing.validate_label(row)
        self.assertEqual(row["leader_athlete_id"],"015709")
        self.assertEqual(row["follower_athlete_id"],"014525")
        self.assertEqual(row["outcome"],"HELD")
        self.assertFalse(out["production_model_promoted"])
        self.assertTrue(out["usable_only_if_available_before_target_as_of"])

    def test_without_external_video_proof_no_label(self):
        with self.assertRaisesRegex(gate.FollowAdmissionError,"VIDEO_SOURCE_NOT"):
            run(video=None)

    def test_without_independent_roster_or_people_no_label(self):
        for which in ("roster","signed"):
            with self.subTest(which=which):
                with self.assertRaises(gate.FollowAdmissionError):
                    run(**{which:None})

    def test_same_reviewer_cannot_approve_both(self):
        p=fixture()
        p["reviews"][1]["reviewer_id"]=p["reviews"][0]["reviewer_id"]
        with self.assertRaisesRegex(gate.FollowAdmissionError,"TWO_EXTERNALLY_DISTINCT"):
            run(p)

    def test_same_signature_repeated_rejected(self):
        p=fixture()
        p["reviews"][1]["signed_review_receipt_sha256"]="d"*64
        with self.assertRaisesRegex(gate.FollowAdmissionError,"TWO_EXTERNALLY_DISTINCT"):
            run(p)

    def test_review_disagreement_not_certified(self):
        p=fixture()
        p["reviews"][1]["outcome"]="GAPPED"
        with self.assertRaisesRegex(gate.FollowAdmissionError,"NOT_CONSENSUS"):
            run(p)

    def test_public_planned_line_can_never_become_follow_label(self):
        p={"schema":"RACE_AI_KEIRIN_PUBLIC_PLANNED_PAIR_RESEARCH_V1",
           "race_id":"202611098402","expected_line_cars":[5,3,6],
           "tactical_follow_outcome":"HELD"}
        with self.assertRaisesRegex(gate.FollowAdmissionError,"PACKET_SCHEMA"):
            run(p)

    def test_finish_order_is_not_sufficient_to_declare_held(self):
        p=fixture()
        p["observed_frames"][1]["relative_relation"]="UNKNOWN"
        with self.assertRaisesRegex(gate.FollowAdmissionError,"HELD_REQUIRES"):
            run(p)

    def test_gapped_requires_gap_visible_on_video_not_3ren_tan_result(self):
        p=fixture()
        p["outcome"]="GAPPED"
        for review in p["reviews"]:
            review["outcome"]="GAPPED"
        with self.assertRaisesRegex(gate.FollowAdmissionError,"GAPPED_REQUIRES_VISIBLE"):
            run(p)
        p["observed_frames"][1]["relative_relation"]="GAP_VISIBLE"
        out=run(p)
        self.assertEqual(out["private_historical_label"]["outcome"],"GAPPED")

    def test_switched_requires_visible_switch(self):
        p=fixture();p["outcome"]="SWITCHED"
        for review in p["reviews"]:
            review["outcome"]="SWITCHED"
        with self.assertRaisesRegex(gate.FollowAdmissionError,"SWITCH_REQUIRES_VISIBLE"):
            run(p)
        p["observed_frames"][2]["relative_relation"]="SWITCH_VISIBLE"
        self.assertEqual(run(p)["private_historical_label"]["outcome"],"SWITCHED")

    def test_future_or_unpublished_review_rejected(self):
        p=fixture()
        p["available_at"]="2026-11-09T12:00:00+09:00"
        with self.assertRaisesRegex(gate.FollowAdmissionError,"FUTURE_HISTORY"):
            run(p)

    def test_reused_image_or_wrong_race_fails(self):
        p=fixture()
        p["observed_frames"][1]["frame_sha256"] = p["observed_frames"][0]["frame_sha256"]
        with self.assertRaisesRegex(gate.FollowAdmissionError,"REUSED"):
            run(p)

    def test_review_does_not_claim_separate_human_when_stub_is_true(self):
        out=run()
        self.assertTrue(out["signed_review_independence_must_be_externally_verified"])
        self.assertFalse(out["original_PR71_weights_changed"])


if __name__=="__main__":
    unittest.main()
