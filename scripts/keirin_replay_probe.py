#!/usr/bin/env python3
"""Single-race browser capture probe. Does not download stream files.

A browser recording is only a technical observation, NOT proof that Matsuyama
1R is shown or proof of what caused the known 3-5-4 finish.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

from playwright.async_api import async_playwright

RACE_ID = "20261108-matsuyama-01"
SOURCE_URL = "https://keirin.kdreams.jp/matsuyama/racecard/75202611080100/"

def source_allowed(url: str, fixture: bool=False) -> bool:
    u = urlparse(url)
    if fixture:
        return u.scheme == "file" and u.path.endswith(".webm")
    return (u.scheme == "https" and u.hostname == "keirin.kdreams.jp"
            and u.path == "/matsuyama/racecard/75202611080100/")

def video_metadata(p: Path) -> dict:
    command = ["ffprobe","-v","error","-show_entries",
               "format=duration:stream=codec_name,width,height","-of","json",str(p)]
    try:
        obj = json.loads(subprocess.run(command,capture_output=True,text=True,
                                        check=True,timeout=20).stdout)
    except Exception:
        obj = {"error":"FFPROBE_FAILED"}
    return {"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
            "ffprobe":obj}

def motion_score(p: Path) -> dict:
    try:
        import cv2
        import numpy as np
        c = cv2.VideoCapture(str(p))
        if not c.isOpened():
            return {"status":"UNREADABLE"}
        try:
            count=int(c.get(cv2.CAP_PROP_FRAME_COUNT))
            fps=float(c.get(cv2.CAP_PROP_FPS) or 0)
            images=[]
            if fps > 0:
                for second in (2,4,6,8,10,12,14):
                    c.set(cv2.CAP_PROP_POS_FRAMES, min(count-1,int(second*fps)))
                    ok,frame=c.read()
                    if ok:
                        images.append(cv2.cvtColor(cv2.resize(frame,(160,90)),cv2.COLOR_BGR2GRAY))
            if len(images)<2:
                return {"status":"TOO_FEW_SAMPLES","frames":count}
            diffs=[float(np.mean(np.abs(a.astype("float32")-b.astype("float32"))))
                   for a,b in zip(images,images[1:])]
            return {"status":"MOTION_IS_NOT_RACE_PROOF","frames":count,
                    "mean_frame_diff":round(sum(diffs)/len(diffs),3)}
        finally:
            c.release()
    except Exception as exc:
        return {"status":"MOTION_CHECK_FAILED","exception_type":type(exc).__name__}

async def media_state(page) -> list:
    output=[]
    for frame in page.frames:
        try:
            state = await frame.evaluate("""() => Array.from(document.querySelectorAll('video'))
              .slice(0,8).map(v=>({currentTime:v.currentTime, paused:v.paused,
                readyState:v.readyState,networkState:v.networkState,
                mediaError:v.error ? v.error.code : null,sourceSet:!!v.currentSrc,
                duration:Number.isFinite(v.duration)?v.duration:null,ended:v.ended,
                width:v.videoWidth,height:v.videoHeight}))""")
            output.extend(state)
        except Exception:
            pass
    return output


def full_player_video_seen(start: dict, finish: dict, fixture: bool=False) -> bool:
    """Require terminal state, playback from near the beginning and no media errors.

    This does NOT establish that the player carries the entire unedited race.
    """
    if not isinstance(start, dict) or not isinstance(finish, dict):
        return False
    duration = finish.get("duration")
    if not isinstance(duration, (int, float)) or duration < (7 if fixture else 40):
        return False
    if start.get("mediaError") is not None or finish.get("mediaError") is not None:
        return False
    if start.get("currentTime") is None or finish.get("currentTime") is None:
        return False
    if start["currentTime"] > min(5.0, 0.08 * duration):
        return False
    if finish["currentTime"] < duration - max(0.65, 0.015 * duration):
        return False
    if finish["currentTime"] <= start["currentTime"] + 3:
        return False
    if not finish.get("ended"):
        return False
    if not finish.get("sourceSet"):
        return False
    if finish.get("width", 0) < 320 or finish.get("height", 0) < 180:
        # Synthetic-only fixtures are deliberately small.
        if not fixture:
            return False
    return True


async def watch_to_player_end(player, seconds: int, fixture: bool):
    """Observe the actual HTML5 player to completion; never rely on a fixed sleep.

    The browser screen recorder is active throughout. Timeout/loop/media failure
    must be reported as INCOMPLETE, not a successful capture.
    """
    import time
    start_at=time.monotonic()
    first=None
    last=None
    observations=0
    end_proven=False
    while time.monotonic()-start_at < seconds:
        states=await media_state(player)
        for state in states:
            if state.get("mediaError") is not None:
                return first,state,False,observations,"PLAYER_MEDIA_ERROR"
        if states:
            current=states[0]
            if first is None and current.get("readyState",0)>=1:
                first=current
            last=current
            observations+=1
            if first and full_player_video_seen(first,current,fixture):
                end_proven=True
                break
        await asyncio.sleep(1)
    # Leave a short tail of the screen showing that playback ended.
    if end_proven:
        await asyncio.sleep(0.6)
    return first,last,end_proven,observations,(
        "HTML_VIDEO_ENDED" if end_proven else "PLAYER_END_NOT_PROVEN")


async def click_digest(page, fixture):
    selectors=(["#start-fixture"] if fixture else
               ["text=ダイジェスト映像","text=レース映像","text=映像を見る"])
    for selector in selectors:
        try:
            loc=page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=5000)
                return {"clicked":True,"selector":selector}
        except Exception as exc:
            return {"clicked":False,"selector":selector,"error":type(exc).__name__}
    return {"clicked":False,"reason":"NO_DIGEST_TRIGGER"}

def encrypt_recordings(recordings: list[Path], public_key_path: Path,
                       encrypted_dir: Path) -> int:
    """Only ciphertext may leave the runner. One-off pilot public RSA key."""
    import secrets
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    public = serialization.load_pem_public_key(public_key_path.read_bytes())
    encrypted_dir.mkdir(parents=True, exist_ok=True)
    metadata = {"schema":"RACE_AI_REPLAY_CIPHER_MANIFEST_V1",
                "race_id":RACE_ID,"files":[]}
    for idx, recording in enumerate(recordings):
        # Never upload plaintext captures, even when there is no video.
        key=secrets.token_bytes(32)
        nonce=secrets.token_bytes(12)
        aad=(RACE_ID+":webm:"+str(idx)).encode("ascii")
        raw=recording.read_bytes()
        cipher=AESGCM(key).encrypt(nonce,raw,aad)
        sealed=public.encrypt(key,padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),label=None))
        name=f"capture-{idx}.webm.aesgcm"
        (encrypted_dir/name).write_bytes(cipher)
        metadata["files"].append({
            "file":name,"nonce":base64.b64encode(nonce).decode("ascii"),
            "wrapped_key":base64.b64encode(sealed).decode("ascii"),
            "aad":base64.b64encode(aad).decode("ascii"),
            "plaintext_sha256":hashlib.sha256(raw).hexdigest(),
            "ciphertext_sha256":hashlib.sha256(cipher).hexdigest(),
        })
    (encrypted_dir/"manifest.json").write_text(
        json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    return len(metadata["files"])


async def probe(url: str, report_path: Path, seconds: int, fixture: bool,
                keep_video: bool=False, encrypted_dir: Path|None=None,
                public_key: Path|None=None) -> dict:
    if not source_allowed(url,fixture):
        raise ValueError("SOURCE_NOT_ALLOWLISTED")
    report_path.parent.mkdir(parents=True,exist_ok=True)
    result={"schema":"RACE_AI_BROWSER_REPLAY_PROBE_V1",
            "race_id":RACE_ID,"fixture_only":fixture,
            "source_page":"SYNTHETIC_LOCAL_ONLY" if fixture else url,
            "observed_at_utc":datetime.now(timezone.utc).isoformat(),
            "real_race_visual_analysis":"NOT_PERFORMED",
            "rider_tracking":"NOT_VERIFIED",
            "cause_of_3_5_4":"UNDETERMINED",
            "drm_bypass":False,"raw_video_public_upload":False,
            "playback_state":"NOT_STARTED"}
    with tempfile.TemporaryDirectory(prefix="keirin-browser-pilot-") as temp:
        player_recording_path=None
        try:
            async with async_playwright() as pw:
                opts={"headless":True,
                      "args":["--no-sandbox","--autoplay-policy=no-user-gesture-required"]}
                if os.environ.get("RACE_AI_CHROMIUM_PATH"):
                    opts["executable_path"]=os.environ["RACE_AI_CHROMIUM_PATH"]
                elif os.environ.get("RACE_AI_BROWSER_CHANNEL") == "chrome":
                    opts["channel"]="chrome"
                browser=await pw.chromium.launch(**opts)
                context=await browser.new_context(viewport={"width":1280,"height":720},
                    record_video_size={"width":1280,"height":720},
                    record_video_dir=temp,locale="ja-JP",timezone_id="Asia/Tokyo")
                page=await context.new_page()
                popups=[]
                page.on("popup",lambda p: popups.append(p))
                try:
                    if fixture:
                        sample=Path(urlparse(url).path)
                        if not sample.is_file() or not 0<sample.stat().st_size<3_000_000:
                            raise ValueError("INVALID_SYNTHETIC_FILE")
                        payload=base64.b64encode(sample.read_bytes()).decode("ascii")
                        await page.set_content(
                            '<title>SYNTHETIC TEST ONLY</title><body style="background:#111">'
                            '<button id="start-fixture" onclick="document.querySelector(\'video\').play()">Play</button>'
                            f'<video width="1000" height="560" muted playsinline src="data:video/webm;base64,{payload}"></video></body>')
                        result["http_status"]=None
                    else:
                        response=await page.goto(url,wait_until="domcontentloaded",timeout=25000)
                        result["http_status"]=response.status if response else None
                    result["page_title"]=(await page.title())[:140]
                    result["click"]=await click_digest(page,fixture)
                    await page.wait_for_timeout(200 if fixture else 1500)
                    pages=[page]+popups
                    result["browser_diagnostics"]={
                        "window_count":len(pages),
                        "frame_count":sum(len(p.frames) for p in pages),
                        "titles":[(await p.title())[:100] for p in pages],
                    }
                    before=[]
                    for candidate in pages:
                        before.extend(await media_state(candidate))
                    result["media_before"]=before
                    for candidate in pages:
                        for frame in candidate.frames:
                            try:
                                await frame.evaluate("""() => {for(const v of document.querySelectorAll('video')){
                                    if(v.paused)v.play().catch(()=>{});}}""")
                            except Exception:
                                pass
                    player_page = popups[-1] if popups else page
                    first,last,end_proven,samples,end_reason=await watch_to_player_end(
                        player_page, seconds, fixture)
                    result["media_after"]=[last] if last else []
                    result["media_first"]=[first] if first else []
                    result["video_end_observations"]=samples
                    result["video_end_reason"]=end_reason
                    result["player_clip_completed"]=end_proven
                    result["html_video_advanced"]=(bool(first and last) and
                        last["currentTime"]>first["currentTime"]+1)
                finally:
                    await context.close()
                    # The replay is a popup window. Keep its recording, not a
                    # duplicate copy of the static racecard page.
                    try:
                        player_page = popups[-1] if popups else page
                        if player_page.video is not None:
                            player_recording_path=Path(await player_page.video.path())
                    except Exception:
                        pass
                    await browser.close()
        except Exception as exc:
            result["error"]=f"{type(exc).__name__}: {str(exc)[:250]}"
        recordings=sorted(Path(temp).glob("*.webm"))
        if player_recording_path in recordings:
            recordings=[player_recording_path]
            result["player_video_only"]=True
        else:
            result["player_video_only"]=False
        result["captures"]=[{"recording":video_metadata(p),"motion":motion_score(p)}
                            for p in recordings]
        # A video element reaching its natural end is a technical clip boundary.
        # It is not proof of a full race if the provider only offers a digest.
        result["whole_unedited_race_verified"]=False
        result["playback_state"]=(
            "COMPLETE_PLAYER_CLIP_RECORDED" if result.get("player_clip_completed")
                 and result.get("html_video_advanced") and result.get("player_video_only")
                 and result["captures"]
            else "CAPTURED_BUT_END_UNVERIFIED" if result.get("html_video_advanced")
                 and result["captures"]
            else "CAPTURED_BUT_PLAYBACK_UNPROVEN" if result["captures"] else "NO_RECORDING")
        if encrypted_dir is not None and public_key is not None and (
                result["playback_state"] == "COMPLETE_PLAYER_CLIP_RECORDED"):
            result["encrypted_capture_count"]=encrypt_recordings(
                recordings, public_key, encrypted_dir)
        if keep_video and recordings and not os.environ.get("GITHUB_ACTIONS"):
            saved=report_path.parent/"matsuyama-1r-screencast.webm"
            shutil.copyfile(recordings[0],saved)
            result["local_video_path"]=str(saved)
    report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default=SOURCE_URL)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--seconds",type=int,default=540,help="Maximum seconds to wait for natural player video end")
    parser.add_argument("--fixture-only",action="store_true")
    parser.add_argument("--keep-video",action="store_true")
    parser.add_argument("--encrypted-dir",type=Path)
    parser.add_argument("--public-key",type=Path)
    a=parser.parse_args()
    if not 6<=a.seconds<=660:
        parser.error("seconds must be 6..660")
    if bool(a.encrypted_dir) != bool(a.public_key):
        parser.error("--encrypted-dir and --public-key are required together")
    r=asyncio.run(probe(a.url,a.report,a.seconds,a.fixture_only,a.keep_video,
                        a.encrypted_dir,a.public_key))
    print(json.dumps({"race_id":r["race_id"],"fixture":r["fixture_only"],
                      "playback_state":r["playback_state"],
                      "error":r.get("error")},ensure_ascii=False))
    if r["playback_state"]!="COMPLETE_PLAYER_CLIP_RECORDED":
        raise SystemExit(2)

if __name__=="__main__":
    main()
