#!/usr/bin/env python3
"""Time-bounded WINTICKET live page screencast, with strict 4-lap evidence gates.

NO replay download, no media-stream extraction, no login/DRM bypass, no betting.
Live capture requires an independently admitted source-rights permission
through an owner-controlled runtime flag. Tests use invented canvas motion.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

from playwright.async_api import async_playwright
from race_ai.keirin_video_lap_gate import (
    SOURCE, validate_plan, coverage_gate, lap_visual_gate, VideoGateError
)

SCHEMA="RACE_AI_KEIRIN_LIVE_FULL_WINDOW_CAPTURE_V1"
MAX_READ=64_000
FIXTURE_PAGE="""
<html lang="ja"><head><title>SYNTHETIC FOUR LAP TEST: NOT REAL</title></head>
<body><canvas id="scene" width="640" height="360"></canvas>
<video id="synthetic" width="640" height="360" autoplay muted playsinline></video>
<script>
const canvas=document.getElementById("scene"),c=canvas.getContext("2d");
const v=document.getElementById("synthetic"); v.srcObject=canvas.captureStream(15);
let beginning=performance.now();
function frame(now){
 const t=(now-beginning)/1000;
 c.fillStyle="#123"; c.fillRect(0,0,640,360);
 c.fillStyle="white"; c.font="bold 50px sans-serif";
 c.fillText("SYNTHETIC ONLY",40,80);
 c.fillText("LAP "+(4-Math.min(3,Math.floor(t/2))),180,180);
 c.fillStyle="#9fe"; c.fillRect(20+Math.floor(t*23)%580,250,40,35);
 requestAnimationFrame(frame);
} requestAnimationFrame(frame);
v.play().catch(()=>{});
</script></body></html>"""


def now_utc():
    return datetime.now(timezone.utc)


def utc_str(d):
    return d.astimezone(timezone.utc).isoformat()


def safe_file_json(path: Path):
    if not path.is_file() or path.is_symlink() or not 0<path.stat().st_size<=MAX_READ:
        raise ValueError("INVALID_CAPTURE_MANIFEST")
    return json.loads(path.read_text(encoding="utf-8"))


def inspect_webm(path: Path):
    if not path.is_file() or path.stat().st_size<40_000:
        return {"valid":False,"reason":"MISSING_OR_TINY_WEBM"}
    try:
        raw=subprocess.run([
            "ffprobe","-v","error","-show_entries",
            "format=duration,size:stream=codec_name,width,height",
            "-of","json",str(path)
        ],check=True,capture_output=True,text=True,timeout=20).stdout
        info=json.loads(raw)
        streams=info.get("streams",[])
        duration=float(info.get("format",{}).get("duration",0))
        valid=(duration>=4 and any(
            int(s.get("width",0))>=320 and int(s.get("height",0))>=180
            for s in streams))
        return {"valid":bool(valid),"duration_seconds":round(duration,3),
                "size_bytes":path.stat().st_size,
                "sha256":sha256(path.read_bytes()).hexdigest(),
                "streams":streams[:2]}
    except Exception as exc:
        return {"valid":False,"reason":type(exc).__name__}


def seal_video(path:Path,output:Path,public_key:Path,race_id:str):
    """AES-GCM content encrypted, RSA-OAEP wrapped one-time key.

    An approved production key is required separately. A test public key in
    the repo cannot be assumed approved for private production storage.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    rsa=serialization.load_pem_public_key(public_key.read_bytes())
    raw=path.read_bytes()
    key=secrets.token_bytes(32)
    nonce=secrets.token_bytes(12)
    aad=("RACE_AI_CAPTURE_V1:"+race_id).encode("ascii")
    ciphertext=AESGCM(key).encrypt(nonce,raw,aad)
    wrapped=rsa.encrypt(key,padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),label=None))
    output.mkdir(parents=True,exist_ok=True)
    (output/"screen.webm.aesgcm").write_bytes(ciphertext)
    receipt={"race_id":race_id,"algorithm":"AES-256-GCM+RSA-OAEP-SHA256",
             "key_wrapped_b64":__import__("base64").b64encode(wrapped).decode(),
             "nonce_b64":__import__("base64").b64encode(nonce).decode(),
             "aad":aad.decode(),"ciphertext_sha256":sha256(ciphertext).hexdigest(),
             "plaintext_sha256":sha256(raw).hexdigest()}
    (output/"receipt.json").write_text(json.dumps(receipt,indent=2))
    return {"encrypted":True,"cipher_sha256":receipt["ciphertext_sha256"]}


