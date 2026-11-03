"""Bounded official nationwide cutoff-order A/B collection (no Vercel).

The authentic current-day nationwide index is verified using fixed PR64
source parser, one official racecard per active venue supplies all 12 cutoffs.
The existing strict PR64 beforeinfo parser validates each race independently.
Source HTML is never persisted. Research scores are untrained/uncalibrated;
external GitHub artifact created_at must still be checked before the cutoff.
One-shot only, not continuous scheduling or permission for unbounded scraping.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT/"pr64-reference"
if not (REF/"race_ai"/"official_day_schedule.py").is_file():
    raise SystemExit("PINNED_OFFICIAL_DAY_SOURCE_REQUIRED")
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(REF))
from race_ai.core import SourceError
from race_ai.official_day_schedule import (
    endpoint as day_endpoint, parse_day_schedule)
from race_ai.official_racelist_adapter import (
    endpoint as racelist_endpoint, parse_official_racelist, MAX_BYTES, JST)
from race_ai.official_race_updates import (
    endpoint as preview_endpoint, parse_update)
from race_ai.tokuyama_day_worker import NoRedirects
from scripts.boat_actual_one_shot_probe import schedule as schedule_times
from scripts.boat_ab_future_pilot import motor_top2
import race_ai
race_ai.__path__.insert(0,str(ROOT/"race_ai"))
from race_ai.boat_deadline_queue import select_due_races
from race_ai.boat_live_feature_shadow import build_live_feature_shadow
from race_ai.boat_manshu_watch import freeze_priced_tail
from race_ai.official_race_updates import endpoint as update_endpoint

MODULE=importlib.util.spec_from_file_location("national_boat_pair",ROOT/"race_ai"/"boat_ab_shadow.py")
model=importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(model)

OUTPUT=ROOT/"boat_nationwide_output"
REQUEST_CAP=45
VENUE_CAP=24
MAX_FORECASTS=3
MAX_ATTEMPTS=5
WAIT_SECONDS=0.15
MIN_TO_CUTOFF=timedelta(seconds=210)
requests_used=0
MAX_HTML=MAX_BYTES


def observed_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def stop(reason, *, source=None, schedule=None, queue=None, tries=None,
         forecasts=None, extended=None, priced=None):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    result={
        "schema":"RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1",
        "state":"OBSERVED_ATTEMPT_NO_FORECAST" if not forecasts else "FORECASTS_GENERATED_NEED_ARTIFACT_CLOCK_VERIFICATION",
        "reason":reason, "observed_at":observed_timestamp(),
        "source_request_count":requests_used,
        "source_request_cap":REQUEST_CAP,
        "official_day_source":source,
        "verified_active_venues":schedule["active_venues"] if schedule else [],
        "verified_venue_count":len(schedule["active_venues"]) if schedule else 0,
        "official_race_registry":queue or [],
        "candidate_attempts":tries or [],
        "paired_forecasts":forecasts or [],
        "paired_forecast_count":len(forecasts or []),
        "additional_official_feature_shadows":extended or [],
        "official_priced_longshot_watches":priced or [],
        "research_only":True,
        "scores_calibrated":False,
        "history_tactical_features_admitted":False,
        "longshot_odds_verified":False,
        "external_artifact_preclose_verified":False,
        "live_continuous_collection_enabled":False,
        "vercel_used":False,
    }
    (OUTPUT/"national.json").write_text(
        json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False),
        encoding="utf-8")
    print(json.dumps({key:result.get(key) for key in (
        "state","reason","verified_venue_count","source_request_count",
        "paired_forecast_count")},ensure_ascii=False))
    return result


def get(url):
    global requests_used
    if requests_used>=REQUEST_CAP:
        raise SourceError("NATIONWIDE_GET_BUDGET_EXHAUSTED")
    requests_used+=1
    req=request.Request(url,headers={"Accept":"text/html",
        "User-Agent":"RACE-AI-owner-reviewed-nationwide-pilot/1.0",
        "Cache-Control":"no-store"})
    with request.build_opener(NoRedirects()).open(req,timeout=12) as response:
        body=response.read(MAX_HTML+1)
        if (response.status!=200 or response.geturl()!=url or len(body)==0
                or len(body)>MAX_HTML or
                not (response.headers.get("content-type") or "").lower().startswith("text/html")):
            raise SourceError("OFFICIAL_RESPONSE_IDENTITY_OR_SIZE_INVALID")
    time.sleep(WAIT_SECONDS)
    captured=datetime.now(timezone.utc)
    return body,captured,hashlib.sha256(body).hexdigest()


def official_schedule(day):
    url=day_endpoint(day)
    data,captured,sha=get(url)
    checked=parse_day_schedule(data,day=day,source_url=url,observed_at=captured.isoformat())
    if checked["status"]!="OFFICIAL_DAY_SCHEDULE_VERIFIED" or len(checked["active_venues"])>VENUE_CAP:
        raise SourceError("NATIONAL_INDEX_INCOMPLETE")
    return checked,captured,sha,url


def make_pair(day,race):
    race_id=race["race_id"];venue=race_id[9:11];n=int(race_id[-2:])
    now=datetime.now(timezone.utc)
    cutoff=datetime.fromisoformat(race["cutoff_at"])
    if cutoff-now<=MIN_TO_CUTOFF:
        return {"race_id":race_id,"state":"TOO_LATE_BEFORE_SOURCE"},None,None,None
    url=racelist_endpoint(day,venue,n)
    raw,at,program_sha=get(url)
    program=parse_official_racelist(raw,day=day,venue=venue,race_no=n,
                     source_url=url,captured_at=at.isoformat())
    if (program["race_id"]!=race_id or program["closed_at"]!=race["cutoff_at"]
            or any(r["entry_status"]!="listed" for r in program["boats"])):
        return {"race_id":race_id,"state":"OFFICIAL_PROGRAM_OR_WITHDRAWAL_CONFLICT"},None,None,None
    motor=motor_top2(raw,program["boats"])
    official_preview_url=preview_endpoint(day,venue,n,"beforeinfo")
    preview,preview_at,preview_sha=get(official_preview_url)
    result=parse_update(preview,kind="beforeinfo",day=day,venue=venue,race_no=n,
                        source_url=official_preview_url,captured_at=preview_at.isoformat(),
                        entries=program["boats"])
    if result["status"]!="AVAILABLE" or result.get("data") is None:
        return {"race_id":race_id,"state":"EXHIBITION_NOT_FULLY_PUBLISHED",
                "source_sha256":preview_sha},None,None,None
    six=sorted(result["data"]["boats"],key=lambda r:r["lane"])
    if len(six)!=6 or any(r["display_time"] is None for r in six):
        return {"race_id":race_id,"state":"EXHIBITION_TIME_INCOMPLETE"},None,None,None
    entrants={r["lane"]:r for r in program["boats"]}
    boats=[]
    for measured in six:
        known=entrants[measured["lane"]]
        if known["racer_registration_id"]!=measured["racer_registration_id"]:
            raise SourceError("SIX_BOAT_REGISTRATION_MISMATCH")
        boats.append({
            "lane":measured["lane"],
            "racer_id":known["racer_registration_id"],
            "national_win_rate":known["national_win_rate"],
            "exhibition_time_seconds":measured["display_time"],
            "motor_two_place_rate_percent":motor[measured["lane"]],
        })
    generated=observed_timestamp()
    data={
        "race_id":race_id, "cutoff_at":race["cutoff_at"],
        "captured_at":max(at,preview_at).isoformat(timespec="microseconds"),
        "program_source_sha256":program_sha,
        "beforeinfo_source_sha256":preview_sha,
        "boats":boats,
    }
    computed=model.build_pair(data,generated)
    if datetime.now(timezone.utc)+MIN_TO_CUTOFF>=cutoff:
        return {"race_id":race_id,"state":"TOO_LATE_AFTER_MODEL"},None,None,None
    # C-lite uses the *same official observations*, including local rate and
    # the already published historical average ST. It remains separate from
    # frozen A/B and is never misrepresented as a tactical history model.
    extra={
        "race_id":race_id,
        "observed_at":preview_at.isoformat(timespec="microseconds"),
        "source_sha256":hashlib.sha256((program_sha+preview_sha).encode()).hexdigest(),
        "participants":[{
            "lane":r["lane"],"racer_id":r["racer_registration_id"],
            "local_win_rate":r["local_win_rate"],
            "average_st":r["average_st"],
            "exhibition_st":next(x for x in six if x["lane"]==r["lane"])["preview_st"],
            "exhibition_st_status":next(x for x in six if x["lane"]==r["lane"])["preview_st_status"],
        } for r in program["boats"]],
    }
    extended=None
    try:
        extended=build_live_feature_shadow(data,extra,observed_timestamp())
    except ValueError:
        extended={"race_id":race_id,"state":"C_LITE_SOURCE_NOT_ADMITTED"}
    # A man-shu is >=10,000 yen for a 100-yen ticket. Do NOT infer it
    # from a low model score. Require 120 published official odds before the
    # relevant cutoff and label the priced research variant separately.
    priced={"race_id":race_id,"state":"OFFICIAL_PRE_CLOSE_PRICES_NOT_VERIFIED"}
    if datetime.now(timezone.utc)+MIN_TO_CUTOFF<cutoff and requests_used<REQUEST_CAP:
        try:
            price_url=update_endpoint(day,venue,n,"odds3t")
            odds_raw,odds_at,odds_sha=get(price_url)
            odds=parse_update(odds_raw,kind="odds3t",day=day,venue=venue,race_no=n,
                              source_url=price_url,captured_at=odds_at.isoformat(),
                              entries=program["boats"])
            old_pair={"schema":"RACE_AI_BOAT_LIVE_AB_RESEARCH_V1",
                      "status":"REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT",
                      "race_id":race_id,"cutoff_at":race["cutoff_at"],
                      "result_used":False,"paired_forecast":computed}
            priced=freeze_priced_tail(old_pair,odds,observed_timestamp())
        except (SourceError,ValueError,KeyError,TypeError) as ex:
            priced={"race_id":race_id,"state":"OFFICIAL_PRE_CLOSE_PRICES_NOT_VERIFIED",
                    "failure_class":type(ex).__name__}
    return {"race_id":race_id,"state":"AB_GENERATED_NOT_YET_EXTERNAL_FROZEN",
            "program_sha256":program_sha,"exhibition_sha256":preview_sha,
            "generated_at":generated},computed,extended,priced


def run():
    global requests_used
    requests_used=0
    if os.environ.get("RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED")!="true":
        return stop("OWNER_SOURCE_SCOPE_REQUIRED")
    now=datetime.now(timezone.utc)
    day=now.astimezone(JST).date()
    try:
        listing,index_at,index_sha,url=official_schedule(day)
    except (SourceError,ValueError,UnicodeError,OSError,error.URLError,TimeoutError,TypeError) as ex:
        return stop("VERIFIED_DAY_SOURCE_UNAVAILABLE",
                    source={"failure_class":type(ex).__name__})
    active=listing["active_venues"]
    rows=[];venue_errors=[]
    # One verified 12R closing schedule per active venue. Source is original,
    # not inferred from a cached website snippet or the race's number.
    for venue in active:
        if requests_used>=REQUEST_CAP:
            venue_errors.append({"venue":venue,"state":"GET_CAP"})
            break
        try:
            source_url=racelist_endpoint(day,venue,1)
            body,at,sha=get(source_url)
            identity=parse_official_racelist(body,day=day,venue=venue,race_no=1,
                 source_url=source_url,captured_at=at.isoformat())
            if identity["status"]!="OFFICIAL_BODY_IDENTITY_VERIFIED":
                raise SourceError("RACELIST_IDENTITY_UNVERIFIED")
            for no,closed in schedule_times(body,day,venue).items():
                rows.append({"race_id":f"{day:%Y%m%d}-{venue}-{no:02d}",
                             "cutoff_at":closed.isoformat(),
                             "schedule_captured_at":at.isoformat(),
                             "source_sha256":sha})
        except (SourceError,ValueError,UnicodeError,OSError,error.URLError,TimeoutError,TypeError) as ex:
            venue_errors.append({"venue":venue,"state":"VENUE_SCHEDULE_REJECTED",
                                 "failure_class":type(ex).__name__})
    if not rows:
        return stop("NO_VERIFIED_CUTOFF_ROWS",schedule=listing,
                    source={"url":url,"source_sha256":index_sha,"captured_at":index_at.isoformat()},
                    tries=venue_errors)
    # The verified day registry contains already-closed morning races. A
    # schedule captured this afternoon is NOT pre-close evidence for a race
    # that finished in the morning. Retain these in the registry/audit count,
    # but never submit them to the pre-close queue or pretend a forecast.
    selection_clock=datetime.now(timezone.utc)
    prospective_rows=[]
    after_close_rows=[]
    for record in rows:
        cutoff=datetime.fromisoformat(record["cutoff_at"])
        captured=datetime.fromisoformat(record["schedule_captured_at"])
        if cutoff<=selection_clock or captured>=cutoff:
            after_close_rows.append({
                "race_id":record["race_id"],
                "reason":"ALREADY_CLOSED_BEFORE_SCHEDULE_CAPTURE"})
        else:
            prospective_rows.append(record)
    try:
        queue=select_due_races(prospective_rows,selection_clock.isoformat(),
                              max_items=24)
    except ValueError as ex:
        return stop("NATIONWIDE_ORDER_VALIDATION_REJECTED",schedule=listing,
                    source={"url":url,"source_sha256":index_sha,"captured_at":index_at.isoformat()},
                    tries=venue_errors)
    attempts=list(after_close_rows)
    forecasts=[];extra_forecasts=[];priced_watches=[]
    for race in queue["eligible"][:MAX_ATTEMPTS]:
        try:
            status,pair,extended,priced=make_pair(day,race)
            attempts.append(status)
            if pair is not None:
                forecasts.append(pair)
                if extended is not None:extra_forecasts.append(extended)
                if priced is not None:priced_watches.append(priced)
                if len(forecasts)>=MAX_FORECASTS:
                    break
        except (SourceError,ValueError,UnicodeError,OSError,error.URLError,TimeoutError,TypeError) as ex:
            attempts.append({"race_id":race["race_id"],"state":"OFFICIAL_RACE_REJECTED",
                             "failure_class":type(ex).__name__})
        if requests_used>=REQUEST_CAP:
            break
    # If the externally saved batch is late, the independent GitHub artifact
    # verifier must disqualify that race, never present it as pre-cutoff.
    source={"url":url,"source_sha256":index_sha,"captured_at":index_at.isoformat(),
            "active_venues":active}
    compact=[{key:item[key] for key in ("race_id","cutoff_at","schedule_captured_at","source_sha256")}
            for item in rows]
    return stop("NEEDS_INDEPENDENT_GITHUB_ARTIFACT_TIME_CHECK" if forecasts else
                "NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES",
                source=source,schedule=listing,
                queue=compact,tries=venue_errors+attempts,forecasts=forecasts,
                extended=extra_forecasts,priced=priced_watches)


if __name__=="__main__":
    run()
