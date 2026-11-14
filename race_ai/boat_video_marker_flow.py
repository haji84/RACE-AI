"""Opt-in original-pixel marker following, with no OCR or numeric identity.

Keys and initial boxes are supplied by the caller. A successful local image
correspondence does not authenticate a printed number, source, capture clock,
physical boat position or field accuracy. Lost pixels are never extrapolated.
All algorithm parameters below are fixed development defaults, not fitted to
the private boat-number references. Legacy tracking defaults are untouched.
"""
from fractions import Fraction
from hashlib import sha256
import math

from .boat_video_identity import _box, _finite, _pixels


SCHEMA = 'RACE_AI_BOAT_MARKER_PIXEL_FLOW_V1'
PARAMETERS = {
    # Bound live per-frame analysis state, never acquisition/runtime totals.
    'maximum_live_markers': 1000,
    'minimum_points': 4,
    'maximum_points': 40,
    'corner_quality': .02,
    'corner_min_distance_px': 2,
    'corner_block_size': 3,
    'lk_window_px': 21,
    'lk_pyramid_levels': 3,
    'lk_iterations': 30,
    'lk_epsilon': .01,
    'maximum_lk_error': 25.,
    'maximum_forward_backward_error_px': 1.,
    'maximum_displacement_dispersion_px': 2.,
    'maximum_displacement_p90_px': 3.,
    'minimum_affine_area_ratio': .75,
    'maximum_affine_area_ratio': 1.33,
    'minimum_affine_axis_scale': .8,
    'maximum_affine_axis_scale': 1.25,
    'maximum_affine_residual_px': 1.5,
    'minimum_affine_inlier_ratio': .75,
    'minimum_support_extent_fraction': .15,
    'minimum_support_area_fraction': .02,
}


def _need(condition):
    if not condition:
        raise ValueError('BOAT_MARKER_PIXEL_FLOW_REJECTED')


def _inside(points, box):
    x, y, w, h = box
    return ((points[:, 0] >= x) & (points[:, 0] < x+w) &
            (points[:, 1] >= y) & (points[:, 1] < y+h))


def _support(points, box, cv, np):
    if len(points) < PARAMETERS['minimum_points'] or not np.isfinite(points).all():
        return False
    extent = np.ptp(points, axis=0)
    fraction = PARAMETERS['minimum_support_extent_fraction']
    return (extent[0] >= fraction*box[2] and extent[1] >= fraction*box[3] and
            cv.contourArea(cv.convexHull(points.astype(np.float32))) >=
            PARAMETERS['minimum_support_area_fraction']*box[2]*box[3])


def _seed(gray, box, cv, np):
    mask = np.zeros(gray.shape, np.uint8)
    x, y, w, h = box
    # The mask cannot introduce pixels from a neighboring mark.
    mask[math.ceil(y):math.ceil(y+h), math.ceil(x):math.ceil(x+w)] = 255
    points = cv.goodFeaturesToTrack(gray, maxCorners=PARAMETERS['maximum_points'],
        qualityLevel=PARAMETERS['corner_quality'],
        minDistance=PARAMETERS['corner_min_distance_px'], mask=mask,
        blockSize=PARAMETERS['corner_block_size'])
    if points is None:
        return None
    points = points.reshape(-1, 2)
    points = points[_inside(points, box)]
    return points if _support(points, box, cv, np) else None


