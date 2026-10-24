"""Conservative, zero-billing free-tier capacity estimate for RACE-AI.

No Cloudflare API, source fetch or deployed configuration is changed.
Numbers are documented 2026-10 Cloudflare Workers Free and D1 ceilings.
Conservative soft caps reserve 40 percent of account-wide capacity.
Counters for OTHER apps must come from authenticated account observability;
otherwise feasibility is unverified, not a green light to deploy.

This budgets all 3T quotes as ONE JSON row per race per update, NOT
one Cloudflare write for each possible trifecta combination.  An indexed
odds_latest row is conservatively counted as TWO row writes. In reality
other indexes, quotas, SQL, CPU and storage still require monitoring.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math

FREE_WORKER_REQUESTS_PER_DAY = 100_000
FREE_D1_ROWS_WRITTEN_PER_DAY = 100_000
FREE_D1_ROWS_READ_PER_DAY = 5_000_000
FREE_D1_STORAGE_BYTES = 5_000_000_000
SOFT_CAP_RATIO = 0.60
CONTRACT_VERSION = "RACE_AI_FREE_TIER_CAPACITY_V1"


@dataclass(frozen=True)
class OtherAppUsage:
    """None means not independently measured; do not convert to zero."""
    worker_requests: int | None = None
    d1_rows_written: int | None = None
    d1_rows_read: int | None = None


def _whole(name: str, value: object, *, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(name + " requires bounded nonnegative integer")
    return value


def estimate_free_capacity(
    *,
    races_per_day: int,
    refresh_window_minutes: int = 60,
    quote_update_seconds: int = 60,
    active_users_per_day: int = 0,
    minutes_open_per_user: int = 60,
    usage: OtherAppUsage = OtherAppUsage(),
    source_rights_verified: bool = False,
    provider_requests_allowed_per_day: int | None = None,
    bytes_per_race_snapshot: int = 65_536,
) -> dict:
    races = _whole("races_per_day", races_per_day, maximum=5_000)
    period = _whole("refresh_window_minutes", refresh_window_minutes, maximum=1_440)
    if not 1 <= period <= 1_440:
        raise ValueError("refresh window must be positive")
    update = _whole("quote_update_seconds", quote_update_seconds, maximum=600)
    if not 60 <= update <= 600 or update % 60:
        raise ValueError("only whole-minute rates >= 60 seconds supported")
    users = _whole("active_users_per_day", active_users_per_day, maximum=1_000_000)
    viewed = _whole("minutes_open_per_user", minutes_open_per_user, maximum=1_440)
    if not isinstance(usage, OtherAppUsage):
        raise ValueError("account usage must be an OtherAppUsage record")
    if type(source_rights_verified) is not bool:
        raise ValueError("source rights verification must be boolean")
    payload = _whole("bytes_per_race_snapshot", bytes_per_race_snapshot, maximum=2_000_000)

    estimates_per_race = math.ceil(period * 60 / update)
    upstream_attempts = races * estimates_per_race
    user_polls = users * math.ceil(viewed / (update / 60))
    # One worker call for each authorized ingest, plus each live user read.
    # Scheduling overhead/extra APIs are NOT counted here: reserve margin.
    request_projection = upstream_attempts + user_polls
    write_projection = upstream_attempts * 2
    read_projection = user_polls + upstream_attempts * 2
    latest_bytes = races * payload

    if provider_requests_allowed_per_day is not None:
        allowed = _whole(
            "provider_requests_allowed_per_day",
            provider_requests_allowed_per_day, maximum=50_000_000
        )
    else:
        allowed = None
    observed = {
        "worker_requests": usage.worker_requests,
        "d1_rows_written": usage.d1_rows_written,
        "d1_rows_read": usage.d1_rows_read,
    }
    limits = {
        "worker_requests": FREE_WORKER_REQUESTS_PER_DAY,
        "d1_rows_written": FREE_D1_ROWS_WRITTEN_PER_DAY,
        "d1_rows_read": FREE_D1_ROWS_READ_PER_DAY,
    }
    projected = {
        "worker_requests": request_projection,
        "d1_rows_written": write_projection,
        "d1_rows_read": read_projection,
    }
    headroom = {}
    for name, limit in limits.items():
        used = observed[name]
        if used is not None:
            _whole("other apps " + name, used, maximum=100_000_000_000)
        headroom[name] = (
            math.floor(limit * SOFT_CAP_RATIO) - used - projected[name]
            if used is not None else None
        )
    warnings = []
    if not source_rights_verified:
        warnings.append("UPSTREAM_SOURCE_PURPOSE_AND_RATE_UNVERIFIED")
    if allowed is None:
        warnings.append("UPSTREAM_REQUEST_LIMIT_UNKNOWN")
    elif upstream_attempts > allowed:
        warnings.append("UPSTREAM_DAILY_REQUEST_LIMIT_EXCEEDED")
    if any(x is None for x in headroom.values()):
        warnings.append("SHARED_CLOUDFLARE_ACCOUNT_USAGE_UNKNOWN")
    for name, remaining in headroom.items():
        if remaining is not None and remaining < 0:
            warnings.append("CLOUDFLARE_SOFT_CAP_EXCEEDED:" + name)
    if latest_bytes > math.floor(FREE_D1_STORAGE_BYTES * SOFT_CAP_RATIO):
        warnings.append("D1_STORAGE_SOFT_CAP_EXCEEDED")
    return {
        "schema": CONTRACT_VERSION,
        "scenario_only": True,
        "free_cost_guaranteed": False,
        "is_admissible_to_start_paid_or_provider_actions": False,
        "configuration": {
            "races_per_day": races,
            "refresh_window_minutes": period,
            "quote_update_seconds": update,
            "active_users_per_day": users,
            "minutes_open_per_user": viewed,
        },
        "projected": {
            **projected,
            "upstream_requests": upstream_attempts,
            "viewer_api_requests": user_polls,
            "latest_odds_storage_bytes": latest_bytes,
        },
        "soft_limits": {
            key: math.floor(value * SOFT_CAP_RATIO) for key, value in limits.items()
        },
        "other_apps_actual_usage": asdict(usage),
        "soft_headroom_after_other_apps": headroom,
        "provider_daily_limit_verified": allowed,
        "warnings": warnings,
        "account_budget_check": "HOLD" if warnings else "PASS_ESTIMATE_ONLY",
        "forecast_model_cpu_assumed_on_cloudflare": False,
        "still_requires_real_cpu_and_d1_metrics": True,
    }
