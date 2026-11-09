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
    temporary_races=set()
    if args.temporary_artifact_receipts is not None:
        receipt=json.loads(args.temporary_artifact_receipts.read_text(encoding="utf-8"))
        if (receipt.get("schema")!="RACE_AI_KEIRIN_GH_TEMP_CIPHERTEXT_RECEIPTS_V1"
           or receipt.get("date_jst")!=today or
           receipt.get("github_action_artifacts_only_not_durable_private_storage") is not True):
            raise ValueError("INVALID_TODAY_TEMPORARY_ARTIFACT_RECEIPTS")
        temporary_races=set(receipt["temporary_capture_race_ids"])
        if len(temporary_races)!=len(receipt["temporary_capture_race_ids"]):
            raise ValueError("DUPLICATE_TEMPORARY_RACE_RECEIPT")
    if args.previous_day_manifest is not None:
        from race_ai.keirin_daily_night_backfill import select_night_backfill
        recovery=select_night_backfill(
            manifest,now=now,progress=state,max_races=args.max_races,
            temporary_captured_race_ids=temporary_races)
        batch={
            "selected":recovery["attempt_candidates"],
            "races_visible_on_result_index":sum(
                x["listed_on_raceresult_index"] for x in manifest["races"]),
            "durably_archived_with_attested_readback":recovery["private_readback_confirmed"],
            "not_selected_due_to_wave_cap":recovery["capped_unprocessed_count"],
        }
    else:
        batch=select(manifest,progress=state,max_races=args.max_races,
                     temporary_captured_race_ids=temporary_races)
    result={
        "schema":REPORT_SCHEMA,"date_jst":today,
        "as_of_jst":now.isoformat(),
        "dynamic_manifest_sha256":manifest["manifest_sha256"],
        "discovered_venue_count":manifest["discovered_venue_count"],
        "discovered_race_count":manifest["discovered_race_count"],
        "result_page_links":batch["races_visible_on_result_index"],
        "previously_retained_with_verified_readback":
            batch["durably_archived_with_attested_readback"],
        "previously_captured_only_in_unexpired_github_artifacts":
            len(temporary_races),
        "temporary_github_artifact_not_private_durable_storage":True,
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
    private_feature_docs=[]
    def ephemeral_research_hook(video_path,source,technical):
        if args.sealed_research_dir is None:
            return
        from race_ai.keirin_daily_video_research import read_private_video
        doc=read_private_video(
            video_path,race_id=source["race_id"],cohort=source["cohort"])
        if (doc["browser_video_sha256"]!=technical.get("sha256")
            or doc["cohort"]!=source["cohort"]):
            raise ValueError("PRIVATE_FEATURE_PROVENANCE_MISMATCH")
        private_feature_docs.append(doc)

    async with async_playwright() as pw:
        browser=await pw.chromium.launch(
            headless=True,channel="chrome",args=[
              "--no-sandbox","--autoplay-policy=no-user-gesture-required"])
        try:
            for source in batch["selected"]:
                try:
                    entry=await capture_one(
                        browser,source,args.encrypted_dir,args.owner_public_key,
                        on_verified_plaintext=ephemeral_research_hook
                            if args.sealed_research_dir else None)
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
                    "ephemeral_visual_features_extracted":
                        entry.get("private_feature_extraction_status")
                        =="SUCCEEDED_EPHEMERAL",
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
    # Every verified browser frame is converted into an owner-only RSA/AES
    # ciphertext envelope before this ephemeral runner exits. No raw feature
    # matrices or frames are ever uploaded to a public Actions artifact.
    if args.sealed_research_dir is not None and private_feature_docs:
        from race_ai.keirin_daily_video_research import (
            fit_private_representation,make_review_queue)
        from race_ai.keirin_private_sealed_payload import seal_json
        studies={
            "schema":"RACE_AI_KEIRIN_CI_DAILY_PRIVATE_RESEARCH_BATCH_V1",
            "date_jst":today,
            "source_races":[{"race_id":x["race_id"],
                "source_sha256":x["browser_video_sha256"],
                "cohort":x["cohort"],
                "frames":len(x["frames"])} for x in private_feature_docs],
            "feature_documents":private_feature_docs,
            "review_candidates":make_review_queue(private_feature_docs),
            "scene_model":fit_private_representation(
               private_feature_docs,min_train_races=2,min_holdout_races=1),
            "actual_rider_tactical_labels_verified":0,
            "official_prediction_model_changed":False,
        }
        sealed=seal_json(studies,args.owner_public_key.read_bytes(),
            aad="RACE_AI_PRIVATE_KEIRIN:"+today+":SCENE_RESEARCH_V1")
        args.sealed_research_dir.mkdir(parents=True,exist_ok=True)
        envelope=args.sealed_research_dir/("keirin_"+today+"_sealed_research.json")
        envelope.write_text(json.dumps(sealed,ensure_ascii=False))
        result["encrypted_private_research_documents"]=1
        result["scene_feature_races"]=len(private_feature_docs)
        result["scene_feature_frame_count"]=sum(
            len(x["frames"]) for x in private_feature_docs)
        result["private_research_ciphertext_sha256"]=sealed["ciphertext_sha256"]
        result["scene_model_status"]=studies["scene_model"]["status"]
    else:
        result["encrypted_private_research_documents"]=0
        result["scene_feature_races"]=0
        result["scene_feature_frame_count"]=0
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
    ap.add_argument("--temporary-artifact-receipts",type=Path,
                    help="Reconstructed from unexpired Actions artifacts, NOT durable Library")
    ap.add_argument("--previous-day-manifest",type=Path,
                    help="Only in JST 00:00-07:59 recovery; use a precommitted prior-day manifest")
    ap.add_argument("--sealed-research-dir",type=Path,
                    help="Public RSA-encrypted frame/model research, never plaintext upload")
    ap.add_argument("--max-races",type=int,default=24)
    ap.add_argument("--plan-only",action="store_true")
    args=ap.parse_args()
    outcome=asyncio.run(run(args))
    print(json.dumps({
        "date":outcome["date_jst"],
        "discovered":outcome["discovered_race_count"],
        "attempted":outcome["attempted"],
        "encrypted":outcome["encrypted"],
        "sealed_research_documents":outcome.get("encrypted_private_research_documents",0),
        "scene_feature_frames":outcome.get("scene_feature_frame_count",0),
        "train_labels_independently_confirmed":0,
        "official_forecast_weights_updated":False,
    },ensure_ascii=False))
if __name__=="__main__":
    main()