def _follow(before, after, old, cv, np):
    points = old['points'].astype(np.float32).reshape(-1, 1, 2)
    params = dict(winSize=(PARAMETERS['lk_window_px'],)*2,
        maxLevel=PARAMETERS['lk_pyramid_levels'],
        criteria=(cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT,
                  PARAMETERS['lk_iterations'], PARAMETERS['lk_epsilon']))
    moved, forward, error = cv.calcOpticalFlowPyrLK(before, after, points, None, **params)
    if moved is None or forward is None or error is None or not np.isfinite(moved).all():
        return None, 'INSUFFICIENT_RELIABLE_POINTS'
    returned, backward, back_error = cv.calcOpticalFlowPyrLK(after, before, moved, None, **params)
    if returned is None or backward is None or back_error is None:
        return None, 'INSUFFICIENT_RELIABLE_POINTS'
    origin, destination = points.reshape(-1, 2), moved.reshape(-1, 2)
    returned = returned.reshape(-1, 2)
    fb = np.linalg.norm(returned-origin, axis=1)
    height, width = after.shape
    good = (forward.ravel().astype(bool) & backward.ravel().astype(bool) &
        np.isfinite(returned).all(axis=1) & np.isfinite(error.ravel()) &
        np.isfinite(back_error.ravel()) &
        (error.ravel() <= PARAMETERS['maximum_lk_error']) &
        (back_error.ravel() <= PARAMETERS['maximum_lk_error']) &
        (fb <= PARAMETERS['maximum_forward_backward_error_px']) &
        _inside(destination, [0, 0, width, height]))
    origin, destination, fb = origin[good], destination[good], fb[good]
    if len(origin) < PARAMETERS['minimum_points']:
        return None, 'INSUFFICIENT_RELIABLE_POINTS'
    displacement = destination-origin
    median = np.median(displacement, axis=0)
    deviation = np.linalg.norm(displacement-median, axis=1)
    dispersion = float(np.median(deviation))
    if (dispersion > PARAMETERS['maximum_displacement_dispersion_px'] or
            np.percentile(deviation, 90) > PARAMETERS['maximum_displacement_p90_px'] or
            np.linalg.norm(median) > max(8., .75*math.hypot(*old['box'][2:]))):
        return None, 'INCOHERENT_PIXEL_DISPLACEMENT'
    # Deterministic affine least squares is a consistency guard only. Output
    # boxes use the measured median translation, not a model extrapolation.
    design = np.column_stack((origin.astype(np.float64), np.ones(len(origin))))
    affine, _, rank, _ = np.linalg.lstsq(design, destination.astype(np.float64), rcond=None)
    if rank != 3 or not np.isfinite(affine).all():
        return None, 'AFFINE_GEOMETRY_REJECTED'
    linear = affine[:2].T
    area = float(np.linalg.det(linear))
    scales = np.linalg.svd(linear, compute_uv=False)
    residual = np.linalg.norm(design @ affine-destination, axis=1)
    inliers = residual <= PARAMETERS['maximum_affine_residual_px']
    if (not PARAMETERS['minimum_affine_area_ratio'] <= area <= PARAMETERS['maximum_affine_area_ratio'] or
            not np.all((scales >= PARAMETERS['minimum_affine_axis_scale']) &
                       (scales <= PARAMETERS['maximum_affine_axis_scale'])) or
            inliers.mean() < PARAMETERS['minimum_affine_inlier_ratio'] or
            inliers.sum() < PARAMETERS['minimum_points']):
        return None, 'AFFINE_GEOMETRY_REJECTED'
    origin, destination, fb = origin[inliers], destination[inliers], fb[inliers]
    median = np.median(destination-origin, axis=0)
    dispersion = float(np.median(np.linalg.norm(destination-origin-median, axis=1)))
    x, y, w, h = old['box']
    box = [float(x+median[0]), float(y+median[1]), w, h]
    if not (0 <= box[0] and 0 <= box[1] and box[0]+w <= width and box[1]+h <= height):
        return None, 'FRAME_EDGE_ESCAPE'
    kept = _inside(destination, box)
    destination, fb = destination[kept], fb[kept]
    if not _support(destination, box, cv, np):
        return None, 'INSUFFICIENT_SPATIAL_SUPPORT'
    return dict(box=box, points=destination.copy(),
        median_displacement_px=[float(v) for v in median],
        median_forward_backward_error_px=float(np.median(fb)),
        displacement_dispersion_px=dispersion, affine_area_ratio=area), None


