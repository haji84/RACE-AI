"""Publisher-labelled LIVE seek points, never verified exhibition intervals.

The official UI maps position_1..5 to its five chapter labels and passes their
values to player.currentTime(). Its time origin, actual frames and physical
event clock remain unverified. No schedule-start-plus-offset conversion occurs.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

from .core import SourceError
from .exhibition_video_source import PLAYER, STADIUMS, SourceResponse, bounded_fetch
from web.race_contract import JST, canonical, stamp

MAX_BYTES = 65536
TIMEOUT = 10
MAX_PARENT_AGE = 90
MAX_SEEK_SECONDS = 86400
LABELS = ('展示ピットアウト', '周回展示', '本番ピットアウト', 'スタート直前', '1マーク')
POSITION_KEYS = {f'position_{n}' for n in range(1, 6)}
SCHEDULE_KEYS = {'schema_version', 'venue_code', 'stadium', 'requested_day_jst', 'player_url',
                 'source_url', 'source_sha256', 'requested_at', 'captured_at', 'setting_updated_at',
                 'channel_ref', 'scheduled_start_at', 'scheduled_end_at', 'schedule_status',
                 'race_binding_status', 'exhibition_detection_status', 'wall_clock_alignment_status',
                 'prediction_input_eligible', 'boat_features', 'model_validation_status', 'snapshot_id'}


def require(condition, error):
    if not condition:
        raise SourceError(error)


def utc_now():
    return datetime.now(timezone.utc)


def instant(value):
    return datetime.fromisoformat(stamp(value))


def digest(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def validate_schedule(schedule, now):
    require(type(schedule) is dict and set(schedule) == SCHEDULE_KEYS, 'LIVE_CHAPTER_PARENT_FIELDS_INVALID')
    require(digest(schedule['snapshot_id']) and schedule['snapshot_id'] == hashlib.sha256(canonical(
        {k:v for k,v in schedule.items() if k != 'snapshot_id'})).hexdigest(), 'LIVE_CHAPTER_PARENT_HASH_INVALID')
    require(all(type(v) is str for k,v in schedule.items() if k not in {'prediction_input_eligible', 'boat_features'}),
            'LIVE_CHAPTER_PARENT_TYPES_INVALID')
    venue = schedule['venue_code']
    require(venue in STADIUMS and schedule['stadium'] == STADIUMS[venue], 'LIVE_CHAPTER_PARENT_VENUE_INVALID')
    stadium = STADIUMS[venue]
    player = (f'{PLAYER}/player/live?service=boatcast&stadium={stadium}'
              '&sourceType=mix&dvr=1&audioMode=0&autoplay=0&bitrate=low')
    require(schedule['schema_version'] == 'normal-live-schedule/v1' and digest(schedule['source_sha256'])
            and schedule['source_url'] == f'{PLAYER}/setting/live/{stadium}/setting.json'
            and schedule['player_url'] == player and schedule['channel_ref'] == f'lm-mix-{stadium}-tokyo',
            'LIVE_CHAPTER_PARENT_SCOPE_INVALID')
    require(schedule['prediction_input_eligible'] is False and type(schedule['boat_features']) is list
            and schedule['boat_features'] == [] and schedule['model_validation_status'] == 'UNVALIDATED'
            and all(schedule[k] == 'UNVERIFIED' for k in ('race_binding_status', 'exhibition_detection_status',
                                                          'wall_clock_alignment_status')),
            'LIVE_CHAPTER_PARENT_GATES_INVALID')
    requested, captured = instant(schedule['requested_at']), instant(schedule['captured_at'])
    updated = instant(schedule['setting_updated_at'])
    begin, end = instant(schedule['scheduled_start_at']), instant(schedule['scheduled_end_at'])
    day = now.astimezone(JST).date()
    require(schedule['requested_day_jst'] == day.isoformat()
            and requested.astimezone(JST).date() == captured.astimezone(JST).date() == begin.astimezone(JST).date() == day
            and 0 <= (captured-requested).total_seconds() <= TIMEOUT
            and 0 <= (now-captured).total_seconds() <= MAX_PARENT_AGE
            and updated <= captured and 0 < (end-begin).total_seconds() <= 86400,
            'LIVE_CHAPTER_PARENT_CLOCK_INVALID')
    status = 'SCHEDULE_FUTURE' if captured < begin else 'SCHEDULE_ENDED' if captured >= end else 'SCHEDULE_ACTIVE'
    require(schedule['schedule_status'] == status, 'LIVE_CHAPTER_PARENT_STATUS_INVALID')
    return stadium, day


def object_pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'LIVE_CHAPTER_DUPLICATE_KEY')
        value[key] = item
    return value


def reject_number(value):
    raise SourceError('LIVE_CHAPTER_NUMBER_INVALID')


def resolve_live_chapters(schedule, *, fetch=None, clock=utc_now):
    """One metadata GET with a fresh parent; no playback, seek, or media request."""
    try:
        started = instant(clock())
        # Keep one immutable-by-ownership parent throughout the request, even
        # when a custom transport or concurrent caller mutates its input dict.
        schedule = json.loads(canonical(schedule))
        stadium, day = validate_schedule(schedule, started)
        url = f'{PLAYER}/setting/chapter/{stadium}/mix/chapter.json'
        headers = {'Accept':'application/json', 'User-Agent':'RaceAI bounded LIVE chapter metadata',
                   'Origin':PLAYER, 'Referer':schedule['player_url']}
        try:
            response = (fetch or bounded_fetch)(url, headers=headers, max_bytes=MAX_BYTES, timeout=TIMEOUT)
        except Exception:
            raise SourceError('LIVE_CHAPTER_UNAVAILABLE') from None
        captured = instant(clock())
        require(0 <= (captured-started).total_seconds() <= TIMEOUT
                and captured.astimezone(JST).date() == day, 'LIVE_CHAPTER_CAPTURE_CLOCK_INVALID')
        validate_schedule(schedule, captured)
        require(isinstance(response, SourceResponse) and type(response.status) is int and response.status == 200
                and response.url == url, 'LIVE_CHAPTER_RESPONSE_INVALID')
        require(type(response.content_type) is str
                and response.content_type.split(';',1)[0].lower() == 'application/json', 'LIVE_CHAPTER_MIME_INVALID')
        require(type(response.body) is bytes and 1 <= len(response.body) <= MAX_BYTES, 'LIVE_CHAPTER_BYTES_INVALID')
        value = json.loads(response.body.decode('utf-8-sig'), object_pairs_hook=object_pairs,
                           parse_constant=reject_number, parse_float=reject_number)
        require(type(value) is dict and set(value) == {'race','update_from','last_update'}, 'LIVE_CHAPTER_FIELDS_INVALID')
        require(type(value['update_from']) is str and 1 <= len(value['update_from']) <= 100
                and type(value['last_update']) is str, 'LIVE_CHAPTER_UPDATE_INVALID')
        updated = instant(value['last_update'])
        require(updated.astimezone(JST).date() == day and updated <= captured, 'LIVE_CHAPTER_UPDATE_INVALID')
        require(type(value['race']) is list and len(value['race']) == 12, 'LIVE_CHAPTER_SLOTS_INVALID')
        races, previous, missing, count = [], 0, False, 0
        for number, row in enumerate(value['race'], 1):
            require(type(row) is dict and set(row) == POSITION_KEYS, 'LIVE_CHAPTER_ROW_INVALID')
            anchors = []
            for position, label in enumerate(LABELS, 1):
                key = f'position_{position}'
                offset = row[key]
                if type(offset) is str and offset == '':
                    missing = True
                    seconds = None
                else:
                    require(type(offset) is int and 0 < offset <= MAX_SEEK_SECONDS,
                            'LIVE_CHAPTER_SEEK_INVALID')
                    require(not missing and offset > previous, 'LIVE_CHAPTER_ORDER_UNSUPPORTED')
                    previous, seconds, count = offset, offset, count+1
                anchors.append(dict(position_key=key, publisher_label=label,
                                    publisher_phase='EXHIBITION' if position <= 2 else 'RACE', seek_seconds=seconds))
            races.append(dict(indexed_race_number=number, anchors=anchors))
        result = dict(schema_version='normal-live-chapters/v1', venue_code=schedule['venue_code'], stadium=stadium,
                      requested_day_jst=day.isoformat(), schedule_snapshot_id=schedule['snapshot_id'],
                      channel_ref=schedule['channel_ref'], source_url=url,
                      source_sha256=hashlib.sha256(response.body).hexdigest(),
                      requested_at=stamp(started), captured_at=stamp(captured), publisher_updated_at=stamp(updated),
                      status='INDEXED_SEEK_POINTS' if count else 'PENDING', indexed_race_slots=12,
                      published_seek_points=count, races=races, player_time_origin='UNVERIFIED',
                      frame_race_phase_verification='UNVERIFIED', physical_exhibition_timing='UNVERIFIED',
                      prediction_input_eligible=False, boat_features=[], model_validation_status='UNVALIDATED')
        result['snapshot_id'] = hashlib.sha256(canonical(result)).hexdigest()
        return result
    except SourceError:
        raise
    except Exception:
        raise SourceError('LIVE_CHAPTER_INVALID') from None
