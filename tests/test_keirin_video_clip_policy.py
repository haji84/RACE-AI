"""Synthetic-only coverage policy tests: partial highlights are real-scene eligible,
but can never masquerade as four independently verified racing laps.
"""
from datetime import datetime,timezone
from hashlib import sha256
import copy
import unittest

from race_ai.keirin_video_clip_policy import (
  CLIP_SCHEMA,ClipPolicyError,assess_clip,choose_preferred_clips,validate,digest)

def h(s):return sha256(s.encode()).hexdigest()

def row(label,sec,n,*,action=None,scene="LIVE",rider=None):
    return {"id":f"event-{n}","time_s":float(sec),"label":label,
        "rider_id":rider,
        "action_key":action or f"action-{n}",
        "frame_sha256":h("fake-video-frame-"+str(n)),
        "scene":scene,"review_ref":f"reviewed-private-frame-{n}"}

def example(*,full=False):
    events=[
        row("ATTACK",22,1,rider="rider-001",action="attack-1"),
        row("POSITION_GAIN",31,2,rider="rider-002"),
        row("ATTACK",44,3,rider="rider-001",action="attack-1",scene="REPLAY"),
        row("REPLAY",46,4,scene="REPLAY"),
        row("FINAL_SPRINT",69,5,rider="rider-003"),
        row("GOAL",77,6),
        row("FINISH",78,7),
    ]
    return {"schema":CLIP_SCHEMA,"race_id":"20261030-yahiko-1R",
        "source_url":"https://www.winticket.jp/keirin/yahiko/raceresult/2026103021/1/1",
        "source_kind":"WINTICKET_PAST_REPLAY",
        "recording_sha256":h("illustrative-yahiko-fake-video"),
        "duration_s":80.164,
        "claimed_coverage":"FULL_FOUR_LAPS" if full else "PARTIAL_HIGHLIGHTS",
        "reviewed_at":"2026-11-09T01:00:00+09:00",
        "events":events}

FRAMES=lambda x:True
RIGHTS=lambda url,purpose:True
LAPS=lambda report,clip:True

