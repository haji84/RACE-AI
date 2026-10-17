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


def source_reference(owner, prefix, payload, today, now=None):
    sources = payload.get('sources')
    if not isinstance(sources, list):
        raise ValueError('availability source proof absent')
    matching = [source for source in sources if source.get('source_url') == owner.get(prefix + '_source_url')
        and source.get('source_sha256') == owner.get(prefix + '_source_sha256')
        and source.get('first_observed_at') == owner.get(prefix + '_observed_at')]
    if len(matching) != 1:
        raise ValueError('availability source proof mismatch')
    observed = datetime.fromisoformat(matching[0]['first_observed_at'].replace('Z', '+00:00'))
    if observed.tzinfo is None or observed.astimezone(JST).date() != today or observed > (now or datetime.now(JST)):
        raise ValueError('availability source observation invalid')


def empty_venue_state(venue, payload, today, now=None):
    source_reference(venue, 'schedule', payload, today, now)
    if venue.get('schedule_verified') is not True:
        raise ValueError('venue schedule unverified')
    if venue.get('status') == 'NO_EVENT' and venue.get('no_event') is True and venue.get('schedule_basis') == 'NOT_LISTED_IN_COMPLETE_DAY_INDEX':
        return
    if (venue.get('status') in {'UNOBTAINED', 'ERROR', 'PARTIAL'} and venue.get('no_event') is False
            and venue.get('schedule_basis') == 'LISTED_IN_COMPLETE_DAY_INDEX'):
        return
    raise ValueError('empty venue lacks explicit availability state')


def validate(payload: object, *, today: date, approval: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(JST)
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
    # Combining an index with common-site details adds a separately reviewed
    # source. Permission for the index must never authorize those new facts.
    if payload.get('sources') is not None:
        sources = payload['sources']
        records = approval.get('source_approvals', [])
        if not isinstance(sources, list) or not sources or not isinstance(records, list):
            raise ValueError('source approval collection invalid')
        approved_sources = [approval] + records
        seen_sources = set()
        for source in sources:
            if not isinstance(source, dict) or not HASH.fullmatch(str(source.get('source_sha256', ''))):
                raise ValueError('source approval provenance incomplete')
            url = source.get('source_url')
            if not isinstance(url, str) or not url.startswith('https://') or url in seen_sources:
                raise ValueError('source approval URL invalid or duplicate')
            seen_sources.add(url)
            matching = [r for r in approved_sources if isinstance(r, dict) and r.get('source_url') == url]
            if (len(matching) != 1 or matching[0].get('redistribution_authorized') is not True
                    or not matching[0].get('evidence_reference') or not matching[0].get('reviewed_by')):
                raise ValueError('source approval missing or conflicting')
            captured = datetime.fromisoformat(str(source.get('first_observed_at', '')).replace('Z', '+00:00'))
            if captured.tzinfo is None or captured.astimezone(JST).date() != today or captured > now:
                raise ValueError('source approval observation time invalid')
        if payload['source_url'] not in seen_sources:
            raise ValueError('source approval for primary source absent')
        primary = next(source for source in sources if source['source_url'] == payload['source_url'])
        if any(primary[field] != payload.get(field) for field in ('source_sha256', 'first_observed_at')):
            raise ValueError('source approval primary provenance conflicts')
    observed = datetime.fromisoformat(str(payload.get("first_observed_at", "")).replace("Z", "+00:00"))
    if observed.tzinfo is None or observed.astimezone(JST).date() != today or observed > now:
        raise ValueError("invalid observation timestamp")
    venues = payload.get("venues")
    if not isinstance(venues, list) or len(venues) > 24:
        raise ValueError("invalid venue collection")
    if not venues:
        if payload.get('status') != 'NO_EVENT' or payload.get('no_event') is not True or payload.get('schedule_verified') is not True or payload.get('active_venues') != []:
            raise ValueError('empty day lacks positive schedule evidence')
        source_reference(payload, 'schedule', payload, today, now)
    count = 0
    completed = 0
    seen_venues = set()
    for venue in venues:
        code = venue.get("venue") if isinstance(venue, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"0[1-9]|1[0-9]|2[0-4]", code) or code in seen_venues:
            raise ValueError("invalid or duplicate venue")
        seen_venues.add(code)
        races = venue.get("races")
        if not isinstance(races, list) or len(races) > 12:
            raise ValueError("invalid races")
        if not races:
            empty_venue_state(venue, payload, today, now)
        elif venue.get('status') == 'NO_EVENT' or venue.get('no_event') is True:
            raise ValueError('no-event venue contains races')
        elif venue.get('schedule_verified') is not None:
            source_reference(venue, 'schedule', payload, today, now)
            if venue.get('schedule_verified') is not True or venue.get('schedule_basis') != 'LISTED_IN_COMPLETE_DAY_INDEX':
                raise ValueError('active venue schedule invalid')
        seen_races = set()
        for race in races:
            rid = race.get("race_id") if isinstance(race, dict) else None
            if not isinstance(rid, str) or not re.fullmatch(today.strftime("%Y%m%d") + "-" + code + r"-(0[1-9]|1[0-2])", rid) or rid in seen_races:
                raise ValueError("invalid or duplicate race")
            seen_races.add(rid)
            if race.get('program_source_url') is not None:
                source_reference(race, 'program', payload, today, now)
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
                if motor is not None and (type(motor) is not int or not 1 <= motor <= 999):
                    raise ValueError("invalid motor")
            count += 1
            completed += len(boats) == 6
    if payload.get("races") not in (None, count):
        raise ValueError("race count mismatch")
    if payload.get("complete_six_boat_races") not in (None, completed):
        raise ValueError("complete race count mismatch")
    if payload.get('schedule_verified') is True:
        for venue in venues:
            no_event = venue.get('no_event')
            expected_basis = ('NOT_LISTED_IN_COMPLETE_DAY_INDEX' if no_event is True
                              else 'LISTED_IN_COMPLETE_DAY_INDEX')
            if (type(no_event) is not bool or venue.get('schedule_verified') is not True
                    or venue.get('schedule_basis') != expected_basis):
                raise ValueError('complete schedule venue proof incomplete')
            source_reference(venue, 'schedule', payload, today, now)
        active = payload.get('active_venues')
        if (not isinstance(active,list) or any(not isinstance(code,str) for code in active)
                or len(active)!=len(set(active)) or len(venues) not in (0,24)
                or set(active)!={venue['venue'] for venue in venues if venue.get('no_event') is False}):
            raise ValueError('complete schedule active venue set conflicts')
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
