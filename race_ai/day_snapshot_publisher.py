"""Publish a licensed normalized daily snapshot without leaking stale data.

This command never fetches third-party sources. A separately approved ingestion
worker must supply a normalized JSON document and verified permission evidence.
No assertion of permission is inferred from a command-line switch alone.
"""
from __future__ import annotations

import argparse
from datetime import datetime, date
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
HASH = re.compile(r"^[0-9a-f]{64}$")


def validate(payload: object, *, today: date, approval: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(approval, dict):
        raise ValueError("invalid input")
    if payload.get("date_jst") != today.isoformat():
        raise ValueError("not today's JST race data")
    if not HASH.fullmatch(str(payload.get("source_sha256", ""))):
        raise ValueError("source hash missing")
    if not isinstance(payload.get("source_url"), str) or not payload["source_url"].startswith("https://"):
        raise ValueError("source URL invalid")
    if approval.get("redistribution_authorized") is not True:
        raise ValueError("redistribution permission not confirmed")
    if approval.get("source_url") != payload["source_url"]:
        raise ValueError("permission evidence does not match source")
    if not approval.get("evidence_reference") or not approval.get("reviewed_by"):
        raise ValueError("permission evidence incomplete")
    observed = datetime.fromisoformat(str(payload.get("first_observed_at", "")).replace("Z", "+00:00"))
    if observed.tzinfo is None or observed > datetime.now(JST):
        raise ValueError("invalid observation timestamp")
    venues = payload.get("venues")
    if not isinstance(venues, list) or not 1 <= len(venues) <= 24:
        raise ValueError("invalid venue collection")
    count = 0
    completed = 0
    seen_venues = set()
    for venue in venues:
        code = venue.get("venue") if isinstance(venue, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"0[1-9]|1[0-9]|2[0-4]", code) or code in seen_venues:
            raise ValueError("invalid or duplicate venue")
        seen_venues.add(code)
        races = venue.get("races")
        if not isinstance(races, list) or not 1 <= len(races) <= 12:
            raise ValueError("invalid races")
        seen_races = set()
        for race in races:
            rid = race.get("race_id") if isinstance(race, dict) else None
            if not isinstance(rid, str) or not re.fullmatch(today.strftime("%Y%m%d") + "-" + code + r"-(0[1-9]|1[0-2])", rid) or rid in seen_races:
                raise ValueError("invalid or duplicate race")
            seen_races.add(rid)
            boats = race.get("boats")
            if not isinstance(boats, list) or not 1 <= len(boats) <= 6:
                raise ValueError("invalid boats")
            lanes = set()
            for boat in boats:
                lane = boat.get("lane") if isinstance(boat, dict) else None
                if type(lane) is not int or not 1 <= lane <= 6 or lane in lanes:
                    raise ValueError("invalid or duplicate lane")
                lanes.add(lane)
                if not re.fullmatch(r"[0-9]{4}", str(boat.get("racer_registration_id", ""))):
                    raise ValueError("invalid racer")
                motor = boat.get("motor_no")
                if type(motor) is not int or not 1 <= motor <= 999:
                    raise ValueError("invalid motor")
            count += 1
            completed += len(boats) == 6
    if payload.get("races") not in (None, count):
        raise ValueError("race count mismatch")
    if payload.get("complete_six_boat_races") not in (None, completed):
        raise ValueError("complete race count mismatch")
    return {**payload, "races": count, "complete_six_boat_races": completed,
            "redistribution_authorized": True}


def publish(source: Path, approval_file: Path, destination: Path, *, today: date | None = None):
    today = today or datetime.now(JST).date()
    if source.stat().st_size > 6_000_000:
        raise ValueError("source too large")
    payload = json.loads(source.read_text(encoding="utf-8"))
    approval = json.loads(approval_file.read_text(encoding="utf-8"))
    verified = validate(payload, today=today, approval=approval)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(verified, ensure_ascii=False, separators=(",", ":")) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                     prefix=".today-", suffix=".tmp", delete=False) as tmp:
        tmp.write(data)
        temp_path = Path(tmp.name)
    try:
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        publish(args.source, args.approval, args.destination)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print("SAFE_STOP: " + str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
