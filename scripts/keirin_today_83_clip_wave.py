#!/usr/bin/env python3
"""Record eligible 2026-11-09 WINTICKET result-page clips, race by race.

Use only displayed browser playback after a public start+5min safety delay.
Do NOT infer real video availability or independent permissions merely from
the schedule. A failed race is an observable failure, not a fabricated clip.
Encrypted ciphertext only is eligible for upload, and historical video labels
are not automatically training truth or real predictive accuracy.

This worker is deliberately bounded to a finite 2026-11-09 manifest.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from playwright.async_api import async_playwright

from race_ai.keirin_20261109_83_manifest import (
    SCHEMA as DAY_MANIFEST_SCHEMA, JST, manifest, digest,
)
from scripts.keirin_winticket_historical_batch_capture import (
    capture_one, admission_manifest,
)

REPORT_SCHEMA="RACE_AI_20261109_WINTICKET_CLIP_WAVE_V1"

def eligible_for_wave(items, *, now, window_hours=2.2, max_attempts=40):
    """Deterministic time window with 12-minute overlap for late publication.

    The real runner ALWAYS calls datetime.now(JST), not a caller's imagined
    date. This helper takes an explicit clock solely for unit tests.
    """
    if now.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    if not 1<=window_hours<=3.0:
        raise ValueError("WINDOW_TOO_WIDE")
    if not 1<=max_attempts<=40:
        raise ValueError("UNBOUNDED_CAPTURE_COUNT")
    current=now.astimezone(JST)
    earliest=current-timedelta(hours=window_hours)
    due=[]
    for item in items:
        t=datetime.fromisoformat(item["minimum_clip_attempt_jst"])
        if earliest<t<=current and item["date"]=="2026年11月9日":
            due.append(item)
    due.sort(key=lambda x:(x["scheduled_start_jst"],x["race_id"]))
    if len(due)>max_attempts:
        # Do not silently drop races when more start than the wave can handle.
        raise ValueError(f"WAVE_CAPACITY_INSUFFICIENT:{len(due)}")
    return due

async def record_batch(args):
    now=datetime.now(JST)
    data=manifest()
    if data["schema"]!=DAY_MANIFEST_SCHEMA or len(data["races"])!=83:
        raise ValueError("TODAY_OFFICIAL_RACE_MANIFEST_CHANGED")
    due=eligible_for_wave(
        data["races"],now=now,window_hours=args.window_hours,
        max_attempts=args.max_attempts)
    report={
      "schema":REPORT_SCHEMA,"manifest_sha256":digest(data),
      "date_jst":"2026-11-09","captured_as_of_jst":now.isoformat(),
      "scheduled_races":83,"eligible_this_wave":len(due),
      "attempted_races":0,"encrypted_capture_count":0,
      "race_rows":[],"owner_reported_winticket_usage_ok":True,
      "permission_exact_scope_independently_attested":False,
      "raw_footage_exported":False,
      "verified_rider_tactics_added":0,
      "prediction_model_weights_changed":False,
      "official_pre_cutoff_forecasts_modified":False,
      "improved_top8_demonstrated":False,
    }
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.encrypted_dir.mkdir(parents=True,exist_ok=True)
    if args.plan_only:
        report["race_rows"]=[{
            "race_id":x["race_id"],"scheduled_start_jst":x["scheduled_start_jst"],
            "url":x["url"],"cohort":x["cohort"],
            "status":"SCHEDULE_ONLY_NO_VIDEO_OPENED"} for x in due]
        report["stage"]="PLAN_ONLY"
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({"eligible_this_wave":len(due),
            "race_ids":[x["race_id"] for x in due],"stage":"PLAN_ONLY"}))
        return report

    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=load_pem_public_key(args.public_key.read_bytes())
    if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=3072:
        raise ValueError("OWNER_RSA_KEY_NOT_VALID")
    if not due:
        report["stage"]="NONE_YET_COMPLETED_IN_SELECTED_WINDOW"
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({"stage":report["stage"],"eligible_this_wave":0}))
        return report

    async with async_playwright() as pw:
        browser=await pw.chromium.launch(
            headless=True,channel="chrome",
            args=["--no-sandbox","--autoplay-policy=no-user-gesture-required"])
        try:
            for item in due:
                # A browser player is only recorded after the official planned
                # race start. Unexpected date/title/redirect => fail closed.
                source={
                    "race_id":item["race_id"],
                    "url":item["url"],
                    "venue":item["venue"],
                    "date":item["date"],
                    "race_no":item["race_no"],
                    "cohort":item["cohort"],
                }
                try:
                    outcome=await capture_one(
                        browser,source,args.encrypted_dir,args.public_key)
                except Exception as exc:
                    outcome=admission_manifest(source)
                    outcome["technical_status"]="CAPTURE_ATTEMPT_FAILED"
                    outcome["error_type"]=type(exc).__name__
                report["attempted_races"]+=1
                report["encrypted_capture_count"]+=int(
                    outcome.get("technical_status")=="ENCRYPTED_COMPLETE_PLAYER")
                report["race_rows"].append({
                    "race_id":item["race_id"],
                    "venue":item["venue"],
                    "scheduled_start_jst":item["scheduled_start_jst"],
                    "status":outcome.get("technical_status"),
                    "http_status":outcome.get("http_status"),
                    "recording_sha256":outcome.get("screen_sha256"),
                    "player_duration_s":outcome.get("player_duration_s"),
                    "player_ended":outcome.get("player_ended"),
                    "cohort":item["cohort"],
                    "failure":outcome.get("error_type") or outcome.get(
                        "failure_before_integrity_check"),
                    "learned_labels":0,
                })
                report["stage"]="ENCRYPTED_CLIP_COLLECTION_IN_PROGRESS"
                args.report.write_text(json.dumps(
                    report,ensure_ascii=False,indent=2))
                print(json.dumps({
                    "race_id":item["race_id"],
                    "status":outcome.get("technical_status"),
                    "encrypted_total_this_wave":report["encrypted_capture_count"]
                },ensure_ascii=False),flush=True)
                await asyncio.sleep(3)
        finally:
            await browser.close()
    report["stage"]="WAVE_COMPLETED"
    report["completed_at_jst"]=datetime.now(JST).isoformat()
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--encrypted-dir",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--public-key",type=Path,required=True)
    parser.add_argument("--window-hours",type=float,default=2.2)
    parser.add_argument("--max-attempts",type=int,default=40)
    parser.add_argument("--plan-only",action="store_true")
    args=parser.parse_args(argv)
    result=asyncio.run(record_batch(args))
    print(json.dumps({
       "attempted_races":result["attempted_races"],
       "encrypted_capture_count":result["encrypted_capture_count"],
       "source_races_today":83,"stage":result["stage"],
       "actual_training_events_approved":0,
       "full_83_coverage_verified":False,
    },ensure_ascii=False))
if __name__=="__main__":
    main()
