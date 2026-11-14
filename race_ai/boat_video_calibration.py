"""Conditional water-plane projection from independently supplied landmarks.

Fit anchors and check landmarks are separate observations. Their source hashes,
clock references and pixels are declarations, not authentication. This module
never invents calibration, boat identity, missing samples, strength, real-time
clock certification, or prediction eligibility. Existing image reports remain
unchanged; callers retain this separately sealed derived envelope.
"""
from copy import deepcopy
import math
import re

from .actions_contract import digest
from .boat_video_measurements import _tracks, measure_tracks


MANIFEST_SCHEMA = 'RACE_AI_BOAT_VIDEO_CALIBRATION_V1'
TRACKS_SCHEMA = 'RACE_AI_BOAT_VIDEO_CALIBRATED_TRACKS_V1'
MEASUREMENTS_SCHEMA = 'RACE_AI_BOAT_VIDEO_CALIBRATED_MEASUREMENTS_V1'
_ERROR = 'BOAT_VIDEO_CALIBRATION_REJECTED'
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_MANIFEST_FIELDS = set('schema_version media_sha256 source_tracking_sha256 report_sha256 dataset_status '
    'world_frame_id world_frame_source_sha256 anchor_coordinate_space world_units ground_plane '
    'clock_reference frames calibration_sha256'.split())
_FRAME_FIELDS = set('frame_index camera_scene decoded_frame_sha256 reference_frame_sha256 '
    'fit_source_sha256 check_source_sha256 anchors checks'.split())
_MAX_ERROR_M = .25
_MAX_CLOCK_RELATIVE_UNCERTAINTY = .01


def _need(condition):
    if not condition:
        raise ValueError(_ERROR)


def _number(value, *, bound=1e8):
    return type(value) in (int, float) and math.isfinite(value) and abs(value) <= bound


def _hash(value, optional=False):
    _need(optional and value is None or type(value) is str and _SHA.fullmatch(value) is not None)


def _point(value):
    _need(type(value) in (list, tuple) and len(value) == 2 and all(_number(v) for v in value))
    return tuple(float(v) for v in value)


def _landmarks(rows, minimum):
    _need(type(rows) is list and minimum <= len(rows) <= 128)
    result, seen_ids, seen_image, seen_world = [], set(), set(), set()
    for row in rows:
        _need(type(row) is dict and set(row) == {'id', 'reference_xy', 'world_xy'})
        _need(type(row['id']) is str and _ID.fullmatch(row['id']) is not None and row['id'] not in seen_ids)
        image, world = _point(row['reference_xy']), _point(row['world_xy'])
        _need(image not in seen_image and world not in seen_world)
        seen_ids.add(row['id']); seen_image.add(image); seen_world.add(world)
        result.append((row['id'], image, world))
    return result


def _hull(points):
    points = sorted(set(points))
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower, upper = [], []
    for chain, sequence in ((lower, points), (upper, reversed(points))):
        for point in sequence:
            while len(chain) >= 2 and cross(chain[-2], chain[-1], point) <= 0:
                chain.pop()
            chain.append(point)
    return lower[:-1]+upper[:-1]


def _inside(point, hull):
    if len(hull) < 3:
        return False
    scale = max(1., max(abs(v) for p in hull for v in p))
    tolerance = 1e-10 * scale * scale
    return all((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]) >= -tolerance
               for a, b in zip(hull, hull[1:]+hull[:1]))


def _project(matrix, point):
    x, y = point
    divisor = matrix[2][0]*x+matrix[2][1]*y+matrix[2][2]
    _need(_number(divisor) and abs(divisor) > 1e-12)
    projected = tuple((matrix[i][0]*x+matrix[i][1]*y+matrix[i][2])/divisor for i in (0, 1))
    _need(all(_number(v) for v in projected))
    return projected


