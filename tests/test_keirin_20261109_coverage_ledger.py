"""Synthetic reproducibility checks for the independent daily clip ledger."""
import copy
from hashlib import sha256
import unittest

from race_ai.keirin_20261109_83_manifest import manifest,digest
from race_ai.keirin_20261109_coverage_ledger import summarize,CoverageError,WAVE_SCHEMA

def h(v):return sha256(v.encode()).hexdigest()
def row(n=1,*,status="ENCRYPTED_COMPLETE_PLAYER",sha=None):
    rid=f"2026110912{n:02d}"
    return {
        "race_id":rid,"status":status,
        "recording_sha256":sha or h("invented-cipher-"+rid),
        "player_ended":True,"player_duration_s":81.0,
        "cohort":"TRAIN_CANDIDATE",
    }
def wave(items):
    return {
        "schema":WAVE_SCHEMA,
        "manifest_sha256":digest(manifest()),
        "date_jst":"2026-11-09","raw_footage_exported":False,
        "prediction_model_weights_changed":False,
        "race_rows":items,
    }
class CoverageTests(unittest.TestCase):
    def test_unique_recordings_not_83_automatically(self):
        result=summarize([wave([row(1),row(2)])])
        self.assertEqual(result["scheduled_races"],83)
        self.assertEqual(result["attempted_unique_races"],2)
        self.assertEqual(result["encrypted_unique_races"],2)
        self.assertEqual(result["confirmed_private_library_races"],0)
        self.assertEqual(result["not_yet_recorded_races"],81)
        self.assertEqual(result["reviewed_verified_rider_events"],0)
        self.assertFalse(result["official_prediction_weights_modified"])
    def test_repeated_attempt_same_race_only_counts_once(self):
        result=summarize([wave([row(1)]),wave([row(1)])])
        self.assertEqual(result["encrypted_unique_races"],1)
        self.assertEqual(result["total_wave_reports"],2)
    def test_persistent_readback_needs_independent_evidence(self):
        receipt={
           "race_id":"202611091201",
           "recording_sha256":h("invented-cipher-202611091201"),
           "ciphertext_sha256":h("invented-CIPHERTEXT"),
           "library_path":"/RACE-AI/KeirinVideo/2026-11-09/archive.zip",
           "readback_verified":True
        }
        result=summarize([wave([row(1)])],
                         independent_library_receipts=[receipt])
        self.assertEqual(result["confirmed_private_library_races"],1)
        receipt["readback_verified"]=False
        with self.assertRaisesRegex(CoverageError,"LIBRARY_READBACK_NOT_PROVEN"):
            summarize([wave([row(1)])],
                      independent_library_receipts=[receipt])
    def test_forecast_modification_and_public_footage_rejected(self):
        a=wave([row(1)])
        a["raw_footage_exported"]=True
        with self.assertRaisesRegex(CoverageError,"PLAIN_MEDIA_EXPORTED"):
            summarize([a])
        a=wave([row(1)])
        a["prediction_model_weights_changed"]=True
        with self.assertRaisesRegex(CoverageError,"OFFICIAL_PREDICTION_WEIGHTS_CHANGED"):
            summarize([a])
    def test_false_capture_and_holdout_integrity(self):
        a=wave([row(1, status="PLAYER_NOT_FINISHED")])
        self.assertEqual(summarize([a])["encrypted_unique_races"],0)
        a=wave([row(1)])
        a["race_rows"][0]["cohort"]="UNSEEN_VIDEO_HOLDOUT"
        with self.assertRaisesRegex(CoverageError,"HOLDOUT_COHORT_MISMATCH"):
            summarize([a])
        a=wave([row(1)])
        a["race_rows"][0]["recording_sha256"]="not-a-real-sha"
        with self.assertRaisesRegex(CoverageError,"ENCRYPTED_SUCCESS_MISSING_SCREEN_SHA256"):
            summarize([a])
    def test_same_raw_video_cannot_count_as_two_different_races(self):
        a=wave([row(1),row(2,sha=h("invented-cipher-202611091201"))])
        with self.assertRaisesRegex(CoverageError,"SAME_SCREEN_BYTES_SHARED_BETWEEN_DISTINCT_RACES"):
            summarize([a])
if __name__=="__main__":unittest.main()
