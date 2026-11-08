#!/usr/bin/env python3
"""Single-event WINTICKET browser replay feasibility test, NO STREAM EXTRACTION.

Purpose: determine whether public browser playback supplies a replay suitable for
Matsuyama 2026-11-08 1R, and whether the /live page offers retrospective DVR.
No screenshots, frames, video bytes, cookies, streams or credentials are saved.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

RACE_ID = "20261108-matsuyama-01"
LIVE_URL = "https://www.winticket.jp/keirin/matsuyama/live"
RACE_RESULT_URL = "https://www.winticket.jp/keirin/matsuyama/raceresult/2026110875/1/1"
ALLOWED = {LIVE_URL, RACE_RESULT_URL}
VIDEO_SEARCH_JS = """() => ({
  videos: [...document.querySelectorAll('video')].slice(0, 8).map(v => ({
    current_time: Number(v.currentTime.toFixed(3)),
    duration: Number.isFinite(v.duration) ? Number(v.duration.toFixed(3)) : null,
    ready_state: v.readyState,
    network_state: v.networkState,
    error_code: v.error ? v.error.code : null,
    width: v.videoWidth, height: v.videoHeight,
    paused: v.paused, ended: v.ended, controls: v.controls,
    seekable: (() => { const a=[]; for(let i=0;i<v.seekable.length;i++){
      a.push([Number(v.seekable.start(i).toFixed(2)),
              Number(v.seekable.end(i).toFixed(2))]);} return a.slice(0,4);})()
  })),
  iframe_count: document.querySelectorAll('iframe').length,
  video_player_hints: [...document.querySelectorAll('[class*=player], [class*=Player], [data-testid*=video], [data-testid*=Video]')]
    .slice(0,12).map(n => ({
       tag: n.tagName,
       class_name: String(n.className||'').slice(0,100),
       test_id: n.getAttribute('data-testid')
    }))
})"""

def source_allowed(url: str) -> bool:
    return url in ALLOWED and urlparse(url).scheme == "https"

async def media_state(page):
    result=[]
    for frame in page.frames[:12]:
        try:
            state=await frame.evaluate(VIDEO_SEARCH_JS)
            state["frame_kind"] = "top" if frame == page.main_frame else "embedded"
            result.append(state)
        except Exception as exc:
            result.append({"frame_kind":"inaccessible","error_type":type(exc).__name__})
    return result

def video_summary(states):
    videos=[v for frame in states for v in frame.get("videos",[])]
    return {
        "count":len(videos),
        "max_current":max((v["current_time"] for v in videos),default=None),
        "max_duration":max((v["duration"] for v in videos if v["duration"] is not None),default=None),
        "playable_video_count":sum(v["ready_state"]>=2 and v["width"]>0 for v in videos),
        "max_seekable_end":max((rng[1] for v in videos for rng in v["seekable"]),default=None),
        "videos":videos[:4],
    }

async def run(report_path: Path) -> dict:
    report={"schema":"RACE_AI_KEIRIN_WINTICKET_REPLAY_FEASIBILITY_V1",
            "race_id":RACE_ID,
            "observed_utc":datetime.now(timezone.utc).isoformat(),
            "pages":{},
            "footage_copied":False,
            "stream_link_extracted":False,
            "authentication_bypassed":False,
            "full_four_laps_verified":False,
            "race_cause_analysis":"NOT_STARTED"}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,channel="chrome",
            args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
        context=await browser.new_context(locale="ja-JP",timezone_id="Asia/Tokyo",
                                         viewport={"width":1280,"height":800})
        for label,url in (("live",LIVE_URL),("race_result",RACE_RESULT_URL)):
            if not source_allowed(url):
                raise ValueError("SOURCE_NOT_ALLOWED")
            page=await context.new_page()
            popups=[]
            page.on("popup",lambda p:popups.append(p))
            info={"url":url,"status":"NOT_OPENED","replay_clicked":False}
            try:
                response=await page.goto(url,wait_until="domcontentloaded",timeout=30000)
                await page.wait_for_timeout(3500)
                info["status"]="PAGE_LOADED"
                info["http_code"]=response.status if response else None
                info["title"]=(await page.title())[:160]
                info["dom_evidence"]={
                    "is_matsuyama":await page.get_by_text("松山",exact=False).count()>0,
                    "has_1r":await page.get_by_text("1R",exact=False).count()>0,
                    "replay_label_count":await page.get_by_text("着順映像を観る",exact=False).count(),
                }
                info["before"]=video_summary(await media_state(page))
                if label=="race_result":
                    selectors=["text=着順映像を観る",
                               "text=映像を観る",
                               "button:has-text('映像')"]
                    for selector in selectors:
                        try:
                            b=page.locator(selector).first
                            if await b.count() and await b.is_visible():
                                await b.click(timeout=5000)
                                info["replay_clicked"]=True
                                info["click_selector"]=selector
                                break
                        except Exception as exc:
                            info["click_error"]=type(exc).__name__
                    await page.wait_for_timeout(4500)
                else:
                    # Confirm ordinary user-facing playback. No stream URL inspection.
                    try:
                        info["play_click"] = await page.evaluate("""async () => {
                          const v=document.querySelector('video');
                          if (!v) return "VIDEO_ELEMENT_MISSING";
                          v.muted=true;
                          try {
                            await Promise.race([
                              v.play().then(()=>true),
                              new Promise((resolve)=>setTimeout(()=>resolve(false),3000))
                            ]);
                            return v.paused?"VIDEO_STILL_PAUSED":"PLAY_REQUEST_ACCEPTED";
                          } catch(e) {return String(e.name||"PLAY_ERROR").slice(0,60);}
                        }""")
                    except Exception as exc:
                        info["play_click_error"]=type(exc).__name__
                    await page.wait_for_timeout(2500)
                info["new_windows"]=len(popups)
                states=[]
                for p in [page]+popups[:3]:
                    states.extend(await media_state(p))
                info["after"]=video_summary(states)
                # Player progression is an additional sanity check; never a 4-lap claim.
                await page.wait_for_timeout(3000)
                states2=[]
                for p in [page]+popups[:3]:
                    states2.extend(await media_state(p))
                info["later"]=video_summary(states2)
                first=info["after"]["max_current"]
                later=info["later"]["max_current"]
                info["video_time_advanced"] = (
                    first is not None and later is not None and later>=first+1.0)
                info["status"]="PROBE_COMPLETE"
            except Exception as exc:
                info["status"]="PROBE_ERROR"
                info["error_type"]=type(exc).__name__
                info["error_preview"]=str(exc)[:180]
            finally:
                report["pages"][label]=info
                try:
                    for p in popups:
                        await p.close()
                    await page.close()
                except Exception:pass
        await context.close()
        await browser.close()
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    return report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    result=asyncio.run(run(args.report))
    for label,page in result["pages"].items():
        print(json.dumps({
            "page":label,"status":page["status"],
            "http_code":page.get("http_code"),
            "title":page.get("title"),
            "replay_clicked":page["replay_clicked"],
            "play_click":page.get("play_click"),
            "dom_evidence":page.get("dom_evidence"),
            "new_windows":page.get("new_windows"),
            "video_before":page.get("before"),
            "video_after":page.get("after"),
            "video_later":page.get("later"),
            "video_time_advanced":page.get("video_time_advanced"),
            "error_type":page.get("error_type"),
        },ensure_ascii=False))
    # Probe exit means metadata collection succeeded. It never implies recording.
    if not any(x["status"]=="PROBE_COMPLETE" for x in result["pages"].values()):
        raise SystemExit("BROWSER_PROBE_FAILED")

if __name__=="__main__":
    main()