async def player_state(page):
    return await page.evaluate("""() => {
      const v=document.querySelector('video');
      if(!v)return null;
      return {media_time:Number(v.currentTime||0),
        ready_state:v.readyState,paused:v.paused,
        video_width:v.videoWidth,video_height:v.videoHeight,
        media_error:v.error?v.error.code:null};
    }""")


async def prepare_live(page, *, fixture):
    if fixture:
        await page.set_content(FIXTURE_PAGE,wait_until="domcontentloaded")
        await page.wait_for_timeout(550)
        return {"status":"SYNTHETIC_VIDEO","source":"SYNTHETIC_ONLY"}
    res=await page.goto(SOURCE,wait_until="domcontentloaded",timeout=25_000)
    if res is None or res.status!=200:
        return {"status":"LIVE_PAGE_UNAVAILABLE","http_status":res.status if res else None}
    title=await page.title()
    if "松山" not in title:
        return {"status":"VENUE_IDENTITY_NOT_FOUND"}
    try:
        await page.wait_for_function("document.querySelector('video')!==null",timeout=15_000)
        await page.evaluate("""() => {
            const v=document.querySelector('video');
            v.muted=true;
            v.play().catch(()=>{});
        }""")
    except Exception:
        return {"status":"LIVE_PLAYER_NOT_READY"}
    return {"status":"PLAYER_REQUESTED","http_status":res.status,
            "source":SOURCE,"venue":"matsuyama"}


async def monitor(page, seconds:float, *, interval:float=2.0):
    """One bounded observation per interval; never infer lap count from HLS time."""
    start=asyncio.get_running_loop().time()
    samples=[]
    while asyncio.get_running_loop().time()-start<seconds:
        try:
            state=await player_state(page)
            if state is not None:
                state["observed_at"]=utc_str(now_utc())
                samples.append(state)
        except Exception:
            pass
        await asyncio.sleep(interval)
    return samples


