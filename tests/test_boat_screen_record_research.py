"""Browser-only BOAT exhibition video research, no provider access in CI."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock

from race_ai.actions_contract import digest

JST=timezone(timedelta(hours=9))
NOW=datetime(2030,4,1,11,0,tzinfo=JST)
RACE="20300401-24-12"
CUT="2030-04-01T12:00:00+09:00"

def source(**changes):
    data=dict(schema="RACE_AI_BOAT_SCREEN_SOURCE_V1",race_id=RACE,cutoff_at=CUT,
        page_url="https://race.boatcast.jp/replay?jo=03",mode="REPLAY",
        play_selector=None)
    data.update(changes)
    return data

def grant(**changes):
    data=dict(schema="RACE_AI_BOAT_SCREEN_RIGHTS_V1",race_id=RACE,
        page_url="https://race.boatcast.jp/replay?jo=03",
        rights_evidence_sha256="a"*64,grant_type="RIGHTS_HOLDER_WRITTEN_GRANT",
        permitted_uses=["SCREEN_RECORDING","PRIVATE_VIDEO_ANALYSIS","RESEARCH_P1_DERIVATION"],
        valid_from="2030-04-01T00:00:00+09:00",
        valid_until="2030-04-02T00:00:00+09:00",private_only=True)
    data.update(changes)
    return data

def verify_grant(value,request):
    assert value["race_id"] == request["race_id"]
    return dict(state="INDEPENDENT_RIGHTS_RECEIPT_VERIFIED",
                manifest_sha256=digest(value),
                evidence_sha256=value["rights_evidence_sha256"],
                verified_at=NOW.isoformat())

class ScreenAdmissionTests(unittest.TestCase):
    def test_no_grant_or_no_independent_reader_cannot_open_browser(self):
        from race_ai.boat_screen_record_research import preflight
        self.assertEqual(preflight(source(),None,now=NOW,verify_grant=None)["status"],
                         "HOLD_SCREEN_RIGHTS_UNAVAILABLE")
        self.assertEqual(preflight(source(),grant(),now=NOW,verify_grant=None)["status"],
                         "HOLD_SCREEN_RIGHTS_UNAVAILABLE")

    def test_exact_race_url_cutoff_and_grant_scope_are_required(self):
        from race_ai.boat_screen_record_research import preflight
        for request,permit in [
            (source(race_id="20300401-01-01"),grant()),
            (source(page_url="https://example.org/replay"),grant()),
            (source(page_url="http://race.boatcast.jp/replay?jo=03"),grant()),
            (source(page_url="https://race.boatcast.jp/replay?jo=03#token"),grant()),
            (source(cutoff_at="2030-04-02T12:00:00+09:00"),grant()),
            (source(mode="AUTOMATIC_BYPASS"),grant()),
            (source(play_selector="input[type=password]"),grant()),
            (source(),grant(grant_type="PUBLIC_FAQ_ONLY")),
            (source(),grant(permitted_uses=["SCREEN_RECORDING","PRIVATE_VIDEO_ANALYSIS"])),
            (source(),grant(page_url="https://other.example.com")),
            (source(),grant(valid_until="2030-03-01T00:00:00+09:00"))
        ]:
            with self.subTest(request=request,permit=permit):
                self.assertNotEqual(preflight(request,permit,now=NOW,
                                              verify_grant=verify_grant)["status"],
                                    "READY_PRIVATE_SCREEN_RESEARCH_ONLY")

    def test_approved_grant_never_proves_model_or_public_video_use(self):
        from race_ai.boat_screen_record_research import preflight
        s=source();g=grant();before=deepcopy((s,g))
        result=preflight(s,g,now=NOW,verify_grant=verify_grant)
        self.assertEqual(result["status"],"READY_PRIVATE_SCREEN_RESEARCH_ONLY")
        self.assertFalse(result["production_video_forecast_proven"])
        self.assertFalse(result["source_fetch_performed"])
        self.assertFalse(result["public_video_approved"])
        self.assertEqual((s,g),before)

    def test_no_grant_stops_before_playwright_opens_a_page(self):
        from race_ai.boat_screen_record_research import record_screen
        fake=AsyncMock()
        out=asyncio.run(record_screen(fake,source(),None,verify_grant=None,now=NOW,
                                     aes_key=b"k"*32))
        fake.new_context.assert_not_called()
        self.assertEqual(out["status"],"HOLD_SCREEN_RIGHTS_UNAVAILABLE")

class ScreenRecorderRealBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shutil import which
        if which("ffmpeg") is None or which("ffprobe") is None:
            raise unittest.SkipTest("ffmpeg must be installed for the real browser fixture")
        from playwright.async_api import async_playwright
        cls.fixture=tempfile.TemporaryDirectory()
        cls.media=Path(cls.fixture.name)/"synthetic-replay.webm"
        subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                        "testsrc=size=320x240:rate=12","-t","2.0",
                        "-c:v","libvpx","-b:v","400k","-an","-y",str(cls.media)],
                       check=True,timeout=25)
        cls.payload=base64.b64encode(cls.media.read_bytes()).decode("ascii")
        cls.live_media=Path(cls.fixture.name)/"synthetic-live.webm"
        subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                        "testsrc=size=320x240:rate=12","-t","10.0",
                        "-c:v","libvpx","-b:v","250k","-an","-y",str(cls.live_media)],
                       check=True,timeout=35)
        cls.live_payload=base64.b64encode(cls.live_media.read_bytes()).decode("ascii")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,"fixture"):cls.fixture.cleanup()

    def test_browser_visible_html5_playback_is_encrypted_then_sha_reopened(self):
        from playwright.async_api import async_playwright
        from race_ai.boat_screen_record_research import record_screen,unseal_screen
        async def record():
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(headless=True,
                    args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
                try:
                    async def fixture_loader(page):
                        await page.set_content(
                            '<html><body><video controls autoplay muted playsinline '+
                            'width="320" height="240" src="data:video/webm;base64,'+
                            self.payload+'"></video></body></html>')
                    return await record_screen(browser,source(),grant(),
                        verify_grant=verify_grant,now=NOW,aes_key=b"k"*32,
                        fixture_loader=fixture_loader,timeout_seconds=12)
                finally:
                    await browser.close()
        outcome=asyncio.run(record())
        self.assertEqual(outcome["status"],"SCREEN_REPLAY_CAPTURE_ENCRYPTED_UNVALIDATED")
        self.assertEqual(outcome["source_class"],"SYNTHETIC_OFFLINE_BROWSER_FIXTURE")
        self.assertIsNotNone(outcome["envelope"])
        self.assertEqual(outcome["media_sha256"],
                         hashlib.sha256(unseal_screen(outcome["envelope"],
                                                       aes_key=b"k"*32)).hexdigest())
        self.assertGreater(outcome["screen_recording_bytes"],1000)
        self.assertTrue(outcome["player_ended"])
        self.assertFalse(outcome["production_video_forecast_proven"])
        with self.assertRaises(ValueError):
            unseal_screen(outcome["envelope"],aes_key=b"j"*32)

    def test_live_window_records_visible_movement_without_forging_natural_end(self):
        from playwright.async_api import async_playwright
        from race_ai.boat_screen_record_research import record_screen,unseal_screen
        async def record():
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(headless=True,
                    args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
                try:
                    async def fixture_loader(page):
                        await page.set_content(
                            '<html><body><video controls autoplay muted playsinline '+
                            'width="320" height="240" src="data:video/webm;base64,'+
                            self.live_payload+'"></video></body></html>')
                    return await record_screen(browser,source(mode="LIVE_WINDOW"),grant(),
                        verify_grant=verify_grant,now=NOW,aes_key=b"k"*32,
                        fixture_loader=fixture_loader,timeout_seconds=5)
                finally:
                    await browser.close()
        outcome=asyncio.run(record())
        self.assertEqual(outcome["status"],"SCREEN_LIVE_WINDOW_ENCRYPTED_UNVALIDATED")
        self.assertEqual(outcome["source_class"],"SYNTHETIC_OFFLINE_BROWSER_FIXTURE")
        self.assertFalse(outcome["player_ended"])
        self.assertGreater(outcome["screen_duration_seconds"],3)
        self.assertGreater(outcome["screen_recording_bytes"],1000)
        self.assertEqual(outcome["media_sha256"],
                         hashlib.sha256(unseal_screen(outcome["envelope"],aes_key=b"k"*32)).hexdigest())
        self.assertFalse(outcome["production_video_forecast_proven"])

    def test_player_not_ended_is_not_retained_as_complete_exhibition(self):
        from playwright.async_api import async_playwright
        from race_ai.boat_screen_record_research import record_screen
        async def record():
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(headless=True,args=["--no-sandbox"])
                try:
                    async def fixture_loader(page):
                        await page.set_content("<html><body>NO VIDEO</body></html>")
                    return await record_screen(browser,source(),grant(),
                        verify_grant=verify_grant,now=NOW,aes_key=b"k"*32,
                        fixture_loader=fixture_loader,timeout_seconds=2)
                finally:
                    await browser.close()
        out=asyncio.run(record())
        self.assertEqual(out["status"],"HOLD_VISIBLE_PLAYER_NOT_COMPLETE")
        self.assertIsNone(out.get("envelope"))
        self.assertFalse(out["production_video_forecast_proven"])

if __name__=="__main__":
    unittest.main()