def _fit(anchors):
    # Normalized DLT, with no check-landmark data in the fitted matrix.
    try:
        import numpy as np
    except ImportError:
        raise ValueError('BOAT_VIDEO_CALIBRATION_NUMPY_REQUIRED') from None
    def normalize(points):
        points = np.asarray(points, dtype=np.float64)
        center = points.mean(axis=0)
        distance = np.linalg.norm(points-center, axis=1).mean()
        _need(np.isfinite(distance) and distance > 1e-12)
        scale = math.sqrt(2.)/float(distance)
        transform = np.array([[scale, 0., -scale*center[0]], [0., scale, -scale*center[1]], [0., 0., 1.]])
        return (points-center)*scale, transform
    origin, origin_transform = normalize([row[1] for row in anchors])
    target, target_transform = normalize([row[2] for row in anchors])
    equations = []
    for (x, y), (a, b) in zip(origin, target):
        equations.extend([[-x, -y, -1., 0., 0., 0., a*x, a*y, a],
                          [0., 0., 0., -x, -y, -1., b*x, b*y, b]])
    try:
        _, singular, right = np.linalg.svd(np.asarray(equations), full_matrices=len(equations) < 9)
        _need(len(singular) >= 8 and singular[7] > 1e-10*singular[0])
        matrix = np.linalg.inv(target_transform) @ right[-1].reshape(3, 3) @ origin_transform
        _need(np.isfinite(matrix).all())
        matrix /= np.linalg.norm(matrix)
        _need(np.linalg.matrix_rank(matrix, tol=1e-12) == 3)
    except np.linalg.LinAlgError:
        raise ValueError(_ERROR) from None
    matrix = matrix.tolist()
    divisors = [matrix[2][0]*p[1][0]+matrix[2][1]*p[1][1]+matrix[2][2] for p in anchors]
    _need(all(d > 1e-12 for d in divisors) or all(d < -1e-12 for d in divisors))
    return matrix


def _clock(value, duration):
    _need(type(value) is dict and set(value) == {'source_sha256', 'points'})
    _hash(value['source_sha256'])
    points = value['points']
    _need(type(points) is list and 2 <= len(points) <= 20000)
    checked = []
    for row in points:
        _need(type(row) is dict and set(row) == {'media_t', 'reference_elapsed_seconds', 'uncertainty_seconds'})
        t, elapsed, error = (row[k] for k in ('media_t', 'reference_elapsed_seconds', 'uncertainty_seconds'))
        _need(_number(t) and 0 <= t <= duration and _number(elapsed, bound=1e12) and elapsed >= 0
              and _number(error) and 0 <= error <= 1)
        if checked:
            previous_t, previous_elapsed, previous_error = checked[-1]
            dt, actual_dt = t-previous_t, elapsed-previous_elapsed
            _need(dt > 0 and actual_dt > 0)
            uncertainty = error+previous_error
            # Zero declared uncertainty still permits machine arithmetic noise.
            _need(uncertainty/dt <= _MAX_CLOCK_RELATIVE_UNCERTAINTY
                  and abs(actual_dt-dt) <= uncertainty+1e-9*max(1., dt))
        checked.append((float(t), float(elapsed), float(error)))
    return {'status': 'REFERENCE_DIFFERENCES_AGREE_NOT_AUTHENTICATED',
            'source_sha256': value['source_sha256'], 'points': deepcopy(points),
            'media_t_start': checked[0][0], 'media_t_end': checked[-1][0],
            'maximum_relative_uncertainty': max((a[2]+b[2])/(b[0]-a[0])
                                                for a,b in zip(checked,checked[1:])),
            'physical_clock_certified': False,
            'rate_error_bound': 'NOT_ESTABLISHED_FROM_REFERENCE_POINTS_BETWEEN_OBSERVATIONS'}