async def run_live(plan,report_path:Path, *, fixture:bool, test_seconds:int,
                   sealed_dir:Path|None=None,public_key:Path|None=None):
    result={"schema":SCHEMA,"race_id":plan.get("race_id"),
            "source":SOURCE if not fixture else "SYNTHETIC_ONLY",
            "synthetic_only":bool(fixture),
            "raw_footage_public":False,"media_stream_extracted":False,
            "auth_bypassed":False,
            "model_weights_changed":False,"status":"NOT_STARTED",
            "recording_rights_confirmed_by_module":False,
            "four_laps_verified":False}
    report_path.parent.mkdir(parents=True,exist_ok=True)
    try:
        expected=validate_plan(plan,synthetic=fixture)
    except VideoGateError as exc:
        result["status"]=str(exc)
        report_path.write_text(json.dumps(result,indent=2))
        return result
    if not fixture and os.environ.get("RACE_AI_VIDEO_RECORDING_PERMISSION")!="APPROVED_BY_OWNER":
        result["status"]="SOURCE_RECORDING_RIGHTS_GATE_BLOCKED"
        report_path.write_text(json.dumps(result,indent=2))
        return result

    if fixture:
        # Synthetic test is never used as an authorization or scheduling proof.
        runtime_len=test_seconds
    else:
        current=now_utc()
        # Run must already be prepared BEFORE the record-from time.
        # A late runner must never produce a false 'full race' claim.
        if current>expected["begin"]:
            result["status"]="MISSED_PRESTART_RECORDING_WINDOW"
            report_path.write_text(json.dumps(result,indent=2))
            return result
        if (expected["begin"]-current).total_seconds()>600:
            result["status"]="START_TOO_EARLY_FOR_GITHUB_RUNNER"
            report_path.write_text(json.dumps(result,indent=2))
            return result
        runtime_len=(expected["end"]-expected["begin"]).total_seconds()

    with tempfile.TemporaryDirectory(prefix="race-ai-live-tmp-") as temp:
        video_path=None
        try:
            async with async_playwright() as pw:
                browser=await pw.chromium.launch(
                    channel="chrome",headless=True,args=["--no-sandbox"])
                ctx=await browser.new_context(locale="ja-JP",
                    timezone_id="Asia/Tokyo",
                    viewport={"width":1280,"height":720},
                    record_video_dir=temp,record_video_size={"width":1280,"height":720})
                page=None
                try:
                    if not fixture:
                        waiting=(expected["begin"]-now_utc()).total_seconds()
                        # Begin page creation slightly early for player setup.
                        if waiting>25:
                            await asyncio.sleep(waiting-25)
                    result["recording_started_at"]=utc_str(now_utc())
                    page=await ctx.new_page()
                    init=await prepare_live(page,fixture=fixture)
                    result["player_setup"]=init
                    if init["status"] not in ("PLAYER_REQUESTED","SYNTHETIC_VIDEO"):
                        result["status"]="LIVE_PLAYER_SETUP_FAILED"
                    else:
                        if not fixture:
                            remaining=(expected["end"]-now_utc()).total_seconds()
                        else:
                            remaining=runtime_len
                        result["media_samples"]=await monitor(
                            page,max(2.0,remaining),interval=1.0 if fixture else 3.0)
                        result["status"]="CAPTURED_SCREEN_UNVERIFIED"
                finally:
                    await ctx.close()
                    if page and page.video:
                        try:
                            video_path=Path(await page.video.path())
                        except Exception:pass
                    await browser.close()
        except Exception as exc:
            result["status"]="CAPTURE_RUNTIME_ERROR"
            result["error_type"]=type(exc).__name__
        result["recording_ended_at"]=utc_str(now_utc())
        if video_path is not None:
            result["recording_file"]=inspect_webm(video_path)
        if fixture:
            result["status"]="SYNTHETIC_BROWSER_RECORDING_TEST"
            result["synthetic_capture_ok"]=bool(
                result.get("recording_file",{}).get("valid") and
                len(result.get("media_samples",[]))>=4)
        elif result.get("recording_file",{}).get("valid"):
            runtime={"recording_started_at":result["recording_started_at"],
                "recording_ended_at":result["recording_ended_at"],
                "media_samples":result.get("media_samples",[]),
                "video_container_ok":result["recording_file"]["valid"]}
            result["capture_gate"]=coverage_gate(plan,runtime)
            if result["capture_gate"].get("capture_window_complete") is True:
                result["status"]="SCREEN_CAPTURE_TIME_WINDOW_COMPLETE_VISUAL_PENDING"
                if sealed_dir and public_key and video_path:
                    result["sealed_capture"]=seal_video(
                        video_path,sealed_dir,public_key,result["race_id"])
            else:
                result["status"]="CAPTURE_INCOMPLETE_"+result["capture_gate"]["status"]
        # No real visual analysis is claimed, regardless of screenshot duration.
        result["four_lap_evidence_gate"]=lap_visual_gate(
            result.get("capture_gate",{}),None,synthetic=fixture)
        # Avoid logging timestamped player samples of unrelated programming;
        # race provenance is kept locally and not uploaded as raw footage.
        report_path.write_text(json.dumps(result,indent=2,ensure_ascii=False))
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    ap.add_argument("--synthetic-test-only",action="store_true")
    ap.add_argument("--test-seconds",type=int,default=9)
    ap.add_argument("--encrypted-dir",type=Path)
    ap.add_argument("--owner-public-key",type=Path)
    args=ap.parse_args()
    if not 6<=args.test_seconds<=30:
        ap.error("test-seconds must be 6..30")
    if not args.synthetic_test_only and not (
        args.encrypted_dir and args.owner_public_key
    ):
        ap.error("Live recording requires owner-approved encryption destination")
    plan=safe_file_json(args.plan)
    result=asyncio.run(run_live(
        plan,args.report,fixture=args.synthetic_test_only,
        test_seconds=args.test_seconds,sealed_dir=args.encrypted_dir,
        public_key=args.owner_public_key))
    print(json.dumps({
        "race_id":result.get("race_id"),"status":result["status"],
        "synthetic_only":result["synthetic_only"],
        "recording_seconds":result.get("recording_file",{}).get("duration_seconds"),
        "four_laps_verified":result["four_laps_verified"],
        "rights_admitted":result["recording_rights_confirmed_by_module"]
    },ensure_ascii=False))
    if args.synthetic_test_only:
        if result.get("synthetic_capture_ok") is not True: raise SystemExit(2)
    elif result.get("sealed_capture",{}).get("encrypted") is not True:
        raise SystemExit(2)

if __name__=="__main__":
    main()