class HistoricalVideoLearningPolicyTests(unittest.TestCase):
    def test_partial_highlight_can_supply_visible_tactics_and_goal(self):
        result=assess_clip(example(),independent_visual_verifier=FRAMES,
                           rights_verifier=RIGHTS)
        self.assertTrue(result["training_eligible"])
        self.assertEqual(result["admitted_coverage"],"PARTIAL_HIGHLIGHTS")
        self.assertFalse(result["all_four_laps_verified"])
        self.assertNotIn("LAP_PASS_COUNT",result["allowed_tasks"])
        self.assertIn("VISIBLE_TACTICS",result["allowed_tasks"])
        self.assertIn("VISIBLE_GOAL",result["allowed_tasks"])
        self.assertEqual(result["evidence_event_count"],5)
        self.assertEqual(sum(x["label"]=="ATTACK"
                     for x in result["reviewed_events"]),1)
        self.assertGreaterEqual(result["deduplicated_replay_count"],1)
        self.assertFalse(result["unseen_actions_mean_negative"])
        self.assertIn("REPLAY",{x["label"] for x in result["reviewed_scene_frames"]})
        self.assertEqual(result["admission_sha256"],digest({
                    k:v for k,v in result.items() if k!="admission_sha256"}))

    def test_no_rights_and_no_independent_frame_review_are_not_training(self):
        clip=example()
        a=assess_clip(clip)
        self.assertFalse(a["training_eligible"])
        self.assertEqual(a["admitted_coverage"],"NONE")
        self.assertEqual(a["reviewed_events"],[])
        self.assertIn("TRAINING_RIGHTS_NOT_CONFIRMED",a["reasons"])
        self.assertIn("INDEPENDENT_FRAME_REVIEW_MISSING",a["reasons"])
        rejected=choose_preferred_clips([a])
        self.assertEqual(rejected["partial_count"],0)
        self.assertEqual(len(rejected["excluded_unverified"]),1)

    def test_claiming_four_laps_does_not_expand_partial_into_lap_evidence(self):
        clip=example(full=True)
        a=assess_clip(clip,independent_visual_verifier=FRAMES,
                      rights_verifier=RIGHTS)
        self.assertTrue(a["training_eligible"])
        self.assertFalse(a["all_four_laps_verified"])
        self.assertEqual(a["admitted_coverage"],"PARTIAL_HIGHLIGHTS")
        self.assertIn("FOUR_LAPS_NOT_INDEPENDENTLY_ATTESTED",a["reasons"])
        self.assertNotIn("LAP_PASS_COUNT",a["allowed_tasks"])

    def test_actual_independent_four_lap_audit_prioritized_for_same_race(self):
        short=assess_clip(example(),independent_visual_verifier=FRAMES,
                          rights_verifier=RIGHTS)
        full=example(full=True)
        full["source_url"]="https://www.winticket.jp/keirin/yahiko/live"
        full["source_kind"]="WINTICKET_LIVE"
        full["duration_s"]=540.0
        full["recording_sha256"]=h("fake-long-source")
        receipt={"status":"FOUR_LAPS_VISUALLY_VERIFIED",
                 "recording_sha256":full["recording_sha256"],
                 "race_id":full["race_id"]}
        long=assess_clip(full,independent_visual_verifier=FRAMES,
                         rights_verifier=RIGHTS,
                         full_lap_audit=receipt,lap_audit_verifier=LAPS)
        self.assertEqual(long["admitted_coverage"],"FULL_FOUR_LAPS")
        self.assertTrue(long["all_four_laps_verified"])
        self.assertIn("LAP_PASS_COUNT",long["allowed_tasks"])
        result=choose_preferred_clips([short,long])
        self.assertEqual(result["full_count"],1)
        self.assertEqual(result["partial_count"],0)
        self.assertEqual(result["selected"][full["race_id"]],long)

    def test_only_replay_marker_with_no_tactic_or_goal_is_not_enough(self):
        clip=example()
        clip["events"]=[row("REPLAY",8,1,scene="REPLAY")]
        r=assess_clip(clip,independent_visual_verifier=FRAMES,
                      rights_verifier=RIGHTS)
        self.assertFalse(r["training_eligible"])
        self.assertIn("NO_VISIBLE_LEARNABLE_ACTION",r["reasons"])

    def test_conflicting_attack_and_goal_same_action_key_blocks_admission(self):
        clip=example()
        clip["events"][1]["action_key"]="attack-1"
        r=assess_clip(clip,independent_visual_verifier=FRAMES,
                      rights_verifier=RIGHTS)
        self.assertFalse(r["training_eligible"])
        self.assertIn("CONFLICTING_DUPLICATE_ACTION_LABELS",r["reasons"])

    def test_cannot_rewrite_source_into_non_winticket_host(self):
        clip=example()
        clip["source_url"]="https://attacker.example/keirin/yahiko/raceresult/2026103021/1/1"
        with self.assertRaisesRegex(ClipPolicyError,"SOURCE_HOST_MISMATCH"):
            validate(clip)

    def test_bad_time_and_duplicate_ids_block_admission(self):
        clip=example()
        clip["reviewed_at"]="2026-11-09 01:00:00"
        with self.assertRaisesRegex(ClipPolicyError,"REVIEW_TIMEZONE_REQUIRED"):
            validate(clip)
        clip=example()
        clip["events"][2]["id"]=clip["events"][0]["id"]
        with self.assertRaisesRegex(ClipPolicyError,"DUPLICATE_EVENT_ID"):
            validate(clip)

    def test_tampered_admission_rejected(self):
        item=assess_clip(example(),independent_visual_verifier=FRAMES,
                         rights_verifier=RIGHTS)
        item["all_four_laps_verified"]=True
        with self.assertRaisesRegex(ClipPolicyError,"INVALID_ADMISSION_INTEGRITY"):
            choose_preferred_clips([item])

if __name__=="__main__":
    unittest.main()