def _camera_frames(tracking):
    """Replay the tracker's actual camera-reference resets, never invent one."""
    import numpy as np
    quality = tracking.get('quality')
    _need(type(quality) is dict)
    estimates, observations = quality.get('camera_estimates'), quality.get('identity_observations')
    _need(type(estimates) is list and 1 <= len(estimates) <= 20000
          and type(observations) is list and len(observations) == len(estimates))
    by_frame = {}
    for row in observations:
        _need(type(row) is dict and type(row.get('frame_index')) is int and row['frame_index'] >= 0
              and row['frame_index'] not in by_frame and _number(row.get('t')))
        _hash(row.get('decoded_frame_sha256'))
        _need(type(row.get('scene')) is int and row['scene'] >= 0)
        by_frame[row['frame_index']] = row
    result, transform, scene, reference = {}, np.eye(3), 0, None
    previous_index = previous_t = -1
    for index_in_sequence, row in enumerate(estimates):
        _need(type(row) is dict and type(row.get('frame_index')) is int)
        index, t = row['frame_index'], row.get('t')
        _need(index > previous_index and _number(t) and t > previous_t and 0 <= t <= tracking['duration_seconds']
              and index in by_frame and by_frame[index]['t'] == t)
        raw = row.get('homography_previous_to_current')
        if index_in_sequence == 0:
            _need(index == 0 and t == 0 and row.get('status') == 'REFERENCE_INITIALIZATION' and raw is None)
            reference = by_frame[index]['decoded_frame_sha256']
        elif row.get('status') == 'ACCEPTED':
            _need(type(raw) is list and len(raw) == 3 and all(type(r) is list and len(r) == 3
                  and all(_number(n) for n in r) for r in raw))
            matrix = np.asarray(raw,dtype=np.float64)
            _need(abs(matrix[2,2]) > 1e-8)
            try:
                transform = transform @ np.linalg.inv(matrix)
            except np.linalg.LinAlgError:
                raise ValueError(_ERROR) from None
            _need(np.isfinite(transform).all() and abs(transform[2,2]) > 1e-12)
            transform /= transform[2,2]
        else:
            _need(type(row.get('status')) is str and raw is None)
            scene += 1
            transform = np.eye(3)
            reference = by_frame[index]['decoded_frame_sha256']
        _need(by_frame[index]['scene'] == scene)
        result[index] = {'camera_scene':scene,'source_pts_seconds':float(t),
            'decoded_frame_sha256':by_frame[index]['decoded_frame_sha256'],
            'reference_frame_sha256':reference,'raw_to_reference':transform.tolist(),
            'camera_status':row['status']}
        previous_index, previous_t = index, t
    _need(set(result) == set(by_frame))
    return result


