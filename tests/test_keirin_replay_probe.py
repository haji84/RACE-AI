"""Synthetic-only regression for the bounded Matsuyama replay browser probe."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]/"scripts"/"keirin_replay_probe.py"
spec=importlib.util.spec_from_file_location("keirin_replay_probe",MODULE)
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class MatsuyamaReplayPilotTest(unittest.TestCase):
    def test_allowlist(self):
        self.assertTrue(probe.source_allowed(probe.SOURCE_URL))
        for url in [
            "https://other.example/matsuyama/racecard/75202611080100/",
            "http://keirin.kdreams.jp/matsuyama/racecard/75202611080100/",
            "https://keirin.kdreams.jp/matsuyama/racecard/75202611080200/",
            "file:///tmp/test.webm",
        ]:
            self.assertFalse(probe.source_allowed(url))
        self.assertTrue(probe.source_allowed("file:///tmp/test.webm",fixture=True))

    def test_synthetic_video_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            source=folder/"synthetic.webm"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=240x160:rate=10",
                "-t","9","-an","-c:v","libvpx","-b:v","250k",str(source)],
                check=True,timeout=30)
            output=folder/"report.json"
            r=subprocess.run([sys.executable,str(MODULE),
                "--fixture-only","--url",source.as_uri(),
                "--seconds","12","--report",str(output)],
                capture_output=True,text=True,timeout=45)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            proof=json.loads(output.read_text())
            self.assertEqual(proof["playback_state"],"COMPLETE_PLAYER_CLIP_RECORDED")
            self.assertTrue(proof["captures"])
            self.assertEqual(proof["real_race_visual_analysis"],"NOT_PERFORMED")
            self.assertEqual(proof["cause_of_3_5_4"],"UNDETERMINED")
            self.assertFalse(proof["raw_video_public_upload"])
            self.assertTrue(proof["player_clip_completed"])
            self.assertEqual(proof["video_end_reason"],"HTML_VIDEO_ENDED")
            self.assertFalse(proof["whole_unedited_race_verified"])
            # Same 9s synthetic clip, intentionally cut short at 6s.
            partial=folder/"partial.json"
            short=subprocess.run([sys.executable,str(MODULE),
                "--fixture-only","--url",source.as_uri(),
                "--seconds","6","--report",str(partial)],
                capture_output=True,text=True,timeout=35)
            self.assertEqual(short.returncode,2,short.stdout+short.stderr)
            failed=json.loads(partial.read_text())
            self.assertNotEqual(failed["playback_state"],"COMPLETE_PLAYER_CLIP_RECORDED")
            self.assertFalse(failed["player_clip_completed"])

if __name__=="__main__":
    unittest.main()
