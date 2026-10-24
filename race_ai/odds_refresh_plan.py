"""Offline bounded planning for per-race all-trifecta odds refreshes.

The plan makes no network calls and cannot grant rights. A signed reviewer
policy alone is NOT a legal determination that automated acquisition is
authorized. The caller must supply a durable counter/last-attempt ledger;
otherwise the planner cannot prove it stayed within daily provider limits.

Designed for a once-per-minute trigger, not a promise that every race and
every quote will update each minute. Never feeds odds into predictions.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from .comprehensive_four_sport_models import moment
from .permissioned_source_delivery import PermissionPolicy, SourceDeliveryError
from .boat_official_3t_odds_adapter import event_from_url

SCHEMA = "RACE_AI_ODDS_REFRESH_PLAN_V1"


def _when(value):
    try:
        return moment(value)
    except (TypeError, ValueError) as exc:
        raise SourceDeliveryError("refresh timestamp not timezone aware") from exc


def plan_one_minute(races, *, now, policy=None, prior_daily_calls=None,
                    minute_limit=0, daily_limit=0, window_minutes=60):
    """Output a deterministic list of due requests, without performing any.

    Missing or untrusted counters fail closed. Limits are proposed technical
    budgets, not rights-holder-granted polling frequencies.
    """
    clock=_when(now)
    if (type(minute_limit) is not int or type(daily_limit) is not int or
        not 0<=minute_limit<=20 or not 0<=daily_limit<=100000 or
        type(window_minutes) is not int or not 1<=window_minutes<=180):
        raise SourceDeliveryError("invalid bounded odds-refresh plan")
    if not isinstance(prior_daily_calls,int) or prior_daily_calls<0:
        # Resetting in-memory call counters every Cron run is not acceptable.
        raise SourceDeliveryError("durable daily provider request counter required")
    if not isinstance(races,list) or len(races)>600:
        raise SourceDeliveryError("bounded race schedule required")
    if policy is not None and not isinstance(policy,PermissionPolicy):
        raise SourceDeliveryError("authenticated provider policy required")
    seen=set()
    result=[]
    for row in races:
        if not isinstance(row,dict) or set(row)!={
            "race_id","source_url","source_rights_ref","cutoff_at",
            "cutoff_verified","last_attempt_at","blocked_until",
        }:
            raise SourceDeliveryError("odds planner race schema incomplete")
        day,venue,rno=event_from_url(row["source_url"])
        if row["race_id"]!=f"{day.replace('-','')}-{venue}-{rno:02d}" or row["race_id"] in seen:
            raise SourceDeliveryError("duplicate or inconsistent odds race identity")
        seen.add(row["race_id"])
        cutoff=_when(row["cutoff_at"])
        if cutoff.astimezone(timezone(timedelta(hours=9))).date().isoformat()!=day:
            raise SourceDeliveryError("official cutoff date does not match race")
        if row["cutoff_verified"] is not True:
            status="OFFICIAL_CUTOFF_UNVERIFIED"
        elif cutoff<=clock:
            status="CLOSED"
        elif cutoff-clock>timedelta(minutes=window_minutes):
            status="OUTSIDE_REFRESH_WINDOW"
        elif policy is None or not all(policy.authorize(
                row["source_url"],row["source_rights_ref"],purpose)
                for purpose in ("collection","analysis","private_storage",
                                "private_derived","odds_display")):
            status="PROVIDER_RIGHTS_UNVERIFIED"
        elif row["blocked_until"] is not None and _when(row["blocked_until"])>clock:
            status="PROVIDER_BLOCKED_OR_BACKOFF"
        elif row["last_attempt_at"] is not None and (
             clock-_when(row["last_attempt_at"])<timedelta(seconds=60)):
            status="COOLDOWN_NOT_DUE"
        else:
            status="ELIGIBLE_FOR_BOUNDED_FETCH"
        result.append({"race_id":row["race_id"],"source_url":row["source_url"],
                       "cutoff_at":row["cutoff_at"],"status":status,
                       "request_selected":False})
    remaining=min(minute_limit,max(0,daily_limit-prior_daily_calls))
    eligible=sorted((r for r in result if r["status"]=="ELIGIBLE_FOR_BOUNDED_FETCH"),
                    key=lambda r:(_when(r["cutoff_at"]),r["race_id"]))
    for item in eligible[:remaining]:
        item["request_selected"]=True
        item["status"]="PLANNED_NOT_EXECUTED"
    for item in eligible[remaining:]:
        item["status"]="CAPACITY_OR_DAILY_QUOTA_UNAVAILABLE"
    return {
        "schema":SCHEMA,
        "as_of":now,
        "requests_selected":sum(r["request_selected"] for r in result),
        "daily_calls_before":prior_daily_calls,
        "daily_budget_remaining_reported":max(0,daily_limit-prior_daily_calls),
        "minute_budget":minute_limit,"daily_budget":daily_limit,
        "official_quote_provider_access_not_executed":True,
        "external_permission_not_proven_by_planner":True,
        "races":sorted(result,key=lambda x:(_when(x["cutoff_at"]),x["race_id"])),
    }
