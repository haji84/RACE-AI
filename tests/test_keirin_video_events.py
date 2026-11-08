"""Offline evidence/replay/learning safety tests. ALL evidence is fictitious."""
import copy
from datetime import datetime,timedelta,timezone
import hashlib
import unittest

from race_ai.keirin_video_events import audit, EvidenceError, SCHEMA
from race_ai.keirin_video_postrace_pdca import (
    create_postrace_learning_candidate)

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def e(label,time,idx,*,phash=None,scene="LIVE",replay=0.03,score=0.97):
    return {"id":f"e{idx}","recording_sec":time,"event":label,
            "confidence":score,"frame_sha256":sha(f"synthetic frame {idx}"),
            "phash64":phash or f"{(idx*0x9e3779b97f4a7c15)&((1<<64)-1):016x}",
            "scene":scene,"replay_confidence":replay,
            "origin":"SYNTHETIC_FIXTURE"}

def doc(source="WINTICKET_LIVE"):
    return {"schema":SCHEMA,"race_id":"20261108-matsuyama-9R",
        "recording_sha256":sha("synthetic source video"),
        "duration_s":620.0,"expected_laps":4,
        "source":source,"inference_model":"synthetic-test-only-not-an-ai",
        "observations":[
            e("START",210,1),
            e("HOME_PASS",245,2),
            e("HOME_PASS",295,3),
            e("HOME_PASS",337,4),
            e("HOME_PASS",405,5),
            e("GOAL",408,6),
            e("REPLAY_START",420,7,scene="REPLAY"),
            e("HOME_PASS",449,8,scene="REPLAY",replay=0.99),
            e("REPLAY_END",480,9,scene="REPLAY"),
            e("RESULT",517,10,scene="INTERMISSION")
        ]}

class FourLapEvidenceTests(unittest.TestCase):
    def test_four_passes_with_replay_ignored(self):
        r=audit(doc(),trusted_visual_verifier=lambda evidence: True)
        self.assertEqual(r["status"],"FOUR_LAPS_VISUALLY_VERIFIED")
        self.assertEqual(r["pass_count"],4)
        self.assertEqual(r["candidate_count"],5)
        self.assertEqual([x["lap"] for x in r["evidence"]],[1,2,3,4])
        self.assertEqual(len(r["excluded_passes"]),1)
        self.assertEqual(r["excluded_passes"][0]["reason"],
                         "REPLAY_OR_SCENE_UNCERTAIN")
        self.assertTrue(r["learning_admission"].startswith("INDEPENDENTLY_"))

    def test_model_cannot_self_certify(self):
        report=audit(doc())
        self.assertEqual(report["status"],"FOUR_LAPS_UNVERIFIED")
        self.assertIn("INDEPENDENT_VISUAL_RECEIPT_MISSING",report["reasons"])
        self.assertEqual(report["learning_admission"],"BLOCKED_UNVERIFIED")

    def test_replay_swallowed_a_live_lap(self):
        x=doc()
        x["observations"][3]["scene"]="REPLAY"
        self.assertIn("NOT_FOUR_DISTINCT_LIVE_PASSES",
                      audit(x,trusted_visual_verifier=lambda evidence: True)["reasons"])

    def test_identical_image_not_new_lap(self):
        x=doc()
        x["observations"][3]["frame_sha256"]=x["observations"][2]["frame_sha256"]
        self.assertIn("NOT_FOUR_DISTINCT_LIVE_PASSES",
                      audit(x,trusted_visual_verifier=lambda evidence: True)["reasons"])

    def test_phash_replay_not_new_lap(self):
        x=doc()
        x["observations"][3]["phash64"]=x["observations"][2]["phash64"]
        out=audit(x,trusted_visual_verifier=lambda evidence: True)
        self.assertEqual(out["pass_count"],3)
        self.assertIn("REPEATED_IMAGE_OR_SUSPECTED_REPLAY",
                      [p["reason"] for p in out["excluded_passes"]])

    def test_real_dev_like_replay_does_not_double_count_near_images(self):
        x=doc()
        # Source 9R visual DEV showed hamming 2-4 for replayed finish frames
        # even though exact SHA was different. This test is synthetic.
        old=int(x["observations"][2]["phash64"],16)
        x["observations"][4]["phash64"]=f"{old ^ 0b1111:016x}"
        out=audit(x,trusted_visual_verifier=lambda reviewed:True)
        self.assertEqual(out["pass_count"],3)
        self.assertIn("REPEATED_IMAGE_OR_SUSPECTED_REPLAY",
            [v["reason"] for v in out["excluded_passes"]])
        self.assertIn("NOT_FOUR_DISTINCT_LIVE_PASSES",out["reasons"])

    def test_edited_digest_not_full_race(self):
        x=doc(source="SYNTHETIC_FIXTURE")
        result=audit(x,trusted_visual_verifier=lambda evidence: True)
        self.assertIn("SYNTHETIC_SOURCE_NOT_REAL_EVIDENCE",result["reasons"])

    def test_out_of_order_rejected(self):
        x=doc()
        x["observations"][1]["recording_sec"]=100
        with self.assertRaisesRegex(EvidenceError,"INVALID_EVENT_TIME_ORDER"):
            audit(x)

    def test_missing_goal_or_result_is_failure(self):
        x=doc()
        x["observations"]=[a for a in x["observations"] if a["event"]!="GOAL"]
        out=audit(x,trusted_visual_verifier=lambda evidence: True)
        self.assertIn("GOAL_NOT_UNIQUE",out["reasons"])

    def test_learning_cannot_accept_unverified(self):
        with self.assertRaisesRegex(EvidenceError,"UNVERIFIED_VIDEO_MUST_NOT_TRAIN"):
            create_postrace_learning_candidate(audit(doc()),{},{})
        report=audit(doc(),trusted_visual_verifier=lambda evidence: True)
        cutoff=datetime(2026,11,8,23,15,tzinfo=timezone(timedelta(hours=9)))
        frozen={"race_id":doc()["race_id"],"original_sha256":sha("forecast"),
                "saved_at":(cutoff-timedelta(minutes=5)).isoformat(),
                "official_cutoff_at":cutoff.isoformat()}
        settled={"race_id":doc()["race_id"],
                 "published_at":(cutoff+timedelta(minutes=20)).isoformat(),
                 "ordered_top3":[1,2,7]}
        with self.assertRaisesRegex(EvidenceError,"INDEPENDENT_ATTESTORS_REQUIRED"):
            create_postrace_learning_candidate(report,frozen,settled)
        candidate=create_postrace_learning_candidate(
            report,frozen,settled,
            frozen_receipt_verifier=lambda x:True,
            official_result_verifier=lambda x:True,
            rights_checker=lambda source,purpose:True)
        self.assertTrue(candidate["prediction_original_untouched"])
        self.assertFalse(candidate["used_for_same_race_forecast"])
        self.assertEqual(len(candidate["lap_intervals_seconds"]),3)
        self.assertEqual(candidate["training_status"],"PRIVATE_CANDIDATE_NOT_FITTED")
        changed=copy.deepcopy(settled)
        changed["published_at"]=(cutoff-timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(EvidenceError,"FORECAST_RESULT_TIME_LEAK"):
            create_postrace_learning_candidate(
              report,frozen,changed, frozen_receipt_verifier=lambda x:True,
              official_result_verifier=lambda x:True,
              rights_checker=lambda source,purpose:True)

if __name__=="__main__":unittest.main()
