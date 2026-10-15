"""Read-only API for independently approved daily snapshots in private Blob.

The web deployment is self-contained: the validator mirrors the public
publisher/browser identity contract without importing the research engine.
Never fetches source websites, grants publication rights, or writes to Blob.
"""
import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler
import json
import math
import os
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from vercel.blob import AsyncBlobClient

MAX_BYTES = 6_000_000
JST = ZoneInfo("Asia/Tokyo")
ROOT_FIELDS = (
    "date_jst", "source_url", "source_sha256", "first_observed_at",
    "upstream_published_at", "provider", "official_result_verified",
    "provider_rights_require_separate_review", "original_exhibition_supported",
    "current_motor_cycle_known", "nationwide_active_motor_inventory_complete",
    "status", "venues_with_races", "races", "complete_six_boat_races", "previews",
    "results", "redistribution_authorized",
)
BOAT_FIELDS = (
    "lane", "racer_registration_id", "name", "motor_no", "motor_top2_rate",
    "average_st", "preview_course", "preview_st", "display_time", "original_lap",
    "original_turn", "original_straight", "result_course", "result_st", "finish",
    "original_exhibition_status",
)


def current_day():
    return datetime.now(JST).date().isoformat()


def _project_scalars(value, fields):
    result = {}
    for key in fields:
        if key in value:
            item = value[key]
            if item is not None and type(item) not in (str, int, float, bool):
                raise ValueError("invalid public field")
            if isinstance(item, str) and len(item) > 4096:
                raise ValueError("public field too long")
            if type(item) is float and not math.isfinite(item):
                raise ValueError("nonfinite public field")
            result[key] = item
    return result


