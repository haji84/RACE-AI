#!/usr/bin/env python3
"""Collect a bounded list of WINTICKET past-race browser replays for private review.

This is *not* a scraper, a general-purpose downloader or a training-label
generator. Only four reviewed results-page URLs may be opened. Ordinary
visible replay controls are clicked in Chrome, screen playback is recorded
from near time zero through natural video end, then RSA-wrapped AES-256-GCM
ciphertext is saved. No user credentials, streaming URLs, or plaintext media
are committed or uploaded. Actual tactical labels are a later separate gate.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile

from playwright.async_api import async_playwright

from scripts.keirin_replay_probe import (
    watch_to_player_end, video_metadata, encrypt_recordings
)
from scripts.keirin_yahiko_1r_encrypted_replay_capture import recording_complete

SOURCES = (
    {"race_id":"20261030-yahiko-2R",
     "url":"https://www.winticket.jp/keirin/yahiko/raceresult/2026103021/1/2",
     "venue":"弥彦","date":"2026年10月30日","race_no":2,
     "cohort":"TRAIN_CANDIDATE"},
    {"race_id":"20261030-yahiko-3R",
     "url":"https://www.winticket.jp/keirin/yahiko/raceresult/2026103021/1/3",
     "venue":"弥彦","date":"2026年10月30日","race_no":3,
     "cohort":"TRAIN_CANDIDATE"},
    {"race_id":"20261030-yahiko-4R",
     "url":"https://www.winticket.jp/keirin/yahiko/raceresult/2026103021/1/4",
     "venue":"弥彦","date":"2026年10月30日","race_no":4,
     "cohort":"TRAIN_CANDIDATE"},
    {"race_id":"20261108-matsuyama-2R",
     "url":"https://www.winticket.jp/keirin/matsuyama/raceresult/2026110875/1/2",
     "venue":"松山","date":"2026年11月8日","race_no":2,
     "cohort":"UNSEEN_RESERVED"},
)
SCHEMA = "RACE_AI_HISTORICAL_CLIP_BATCH_SCREEN_CAPTURE_V1"

def identity_ok(source, url, title, code):
    """Return False for any redirect or mislabeled race before opening media."""
    return (
        code==200 and url==source["url"]
        and source["venue"] in title and source["date"] in title
        and re.search(rf"(?:^|[^0-9]){source['race_no']}(?:レース|R)(?![0-9])",
                      title) is not None
    )

def admission_manifest(source, *, technical=None):
    """An encrypted source clip is a CANDIDATE, never a training example."""
    return {
        "race_id":source["race_id"],
        "source_url":source["url"],
        "cohort":source["cohort"],
        "clip_kind":"PARTIAL_HIGHLIGHTS_CANDIDATE",
        "full_four_laps_confirmed":False,
        "independent_tactical_labels_confirmed":False,
        "winticket_permission_owner_reported":True,
        "permission_scope_independently_documented":False,
        "encrypted_video_verified":bool(technical),
        "training_eligible":False,
        "forecasts_modified":False,
    }

async def capture_one(browser, source, root, public_key):
    entry=admission_manifest(source)
    entry["technical_status"]="NOT_STARTED"
    with tempfile.TemporaryDirectory(prefix="race-ai-past-screen-") as temp_dir:
        context=await browser.new_context(
            locale="ja-JP",timezone_id="Asia/Tokyo",
            viewport={"width":1280,"height":720},
            record_video_dir=temp_dir,
            record_video_size={"width":1280,"height":720},
        )
        page=await context.new_page()
        selected=None
        first=last=None
        try:
            response=await page.goto(
                source["url"],wait_until="domcontentloaded",timeout=26000)
            entry["http_status"]=response.status if response else None
            await page.wait_for_timeout(2600)
            title=await page.title()
            entry["page_title"]=title[:160]
            if not identity_ok(source,page.url,title,entry["http_status"]):
                entry["technical_status"]="RACE_IDENTITY_MISMATCH"
            else:
                loc=page.locator("text=映像を観る").first
                if not (await loc.count() and await loc.is_visible()):
                    entry["technical_status"]="NO_VISIBLE_REPLAY_CONTROL"
                else:
                    await loc.click(timeout=6000)
                    await page.wait_for_timeout(700)
                    first,last,ended,checks,reason=await watch_to_player_end(
                        page,seconds=200,fixture=False)
                    entry["player_checks"]=checks
                    entry["player_end_reason"]=reason
                    entry["player_duration_s"]=(
                        last.get("duration") if last else None)
                    entry["player_ended"]=bool(last and last.get("ended"))
                    entry["technical_status"]=(
                        "PLAYER_FINISHED" if ended else "PLAYER_NOT_FINISHED")
        except Exception as exc:
            entry["technical_status"]="BROWSER_CAPTURE_ERROR"
            entry["error_type"]=type(exc).__name__
        finally:
            try:
                await context.close()
                if page.video:
                    selected=Path(await page.video.path())
            except Exception as exc:
                entry["screencast_error_type"]=type(exc).__name__
            pass

        if selected is not None and selected.is_file():
            tech=video_metadata(selected)
            entry["screen_format"]=tech.get("ffprobe")
            entry["screen_bytes"]=tech.get("bytes")
            entry["screen_sha256"]=tech.get("sha256")
            if (entry["technical_status"]=="PLAYER_FINISHED"
                    and recording_complete(first,last,tech)):
                encrypted_dir=root/source["race_id"]
                count=encrypt_recordings([selected],public_key,encrypted_dir,
                                         race_id=source["race_id"])
                entry["technical_status"]="ENCRYPTED_COMPLETE_PLAYER"
                entry["encrypted_capture_count"]=count
            else:
                entry["technical_status"]="INCOMPLETE_NOT_EXPORTED"
        return entry

async def execute(report, root, public_key):
    if not public_key.is_file():
        raise FileNotFoundError("PUBLIC_KEY_NOT_FOUND")
    report.parent.mkdir(parents=True,exist_ok=True)
    root.mkdir(parents=True,exist_ok=True)
    details={"schema":SCHEMA,
             "started_utc":datetime.now(timezone.utc).isoformat(),
             "captured_video_in_public_github":False,
             "user_reports_winticket_use_ok":True,
             "permission_scope_documented":False,
             "real_scene_training_completed":False,
             "source_limit":len(SOURCES),"races":[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(
            headless=True,channel="chrome",
            args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
        try:
            for source in SOURCES:
                result=await capture_one(browser,source,root,public_key)
                details["races"].append(result)
                # Do not log playback pixels, cookies or keys.
                print(json.dumps({k:result.get(k) for k in (
                    "race_id","cohort","technical_status","http_status",
                    "player_duration_s","player_ended",
                    "encrypted_capture_count","error_type")},
                    ensure_ascii=False),flush=True)
        finally:
            await browser.close()
    details["finished_utc"]=datetime.now(timezone.utc).isoformat()
    details["encrypted_races"]=sum(x["technical_status"]==
        "ENCRYPTED_COMPLETE_PLAYER" for x in details["races"])
    details["train_candidates"]=sum(
        x["technical_status"]=="ENCRYPTED_COMPLETE_PLAYER"
        and x["cohort"]=="TRAIN_CANDIDATE" for x in details["races"])
    details["unseen_reserved"]=sum(
        x["technical_status"]=="ENCRYPTED_COMPLETE_PLAYER"
        and x["cohort"]=="UNSEEN_RESERVED" for x in details["races"])
    report.write_text(json.dumps(details,ensure_ascii=False,indent=2))
    return details

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--report",required=True,type=Path)
    parser.add_argument("--encrypted-dir",required=True,type=Path)
    parser.add_argument("--public-key",required=True,type=Path)
    args=parser.parse_args()
    result=asyncio.run(execute(args.report,args.encrypted_dir,args.public_key))
    print(json.dumps({
        "recorded":result["encrypted_races"],
        "train_candidates":result["train_candidates"],
        "unseen_reserved":result["unseen_reserved"],
        "real_scene_training_completed":False},ensure_ascii=False))
    if result["encrypted_races"]<2:
        raise SystemExit("NEED_AT_LEAST_TWO_DISTINCT_REPLAY_CAPTURED")

if __name__=="__main__":
    main()
