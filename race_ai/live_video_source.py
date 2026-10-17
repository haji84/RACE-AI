"""One public LIVE schedule GET, separate from the exhibition VOD contract.

An active schedule does not identify the pictures, race, phase, or frame clock.
This reader never requests playback metadata, manifests, segments or keys, and
never returns a media lease or usable prediction input.
"""
from datetime import datetime, timezone
import hashlib
import json

from .core import SourceError
from .exhibition_video_source import PLAYER, STADIUMS, SourceResponse, bounded_fetch
from web.race_contract import JST, canonical, stamp

MAX_BYTES = 16384
TIMEOUT = 10
ROWS = {'br_live', 'br_dvr', 'mix_live', 'mix_dvr'}
FIELDS = {'ref_id', 'type', 'region', 'source_type', 'start_at', 'end_at'}
PUBLIC_ROUTE_EVIDENCE = {
    'source_url': PLAYER + '/js/live.js',
    'source_sha256': 'eeb812473c139e2f32127b3e49774ffdeb48c97cef7821598e0e191f7ae465d8',
    'captured_at': '2026-10-16T07:25:00.210263+00:00',
    'observed_setting_url': PLAYER + '/setting/live/24omura/setting.json',
    'scope': 'PUBLIC_SCHEDULE_ONLY_NOT_PLAYBACK_OR_RACE_IDENTITY',
}


def require(condition, error):
    if not condition:
        raise SourceError(error)


def utc_now():
    return datetime.now(timezone.utc)


def instant(value):
    return datetime.fromisoformat(stamp(value))


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'LIVE_SETTING_DUPLICATE_KEY')
        result[key] = value
    return result


def reject_number(value):
    raise SourceError('LIVE_SETTING_NUMBER_INVALID')


def resolve_live_schedule(venue_code, *, fetch=None, clock=utc_now):
    """Read one exact current-day venue schedule, with no retry or media GET."""
    try:
        require(type(venue_code) is str and venue_code in STADIUMS, 'LIVE_VENUE_INVALID')
        started = instant(clock())
        day = started.astimezone(JST).date()
        stadium = STADIUMS[venue_code]
        url = f'{PLAYER}/setting/live/{stadium}/setting.json'
        player = (f'{PLAYER}/player/live?service=boatcast&stadium={stadium}'
                  '&sourceType=mix&dvr=1&audioMode=0&autoplay=0&bitrate=low')
        headers = {'Accept': 'application/json', 'User-Agent': 'RaceAI bounded LIVE schedule metadata',
                   'Origin': PLAYER, 'Referer': player}
        try:
            response = (fetch or bounded_fetch)(url, headers=headers, max_bytes=MAX_BYTES, timeout=TIMEOUT)
        except Exception:
            raise SourceError('LIVE_SETTING_UNAVAILABLE') from None
        captured = instant(clock())
        require(started <= captured and (captured - started).total_seconds() <= TIMEOUT
                and captured.astimezone(JST).date() == day, 'LIVE_CAPTURE_CLOCK_INVALID')
        require(isinstance(response, SourceResponse) and type(response.status) is int
                and response.status == 200 and response.url == url, 'LIVE_SETTING_RESPONSE_INVALID')
        require(isinstance(response.content_type, str)
                and response.content_type.split(';', 1)[0].lower() == 'application/json', 'LIVE_SETTING_MIME_INVALID')
        require(type(response.body) is bytes and 1 <= len(response.body) <= MAX_BYTES,
                'LIVE_SETTING_BYTES_INVALID')
        value = json.loads(response.body.decode('utf-8-sig'), object_pairs_hook=object_pairs,
                           parse_constant=reject_number, parse_float=reject_number)
        require(type(value) is dict and set(value) == ROWS | {'update_from', 'last_update'},
                'LIVE_SETTING_FIELDS_INVALID')
        require(type(value['update_from']) is str and 1 <= len(value['update_from']) <= 100,
                'LIVE_SETTING_UPDATE_INVALID')
        require(type(value['last_update']) is str, 'LIVE_SETTING_UPDATE_INVALID')
        updated = instant(value['last_update'])
        require(updated <= captured, 'LIVE_SETTING_UPDATE_INVALID')
        windows = {}
        for key in sorted(ROWS):
            row = value[key]
            source, kind = key.split('_')
            require(type(row) is dict and set(row) == FIELDS
                    and all(type(v) is str for v in row.values()), 'LIVE_SETTING_ROW_INVALID')
            # Only the independently observed region and exact public ref form
            # are supported. Unknown schemas/regions stop; they do not widen VOD.
            ref = f'lm-{source}-{stadium}-tokyo' + (f'-{day:%Y%m%d}' if kind == 'dvr' else '')
            require(row['type'] == kind and row['region'] == 'tokyo'
                    and row['source_type'] == source and row['ref_id'] == ref,
                    'LIVE_SETTING_IDENTITY_INVALID')
            begin, end = instant(row['start_at']), instant(row['end_at'])
            require(begin.astimezone(JST).date() == day and begin < end
                    and (end - begin).total_seconds() <= 86400, 'LIVE_SETTING_WINDOW_INVALID')
            windows[key] = begin, end
        for source in ('br', 'mix'):
            require(windows[f'{source}_live'] == windows[f'{source}_dvr'], 'LIVE_SETTING_PAIR_INVALID')
        begin, end = windows['mix_live']
        status = 'SCHEDULE_FUTURE' if captured < begin else 'SCHEDULE_ENDED' if captured >= end else 'SCHEDULE_ACTIVE'
        result = dict(schema_version='normal-live-schedule/v1', venue_code=venue_code,
                      stadium=stadium, requested_day_jst=day.isoformat(), player_url=player,
                      source_url=url, source_sha256=hashlib.sha256(response.body).hexdigest(),
                      requested_at=stamp(started), captured_at=stamp(captured),
                      setting_updated_at=stamp(updated), channel_ref=value['mix_live']['ref_id'],
                      scheduled_start_at=stamp(begin), scheduled_end_at=stamp(end),
                      schedule_status=status, race_binding_status='UNVERIFIED',
                      exhibition_detection_status='UNVERIFIED', wall_clock_alignment_status='UNVERIFIED',
                      prediction_input_eligible=False, boat_features=[], model_validation_status='UNVALIDATED')
        result['snapshot_id'] = hashlib.sha256(canonical(result)).hexdigest()
        return result
    except SourceError:
        raise
    except Exception:
        raise SourceError('LIVE_SETTING_INVALID') from None
