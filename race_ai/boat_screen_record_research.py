"""Opt-in HTML5 SCREEN recording, encrypted before any public artifact upload.

A research-only, ordinary browser-display recorder inspired by the existing
KEIRIN Playwright capture. No media stream extraction, DRM/login bypass,
bulk crawler, secret fallback, scheduler, forecast generation or result input.
The site owner still must authorize source use under applicable rules; a mock
fixture receipt is NOT actual permission. The output is never a production P1.
"""
import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit

from .actions_contract import digest
from .boat_national_video_research_gate import _RACE, _SHA, JST, instant

_SOURCE_SCHEMA="RACE_AI_BOAT_SCREEN_SOURCE_V1"
_GRANT_SCHEMA="RACE_AI_BOAT_SCREEN_RIGHTS_V1"
_CIPHER_SCHEMA="RACE_AI_BOAT_SCREEN_CAPTURE_AES_V1"
_URL_HOSTS=frozenset(("race.boatcast.jp","boatcast.jp","www.boatrace.jp"))
_REQUIRED_USES=frozenset(("SCREEN_RECORDING","PRIVATE_VIDEO_ANALYSIS","RESEARCH_P1_DERIVATION"))
_MAX_SCREEN_BYTES=256*1024*1024


def _hold(code):
    return dict(status=code,source_fetch_performed=False,
                production_video_forecast_proven=False,
                public_video_approved=False,model_eligible=False,
                automatic_production_enabled=False)


def _utc(value):
    return value.astimezone(timezone.utc)


def preflight(source,grant,*,now,verify_grant=None):
    """Independent grant is required BEFORE navigating to a source page."""
    try:
        if not isinstance(now,datetime) or now.utcoffset() is None:
            return _hold("HOLD_SCREEN_CLOCK_INVALID")
        if (type(source) is not dict or set(source)!={"schema","race_id","cutoff_at",
                                                    "page_url","mode","play_selector"} or
                source.get("schema")!=_SOURCE_SCHEMA or
                type(source.get("race_id")) is not str or
                _RACE.fullmatch(source["race_id"]) is None or
                source.get("mode") not in ("REPLAY",)):
            return _hold("HOLD_SCREEN_SOURCE_INVALID")
        cutoff=instant(source["cutoff_at"])
        if (cutoff.astimezone(JST).strftime("%Y%m%d")!=source["race_id"][:8] or
                now>=cutoff-timedelta(seconds=210)):
            return _hold("HOLD_SCREEN_CUTOFF_NOT_SAFE")
        raw=source["page_url"]
        if type(raw) is not str or len(raw)>2048 or any(ord(c)<33 or ord(c)==127 for c in raw):
            return _hold("HOLD_SCREEN_SOURCE_INVALID")
        u=urlsplit(raw)
        if (u.scheme!="https" or u.hostname not in _URL_HOSTS or
                u.netloc!=u.hostname or u.fragment or u.username or u.password):
            return _hold("HOLD_SCREEN_SOURCE_INVALID")
        play=source["play_selector"]
        if play is not None and (type(play) is not str or
                re.fullmatch(r'button(?:#[a-zA-Z][a-zA-Z0-9_-]*)?',play) is None):
            return _hold("HOLD_SCREEN_SOURCE_INVALID")
        if (type(grant) is not dict or set(grant)!={"schema","race_id","page_url",
            "rights_evidence_sha256","grant_type","permitted_uses","valid_from",
            "valid_until","private_only"} or
            grant.get("schema")!=_GRANT_SCHEMA or
            grant.get("race_id")!=source["race_id"] or
            grant.get("page_url")!=source["page_url"] or
            grant.get("grant_type")!="RIGHTS_HOLDER_WRITTEN_GRANT" or
            grant.get("private_only") is not True or
            type(grant.get("rights_evidence_sha256")) is not str or
            _SHA.fullmatch(grant["rights_evidence_sha256"]) is None or
            type(grant.get("permitted_uses")) is not list or
            not all(type(x) is str for x in grant["permitted_uses"]) or
            len(set(grant["permitted_uses"]))!=len(grant["permitted_uses"]) or
            not _REQUIRED_USES.issubset(set(grant["permitted_uses"]))):
            return _hold("HOLD_SCREEN_RIGHTS_UNAVAILABLE")
        if not instant(grant["valid_from"])<=now<instant(grant["valid_until"]):
            return _hold("HOLD_SCREEN_RIGHTS_UNAVAILABLE")
        if not callable(verify_grant):
            return _hold("HOLD_SCREEN_RIGHTS_UNAVAILABLE")
        receipt=verify_grant(grant,source)
        if (type(receipt) is not dict or
                receipt.get("state")!="INDEPENDENT_RIGHTS_RECEIPT_VERIFIED" or
                receipt.get("manifest_sha256")!=digest(grant) or
                receipt.get("evidence_sha256")!=grant["rights_evidence_sha256"] or
                not instant(grant["valid_from"])<=instant(receipt["verified_at"])<=now):
            return _hold("HOLD_SCREEN_RIGHTS_UNAVAILABLE")
        return dict(_hold("READY_PRIVATE_SCREEN_RESEARCH_ONLY"),
                    rights_manifest_sha256=digest(grant),
                    source_page_sha256=sha256(raw.encode()).hexdigest())
    except (ValueError,KeyError,TypeError,OverflowError,UnicodeError,AttributeError,AssertionError):
        return _hold("HOLD_SCREEN_RIGHTS_UNAVAILABLE")


