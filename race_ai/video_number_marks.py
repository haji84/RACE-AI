"""Bounded OCR number-mark observations; no claim of hull or boat identity.

Broadcast overlays, pit signs and other boats can all contain the same digits.
Only an independently audited detector can turn these observations into boat
identities. Image-space associations never confer world motion or model input.
"""
import hashlib
import json
import math

from .core import SourceError
from web.race_contract import canonical


def require(value, message='VIDEO_NUMBER_MARK_INVALID'):
    if not value:
        raise SourceError(message)


def finite(value):
    try:
        return type(value) in (float, int) and math.isfinite(value)
    except OverflowError:
        return False


def geometry(width, height, exclusions):
    require(type(width) is int and type(height) is int and 0 < width <= 1280
            and 0 < height <= 720 and width * height <= 1280*720)
    require(type(exclusions) is list and len(exclusions) <= 32)
    boxes = []
    for box in exclusions:
        require(type(box) in (list, tuple) and len(box) == 4 and all(finite(n) for n in box))
        x, y, w, h = box
        require(0 <= x < x+w <= width and 0 <= y < y+h <= height)
        boxes.append(tuple(float(n) for n in box))
    return boxes


def assess_marks(rows, *, width, height, exclusions):
    """Keep exact digits outside caller-supplied exclusion regions as candidates."""
    masks = geometry(width, height, exclusions)
    require(type(rows) is list and len(rows) <= 128)
    possible, excluded = [], 0
    for row in rows:
        require(type(row) is dict and set(row) == {'text', 'score', 'box'})
        require(type(row['text']) is str and len(row['text']) <= 256)
        require(finite(row['score']) and 0 <= row['score'] <= 1)
        points = row['box']
        require(type(points) in (list, tuple) and len(points) == 4)
        require(all(type(p) in (list, tuple) and len(p) == 2
                    and all(finite(n) for n in p) and 0 <= p[0] <= width
                    and 0 <= p[1] <= height for p in points))
        crosses = []
        for i in range(4):
            a, b, c = points[i], points[(i+1)%4], points[(i+2)%4]
            crosses.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
        require(all(n > 0 for n in crosses) or all(n < 0 for n in crosses))
        x, y = min(p[0] for p in points), min(p[1] for p in points)
        w, h = max(p[0] for p in points)-x, max(p[1] for p in points)-y
        if row['text'] not in ('1','2','3','4','5','6') or row['score'] < .90:
            continue
        if any(x < a+c and a < x+w and y < b+d and b < y+h for a,b,c,d in masks):
            excluded += 1
            continue
        possible.append(dict(candidate_number=int(row['text']), confidence=float(row['score']),
                             box=[float(x),float(y),float(w),float(h)]))
    ambiguous = sorted({r['candidate_number'] for r in possible
                        if sum(q['candidate_number'] == r['candidate_number'] for q in possible) > 1})
    return dict(schema_version='video-number-marks/v1',
                candidates=[r for r in possible if r['candidate_number'] not in ambiguous],
                ambiguous_numbers=ambiguous, excluded_overlay_marks=excluded,
                boat_identity='UNVERIFIED', world_calibration='UNVERIFIED',
                prediction_eligible=False, boat_features=[])


class NumberMarkTracker:
    """A same-digit image-space hypothesis, reset on gaps, cuts and segments."""
    def __init__(self, *, width, height, exclusions):
        geometry(width, height, exclusions)
        self.width, self.height = width, height
        self.exclusions = [list(b) for b in exclusions]
        self.last_second, self.last_segment = None, None
        self.active, self.tracks, self.observations = {}, [], []

    def observe(self, rows, *, second, segment, scene_cut=False):
        require(finite(second) and 0 <= second <= 600 and type(segment) is int
                and 0 <= segment < 100 and type(scene_cut) is bool)
        require(self.last_second is None or second > self.last_second, 'VIDEO_NUMBER_MARK_CLOCK_INVALID')
        require(self.last_segment is None or segment >= self.last_segment, 'VIDEO_NUMBER_MARK_SEGMENT_INVALID')
        require(len(self.observations) < 400, 'VIDEO_NUMBER_MARK_FRAME_LIMIT')
        assessment = assess_marks(rows, width=self.width, height=self.height, exclusions=self.exclusions)
        if (scene_cut or segment != self.last_segment or self.last_second is None
                or second-self.last_second > 3.1):
            self.active.clear()
        current = {}
        for candidate in assessment['candidates']:
            number = candidate['candidate_number']
            x,y,w,h = candidate['box']
            center = (x+w/2, y+h/2)
            old = self.active.get(number)
            if old is not None and math.dist(center, old['last_center']) <= self.width*.15:
                old.update(last_center=center, last_second=float(second), samples=old['samples']+1)
                track = old
            else:
                require(len(self.tracks) < 2400, 'VIDEO_NUMBER_MARK_TRACK_LIMIT')
                track = dict(candidate_number=number, segment=segment, samples=1,
                             first_second=float(second), last_second=float(second),
                             first_center=center, last_center=center)
                self.tracks.append(track)
            current[number] = track
        # Missing/ambiguous markings cannot silently inherit the last identity.
        self.active = current
        self.last_second, self.last_segment = float(second), segment
        self.observations.append(json.loads(canonical(dict(second=float(second), segment=segment,
                                                           scene_cut=scene_cut, **assessment))))
        return assessment

    def finish(self):
        result = dict(schema_version='video-number-mark-tracks/v1',
                      frames_observed=len(self.observations), observations=json.loads(canonical(self.observations)),
                      tracks=[dict(candidate_number=t['candidate_number'], segment=t['segment'],
                                   samples=t['samples'], first_second=t['first_second'], last_second=t['last_second'],
                                   dx_pixels=t['last_center'][0]-t['first_center'][0],
                                   dy_pixels=t['last_center'][1]-t['first_center'][1])
                              for t in self.tracks if t['samples'] >= 2],
                      metric_units='IMAGE_PIXELS_NOT_BOAT_PERFORMANCE', boat_identity='UNVERIFIED',
                      world_calibration='UNVERIFIED', prediction_eligible=False, boat_features=[])
        result['snapshot_id'] = hashlib.sha256(canonical(result)).hexdigest()
        return result
