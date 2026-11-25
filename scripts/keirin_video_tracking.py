"""Track visible KEIRIN jersey colours in a verified local replay clip.

Image positions are screen pixels, with no inferred distances or speeds. Wide
shots, occlusion, cuts and competing colour blobs can cause abstentions. Raw
tracks and independent annotations stay in the private review directory.
"""

import argparse
from collections import Counter
from datetime import date
from hashlib import file_digest, sha256
import json
import math
from pathlib import Path
import re
import stat
import subprocess

import numpy as np
from PIL import Image
from scipy import ndimage

from race_ai.keirin_note_view import _create, _private_root


SCHEMA = 'KEIRIN_REPLAY_BIB_TRACKS_V1'
REFERENCE_SCHEMA = 'KEIRIN_REPLAY_BIB_VALIDATION_V1'
FPS = 5
TRACK_GAP_MS = 800
MAX_SECONDS = 180
MAX_ASSET_BYTES = 512 * 1024 * 1024
WIDTH = 640
TAKEO_BIBS = (1, 2, 3, 4, 5, 6)
_SHAPE = np.ones((2, 2), dtype=bool)


def _hex(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _validate_race(value):
    if type(value) is not str or re.fullmatch(r'20[0-9]{6}-84-(0[1-9]|1[0-2])', value) is None:
        raise ValueError('A dated Takeo race ID is required for this broadcast layout.')
    date.fromisoformat(value[:8])


def _colour_mask(hsv, car):
    hue, saturation, value = (hsv[:, :, i] for i in range(3))
    if car == 1:
        return (saturation <= 44) & (value >= 171)
    if car == 2:
        return (saturation <= 92) & (value >= 17) & (value <= 76)
    h = {3: (hue <= 11) | (hue >= 227), 4: (hue >= 131) & (hue <= 165),
         5: (hue >= 25) & (hue <= 44), 6: (hue >= 83) & (hue <= 119)}[car]
    s, v = {3: (75, 77), 4: (72, 103), 5: (75, 102), 6: (46, 82)}[car]
    return h & (saturation >= s) & (value >= v)


def _track_area(image, at_ms):
    height, width = image.shape[:2]
    area = np.ones((height, width), dtype=bool)
    area[:, :round(.021 * width)] = False
    area[:, round(.98 * width):] = False
    area[round(.957 * height):] = False
    if at_ms < 63000:
        area[:round(.17 * height), :round(.42 * width)] = False
        area[:round(.272 * height), round(.68 * width):] = False
        area[round(.765 * height):, :round(.325 * width)] = False
        area[round(.80 * height):, round(.76 * width):] = False
    return area


def _components(mask):
    labels, count = ndimage.label(ndimage.binary_opening(mask, structure=_SHAPE))
    if not count:
        return []
    sizes = np.bincount(labels.ravel())
    result = []
    for index, bounds in enumerate(ndimage.find_objects(labels), 1):
        if bounds is None or not 15 <= sizes[index] <= 2600:
            continue
        y, x = bounds
        width, height = x.stop-x.start, y.stop-y.start
        if not 4 <= width <= 76 or not 4 <= height <= 63 or not .22 <= width/height <= 4.4:
            continue
        if sizes[index] / (width * height) < .29:
            continue
        yy, xx = np.nonzero(labels[bounds] == index)
        result.append((float(x.start+xx.mean()), float(y.start+yy.mean()), int(sizes[index])))
    return result


def _near_pack(candidates, points):
    if len(points) < 2:
        return []
    xs, ys = zip(*points)
    return [(x, y, size) for x, y, size in candidates
            if min(xs)-132 <= x <= max(xs)+132 and min(ys)-48 <= y <= max(ys)+46
            and min(math.hypot(x-px, y-py) for px, py in points) >= 23]


def _choose(candidates, prior, at_ms):
    if not candidates:
        return None
    if prior is not None:
        last_ms, x, y, vx, vy, _ = prior
        interval = at_ms-last_ms
        if interval <= TRACK_GAP_MS:
            tolerance = 40 + .09 * interval
            expected = (x+vx*interval, y+vy*interval)
            distances = sorted((math.hypot(xx-expected[0], yy-expected[1]), xx, yy, size)
                               for xx, yy, size in candidates)
            if distances[0][0] <= tolerance:
                if len(distances) > 1 and distances[1][0] - distances[0][0] < 7:
                    return None
                return distances[0][1:]
    ordered = sorted(candidates, key=lambda row: row[2], reverse=True)
    if len(ordered) > 1 and ordered[1][2] >= .72 * ordered[0][2]:
        return None
    return ordered[0]


def track_frames(frames, cars, *, scale=1):
    """Associate visibly coloured candidates across adjacent frames in the same shot."""
    cars = tuple(cars)
    if not cars or len(set(cars)) != len(cars) or any(type(car) is not int or car not in TAKEO_BIBS for car in cars):
        raise ValueError('Track input requires a unique Takeo bib roster.')
    active, tracks = {}, []
    next_track_id = 0
    previous_image = None
    previous_time = -1
    for at_ms, image in frames:
        if type(at_ms) is not int or at_ms <= previous_time:
            raise ValueError('Track frames must have increasing actual sample times.')
        raw = image[::8, ::8].astype(np.int16)
        cut = previous_image is not None and float(np.abs(raw-previous_image).mean()) > 42
        if cut:
            active.clear()
        previous_image, previous_time = raw, at_ms
        area = _track_area(image, at_ms)
        hsv = np.asarray(Image.fromarray(image).convert('HSV'))
        accepted, rider_points = {}, []
        for car in sorted(cars, key=lambda bib: bib < 3):
            subject = _components(_colour_mask(hsv, car) & area)
            if car < 3:
                subject = _near_pack(subject, rider_points)
            prior = active.get(car)
            choice = _choose(subject, prior, at_ms)
            if choice is None:
                continue
            x, y, _ = choice
            if prior and at_ms-prior[0] <= TRACK_GAP_MS and math.hypot(x-prior[1], y-prior[2]) <= 90:
                elapsed = at_ms-prior[0]
                vx, vy = (x-prior[1])/elapsed, (y-prior[2])/elapsed
                link = prior[5]
            else:
                next_track_id += 1
                link, vx, vy = next_track_id, 0, 0
            active[car] = (at_ms, x, y, vx, vy, link)
            rider_points.append((x, y))
            accepted[str(car)] = {'x': round(x*scale), 'y': round(y*scale), 'track_id': link}
        tracks.append({'at_ms': at_ms, 'cut_before': cut, 'riders': accepted})
    return tracks


def _review_points(reference, race_id, media_sha256, cars, width, height):
    if (reference['race_id'], reference['media_sha256']) != (race_id, media_sha256):
        raise ValueError('The review does not bind to the tracked footage.')
    allowed = {str(car) for car in cars}
    points = {}
    for row in reference['frames']:
        at_ms, sightings = row['at_ms'], row['riders']
        if (type(at_ms) is not int or at_ms < 0 or at_ms in points or not set(sightings) <= allowed or
                any(type(point) is not list or len(point) != 2 or not all(type(coord) is int for coord in point)
                    or not 0 <= point[0] < width or not 0 <= point[1] < height for point in sightings.values())):
            raise ValueError('Invalid reviewed frame or point.')
        points[at_ms] = sightings
    return points


def score_reference(tracks, first, second, *, width, cars):
    """Compare matching bibs only where the two independent reviews agree spatially."""
    if not first or first.keys() != second.keys():
        raise ValueError('Independent reviewers must use the same fixed sample clock.')
    measured = {row['at_ms']: row['riders'] for row in tracks}
    if not first.keys() <= measured.keys():
        raise ValueError('Tracked sample timestamps are missing.')
    counts = Counter()
    by_car = {str(car): Counter() for car in cars}
    for at_ms, earlier in first.items():
        later, observations = second[at_ms], measured[at_ms]
        for car, total in by_car.items():
            a, b, tracked = earlier.get(car), later.get(car), observations.get(car)
            if a is None or b is None:
                total['reference_unknown'] += 1
            elif math.dist(a, b) > width * .04:
                total['reviewer_disagreements'] += 1
            else:
                total['agreed_points'] += 1
                target = ((a[0]+b[0])/2, (a[1]+b[1])/2)
                if tracked is None:
                    total['tracker_abstentions'] += 1
                elif math.dist(target, (tracked['x'], tracked['y'])) <= width * .05:
                    total['localized_car_correctly'] += 1
                else:
                    total['localized_car_incorrectly'] += 1
                continue
            if tracked is not None:
                total['unscored_predictions'] += 1
    for subtotal in by_car.values():
        counts.update(subtotal)
    return dict(annotated_frames=len(first), agreed_points=counts['agreed_points'],
                localized_car_correctly=counts['localized_car_correctly'],
                localized_car_incorrectly=counts['localized_car_incorrectly'],
                tracker_abstentions=counts['tracker_abstentions'], reference_unknown=counts['reference_unknown'],
                reviewer_disagreements=counts['reviewer_disagreements'], unscored_predictions=counts['unscored_predictions'],
                by_car={car: dict(subtotal) for car, subtotal in by_car.items()})


def _json(raw):
    return (json.dumps(raw, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))+'\n').encode()


