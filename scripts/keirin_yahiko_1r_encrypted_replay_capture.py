#!/usr/bin/env python3
"""One-time WINTICKET Yahiko 2026-10-30 1R browser replay capture for review.

User reports WINTICKET use is OK. The precise authorization/third-party rights
terms were not supplied; keep source private, do not publish or train on it
without separate reviewed frame evidence. Reuses the existing RSA/AES-GCM
recorder; does not fetch direct media stream URLs or bypass access controls.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
from playwright.async_api import async_playwright
from scripts.keirin_replay_probe import (
    encrypt_recordings,video_metadata,watch_to_player_end)

RACE_ID="20261030-yahiko-1R"
RACE_URL="https://www.winticket.jp/keirin/yahiko/raceresult/2026103021/1/1"

def recording_complete(start,finish,frame_meta):
    if not start or not finish or not isinstance(frame_meta,dict):
        return False
    duration=finish.get("duration")
    if not isinstance(duration,(int,float)) or not 30<=duration<=600:
        return False
    fmt=frame_meta.get("ffprobe",{}).get("format",{})
    stream=frame_meta.get("ffprobe",{}).get("streams",[])
    try:
        length=float(fmt["duration"])
    except (ValueError,KeyError,TypeError):
        return False
    # Browser playback from close to 0 until ended and stored WebM covers
    # at least the video time span. This does not prove uncut four-lap content.
    return (length>=duration-3 and length<=duration+90
       and start.get("currentTime",-1)>=0
       and start.get("currentTime",100)<=5
       and finish.get("ended") is True
       and finish.get("currentTime",0)>=duration-1.5
       and any(int(s.get("width",0))>=640 and int(s.get("height",0))>=360
               for s in stream))

async def execute(report_path:Path,encrypted_dir:Path,public_key:Path):
    report={"schema":"RACE_AI_YAHIKO_HISTORICAL_ENCRYPTED_SCREEN_RECORD_V1",
      "race_id":RACE_ID,"source_url":RACE_URL,
      "observed_at":datetime.now(timezone.utc).isoformat(),
      "permission_reported_by_owner":True,
      "permission_exact_scope_supplied":False,
      "raw_video_public":False,"stream_url_extracted":False,
      "four_laps_verified":False,"video_training_admitted":False,
      "status":"NOT_STARTED"}
    report_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="keirin-yahiko-browser-private-") as tmp:
        captured=None
        try:
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(headless=True,channel="chrome",
                    args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
                context=await browser.new_context(
                    locale="ja-JP",timezone_id="Asia/Tokyo",
                    viewport={"width":1280,"height":720},
                    record_video_dir=tmp,record_video_size={"width":1280,"height":720})
                page=await context.new_page()
                try:
                    response=await page.goto(RACE_URL,
                        wait_until="domcontentloaded",timeout=26000)
                    report["source_http_status"]=response.status if response else None
                    report["page_title"]=(await page.title())[:155]
                    if report["source_http_status"]!=200 or (
                       "弥彦" not in report["page_title"] or "1レース" not in report["page_title"]):
                        report["status"]="SOURCE_IDENTITY_MISMATCH"
                    else:
                        # Do not open the page source, browser network logs or
                        # direct media links; click user-facing replay control.
                        loc=page.locator("text=映像を観る").first
                        if not await loc.count() or not await loc.is_visible():
                            report["status"]="NO_VISIBLE_REPLAY_CONTROL"
                        else:
                            await loc.click(timeout=5000)
                            await page.wait_for_timeout(850)
                            first,last,proved,samples,reason=await watch_to_player_end(
                                page,seconds=160,fixture=False)
                            report["player_status"]=reason
                            report["player_samples"]=samples
                            report["player_duration"]=last.get("duration") if last else None
                            report["player_ended"]=bool(last and last.get("ended"))
                            report["player_started_near_zero"]=bool(
                                first and first.get("currentTime",100)<=5)
                            report["watch_completed"]=proved
                            report["status"]=(
                                "BROWSER_PLAYER_ENDED"
                                if proved else "BROWSER_CLIP_NOT_COMPLETE")
                finally:
                    await context.close()
                    try:
                        if page.video:captured=Path(await page.video.path())
                    except Exception as exc:
                        report["recording_path_error"]=type(exc).__name__
                    await browser.close()
        except Exception as exc:
            report["status"]="BROWSER_CAPTURE_ERROR"
            report["error_type"]=type(exc).__name__
            report["error_summary"]=str(exc)[:180]
        if captured and captured.is_file():
            technical=video_metadata(captured)
            report["capture_technical"]=technical
            if report["status"]=="BROWSER_PLAYER_ENDED" and recording_complete(
                    first,last,technical):
                count=encrypt_recordings(
                    [captured],public_key,encrypted_dir,race_id=RACE_ID)
                report["encrypted_capture_count"]=count
                report["status"]="ENCRYPTED_FULL_REPLAY_PLAYER_CAPTURED"
            else:
                report["status"]="SCREEN_CAPTURE_INCOMPLETE_NOT_EXPORTED"
        report_path.write_text(json.dumps(
            report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--report",required=True,type=Path)
    p.add_argument("--encrypted-dir",required=True,type=Path)
    p.add_argument("--public-key",required=True,type=Path)
    a=p.parse_args()
    r=asyncio.run(execute(a.report,a.encrypted_dir,a.public_key))
    # Only technical facts, never the recorded copyrighted browser pixels.
    print(json.dumps({k:r.get(k) for k in (
       "race_id","status","source_http_status","player_status",
       "player_duration","player_samples","player_ended",
       "player_started_near_zero","encrypted_capture_count",
       "four_laps_verified","video_training_admitted","error_type")},
       ensure_ascii=False))
    if r["status"]!="ENCRYPTED_FULL_REPLAY_PLAYER_CAPTURED":
        raise SystemExit(2)

if __name__=="__main__": main()
