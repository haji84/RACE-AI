"""Bounded, opt-in hourly personal KEIRIN result-page checker.

Exactly zero or one public web-page GET per invocation. No crawling, no retry,
no third-party raw data storage, no future forecasts, no auto-betting.
Published cutoff times in the operator's watchlist are NOT official cutoffs.
This is a noncommercial research canary, not a continuous official result feed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from .keirin_mobile_one_shot import ACK, MobileProbeError, probe_one

JST = timezone(timedelta(hours=9))
SCHEMA = "RACE_AI_KEIRIN_PERSONAL_HOURLY_MANIFEST_V1"
ROW = re.compile(r"([0-9]{2})([0-9]{2})@([0-2][0-9])([0-5][0-9])\Z")
MAX_WATCHLIST_BYTES = 100_000


class MonitorError(ValueError):
    pass


def _manifest(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_WATCHLIST_BYTES:
        raise MonitorError("INVALID_MANIFEST_FILE")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError):
        raise MonitorError("INVALID_MANIFEST_JSON") from None
    if type(value) is not dict or set(value) != {
        "schema", "event_date_jst", "origin", "query_limit_per_run", "cutoff_rows"
    } or value["schema"] != SCHEMA or value["query_limit_per_run"] != 1:
        raise MonitorError("INVALID_MANIFEST_SCHEMA")
    if type(value["origin"]) is not str or not 1 <= len(value["origin"]) <= 500:
        raise MonitorError("MANIFEST_ORIGIN_MISSING")
    try:
        day = datetime.strptime(value["event_date_jst"], "%Y-%m-%d").date()
        if day.isoformat() != value["event_date_jst"]:
            raise ValueError()
    except (ValueError, TypeError):
        raise MonitorError("INVALID_MANIFEST_DAY") from None
    rows = value["cutoff_rows"]
    if type(rows) is not str or len(rows) > 15000:
        raise MonitorError("INVALID_RACE_ROSTER")
    seen = set()
    races = []
    for item in rows.split():
        m = ROW.fullmatch(item)
        if not m:
            raise MonitorError("INVALID_ROSTER_ROW")
        venue, race, h, minute = (int(x) for x in m.groups())
        if not (1 <= venue <= 99 and 1 <= race <= 12 and h <= 23):
            raise MonitorError("INVALID_ROSTER_VALUE")
        rid = value["event_date_jst"].replace("-", "") + f"{venue:02d}{race:02d}"
        if rid in seen:
            raise MonitorError("DUPLICATE_RACE")
        seen.add(rid)
        deadline = datetime(day.year, day.month, day.day, h, minute, tzinfo=JST)
        races.append((deadline, rid, venue, race))
    if not 1 <= len(races) <= 200:
        raise MonitorError("INVALID_ROSTER_SIZE")
    return value["event_date_jst"], races


def select_one(path, *, at):
    if not isinstance(at, datetime) or at.utcoffset() is None:
        raise MonitorError("TZ_AWARE_TIME_REQUIRED")
    day, races = _manifest(path)
    local = at.astimezone(JST)
    if local.date().isoformat() != day:
        return {"state":"NO_CURRENT_DAY_MANIFEST","eligible":0,
                "get_attempts":0,"date":day}
    # A page is first checked after its indicated cutoff +12 minutes.
    # One hourly run covers only a 60-minute cutoff band, so two runs cannot
    # select the same race unless schedule replays or is manually dispatched.
    eligible = [(cutoff, rid, venue, race) for cutoff,rid,venue,race in races
                if local - timedelta(minutes=72) < cutoff <=
                    local - timedelta(minutes=12)]
    if not eligible:
        return {"state":"NO_RECENTLY_FINISHED_RACE","eligible":0,
                "get_attempts":0,"date":day}
    cutoff, rid, venue, race = max(eligible, key=lambda x:(x[0],x[1]))
    return {"state":"ONE_RACE_SELECTED","date":day,"race_id":rid,
            "venue":venue,"race":race,
            "cutoff_proxy_at":cutoff.isoformat(),
            "cutoff_is_officially_verified":False,
            "eligible":len(eligible),"get_attempts":0}


def run_once(manifest, *, now, allow_get, fetch=probe_one):
    selected=select_one(manifest, at=now)
    if selected["state"] != "ONE_RACE_SELECTED":
        return selected
    if allow_get is not True:
        return {**selected,"state":"DRY_RUN_ONE_RACE_READY"}
    try:
        p=fetch(selected["date"].replace("-",""),
                selected["venue"],selected["race"],
                acknowledgement=ACK,route="legacy")
    except (MobileProbeError,OSError,TimeoutError):
        return {"state":"PROVIDER_ONE_GET_FAILED_NO_RETRY",
                "date":selected["date"],"race_id":selected["race_id"],
                "get_attempts":1,"confirmed_official_result":False}
    if not isinstance(p,dict) or p.get("schema") != "RACE_AI_KEIRIN_MOBILE_SINGLE_PAGE_RESEARCH_PROBE_V1":
        return {"state":"INVALID_PROVIDER_RESPONSE",
                "date":selected["date"],"race_id":selected["race_id"],
                "get_attempts":1,"confirmed_official_result":False}
    candidate=p.get("candidate_result",{})
    good=bool(p.get("page_date_marker") and p.get("page_race_marker") and
              type(candidate) is dict and
              candidate.get("state") == "ONE_UNVERIFIED_PROVIDER_CANDIDATE")
    # Public CI logs contain neither picks nor payout nor raw source.
    return {"state":"ONE_PAGE_CANDIDATE_OBSERVED" if good else
                    "ONE_PAGE_RESULT_NOT_VERIFIED",
            "date":selected["date"],"race_id":selected["race_id"],
            "get_attempts":1, "candidate_visible":good,
            "source_sha256":p.get("source_sha256"),
            "confirmed_official_result":False,
            "permanent_private_storage":False,
            "next_forecast_saved":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--allow-one-get",action="store_true")
    args=parser.parse_args(argv)
    try:
        result=run_once(args.manifest,now=datetime.now(timezone.utc),
                        allow_get=args.allow_one_get)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0 if result["state"] not in {
            "PROVIDER_ONE_GET_FAILED_NO_RETRY","INVALID_PROVIDER_RESPONSE"} else 2
    except (MonitorError,ValueError,OSError):
        print('{"state":"MONITOR_CONFIGURATION_REJECTED","get_attempts":0}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