def _b64(raw):
    return base64.b64encode(raw).decode("ascii")


def _bytes(text):
    if type(text) is not str:
        raise ValueError("BOAT_SCREEN_CIPHER_INVALID")
    return base64.b64decode(text,validate=True)


def seal_screen(video_bytes,*,race_id,page_url,fixture,aes_key):
    """Private encrypted bytes only; no plaintext media on public Git."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if (type(video_bytes) is not bytes or not 0<len(video_bytes)<=_MAX_SCREEN_BYTES or
        type(aes_key) is not bytes or len(aes_key)!=32 or
        type(race_id) is not str or _RACE.fullmatch(race_id) is None or
        type(page_url) is not str or type(fixture) is not bool):
        raise ValueError("BOAT_SCREEN_CIPHER_INVALID")
    import os
    digest_media=sha256(video_bytes).hexdigest()
    binding=dict(schema=_CIPHER_SCHEMA,race_id=race_id,media_sha256=digest_media,
                 source_page_sha256=sha256(page_url.encode()).hexdigest(),
                 synthetic_fixture=fixture)
    aad=json.dumps(binding,sort_keys=True,separators=(',',':')).encode()
    nonce=os.urandom(12)
    cipher=AESGCM(aes_key).encrypt(nonce,video_bytes,aad)
    return dict(binding,nonce=_b64(nonce),ciphertext=_b64(cipher))


def unseal_screen(envelope,*,aes_key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if (type(envelope) is not dict or set(envelope)!={"schema","race_id","media_sha256",
        "source_page_sha256","synthetic_fixture","nonce","ciphertext"} or
        envelope.get("schema")!=_CIPHER_SCHEMA or type(aes_key) is not bytes or len(aes_key)!=32 or
        type(envelope.get("race_id")) is not str or _RACE.fullmatch(envelope["race_id"]) is None):
        raise ValueError("BOAT_SCREEN_CIPHER_INVALID")
    fields={k:v for k,v in envelope.items() if k not in ("nonce","ciphertext")}
    try:
        nonce=_bytes(envelope["nonce"])
        cipher=_bytes(envelope["ciphertext"])
        if len(nonce)!=12 or not 16<len(cipher)<=_MAX_SCREEN_BYTES+16:
            raise ValueError()
        aad=json.dumps(fields,sort_keys=True,separators=(',',':')).encode()
        video=AESGCM(aes_key).decrypt(nonce,cipher,aad)
        if sha256(video).hexdigest()!=fields["media_sha256"]:
            raise ValueError()
        return video
    except (ValueError,KeyError,TypeError,OverflowError):
        raise ValueError("BOAT_SCREEN_CIPHER_INVALID") from None
    except Exception:
        raise ValueError("BOAT_SCREEN_CIPHER_INVALID") from None


def _duration(path):
    command=["ffprobe","-v","error","-show_entries","format=duration",
             "-of","json",str(path)]
    data=json.loads(subprocess.check_output(command,timeout=15))
    value=float(data["format"]["duration"])
    if not math.isfinite(value) or value<0.5 or value>210:
        raise ValueError("BOAT_SCREEN_DURATION_UNVERIFIED")
    return value


async def _visible_state(page):
    # Only read the visible HTML5 player API (including ordinary iframes).
    # Never read direct media URLs or inspect/decode a protected stream.
    js="""() => {
      const player=document.querySelector('video');
      if(!player)return null;
      const b=player.getBoundingClientRect();
      const css=getComputedStyle(player);
      return {visible:b.width>40&&b.height>40&&css.display!=='none'&&
            css.visibility!=='hidden',currentTime:player.currentTime,
        duration:Number.isFinite(player.duration)?player.duration:null,
        ended:player.ended,readyState:player.readyState,paused:player.paused};
    }"""
    for frame in page.frames:
        try:
            result=await frame.evaluate(js)
            if result and result.get("visible") is True and result.get("readyState",0)>=1:
                return result
        except Exception:
            continue
    return None


async def record_screen(browser,source,grant,*,verify_grant,now,aes_key,
                        fixture_loader=None,timeout_seconds=30):
    """Record one ordinary visible HTML5 replay, then encrypt the screen WebM.

    In fixture mode the supplied loader sets LOCAL HTML only, and the output
    is labelled synthetic. A live run requires current clock plus independent
    rights proof and ordinary exact-page navigation; it is never a P1 proof.
    """
    status=preflight(source,grant,now=now,verify_grant=verify_grant)
    if status["status"]!="READY_PRIVATE_SCREEN_RESEARCH_ONLY":
        return status
    if type(aes_key) is not bytes or len(aes_key)!=32:
        return _hold("HOLD_SCREEN_ENCRYPTION_KEY_REQUIRED")
    if type(timeout_seconds) is not int or not 2<=timeout_seconds<=180:
        return _hold("HOLD_SCREEN_TIMEOUT_INVALID")
    if fixture_loader is not None and not callable(fixture_loader):
        return _hold("HOLD_SCREEN_FIXTURE_INVALID")
    if fixture_loader is None:
        # A caller-injected historical clock cannot authorize real capture.
        if abs((_utc(now)-datetime.now(timezone.utc)).total_seconds())>120:
            return _hold("HOLD_SCREEN_LIVE_CLOCK_UNVERIFIED")
        if now+timedelta(seconds=timeout_seconds+210)>=instant(source["cutoff_at"]):
            return _hold("HOLD_SCREEN_TIME_WINDOW_TOO_SHORT")
    with tempfile.TemporaryDirectory(prefix="boat-screen-research-") as folder:
        import os
        os.chmod(folder,0o700)
        context=None
        page=None
        recorded=None
        first=last=None
        ended=False
        try:
            context=await browser.new_context(
                viewport={"width":640,"height":360},
                record_video_dir=folder,
                record_video_size={"width":640,"height":360},
                locale="ja-JP",timezone_id="Asia/Tokyo")
            page=await context.new_page()
            if fixture_loader is not None:
                await fixture_loader(page)
            else:
                response=await page.goto(source["page_url"],
                                         wait_until="domcontentloaded",timeout=20000)
                if (response is None or response.status!=200 or
                        page.url!=source["page_url"]):
                    return _hold("HOLD_SCREEN_PAGE_IDENTITY_UNVERIFIED")
                if source["play_selector"] is not None:
                    button=page.locator(source["play_selector"])
                    if await button.count()!=1 or not await button.is_visible():
                        return _hold("HOLD_SCREEN_PLAY_CONTROL_UNAVAILABLE")
                    await button.click(timeout=6000)
            import time
            deadline=time.monotonic()+timeout_seconds
            while time.monotonic()<deadline:
                current=await _visible_state(page)
                if current:
                    if first is None:
                        first=current
                    last=current
                    duration=current.get("duration")
                    if (type(duration) in (float,int) and
                            1.0<=duration<=180.0 and
                            first.get("currentTime",999)<min(5.0,max(0.65,duration*0.08)) and
                            current.get("ended") is True and
                            current.get("currentTime",0)>=duration-max(0.7,duration*.03) and
                            current.get("currentTime",0)-first.get("currentTime",0)>0.75):
                        ended=True
                        break
                await page.wait_for_timeout(170)
        except Exception:
            return _hold("HOLD_SCREEN_PLAYBACK_UNAVAILABLE")
        finally:
            try:
                if context is not None:
                    await context.close()
                if page is not None and page.video is not None:
                    recorded=Path(await page.video.path())
            except Exception:
                recorded=None
        if not ended or recorded is None or not recorded.is_file() or recorded.is_symlink():
            return _hold("HOLD_VISIBLE_PLAYER_NOT_COMPLETE")
        try:
            stat=recorded.stat()
            if not 1000<=stat.st_size<=_MAX_SCREEN_BYTES:
                return _hold("HOLD_SCREEN_CAPTURE_BYTES_INVALID")
            actual=_duration(recorded)
            if actual+1.7<last["duration"] or actual>last["duration"]+30:
                return _hold("HOLD_SCREEN_CAPTURE_DURATION_MISMATCH")
            raw=recorded.read_bytes()
            envelope=seal_screen(raw,race_id=source["race_id"],
                page_url=source["page_url"],fixture=fixture_loader is not None,
                aes_key=aes_key)
            return dict(status="SCREEN_REPLAY_CAPTURE_ENCRYPTED_UNVALIDATED",
                source_class=("SYNTHETIC_OFFLINE_BROWSER_FIXTURE" if fixture_loader is not None
                              else "OWNER_RIGHTS_GATED_BROWSER_SCREEN_UNVALIDATED"),
                race_id=source["race_id"],media_sha256=envelope["media_sha256"],
                screen_recording_bytes=len(raw),screen_duration_seconds=actual,
                player_ended=True,screen_recording_technically_verified=True,
                production_video_forecast_proven=False,
                public_video_approved=False,model_eligible=False,
                source_fetch_performed=fixture_loader is None,
                envelope=envelope)
        except (OSError,ValueError,TypeError,OverflowError,subprocess.SubprocessError,UnicodeError):
            return _hold("HOLD_SCREEN_CAPTURE_VERIFICATION_FAILED")