def _frames(manifest, tracking):
    import numpy as np
    value = manifest['frames']
    _need(type(value) is list and 1 <= len(value) <= 20000)
    frames, camera_frames = {}, _camera_frames(tracking)
    sample_bindings = {}
    for track in tracking['tracks']:
        for row in track['samples']:
            if row['valid']:
                index = row['frame_index']
                _hash(row.get('frame_sha256'))
                _need(type(row.get('camera_scene')) is int and row['camera_scene'] >= 0)
                binding = row['camera_scene'], row['frame_sha256']
                _need(index not in sample_bindings or sample_bindings[index] == binding)
                _need(index in camera_frames and camera_frames[index]['camera_status'] == 'ACCEPTED'
                      and camera_frames[index]['source_pts_seconds'] == row['t']
                      and camera_frames[index]['camera_scene'] == binding[0]
                      and camera_frames[index]['decoded_frame_sha256'] == binding[1])
                sample_bindings[index] = binding
    landmark_worlds, fit_ids, check_ids, fit_worlds, check_worlds = {}, set(), set(), set(), set()
    for row in value:
        _need(type(row) is dict and set(row) == _FRAME_FIELDS)
        index, scene = row['frame_index'], row['camera_scene']
        _need(type(index) is int and index >= 0 and index not in frames
              and type(scene) is int and scene >= 0)
        for key in ('decoded_frame_sha256', 'reference_frame_sha256', 'fit_source_sha256', 'check_source_sha256'):
            _hash(row[key])
        _need(index in camera_frames)
        camera = camera_frames[index]
        _need(camera['camera_scene'] == scene and camera['decoded_frame_sha256'] == row['decoded_frame_sha256']
              and camera['reference_frame_sha256'] == row['reference_frame_sha256'])
        anchors, checks = _landmarks(row['anchors'], 4), _landmarks(row['checks'], 2)
        _need(all(0 <= p[1][0] <= tracking['width']-1 and 0 <= p[1][1] <= tracking['height']-1
                  for p in anchors+checks))
        for key in (0, 1, 2):
            _need(not {p[key] for p in anchors}.intersection(p[key] for p in checks))
        for id_, _, world in anchors+checks:
            _need(id_ not in landmark_worlds or landmark_worlds[id_] == world)
            landmark_worlds[id_] = world
        fit_ids.update(p[0] for p in anchors); check_ids.update(p[0] for p in checks)
        fit_worlds.update(p[2] for p in anchors); check_worlds.update(p[2] for p in checks)
        _need(not fit_ids.intersection(check_ids) and not fit_worlds.intersection(check_worlds))
        raw_hull = _hull([p[1] for p in anchors])
        _need(len(raw_hull) >= 3 and all(_inside(p[1], raw_hull) for p in checks))
        raw_matrix = _fit(anchors)
        fit_error = max(math.dist(_project(raw_matrix, p[1]), p[2]) for p in anchors)
        check_error = max(math.dist(_project(raw_matrix, p[1]), p[2]) for p in checks)
        _need(fit_error <= _MAX_ERROR_M and check_error <= _MAX_ERROR_M)
        raw_to_reference = camera['raw_to_reference']
        matrix = (np.asarray(raw_matrix) @ np.linalg.inv(np.asarray(raw_to_reference))).tolist()
        _need(all(_number(n) for r in matrix for n in r))
        hull = _hull([_project(raw_to_reference,p[1]) for p in anchors])
        frames[index] = {'frame_index': index, 'camera_scene': scene,
            'source_pts_seconds':camera['source_pts_seconds'],'raw_to_reference':raw_to_reference,
            'decoded_frame_sha256': row['decoded_frame_sha256'],
            'reference_frame_sha256': row['reference_frame_sha256'],
            'fit_source_sha256': row['fit_source_sha256'], 'check_source_sha256': row['check_source_sha256'],
            'raw_to_world':raw_matrix,'reference_to_world': matrix,
            'support_polygon_reference_xy': [list(p) for p in hull],
            'training_anchor_count': len(anchors), 'independent_check_count': len(checks),
            'max_fit_error_m': fit_error, 'max_check_error_m': check_error,
            'position_reference_error_m': max(fit_error, check_error),
            'scope': 'SUPPLIED_DISJOINT_CHECK_LANDMARKS_NOT_FIELD_AUTHENTICATION'}
    return frames


def _position_error(matrix, point, world, supplied):
    # Exact difference bound for a homography over a supplied image-error disk.
    # This bounds only the supplied error, not the quality/authenticity of it.
    c0, c1, c2 = matrix[2]
    divisor = abs(c0*point[0]+c1*point[1]+c2)
    lower = divisor-math.hypot(c0,c1)*supplied
    _need(lower > 1e-12)
    coefficients = [matrix[i][j]-world[i]*matrix[2][j] for i in (0,1) for j in (0,1)]
    bound = math.sqrt(sum(c*c for c in coefficients))*supplied/lower
    _need(_number(bound) and bound >= 0)
    return bound


