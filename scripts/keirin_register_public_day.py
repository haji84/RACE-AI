"""Build a partial, source-byte-bound future-day KEIRIN registry from real links.

Read only ordinary public Kdreams calendar -> meeting -> racedetail hrefs.
Do not invent meetings, races, cutoff clocks, grades or rider identities.
A Kdreams-only observed set is NEVER certified as the nationwide universe.
All HTML is confined to a private directory and the day report is redacted.
This is a feeder for the existing A/B collector, not a production feed licence,
official cutoff certificate, or proof of complete nationwide coverage.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os

from race_ai import keirin_dynamic_nationwide_registry as dynamic
from scripts import keirin_capture_public_two_sources as capture
from scripts import keirin_discover_public_race_links as links

REPORT = "RACE_AI_KEIRIN_PUBLIC_LINK_DAY_REGISTRATION_V1"
MAX_MEETINGS = 20


class DayPublicRegistrationError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise DayPublicRegistrationError(code)


def _now(clock):
    value = clock()
    require(isinstance(value, datetime) and value.utcoffset() is not None,
            "CAPTURE_CLOCK_WITH_OFFSET_REQUIRED")
    return value.astimezone(timezone.utc).isoformat()


def register_day(*, day_jst, private_raw_dir, fetch=None, clock=None,
                 max_meetings=MAX_MEETINGS):
    """Collect a real partial roster, preserving uncertainty, with no model call.

    A second read of the saved source bytes authenticates the local SHA only.
    It is NOT a second provider nor independent whole-day certification.
    """
    try:
        day = date.fromisoformat(day_jst)
        require(day.isoformat() == day_jst, "DAY_JST_INVALID")
    except (ValueError, TypeError, AttributeError):
        raise DayPublicRegistrationError("DAY_JST_INVALID") from None
    require(type(max_meetings) is int and 1 <= max_meetings <= MAX_MEETINGS,
            "MEETING_GET_BUDGET_INVALID")
    raw_dir = capture.private_dir(private_raw_dir)
    fetch = fetch or capture.fetch_once
    clock = clock or (lambda: datetime.now(timezone.utc))
    require(callable(fetch) and callable(clock),
            "FETCH_AND_CLOCK_REQUIRED")

    calendar_url = links.CALENDAR.format(
        year=day.year, month=day.month, day=day.day)
    calendar_html = fetch(calendar_url)
    calendar_at = _now(clock)
    require(type(calendar_html) is bytes and
            0 < len(calendar_html) <= capture.MAX_BYTES,
            "CALENDAR_BYTES_INVALID")
    calendar_sha = sha256(calendar_html).hexdigest()
    capture._write_once(raw_dir / (calendar_sha + ".html"), calendar_html)
    cards = links.linked_racecards(
        calendar_html, base_url=calendar_url, day=day_jst)
    require(cards, "DAY_NO_REAL_CALENDAR_MEETING_LINKS")

    snapshots = []
    linked = {}
    errors = 0
    stopped_for_denial = False
    attempted = 0
    for venue_code, meeting_url in sorted(cards.items()):
        if attempted >= max_meetings:
            break
        attempted += 1
        try:
            meeting_html = fetch(meeting_url)
            received_at = _now(clock)
            require(type(meeting_html) is bytes and
                    0 < len(meeting_html) <= capture.MAX_BYTES,
                    "MEETING_BYTES_INVALID")
            page_sha = sha256(meeting_html).hexdigest()
            capture._write_once(raw_dir / (page_sha + ".html"), meeting_html)
            details = links.linked_details(
                meeting_html, base_url=meeting_url,
                day=day_jst, venue=venue_code)
        except capture.SourceCaptureError as exc:
            errors += 1
            # Do not probe other pages after a denial or rate limit.
            if str(exc) in ("PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                            "PUBLIC_PROVIDER_HTTP_ERROR_STOP",
                            "PUBLIC_PROVIDER_UNAVAILABLE_STOP"):
                stopped_for_denial = True
                break
            continue
        if not details:
            continue
        numbers = sorted({int(race_id[-2:]) for race_id in details})
        # Visible hrefs are the only admitted race count. Do not silently
        # fill gaps or say a provider's partial page proves all 12 races.
        snapshots.append({
            "venue": venue_code, "venue_code": venue_code,
            "grade": "UNKNOWN",
            "source_url": meeting_url,
            "source_bytes_sha256": page_sha,
            "source_available_at": received_at,
            "race_numbers": numbers,
            "source_race_day": day_jst,
        })
        linked.update(details)

    require(snapshots, "DAY_NO_VERIFIABLE_RACE_DETAIL_LINKS")
    registered_at = _now(clock)

    def verify_saved_source_bytes(block):
        # Read again from the private directory, not the original fetch buffer.
        p = raw_dir / (block["source_bytes_sha256"] + ".html")
        if not p.is_file() or p.is_symlink():
            return False
        return sha256(p.read_bytes()).hexdigest() == block["source_bytes_sha256"]

    registry = dynamic.create_day(
        day_jst=day_jst, registered_at=registered_at,
        venue_snapshots=snapshots,
        expected_venue_codes=None,  # Never claim a one-provider national universe.
        independently_verify_venue_snapshot=verify_saved_source_bytes,
        independently_verify_whole_day=None,
    )
    dynamic.checked_day(registry)
    rows = []
    for race in registry["races"]:
        rid = race["race_id"]
        # A netkeirin URL is a *candidate* for bounded subsequent GET.
        # It was not discovered in an href or authenticated here.
        rows.append({
            "race_id": rid,
            "netkeirin_url":
                "https://keirin.netkeiba.com/race/entry/?race_id=" + rid,
            "kdreams_url": linked[rid],
            "cutoff_hint": None,
        })
    manifest = {
        "schema": capture.SCHEMA,
        "day_jst": day_jst, "races": rows,
        "source_use_scope": "OWNER_PERSONAL_RESEARCH_ONLY",
    }
    capture.manifest_check(
        manifest, registered_ids=[r["race_id"] for r in registry["races"]])
    safe = {
        "schema": REPORT, "day_jst": day_jst,
        "calendar_html_sha256": calendar_sha,
        "calendar_observed_at": calendar_at,
        "linked_calendar_venues": len(cards),
        "meeting_pages_attempted": attempted,
        "meeting_pages_with_verified_detail_hrefs": len(snapshots),
        "observed_races_registered": len(registry["races"]),
        "uninspected_meeting_pages": len(cards) - attempted,
        "page_errors": errors,
        "stopped_after_provider_error": stopped_for_denial,
        "national_universe_verified": False,
        "official_cutoff_verified": False,
        "actual_forecasts_generated": 0,
        "pre_race_netkeirin_candidates_not_verified": True,
        "registry_sha256": registry["registry_sha256"],
    }
    return registry, manifest, safe


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True)
    ap.add_argument("--private-raw-dir", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--safe-report", required=True)
    a = ap.parse_args(argv)
    try:
        registry, manifest, safe = register_day(
            day_jst=a.day, private_raw_dir=a.private_raw_dir)
        targets = [
            (Path(a.registry), registry),
            (Path(a.manifest), manifest),
            (Path(a.safe_report), safe),
        ]
        for path, _ in targets:
            require(path.is_absolute() and path.parent.is_dir() and
                    not path.exists() and not path.is_symlink(),
                    "DAY_SOURCE_OUTPUT_MUST_BE_NEW_ABSOLUTE_PATH")
        for path, doc in targets:
            data = (json.dumps(
                doc, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")) + "\n").encode("utf-8")
            capture._write_once(path, data)
        # Logs reveal only aggregate counters, never rider data or raw HTML.
        print(json.dumps(safe, sort_keys=True))
        return 0
    except (DayPublicRegistrationError, capture.SourceCaptureError,
            links.DayLinksError, dynamic.DynamicDayError,
            ValueError, TypeError, KeyError, OSError):
        print('{"state":"HOLD_DAY_REGISTRATION_NOT_CERTIFIED"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
