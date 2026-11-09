"""Real one-race forward public SSR integration probe for KEIRIN.

From the current WINTICKET published daily index, select a genuinely
future 7/9-rider event with an observed cutoff and source-joined ordinary
public racecard/odds URLs. Then check complete 210/504 odds and partial
source-derived 347/437 preflight using existing parsers.

This is a READ-ONLY integration check, not a production predictor. Data
contents are not emitted or persisted in public GitHub Actions; no fake
prices, late forecasts, or artificial full-347/437 claims.
"""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
import argparse
import json
import re

from race_ai.keirin_winticket_day_index import (
    extract_owner_winticket_day,safe_day_index_summary,
    WinticketDayIndexError
)
from race_ai.keirin_owner_public_page_fetch import (
    network_page_once,PublicPageFetchError
)
from race_ai.keirin_result_delivery import utc
from race_ai.keirin_winticket_embedded_racecard import EmbeddedRacecardError
from race_ai.keirin_winticket_embedded_odds import EmbeddedOddsError
from scripts.keirin_future_public_ssr_probe import public_future_race_probe

SCHEMA="RACE_AI_KEIRIN_NEXT_PUBLISHED_RACE_SOURCE_GATE_V1"
JST=ZoneInfo("Asia/Tokyo")


def discover_and_probe(*,event_day=None,race_id=None,clock=None,fetch=None):
    if clock is None:clock=lambda:datetime.now(timezone.utc)
    if fetch is None:fetch=network_page_once
    now=clock()
    if not isinstance(now,datetime) or now.utcoffset() is None:
        raise ValueError("TRUSTED_AWARE_CLOCK_REQUIRED")
    now=now.astimezone(timezone.utc)
    day=event_day or now.astimezone(JST).date().isoformat()
    if race_id is not None:
        if (type(race_id) is not str or
                re.fullmatch(r"20[0-9]{10}",race_id) is None or
                race_id[:8] != day.replace("-","")):
            raise ValueError("EXACT_FUTURE_RACE_AND_JST_DAY_REQUIRED")
    url="https://www.winticket.jp/keirin/odds/"+day.replace("-","")
    raw=fetch(url)
    roster=extract_owner_winticket_day(
        raw,source_url=url,event_day=day)
    index=safe_day_index_summary(roster)
    def eligible(row):
        if not (row["candidate_odds_page_url"] and
                row["candidate_racecard_page_url"] and
                row["candidate_url_source"]==
                "PUBLISHED_SSR_CUP_SCHEDULE_VENUE_AND_PUBLIC_VENUE_LINK" and
                row["candidate_page_http_get_verified"] is False and
                row["published_entrant_count"] in (7,9)):
            return False
        close=row["public_close_at_utc"]
        if type(close) is not str:return False
        try:deadline=utc(close)
        except (TypeError,ValueError):return False
        return now+timedelta(minutes=6)<deadline
    candidates=sorted(
        (r for r in roster["public_schedule_rows"]
         if eligible(r) and (race_id is None or r["race_id"]==race_id)),
        key=lambda r:(r["public_close_at_utc"],r["race_id"]))
    report={
        "schema":SCHEMA,"event_date_jst":day,
        "observation_clock_utc":now.isoformat(),
        "date_index_sha256":index["index_html_sha256"],
        "source_races_observed":index["published_ssr_race_count"],
        "source_derived_candidate_page_count":
            index["published_ssr_candidate_url_count"],
        "explicit_research_target": race_id,
        "target_seen_in_public_index": (
            race_id is None or any(
                r["race_id"]==race_id
                for r in roster["public_schedule_rows"])),
        "target_page_source_confirmed": bool(candidates),
        "eligible_unstarted_races":len(candidates),
        "actual_model_prediction_saved":False,
        "actual_forecast_pre_cutoff_evidenced":False,
        "formal_model_input_preflight_completed":False,
        "production_aead_checkpoint_saved":False,
        "research_reference_only":True,
    }
    if not candidates:
        return {
            **report,"status":"NO_UPCOMING_SOURCE_ELIGIBLE_EVENT",
            "target_selected":False,"real_full_odds_verified":False,
        }
    target=candidates[0]
    result={
        **report,
        "target_selected":True,
        "race_id":target["race_id"],
        "winticket_close_at_utc":target["public_close_at_utc"],
        "published_entrants":target["published_entrant_count"],
    }
    try:
        probe=public_future_race_probe(
            race_id=target["race_id"],
            racecard_url=target["candidate_racecard_page_url"],
            odds_url=target["candidate_odds_page_url"],
            fetch=fetch,clock=clock)
    except (PublicPageFetchError,EmbeddedRacecardError,EmbeddedOddsError,
            OSError,ValueError) as exc:
        reason=str(exc)
        safe_reasons={
            "PUBLIC_PAGE_NOT_PUBLISHED_OR_GONE",
            "PUBLIC_PAGE_BLOCKED_OR_RATE_LIMITED_NO_RETRY",
            "PUBLIC_PAGE_HTTP_NOT_OK",
            "PUBLIC_PAGE_NETWORK_UNAVAILABLE",
        }
        return {
            **result,"status":"CANDIDATE_PUBLIC_PAGE_NOT_AVAILABLE",
            "unavailable_reason":reason if reason in safe_reasons
                               else "SOURCE_REJECTED",
            "real_full_odds_verified":False,
        }
    return {
        **result,"status":probe["status"],
        "real_full_odds_verified":probe.get("actual_210_or_504_verified") is True,
        "observed_trifecta_rows":probe.get("actual_full_trifecta_rows",0),
        "rider_identity_count":probe.get("racecard_verified_riders",0),
        "preflight_checked_count":probe.get("preflight_checked_items",0),
        "preflight_verified_source_count":
            probe.get("preflight_source_verified_items",0),
        "preflight_unavailable_count":
            probe.get("preflight_unavailable_items",0),
        "required_source_slots_total":
            probe.get("model_required_total_A"),
        "required_source_slots_A_observed":
            probe.get("model_required_observed_A"),
        "required_source_slots_A_missing":
            probe.get("model_required_missing_A"),
        "required_source_slots_B_observed":
            probe.get("model_required_observed_B"),
        "required_source_slots_B_missing":
            probe.get("model_required_missing_B"),
        "critical_preflight_source_slots_missing":
            probe.get("preflight_core_required_missing"),
        "odds_price_sha256":probe.get("real_price_sha256"),
        "actual_model_prediction_saved":False,
        "production_aead_checkpoint_saved":False,
    }


def main(args=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--event-day-jst",default=None)
    p.add_argument("--race-id",default=None,
                   help="exact 12-digit official date/venue/R id; source joins only")
    opts=p.parse_args(args)
    try:report=discover_and_probe(
        event_day=opts.event_day_jst, race_id=opts.race_id)
    except (PublicPageFetchError,WinticketDayIndexError,OSError,ValueError):
        report={"schema":SCHEMA,"status":"DAY_INDEX_SOURCE_UNAVAILABLE",
                "real_full_odds_verified":False,
                "production_aead_checkpoint_saved":False}
    print(json.dumps(report,sort_keys=True,separators=(",",":"),
                     ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
