"""Bounded HLS source-declared segment clocks, never physical-event clock proof.

RFC 8216 4.3.2.6 maps PROGRAM-DATE-TIME to a segment's first media sample.
This assessor does not map decoded video PTS to that first media sample, verify
the provider's clock, or identify an exhibition event. Every segment requires
an explicit anchor; no extrapolated, missing, or partial clock is promoted.
Resource authorization/decryption/decoding remain the caller's separate gates.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import math
import re
from zoneinfo import ZoneInfo


MAX_BYTES = 1024 * 1024
MAX_SEGMENTS = 100
MAX_LINES = 2500
JST = ZoneInfo('Asia/Tokyo')
DATETIME = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?'
                      r'(?:Z|[+-](?:(?:0\d|1[0-3]):[0-5]\d|14:00))')
DURATION = re.compile(r'\d{1,2}(?:\.\d{1,6})?')


class _Rejected(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise _Rejected(code)


def _instant(value):
    if isinstance(value, str):
        if not DATETIME.fullmatch(value):
            raise ValueError('clock shape')
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('aware clock required')
    if abs(value.utcoffset()) > timedelta(hours=14):
        raise ValueError('clock offset outside bounds')
    return value.astimezone(timezone.utc)


def _stamp(value):
    return value.isoformat(timespec='microseconds')


def _empty():
    return dict(schema_version=1, status='UNVERIFIED_PROGRAM_CLOCK_STRUCTURE',
        source_clock_consistent=False, playlist_sha256=None, segment_count=0,
        explicit_anchor_count=0, discontinuity_count=0, declared_clip_start_at=None,
        declared_clip_end_at=None, segment_boundaries=[],
        timing_scope='SOURCE_DECLARED_SEGMENT_BOUNDARIES_ONLY', frame_time_mapping='NOT_COMPUTED',
        coverage_scope='WHOLE_PLAYLIST_METADATA_NOT_DECODE_COVERAGE',
        independent_clock_verified=False, physical_exhibition_time_verified=False,
        prediction_eligible=False, raw_manifest_or_resource_locations_retained=False)


def assess_program_clock(raw, segments, *, closed_at, captured_at):
    """Assess an already scoped VOD's exact segment metadata without any I/O.

    `segments` contains only sequence/duration/discontinuity, never URLs/keys.
    A forward rounding gap <=1 ms is retained explicitly; any overlap fails.
    Source-declared segment ends must precede close and not exceed capture.
    A quality failure returns no usable timestamps, even for a valid prefix.
    """
    result = _empty()
    try:
        try:
            close, capture = _instant(closed_at), _instant(captured_at)
        except (ValueError, TypeError, OverflowError):
            raise _Rejected('UNVERIFIED_PROGRAM_CLOCK_CONTEXT') from None
        day = close.astimezone(JST).date()
        _require(capture.astimezone(JST).date() == day, 'UNVERIFIED_PROGRAM_CLOCK_CONTEXT')
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
        result['playlist_sha256'] = hashlib.sha256(raw).hexdigest()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeError:
            raise _Rejected('UNVERIFIED_PROGRAM_CLOCK_STRUCTURE') from None
        _require(all(char in '\r\n\t' or 32 <= ord(char) <= 126 for char in text),
                 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        _require(0 < len(lines) <= MAX_LINES and lines[0] == '#EXTM3U' and lines.count('#EXTM3U') == 1
                 and [line for line in lines if line.startswith('#EXT-X-PLAYLIST-TYPE')] == ['#EXT-X-PLAYLIST-TYPE:VOD']
                 and lines[-1] == '#EXT-X-ENDLIST' and lines.count('#EXT-X-ENDLIST') == 1,
                 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
        # Malformed known tags must not disappear as ignored HLS extensions.
        for line in lines:
            for prefix in ('#EXTINF', '#EXT-X-PROGRAM-DATE-TIME', '#EXT-X-MEDIA-SEQUENCE',
                           '#EXT-X-DISCONTINUITY-SEQUENCE'):
                if line.startswith(prefix):
                    _require(line.startswith(prefix + ':'), 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
            for prefix in ('#EXTM3U', '#EXT-X-ENDLIST', '#EXT-X-DISCONTINUITY'):
                if line.startswith(prefix) and not line.startswith('#EXT-X-DISCONTINUITY-SEQUENCE:'):
                    _require(line == prefix, 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
        discontinuity_sequences = [line.split(':', 1)[1] for line in lines
                                   if line.startswith('#EXT-X-DISCONTINUITY-SEQUENCE:')]
        _require(len(discontinuity_sequences) <= 1 and all(re.fullmatch(r'\d{1,15}', v)
                 for v in discontinuity_sequences), 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
        seq = [line.split(':', 1)[1] for line in lines if line.startswith('#EXT-X-MEDIA-SEQUENCE:')]
        _require(len(seq) == 1 and re.fullmatch(r'\d{1,15}', seq[0]), 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
        sequence = int(seq[0])
        _require(type(segments) is list and 1 <= len(segments) <= MAX_SEGMENTS,
                 'UNVERIFIED_PROGRAM_CLOCK_SEGMENTS')
        for row in segments:
            _require(type(row) is dict and set(row) == {'sequence', 'duration', 'discontinuity'}
                     and type(row['sequence']) is int and type(row['discontinuity']) is bool
                     and type(row['duration']) in (int, float) and 0 < row['duration'] <= 20
                     and math.isfinite(row['duration']), 'UNVERIFIED_PROGRAM_CLOCK_SEGMENTS')
        parsed = []; anchor = duration = None; discontinuity = False
        for line in lines[1:]:
            if line.startswith('#EXT-X-PROGRAM-DATE-TIME:'):
                _require(anchor is None, 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
                anchor = line.split(':', 1)[1]
            elif line == '#EXT-X-DISCONTINUITY':
                _require(not discontinuity, 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
                discontinuity = True
            elif line.startswith('#EXTINF:'):
                value = line.split(':', 1)[1].split(',', 1)[0]
                _require(duration is None and DURATION.fullmatch(value), 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
                duration = Decimal(value)
                _require(0 < duration <= 20, 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
            elif not line.startswith('#'):
                _require(duration is not None and len(parsed) < MAX_SEGMENTS, 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
                parsed.append(dict(sequence=sequence, duration=duration, anchor=anchor, discontinuity=discontinuity))
                sequence += 1; anchor = duration = None; discontinuity = False
        _require(anchor is None and duration is None and not discontinuity and parsed
                 and sum(row['duration'] for row in parsed) <= 600, 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')
        result['segment_count'] = len(parsed)
        result['explicit_anchor_count'] = sum(row['anchor'] is not None for row in parsed)
        result['discontinuity_count'] = sum(row['discontinuity'] for row in parsed)
        _require(len(parsed) == len(segments), 'UNVERIFIED_PROGRAM_CLOCK_SEGMENTS')
        for actual, expected in zip(parsed, segments):
            _require(actual['sequence'] == expected['sequence']
                     and actual['duration'] == Decimal(str(expected['duration']))
                     and actual['discontinuity'] == expected['discontinuity'], 'UNVERIFIED_PROGRAM_CLOCK_SEGMENTS')
        _require(result['explicit_anchor_count'] == len(parsed), 'UNVERIFIED_MISSING_SEGMENT_ANCHOR')
        boundaries = []; previous_end = None
        for row in parsed:
            try:
                start = _instant(row['anchor'])
                end = start + timedelta(microseconds=int(row['duration'] * 1000000))
            except (ValueError, TypeError, OverflowError):
                raise _Rejected('UNVERIFIED_PROGRAM_CLOCK_VALUE') from None
            _require(start.astimezone(JST).date() == day and end.astimezone(JST).date() == day,
                     'UNVERIFIED_PROGRAM_CLOCK_DAY')
            _require(end <= capture, 'UNVERIFIED_PROGRAM_CLOCK_FUTURE')
            _require(end < close, 'UNVERIFIED_PROGRAM_CLOCK_CUTOFF')
            gap = (start - previous_end).total_seconds() if previous_end is not None else 0.0
            _require(gap >= 0 and (row['discontinuity'] or gap <= .001),
                     'UNVERIFIED_PROGRAM_CLOCK_CONTINUITY')
            boundaries.append(dict(sequence=row['sequence'], program_start_at=_stamp(start),
                program_end_at=_stamp(end), duration_seconds=float(row['duration']),
                discontinuity=row['discontinuity'], gap_before_seconds=gap))
            previous_end = end
        result.update(status='SOURCE_DECLARED_CLOCK_CONSISTENT', source_clock_consistent=True,
            declared_clip_start_at=boundaries[0]['program_start_at'],
            declared_clip_end_at=boundaries[-1]['program_end_at'], segment_boundaries=boundaries)
    except _Rejected as error:
        result['status'] = str(error)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        result['status'] = 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE'
    return result
