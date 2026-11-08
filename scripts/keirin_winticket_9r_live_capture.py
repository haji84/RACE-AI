#!/usr/bin/env python3
"""One-time WINTICKET Matsuyama live screencast, no direct stream extraction.

Capture begins before a verified scheduled race and continues after finish.
A continuous file and browser time progression are necessary but NOT sufficient
proof of all four laps; do not set four_laps_verified without visual evidence.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from playwright.async_api import async_playwright
from scripts.keirin_replay_probe import encrypt_recordings

URL="https://www.winticket.jp/keirin/matsuyama/live"
RACE="2026-11-08-matsuyama-9R"
START=datetime.fromisoformat("2026-11-08T23:17:30+09:00")
RACE_START=datetime.fromisoformat("2026-11-08T23:20:00+09:00")
END=datetime.fromisoformat("2026-11-08T23:26:00+09:00")

def jst_now():
    return datetime.now(timezone.utc).astimezone(START.tzinfo)

def feasible(now, start=START, scheduled=RACE_START, end=END):
    """Fail closed if recording could not start before scheduled race time."""
    return now <= scheduled and start < scheduled < end and         (end-start).total_seconds() <= 11*60

def coverage_ok(samples, started, finished, expected_race=RACE_START):
    """Technical continuity gate only; NOT a four-lap visual verification."""
    if not started or not finished or not started < expected_race < finished:
        return False
    if len(samples)<8:return False
    times=[datetime.fromisoformat(x["utc"]) for x in samples]
    if (times[-1]-times[0]).total_seconds()<210:return False
    if any((b-a).total_seconds()>8 for a,b in zip(times,times[1:])):return False
    good=[x for x in samples if x["ready"]>=2 and x["width"]>=320
          and x["height"]>=180 and not x["paused"] and x["error"] is None]
    if len(good)/len(samples)<0.85:return False
    # For live HLS, currentTime may reset at segment edges.
    # Report discontinuities separately, never silently treat them as four laps.
    if sum(1 for a,b in zip(good,good[1:]) if b["position"]<a["position"]-3)>0:
        return False
    return True

async def video_info(page):
    return await page.evaluate("""() => {
       let v=document.querySelector('video');
       if(!v)return null;
       return {
          position:Number(v.currentTime.toFixed(2)),
          width:v.videoWidth,height:v.videoHeight,
          ready:v.readyState,paused:v.paused,ended:v.ended,
          error:v.error?v.error.code:null
       };
    }""")

async def record(report_path: Path, encrypted_dir: Path, public_key: Path):
    record={"schema":"RACE_AI_WINTICKET_UNCUT_LIVE_CAPTURE_V1",
            "race_id":RACE,"live_url":URL,"scheduled":RACE_START.isoformat(),
            "window":[START.isoformat(),END.isoformat()],
            "status":"NOT_STARTED","four_laps_verified":False,
            "start_gate":False,"finish_gate":False,
            "rider_tracking":"NOT_PERFORMED","stream_extraction":False,
            "browser_screen_recording":True,"direct_download":False}
    report_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="race-ai-live-9r-") as tmp:
        result_webm=None
        try:
            now=jst_now()
            record["actual_started_check"]=now.isoformat()
            if not feasible(now):
                record["status"]="MISSED_PRE_START_OR_INVALID_WINDOW"
            else:
                async with async_playwright() as pw:
                    browser=await pw.chromium.launch(headless=True,channel="chrome",
                       args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
                    context=await browser.new_context(
                       locale="ja-JP",timezone_id="Asia/Tokyo",
                       viewport={"width":1280,"height":720},
                       record_video_size={"width":1280,"height":720},
                       record_video_dir=tmp)
                    page=await context.new_page()
                    try:
                        response=await page.goto(URL,wait_until="domcontentloaded",
                                                 timeout=25000)
                        record["source_http"]=response.status if response else None
                        title=await page.title()
                        record["source_title"]=title[:150]
                        if record["source_http"]!=200 or "松山競輪" not in title:
                            record["status"]="SOURCE_NOT_MATCHED"
                        else:
                            while jst_now()<START:
                                await asyncio.sleep(min(2,max(0.1,(START-jst_now()).total_seconds())))
                            record["first_capture_clock"]=jst_now().isoformat()
                            record["start_gate"]=record["first_capture_clock"] < RACE_START.isoformat()
                            await page.evaluate("""() => {
                              const v=document.querySelector('video');
                              if(v){v.muted=true;v.play().catch(()=>{});}
                            }""")
                            record["status"]="MONITORING_LIVE"
                            samples=[];tries=0
                            while jst_now()<END:
                                now=jst_now()
                                state=await video_info(page)
                                if state is not None:
                                    state["utc"]=now.astimezone(timezone.utc).isoformat()
                                    samples.append(state)
                                    if state["paused"] and tries<6:
                                        tries+=1
                                        await page.evaluate("""() => {
                                          let v=document.querySelector('video');
                                          if(v)v.play().catch(()=>{});
                                        }""")
                                else:
                                    record["missing_video_samples"]=record.get("missing_video_samples",0)+1
                                await asyncio.sleep(2)
                            finished=jst_now()
                            record["last_capture_clock"]=finished.isoformat()
                            record["finish_gate"]=finished>=END
                            record["sample_count"]=len(samples)
                            record["first_sample"]=samples[0] if samples else None
                            record["last_sample"]=samples[-1] if samples else None
                            record["sample_clock_gaps_max_sec"]=max(
                                 [(datetime.fromisoformat(b["utc"])-
                                   datetime.fromisoformat(a["utc"])).total_seconds()
                                  for a,b in zip(samples,samples[1:])] or [None],
                                 key=lambda x: x if x is not None else -1)
                            record["technical_coverage"]=coverage_ok(
                                 samples,datetime.fromisoformat(record["first_capture_clock"]),
                                 finished)
                            record["status"]="LIVE_WINDOW_CAPTURED" if record["technical_coverage"] else "LIVE_WINDOW_INCOMPLETE"
                    finally:
                        await context.close()
                        try:
                            if page.video:
                                result_webm=Path(await page.video.path())
                        except Exception as exc:
                            record["video_file_error"]=type(exc).__name__
                        await browser.close()
        except Exception as exc:
            record["status"]="EXCEPTION"
            record["error_type"]=type(exc).__name__
            record["error_preview"]=str(exc)[:180]

        if result_webm is not None and result_webm.is_file():
            raw_size=result_webm.stat().st_size
            record["local_recording_bytes"]=raw_size
            try:
                fp=subprocess.run(["ffprobe","-v","error","-show_entries",
                    "format=duration:stream=codec_name,width,height","-of","json",str(result_webm)],
                    check=True,capture_output=True,text=True,timeout=20)
                record["video_integrity"]=json.loads(fp.stdout)
            except Exception as exc:
                record["integrity_error"]=type(exc).__name__
            if record["status"]=="LIVE_WINDOW_CAPTURED" and raw_size>500_000 and "video_integrity" in record:
                record["encrypted_count"]=encrypt_recordings(
                    [result_webm],public_key,encrypted_dir)
            else:
                record["status"]="RECORDING_NOT_PROVEN"
        record["whole_four_laps_visual_confirmation"]="NOT_VERIFIED"
        report_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    return record

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--report",type=Path,required=True)
    ap.add_argument("--encrypted-dir",type=Path,required=True)
    ap.add_argument("--public-key",type=Path,required=True)
    args=ap.parse_args()
    r=asyncio.run(record(args.report,args.encrypted_dir,args.public_key))
    print(json.dumps({k:r.get(k) for k in (
        "race_id","status","first_capture_clock","last_capture_clock",
        "sample_count","technical_coverage","encrypted_count",
        "whole_four_laps_visual_confirmation","error_type")},
        ensure_ascii=False))
    if r["status"]!="LIVE_WINDOW_CAPTURED" or r.get("encrypted_count")!=1:
        raise SystemExit(2)

if __name__=="__main__":main()
