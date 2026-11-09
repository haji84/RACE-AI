#!/usr/bin/env python3
"""Daily nationwide WINTICKET video collector: current actual schedule, no 83 cap.

Run on an owner-controlled CI/GitHub research branch each hour during the
Japanese race day. First read *visible* racecard/results indexes in Chrome.
Then only record individual published result links through their visible
HTML5 player. Require browser natural playback end and verify screen WebM
bytes before RSA-wrapping a fresh AES-256-GCM content key.
No streaming endpoint extraction, no DRM/authentication bypass, no odds, no
pseudo-official forecasts, no result-derived scene model feature. A recorded
clip is a private research *candidate*, never automatically a training label.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path

from playwright.async_api import async_playwright

from race_ai.keirin_daily_public_catalog import JST
from race_ai.keirin_daily_clip_batch import select
from scripts.keirin_daily_public_discovery import discover
from scripts.keirin_winticket_historical_batch_capture import (
    capture_one,admission_manifest,
)

REPORT_SCHEMA="RACE_AI_KEIRIN_DAILY_RECORDINGS_ENCRYPTED_WAVE_V1"

async def run(args):
    now=datetime.now(JST)
    today=now.date().isoformat()
    if args.previous_day_manifest is not None:
        # Recovery is restricted to the genuine previous Japanese date,
        # within the midnight time window, never a user-chosen future date.
        manifest=json.loads(args.previous_day_manifest.read_text(encoding="utf-8"))
        today=manifest.get("date_jst")
    else:
        manifest=await discover(today)
    state=None
    if args.private_retention_receipts:
        path=args.private_retention_receipts
        if path.is_file():
            state=json.loads(path.read_text(encoding="utf-8"))
    if args.previous_day_manifest is not None:
        from race_ai.keirin_daily_night_backfill import select_night_backfill
        recovery=select_night_backfill(
            manifest,now=now,progress=state,max_races=args.max_races)
        batch={
            "selected":recovery["attempt_candidates"],
            "races_visible_on_result_index":sum(
                x["listed_on_raceresult_index"] for x in manifest["races"]),
            "durably_archived_with_attested_readback":recovery["private_readback_confirmed"],
            "not_selected_due_to_wave_cap":recovery["capped_unprocessed_count"],
        }
    else:
        batch=select(manifest,progress=state,max_races=args.max_races)
    result={
        "schema":REPORT_SCHEMA,"date_jst":today,
        "as_of_jst":now.isoformat(),
        "dynamic_manifest_sha256":manifest["manifest_sha256"],
        "discovered_venue_count":manifest["discovered_venue_count"],
        "discovered_race_count":manifest["discovered_race_count"],
        "result_page_links":batch["races_visible_on_result_index"],
        "previously_retained_with_verified_readback":
            batch["durably_archived_with_attested_readback"],
        "candidates_remaining_for_another_wave":
            batch["not_selected_due_to_wave_cap"],
        "available_candidates_this_wave":len(batch["selected"]),
        "attempted":0,"encrypted":0,"race_rows":[],
        "owner_reports_winticket_permission":True,
        "exact_permission_scope_independently_documented":False,
        "full_four_laps_asserted":False,
        "verified_training_video_events":0,
        "model_training_completed":False,
        "production_model_weights_changed":False,
        "future_race_prediction_rewritten":False,
        "source_has_no_direct_media_stream_fetch":True,
    }
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.encrypted_dir.mkdir(parents=True,exist_ok=True)
    args.manifest.parent.mkdir(parents=True,exist_ok=True)
    args.manifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    if args.plan_only or len(batch["selected"])==0:
        result["status"]="PLAN_ONLY" if args.plan_only else "NO_FINISHED_RESULT_LINK_READY"
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({**{
             k:result[k] for k in ("date_jst","discovered_race_count",
               "result_page_links","available_candidates_this_wave")
             },"status":result["status"]},ensure_ascii=False))
        return result

    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=load_pem_public_key(args.owner_public_key.read_bytes())
    if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=3072:
        raise ValueError("OWNER_RESEARCH_ENCRYPTION_KEY_INVALID")
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(
            headless=True,channel="chrome",args=[
              "--no-sandbox","--autoplay-policy=no-user-gesture-required"])
        try:
            for source in batch["selected"]:
                try:
                    entry=await capture_one(
                        browser,source,args.encrypted_dir,args.owner_public_key)
                except Exception as exc:
                    entry=admission_manifest(source)
                    entry["technical_status"]="CAPTURE_ERROR"
                    entry["error_type"]=type(exc).__name__
                ok=entry.get("technical_status")=="ENCRYPTED_COMPLETE_PLAYER"
                result["attempted"]+=1
                result["encrypted"]+=int(ok)
                result["race_rows"].append({
                    "race_id":source["race_id"],
                    "cohort":source["cohort"],
                    "source_url":source["url"],
                    "status":entry.get("technical_status"),
                    "http_status":entry.get("http_status"),
                    "source_video_sha256":entry.get("screen_sha256"),
                    "video_player_duration_s":entry.get("player_duration_s"),
                    "playback_ended":entry.get("player_ended"),
                    "encrypted_file_count":entry.get("encrypted_capture_count",0),
                    "failure_type":entry.get("error_type") or
                                    entry.get("failure_before_integrity_check"),
                    "full_lap_claim":False,
                    "independently_reviewed_tactics":False,
                    "permitted_training_label":False,
                })
                result["status"]="PARTIAL_BATCH_PROGRESS"
                args.report.write_text(json.dumps(
                    result,ensure_ascii=False,indent=2))
                print(json.dumps({
                    "race_id":source["race_id"],
                    "status":entry.get("technical_status"),
                    "success_so_far":result["encrypted"]
                },ensure_ascii=False),flush=True)
                await asyncio.sleep(1)
        finally:
            await browser.close()
    result["status"]="WAVE_RECORDED_OR_FAILED_PER_RACE"
    result["ended_jst"]=datetime.now(JST).isoformat()
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--owner-public-key",required=True,type=Path)
    ap.add_argument("--encrypted-dir",required=True,type=Path)
    ap.add_argument("--report",required=True,type=Path)
    ap.add_argument("--manifest",required=True,type=Path)
    ap.add_argument("--private-retention-receipts",type=Path)
    ap.add_argument("--previous-day-manifest",type=Path,
                    help="Only in JST 00:00-07:59 recovery; use a precommitted prior-day manifest")
    ap.add_argument("--max-races",type=int,default=24)
    ap.add_argument("--plan-only",action="store_true")
    args=ap.parse_args()
    outcome=asyncio.run(run(args))
    print(json.dumps({
        "date":outcome["date_jst"],
        "discovered":outcome["discovered_race_count"],
        "attempted":outcome["attempted"],
        "encrypted":outcome["encrypted"],
        "train_labels_independently_confirmed":0,
        "official_forecast_weights_updated":False,
    },ensure_ascii=False))
if __name__=="__main__":
    main()