def _tracking(value):
    _need(type(value) is dict and value.get('schema_version') == 'RACE_AI_BOAT_VIDEO_TRACKS_V1'
          and value.get('coordinate_space') == 'REFERENCE_IMAGE_PX' and value.get('timeline_source') == 'MEDIA_PTS'
          and value.get('validation_status') == 'UNVALIDATED' and value.get('model_eligible') is False)
    _hash(value.get('media_sha256'))
    _need(all(type(value.get(k)) is int and 0 < value[k] <= 16384 for k in ('width','height')))
    _need(_number(value.get('duration_seconds')) and value['duration_seconds'] >= 0)
    _tracks(value['tracks'])
    _need(len(value['tracks']) == 6 and {r['lane'] for r in value['tracks']} == set(range(1,7)))
    for track in value['tracks']:
        _need(len(track['samples']) <= 20000 and all(r['t'] <= value['duration_seconds'] for r in track['samples']))
    return value


def calibrate_tracks(tracking, manifest):
    """Project bound observed points; missing evidence stays an invalid sample.

    The manifest contains explicitly supplied raw decoded-frame anchors and
    independent checks per frame, their original source hashes, a ground-plane
    metre declaration, and independent clock-reference observations. Global
    camera_scene selects the image reference; lane-local scene preserves
    occlusion continuity. Source hashes do not authenticate these declarations.
    """
    try:
        source = _tracking(tracking)
        _need(type(manifest) is dict and set(manifest) == _MANIFEST_FIELDS)
        _hash(manifest['calibration_sha256'])
        _need(manifest['calibration_sha256'] == digest({k:v for k,v in manifest.items() if k!='calibration_sha256'}))
        _need(manifest['schema_version'] == MANIFEST_SCHEMA
              and manifest['media_sha256'] == source['media_sha256']
              and manifest['source_tracking_sha256'] == digest(source)
              and manifest['anchor_coordinate_space'] == 'RAW_DECODED_FRAME_PX'
              and manifest['world_units'] == 'm' and manifest['ground_plane'] is True
              and manifest['dataset_status'] in ('SYNTHETIC_ONLY','REAL_REPORTED'))
        _hash(manifest['report_sha256'],optional=True)
        _need(type(manifest['world_frame_id']) is str and _ID.fullmatch(manifest['world_frame_id']) is not None)
        _hash(manifest['world_frame_source_sha256'])
        clock = _clock(manifest['clock_reference'], source['duration_seconds'])
        frames = _frames(manifest, source)
        tracks = deepcopy(source['tracks'])
        used_checks = {}
        for track in tracks:
            for row in track['samples']:
                if not row['valid']:
                    # The retained source hash binds its original pixels. Null
                    # invalid derived coordinates avoid labelling image units m.
                    row.update(x=None,y=None,position_error=None)
                    continue
                reason, calibration = None, frames.get(row['frame_index'])
                if calibration is None:
                    reason = 'FRAME_CALIBRATION_MISSING'
                elif not clock['media_t_start'] <= row['t'] <= clock['media_t_end']:
                    reason = 'CLOCK_REFERENCE_COVERAGE_MISSING'
                elif not _number(row.get('position_error')) or row['position_error'] < 0:
                    reason = 'SOURCE_POSITION_ERROR_MISSING'
                elif not _inside((row['x'],row['y']),calibration['support_polygon_reference_xy']):
                    reason = 'OUTSIDE_CALIBRATION_SUPPORT'
                if reason:
                    row.update(valid=False,x=None,y=None,position_error=None,reason=reason)
                    continue
                matrix, point = calibration['reference_to_world'], (row['x'],row['y'])
                world = _project(matrix,point)
                try:
                    error = _position_error(matrix,point,world,row['position_error'])
                except ValueError:
                    row.update(valid=False,x=None,y=None,position_error=None,reason='POSITION_UNCERTAINTY_CROSSES_HORIZON')
                    continue
                row.update(x=world[0],y=world[1],position_error=error+calibration['position_reference_error_m'])
                used_checks[(row['scene'],row['frame_index'])] = calibration['position_reference_error_m']
        maximum = max((r['position_reference_error_m'] for r in frames.values()), default=0.)
        evidence = {'validation_status':'CALIBRATION_PROVIDED_UNVERIFIED',
            'source_sha256':manifest['calibration_sha256'],
            'reference_frame_sha256':next(iter(frames.values()))['reference_frame_sha256'],
            'ground_plane':True,'world_units':'m',
            'training_anchor_count':min(r['training_anchor_count'] for r in frames.values()),
            'independent_check_count':min(r['independent_check_count'] for r in frames.values()),
            'max_check_error_m':maximum,
            'per_frame_checks':[{'scene':scene,'frame_index':index,'max_check_error_m':error}
                                for (scene,index),error in sorted(used_checks.items())]}
        out = {'schema_version':TRACKS_SCHEMA,'media_sha256':source['media_sha256'],
            'source_tracking_sha256':digest(source),'report_sha256':manifest['report_sha256'],
            'calibration_sha256':manifest['calibration_sha256'],
            'world_frame_id':manifest['world_frame_id'],'world_frame_source_sha256':manifest['world_frame_source_sha256'],
            'dataset_status':manifest['dataset_status'],'coordinate_space':'WATER_PLANE_METRES',
            'time_basis':'MEDIA_TIMELINE_SECONDS','tracks':tracks,'calibration_evidence':evidence,
            'clock_evidence':clock,'per_frame_validation':list(frames.values()),
            'validation_status':'UNVALIDATED','provenance_authentication':'NOT_ESTABLISHED',
            'identity_validated':False,'independent_human_heldout_verified':False,
            'prediction_eligible':False,'production_eligible':False,
            'physical_velocity':'NOT_ESTABLISHED',
            'point_scope':'SUPPLIED_TRACK_POINT_NOT_VERIFIED_WATER_CONTACT',
            'validation_gaps':['SOURCE_PROVENANCE_AUTHENTICATION_NOT_ESTABLISHED',
                'BOAT_GROUND_PLANE_CONTACT_UNVERIFIED','SOURCE_POSITION_ERROR_HEURISTIC_UNCERTIFIED',
                'CLOCK_CORRESPONDENCE_BETWEEN_REFERENCE_OBSERVATIONS_UNVERIFIED',
                'INDEPENDENT_HUMAN_HELDOUT_MEASUREMENT_VALIDATION_MISSING'],
            'uncertainty_scope':'SUPPLIED_PIXEL_ERROR_AND_OBSERVED_CALIBRATION_RESIDUAL_ONLY_UNCERTIFIED'}
        out['envelope_sha256']=digest(out)
        return out
    except ImportError:
        raise ValueError('BOAT_VIDEO_CALIBRATION_NUMPY_REQUIRED') from None
    except (KeyError,TypeError,OverflowError,RecursionError,ValueError) as exc:
        if str(exc)=='BOAT_VIDEO_CALIBRATION_NUMPY_REQUIRED':
            raise ValueError(str(exc)) from None
        raise ValueError(_ERROR) from None


def measure_calibrated_tracks(tracking, manifest, *, phase_windows=None, start_gate=None, max_gap_seconds=.3):
    """Measure per-boat physical-coordinate windows, retaining conditional scope.

    Sequential exhibition phases need not share frames after valid water-plane
    projection. This computes raw sampled geometry, never a competitive rating
    or comparability certification. Runup still requires an observed start gate.
    """
    calibrated=calibrate_tracks(tracking,manifest)
    measurements=measure_tracks(calibrated['tracks'],coordinate_space='WATER_PLANE_METRES',
        phase_windows=phase_windows,start_gate=start_gate,
        calibration_evidence=calibrated['calibration_evidence'],max_gap_seconds=max_gap_seconds)
    out={'schema_version':MEASUREMENTS_SCHEMA,'calibrated_tracking':calibrated,
         'measurements':measurements,'measurements_sha256':digest(measurements),
         'phase_scope':'PER_BOAT_WINDOWS_NOT_COMPARATIVE_STRENGTH',
         'validation_status':'UNVALIDATED','independent_human_heldout_verified':False,
         'prediction_eligible':False,'production_eligible':False}
    out['envelope_sha256']=digest(out)
    return out
