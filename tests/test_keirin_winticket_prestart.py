"""Offline fail-closed regression for WINTICKET start-to-finish capture.

No source network requests, no third-party footage, no real race outcomes.
"""
import json
from datetime import datetime,timedelta
from pathlib import Path
import unittest

from race_ai.keirin_video_lap_gate import (
    PLAN_SCHEMA,VISUAL_SCHEMA,VideoGateError,validate_plan,coverage_gate,
    lap_visual_gate
)
from scripts.keirin_winticket_prestart_recorder import SOURCE,inspect_webm

PLAN=Path(__file__).resolve().parent/"fixtures"/"keirin_matsuyama_full_window_synthetic.json"


def fixture_plan():
    return json.loads(PLAN.read_text())


def mocked_runtime(plan):
    start=datetime.fromisoformat(plan["record_from_at"])-timedelta(seconds=10)
    end=datetime.fromisoformat(plan["record_until_at"])+timedelta(seconds=5)
    samples=[]
    time=start
    n=0
    while time<=end:
        samples.append({
            "observed_at":time.isoformat(),
            "media_time":float(n*5+20),
            "ready_state":4,"paused":False,
            "video_width":640,"video_height":360,"media_error":None})
        time+=timedelta(seconds=5)
        n+=1
    return {
        "recording_started_at":start.isoformat(),
        "recording_ended_at":end.isoformat(),
        "media_samples":samples,
        "video_container_ok":True,
        "frames_checked":True
    }


