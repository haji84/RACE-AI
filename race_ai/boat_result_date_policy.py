"""Strict JST race-day gate for independently frozen, post-close result audits.

Historic result verification is allowed, but future races and malformed
or timezone-naive inputs must fail closed. This never authorizes retroactive
forecasts or waives the external original-receipt and official-identity checks.
"""
from datetime import date, datetime, timedelta, timezone
import re

JST = timezone(timedelta(hours=9))


def is_past_or_current_result_day(race_day: str, observed_at: datetime) -> bool:
    """Return whether the official 8-digit race date is not after JST today."""
    if not isinstance(race_day, str) or not re.fullmatch(r"\d{8}", race_day):
        raise ValueError("8-digit official race day required")
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("timezone-aware observation clock required")
    try:
        racedate = date(int(race_day[0:4]), int(race_day[4:6]), int(race_day[6:8]))
    except ValueError as exc:
        raise ValueError("invalid official race day") from exc
    return racedate <= observed_at.astimezone(JST).date()
