"""Read approved current-day snapshots through the pinned private Blob SDK.

vercel==0.11.6 returns GetBlobResult.content (bytes), not a stream. Official
sources are never fetched by this API. Both the operator feed gate and the
snapshot's publication flag must be present before anything is served.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import json
import math
import os
import re

MAX_BYTES = 6_000_000
JST = ZoneInfo('Asia/Tokyo')


def utc_now():
    return datetime.now(timezone.utc)


def current_day():
    return utc_now().astimezone(JST).date().isoformat()


def create_blob_client(token):
    from vercel.blob import BlobClient
    return BlobClient(token=token)


def https_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('invalid source URL')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.port not in (None, 443)
            or any(ord(c) < 33 for c in value)):
        raise ValueError('invalid source URL')
    return parsed


def timestamp(value, *, day, now, future=False):
    if not isinstance(value, str):
        raise ValueError('missing timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.astimezone(JST).date() != day or (not future and parsed > now):
        raise ValueError('timestamp outside permitted day/as-of')
    return parsed


def source_reference(owner, prefix, sources, *, day, now):
    url = owner.get(prefix + '_source_url')
    digest = owner.get(prefix + '_source_sha256')
    observed = owner.get(prefix + '_observed_at')
    if not isinstance(sources, list):
        raise ValueError('availability source proof absent')
    matching = [s for s in sources if s.get('source_url') == url and
                s.get('source_sha256') == digest and s.get('first_observed_at') == observed]
    if len(matching) != 1:
        raise ValueError('availability source proof mismatch')
    timestamp(observed, day=day, now=now)


def empty_venue_state(venue, sources, *, day, now):
    source_reference(venue, 'schedule', sources, day=day, now=now)
    if venue.get('schedule_verified') is not True:
        raise ValueError('venue schedule unverified')
    if venue.get('status') == 'NO_EVENT' and venue.get('no_event') is True and venue.get('schedule_basis') == 'NOT_LISTED_IN_COMPLETE_DAY_INDEX':
        return
    if (venue.get('status') in {'UNOBTAINED', 'ERROR', 'PARTIAL'} and venue.get('no_event') is False
            and venue.get('schedule_basis') == 'LISTED_IN_COMPLETE_DAY_INDEX'):
        return
    raise ValueError('empty venue has no explicit availability state')


def validate_feed(data, *, day, now):
    """Validate every venue/race/lane, without substituting missing fields."""
    if (not isinstance(data, dict) or data.get('date_jst') != day.isoformat()
            or data.get('redistribution_authorized') is not True
            or not re.fullmatch(r'[0-9a-f]{64}', str(data.get('source_sha256', '')))):
        raise ValueError('stale or unapproved feed')
    https_url(data.get('source_url'))
    timestamp(data.get('first_observed_at'), day=day, now=now)
    if data.get('last_observed_at') is not None:
        last = timestamp(data['last_observed_at'], day=day, now=now)
        if last < timestamp(data['first_observed_at'], day=day, now=now):
            raise ValueError('observation order invalid')
    sources = data.get('sources')
    source_urls = set()
    if sources is not None:
        if not isinstance(sources, list) or not 1 <= len(sources) <= 289:
            raise ValueError('invalid source collection')
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError('invalid source')
            url = source.get('source_url')
            https_url(url)
            if url in source_urls or not re.fullmatch(r'[0-9a-f]{64}', str(source.get('source_sha256', ''))):
                raise ValueError('duplicate source or missing source hash')
            source_urls.add(url)
            timestamp(source.get('first_observed_at'), day=day, now=now)
        if data['source_url'] not in source_urls:
            raise ValueError('primary source absent')
        primary = next(source for source in sources if source['source_url'] == data['source_url'])
        if any(primary[field] != data[field] for field in ('source_sha256', 'first_observed_at')):
            raise ValueError('primary source provenance conflicts')
    venues = data.get('venues')
    if not isinstance(venues, list) or len(venues) > 24:
        raise ValueError('invalid venues')
    if not venues:
        if data.get('status') != 'NO_EVENT' or data.get('no_event') is not True or data.get('schedule_verified') is not True or data.get('active_venues') != []:
            raise ValueError('empty day lacks positive schedule evidence')
        source_reference(data, 'schedule', sources, day=day, now=now)
    seen_venues = set()
    count = completed = 0
    for venue in venues:
        code = venue.get('venue') if isinstance(venue, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r'0[1-9]|1[0-9]|2[0-4]', code) or code in seen_venues:
            raise ValueError('invalid or duplicate venue')
        seen_venues.add(code)
        races = venue.get('races')
        if not isinstance(races, list) or len(races) > 12:
            raise ValueError('invalid race list')
        if not races:
            empty_venue_state(venue, sources, day=day, now=now)
        elif venue.get('status') == 'NO_EVENT' or venue.get('no_event') is True:
            raise ValueError('no-event venue contains races')
        elif venue.get('schedule_verified') is not None:
            source_reference(venue, 'schedule', sources, day=day, now=now)
            if venue.get('schedule_verified') is not True or venue.get('schedule_basis') != 'LISTED_IN_COMPLETE_DAY_INDEX':
                raise ValueError('active venue schedule invalid')
        seen_races = set()
        for race in races:
            rid = race.get('race_id') if isinstance(race, dict) else None
            if (not isinstance(rid, str) or not re.fullmatch(f'{day:%Y%m%d}-{code}-(0[1-9]|1[0-2])', rid)
                    or rid in seen_races):
                raise ValueError('invalid or duplicate race')
            seen_races.add(rid)
            if race.get('program_source_url') is not None:
                source_reference(race, 'program', sources, day=day, now=now)
            if race.get('closed_at') is not None:
                timestamp(race['closed_at'], day=day, now=now, future=True)
            boats = race.get('boats')
            if not isinstance(boats, list) or not 1 <= len(boats) <= 6:
                raise ValueError('invalid boat list')
            identities = {field: set() for field in ('lane', 'racer_registration_id', 'motor_no', 'boat_no')}
            for boat in boats:
                if not isinstance(boat, dict):
                    raise ValueError('invalid boat')
                lane, racer = boat.get('lane'), boat.get('racer_registration_id')
                if type(lane) is not int or not 1 <= lane <= 6 or not isinstance(racer, str) or not re.fullmatch(r'[0-9]{4}', racer):
                    raise ValueError('invalid lane or registration')
                for field in identities:
                    value = boat.get(field)
                    if field in ('motor_no', 'boat_no') and value is not None and (type(value) is not int or not 1 <= value <= 999):
                        raise ValueError('invalid allocation')
                    if value is not None:
                        if value in identities[field]:
                            raise ValueError('duplicate identity')
                        identities[field].add(value)
                name = boat.get('name')
                if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= 128 or any(ord(c) < 32 for c in name)):
                    raise ValueError('invalid name')
                for field in ('average_st', 'display_time', 'national_win_rate', 'local_win_rate'):
                    value = boat.get(field)
                    maximum = 1 if field == 'average_st' else (100 if field == 'display_time' else 10)
                    if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= maximum):
                        raise ValueError('invalid measurement')
                if boat.get('preview_course') is not None and (type(boat['preview_course']) is not int or not 1 <= boat['preview_course'] <= 6):
                    raise ValueError('invalid preview course')
                if boat.get('detail_captured_at') is not None:
                    timestamp(boat['detail_captured_at'], day=day, now=now)
                if boat.get('detail_source_url') is not None:
                    https_url(boat['detail_source_url'])
                    if boat.get('detail_captured_at') is None:
                        raise ValueError('detail timestamp absent')
                    if sources is not None and boat['detail_source_url'] not in source_urls:
                        raise ValueError('detail source absent')
            count += 1
            completed += len(boats) == 6
    if type(data.get('races')) is not int or data['races'] != count:
        raise ValueError('race count mismatch')
    if type(data.get('complete_six_boat_races')) is not int or data['complete_six_boat_races'] != completed:
        raise ValueError('complete race count mismatch')
    if data.get('schedule_verified') is True:
        for venue in venues:
            no_event = venue.get('no_event')
            expected_basis = ('NOT_LISTED_IN_COMPLETE_DAY_INDEX' if no_event is True
                              else 'LISTED_IN_COMPLETE_DAY_INDEX')
            if (type(no_event) is not bool or venue.get('schedule_verified') is not True
                    or venue.get('schedule_basis') != expected_basis):
                raise ValueError('complete schedule venue proof incomplete')
            source_reference(venue, 'schedule', sources, day=day, now=now)
        active = data.get('active_venues')
        if (not isinstance(active,list) or any(not isinstance(code,str) for code in active)
                or len(active)!=len(set(active)) or len(venues) not in (0,24)
                or set(active)!={venue['venue'] for venue in venues if venue.get('no_event') is False}):
            raise ValueError('complete schedule active venue set conflicts')
    return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('nonfinite JSON number')


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('nonfinite JSON number')
    return result


def load_feed():
    if os.environ.get('RACE_AI_FEED_APPROVED') != '1':
        return 503, {'error': 'FEED_NOT_APPROVED'}
    token = os.environ.get('BLOB_READ_WRITE_TOKEN')
    # Vercel deployment OIDC and Blob read/write credentials have different
    # audiences; an OIDC string must never be forwarded as a Blob bearer token.
    if not token:
        return 503, {'error': 'FEED_STORE_NOT_CONFIGURED'}
    client = None
    try:
        before = utc_now()
        day = before.astimezone(JST).date()
        key = f'race-ai/day/{day.isoformat()}.json'
        client = create_blob_client(token)
        result = client.get(key, access='private', timeout=8, use_cache=False)
        if result is None or result.status_code != 200 or result.pathname != key:
            raise ValueError('unexpected Blob result')
        url = https_url(result.url)
        if not re.fullmatch(r'[A-Za-z0-9]+\.private\.blob\.vercel-storage\.com', url.hostname or '') or url.path != '/' + key:
            raise ValueError('unexpected Blob origin')
        if not isinstance(result.content_type, str) or result.content_type.split(';')[0].strip().lower() != 'application/json':
            raise ValueError('unexpected Blob content type')
        raw = result.content
        # HTTP Content-Length may describe compressed bytes while SDK .content
        # is decoded. Bound each independently; equality is not guaranteed.
        if (not isinstance(raw, bytes) or len(raw) > MAX_BYTES or type(result.size) is not int
                or not 0 <= result.size <= MAX_BYTES):
            raise ValueError('invalid Blob size/content')
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                          parse_constant=reject_constant, parse_float=finite_float)
        after = utc_now()
        if after.astimezone(JST).date() != day:
            raise ValueError('JST midnight crossed')
        validated = validate_feed(data, day=day, now=after)
        # Reject escaped lone surrogates and any unsupported output values
        # inside optional fields before the HTTP handler writes its headers.
        json.dumps(validated, ensure_ascii=False, allow_nan=False).encode('utf-8')
        return 200, validated
    except Exception:
        # SDK and transport exceptions can contain credentials or source URLs.
        return 503, {'error': 'FEED_STORE_UNAVAILABLE'}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, payload = load_feed()
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
