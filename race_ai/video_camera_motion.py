"""Bounded, RAM-only background camera estimates in image pixels.

The limited affine maps previous-frame points into the current frame. An
accepted fit is evidence for that image pair only. It establishes no boat or
lane identity, world calibration, physical performance, or prediction value.
There is no identity-transform fallback when evidence is inadequate.
"""
import math
from numbers import Real


MAX_PIXELS = 1280 * 720
MAX_DIMENSION = 1280
MIN_DIMENSION = 64
MAX_FEATURES = 400
MIN_FEATURES = 24
MIN_INLIERS = 20
MIN_INLIER_RATIO = .75
MIN_COVERAGE = .20
MIN_GRID_CELLS = 6
MAX_REPROJECTION_RMSE = 1.0
MAX_REPROJECTION_P90 = 1.5
MAX_PHOTOMETRIC_ERROR = 18.0
MIN_OVERLAP = .50
EXCLUSION_PADDING = 24


def _number(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _claims():
    return {'metric_units': 'CAMERA_ESTIMATED_PIXELS', 'boat_identity': 'UNVERIFIED',
            'world_calibration': 'UNVERIFIED', 'prediction_eligible': False}


def _result(status, **quality):
    result = {'status': status, 'accepted': False, 'affine_previous_to_current': None,
              'feature_count': 0, 'tracked_count': 0, 'inlier_count': 0, 'inlier_ratio': 0.0,
              'spatial_coverage': 0.0, 'covered_grid_cells': 0,
              'horizontal_span_ratio': 0.0, 'vertical_span_ratio': 0.0,
              'reprojection_rmse_pixels': None, 'reprojection_p90_pixels': None,
              'photometric_mean_error': None, 'background_overlap_ratio': 0.0,
              'frame_width': None, 'frame_height': None, **_claims()}
    result.update(quality)
    return result


def _dimensions(width, height):
    return (type(width) is int and type(height) is int
            and MIN_DIMENSION <= width <= MAX_DIMENSION
            and MIN_DIMENSION <= height <= MAX_DIMENSION and width * height <= MAX_PIXELS)


def _matrix_valid(matrix, width, height):
    if not isinstance(matrix, (list, tuple)) or len(matrix) != 2:
        return False
    if any(not isinstance(row, (list, tuple)) or len(row) != 3 for row in matrix):
        return False
    if not all(_number(value) for row in matrix for value in row):
        return False
    (a, b, tx), (c, d, ty) = matrix
    # estimateAffinePartial2D promises rotation + uniform scale, no shear/reflection.
    scale = math.hypot(a, c)
    if (not .90 <= scale <= 1.10 or abs(a - d) > 1e-5 or abs(b + c) > 1e-5
            or a * d - b * c <= 0 or abs(math.degrees(math.atan2(c, a))) > 12):
        return False
    limit = .20 * math.hypot(width, height)
    return all(math.hypot(a*x + b*y + tx - x, c*x + d*y + ty - y) <= limit
               for x, y in ((0, 0), (width-1, 0), (0, height-1), (width-1, height-1)))


def _background_mask(np, shape, exclusions):
    height, width = shape
    if not isinstance(exclusions, (list, tuple)) or len(exclusions) > 64:
        return None
    mask = np.full((height, width), 255, dtype=np.uint8)
    mask[:12] = mask[-12:] = 0
    mask[:, :12] = mask[:, -12:] = 0
    for box in exclusions:
        if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(_number(v) for v in box):
            return None
        x, y, box_width, box_height = box
        if not (0 <= x < width and 0 <= y < height and box_width > 0 and box_height > 0
                and x + box_width <= width and y + box_height <= height):
            return None
        left, top = max(0, math.floor(x)-EXCLUSION_PADDING), max(0, math.floor(y)-EXCLUSION_PADDING)
        right = min(width, math.ceil(x+box_width)+EXCLUSION_PADDING)
        bottom = min(height, math.ceil(y+box_height)+EXCLUSION_PADDING)
        mask[top:bottom, left:right] = 0
    return mask


def estimate_camera_motion(previous_bgr, current_bgr, *, previous_exclusions=(), current_exclusions=()):
    """Fit bounded background flow; exclusions are in-frame (x, y, width, height).

    Inputs must be same-size uint8 HxWx3 BGR numpy arrays. At most 400 corners
    and 64 exclusions per frame are considered. Returned JSON-safe derivatives
    never include pixels, feature coordinates, or a transform for a failed fit.
    Quality gates are conservative heuristics, not physical calibration.
    """
    try:
        import cv2
        import numpy as np
    except (ImportError, OSError):
        return _result('UNVERIFIED_RUNTIME_UNAVAILABLE')
    for frame in (previous_bgr, current_bgr):
        if (type(frame) is not np.ndarray or frame.dtype != np.uint8 or frame.ndim != 3
                or frame.shape[2] != 3 or not _dimensions(frame.shape[1], frame.shape[0])):
            return _result('UNVERIFIED_INVALID_FRAME')
    if previous_bgr.shape != current_bgr.shape:
        return _result('UNVERIFIED_SIZE_CHANGE')
    height, width = previous_bgr.shape[:2]
    quality = {'frame_width': width, 'frame_height': height}
    previous_mask = _background_mask(np, (height, width), previous_exclusions)
    current_mask = _background_mask(np, (height, width), current_exclusions)
    if previous_mask is None or current_mask is None:
        return _result('UNVERIFIED_INVALID_EXCLUSIONS', **quality)
    try:
        previous = cv2.cvtColor(previous_bgr, cv2.COLOR_BGR2GRAY)
        current = cv2.cvtColor(current_bgr, cv2.COLOR_BGR2GRAY)
        points = cv2.goodFeaturesToTrack(previous, maxCorners=MAX_FEATURES, qualityLevel=.02,
            minDistance=8, mask=previous_mask, blockSize=7)
        quality['feature_count'] = 0 if points is None else len(points)
        if quality['feature_count'] < MIN_FEATURES:
            return _result('UNVERIFIED_INSUFFICIENT_FEATURES', **quality)
        if not np.any(current_mask):
            return _result('UNVERIFIED_INSUFFICIENT_TRACKS', **quality)
        hist_previous = np.bincount((previous[previous_mask > 0] // 8), minlength=32)
        hist_current = np.bincount((current[current_mask > 0] // 8), minlength=32)
        histogram_distance = float(np.abs(hist_previous / hist_previous.sum()
                                         - hist_current / hist_current.sum()).sum())
        if histogram_distance > .90:
            return _result('UNVERIFIED_SCENE_CHANGE', **quality)
        options = {'winSize': (21, 21), 'maxLevel': 3,
                   'criteria': (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01)}
        moved, found, error = cv2.calcOpticalFlowPyrLK(previous, current, points, None, **options)
        if moved is None or found is None or error is None or not np.isfinite(moved).all():
            return _result('UNVERIFIED_INSUFFICIENT_TRACKS', **quality)
        returned, backward_found, _ = cv2.calcOpticalFlowPyrLK(current, previous, moved, None, **options)
        if returned is None or backward_found is None or not np.isfinite(returned).all():
            return _result('UNVERIFIED_INSUFFICIENT_TRACKS', **quality)
        source, destination = points.reshape(-1, 2), moved.reshape(-1, 2)
        inside = ((destination[:, 0] >= 0) & (destination[:, 0] < width)
                  & (destination[:, 1] >= 0) & (destination[:, 1] < height))
        in_background = np.zeros(len(points), dtype=bool)
        bounded = destination[inside].astype(int)
        in_background[inside] = current_mask[bounded[:, 1], bounded[:, 0]] > 0
        usable = (found.reshape(-1).astype(bool) & backward_found.reshape(-1).astype(bool)
                  & np.isfinite(error.reshape(-1)) & (error.reshape(-1) <= 20)
                  & (np.linalg.norm(returned.reshape(-1, 2) - source, axis=1) <= 1.0)
                  & inside & in_background)
        source, destination = source[usable], destination[usable]
        quality['tracked_count'] = len(source)
        if len(source) < MIN_FEATURES:
            return _result('UNVERIFIED_INSUFFICIENT_TRACKS', **quality)
        affine, reported_inliers = cv2.estimateAffinePartial2D(source, destination, method=cv2.RANSAC,
            ransacReprojThreshold=1.5, maxIters=1000, confidence=.99, refineIters=10)
        if affine is None or not _matrix_valid(affine.tolist(), width, height):
            return _result('UNVERIFIED_INVALID_TRANSFORM', **quality)
        if (reported_inliers is None or reported_inliers.shape != (len(source), 1)
                or not np.isin(reported_inliers, (0, 1)).all()):
            return _result('UNVERIFIED_INSUFFICIENT_INLIERS', **quality)
        projected = source @ affine[:, :2].T + affine[:, 2]
        errors = np.linalg.norm(projected - destination, axis=1)
        inliers = reported_inliers.reshape(-1).astype(bool) & (errors <= 1.5)
        quality.update(inlier_count=int(inliers.sum()), inlier_ratio=float(inliers.mean()))
        if quality['inlier_count'] < MIN_INLIERS or quality['inlier_ratio'] < MIN_INLIER_RATIO:
            return _result('UNVERIFIED_INSUFFICIENT_INLIERS', **quality)
        support = source[inliers]
        hull_area = cv2.contourArea(cv2.convexHull(support))
        cells = {(min(3, int(x*4/width)), min(2, int(y*3/height))) for x, y in support}
        quality.update(spatial_coverage=float(hull_area / (width*height)), covered_grid_cells=len(cells),
            horizontal_span_ratio=float(np.ptp(support[:, 0])/width),
            vertical_span_ratio=float(np.ptp(support[:, 1])/height))
        if (quality['spatial_coverage'] < MIN_COVERAGE or len(cells) < MIN_GRID_CELLS
                or quality['horizontal_span_ratio'] < .50 or quality['vertical_span_ratio'] < .50):
            return _result('UNVERIFIED_SPATIAL_SUPPORT', **quality)
        quality.update(reprojection_rmse_pixels=float(np.sqrt(np.mean(errors[inliers]**2))),
                       reprojection_p90_pixels=float(np.percentile(errors[inliers], 90)))
        if (quality['reprojection_rmse_pixels'] > MAX_REPROJECTION_RMSE
                or quality['reprojection_p90_pixels'] > MAX_REPROJECTION_P90):
            return _result('UNVERIFIED_REPROJECTION_ERROR', **quality)
        warped = cv2.warpAffine(previous, affine, (width, height))
        warped_mask = cv2.warpAffine(previous_mask, affine, (width, height), flags=cv2.INTER_NEAREST)
        common = (warped_mask > 0) & (current_mask > 0)
        # Both areas must be measured in destination pixels when scale differs.
        denominator = min(int((warped_mask > 0).sum()), int((current_mask > 0).sum()))
        quality['background_overlap_ratio'] = float(common.sum() / denominator)
        if quality['background_overlap_ratio'] < MIN_OVERLAP:
            return _result('UNVERIFIED_BACKGROUND_OVERLAP', **quality)
        quality['photometric_mean_error'] = float(np.abs(warped[common].astype(float)
                                                        - current[common].astype(float)).mean())
        if quality['photometric_mean_error'] > MAX_PHOTOMETRIC_ERROR:
            return _result('UNVERIFIED_SCENE_CHANGE', **quality)
        return _result('ACCEPTED', **quality, accepted=True, affine_previous_to_current=affine.tolist())
    except (cv2.error, ValueError, TypeError, OverflowError):
        return _result('UNVERIFIED_COMPUTATION_ERROR', **quality)


def _accepted_motion(motion):
    if not isinstance(motion, dict) or motion.get('status') != 'ACCEPTED' or motion.get('accepted') is not True:
        return False
    if (motion.get('prediction_eligible') is not False
            or any(motion.get(key) != value for key, value in _claims().items())):
        return False
    width, height = motion.get('frame_width'), motion.get('frame_height')
    if not _dimensions(width, height) or not _matrix_valid(motion.get('affine_previous_to_current'), width, height):
        return False
    counts = [motion.get(key) for key in ('feature_count', 'tracked_count', 'inlier_count', 'covered_grid_cells')]
    if not all(type(value) is int for value in counts):
        return False
    features, tracked, inliers, cells = counts
    if not (MIN_INLIERS <= inliers <= tracked <= features <= MAX_FEATURES
            and tracked >= MIN_FEATURES and MIN_GRID_CELLS <= cells <= 12):
        return False
    limits = {'inlier_ratio': (MIN_INLIER_RATIO, 1.0), 'spatial_coverage': (MIN_COVERAGE, 1.0),
              'horizontal_span_ratio': (.50, 1.0), 'vertical_span_ratio': (.50, 1.0),
              'background_overlap_ratio': (MIN_OVERLAP, 1.0),
              'reprojection_rmse_pixels': (0.0, MAX_REPROJECTION_RMSE),
              'reprojection_p90_pixels': (0.0, MAX_REPROJECTION_P90),
              'photometric_mean_error': (0.0, MAX_PHOTOMETRIC_ERROR)}
    if any(not _number(motion.get(key)) or not low <= motion[key] <= high
           for key, (low, high) in limits.items()):
        return False
    return abs(motion['inlier_ratio'] - inliers / tracked) <= 1e-8


def candidate_point_residual(motion, previous_point, current_point):
    """Current point minus accepted camera projection, in current-frame pixels.

    Association and identity remain the caller's unverified responsibility. This
    helper defensively rechecks an accepted result's matrix and quality gates.
    """
    result = {'status': 'UNVERIFIED_CAMERA_MOTION', 'accepted': False,
              'residual_dx_pixels': None, 'residual_dy_pixels': None,
              'residual_distance_pixels': None, **_claims()}
    if not _accepted_motion(motion):
        return result
    width, height = motion['frame_width'], motion['frame_height']
    for point in (previous_point, current_point):
        if (not isinstance(point, (tuple, list)) or len(point) != 2 or not all(_number(v) for v in point)
                or not 0 <= point[0] < width or not 0 <= point[1] < height):
            result['status'] = 'UNVERIFIED_INVALID_POINT'
            return result
    (a, b, tx), (c, d, ty) = motion['affine_previous_to_current']
    x, y = previous_point
    dx, dy = current_point[0] - (a*x + b*y + tx), current_point[1] - (c*x + d*y + ty)
    result.update(status='ACCEPTED', accepted=True, residual_dx_pixels=float(dx),
                  residual_dy_pixels=float(dy), residual_distance_pixels=float(math.hypot(dx, dy)))
    return result
