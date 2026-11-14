"""Full-day exhibition A/B coverage ledger, grounded in the retained schedule.

This is NOT a source crawler and does not invent a 132-race manifest. The
caller supplies the independently admitted official schedule. Counts never
turn a missed cutoff or absent B into a hit/miss.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone, timedelta
import re

SCHEMA = "RACE_AI_BOAT_POST_EXHIBITION_AB_COVERAGE_V1"
RID = re.compile(r"(20[0-9]{6})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])\Z")


def _clock(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("BOAT_AB_COVERAGE_CLOCK_INVALID") from None


def count_schedule(schedule, research, *, now, artifact_saved_at=None):
    if not isinstance(schedule, list) or len(schedule) > 288 or not isinstance(research, dict):
        raise ValueError("BOAT_AB_COVERAGE_SCHEDULE_INVALID")
    if research.get("schema") != "RACE_AI_POST_EXHIBITION_AB_ENCRYPTED_ROUND_V1":
        raise ValueError("BOAT_AB_COVERAGE_RESEARCH_INVALID")
    clock = _clock(now)
    receipt = _clock(artifact_saved_at) if artifact_saved_at else None
    pairs = {r["race_id"]: r for r in research["pairs"]}
    holds = {r["race_id"]: r for r in research["holds"]}
    if len(pairs) != len(research["pairs"]) or len(holds) != len(research["holds"]) or set(pairs) & set(holds):
        raise ValueError("BOAT_AB_COVERAGE_DUPLICATE_RESEARCH")
    by_venue = {}
    seen = set()
    by_state = Counter()
    days = set()
    for row in schedule:
        if not isinstance(row, dict):
            raise ValueError("BOAT_AB_COVERAGE_ROW_INVALID")
        rid, value = row.get("race_id"), row.get("cutoff_at")
        m = RID.fullmatch(rid) if isinstance(rid, str) else None
        if m is None or rid in seen:
            raise ValueError("BOAT_AB_COVERAGE_RACE_ID_DUPLICATE")
        seen.add(rid)
        days.add(m[1])
        cutoff = _clock(value)
        if cutoff.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d") != m[1]:
            raise ValueError("BOAT_AB_COVERAGE_CUTOFF_DAY_INVALID")
        venue = m[2]
        item = by_venue.setdefault(venue, Counter())
        if rid in pairs:
            saved = receipt is not None and receipt < cutoff and _clock(pairs[rid]["generated_at"]) <= receipt
            status = "B_ENCRYPTED_READBACK_ELIGIBLE" if saved else (
                "B_PREPARED_AWAITING_PHYSICAL_SAVE" if receipt is None
                else "HOLD_B_PHYSICAL_SAVE_TOO_LATE")
        elif rid in holds:
            status = "HOLD_B_RESEARCH_FEATURES_OR_ORIGINAL"
        else:
            status = "HOLD_CUTOFF_PASSED_NO_B" if cutoff <= clock else "WAIT_POST_EXHIBITION_P1"
        item["scheduled"] += 1
        item[status] += 1
        by_state[status] += 1
    if len(days) > 1 or not set(pairs) <= seen or not set(holds) <= seen:
        raise ValueError("BOAT_AB_COVERAGE_SCHEDULE_RESEARCH_MISMATCH")
    counts = {venue: dict(sorted(values.items())) for venue, values in sorted(by_venue.items())}
    return dict(schema=SCHEMA,
                event_day_jst=next(iter(days)) if days else None,
                scheduled_races=len(seen),venues=len(by_venue),
                venue_counts=counts,
                status_counts=dict(sorted(by_state.items())),
                b_physically_saved_before_cutoff=by_state["B_ENCRYPTED_READBACK_ELIGIBLE"],
                b_prepared_not_yet_saved=by_state["B_PREPARED_AWAITING_PHYSICAL_SAVE"],
                scheduled_source_authenticated_by_caller_only=True,
                source_provider_requests=0,
                actual_results_used=False,production_promoted=False)
