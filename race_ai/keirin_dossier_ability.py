"""Measured finish profiles from the pinned public rider directory."""
from datetime import date
from hashlib import sha256
import json
import re

from .keirin_note_view import MAX_FILE, _pairs


DIRECTORY_SCHEMA = "RACE_AI_KEIRIN_PUBLIC_RIDER_DIRECTORY_V1"
SCOPE = "OBSERVED_FINISHES_ONLY"
RANKS = tuple(str(rank) for rank in range(1, 10))
WINDOWS = ("1_year", "4_months", "1_month")
AXES = (
    ("1_year", 1, "1年・1着"),
    ("1_year", 2, "1年・2着以内"),
    ("1_year", 3, "1年・3着以内"),
    ("4_months", 3, "4か月・3着以内"),
    ("4_months", 2, "4か月・2着以内"),
    ("4_months", 1, "4か月・1着"),
)


def _need(ok, reason):
    if not ok:
        raise ValueError("RADAR_" + reason)


def _date(value):
    _need(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value),
          "DATE")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("RADAR_DATE") from None


def _finish_counts(period, earliest, latest):
    fields = {"observed_count", "finish_counts", "first_observed_day", "latest_observed_day"}
    _need(type(period) is dict and fields <= period.keys(), "FINISH_COUNTS")
    counts, total = period.get("finish_counts"), period.get("observed_count")
    _need(type(counts) is dict and counts.keys() == set(RANKS) and type(total) is int and
          all(type(count) is int and count >= 0 for count in counts.values()) and
          sum(counts.values()) == total, "FINISH_COUNTS")
    first, last = period.get("first_observed_day"), period.get("latest_observed_day")
    if total:
        _need(earliest <= _date(first) <= _date(last) <= latest, "WINDOW_DATES")
    else:
        _need(first is None and last is None, "WINDOW_DATES")
    return counts


def _project_rider(rider, earliest, latest, as_of):
    history = rider.get("history")
    enclosing_counts = _finish_counts(history, earliest, latest)
    if "history_windows" not in rider:
        return None
    windows = rider["history_windows"]
    _need(type(windows) is dict and windows.keys() == set(WINDOWS), "WINDOW_SET")
    counts_by_period = {}
    enclosing_start = date.min
    enclosing = history
    for name in WINDOWS:
        window = windows[name]
        _need(type(window) is dict, "WINDOW_DATES")
        start = _date(window.get("start_day_inclusive"))
        _need(enclosing_start < start < as_of, "WINDOW_DATES")
        counts = _finish_counts(window, max(earliest, start), latest)
        _need(all(counts[rank] <= enclosing_counts[rank] for rank in RANKS),
              "WINDOW_CONTAINMENT")
        parent_first, parent_last = enclosing["first_observed_day"], enclosing["latest_observed_day"]
        if window["observed_count"]:
            _need(window["latest_observed_day"] == parent_last and
                  window["first_observed_day"] >= parent_first, "WINDOW_CONTAINMENT")
            if _date(parent_first) >= start:
                _need(counts == enclosing_counts and window["first_observed_day"] == parent_first,
                      "WINDOW_CONTAINMENT")
        else:
            _need(parent_last is None or _date(parent_last) < start, "WINDOW_CONTAINMENT")
        counts_by_period[name] = counts
        enclosing, enclosing_counts, enclosing_start = window, counts, start

    if not windows["1_year"]["observed_count"]:
        return None
    axes = []
    for name, rank, label in AXES:
        window = windows[name]
        denominator = window["observed_count"]
        counts = counts_by_period[name]
        axes.append({
            "period": name,
            "rank_within": rank,
            "label": label,
            "numerator": sum(counts[key] for key in RANKS[:rank]) if denominator else None,
            "denominator": denominator,
            "start_day_inclusive": window["start_day_inclusive"],
            "first_observed_day": window["first_observed_day"],
            "latest_observed_day": window["latest_observed_day"],
        })
    return {"scope": SCOPE, "history_end_day": latest.isoformat(), "axes": axes}


def project_verified_results_radars(raw, *, expected_sha256):
    """Read exact archived aggregate bytes and return one measured profile per registration.

    Each rate describes numerical finishes within a published historical window.
    A missing sample has no measured rate. The result is independent of forecasts.
    """
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_FILE and
          type(expected_sha256) is str and sha256(raw).hexdigest() == expected_sha256,
          "DIRECTORY_SHA")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                              parse_constant=lambda _: _need(False, "DIRECTORY_JSON"))
    except (ValueError, UnicodeError):
        raise ValueError("RADAR_DIRECTORY_JSON") from None
    _need(type(document) is dict and document.get("schema") == DIRECTORY_SCHEMA and
          type(document.get("riders")) is list, "DIRECTORY_SCHEMA")
    earliest = _date(document.get("history_start_day"))
    latest = _date(document.get("history_end_day"))
    as_of = _date(document.get("as_of"))
    _need(earliest <= latest <= as_of, "WINDOW_DATES")
    profiles = {}
    for rider in document["riders"]:
        registration = rider.get("registration") if type(rider) is dict else None
        _need(type(registration) is str and re.fullmatch(r"[0-9]{6}", registration) and
              registration != "000000" and registration not in profiles, "REGISTRATION")
        profiles[registration] = _project_rider(rider, earliest, latest, as_of)
    return profiles