class MarkerPixelFollower:
    """Follow explicitly supplied opaque image marks through actual LK points."""
    def __init__(self, max_gap_seconds=.5):
        _need(_finite(max_gap_seconds) and 0 < max_gap_seconds <= .5)
        self.max_gap = float(max_gap_seconds)
        self._time = self._index = self._scene = self._shape = self._sha = None
        self._gray = None
        self._tracks = {}

    def update(self, frame, seeds, *, t, frame_index, scene):
        width, height = _pixels(frame)
        _need(_finite(t) and t >= 0 and type(frame_index) is int and 0 <= frame_index < 2**63
              and type(scene) is int and 0 <= scene < 2**63)
        _need(self._time is None or t > self._time and frame_index > self._index)
        _need(self._scene is None or scene >= self._scene)
        _need(type(seeds) is list and len(seeds) <= PARAMETERS['maximum_live_markers'])
        checked = {}
        for row in seeds:
            _need(type(row) is dict and set(row) == {'key', 'box'} and
                  type(row['key']) is str and 0 < len(row['key']) <= 128 and
                  not any(ord(c) < 32 or ord(c) == 127 for c in row['key']) and
                  row['key'] not in checked)
            checked[row['key']] = _box(row['box'], width, height)
        reset_reason = None
        if self._time is not None:
            if scene != self._scene:
                reset_reason = 'SCENE_CHANGE'
            elif self._shape != (width, height):
                reset_reason = 'FRAME_SIZE_CHANGE'
            elif Fraction(str(t))-Fraction(str(self._time)) >= Fraction(str(self.max_gap)):
                reset_reason = 'TIME_GAP'
        _need(reset_reason is not None or
              len(set(self._tracks) | set(checked)) <= PARAMETERS['maximum_live_markers'])
        # No mutable state is changed until every input and all image work
        # succeed. Original BGR and the copied grayscale have distinct owners.
        import cv2 as cv
        import numpy as np
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        current_sha = sha256(frame.tobytes()).hexdigest()
        current, rows, lost = {}, [], {}
        for key, old in sorted(self._tracks.items()):
            if key in checked:
                continue
            if reset_reason:
                lost[key] = reset_reason
                continue
            try:
                followed, reason = _follow(self._gray, gray, old, cv, np)
            except (cv.error, np.linalg.LinAlgError):
                followed, reason = None, 'PIXEL_COMPUTATION_FAILED'
            if followed is None:
                lost[key] = reason
                continue
            current[key] = dict(box=list(followed['box']), points=followed['points'].copy())
            rows.append(dict(key=key, box=list(followed['box']), status='TRACKED',
                point_count=len(followed['points']),
                median_displacement_px=list(followed['median_displacement_px']),
                median_forward_backward_error_px=followed['median_forward_backward_error_px'],
                displacement_dispersion_px=followed['displacement_dispersion_px'],
                affine_area_ratio=followed['affine_area_ratio'], explicit_seed=False,
                previous_frame_sha256=self._sha))
        for key, box in sorted(checked.items()):
            try:
                points = _seed(gray, box, cv, np)
            except cv.error:
                points = None
            if points is None:
                lost[key] = 'INSUFFICIENT_TEXTURE'
                continue
            current[key] = dict(box=list(box), points=points.copy())
            rows.append(dict(key=key, box=list(box), status='SEEDED',
                point_count=len(points), median_displacement_px=None,
                median_forward_backward_error_px=None, displacement_dispersion_px=None,
                affine_area_ratio=None, explicit_seed=True, previous_frame_sha256=None))
        result = dict(schema_version=SCHEMA, coordinate_space='IMAGE_PX',
            t=float(t), frame_index=frame_index, scene=scene, frame_sha256=current_sha,
            tracked=sorted(rows, key=lambda r: r['key']), lost_keys=sorted(lost),
            loss_reasons=lost, parameters=dict(PARAMETERS),
            repeated_frame_pixels=current_sha == self._sha,
            model_eligible=False, metric_positions_inferred=False,
            numeric_identity_inferred=False, field_validation='NOT_ESTABLISHED')
        # Finish the fallible allocation before publishing any new state.
        stored_gray = gray.copy()
        self._tracks = current
        self._gray = stored_gray
        self._time, self._index, self._scene = float(t), frame_index, scene
        self._shape, self._sha = (width, height), current_sha
        return result
