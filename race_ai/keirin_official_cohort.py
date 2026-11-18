"""Cumulative registration from intact official day revisions, without I/O.

Every individual source is reparsed before its genuine race IDs enter the
union. The cumulative registry is labelled as a union; no raw page, source
hash or source race count is rewritten to pretend one page contained it.
The caller still owns the trusted HTTPS/history acquisition boundary.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256

from . import keirin_dynamic_nationwide_registry as dynamic
from . import keirin_official_public_source as official


SCOPE = "UNION_OF_VERIFIED_OFFICIAL_DAY_REVISIONS"


class OfficialCohortError(ValueError):
    pass


def _need(ok, reason):
    if not ok:
        raise OfficialCohortError(reason)


def _when(value):
    # Called only on times already checked by the official receipt parser.
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_registry(schedule):
    """Build one existing dynamic registry from its actual, unchanged sources."""
    _need(official.reparse_day_schedule(schedule),
          "OFFICIAL_SCHEDULE_BYTES_OR_IDENTITY_UNVERIFIED")
    snapshots = schedule["snapshots"]
    by_sha = {source["source_sha256"]: source for source in snapshots}

    def verify_venue(block):
        source = by_sha.get(block["source_bytes_sha256"])
        return (source is not None and source["url"] == block["source_url"] and
                sha256(source["raw_bytes"]).hexdigest() == block["source_bytes_sha256"] and
                block in schedule["venue_snapshots"])

    def verify_day(day, venues, sources):
        return (day == schedule["day_jst"] and
                venues == sorted(schedule["expected_venue_codes"]) and
                {source["code"] for source in sources} == set(venues) and
                official.reparse_day_schedule(schedule))

    observed = max(_when(source["observed_at"]) for source in snapshots).isoformat()
    return dynamic.create_day(
        day_jst=schedule["day_jst"], registered_at=observed,
        venue_snapshots=schedule["venue_snapshots"],
        expected_venue_codes=schedule["expected_venue_codes"],
        independently_verify_venue_snapshot=verify_venue,
        independently_verify_whole_day=verify_day)


def build_registered_cohort(schedules):
    """Retain every genuinely observed race, while identifying the last roster.

    ``latest_schedule`` is the last actual revision supplied by the caller;
    it is never synthesized. For each race, ``races_by_id`` retains the actual
    row with the newest observation time (later list entry breaks ties).
    Removed races remain registered but are not thereby cleared for scoring.
    All returned mutable objects are detached from the input receipts.
    """
    _need(type(schedules) is list and bool(schedules),
          "OFFICIAL_COHORT_REVISIONS_REQUIRED")
    individual, references, sources = [], [], []
    races_by_id, registered_rows = {}, {}
    day = None
    for index, schedule in enumerate(schedules):
        registry = build_registry(schedule)
        _need(day is None or registry["day_jst"] == day,
              "OFFICIAL_COHORT_DIFFERENT_DAYS")
        day = registry["day_jst"]
        individual.append(registry)
        references.append({
            "revision_index": index,
            "registry_sha256": registry["registry_sha256"],
            "registered_at": registry["registered_at"],
            "race_ids": [row["race_id"] for row in registry["races"]],
            "source_receipts": [{
                "url": source["url"], "source_sha256": source["source_sha256"],
                "observed_at": source["observed_at"]} for source in schedule["snapshots"]],
        })
        sources.extend(dict(deepcopy(source), revision_index=index,
                            source_registry_sha256=registry["registry_sha256"])
                       for source in registry["source_venues"])
        normalized = {row["race_id"]: row for row in registry["races"]}
        for row in schedule["races"]:
            rid = row["race_id"]
            previous = races_by_id.get(rid)
            if previous is None or _when(row["source_observed_at"]) >= _when(previous["source_observed_at"]):
                races_by_id[rid] = deepcopy(row)
                registered_rows[rid] = deepcopy(normalized[rid])

    registry = deepcopy(individual[-1])
    registry.pop("registry_sha256")
    codes = sorted({row["venue_code"] for row in races_by_id.values()})
    registry.update(
        registered_at=max(_when(item["registered_at"]) for item in individual).isoformat(),
        captured_venue_count=len(codes), captured_race_count=len(races_by_id),
        expected_venue_codes=codes,
        races=[registered_rows[rid] for rid in sorted(registered_rows)],
        source_venues=sources,
        registered_cohort_scope=SCOPE,
        source_venues_scope="PER_VERIFIED_OFFICIAL_DAY_REVISION",
        verified_official_day_revisions=references,
    )
    registry["registry_sha256"] = dynamic.digest(registry)
    dynamic.checked_day(registry)
    active = {row["race_id"] for row in schedules[-1]["races"]}
    return {
        "registry": registry,
        "races_by_id": {rid: races_by_id[rid] for rid in sorted(races_by_id)},
        "latest_schedule": deepcopy(schedules[-1]),
        "active_race_ids": sorted(active),
        "removed_race_ids": sorted(set(races_by_id) - active),
    }
