"""Bounded streaming quality of decoded presentation times, with no wall-time claim.

The first decoded video frame need not be the first HLS media sample. Relative
PTS consistency therefore never maps PROGRAM-DATE-TIME onto decoded frames or
proves source frame completeness, physical event times, boat identity or speed.
Only small per-segment summaries survive; no pixels or frame list is retained.
"""
from fractions import Fraction
import hashlib
import math


MAX_FRAMES = 20000


def _pair(value):
    return [value.numerator, value.denominator] if value is not None else None


class FrameTimingQuality:
    def __init__(self, declared_duration):
        self.count = 0
        self.first = self.last = self.base = self.minimum = self.maximum = None
        self.digest = hashlib.sha256()
        self.reason = None
        self.duration = None
        if (type(declared_duration) not in (int, float) or not 0 < declared_duration <= 20
                or not math.isfinite(declared_duration)):
            self.reason = 'UNVERIFIED_FRAME_SEGMENT_DURATION'
        else:
            self.duration = Fraction(str(declared_duration))

    def observe(self, pts, time_base):
        """Consume every decoded frame, including frames skipped by image sampling."""
        self.count += 1
        if self.count > MAX_FRAMES:
            self.reason = 'UNVERIFIED_FRAME_COUNT_BOUND'
            return
        if self.reason:
            return
        if type(pts) is not int or not 0 <= pts < (1 << 63):
            self.reason = 'UNVERIFIED_FRAME_PTS_VALUE'
            return
        if (type(time_base) is not Fraction or not 0 < time_base <= 1
                or time_base.numerator > 10**9 or time_base.denominator > 10**9):
            self.reason = 'UNVERIFIED_FRAME_TIME_BASE'
            return
        self.digest.update(f'{pts}/{time_base.numerator}/{time_base.denominator}\n'.encode('ascii'))
        if self.first is None:
            self.first = self.last = pts
            self.base = time_base
            return
        if time_base != self.base:
            self.reason = 'UNVERIFIED_FRAME_TIME_BASE_CHANGED'
        elif pts == self.last:
            self.reason = 'UNVERIFIED_FRAME_PTS_DUPLICATE'
        elif pts < self.last:
            self.reason = 'UNVERIFIED_FRAME_PTS_REVERSED'
        elif (pts - self.first) * self.base >= self.duration:
            self.reason = 'UNVERIFIED_FRAME_OUTSIDE_DECLARED_SEGMENT'
        else:
            delta = (pts - self.last) * self.base
            self.minimum = delta if self.minimum is None else min(self.minimum, delta)
            self.maximum = delta if self.maximum is None else max(self.maximum, delta)
            self.last = pts

    def finish(self):
        """Any failure suppresses the entire segment's usable timing prefix."""
        status = self.reason or ('RELATIVE_PTS_CONSISTENT' if self.count >= 2
                                 else 'UNVERIFIED_INSUFFICIENT_FRAME_TIMES')
        good = status == 'RELATIVE_PTS_CONSISTENT'
        return dict(schema_version=1, status=status, relative_pts_consistent=good,
            frames_observed=self.count, pts_sha256=self.digest.hexdigest() if good else None,
            first_pts=self.first if good else None, last_pts=self.last if good else None,
            time_base=_pair(self.base) if good else None,
            relative_span=_pair((self.last - self.first) * self.base) if good else None,
            minimum_interval=_pair(self.minimum) if good else None,
            maximum_interval=_pair(self.maximum) if good else None,
            timing_scope='DECODED_VIDEO_SEGMENT_RELATIVE_PTS_ONLY',
            wall_clock_mapping='NOT_COMPUTED_FIRST_MEDIA_SAMPLE_ALIGNMENT_UNVERIFIED',
            source_frame_completeness_verified=False, independent_clock_verified=False,
            physical_exhibition_time_verified=False, prediction_eligible=False)