def _track_clip(media, digest, race_id, cars):
    _validate_race(race_id)
    initial = media.lstat()
    if not stat.S_ISREG(initial.st_mode) or not 0 < initial.st_size <= MAX_ASSET_BYTES or not _hex(digest):
        raise ValueError('A bounded local file with verified media SHA-256 is required.')
    with media.open('rb') as stream:
        if file_digest(stream, 'sha256').hexdigest() != digest:
            raise ValueError('Verified media SHA-256 is required.')
    probe = subprocess.check_output(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-select_streams', 'v:0', '-show_entries', 'stream=width,height,duration,avg_frame_rate,r_frame_rate,start_time',
        '-of', 'json', str(media)], timeout=20)
    stream, = json.loads(probe)['streams']
    width, height = stream['width'], stream['height']
    if ((width, height) != (1280, 720) or not 1 < float(stream['duration']) <= MAX_SECONDS
            or stream['avg_frame_rate'] != '25/1' or stream['r_frame_rate'] != '25/1' or float(stream['start_time']) != 0):
        raise ValueError('The Takeo test profile expects bounded 25 fps 1280x720 player footage starting at zero.')
    # The independent review uses original frames 0, 5, 10, ... on this 25 fps clock.
    # Default nearest rounding observes frames 2, 7, 12, ... and shifts that clock.
    raw = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-protocol_whitelist', 'file,pipe',
        '-threads', '1', '-i', str(media), '-map', '0:v:0', '-vf', f'fps={FPS}:start_time=0:round=up,scale={WIDTH}:360',
        '-filter_threads', '1', '-frames:v', str(MAX_SECONDS*FPS+1), '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], timeout=120)
    frames = np.frombuffer(raw, dtype=np.uint8).reshape((-1, 360, WIDTH, 3))
    if not 0 < len(frames) <= MAX_SECONDS*FPS:
        raise ValueError('Decoded video frames outside the Takeo profile bounds.')
    updated = media.lstat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if any(getattr(initial, field) != getattr(updated, field) for field in fields):
        raise ValueError('The reviewed media changed during tracking.')
    with media.open('rb') as source:
        if file_digest(source, 'sha256').hexdigest() != digest:
            raise ValueError('The reviewed media changed during tracking.')
    tracks = track_frames(((index*1000//FPS, frame) for index, frame in enumerate(frames)), cars, scale=width/WIDTH)
    return dict(schema=SCHEMA, race_id=race_id, media_sha256=digest, cars=list(cars), width=width, height=height,
                tracker_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), sample_fps=FPS, tracks=tracks)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest='action', required=True)
    detect = commands.add_parser('track')
    detect.add_argument('--media', type=Path, required=True)
    detect.add_argument('--media-sha256', required=True)
    detect.add_argument('--race-id', required=True)
    detect.add_argument('--cars', type=int, nargs='+', required=True)
    detect.add_argument('--out', type=Path, required=True)
    compare = commands.add_parser('verify')
    compare.add_argument('--tracks', type=Path, required=True)
    compare.add_argument('--tracks-sha256', required=True)
    compare.add_argument('--reference', type=Path, action='append', required=True)
    args = parser.parse_args(argv)
    if args.action == 'track':
        _private_root(args.out.parent)
        record = _track_clip(args.media, args.media_sha256, args.race_id, args.cars)
        raw = _json(record)
        _create(args.out, raw)
        result = dict(sampled_frames=len(record['tracks']), tracks_sha256=sha256(raw).hexdigest())
    else:
        raw = args.tracks.read_bytes()
        if sha256(raw).hexdigest() != args.tracks_sha256 or len(args.reference) != 2:
            raise ValueError('A pinned track output and two independent review files are required.')
        record = json.loads(raw)
        if record['schema'] != SCHEMA:
            raise ValueError('Unexpected tracking schema.')
        reviews = [path.read_bytes() for path in args.reference]
        hashes = [sha256(content).hexdigest() for content in reviews]
        if hashes[0] == hashes[1]:
            raise ValueError('An identical review file is not a second review.')
        first, second = (_review_points(json.loads(content), record['race_id'], record['media_sha256'],
                                        record['cars'], record['width'], record['height']) for content in reviews)
        result = score_reference(record['tracks'], first, second, width=record['width'], cars=record['cars'])
        result.update(schema=REFERENCE_SCHEMA, tracks_sha256=args.tracks_sha256, review_sha256s=hashes,
                      race_id=record['race_id'], media_sha256=record['media_sha256'],
                      tracker_source_sha256=record['tracker_source_sha256'])
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