class LiveFourLapAuditTest(unittest.TestCase):
    def test_fixture_plan_valid_and_production_requires_rights(self):
        p=fixture_plan()
        self.assertEqual(validate_plan(p,synthetic=True)["race_number"],1)
        with self.assertRaisesRegex(VideoGateError,"RECORDING_RIGHTS_UNVERIFIED"):
            validate_plan(p)
        p["recording_rights_ref"]="user_typed_not_authorization"
        self.assertEqual(validate_plan(p)["pre_seconds"],180)

    def test_bad_source_and_date_rejected(self):
        p=fixture_plan()
        p["source_url"]="https://example.com/video"
        with self.assertRaisesRegex(VideoGateError,"SOURCE_NOT_ALLOWLISTED"):
            validate_plan(p,synthetic=True)
        p=fixture_plan();p["race_id"]="20261108-matsuyama-01"
        with self.assertRaisesRegex(VideoGateError,"RACE_JST_DATE_MISMATCH"):
            validate_plan(p,synthetic=True)
        p=fixture_plan();p["race_number"]=5
        with self.assertRaisesRegex(VideoGateError,"RACE_ID_NUMBER_MISMATCH"):
            validate_plan(p,synthetic=True)

    def test_no_shortened_window_or_unsupported_laps(self):
        p=fixture_plan();p["expected_laps"]=3
        with self.assertRaisesRegex(VideoGateError,"FOUR_LAPS_REQUIRED"):
            validate_plan(p,synthetic=True)
        p=fixture_plan();p["record_from_at"]="2026-11-09T20:39:00+09:00"
        with self.assertRaisesRegex(VideoGateError,"CAPTURE_WINDOW_UNSAFE"):
            validate_plan(p,synthetic=True)
        p=fixture_plan();p["record_until_at"]="2026-11-09T20:44:00+09:00"
        with self.assertRaisesRegex(VideoGateError,"CAPTURE_WINDOW_UNSAFE"):
            validate_plan(p,synthetic=True)

    def test_fully_observed_but_no_lap_proof(self):
        p=fixture_plan()
        good=coverage_gate(p,mocked_runtime(p),synthetic=True)
        self.assertEqual(good["status"],"CAPTURE_WINDOW_HEALTHY")
        self.assertTrue(good["capture_window_complete"])
        self.assertFalse(good["four_laps_verified"])
        gate=lap_visual_gate(good,None,synthetic=True)
        self.assertEqual(gate["status"],"VISUAL_EVIDENCE_NOT_AVAILABLE")
        self.assertFalse(gate["four_laps_verified"])

    def test_late_cutoff_and_stalled_player_are_rejected(self):
        p=fixture_plan()
        runtime=mocked_runtime(p)
        runtime["recording_started_at"]=(
            datetime.fromisoformat(p["record_from_at"])+
            timedelta(seconds=6)).isoformat()
        self.assertEqual(coverage_gate(p,runtime,synthetic=True)["status"],
                         "STARTED_TOO_LATE")
        runtime=mocked_runtime(p)
        runtime["media_samples"][5]["media_time"]=runtime["media_samples"][4]["media_time"]
        self.assertEqual(coverage_gate(p,runtime,synthetic=True)["status"],
                         "PLAYER_STALLED_OR_SEEKED")
        runtime=mocked_runtime(p)
        runtime["media_samples"][3]["paused"]=True
        self.assertEqual(coverage_gate(p,runtime,synthetic=True)["status"],
                         "PLAYER_UNHEALTHY")
        runtime=mocked_runtime(p)
        runtime["media_samples"].pop(5)
        runtime["media_samples"].pop(5)
        self.assertEqual(coverage_gate(p,runtime,synthetic=True)["status"],
                         "HEARTBEAT_GAP")
        runtime=mocked_runtime(p)
        runtime["frames_checked"]=False
        self.assertEqual(coverage_gate(p,runtime,synthetic=True)["status"],
                         "RENDERED_VIDEO_FRAMES_NOT_VERIFIED")
        runtime=mocked_runtime(p)
        runtime["video_container_ok"]=False
        self.assertEqual(coverage_gate(p,runtime,synthetic=True)["status"],
                         "RECORDING_FILE_INVALID")

    def test_forged_visual_cannot_claim_four_laps(self):
        p=fixture_plan()
        complete=coverage_gate(p,mocked_runtime(p),synthetic=True)
        events=["race_start","lap4","lap3","lap2","lap1","finish"]
        visual={"schema":VISUAL_SCHEMA,"synthetic_only":True,
                "source":"INDEPENDENT_VERIFIED_VISION","validator_version":"v1",
                "real_capture_sha256":"d"*64,"identity_attested":True,
                "observations":[{
                   "event":name,"recording_sec":i*40.,
                   "confidence":0.99,"frame_sha256":f"{i+1:064x}"
                } for i,name in enumerate(events)]}
        r=lap_visual_gate(complete,visual,synthetic=True)
        self.assertEqual(r["status"],"SYNTHETIC_VISUAL_EVIDENCE_ONLY")
        self.assertFalse(r["four_laps_verified"])
        visual["synthetic_only"]=False
        visual["observations"][2]["event"]="lap4"
        r=lap_visual_gate(complete,visual)
        self.assertEqual(r["status"],"FOUR_LAP_VISUAL_SEQUENCE_MISSING")
        visual["observations"][2]["event"]="lap3"
        visual["race_id"]=p["race_id"]
        r=lap_visual_gate(complete,visual)
        self.assertEqual(r["status"],"RAW_RECORDING_DIGEST_NOT_ATTESTED")
        bound=dict(complete,recording_sha256="d"*64,
                   frame_inventory=[{
                      "recording_sec":i*40.,
                      "frame_sha256":f"{i+1:064x}"}
                      for i in range(6)],race_id=p["race_id"])
        r=lap_visual_gate(bound,visual)
        self.assertEqual(r["status"],"INDEPENDENT_ATTESTATION_MISSING")
        self.assertFalse(r["four_laps_verified"])
        r=lap_visual_gate(bound,visual,
                   independent_attestor=lambda e,c:False)
        self.assertEqual(r["status"],"INDEPENDENT_ATTESTATION_REJECTED")

    def test_live_capture_cannot_start_without_owner_rights_gate(self):
        import asyncio
        import os
        import tempfile
        from unittest.mock import patch
        from scripts.keirin_winticket_prestart_recorder import run_live
        p=fixture_plan()
        p["recording_rights_ref"]="INDEPENDENT_RIGHTS_EVIDENCE_REQUIRED"
        with tempfile.TemporaryDirectory() as t:
            report=Path(t)/"status.json"
            with patch.dict(os.environ,{},clear=True):
                answer=asyncio.run(run_live(
                    p,report,fixture=False,test_seconds=9))
            self.assertEqual(answer["status"],
                             "SOURCE_RECORDING_RIGHTS_GATE_BLOCKED")
            self.assertFalse(answer["four_laps_verified"])
            self.assertTrue(report.exists())
            self.assertNotIn("recording_file",answer)

    def test_video_garbage_is_not_a_recording(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"broken.webm"
            path.write_bytes(b"fake")
            self.assertFalse(inspect_webm(path)["valid"])


if __name__=="__main__":
    unittest.main()
