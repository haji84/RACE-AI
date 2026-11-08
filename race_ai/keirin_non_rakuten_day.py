"""Offline race-day manifest from owner-saved NON-Rakuten race listings.

This does not scrape a website or pretend that all races/official cutoffs were
found. The manifest must be transcribed from already legally obtained material,
with provenance, by the owner or an approved external delivery.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re

from .keirin_non_rakuten_sources import is_rakuten_url, source_id

SCHEMA = "RACE_AI_KEIRIN_NON_RAKUTEN_OWNER_DAY_ROSTER_V1"


class OwnerDayRosterError(ValueError):
    pass


def _need(ok, code):
    if not ok:
        raise OwnerDayRosterError(code)


def read_saved_day_roster(path, expected_day):
    """Read bounded local JSON only; verify race_id and venue-row coverage."""
    file = Path(path).expanduser()
    _need(file.is_absolute() and file.is_file() and not file.is_symlink() and
          0 < file.stat().st_size <= 200_000, "LOCAL_DAY_ROSTER_REQUIRED")
    try:
        raw = file.read_bytes()
        obj = json.loads(raw)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise OwnerDayRosterError("DAY_ROSTER_NOT_VALID_JSON") from exc
    _need(type(obj) is dict and set(obj) == {
        "schema", "event_date_jst", "source_url",
        "source_sha256", "captured_at", "races"
    } and obj["schema"] == SCHEMA and obj["event_date_jst"] == expected_day,
          "DAY_ROSTER_BINDING_MISMATCH")
    try:
        day = date.fromisoformat(expected_day)
        captured = datetime.fromisoformat(obj["captured_at"])
        _need(captured.utcoffset() is not None,
              "CAPTURE_TIMEZONE_REQUIRED")
    except (TypeError, ValueError):
        raise OwnerDayRosterError("DAY_OR_CAPTURE_TIME_INVALID") from None
    _need(not is_rakuten_url(obj["source_url"]) and
          source_id(obj["source_url"]) is not None,
          "NON_RAKUTEN_KNOWN_SOURCE_REQUIRED")
    _need(type(obj["source_sha256"]) is str and
          re.fullmatch(r"[0-9a-f]{64}", obj["source_sha256"]) is not None,
          "SOURCE_HASH_FORMAT_INVALID")
    _need(type(obj["races"]) is list and 1 <= len(obj["races"]) <= 200,
          "RACE_ROSTER_EMPTY_OR_TOO_BIG")
    seen = set()
    by_venue = {}
    rows = []
    for item in obj["races"]:
        _need(type(item) is dict and set(item) == {
            "race_id", "venue_code", "race_no"
        }, "RACE_ROW_INVALID")
        venue, no = item["venue_code"], item["race_no"]
        _need(type(venue) is int and type(no) is int and
              1 <= venue <= 99 and 1 <= no <= 12,
              "VENUE_RACE_CODE_INVALID")
        rid = "%s%02d%02d" % (day.strftime("%Y%m%d"), venue, no)
        _need(item["race_id"] == rid and rid not in seen,
              "RACE_ID_DUPLICATE_OR_DATE_MISMATCH")
        seen.add(rid)
        by_venue.setdefault(venue, set()).add(no)
        rows.append({"race_id": rid, "event_date_jst": expected_day,
                     "venue_code": venue, "race_no": no})
    _need(all(nums == set(range(1, max(nums)+1)) for nums in by_venue.values()),
          "GAPPED_VENUE_ROSTER_NOT_ACCEPTED")
    return {
        "schema": "RACE_AI_KEIRIN_DATED_DISCOVERY_V1",
        "source_url": obj["source_url"],
        "source_sha256": obj["source_sha256"],
        "event_date_jst": expected_day,
        "races": sorted(rows, key=lambda x:(x["venue_code"],x["race_no"])),
        "race_count": len(rows),
        "venue_count": len(by_venue),
        "venue_race_counts": {str(k):len(v) for k,v in sorted(by_venue.items())},
        "complete_national_coverage_verified": False,
        "official_cutoffs_verified": False,
        "model_features_available": False,
        "source_use_rights_verified": False,
        "provenance_self_reported": True,
        "local_manifest_sha256": sha256(raw).hexdigest(),
    }
