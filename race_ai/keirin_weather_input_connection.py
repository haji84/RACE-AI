"""Existing Open-Meteo forecast adapter -> existing partial KEIRIN inputs.

No new weather service or prediction model. Forecast values are labelled as
numerical-grid forecasts, NEVER measurements at the track. Original published
racecard observations win over modelled weather. Missing surface wetness,
roughness, exposure and bank geometry remain missing.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import re

from .keirin_open_meteo_weather import (
    request_url, parse_one_forecast, _get_once, WeatherSourceError, MAX_BODY,
)
from .keirin_preflight import expected_keys
from .keirin_result_delivery import canonical, utc
from .keirin_real_source_gap_report import inspect_source_gaps
from .keirin_prior_private_stage import _private_root
from .keirin_permissioned_owner import _write_private_once

# Read from the venue's own access-page map iframe on 2026-11-10.
# URL pb components !2d140.664542 !3d40.797139. This is a map reference
# location, not surveyed telemetry coordinates or a user's location.
VENUES = {
    '12': {
        'latitude': 40.797139, 'longitude': 140.664542,
        'source_url': 'https://aomorikeirin.com/access/',
        'source_locator': 'surrounding-access Google Maps embed pb:2d/3d',
        'coordinate_kind': 'OFFICIAL_VENUE_MAP_REFERENCE_NOT_SURVEYED_TRACK_CENTER',
        'reviewed_on': '2026-11-10',
    },
}
WEATHER_SOURCE_KIND = 'MODELLED_NUMERICAL_GRID_FORECAST_NOT_ON_SITE_MEASUREMENT'
SCHEMA = 'RACE_AI_PRIVATE_MODELLED_WEATHER_CONNECTION_V1'
REQUIRED_FIELDS = frozenset({'air_temperature', 'humidity', 'rainfall', 'wind_speed'})


def need(ok, code):
    if not ok:
        raise WeatherSourceError(code)


def _location_and_start(card):
    inspect_source_gaps(card)
    rid = card.get('race_id')
    need(type(rid) is str and re.fullmatch(r'20[0-9]{10}', rid),
         'WEATHER_TARGET_RACE_ID_NOT_VERIFIED')
    venue = VENUES.get(rid[8:10])
    need(venue is not None, 'VENUE_COORDINATES_NOT_YET_VERIFIED')
    start = card['direct_verified_fields'].get('race/start_time')
    cutoff = card.get('source_published_cutoff_at_utc')
    need(type(start) is str and type(cutoff) is str and
         utc(card['source_capture_at_utc']) < utc(cutoff) <= utc(start),
         'WEATHER_ORIGINAL_RACE_CLOCKS_REQUIRED')
    return venue, start, cutoff


def _clock_stamp(clock):
    value = clock()
    need(isinstance(value, datetime) and value.utcoffset() is not None,
         'WEATHER_REAL_CAPTURE_CLOCK_REQUIRED')
    return value.isoformat()


def collect_modelled_weather(card, *, owner_noncommercial, fetch=None, clock=None):
    """One existing API GET; record the completion time, not request start.

    This is for owner-private noncommercial research under the already used
    weather API terms. A missing venue/start clock denies the network call.
    """
    need(owner_noncommercial is True, 'NONCOMMERCIAL_WEATHER_SCOPE_REQUIRED')
    venue, start, cutoff = _location_and_start(card)
    clock = clock or (lambda: datetime.now(timezone.utc))
    before = _clock_stamp(clock)
    need(utc(card['source_capture_at_utc']) <= utc(before) < utc(cutoff),
         'WEATHER_CAPTURE_ALREADY_AFTER_CUTOFF')
    url = request_url(venue['latitude'], venue['longitude'])
    raw = _get_once(url) if fetch is None else fetch(url)
    captured = _clock_stamp(clock)
    # Parsing rechecks the completion time against the same target cutoff.
    attach_modelled_weather_input(card, raw, captured_at=captured)
    return raw, captured


def attach_modelled_weather_input(card, raw, *, captured_at):
    """Pure, replayable source join; return no 'official' forecast claim."""
    venue, start, cutoff = _location_and_start(card)
    need(type(raw) is bytes and 0 < len(raw) <= MAX_BODY and
         utc(card['source_capture_at_utc']) <= utc(captured_at) < utc(cutoff),
         'WEATHER_CAPTURE_TIME_OR_BODY_INVALID')
    # The existing parser validates units, grid and horizon. Reject duplicate
    # JSON keys first so an ambiguous source cannot have multiple meanings.
    def unique(pairs):
        out = {}
        for key, value in pairs:
            need(key not in out, 'WEATHER_DUPLICATE_SOURCE_KEY')
            out[key] = value
        return out
    json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    record = parse_one_forecast(raw, latitude=venue['latitude'],
        longitude=venue['longitude'], race_id=card['race_id'],
        race_start_at=start, official_cutoff_at=cutoff, captured_at=captured_at)
    need(record['value_kind'] == WEATHER_SOURCE_KIND,
         'WEATHER_SOURCE_KIND_CHANGED')
    out = deepcopy(card)
    evidence = {}
    for field, value in record['model_inputs'].items():
        key = 'race/' + field
        if key in out['direct_verified_fields']:
            continue
        out['direct_verified_fields'][key] = value
        evidence[key] = {
            'value': value, 'value_kind': WEATHER_SOURCE_KIND,
            'source_url': record['source_url'],
            'source_rights_ref': record['source_rights_ref'],
            'license_url': record['license_url'],
            'attribution': record['attribution'],
            'captured_at': captured_at,
            'forecast_hour_at': record['forecast_hour_at'],
            'source_published_at': None,
            'original_weather_sha256': record['source_bytes_sha256'],
            'coordinate_source_url': venue['source_url'],
            'coordinate_kind': venue['coordinate_kind'],
            'coordinates': [venue['latitude'], venue['longitude']],
            'on_site_measurement': False,
            'approved_for_pr71_input': False,
        }
    registry = set(expected_keys([r['car_number'] for r in card['riders']]))
    keys = set(out['direct_verified_fields'])
    need(keys <= registry, 'WEATHER_UNREGISTERED_PARTIAL_INPUT')
    out.update({
        'verified_registry_keys': sorted(keys),
        'unavailable_registry_keys': sorted(registry - keys),
        'registry_verified_count': len(keys),
        'registry_unavailable_count': len(registry - keys),
        'full_347_or_437_verified': keys == registry,
        'modelled_weather_input_evidence': evidence,
        'weather_input_kind': WEATHER_SOURCE_KIND,
        'partial_input_as_of': captured_at,
        'full_model_input_admitted': False,
    })
    inspect_source_gaps(out)
    return out


def stage_modelled_weather_input(root, card, raw, *, captured_at):
    """Retain raw forecast bytes and combined partial input privately.

    Uses the existing partial-racecard folder. Nothing enters pre/, public
    Git artifacts or production AES simply by being saved in runner temp.
    """
    owner = _private_root(root)
    enriched = attach_modelled_weather_input(card, raw, captured_at=captured_at)
    folder = owner / 'weather'
    need(not folder.is_symlink(), 'PRIVATE_WEATHER_SYMLINK_FORBIDDEN')
    folder.mkdir(mode=0o700, exist_ok=True)
    original = {
        'schema': SCHEMA, 'base_partial_input': card,
        'weather_original_utf8': raw.decode('utf-8'),
        'weather_original_sha256': sha256(raw).hexdigest(),
        'captured_at': captured_at,
    }
    original_sha = sha256(canonical(original)).hexdigest()
    source_file = folder / (original_sha + '.json')
    _write_private_once(source_file, original)
    restored_raw = source_file.read_bytes()
    need(sha256(restored_raw).hexdigest() == original_sha,
         'PRIVATE_WEATHER_SOURCE_READBACK_MISMATCH')
    restored = json.loads(restored_raw)
    restored_weather = restored['weather_original_utf8'].encode('utf-8')
    need(sha256(restored_weather).hexdigest() == restored['weather_original_sha256'] and
         attach_modelled_weather_input(restored['base_partial_input'], restored_weather,
             captured_at=restored['captured_at']) == enriched,
         'PRIVATE_WEATHER_REPLAY_MISMATCH')
    partial = owner / 'winticket_racecard_partial'
    need(not partial.is_symlink(), 'PRIVATE_WEATHER_INPUT_SYMLINK_FORBIDDEN')
    partial.mkdir(mode=0o700, exist_ok=True)
    digest = sha256(canonical(enriched)).hexdigest()
    target = partial / (digest + '.json')
    created = _write_private_once(target, enriched)
    need(sha256(target.read_bytes()).hexdigest() == digest and
         json.loads(target.read_bytes()) == enriched,
         'PRIVATE_WEATHER_INPUT_READBACK_MISMATCH')
    return {
        'state': 'PRIVATE_MODELLED_WEATHER_PARTIAL_INPUT_REPLAYED',
        'connected_input_sha256': digest, 'weather_packet_sha256': original_sha,
        'original_weather_sha256': sha256(raw).hexdigest(),
        'new_partial_input': created,
        'weather_required_slots_connected': sum(k.split('/')[-1] in REQUIRED_FIELDS
            for k in enriched['modelled_weather_input_evidence']),
        'weather_optional_slots_connected': sum(k.split('/')[-1] not in REQUIRED_FIELDS
            for k in enriched['modelled_weather_input_evidence']),
        'on_site_measurements_created': 0,
        'public_plaintext_written': False,
        'production_aes_archived': False, 'live_model_invoked': False,
    }
