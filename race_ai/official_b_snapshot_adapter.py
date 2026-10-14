"""Adapt an already acquired, extracted official B program to the day snapshot schema.

No network activity or publishing is performed here. This intentionally does
not infer names, motor numbers or display measurements from unknown fields.
The caller must supply independently validated motor allocation rows.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date
import hashlib
from pathlib import Path

from .core import SourceError, parse_b


def normalize_b_snapshot(raw: bytes, *, day: date, source_url: str,
                         observed_at: str, motors: dict | None = None) -> dict:
    """Construct race identities from official B; fail closed on absent motor data."""
    records = parse_b(raw, day.isoformat())
    if not source_url.startswith("https://"):
        raise SourceError("source must be HTTPS")
    grouped = defaultdict(lambda: defaultdict(list))
    for row in records:
        rid = row["race_id"]
        venue = rid[9:11]
        grouped[venue][rid].append(row)
    venues = []
    for venue, races in sorted(grouped.items()):
        items = []
        for rid, rows in sorted(races.items()):
            boats = []
            for row in sorted(rows, key=lambda item: item["lane"]):
                key = (rid, row["lane"])
                motor = motors.get(key) if motors else None
                if not isinstance(motor, int) or not 1 <= motor <= 999:
                    raise SourceError("motor allocation unavailable; cannot publish incomplete race")
                boats.append({"lane": row["lane"],
                              "racer_registration_id": row["racer_id"],
                              "motor_no": motor,
                              "name": None,
                              "average_st": None,
                              "display_time": None,
                              "preview_course": None})
            items.append({"race_id": rid, "boats": boats, "closed_at": None,
                          "preview_available": False})
        venues.append({"venue": venue, "races": items})
    return {"date_jst": day.isoformat(), "source_url": source_url,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "first_observed_at": observed_at, "venues": venues,
            "races": sum(len(v["races"]) for v in venues),
            "complete_six_boat_races": sum(len(r["boats"]) == 6 for v in venues for r in v["races"])}


def normalize_b_file(path: Path, *, day: date, source_url: str,
                     observed_at: str, motors: dict | None = None) -> dict:
    return normalize_b_snapshot(path.read_bytes(), day=day, source_url=source_url,
                                observed_at=observed_at, motors=motors)
