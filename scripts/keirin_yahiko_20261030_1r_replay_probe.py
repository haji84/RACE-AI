#!/usr/bin/env python3
"""Verify only the public WINTICKET 2026-10-30 Yahiko 1R past-race video player.

Does not copy video or discover stream URLs; collects HTML5 video metadata
when the page's ordinary visible video button is clicked.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright

URL="https://www.winticket.jp/keirin/yahiko/raceresult/2026103021/1/1"

async def states(page):
    all_states=[]
    for frame in page.frames:
        try:
            all_states.extend(await frame.evaluate("""() =>
              [...document.querySelectorAll('video')].slice(0,6).map(v=>({
                 currentTime:v.currentTime,
                 duration:Number.isFinite(v.duration)?v.duration:null,
                 readyState:v.readyState,networkState:v.networkState,
                 width:v.videoWidth,height:v.videoHeight,
                 paused:v.paused,ended:v.ended,
                 error:v.error?v.error.code:null,
                 seekable:[...Array(v.seekable.length).keys()]
                    .slice(0,4).map(i=>[v.seekable.start(i),v.seekable.end(i)])
              }))"""))
        except Exception:
            continue
    return all_states

async def inspect(out):
    result={"schema":"RACE_AI_YAHIKO_20261030_1R_PUBLIC_VIDEO_PROBE_V1",
        "source_url":URL,"observed_at_utc":datetime.now(timezone.utc).isoformat(),
        "source_copied":False,"stream_url_extracted":False,
        "full_four_laps_independently_verified":False}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,channel="chrome",
          args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
        context=await browser.new_context(locale="ja-JP",timezone_id="Asia/Tokyo",
                                          viewport={"width":1280,"height":800})
        page=await context.new_page()
        popups=[]
        page.on("popup",lambda p:popups.append(p))
        try:
            response=await page.goto(URL,wait_until="domcontentloaded",timeout=25000)
            result["http_status"]=response.status if response else None
            await page.wait_for_timeout(3000)
            result["page_title"]=(await page.title())[:180]
            result["button_clicked"]=False
            result["button_used"]=None
            for candidate in ["text=着順映像を観る","text=映像を見る","text=映像を観る",
                              "button:has-text('映像')"]:
                try:
                    loc=page.locator(candidate).first
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=5000)
                        result["button_clicked"]=True
                        result["button_used"]=candidate
                        break
                except Exception as exc:
                    result["click_failure_type"]=type(exc).__name__
            await page.wait_for_timeout(4300)
            pages=[page]+popups
            before=[]
            for p in pages: before.extend(await states(p))
            result["video_after_click"]=before
            await page.wait_for_timeout(3500)
            after=[]
            for p in pages: after.extend(await states(p))
            result["video_later"]=after
            result["video_time_advanced"]=any(
                b["currentTime"]>=a["currentTime"]+1.0
                for a,b in zip(before,after))
            result["status"]="METADATA_CHECK_COMPLETE"
        except Exception as exc:
            result["status"]="PROBE_ERROR"
            result["error_type"]=type(exc).__name__
            result["error_message"]=str(exc)[:150]
        finally:
            await context.close()
            await browser.close()
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
    return result

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: probe.py result.json")
    r=asyncio.run(inspect(Path(sys.argv[1])))
    if r.get("status")!="METADATA_CHECK_COMPLETE":raise SystemExit(2)
