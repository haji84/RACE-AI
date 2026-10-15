"""Bounded RAM-only HLS decode and color-candidate tracking, never boat metrics.

Only the normal public player's exact media/source resources are accepted.
Identity AES-128 is ordinary HLS playback, with no DRM/license work. Keys,
tokens, segment bodies and frames are never included in returned derivatives.
Color blobs have no verified registration/lane or camera geometry. They cannot
enter predictions or stand in for speed, turning skill or exhibition times.
"""
from dataclasses import dataclass, field
import hashlib
import io
import math
import re
import time
from urllib.parse import urlsplit, parse_qs

from .core import SourceError
from .exhibition_video_source import (PLAYER, PROJECT, SourceResponse, bounded_fetch,
                                      instant, require, utc_now, validate_descriptor, _resource)
from web.race_contract import canonical, stamp, JST

MANIFEST_BYTES = 1024 * 1024
SEGMENT_BYTES = 4 * 1024 * 1024
TOTAL_BYTES = 64 * 1024 * 1024
MAX_SEGMENTS = 100
MAX_SECONDS = 600
MAX_PIXELS = 1280 * 720
MAX_FRAMES = 20000
MAX_SAMPLES = 400
MAX_TRACKS = 1000
MIME_HLS = {'application/vnd.apple.mpegurl', 'application/x-mpegurl', 'audio/mpegurl'}


@dataclass(frozen=True)
class Variant:
    url: str = field(repr=False)
    number: int
    width: int
    height: int
    bandwidth: int


@dataclass(frozen=True)
class Segment:
    url: str = field(repr=False)
    sequence: int
    duration: float
    key_url: str | None = field(repr=False)
    iv: bytes | None = field(repr=False)
    discontinuity: bool = False


def _text(raw):
    require(isinstance(raw, bytes) and 1 <= len(raw) <= MANIFEST_BYTES, 'VIDEO_HLS_SIZE_INVALID')
    try:
        value = raw.decode('utf-8-sig')
    except UnicodeError:
        raise SourceError('VIDEO_HLS_ENCODING_INVALID') from None
    require(value.startswith('#EXTM3U\n') or value.startswith('#EXTM3U\r\n'), 'VIDEO_HLS_HEADER_INVALID')
    require(all(c in '\r\n\t' or 32 <= ord(c) <= 126 for c in value), 'VIDEO_HLS_CHARACTERS_INVALID')
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    require(len(lines) <= 2500, 'VIDEO_HLS_LINES_OUTSIDE_BOUNDS')
    return lines


def _attributes(value):
    pattern = r'([A-Z0-9-]+)=("[^"\r\n]*"|[^,\r\n]+)(?:,|$)'
    result = {}; cursor = 0
    for match in re.finditer(pattern, value):
        require(match.start() == cursor and match[1] not in result, 'VIDEO_HLS_ATTRIBUTES_INVALID')
        result[match[1]] = match[2].strip('"'); cursor = match.end()
    require(cursor == len(value), 'VIDEO_HLS_ATTRIBUTES_INVALID')
    return result


def _url(value, host, path):
    require(isinstance(value, str) and 0 < len(value) <= 16384
            and all(32 < ord(c) < 127 for c in value), 'VIDEO_HLS_URL_INVALID')
    parsed = urlsplit(value)
    require(parsed.scheme == 'https' and parsed.netloc == host and not parsed.fragment
            and re.fullmatch(path, parsed.path) is not None, 'VIDEO_HLS_RESOURCE_SCOPE_INVALID')
    return parsed


