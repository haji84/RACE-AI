"""Opt-in, registered normal-player transport grammar; no source-owner authentication.

The frozen registration is private. Only its canonical digest is a trust anchor
here. Asset cooccurrence is not proof of namespace ownership, physical clocks,
boat identity or performance. Default legacy playback remains a separate path.
"""
from copy import deepcopy
import hashlib
import math
import re
from urllib.parse import urlsplit

from .core import SourceError
from .exhibition_video_source import instant, require
from .exhibition_video_decode import (_attributes, _text, _url, Segment,
                                      MAX_SECONDS, MAX_SEGMENTS)
from web.race_contract import canonical, JST

# Reviewed registration digest, not a caller-selectable namespace allow-list.
REGISTERED_SCOPE_SHA256 = '5eaa11f6677ecb748cef05f6c9bbc13bb1525d67372628cf4041f2ec6220c1b5'
SCOPE_FIELDS = {'schema_version', 'date_jst', 'venue_code', 'observed_target',
                'observed_at', 'evidence_sha256', 'opaque_key_namespace_sha256',
                'namespace_hash_preimage', 'permission_basis', 'transport_only'}
LEGACY_SEGMENT = 'live-cp-boatrace-prod.streaks.jp'
CDN_SEGMENT = 'j-live-cp-boatrace-prod.streaks.jp'
CDN_KEY = 'd28jce9iiridbn.cloudfront.net'
SHA = r'[0-9a-f]{64}'


def validate_normal_player_scope(scope, race, now):
    """Copy and validate the one registered observation, separately from race input.

    This conditional transport permission can cover a new same-venue/day target;
    its resolver must independently establish exact ref -> metadata -> master.
    """
    require(type(scope) is dict and set(scope) == SCOPE_FIELDS,
            'VIDEO_CDN_REGISTRATION_INVALID')
    require(all(type(scope[k]) is str for k in SCOPE_FIELDS - {'transport_only'})
            and scope['transport_only'] is True,
            'VIDEO_CDN_REGISTRATION_INVALID')
    try:
        frozen = deepcopy(scope)
        digest = hashlib.sha256(canonical(frozen)).hexdigest()
    except (ValueError, TypeError, UnicodeError):
        raise SourceError('VIDEO_CDN_REGISTRATION_INVALID') from None
    require(digest == REGISTERED_SCOPE_SHA256, 'VIDEO_CDN_REGISTRATION_UNREGISTERED')
    require(frozen['schema_version'] == 'normal-player-cdn/v1'
            and frozen['namespace_hash_preimage'] == 'RAW_HEX32_ASCII_CASE_SENSITIVE'
            and frozen['permission_basis'] == 'OWNER_20261017_SEPARATE_STRICT_NORMAL_PLAYER_CONTRACT'
            and re.fullmatch(SHA, frozen['evidence_sha256'])
            and re.fullmatch(SHA, frozen['opaque_key_namespace_sha256']),
            'VIDEO_CDN_REGISTRATION_INVALID')
    current = instant(now); observed = instant(frozen['observed_at'])
    day = current.astimezone(JST).date().isoformat()
    require(frozen['date_jst'] == day == observed.astimezone(JST).date().isoformat()
            == instant(race['closed_at']).astimezone(JST).date().isoformat()
            and race['race_id'].split('-')[1] == frozen['venue_code']
            and re.fullmatch(r'\d{8}-' + frozen['venue_code'] + r'-[0-9]{2}', frozen['observed_target'])
            and frozen['observed_target'][:8] == day.replace('-', '')
            and race['race_id'].startswith(day.replace('-', '') + '-' + frozen['venue_code'] + '-')
            and 0 <= (current - observed).total_seconds() <= 21600,
            'VIDEO_CDN_REGISTRATION_CLOCK_OR_TARGET_INVALID')
    return frozen


def _exact_url(value, host, path):
    # Even empty ?/# delimiters are outside the new canonical resource grammar.
    parsed = _url(value, host, path)
    require('#' not in value and not value.endswith('?'), 'VIDEO_CDN_URL_INVALID')
    return parsed


