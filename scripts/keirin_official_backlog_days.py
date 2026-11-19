"""Bounded result-day rotation from existing Git history directory names.

Always consider current/previous JST days and at most one older archived day.
This helper reads only Git metadata. It never fetches provider data, creates a
state branch, generates a forecast, or rewrites stored originals/results.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import argparse
import json
import re
import sys

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_run_history as official_history

JST = timezone(timedelta(hours=9))


class BacklogDaysError(ValueError):
    pass


def _need(condition, code):
    if not condition:
        raise BacklogDaysError(code)


def _day(value):
    _need(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value),
          "BACKLOG_DAY_INVALID")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise BacklogDaysError("BACKLOG_DAY_INVALID") from None
    _need(parsed.isoformat() == value, "BACKLOG_DAY_INVALID")
    return parsed


def select_days(now: datetime, known_days: list[str]) -> list[str]:
    """Use a UTC ten-minute slot to visit every existing older day in turn."""
    _need(isinstance(now, datetime) and now.utcoffset() is not None,
          "BACKLOG_AWARE_CLOCK_REQUIRED")
    _need(type(known_days) is list, "BACKLOG_KNOWN_DAY_LIST_REQUIRED")
    today = now.astimezone(JST).date()
    yesterday = today - timedelta(days=1)
    parsed = {_day(day) for day in known_days}
    _need(all(day <= today for day in parsed), "BACKLOG_FUTURE_DAY_REJECTED")
    older = sorted(day for day in parsed if day < yesterday)
    selected = [today.isoformat(), yesterday.isoformat()]
    if older:
        slot = int(now.astimezone(timezone.utc).timestamp() // 600)
        selected.append(older[slot % len(older)].isoformat())
    return selected


def discover_days(repo, *, synthetic_local=False) -> list[str]:
    """Discover real day directories in the already existing trusted branch.

    synthetic_local is fixture-only and is deliberately not a CLI option.
    A missing state branch is a stop condition; absent data roots are empty.
    """
    repo = archive._remote(repo, synthetic_local=synthetic_local)
    head = archive._refresh(repo)
    days = set()
    for root in (archive.ROOT, official_history.ROOT):
        prefix = root + "/"
        _, names = archive._cmd(repo, "--no-replace-objects", "ls-tree", "-d",
                                "--name-only", head, "--", prefix)
        for path in names.splitlines():
            _need(path.startswith(prefix), "BACKLOG_HISTORY_DIRECTORY_MISMATCH")
            name = path[len(prefix):]
            _day(name)
            days.add(name)
    return sorted(days)


def main(argv=None, *, clock=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    clock = clock or (lambda: datetime.now(timezone.utc))
    try:
        days = select_days(clock(), discover_days(args.repo))
        print("\n".join(days))
        return 0
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        reason = str(exc)
        if not re.fullmatch(r"[A-Z0-9_]{1,100}", reason):
            reason = "BACKLOG_HISTORY_OR_CLOCK_UNVERIFIED"
        print(json.dumps({"state": "HOLD_OFFICIAL_BACKLOG_DAYS_UNVERIFIED",
                          "reason": reason}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
