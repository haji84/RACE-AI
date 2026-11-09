"""Connect owner-private saved WINTICKET SSR bytes to existing intake.

Uses pre-existing owner_public_capture/*.html plus SHA receipt made by the
public page collector. Source-grounded pre-race racecards are retained even
before a live odds page is published. Both racecard AND a complete 210/504
odds page are required only for staging price sets. No retroactive forecast,
guessed 347/437 rider factors, public plaintext or private-source log.
"""
from __future__ import annotations

from datetime import datetime,timedelta
from hashlib import sha256
from pathlib import Path
import json
import re

from .keirin_permissioned_owner import _write_private_once
from .keirin_result_delivery import canonical,utc
from .keirin_winticket_embedded_odds import (
    private_winticket_trifecta,stage_private_winticket_odds,
    EmbeddedOddsError
)
from .keirin_winticket_embedded_racecard import (
    racecard_from_public_html,EmbeddedRacecardError
)

SOURCE_RE=re.compile(
    r"^https://(?:www\.)?winticket\.jp/keirin/"
    r"([a-z][a-z0-9-]{2,30})/(racecard|odds)/"
    r"([0-9]{8})([0-9]{2})/([123])/([1-9][0-9]?)$"
)
MAX_CAPTURES=2500


class CapturedSSRIntakeError(ValueError):
    pass


def require(ok,code):
    if not ok:
        raise CapturedSSRIntakeError(code)


def _identity(url):
    require(type(url) is str,"SOURCE_URL_INVALID")
    m=SOURCE_RE.fullmatch(url)
    require(m is not None,"NOT_APPROVED_WINTICKET_RACE_PAGE")
    venue,kind,start,track,day,no=m.groups()
    try:
        begin=datetime.strptime(start,"%Y%m%d").date()
        event=begin+timedelta(days=int(day)-1)
        num=int(no)
        require(1<=num<=12 and 1<=int(track)<=99,
                "RACE_ID_OUT_OF_RANGE")
        rid=f"{event:%Y%m%d}{track}{num:02d}"
    except (ValueError,OverflowError):
        raise CapturedSSRIntakeError("INVALID_EVENT_DAY") from None
    return rid,kind


def _read_capture_pair(receipt_path):
    require(receipt_path.is_file() and not receipt_path.is_symlink() and
            0<receipt_path.stat().st_size<8192,"SOURCE_RECEIPT_UNSAFE")
    try:
        meta=json.loads(receipt_path.read_text(encoding="utf-8"))
        require(type(meta) is dict and meta.get("schema")==
                "RACE_AI_KEIRIN_OWNER_PUBLIC_HTML_CAPTURE_V1",
                "UNEXPECTED_CAPTURE_SCHEMA")
        source=meta.get("source_url")
        rid,kind=_identity(source)
        captured=utc(meta["captured_at_utc"])
        html=receipt_path.with_suffix(".html")
        require(html.is_file() and not html.is_symlink() and
                0<html.stat().st_size<=8_000_000,"CAPTURE_HTML_UNSAFE")
        data=html.read_bytes()
        require(sha256(data).hexdigest()==meta["body_sha256"] and
                len(data)==meta["body_size_bytes"],
                "CAPTURED_SOURCE_SHA_MISMATCH")
        return rid,kind,source,captured,data
    except (OSError,ValueError,KeyError,TypeError) as e:
        if isinstance(e,CapturedSSRIntakeError):
            raise
        raise CapturedSSRIntakeError("SOURCE_CAPTURE_RECEIPT_INVALID") from None


def stage_private_captured_winticket(inbox):
    """Reuses private owner inbox. A historical race can only stage odds, never
    create a retroactive forecast, even if its HTML was genuinely pre-cutoff.
    """
    root=Path(inbox).expanduser()
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
            "OWNER_PRIVATE_INBOX_REQUIRED")
    folder=root/"owner_public_capture"
    if not folder.exists():
        return {
            "schema":"RACE_AI_KEIRIN_CAPTURED_SSR_SOURCE_STAGE_V1",
            "captured_html_seen":0,"full_odds_races_staged":0,
            "private_partial_racecards_staged":0,
            "incomplete_races":0,"network_requests":0,
            "forecasts_created":0,
        }
    require(folder.is_dir() and not folder.is_symlink(),
            "CAPTURE_ROOT_UNSAFE")
    receipts=sorted(folder.glob("*.json"))
    require(len(receipts)<=MAX_CAPTURES,
            "TOO_MANY_CAPTURES_IN_ONE_SCAN")
    race={}
    rejected=0
    for receipt in receipts:
        try:
            rid,kind,url,observed,data=_read_capture_pair(receipt)
        except CapturedSSRIntakeError:
            rejected+=1
            continue
        race.setdefault(rid,{}).setdefault(kind,[]).append(
            (observed,url,data))
    staged_prices=0
    partial_riders=0
    incomplete=0
    partial_dir=root/"winticket_racecard_partial"
    if not partial_dir.exists():
        partial_dir.mkdir(mode=0o700)
    require(partial_dir.is_dir() and not partial_dir.is_symlink(),
            "RACECARD_PARTIAL_DIR_UNSAFE")
    for rid,parts in sorted(race.items()):
        cards=sorted(parts.get("racecard",[]),key=lambda x:x[0])
        prices=sorted(parts.get("odds",[]),key=lambda x:x[0])
        if not cards:
            incomplete+=1
            continue
        admitted_card=None
        for at,url,body in cards:
            try:
                admitted_card=racecard_from_public_html(
                    body,url=url,race_id=rid,
                    captured_at=at.isoformat())
                break
            except EmbeddedRacecardError:
                continue
        if admitted_card is None:
            incomplete+=1
            continue
        # A partial 347/437-field source record is useful evidence, but
        # MUST NOT be supplied as a complete full-factor PR71 forecast input.
        h=sha256(canonical(admitted_card)).hexdigest()
        partial_dir.joinpath(h+".json")
        if _write_private_once(partial_dir/(h+".json"),admitted_card):
            partial_riders+=1
        # Odds can legitimately be pending many hours before the race.
        # Preserve the authentic rider source packet now and process prices
        # independently when the same race's public odds are later published.
        if not prices:
            incomplete+=1
            continue
        qualified=False
        for at,url,body in prices:
            try:
                verified=private_winticket_trifecta(
                    body,url=url,race_id=rid,
                    captured_at=at.isoformat(),
                    official_cutoff_at=admitted_card[
                        "source_published_cutoff_at_utc"])
                saved=stage_private_winticket_odds(root,verified)
                staged_prices+=saved["private_odds_created"]
                qualified=True
                break
            except EmbeddedOddsError:
                continue
        if not qualified:
            incomplete+=1
    return {
        "schema":"RACE_AI_KEIRIN_CAPTURED_SSR_SOURCE_STAGE_V1",
        "captured_html_seen":len(receipts),
        "captured_unadmitted":rejected,
        "source_races_seen":len(race),
        "full_odds_races_staged":staged_prices,
        "private_partial_racecards_staged":partial_riders,
        "incomplete_races":incomplete,
        "network_requests":0,
        "full_preflight_claimed":False,
        "forecasts_created":0,
        "public_plaintext_written":False,
    }
