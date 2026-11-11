"""Owner-private recurring WINTICKET intake from the existing PUBLIC SSR pages.

The GitHub scheduler invokes this on a trusted persistent owner runner, not
in an ephemeral pull-request worker. This is a source feeder, not a new model:
existing keirin_permissioned_owner_agent consumes the saved owner inbox, and
the original PR71 four-model stage runs only with a real complete permitted
347/437 observation set. Never fills missing metrics or invents URL paths.

Only same-day source-linked public paths and actual closeAt values are used.
No unofficial APIs, redirects, auth bypass, raw HTML logs, auto-bets or
public rider data. An owner-attested personal-source selection is not a
provider-granted machine licence or permission for redistribution.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from race_ai.keirin_winticket_day_index import (
    extract_owner_winticket_day, WinticketDayIndexError,
)
from race_ai.keirin_owner_public_page_fetch import (
    network_page_once, capture_approved_public_pages, PublicPageFetchError,
)
from race_ai.keirin_owner_captured_ssr_intake import (
    stage_private_captured_winticket,
)
from race_ai.keirin_winticket_embedded_odds import EmbeddedOddsError
from race_ai.keirin_owner_auto_sources import (
    OwnerAttestedAutomaticSources, AUTOMATION_CONSENT,
)
from race_ai.keirin_owner_approved_sources import PROFILE_ID
from race_ai.keirin_result_delivery import utc

SCHEMA="RACE_AI_KEIRIN_GITHUB_OWNER_DAILY_SOURCE_INTAKE_V1"
JST=ZoneInfo("Asia/Tokyo")
MIN_LEAD_SECONDS=390


def owner_future_public_intake(inbox, *, fetch=None, clock=None,
                               lookahead_minutes=90,max_races=16):
    """Capture *eligible* future source-linked cards + prices, then stage.

    This function does not run a predictor and does not claim a complete
    preflight. Paths are create-once under the original owner-private inbox.
    """
    if clock is None:clock=lambda:datetime.now(timezone.utc)
    if fetch is None:fetch=network_page_once
    private=Path(inbox).expanduser()
    if (not private.is_absolute() or not private.is_dir() or
            private.is_symlink()):
        raise ValueError("EXISTING_OWNER_PRIVATE_INBOX_REQUIRED")
    if type(max_races) is not int or not 1<=max_races<=120:
        raise ValueError("INVALID_PER_RUN_SOURCE_WORK_BUDGET")
    if type(lookahead_minutes) is not int or not 10<=lookahead_minutes<=180:
        raise ValueError("INVALID_SOURCE_FORECAST_WINDOW")
    at=clock()
    if not isinstance(at,datetime) or at.utcoffset() is None:
        raise ValueError("TRUSTED_AWARE_CAPTURE_CLOCK_REQUIRED")
    at=at.astimezone(timezone.utc)
    day=at.astimezone(JST).date().isoformat()
    index_url="https://www.winticket.jp/keirin/odds/"+day.replace("-","")
    grant=OwnerAttestedAutomaticSources(
        profile=PROFILE_ID,consent=AUTOMATION_CONSENT,now=at.isoformat())
    # One ordinary public page. If unavailable, stop rather than scrape
    # alternate/undocumented sources.
    index=extract_owner_winticket_day(
        fetch(index_url),source_url=index_url,event_day=day)
    possible=[]
    for row in index["public_schedule_rows"]:
        if not (
            row["candidate_odds_page_url"] and
            row["candidate_racecard_page_url"] and
            row["candidate_url_source"]==
                "PUBLISHED_SSR_CUP_SCHEDULE_VENUE_AND_PUBLIC_VENUE_LINK" and
            row["published_entrant_count"] in (7,9) and
            row["candidate_page_http_get_verified"] is False and
            isinstance(row["public_close_at_utc"],str)
        ):continue
        try: close=utc(row["public_close_at_utc"])
        except (TypeError,ValueError):continue
        if (at+timedelta(seconds=MIN_LEAD_SECONDS)<close<=
                at+timedelta(minutes=lookahead_minutes)):
            possible.append((close,row))
    possible.sort(key=lambda v:(v[0],v[1]["race_id"]))
    chosen=possible[:max_races]
    counts=Counter()
    blocking=[]
    for _,row in chosen:
        # Clock is checked again for EVERY race, since a slow run or event
        # delay must not retroactively record a future model input.
        moment=clock()
        if (not isinstance(moment,datetime) or moment.utcoffset() is None or
                moment.astimezone(timezone.utc)+timedelta(
                    seconds=MIN_LEAD_SECONDS)>=utc(
                    row["public_close_at_utc"])):
            counts["cutoff_margin_now_missing"]+=1
            continue
        try:
            first=capture_approved_public_pages(
                private,grant,urls=[row["candidate_racecard_page_url"]],
                transport=fetch,clock=clock)
            counts["racecard_capture_attempted"]+=1
            counts["racecard_capture_created"]+=first["captures_created"]
        except (PublicPageFetchError,ValueError,OSError) as e:
            counts["racecard_hold"]+=1
            blocking.append(str(e))
            if str(e)=="PUBLIC_PAGE_BLOCKED_OR_RATE_LIMITED_NO_RETRY":
                break
            continue
        # The odds page may exist while the 210/504 price set remains
        # unpublished. Preserve the source card regardless.
        try:
            second=capture_approved_public_pages(
                private,grant,urls=[row["candidate_odds_page_url"]],
                transport=fetch,clock=clock,odds_race_id=row["race_id"],
                odds_official_cutoff_at=row["public_close_at_utc"])
            counts["complete_odds_source_verified"]+=int(
                second["complete_real_race_odds_verified"])
            counts["private_odds_created_by_collector"]+=int(
                second["private_odds_originals_created"])
        except (PublicPageFetchError,EmbeddedOddsError,ValueError,OSError) as e:
            counts["odds_pending_or_hold"]+=1
            blocking.append(str(e))
            if str(e)=="PUBLIC_PAGE_BLOCKED_OR_RATE_LIMITED_NO_RETRY":
                break
    # The existing private adapter independently checks captured original
    # bytes/SHA, actual starters and each odds price. No retroactive forecast.
    stage=stage_private_captured_winticket(private)
    # Never include source URLs, rider IDs, names, scores or odds in stdout.
    return {
        "schema":SCHEMA,
        "date_jst":day,
        "source_day_schedule_race_count":index["published_ssr_race_count"],
        "future_7_or_9_source_linked_in_window":len(possible),
        "selected_in_this_cycle":len(chosen),
        "source_job_state":("SOURCE_ONLY_PARTIAL_OR_HOLD"
                            if blocking or stage.get("incomplete_races",0)>0
                            else "SOURCE_CAPTURED_OR_NOT_YET_NEEDED"),
        "capture_counts":dict(sorted(counts.items())),
        "private_partial_racecards_staged":
            stage["private_partial_racecards_staged"],
        "private_full_odds_races_staged":(
            counts["private_odds_created_by_collector"]+
            stage["full_odds_races_staged"]),
        "private_pending_or_incomplete":stage["incomplete_races"],
        "source_blocked_or_pending_count":len(blocking),
        "provider_machine_rights_independently_verified":False,
        "source_347_or_437_formal_gate_claimed":False,
        "pr71_four_models_run_here":False,
        "source_values_or_rider_names_publicly_logged":False,
        "public_repository_plaintext_written":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inbox",required=True)
    p.add_argument("--lookahead-minutes",type=int,default=90)
    p.add_argument("--max-races",type=int,default=16)
    args=p.parse_args(argv)
    try:
        report=owner_future_public_intake(
            args.inbox,lookahead_minutes=args.lookahead_minutes,
            max_races=args.max_races)
    except (ValueError,WinticketDayIndexError,PublicPageFetchError,
            EmbeddedOddsError,OSError,KeyError,TypeError):
        report={"schema":SCHEMA,"source_job_state":"SOURCE_UNAVAILABLE_HOLD",
                "model_forecast_saved":False,
                "provider_machine_rights_independently_verified":False}
        print(json.dumps(report,sort_keys=True,separators=(",",":")))
        return 2
    print(json.dumps(report,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