def parse_normal_player_vod(raw, media_id, source_id, variant, *, key_namespace_sha256):
    """Parse only the two explicit transport profiles, never guess unknown resources.

    This pure grammar function is conditional on its namespace argument. Network
    callers must first use validate_normal_player_scope with the pinned digest.
    """
    require(type(key_namespace_sha256) is str and re.fullmatch(SHA, key_namespace_sha256),
            'VIDEO_CDN_NAMESPACE_INVALID')
    require(all(type(x) is str and re.fullmatch(r'[0-9a-f]{32}', x)
                for x in (media_id, source_id)), 'VIDEO_CDN_PARENT_INVALID')
    lines = _text(raw)
    require(lines[-1] == '#EXT-X-ENDLIST' and lines.count('#EXT-X-ENDLIST') == 1
            and lines.count('#EXT-X-PLAYLIST-TYPE:VOD') == 1,
            'VIDEO_HLS_NOT_COMPLETE_VOD')
    seqs = [x.split(':', 1)[1] for x in lines if x.startswith('#EXT-X-MEDIA-SEQUENCE:')]
    require(len(seqs) == 1 and re.fullmatch(r'[0-9]{1,15}', seqs[0]),
            'VIDEO_HLS_SEQUENCE_INVALID')
    sequence = int(seqs[0]); segments = []; duration = None
    key = iv = None; discontinuity = False; profile = None; query_mode = None
    for line in lines[1:]:
        require(not line.startswith(('#EXT-X-BYTERANGE', '#EXT-X-MAP', '#EXT-X-PART', '#EXT-X-SESSION-KEY')),
                'VIDEO_HLS_UNSUPPORTED_RESOURCE')
        require(not (line.startswith('#') and 'URI=' in line and not line.startswith('#EXT-X-KEY:')),
                'VIDEO_HLS_UNSUPPORTED_RESOURCE')
        if line == '#EXT-X-DISCONTINUITY':
            require(not discontinuity and duration is None, 'VIDEO_HLS_SEGMENT_INVALID')
            discontinuity = True
        elif line.startswith('#EXT-X-KEY:'):
            require(duration is None, 'VIDEO_HLS_SEGMENT_INVALID')
            attrs = _attributes(line.split(':', 1)[1])
            require(set(attrs) <= {'METHOD', 'URI', 'IV', 'KEYFORMAT', 'KEYFORMATVERSIONS'}
                    and attrs.get('METHOD') == 'AES-128'
                    and attrs.get('KEYFORMAT', 'identity') == 'identity'
                    and attrs.get('KEYFORMATVERSIONS', '1') == '1',
                    'VIDEO_HLS_DRM_OR_ENCRYPTION_UNSUPPORTED')
            key = attrs.get('URI'); host = urlsplit(key or '').netloc
            if host == 'key.streaks.jp':
                parsed = _exact_url(key, host, rf'/{media_id}/{source_id}/[A-Za-z0-9_-]{{16,100}}')
            else:
                parsed = _exact_url(key, CDN_KEY,
                    r'/([0-9a-f]{32})/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
                namespace = parsed.path.split('/')[1]
                require(hashlib.sha256(namespace.encode('ascii')).hexdigest() == key_namespace_sha256,
                        'VIDEO_CDN_NAMESPACE_MISMATCH')
            require(not parsed.query, 'VIDEO_HLS_KEY_SCOPE_INVALID')
            iv = attrs.get('IV')
            require(iv is None or re.fullmatch(r'0x[0-9a-fA-F]{32}', iv), 'VIDEO_HLS_IV_INVALID')
        elif line.startswith('#EXTINF:'):
            require(duration is None, 'VIDEO_HLS_DURATION_INVALID')
            try:
                duration = float(line.split(':', 1)[1].split(',')[0])
            except ValueError:
                raise SourceError('VIDEO_HLS_DURATION_INVALID') from None
            require(math.isfinite(duration) and 0 < duration <= 20, 'VIDEO_HLS_DURATION_INVALID')
        elif not line.startswith('#'):
            require(duration is not None, 'VIDEO_HLS_SEGMENT_INVALID')
            host = urlsplit(line).netloc
            require(host in {LEGACY_SEGMENT, CDN_SEGMENT} and (profile is None or profile == host),
                    'VIDEO_CDN_PROFILE_MIXED_OR_UNKNOWN')
            profile = host
            parsed = _exact_url(line, host, rf'/{media_id}/{source_id}/manifest_{variant.number}_{sequence}\.ts')
            require(host != LEGACY_SEGMENT or not key or urlsplit(key).netloc == 'key.streaks.jp',
                    'VIDEO_CDN_PROFILE_MIXED_OR_UNKNOWN')
            require(not parsed.query or (host == CDN_SEGMENT
                    and re.fullmatch(r'm=[0-9]{10}', parsed.query)), 'VIDEO_HLS_SEGMENT_SCOPE_INVALID')
            require(query_mode is None or query_mode == parsed.query, 'VIDEO_CDN_QUERY_MIXED')
            query_mode = parsed.query
            segment_iv = (bytes.fromhex(iv[2:]) if iv else sequence.to_bytes(16, 'big')) if key else None
            segments.append(Segment(line, sequence, duration, key, segment_iv, discontinuity))
            sequence += 1; duration = None; discontinuity = False
    require(duration is None and not discontinuity and 1 <= len(segments) <= MAX_SEGMENTS
            and sum(s.duration for s in segments) <= MAX_SECONDS, 'VIDEO_HLS_CLIP_OUTSIDE_BOUNDS')
    require(len({s.key_url for s in segments if s.key_url}) <= 4,
            'VIDEO_HLS_KEY_ROTATION_OUTSIDE_BOUNDS')
    return segments