def select_variant(raw, media_id, source_id):
    lines = _text(raw); candidates = []
    for n, line in enumerate(lines):
        if not line.startswith('#EXT-X-STREAM-INF:'): continue
        attrs = _attributes(line.split(':', 1)[1])
        resolution = re.fullmatch(r'(\d{1,5})x(\d{1,5})', attrs.get('RESOLUTION', ''))
        require(resolution is not None and attrs.get('BANDWIDTH', '').isdigit(), 'VIDEO_HLS_VARIANT_INVALID')
        width, height = map(int, resolution.groups()); bandwidth = int(attrs['BANDWIDTH'])
        require(0 < width <= 8000 and 0 < height <= 8000 and 0 < bandwidth <= 100000000,
                'VIDEO_HLS_VARIANT_INVALID')
        require(n + 1 < len(lines), 'VIDEO_HLS_VARIANT_INVALID')
        url = lines[n + 1]
        path = rf'/v5/{PROJECT}/{media_id}/{source_id}/manifest_([1-9][0-9]?)\.m3u8'
        parsed = _url(url, 'variants.streaks.jp', path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        require(set(query) == {'vt'} and len(query['vt']) == 1 and
                re.fullmatch(r'[A-Za-z0-9._~+/=-]{1,8192}', query['vt'][0]) is not None,
                'VIDEO_HLS_QUERY_INVALID')
        number = int(re.fullmatch(path, parsed.path)[1])
        if width * height <= MAX_PIXELS:
            candidates.append(Variant(url, number, width, height, bandwidth))
    require(1 <= len(candidates) <= 8, 'VIDEO_HLS_NO_BOUNDED_VARIANT')
    return min(candidates, key=lambda v: (v.bandwidth, v.width * v.height))


def parse_vod(raw, media_id, source_id, variant):
    lines = _text(raw)
    require(lines[-1] == '#EXT-X-ENDLIST' and lines.count('#EXT-X-ENDLIST') == 1
            and '#EXT-X-PLAYLIST-TYPE:VOD' in lines, 'VIDEO_HLS_NOT_COMPLETE_VOD')
    seqs = [x.split(':', 1)[1] for x in lines if x.startswith('#EXT-X-MEDIA-SEQUENCE:')]
    require(len(seqs) == 1 and re.fullmatch(r'\d{1,15}', seqs[0]), 'VIDEO_HLS_SEQUENCE_INVALID')
    sequence = int(seqs[0]); segments = []; duration = None; key = None; iv = None; discontinuity = False
    for line in lines[1:]:
        require(not line.startswith(('#EXT-X-BYTERANGE', '#EXT-X-MAP', '#EXT-X-PART', '#EXT-X-SESSION-KEY')),
                'VIDEO_HLS_UNSUPPORTED_RESOURCE')
        if line == '#EXT-X-DISCONTINUITY': discontinuity = True
        elif line.startswith('#EXT-X-KEY:'):
            attrs = _attributes(line.split(':', 1)[1])
            require(set(attrs) <= {'METHOD', 'URI', 'IV', 'KEYFORMAT', 'KEYFORMATVERSIONS'}
                    and attrs.get('METHOD') == 'AES-128' and attrs.get('KEYFORMAT', 'identity') == 'identity'
                    and attrs.get('KEYFORMATVERSIONS', '1') == '1', 'VIDEO_HLS_DRM_OR_ENCRYPTION_UNSUPPORTED')
            key = attrs.get('URI')
            parsed = _url(key, 'key.streaks.jp', rf'/{media_id}/{source_id}/[A-Za-z0-9_-]{{16,100}}')
            require(not parsed.query, 'VIDEO_HLS_KEY_SCOPE_INVALID')
            iv = attrs.get('IV')
            require(iv is None or re.fullmatch(r'0x[0-9a-fA-F]{32}', iv), 'VIDEO_HLS_IV_INVALID')
        elif line.startswith('#EXTINF:'):
            require(duration is None, 'VIDEO_HLS_DURATION_INVALID')
            try: duration = float(line.split(':', 1)[1].split(',')[0])
            except ValueError: raise SourceError('VIDEO_HLS_DURATION_INVALID') from None
            require(math.isfinite(duration) and 0 < duration <= 20, 'VIDEO_HLS_DURATION_INVALID')
        elif not line.startswith('#'):
            require(duration is not None, 'VIDEO_HLS_SEGMENT_INVALID')
            parsed = _url(line, 'live-cp-boatrace-prod.streaks.jp',
                          rf'/{media_id}/{source_id}/manifest_{variant.number}_{sequence}\.ts')
            require(not parsed.query, 'VIDEO_HLS_SEGMENT_SCOPE_INVALID')
            segment_iv = (bytes.fromhex(iv[2:]) if iv else sequence.to_bytes(16, 'big')) if key else None
            segments.append(Segment(line, sequence, duration, key, segment_iv, discontinuity))
            sequence += 1; duration = None; discontinuity = False
    require(duration is None and 1 <= len(segments) <= MAX_SEGMENTS
            and sum(s.duration for s in segments) <= MAX_SECONDS, 'VIDEO_HLS_CLIP_OUTSIDE_BOUNDS')
    require(len({s.key_url for s in segments if s.key_url}) <= 4, 'VIDEO_HLS_KEY_ROTATION_OUTSIDE_BOUNDS')
    return segments


def _decrypt(raw, key, iv):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    require(len(key) == 16 and len(raw) % 16 == 0, 'VIDEO_HLS_AES_SIZE_INVALID')
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = cipher.update(raw) + cipher.finalize()
    unpad = PKCS7(128).unpadder()
    return unpad.update(padded) + unpad.finalize()


def _candidates(frame):
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    ranges = {'red': [(0, 10), (170, 179)], 'blue': [(95, 130)],
              'yellow': [(20, 38)], 'green': [(40, 90)]}
    height, width = frame.shape[:2]; found = []
    for color, bounds in ranges.items():
        mask = np.zeros((height, width), dtype=np.uint8)
        for low, high in bounds:
            mask |= cv2.inRange(hsv, (low, 100, 90), (high, 255, 255))
        count, _, stats, centers = cv2.connectedComponentsWithStats(mask)
        for index in range(1, count):
            x, y, w, h, area = map(int, stats[index])
            if 4 <= w and 4 <= h and 25 <= area <= width * height * .10:
                found.append(dict(color=color, x=float(centers[index][0]), y=float(centers[index][1]),
                                  area=area, box=[x, y, w, h]))
    return sorted(found, key=lambda c: -c['area'])[:12]


def analyze_exhibition(descriptor, lease, race, *, fetch=None, clock=utc_now,
                       sample_interval=2.0, segment_limit=MAX_SEGMENTS, elapsed_limit=90, camera_motion=False):
    """A consumed lease returns derived evidence only. Runtime fails before media GETs."""
    start = stamp(clock()); validate_descriptor(descriptor, race, start)
    require(descriptor['status'] == 'AVAILABLE' and lease is not None, 'VIDEO_RECORDING_UNAVAILABLE')
    require(type(sample_interval) in (int, float) and .5 <= sample_interval <= 10
            and type(segment_limit) is int and 1 <= segment_limit <= MAX_SEGMENTS
            and type(elapsed_limit) in (int, float) and 1 <= elapsed_limit <= 120
            and type(camera_motion) is bool, 'VIDEO_PROCESSING_BOUNDS_INVALID')
    try:
        import av
        import cv2
    except (ImportError, OSError):
        raise SourceError('VIDEO_DECODE_RUNTIME_UNAVAILABLE') from None
    fetch = fetch or bounded_fetch
    if camera_motion:
        from .video_camera_motion import estimate_camera_motion, candidate_point_residual
    def process(master_url):
        began = time.monotonic(); total = 0; last = instant(start); media = descriptor['media']
        require(_resource(master_url,media['id'],media['source_id'],signed=True)==media['source_url_without_query'],
                'VIDEO_LEASE_DESCRIPTOR_MISMATCH')
        headers = {'User-Agent': 'RaceAI bounded private exhibition analysis', 'Origin': PLAYER, 'Referer': PLAYER + '/'}
        def read(url, cap, mimes):
            nonlocal total, last
            require(time.monotonic() - began < elapsed_limit, 'VIDEO_PROCESSING_TIME_EXCEEDED')
            response = fetch(url, headers=headers, max_bytes=cap, timeout=min(10, elapsed_limit-(time.monotonic()-began)))
            require(time.monotonic()-began < elapsed_limit, 'VIDEO_PROCESSING_TIME_EXCEEDED')
            require(isinstance(response, SourceResponse) and type(response.status) is int and response.status == 200
                    and response.url == url and isinstance(response.body, bytes) and 1 <= len(response.body) <= cap,
                    'VIDEO_MEDIA_RESPONSE_INVALID')
            require(response.content_type.split(';', 1)[0].lower() in mimes, 'VIDEO_MEDIA_MIME_INVALID')
            total += len(response.body); require(total <= TOTAL_BYTES, 'VIDEO_MEDIA_TOTAL_BYTES_EXCEEDED')
            now = instant(clock()); require(last <= now and now.astimezone(JST).date() == instant(race['closed_at']).astimezone(JST).date(),
                                            'VIDEO_PROCESSING_CLOCK_INVALID'); last = now
            return response.body
        master_raw = read(master_url, MANIFEST_BYTES, MIME_HLS)
        master_sha = hashlib.sha256(master_raw).hexdigest()
        variant = select_variant(master_raw, media['id'], media['source_id']); master_raw = None
        child_raw = read(variant.url, MANIFEST_BYTES, MIME_HLS)
        child_sha = hashlib.sha256(child_raw).hexdigest()
        segments = parse_vod(child_raw, media['id'], media['source_id'], variant); child_raw = None
        tracks = []; previous = None; keys = {}; decoded = sampled = completed = 0; offset = 0.0
        sharpness = []; sizes = set(); segment_hash = hashlib.sha256()
        previous_pixels = None; previous_candidates = []; previous_second = None
        camera_attempts = camera_accepted = 0; camera_rejections = {}; camera_rmse = []; camera_inliers = []
        try:
            for number, segment in enumerate(segments[:segment_limit]):
                decoded_before_segment = decoded
                raw = read(segment.url, SEGMENT_BYTES, {'video/mp2t', 'application/octet-stream'})
                segment_hash.update(hashlib.sha256(raw).digest())
                if segment.key_url:
                    if segment.key_url not in keys:
                        key = read(segment.key_url, 16, {'application/octet-stream', 'binary/octet-stream'})
                        require(len(key) == 16, 'VIDEO_HLS_KEY_BYTES_INVALID'); keys[segment.key_url] = key
                    raw = _decrypt(raw, keys[segment.key_url], segment.iv)
                local_tracks = []; first_pts = None; next_sample = 0.0; previous = None
                previous_pixels = None; previous_candidates = []; previous_second = None
                with av.open(io.BytesIO(raw), format='mpegts', mode='r') as container:
                    require(len(container.streams.video) == 1, 'VIDEO_STREAM_COUNT_INVALID')
                    for frame in container.decode(video=0):
                        decoded += 1
                        require(decoded <= MAX_FRAMES and time.monotonic()-began < elapsed_limit,
                                'VIDEO_DECODE_LIMIT_EXCEEDED')
                        require(0 < frame.width * frame.height <= MAX_PIXELS and frame.time is not None,
                                'VIDEO_FRAME_GEOMETRY_OR_TIME_INVALID')
                        sizes.add((frame.width, frame.height))
                        if first_pts is None: first_pts = frame.time
                        position = float(frame.time - first_pts)
                        require(-.01 <= position <= segment.duration + 1, 'VIDEO_FRAME_TIME_INVALID')
                        if position + .0001 < next_sample: continue
                        sampled += 1; require(sampled <= MAX_SAMPLES, 'VIDEO_SAMPLE_LIMIT_EXCEEDED')
                        next_sample += sample_interval
                        pixels = frame.to_ndarray(format='bgr24')
                        gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
                        sharpness.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
                        # Segment/cut boundaries never create a cross-shot camera estimate or association.
                        thumbnail = cv2.resize(gray, (32, 18))
                        if previous is not None and float(cv2.absdiff(previous, thumbnail).mean()) > 35:
                            local_tracks = []
                            previous_pixels = None; previous_candidates = []; previous_second = None
                        previous = thumbnail; candidates = _candidates(pixels); used = set()
                        motion = None
                        if camera_motion and previous_pixels is not None and previous_pixels.shape != pixels.shape:
                            # Reset before the estimator's minimum-size validation can hide a size change.
                            local_tracks = []; previous_pixels = None; previous_candidates = []; previous_second = None
                        if camera_motion and previous_pixels is not None:
                            motion = estimate_camera_motion(previous_pixels, pixels,
                                previous_exclusions=[c['box'] for c in previous_candidates],
                                current_exclusions=[c['box'] for c in candidates])
                            camera_attempts += 1
                            if motion['accepted']:
                                camera_accepted += 1
                                camera_rmse.append(motion['reprojection_rmse_pixels'])
                                camera_inliers.append(motion['inlier_ratio'])
                            else:
                                status = motion['status']
                                camera_rejections[status] = camera_rejections.get(status, 0) + 1
                                if status in {'UNVERIFIED_SCENE_CHANGE', 'UNVERIFIED_SIZE_CHANGE'}:
                                    local_tracks = []
                        for candidate in candidates:
                            matches = []
                            for i, t in enumerate(local_tracks):
                                if i in used or t['color'] != candidate['color'] or offset+position-t['last_second'] > sample_interval*1.5:
                                    continue
                                residual = None
                                if motion is not None and t['last_second'] == previous_second:
                                    residual = candidate_point_residual(motion,
                                        (t['last_x'], t['last_y']), (candidate['x'], candidate['y']))
                                distance = (residual['residual_distance_pixels'] if residual and residual['accepted'] else
                                    math.hypot(t['last_x']-candidate['x'], t['last_y']-candidate['y']))
                                matches.append((distance, i, t, residual))
                            match = min(matches, default=None, key=lambda x:x[0])
                            if match and match[0] <= frame.width*.15:
                                _, index, track, residual = match; used.add(index)
                                if camera_motion:
                                    if residual and residual['accepted']:
                                        track['corrected_transitions'] += 1
                                        track['corrected_dx'] += residual['residual_dx_pixels']
                                        track['corrected_dy'] += residual['residual_dy_pixels']
                                    else:
                                        track['all_transitions_corrected'] = False
                                track.update(last_x=candidate['x'],last_y=candidate['y'],last_second=offset+position,samples=track['samples']+1)
                            else:
                                require(len(tracks) < MAX_TRACKS, 'VIDEO_CANDIDATE_LIMIT_EXCEEDED')
                                track=dict(color=candidate['color'],first_x=candidate['x'],first_y=candidate['y'],
                                           last_x=candidate['x'],last_y=candidate['y'],first_second=offset+position,
                                           last_second=offset+position,samples=1,segment=number)
                                if camera_motion:
                                    track.update(corrected_dx=0.0, corrected_dy=0.0, corrected_transitions=0,
                                                 all_transitions_corrected=True)
                                tracks.append(track);local_tracks.append(track);used.add(len(local_tracks)-1)
                        if camera_motion:
                            previous_pixels = pixels
                            previous_candidates = candidates; previous_second = offset+position
                        pixels = gray = thumbnail = None
                        require(time.monotonic()-began < elapsed_limit, 'VIDEO_PROCESSING_TIME_EXCEEDED')
                require(decoded>decoded_before_segment,'VIDEO_SEGMENT_NO_FRAMES_DECODED')
                raw = None; completed += 1; offset += segment.duration
            done = stamp(clock()); require(last <= instant(done) and instant(done).astimezone(JST).date()==instant(race['closed_at']).astimezone(JST).date(),
                                          'VIDEO_PROCESSING_CLOCK_INVALID')
            require(decoded > 0 and sampled > 0, 'VIDEO_NO_FRAMES_DECODED')
            result = dict(schema_version=1,race_id=race['race_id'],closed_at=stamp(race['closed_at']),
                source_descriptor_snapshot_id=descriptor['snapshot_id'],program_identity_sha256=descriptor['program_identity_sha256'],
                analysis_version='transient-hls-color-candidates/v1',capture_started_at=start,analysis_completed_at=done,
                capture_eligible_pre_race=instant(done)<instant(race['closed_at']),prediction_eligible=False,
                validation_status='UNVALIDATED',boat_identity='UNVERIFIED',camera_calibration='UNVERIFIED',boat_features=[],
                metric_units='CAMERA_UNCORRECTED_PIXELS_NOT_BOAT_PERFORMANCE',raw_media_retained=False,
                coverage='COMPLETE_PLAYLIST' if completed==len(segments) else 'PARTIAL_PLAYLIST',
                segments_in_playlist=len(segments),segments_decoded=completed,frames_decoded=decoded,frames_sampled=sampled,
                declared_playlist_seconds=sum(s.duration for s in segments),decoded_segment_seconds=offset,
                timestamp_basis='RELATIVE_SEGMENT_PTS_NOT_PHYSICAL_EXHIBITION_CLOCK',encoded_bytes_read=total,
                master_sha256=master_sha,child_sha256=child_sha,encoded_segment_digest=segment_hash.hexdigest(),
                encryption='STANDARD_IDENTITY_AES_128' if keys else 'NONE',
                dimensions=[list(x) for x in sorted(sizes)],mean_laplacian_variance=sum(sharpness)/len(sharpness),
                candidate_tracks=[dict(color=t['color'],segment=t['segment'],samples=t['samples'],
                  first_second=t['first_second'],last_second=t['last_second'],dx_pixels=t['last_x']-t['first_x'],
                  dy_pixels=t['last_y']-t['first_y']) for t in tracks if t['samples']>=2])
            if camera_motion:
                eligible_tracks = [t for t in tracks if t['samples'] >= 2]
                result.update(analysis_version='transient-hls-color-candidates/v2',
                    metric_units='IMAGE_PIXELS_WITH_OPTIONAL_CAMERA_ESTIMATE_NOT_BOAT_PERFORMANCE',
                    camera_motion=dict(attempted_pairs=camera_attempts, accepted_pairs=camera_accepted,
                        rejected_pairs=camera_attempts-camera_accepted, rejection_counts=camera_rejections,
                        mean_accepted_inlier_ratio=sum(camera_inliers)/len(camera_inliers) if camera_inliers else None,
                        mean_accepted_reprojection_rmse_pixels=sum(camera_rmse)/len(camera_rmse) if camera_rmse else None,
                        scope='BACKGROUND_AFFINE_IMAGE_ESTIMATE_ONLY', boat_identity='UNVERIFIED',
                        world_calibration='UNVERIFIED', prediction_eligible=False,
                        residual_basis='SUM_OF_PAIR_RESIDUALS_IN_EACH_CURRENT_FRAME_NOT_WORLD_DISPLACEMENT'),
                    candidate_tracks_total=len(eligible_tracks), candidate_tracks_returned=min(len(eligible_tracks), 500),
                    candidate_tracks_truncated=len(eligible_tracks)>500)
                result['candidate_tracks'] = [dict(output,
                    camera_corrected_transitions=t['corrected_transitions'],
                    camera_corrected_dx_pixels=t['corrected_dx'] if t['all_transitions_corrected'] else None,
                    camera_corrected_dy_pixels=t['corrected_dy'] if t['all_transitions_corrected'] else None,
                    camera_correction_status='IMAGE_ESTIMATE_ONLY' if t['all_transitions_corrected'] else 'UNVERIFIED')
                    for output, t in zip(result['candidate_tracks'][:500], eligible_tracks[:500])]
            result['snapshot_id']=hashlib.sha256(canonical(result)).hexdigest()
            require(time.monotonic()-began < elapsed_limit, 'VIDEO_PROCESSING_TIME_EXCEEDED')
            return result
        finally:
            keys.clear(); segments.clear(); tracks.clear(); raw = previous = previous_pixels = None
            previous_candidates.clear()
    return lease.consume(process)
