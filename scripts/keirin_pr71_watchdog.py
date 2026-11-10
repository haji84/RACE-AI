"""Fail-closed, metadata-only PR71 schedule fallback decision.

Only the scoped GitHub Actions workflow-runs list is accepted as input.
No providers, race data, secrets or state archives are accessed here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import argparse
import json
import sys

ACTIVE = frozenset(("requested", "queued", "pending", "waiting", "in_progress"))
TRUSTED_EVENTS = frozenset(("schedule", "workflow_dispatch"))
# New primary is every five minutes; do not hide a stalled producer for 26 min.
# Keep the pre-existing half-hour watchdog trigger unchanged.
RECENT_WINDOW = timedelta(minutes=12)
MAX_FUTURE_SKEW = timedelta(minutes=3)
# Metadata audit only, not an SLA or proof that a race/forecast ran.
SCHEDULE_AUDIT_MINUTES = 35
SCHEDULE_GRACE_MINUTES = 3
PRODUCER_CRON_MINUTES = frozenset(range(3, 60, 5))


def nominal_schedule_tick_count(now):
    """Count UTC 5-minute slots old enough to rule out only brief dispatch lag."""
    begin = now - timedelta(minutes=SCHEDULE_AUDIT_MINUTES)
    end = now - timedelta(minutes=SCHEDULE_GRACE_MINUTES)
    minute = begin.replace(second=0, microsecond=0)
    if minute < begin:
        minute += timedelta(minutes=1)
    ticks = 0
    while minute <= end:
        ticks += minute.minute in PRODUCER_CRON_MINUTES
        minute += timedelta(minutes=1)
    return ticks


class WatchdogError(ValueError):
    pass


def utc(value):
    if not isinstance(value, str):
        raise WatchdogError("RUN_TIMESTAMP_MISSING")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WatchdogError("RUN_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise WatchdogError("RUN_TIMESTAMP_NOT_AWARE")
    return dt.astimezone(timezone.utc)


def inspect_workflow_runs(payload, *, now):
    """Return decision + counts only. Never infer that CI was live production."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise WatchdogError("CURRENT_TIME_MUST_BE_AWARE")
    now = now.astimezone(timezone.utc)
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise WatchdogError("WORKFLOW_RUN_LIST_REQUIRED")
    runs = payload["workflow_runs"]
    total = payload.get("total_count")
    if type(total) is not int or total < 0 or len(runs) > 100:
        raise WatchdogError("WORKFLOW_RUN_LIST_BOUNDS")
    if total > 0 and not runs:
        raise WatchdogError("WORKFLOW_RUN_LIST_UNTRUSTWORTHY")
    fresh = 0
    active = 0
    considered = 0
    observed_schedule = 0
    observed_dispatch = 0
    observation_start = now - timedelta(minutes=SCHEDULE_AUDIT_MINUTES)
    observation_end = now - timedelta(minutes=SCHEDULE_GRACE_MINUTES)
    for run in runs:
        if not isinstance(run, dict):
            raise WatchdogError("WORKFLOW_RUN_INVALID")
        event = run.get("event")
        if event not in TRUSTED_EVENTS or run.get("head_branch") != "main":
            continue
        if type(run.get("id")) is not int or run["id"] < 1:
            raise WatchdogError("RUN_ID_INVALID")
        status = run.get("status")
        if status not in ACTIVE | {"completed"}:
            raise WatchdogError("RUN_STATUS_UNKNOWN")
        stamp = utc(run.get("created_at"))
        if stamp > now + MAX_FUTURE_SKEW:
            raise WatchdogError("RUN_TIMESTAMP_IN_FUTURE")
        considered += 1
        age = now - stamp
        if observation_start <= stamp <= observation_end:
            if event == "schedule":
                observed_schedule += 1
            else:
                observed_dispatch += 1
        if status in ACTIVE:
            active += 1
        if age <= RECENT_WINDOW:
            fresh += 1
    if active:
        state = "HOLD_ACTIVE_TRUSTED_PRODUCER"
    elif fresh:
        state = "SKIP_RECENT_TRUSTED_PRODUCER"
    else:
        state = "DISPATCH_MISSING_TRUSTED_PRODUCER"
    # GitHub's two 30-item API result pages are not exhaustive if the
    # combined total exceeds returned rows. Do not present false tick gaps.
    history_complete = total == len(runs)
    nominal_ticks = nominal_schedule_tick_count(now)
    observed_gap = (max(0, nominal_ticks - observed_schedule)
                    if history_complete else None)
    return {
        "schema": "RACE_AI_KEIRIN_PR71_RECURRING_WATCHDOG_V1",
        "source_free_schedule_audit": {
            "lookback_minutes": SCHEDULE_AUDIT_MINUTES,
            "grace_minutes": SCHEDULE_GRACE_MINUTES,
            "nominal_five_minute_ticks": nominal_ticks,
            "schedule_runs_observed": observed_schedule,
            "manual_dispatch_runs_observed": observed_dispatch,
            "nominal_ticks_without_observed_event": observed_gap,
            "history_page_complete": history_complete,
            "actual_start_or_forecast_proven": False,
            "scheduler_root_cause_proven": False,
        },
        "decision": state,
        "trusted_main_producer_runs_examined": considered,
        "recent_main_producer_runs": fresh,
        "active_main_producer_runs": active,
        "real_forecast_claimed": False,
        "schedule_success_claimed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-json", required=True)
    args = parser.parse_args(argv)
    try:
        from pathlib import Path
        path = Path(args.runs_json)
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
            raise WatchdogError("RUN_LIST_INPUT_UNSAFE")
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = inspect_workflow_runs(payload, now=datetime.now(timezone.utc))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, UnicodeError):
        print(json.dumps({
            "schema": "RACE_AI_KEIRIN_PR71_RECURRING_WATCHDOG_V1",
            "decision": "HOLD_INVALID_RUN_METADATA",
            "real_forecast_claimed": False,
            "schedule_success_claimed": False,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
