"""Reopen AES-wrapped browser WebM into the already existing BOAT CV pipeline.

All inputs in this suite are synthetic. No camera calibration or verified boat
numbers are supplied, so the output MUST be unvalidated and never a P1 ticket.
"""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
import subprocess
import tempfile
import unittest

from race_ai.boat_screen_record_research import seal_screen
from race_ai.boat_screen_model_bridge import evaluate_encrypted_screen

JST=timezone(timedelta(hours=9))
START=datetime(2030,4,1,11,1,0,tzinfo=JST)
RACE="20300401-24-12"
CUTOFF="2030-04-01T12:00:00+09:00"

def job(digest,kind="SYNTHETIC_TEST"):
    return dict(schema_version="RACE_AI_BOAT_VIDEO_JOB_V1",race_id=RACE,cutoff_at=CUTOFF,
        roster=[dict(lane=i,registration_number=str(4200+i)) for i in range(1,7)],
        source=dict(kind=kind,media_sha256=digest,captured_at=START.isoformat(),
                    identity_status="SYNTHETIC" if kind=="SYNTHETIC_TEST" else "OWNER_DECLARED"))

class ScreenToModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.path=Path(cls.temp.name)/"measured-screen.webm"
        subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                        "testsrc=size=320x240:rate=10","-t","2.0",
                        "-c:v","libvpx","-b:v","300k","-an","-y",str(cls.path)],
                       timeout=30,check=True)
        cls.raw=cls.path.read_bytes()
        cls.sha=sha256(cls.raw).hexdigest()
        cls.cipher=seal_screen(cls.raw,race_id=RACE,
             page_url="https://race.boatcast.jp/replay?jo=03",fixture=True,
             aes_key=b"k"*32,captured_at=START.isoformat())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_research_only_real_cv_measurement_is_non_production(self):
        ticks=iter((START+timedelta(seconds=1),START+timedelta(seconds=6)))
        result=evaluate_encrypted_screen(self.cipher,job(self.sha),
            aes_key=b"k"*32,clock=lambda:next(ticks))
        self.assertEqual(result["status"],"VIDEO_SCREEN_ANALYZED_UNVALIDATED_IDENTITIES")
        self.assertEqual(result["source_role"],"SYNTHETIC_FIXTURE")
        self.assertEqual(result["tracking_lane_candidates"],6)
        self.assertRegex(result["report_sha256"],r"^[0-9a-f]{64}$")
        self.assertFalse(result["production_video_forecast_proven"])
        self.assertFalse(result["model_prediction_generated"])
        self.assertFalse(result["original_forecast_modified"])
        self.assertEqual(result["dataset_status"],"SYNTHETIC_ONLY")

    def test_synthetic_cipher_is_not_convertible_to_real_race_input(self):
        result=evaluate_encrypted_screen(self.cipher,job(self.sha,"OWNER_LOCAL"),
            aes_key=b"k"*32,clock=lambda:START)
        self.assertEqual(result["status"],"HOLD_SCREEN_DATASET_SCOPE_MISMATCH")

    def test_wrong_aes_key_wrong_original_sha_or_cutoff_prevents_evaluation(self):
        self.assertEqual(evaluate_encrypted_screen(self.cipher,job(self.sha),
            aes_key=b"x"*32,clock=lambda:START)["status"],"HOLD_SCREEN_CIPHER_INVALID")
        wrong=job("1"*64)
        self.assertEqual(evaluate_encrypted_screen(self.cipher,wrong,aes_key=b"k"*32,
            clock=lambda:START)["status"],"HOLD_SCREEN_JOB_OR_ORIGINAL_INVALID")
        late=job(self.sha);late["cutoff_at"]="2030-04-01T10:00:00+09:00"
        self.assertNotEqual(evaluate_encrypted_screen(self.cipher,late,aes_key=b"k"*32,
            clock=lambda:START)["status"],"VIDEO_SCREEN_ANALYZED_UNVALIDATED_IDENTITIES")

if __name__=="__main__":
    unittest.main()
