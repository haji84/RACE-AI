"""Provider 403/429 stops a daily replay wave without retries or fake labels.

Entirely offline: fake browser pages and imaginary race IDs, no real GET.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import asyncio
import json
import unittest

from scripts.keirin_winticket_historical_batch_capture import capture_one
from scripts import keirin_daily_dynamic_clip_collector as collector

ROOT=Path(__file__).resolve().parents[1]
PUBLIC_KEY=ROOT/"docs/keirin-historical-batch-20261109-public.pem"


def source(i):
    return {
        "race_id":f"2030011512{i:02d}",
        "venue":"架空場","date":"2030年1月15日","race_no":i,
        "cohort":"TRAIN_CANDIDATE",
        "url":f"https://www.winticket.jp/keirin/aomori/raceresult/2030011512/1/{i}",
    }


class FakePage:
    video=None
    def __init__(self, code, url):
        self.code,self.url,self.title_calls=code,url,0
    async def goto(self, *args, **kwargs):
        return SimpleNamespace(status=self.code)
    async def wait_for_timeout(self, timeout):
        if self.code in (403,429):
            raise AssertionError("DENIED_PAGE_MUST_NOT_WAIT_OR_POLL")
    async def title(self):
        self.title_calls+=1
        if self.code in (403,429):
            raise AssertionError("DENIED_PAGE_MUST_NOT_READ_TITLE")
        return "mismatched venue"


class FakeBrowser:
    def __init__(self, page=None):
        self.page=page
        self.closed=False
    async def new_context(self, **kwargs):
        browser=self
        class Context:
            async def new_page(self):
                return browser.page
            async def close(self):
                browser.closed=True
        return Context()
    async def close(self):
        self.closed=True


class FakePlaywrightContext:
    def __init__(self):
        self.browser=FakeBrowser()
    async def __aenter__(self):
        async def launch(**kwargs):
            return self.browser
        return SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    async def __aexit__(self,*args):
        pass


class SinglePageDenialTests(unittest.IsolatedAsyncioTestCase):
    async def test_403_429_are_denials_not_identity_mismatch(self):
        with TemporaryDirectory() as tmp:
            for code in (403,429):
                s=source(1)
                page=FakePage(code,s["url"])
                browser=FakeBrowser(page)
                out=await capture_one(browser,s,Path(tmp),PUBLIC_KEY)
                self.assertEqual(out["http_status"],code)
                self.assertEqual(out["technical_status"],"SOURCE_ACCESS_DENIED_NO_RETRY")
                self.assertEqual(out["failure_before_integrity_check"],
                                 "SOURCE_ACCESS_DENIED_NO_RETRY")
                self.assertNotIn("screen_sha256",out)
                self.assertNotIn("encrypted_capture_count",out)
                self.assertEqual(page.title_calls,0)
                self.assertTrue(browser.closed)

    async def test_200_with_wrong_title_is_real_identity_failure(self):
        with TemporaryDirectory() as tmp:
            s=source(1)
            page=FakePage(200,s["url"])
            out=await capture_one(FakeBrowser(page),s,Path(tmp),PUBLIC_KEY)
            self.assertEqual(out["technical_status"],"RACE_IDENTITY_MISMATCH")
            self.assertEqual(page.title_calls,1)
            self.assertNotIn("encrypted_capture_count",out)


class DailyBatchDenialTests(unittest.IsolatedAsyncioTestCase):
    async def _wave(self, first_code, total=3):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            args=SimpleNamespace(
                previous_day_manifest=None,private_retention_receipts=None,
                temporary_artifact_receipts=None,plan_only=False,max_races=24,
                owner_public_key=PUBLIC_KEY,report=root/"wave.json",
                manifest=root/"manifest.json",encrypted_dir=root/"sealed",
                sealed_research_dir=None,
            )
            sources=[source(i) for i in range(1,total+1)]
            manifest={
                "date_jst":"2030-01-15","manifest_sha256":"a"*64,
                "discovered_venue_count":1,"discovered_race_count":total,
                "races":sources,
            }
            batch={
                "selected":sources,
                "races_visible_on_result_index":total,
                "durably_archived_with_attested_readback":0,
                "not_selected_due_to_wave_cap":0,
            }
            requested=[]
            async def discover(day):
                return manifest
            async def capture(browser,row,folder,pub,**kwargs):
                requested.append(row["race_id"])
                if first_code in (403,429):
                    return {
                        "technical_status":"SOURCE_ACCESS_DENIED_NO_RETRY",
                        "http_status":first_code,
                        "failure_before_integrity_check":"SOURCE_ACCESS_DENIED_NO_RETRY",
                    }
                return {
                    "technical_status":"NO_VISIBLE_REPLAY_CONTROL","http_status":200
                }
            with patch.object(collector,"discover",new=discover), \
                 patch.object(collector,"select",return_value=batch), \
                 patch.object(collector,"capture_one",new=capture), \
                 patch.object(collector,"async_playwright",new=FakePlaywrightContext):
                result=await collector.run(args)
            self.assertEqual(result,json.loads(args.report.read_text()))
            return result,requested

    async def test_403_stops_before_remaining_races(self):
        result,requested=await self._wave(403)
        self.assertEqual(result["attempted"],1)
        self.assertEqual(len(requested),1)
        self.assertEqual(result["encrypted"],0)
        self.assertEqual(result["provider_denial_http_status"],403)
        self.assertEqual(result["provider_denial_deferred_in_wave"],2)
        self.assertTrue(result["provider_denial_stopped_wave"])
        self.assertEqual(result["status"],"HOLD_PROVIDER_ACCESS_DENIED_NO_RETRY")
        self.assertEqual(result["race_rows"][0]["failure_type"],
                         "SOURCE_ACCESS_DENIED_NO_RETRY")

    async def test_429_stops_before_remaining_races(self):
        result,requested=await self._wave(429)
        self.assertEqual(len(requested),1)
        self.assertEqual(result["provider_denial_http_status"],429)
        self.assertEqual(result["provider_denial_deferred_in_wave"],2)

    async def test_no_control_does_not_masquerade_as_403(self):
        result,requested=await self._wave(200,total=2)
        self.assertEqual(len(requested),2)
        self.assertFalse(result["provider_denial_stopped_wave"])
        self.assertEqual(result["status"],"WAVE_RECORDED_OR_FAILED_PER_RACE")
        self.assertEqual(result["encrypted"],0)


if __name__=="__main__":
    unittest.main()
