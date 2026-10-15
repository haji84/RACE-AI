"""Bounded ordinary public-player metadata resolver, not video/CV analysis.

Only the observed Naruto mapping is supported. No media GETs, keys, DRM work,
original retention or new permission are provided here. Signed playback URLs
live only inside a nonserializable one-use transient-processing lease.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit, parse_qs, urlunsplit

from .core import SourceError
from web.race_contract import canonical, program_digest, stamp, JST

PLAYER = 'https://front.player.boatrace-cdn.jp'
PROJECT = 'cp-boatrace-prod'
STADIUMS = {'14': '14naruto'}
MAX_BYTES = 1024 * 1024
MAX_DERIVED_BYTES = 256000
TIMEOUT = 10
TOP = {'schema_version', 'race_id', 'closed_at', 'program_identity_sha256', 'stadium',
       'project_id', 'recording_ref', 'status', 'sources', 'recording_index_last_update',
       'media', 'capture_eligible_pre_race', 'model_validation_status', 'boat_features', 'snapshot_id'}


def require(condition, message):
    if not condition:
        raise SourceError(message)


def utc_now():
    return datetime.now(timezone.utc)


def instant(value):
    return datetime.fromisoformat(stamp(value))


def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected), 'VIDEO_SOURCE_FIELDS_INVALID')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class SourceResponse:
    status: int
    url: str = field(repr=False)
    content_type: str
    body: bytes = field(repr=False)


def bounded_fetch(url, *, headers, max_bytes, timeout):
    """Only called for exact index/API URLs; errors never echo request bodies."""
    try:
        request = urllib.request.Request(url, headers=headers, method='GET')
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            return SourceResponse(response.status, response.geturl(), response.headers.get_content_type(), raw)
    except urllib.error.HTTPError as exc:
        code = 'VIDEO_SOURCE_AUTH_UNAVAILABLE' if exc.code in (401, 403) else 'VIDEO_SOURCE_HTTP_UNAVAILABLE'
        raise SourceError(code) from None
    except Exception:
        raise SourceError('VIDEO_SOURCE_TRANSPORT_UNAVAILABLE') from None


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'VIDEO_SOURCE_DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _constant(value):
    raise SourceError('VIDEO_SOURCE_NONFINITE_JSON')


def _float(value):
    number = float(value)
    require(math.isfinite(number), 'VIDEO_SOURCE_NONFINITE_JSON')
    return number


def _read(url, headers, fetch, clock, component):
    try:
        response = fetch(url, headers=headers, max_bytes=MAX_BYTES, timeout=TIMEOUT)
        require(isinstance(response, SourceResponse) and type(response.status) is int
                and response.status == 200 and response.url == url, 'VIDEO_SOURCE_RESPONSE_INVALID')
        require(response.content_type.split(';', 1)[0].lower() == 'application/json', 'VIDEO_SOURCE_MIME_INVALID')
        require(isinstance(response.body, bytes) and 1 <= len(response.body) <= MAX_BYTES,
                'VIDEO_SOURCE_BYTES_OUTSIDE_BOUNDS')
        captured = stamp(clock())
        data = json.loads(response.body.decode('utf-8-sig'), object_pairs_hook=_object,
                          parse_constant=_constant, parse_float=_float)
        require(isinstance(data, dict), 'VIDEO_SOURCE_JSON_INVALID')
        source = dict(component=component, source_url=url,
                      source_sha256=hashlib.sha256(response.body).hexdigest(),
                      captured_at=captured, available_at=captured)
        return data, source
    except SourceError:
        raise
    except Exception:
        raise SourceError('VIDEO_SOURCE_RESPONSE_INVALID') from None


def _paths(race, stadium):
    race_id = race['race_id']
    program_digest(race)
    require(STADIUMS.get(race_id[9:11]) == stadium, 'VIDEO_STADIUM_UNVERIFIED')
    day, number = race_id[:8], race_id[-2:]
    ref = f'mix-{stadium}-exhibition-{day}-{number}'
    index = f'{PLAYER}/setting/vod/{day}/{stadium}/exhibition/setting.json'
    api = f'https://playback.api.streaks.jp/v1/projects/{PROJECT}/medias/ref:{ref}'
    player = f'{PLAYER}/player/vod?service=boatcast&stadium={stadium}&raceType=exhibition&raceDate={day}&raceNumber={number}&autoplay=0&bitrate=low'
    return index, api, player, ref


def _duration(value):
    require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 1200,
            'VIDEO_SOURCE_DURATION_INVALID')


def _hex(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{32}', value) is not None


def _resource(value, media_id, source_id, *, signed):
    require(isinstance(value, str) and len(value) <= 16384
            and all(32 < ord(character) <= 126 for character in value), 'VIDEO_RESOURCE_INVALID')
    parsed = urlsplit(value)
    require(parsed.scheme == 'https' and parsed.netloc == 'manifest.streaks.jp'
            and not parsed.fragment, 'VIDEO_RESOURCE_SCOPE_INVALID')
    path = f'/v6/{PROJECT}/{media_id}/{source_id}/hls/v3/manifest.m3u8'
    require(_hex(media_id) and _hex(source_id) and parsed.path == path, 'VIDEO_RESOURCE_IDENTITY_INVALID')
    if signed:
        query = parse_qs(parsed.query, keep_blank_values=True)
        require(set(query) == {'token'} and len(query['token']) == 1
                and 0 < len(query['token'][0]) <= 8192
                and re.fullmatch(r'[A-Za-z0-9._~+/=-]+', query['token'][0]) is not None,
                'VIDEO_RESOURCE_QUERY_INVALID')
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
    require(not parsed.query, 'VIDEO_DESCRIPTOR_CONTAINS_QUERY')
    return value


class EphemeralMediaLease:
    """RAM-only URL; trusted consumer receives it once, never ordinary serializers."""
    __slots__ = ('__url',)

    def __init__(self, url):
        self.__url = url

    def __repr__(self):
        return '<EphemeralMediaLease redacted>'

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError('ephemeral media leases cannot be serialized')

    def consume(self, processor):
        url = self.__url
        self.__url = None
        require(url is not None, 'VIDEO_LEASE_ALREADY_CONSUMED')
        try:
            result = processor(url)
            encoded = canonical(result)
            require(len(encoded) <= MAX_DERIVED_BYTES, 'VIDEO_DERIVED_BYTES_OUTSIDE_BOUNDS')
            token = parse_qs(urlsplit(url).query)['token'][0]
            require(url.encode() not in encoded and token.encode() not in encoded,
                    'VIDEO_PROCESSOR_OUTPUT_REJECTED')
            return result
        except Exception:
            raise SourceError('VIDEO_TRANSIENT_PROCESSOR_FAILED') from None
        finally:
            url = None


def resolve_exhibition_source(race, *, stadium='14naruto', fetch=None, clock=utc_now,
                              player_duration_seconds=None):
    """At most index+metadata GETs; no playback resource is ever fetched here."""
    try:
        start = instant(clock())
        index_url, metadata_url, player_url, ref = _paths(race, stadium)
        require(instant(race['closed_at']).astimezone(JST).date() == start.astimezone(JST).date(),
                'CURRENT_VIDEO_RACE_REQUIRED')
        if player_duration_seconds is not None:
            _duration(player_duration_seconds)
        headers = {'Accept': 'application/json', 'User-Agent': 'RaceAI bounded public-player metadata',
                   'Origin': PLAYER, 'Referer': player_url}
        fetch = fetch or bounded_fetch
        index, first = _read(index_url, headers, fetch, clock, 'recording_index')
        keys(index, {'races', 'update_from', 'last_update'})
        require(isinstance(index['update_from'], str) and 0 < len(index['update_from']) <= 100,
                'VIDEO_RECORDING_INDEX_INVALID')
        keys(index['races'], {f'{n:02d}' for n in range(1, 13)})
        for number, row in index['races'].items():
            keys(row, {'race_number', 'ref_id', 'source_type'})
            expected = f'mix-{stadium}-exhibition-{race["race_id"][:8]}-{number}'
            require(row['race_number'] == number and
                    ((row['ref_id'] == expected and row['source_type'] == 'mix') or
                     (row['ref_id'] == '' and row['source_type'] == '')), 'VIDEO_RECORDING_IDENTITY_INVALID')
        update = stamp(index['last_update'])
        require(instant(update) <= instant(first['captured_at']), 'VIDEO_RECORDING_UPDATE_IN_FUTURE')
        value = dict(schema_version=1, race_id=race['race_id'], closed_at=stamp(race['closed_at']),
                     program_identity_sha256=program_digest(race), stadium=stadium, project_id=PROJECT,
                     recording_ref='', status='PENDING', sources=[first], recording_index_last_update=update,
                     media=None, model_validation_status='UNVALIDATED', boat_features='NONE')
        lease = None
        selected = index['races'][race['race_id'][-2:]]
        if selected['ref_id']:
            media, second = _read(metadata_url, headers, fetch, clock, 'playback_metadata')
            require(media.get('project_id') == PROJECT and media.get('ref_id') == ref
                    and media.get('type') == 'clip' and _hex(media.get('id')), 'VIDEO_METADATA_IDENTITY_INVALID')
            _duration(media.get('duration'))
            require(type(media.get('offline_enabled')) is bool and isinstance(media.get('sources'), list)
                    and len(media['sources']) == 1, 'VIDEO_METADATA_SOURCES_INVALID')
            stream = media['sources'][0]
            require(isinstance(stream, dict) and stream.get('type') == 'application/x-mpegURL'
                    and 'key_systems' not in stream and _hex(stream.get('id')), 'VIDEO_METADATA_DRM_OR_TYPE_UNSUPPORTED')
            safe_url = _resource(stream.get('src'), media['id'], stream['id'], signed=True)
            value.update(status='AVAILABLE', recording_ref=ref, sources=[first, second],
                         media=dict(id=media['id'], source_id=stream['id'], type='clip',
                             duration_metadata_raw=media['duration'], duration_metadata_unit='SOURCE_RAW_UNIT_NOT_CONFIRMED',
                             duration_player_observed_seconds=player_duration_seconds,
                             duration_comparison='DISTINCT_SOURCE_OBSERVATIONS', offline_enabled=media['offline_enabled'],
                             stream_type=stream['type'], source_url_without_query=safe_url))
            lease = EphemeralMediaLease(stream['src'])
        value['capture_eligible_pre_race'] = all(instant(s['captured_at']) < instant(value['closed_at']) for s in value['sources'])
        value['snapshot_id'] = hashlib.sha256(canonical(value)).hexdigest()
        final = stamp(clock())
        require(start <= instant(first['captured_at']) <= instant(final), 'VIDEO_SOURCE_CLOCK_MOVED_BACKWARD')
        validate_descriptor(value, race, final)
        return value, lease
    except SourceError:
        raise
    except Exception:
        raise SourceError('VIDEO_SOURCE_CONTRACT_INVALID') from None


def validate_descriptor(value, race, now):
    """Recheck safe persisted derivative only; never confers a cloud-save proof."""
    try:
        keys(value, TOP)
        require(value['snapshot_id'] == hashlib.sha256(canonical({k:v for k,v in value.items() if k != 'snapshot_id'})).hexdigest(),
                'VIDEO_DESCRIPTOR_HASH_INVALID')
        index_url, metadata_url, _, ref = _paths(race, value['stadium'])
        close, clock = instant(race['closed_at']), instant(now)
        require(type(value['schema_version']) is int and value['schema_version'] == 1
                and value['race_id'] == race['race_id'] and value['closed_at'] == stamp(close)
                and value['program_identity_sha256'] == program_digest(race)
                and value['project_id'] == PROJECT and value['model_validation_status'] == 'UNVALIDATED'
                and value['boat_features'] == 'NONE', 'VIDEO_DESCRIPTOR_IDENTITY_INVALID')
        available = value['status'] == 'AVAILABLE'
        require(value['status'] in {'AVAILABLE', 'PENDING'} and isinstance(value['sources'], list)
                and len(value['sources']) == (2 if available else 1), 'VIDEO_DESCRIPTOR_STATUS_INVALID')
        captures = []
        for source, component, url in zip(value['sources'], ('recording_index', 'playback_metadata'), (index_url, metadata_url)):
            keys(source, {'component', 'source_url', 'source_sha256', 'captured_at', 'available_at'})
            captured = instant(source['captured_at'])
            require(source['component'] == component and source['source_url'] == url
                    and isinstance(source['source_sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', source['source_sha256']) is not None
                    and instant(source['available_at']) == captured <= clock
                    and captured.astimezone(JST).date() == close.astimezone(JST).date(), 'VIDEO_DESCRIPTOR_SOURCE_INVALID')
            captures.append(captured)
        require(captures == sorted(captures) and instant(value['recording_index_last_update']) <= captures[0]
                and instant(value['recording_index_last_update']).astimezone(JST).date() == close.astimezone(JST).date(),
                'VIDEO_DESCRIPTOR_UPDATE_INVALID')
        require(type(value['capture_eligible_pre_race']) is bool
                and value['capture_eligible_pre_race'] == all(t < close for t in captures), 'VIDEO_DESCRIPTOR_PHASE_INVALID')
        if not available:
            require(value['media'] is None and value['recording_ref'] == '', 'VIDEO_PENDING_CONTAINS_MEDIA')
            return
        require(value['recording_ref'] == ref, 'VIDEO_DESCRIPTOR_RECORDING_INVALID')
        media = value['media']
        keys(media, {'id', 'source_id', 'type', 'duration_metadata_raw', 'duration_metadata_unit',
                     'duration_player_observed_seconds', 'duration_comparison', 'offline_enabled',
                     'stream_type', 'source_url_without_query'})
        require(_hex(media['id']) and _hex(media['source_id']) and media['type'] == 'clip'
                and media['duration_metadata_unit'] == 'SOURCE_RAW_UNIT_NOT_CONFIRMED'
                and media['duration_comparison'] == 'DISTINCT_SOURCE_OBSERVATIONS'
                and type(media['offline_enabled']) is bool and media['stream_type'] == 'application/x-mpegURL',
                'VIDEO_DESCRIPTOR_MEDIA_INVALID')
        _duration(media['duration_metadata_raw'])
        if media['duration_player_observed_seconds'] is not None:
            _duration(media['duration_player_observed_seconds'])
        _resource(media['source_url_without_query'], media['id'], media['source_id'], signed=False)
    except SourceError:
        raise
    except Exception:
        raise SourceError('VIDEO_DESCRIPTOR_INVALID') from None
