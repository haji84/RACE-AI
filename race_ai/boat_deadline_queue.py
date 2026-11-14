"""Strict nationwide BOAT cutoff queue from *already verified* official schedules.

Pure, offline selection only. This module NEVER fetches a source, starts a
workflow, creates a forecast, changes existing A/B coefficients, or bets.
Every eligible race still requires its own independent pre-close artifact.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re

JST = timezone(timedelta(hours=9))
MIN_SAFE_SECONDS = 210
MAX_WINDOW_SECONDS = 15 * 60
TARGET_DUE_SECONDS = 10 * 60
RACE_ID = re.compile(r"^(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$")


def _instant(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("explicit timezone-aware ISO instant required")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        raise ValueError("missing timezone")
    return stamp


def select_due_races(schedule_rows: list[dict], as_of: str,
                     *, already_frozen: frozenset[str] = frozenset(),
                     max_items: int | None = None) -> dict:
    """Prefer T-15..T-10 entries, then explicitly labelled late input fallback.

    Input is verified schedule metadata, not a claimed real-time API. Strictly
    refuses duplicates, contradictory dates and post-as_of source captures.
    Statuses are explicit; missing data is never filled, nor is 'ready' proof
    of a saved forecast. The caller independently rechecks cutoff before
    every source fetch, scoring, and artifact creation.
    """
    clock = _instant(as_of)
    if max_items is not None and (type(max_items) is not int or max_items < 1):
        raise ValueError("max_items must be a positive integer or None")
    if not isinstance(schedule_rows, list) or len(schedule_rows) > 24 * 12:
        raise ValueError("bounded nationwide schedule list required")
    if not isinstance(already_frozen, frozenset) or not all(
            isinstance(x, str) and RACE_ID.fullmatch(x) for x in already_frozen):
        raise ValueError("frozen identifiers must be verified canonical IDs")
    seen = set()
    eligible, deferred, rejected = [], [], []
    for row in schedule_rows:
        if not isinstance(row, dict) or set(row) != {
                "race_id", "cutoff_at", "schedule_captured_at", "source_sha256"}:
            raise ValueError("exact official schedule evidence fields required")
        rid = row["race_id"]
        matched = RACE_ID.fullmatch(rid) if isinstance(rid, str) else None
        if matched is None or rid in seen:
            raise ValueError("invalid or duplicated race ID")
        seen.add(rid)
        cutoff = _instant(row["cutoff_at"])
        captured = _instant(row["schedule_captured_at"])
        if (cutoff.astimezone(JST).strftime("%Y%m%d") != matched[1]
                or cutoff.utcoffset() != timedelta(hours=9)
                or captured > clock or captured >= cutoff
                or not isinstance(row["source_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]) is None):
            raise ValueError("conflicting or unauthenticated schedule evidence")
        remaining = (cutoff-clock).total_seconds()
        record = {"race_id": rid, "cutoff_at": cutoff.isoformat(),
                  "schedule_captured_at": captured.isoformat(),
                  "source_sha256": row["source_sha256"]}
        if rid in already_frozen:
            rejected.append({**record, "reason": "ALREADY_FROZEN"})
        elif remaining <= MIN_SAFE_SECONDS:
            rejected.append({**record, "reason": "TOO_LATE_OR_UNSAFE"})
        elif remaining > MAX_WINDOW_SECONDS:
            deferred.append({**record, "reason": "NOT_IN_CAPTURE_WINDOW"})
        else:
            phase = "WINDOW" if remaining >= TARGET_DUE_SECONDS else "LATE_INPUT_FALLBACK"
            eligible.append({**record, "phase": phase, "reason": phase})
    key = lambda item: (item["cutoff_at"], item["race_id"][9:11], item["race_id"][12:14])
    eligible.sort(key=lambda item: (item["phase"] != "WINDOW", *key(item)))
    capacity = len(eligible) if max_items is None else max_items
    selected = eligible[:capacity]
    deferred += [{**r, "reason": "CAPACITY_DEFERRED"} for r in eligible[capacity:]]
    deferred.sort(key=key)
    rejected.sort(key=key)
    return {"schema": "RACE_AI_BOAT_NATIONWIDE_QUEUE_V1",
            "as_of": clock.isoformat(), "eligible": selected,
            "deferred": deferred, "rejected": rejected,
            "freeze_proven": False,
            "forecast_generated": False,
            "source_fetch_performed": False,
            "model_auto_promoted": False}