def _validate_timestamp(value, *, now):
    if not isinstance(value, str) or not re.search(r"T.*(?:Z|[+-][0-9]{2}:[0-9]{2})$", value):
        raise ValueError("invalid evidence timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed > now:
        raise ValueError("invalid evidence timestamp")


def validate_snapshot(data, *, day):
    """Validate publisher identities/provenance, then expose public fields only.

    The approval flag is evidence asserted by the separately reviewed publisher;
    this reader cannot independently grant or establish redistribution rights.
    """
    if not isinstance(data, dict) or data.get("date_jst") != day:
        raise ValueError("not the requested JST day")
    if data.get("redistribution_authorized") is not True:
        raise ValueError("unapproved snapshot")
    source = data.get("source_url")
    url = urlsplit(source) if isinstance(source, str) else None
    if (not url or url.scheme != "https" or not url.hostname or url.username or
            url.password or any(c.isspace() or ord(c) < 32 for c in source)):
        raise ValueError("invalid source URL")
    if not isinstance(data.get("source_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", data["source_sha256"]):
        raise ValueError("missing source hash")
    now = datetime.now(JST)
    _validate_timestamp(data.get("first_observed_at"), now=now)
    if data.get("upstream_published_at") is not None:
        _validate_timestamp(data["upstream_published_at"], now=now)
    venues = data.get("venues")
    if not isinstance(venues, list) or not 1 <= len(venues) <= 24:
        raise ValueError("invalid venues")
    public_venues, seen_venues = [], set()
    count = complete = previews = results = 0
    for venue in venues:
        code = venue.get("venue") if isinstance(venue, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"0[1-9]|1[0-9]|2[0-4]", code) or code in seen_venues:
            raise ValueError("invalid or duplicate venue")
        seen_venues.add(code)
        races = venue.get("races")
        if not isinstance(races, list) or not 1 <= len(races) <= 12:
            raise ValueError("invalid races")
        public_races, seen_races = [], set()
        for race in races:
            rid = race.get("race_id") if isinstance(race, dict) else None
            if not isinstance(rid, str) or not re.fullmatch(day.replace("-", "") + "-" + code + r"-(0[1-9]|1[0-2])", rid) or rid in seen_races:
                raise ValueError("invalid or duplicate race")
            seen_races.add(rid)
            boats = race.get("boats")
            if not isinstance(boats, list) or not 1 <= len(boats) <= 6:
                raise ValueError("invalid boats")
            public_boats, lanes, racers, motors = [], set(), set(), set()
            for boat in boats:
                lane = boat.get("lane") if isinstance(boat, dict) else None
                if type(lane) is not int or not 1 <= lane <= 6 or lane in lanes:
                    raise ValueError("invalid or duplicate lane")
                lanes.add(lane)
                racer = boat.get("racer_registration_id")
                if not isinstance(racer, str) or not re.fullmatch(r"[0-9]{4}", racer) or racer in racers:
                    raise ValueError("invalid or duplicate racer")
                racers.add(racer)
                motor = boat.get("motor_no")
                if motor is not None:
                    if type(motor) is not int or not 1 <= motor <= 999 or motor in motors:
                        raise ValueError("invalid or duplicate motor")
                    motors.add(motor)
                if race.get("result_available") is not True and any(
                        boat.get(field) is not None for field in ("result_course", "result_st", "finish")):
                    raise ValueError("result fields without result availability")
                public_boat = _project_scalars(boat, BOAT_FIELDS)
                # The browser requires null for an unknown motor, not absence.
                public_boat["motor_no"] = motor
                public_boats.append(public_boat)
            public_race = _project_scalars(race, ("race_id", "closed_at", "boat_count", "result_available", "preview_available", "source_status"))
            if "boat_count" in race and (type(race["boat_count"]) is not int or race["boat_count"] != len(boats)):
                raise ValueError("boat count mismatch")
            for flag in ("result_available", "preview_available"):
                if flag in race and type(race[flag]) is not bool:
                    raise ValueError("invalid availability flag")
            if "weather_preview" in race:
                if not isinstance(race["weather_preview"], dict):
                    raise ValueError("invalid weather")
                public_race["weather_preview"] = _project_scalars(race["weather_preview"], ("wind_speed", "wind_direction_number", "wave_height"))
            public_race["boats"] = public_boats
            public_races.append(public_race)
            count += 1
            complete += len(boats) == 6
            # The normalizer counts races with availability, not result boats.
            previews += race.get("preview_available") is True
            results += race.get("result_available") is True
        public_venue = _project_scalars(venue, ("venue", "motor_scope", "race_count"))
        if "race_count" in venue and (type(venue["race_count"]) is not int or venue["race_count"] != len(races)):
            raise ValueError("venue race count mismatch")
        if "listed_motor_numbers" in venue:
            motors = venue["listed_motor_numbers"]
            if not isinstance(motors, list) or len(motors) > 72 or any(type(m) is not int or not 1 <= m <= 999 for m in motors):
                raise ValueError("invalid listed motors")
            public_venue["listed_motor_numbers"] = motors
        public_venue["races"] = public_races
        public_venues.append(public_venue)
    for field, expected in (("races", count), ("complete_six_boat_races", complete),
                            ("venues_with_races", len(venues)), ("previews", previews), ("results", results)):
        if field in data and (type(data[field]) is not int or data[field] != expected):
            raise ValueError("snapshot count mismatch")
    public = _project_scalars(data, ROOT_FIELDS)
    public.update(venues=public_venues, races=count, complete_six_boat_races=complete)
    return public


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite JSON number")


async def _load_private_snapshot(token, day):
    key = "race-ai/day/" + day + ".json"
    try:
        async with AsyncBlobClient(token=token) as client:
            response = await client.get(key, access="private", use_cache=False, timeout=8)
        if response.status_code != 200 or response.pathname != key or not isinstance(response.content, bytes):
            return 503, {"error": "FEED_STORE_UNAVAILABLE"}
        raw = response.content
        if len(raw) > MAX_BYTES or (response.size is not None and response.size > MAX_BYTES):
            return 503, {"error": "FEED_TOO_LARGE"}
    except Exception:
        # SDK/httpx errors must not expose tokens, private URLs or upstream text.
        return 503, {"error": "FEED_STORE_UNAVAILABLE"}
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        public = validate_snapshot(data, day=day)
        if current_day() != day:
            raise ValueError("JST day changed during read")
        return 200, public
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        return 503, {"error": "FEED_STALE_OR_UNAPPROVED"}


def load_feed():
    if os.environ.get("RACE_AI_FEED_APPROVED") != "1":
        return 503, {"error": "FEED_NOT_APPROVED"}
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token or not token.strip():
        return 503, {"error": "FEED_STORE_NOT_CONFIGURED"}
    return asyncio.run(_load_private_snapshot(token, current_day()))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, payload = load_feed()
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
