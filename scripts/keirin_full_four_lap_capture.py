#!/usr/bin/env python3
"""Matsuyama 2026-11-08 1R *uncut-broadcast* screen recording attempt.

The source is the operator's same-date YouTube broadcast, NOT the 92-second
Kdreams digest. Use ordinary YouTube playback only; no stream extraction, login
bypass, DRM circumvention, synthetic-success substitution, or background tasks.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from playwright.async_api import async_playwright
from scripts.keirin_replay_probe import encrypt_recordings, video_metadata

RACE_ID="20261108-matsuyama-01"
VIDEO_ID="BhwmwNby6Ow"
CHANNEL_ID="UCX3xb9FwC7jL_ZnVmoyzgDg"
VIDEO_URL="https://www.youtube.com/watch?v="+VIDEO_ID
WINDOW_BEGIN=datetime.fromisoformat("2026-11-08T20:37:30+09:00")
WINDOW_END=datetime.fromisoformat("2026-11-08T20:44:30+09:00")

def offset_for(start_timestamp: str, target: datetime) -> float:
    if target.utcoffset() is None:
        raise ValueError("TARGET_TIMEZONE_REQUIRED")
    started=datetime.fromisoformat(start_timestamp.replace("Z","+00:00"))
    if started.utcoffset() is None:
        raise ValueError("BROADCAST_START_TIMEZONE_REQUIRED")
    delta=(target-started).total_seconds()
    if not 0<=delta<=18*3600:
        raise ValueError("RACE_WINDOW_OUTSIDE_BROADCAST")
    return delta

def seek_available(start: float, end: float, ranges: list) -> bool:
    return (end>start>=0 and any(
        isinstance(r,list) and len(r)==2 and r[0]<=start and end<=r[1]
        for r in ranges))

async def player(page) -> dict:
    return await page.evaluate("""() => {
      const r=window.ytInitialPlayerResponse||{};
      const d=r.videoDetails||{};
      const live=r.microformat?.playerMicroformatRenderer?.liveBroadcastDetails||{};
      const v=document.querySelector('video');
      const ranges=[];
      if (v?.seekable) for(let i=0;i<v.seekable.length;i++)
        ranges.push([v.seekable.start(i),v.seekable.end(i)]);
      return {status:r.playabilityStatus?.status||'UNKNOWN',
        title:d.title||null,video_id:d.videoId||null,
        channel_id:d.channelId||null,live_start:live.startTimestamp||null,
        element:v?{current:v.currentTime,duration:Number.isFinite(v.duration)?v.duration:null,
                    width:v.videoWidth,height:v.videoHeight,ready:v.readyState,
                    paused:v.paused,ended:v.ended,ranges:ranges}:null};
    }""")

async def record(*, report: Path, encrypted_dir: Path|None, public_key: Path|None,
                 capture: bool, max_seconds: int=520):
    result={"schema":"RACE_AI_MATSUYAMA_1R_FOUR_LAP_BROADCAST_CAPTURE_V1",
      "race_id":RACE_ID,"source":VIDEO_URL,
      "recording_mode":"BROWSER_RENDERED_VIDEO_ONLY",
      "digest_source_used":False,"uncut_four_laps_verified":False,
      "finish_and_lap_count_verified":False,
      "rider_tracking_verified":False,"model_weights_changed":False,
      "authentication_bypassed":False,"source_stream_downloaded":False,
      "status":"NOT_STARTED","at_utc":datetime.now(timezone.utc).isoformat()}
    report.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="race-ai-four-laps-") as tmp:
        video_file=None
        try:
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(
                    headless=True, channel="chrome",
                    args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
                ctx=await browser.new_context(
                    viewport={"width":1280,"height":720},
                    record_video_dir=tmp,
                    record_video_size={"width":1280,"height":720},
                    locale="ja-JP",timezone_id="Asia/Tokyo")
                page=await ctx.new_page()
                try:
                    response=await page.goto(VIDEO_URL,
                        wait_until="domcontentloaded",timeout=30000)
                    await page.wait_for_timeout(3500)
                    result["http_status"]=response.status if response else None
                    info=await player(page)
                    result["player_status"]=info["status"]
                    result["video_title"]=(info["title"] or "")[:130]
                    result["player_ready_state"]=(
                        info["element"]["ready"] if info["element"] else None)
                    if info["status"]!="OK":
                        result["status"]="SOURCE_NOT_PLAYABLE_"+info["status"]
                    elif info["video_id"]!=VIDEO_ID or info["channel_id"]!=CHANNEL_ID:
                        result["status"]="RACE_SOURCE_IDENTITY_MISMATCH"
                    elif not info["live_start"] or not info["element"]:
                        result["status"]="BROADCAST_TIME_OR_VIDEO_UNAVAILABLE"
                    else:
                        begin=offset_for(info["live_start"],WINDOW_BEGIN)
                        end=offset_for(info["live_start"],WINDOW_END)
                        result["target_broadcast_offsets"]=[round(begin,2),round(end,2)]
                        result["recording_window_jst"]=[WINDOW_BEGIN.isoformat(),WINDOW_END.isoformat()]
                        if not seek_available(begin,end,info["element"]["ranges"]):
                            result["status"]="RACE_WINDOW_NOT_IN_DVR"
                        elif not capture:
                            result["status"]="PLAYABLE_SOURCE_AND_DVR_WINDOW_VERIFIED"
                        else:
                            await page.evaluate("""t => {
                              let v=document.querySelector('video');v.currentTime=t;
                              v.play().catch(()=>{}); }""",begin)
                            await page.wait_for_timeout(2500)
                            after=await player(page)
                            actual=after["element"]["current"] if after["element"] else -1
                            result["seeked_video_time"]=round(actual,3)
                            if abs(actual-begin)>5:
                                result["status"]="DVR_SEEK_FAILED"
                            else:
                                progress=[]
                                loop=asyncio.get_running_loop()
                                deadline=loop.time()+max_seconds
                                last=actual
                                stalled=0
                                while loop.time()<deadline:
                                    p=await player(page)
                                    element=p["element"]
                                    if not element or p["status"]!="OK":
                                        result["status"]="VIDEO_PLAYER_LOST"
                                        break
                                    current=element["current"]
                                    progress.append(round(current,1))
                                    if current>=end-0.6:
                                        result["status"]="TIMED_BROADCAST_WINDOW_RECORDED"
                                        break
                                    if current<last-1:
                                        result["status"]="SEEK_BACKWARDS_DURING_RECORDING"
                                        break
                                    stalled=stalled+1 if current<=last+0.04 else 0
                                    if stalled>=15:
                                        result["status"]="VIDEO_STALLED"
                                        break
                                    last=current
                                    await asyncio.sleep(1.0)
                                else:
                                    result["status"]="RECORDING_TIMEOUT"
                                result["recorded_player_samples"]=len(progress)
                                result["last_player_time"]=progress[-1] if progress else None
                finally:
                    await ctx.close()
                    try:
                        if page.video: video_file=Path(await page.video.path())
                    except Exception:
                        pass
                    await browser.close()
        except Exception as exc:
            result["status"]="CAPTURE_ERROR"
            result["error_type"]=type(exc).__name__
        if video_file and video_file.is_file() and result["status"]=="TIMED_BROADCAST_WINDOW_RECORDED":
            result["recording"]=video_metadata(video_file)
            if encrypted_dir is not None and public_key is not None:
                result["encrypted_files"]=encrypt_recordings(
                    [video_file],public_key,encrypted_dir)
            else:
                result["status"]="ENCRYPTION_DESTINATION_REQUIRED"
        report.write_text(json.dumps(result,indent=2,ensure_ascii=False),
                          encoding="utf-8")
    return result

def main():
    arg=argparse.ArgumentParser()
    arg.add_argument("--report",type=Path,required=True)
    arg.add_argument("--capture",action="store_true")
    arg.add_argument("--encrypted-dir",type=Path)
    arg.add_argument("--public-key",type=Path)
    arg.add_argument("--max-seconds",type=int,default=520)
    a=arg.parse_args()
    if a.capture and (a.encrypted_dir is None or a.public_key is None):
        arg.error("Capture requires encryption destination and public key")
    if not 60<=a.max_seconds<=600:
        arg.error("max-seconds must be 60..600")
    r=asyncio.run(record(
      report=a.report,encrypted_dir=a.encrypted_dir,public_key=a.public_key,
      capture=a.capture,max_seconds=a.max_seconds))
    print(json.dumps({k:r.get(k) for k in
      ("race_id","source","status","http_status","player_status",
       "video_title","target_broadcast_offsets","recording_window_jst",
       "encrypted_files","uncut_four_laps_verified")},
      ensure_ascii=False))
    if a.capture:
        if r["status"]!="TIMED_BROADCAST_WINDOW_RECORDED":
            raise SystemExit(2)
    elif r["status"]!="PLAYABLE_SOURCE_AND_DVR_WINDOW_VERIFIED":
        raise SystemExit(2)

if __name__=="__main__":
    main()
