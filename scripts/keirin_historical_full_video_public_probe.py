#!/usr/bin/env python3
"""One-shot public historical race VIDEO PAGE feasibility check (no media copying).

The mere existence of a past-race player or of a 4-minute duration does NOT
prove an unedited four-lap race. Only independent frame review can admit it.
No stream URL extraction, login/DRM bypass, repeating retries or video capture.
"""
from __future__ import annotations

import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

from playwright.async_api import async_playwright

SOURCES=(
    ("oddspark_mobile_public_replay",
     "https://sp.oddspark.com/keirin/yosou/movie/archive/?editionNo=00&gradeCd=03&joCode=84&kaisaiBi=20260418&raceNo=1"),
    ("ito_keirin_past_on_demand",
     "https://www.itokeirin.com/ondemand/"),
    ("toyama_keirin_public_history",
     "https://www.toyama-keirin.com/raceinfo/digest"),
    ("kumamoto_keirin_official_broadcast_index",
     "https://www.kumamotokeirin.jp/race-info/live/"),
)

async def public_media_state(page):
    return await page.evaluate("""() => {
      const playable=[...document.querySelectorAll('video')].slice(0,6)
        .map(v=>({
          duration:Number.isFinite(v.duration)?Number(v.duration.toFixed(2)):null,
          width:v.videoWidth,height:v.videoHeight,paused:v.paused,
          ready_state:v.readyState,error_code:v.error?.code??null,
          max_seekable:v.seekable?.length?v.seekable.end(v.seekable.length-1):null
        }));
      return {
        video_count:document.querySelectorAll('video').length,
        iframe_count:document.querySelectorAll('iframe').length,
        loaded_media:playable,
        listed_race_links:[...document.querySelectorAll('a[href]')]
           .filter(a=>/\\b[0-9]{1,2}\\s*R\\b|レース映像|過去レース|過去のレース/.test(
             a.innerText?.trim()||''))
           .slice(0,10).map(a=>({label:a.innerText.trim().slice(0,65),
                                 host:(new URL(a.href)).hostname})),
      };
    }""")

async def main():
    report={"schema":"RACE_AI_HISTORIC_FULL_RACE_PUBLIC_SOURCE_PROBE_V1",
            "time_utc":datetime.now(timezone.utc).isoformat(),
            "only_public_browser_metadata":True,
            "no_stream_extraction":True,"no_video_persisted":True,
            "sources":[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,channel="chrome",
                                          args=["--no-sandbox"])
        context=await browser.new_context(locale="ja-JP",timezone_id="Asia/Tokyo")
        for name,url in SOURCES:
            page=await context.new_page()
            r={"source":name,"url":url}
            try:
                response=await page.goto(url,wait_until="domcontentloaded",
                                         timeout=20000)
                await page.wait_for_timeout(1800)
                r["http_code"]=response.status if response else None
                r["title"]=(await page.title())[:120]
                if r["http_code"]!=200 or "Access Denied" in r["title"]:
                    r["status"]="PUBLIC_ACCESS_UNAVAILABLE"
                else:
                    r["status"]="INDEX_PRESENT_NOT_FOUR_LAP_PROOF"
                    r["media"]=await public_media_state(page)
            except Exception as exc:
                r["status"]="PAGE_NOT_ACCESSIBLE"
                r["error_type"]=type(exc).__name__
            finally:
                report["sources"].append(r)
                await page.close()
        await context.close()
        await browser.close()
    Path(sys.argv[1]).write_text(json.dumps(
        report,ensure_ascii=False,indent=2),encoding="utf-8")
    for row in report["sources"]:
        print(json.dumps({
            "source":row["source"],"status":row["status"],
            "http_code":row.get("http_code"),
            "title":row.get("title"),
            "media":row.get("media"),
            "error_type":row.get("error_type")},
            ensure_ascii=False))
if __name__=="__main__":
    asyncio.run(main())
