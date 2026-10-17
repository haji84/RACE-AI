"""Conditional sampled water-plane geometry, never field certification.

Each frame needs its own checked mapping and physical-clock correspondence.
Supplied landmark, identity and clock evidence hashes are references only. No
I/O is performed and no result becomes a forecast feature through this module.
"""
import hashlib
import math
from datetime import timedelta, timezone

from .video_hull_quality import _finite, _identifier, _keys, _race, _sha, _time
from .core import SourceError
from web.race_contract import canonical


def _require(condition):
    if not condition:
        raise SourceError('VIDEO_WORLD_MOTION_CONTRACT_INVALID')


def _point(value, bound):
    _require(type(value) is list and len(value) == 2
             and all(_finite(n) and abs(n) <= bound for n in value))
    return tuple(float(n) for n in value)


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _convex(points):
    ordered = sorted(set(points)); lower = []; upper = []
    for p in ordered:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(ordered):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1]+upper[:-1]
    _require(len(hull) >= 3 and abs(sum(_cross((0, 0), a, b)
             for a, b in zip(hull, hull[1:]+hull[:1]))) > 2)
    return hull


def _supported(point, hull):
    return all(_cross(a, b, point) >= -1e-9 for a, b in zip(hull, hull[1:]+hull[:1]))


def _project(matrix, point):
    x, y = point; a, b, c = matrix
    denominator = c[0]*x+c[1]*y+c[2]
    _require(denominator >= 1e-6)
    result = ((a[0]*x+a[1]*y+a[2])/denominator, (b[0]*x+b[1]*y+b[2])/denominator)
    _require(all(math.isfinite(n) and abs(n) <= 10000 for n in result))
    return result


def _calibration(value, observation):
    _keys(value, 'frame_sha256 scene_id width height world_reference_sha256 matrix training_landmarks check_landmarks')
    _require(value['frame_sha256'] == observation['frame_sha256'] and value['scene_id'] == observation['scene_id'])
    _sha(value['world_reference_sha256'])
    width, height = value['width'], value['height']
    _require(type(width) is int and type(height) is int and 0 < width <= 1280 and 0 < height <= 720)
    matrix = value['matrix']
    _require(type(matrix) is list and len(matrix) == 3 and all(type(r) is list and len(r) == 3 for r in matrix))
    _require(all(_finite(n) and abs(n) <= 10000 for row in matrix for n in row))
    _require(abs(matrix[2][2]) >= 1e-9)
    matrix = [[float(n/matrix[2][2]) for n in row] for row in matrix]
    a, b, c = matrix
    determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
    _require(math.isfinite(determinant) and abs(determinant) > 1e-12)
    for corner in ((0, 0), (width, 0), (width, height), (0, height)):
        _project(matrix, corner)
    training, checks = value['training_landmarks'], value['check_landmarks']
    _require(type(training) is list and 4 <= len(training) <= 16
             and type(checks) is list and 2 <= len(checks) <= 16)
    ids = set(); images = set(); worlds = set(); landmarks = []; residual = 0.
    for role, rows in (('training', training), ('check', checks)):
        for row in rows:
            _keys(row, 'anchor_id image world'); _identifier(row['anchor_id'])
            image, world = _point(row['image'], 1280), _point(row['world'], 10000)
            _require(0 <= image[0] <= width and 0 <= image[1] <= height)
            _require(row['anchor_id'] not in ids and image not in images and world not in worlds)
            ids.add(row['anchor_id']); images.add(image); worlds.add(world)
            error = math.dist(_project(matrix, image), world)
            _require(error <= .25); residual = max(residual, error)
            landmarks.append(dict(id=row['anchor_id'], role=role, image=image, world=world))
    support = _convex([p['image'] for p in landmarks if p['role'] == 'training'])
    _require(all(_supported(p['image'], support) for p in landmarks if p['role'] == 'check'))
    point = _point(observation['image_point'], 1280)
    _require(0 <= point[0] <= width and 0 <= point[1] <= height and _supported(point, support))
    reference = (value['world_reference_sha256'], tuple(sorted((p['id'], p['role'], p['world']) for p in landmarks)))
    return _project(matrix, point), residual, reference


def measure_world_track(track):
    """Compute only within one camera scene and a stable, supplied world reference."""
    _keys(track, 'schema_version race_id media_sha256 program_identity_sha256 identity_evidence_sha256 hull_number track_id motion_phase frame_step observations')
    _require(track['schema_version'] == 'image-world-track/v1')
    _race(track['race_id']); _sha(track['media_sha256']); _sha(track['program_identity_sha256']); _sha(track['identity_evidence_sha256'])
    _identifier(track['track_id'])
    _require(type(track['hull_number']) is int and 1 <= track['hull_number'] <= 6
             and track['motion_phase'] in ('STRAIGHT', 'TURN'))
    _require(type(track['frame_step']) is int and 1 <= track['frame_step'] <= 300)
    _require(type(track['observations']) is list and 3 <= len(track['observations']) <= 6000)
    points = []; previous_id = -1; hashes = set(); scene = reference = None
    for observation in track['observations']:
        _keys(observation, 'frame_id frame_sha256 scene_id physical_time clock_evidence_sha256 time_uncertainty_seconds image_point total_world_position_error_bound_metres world_error_bound_evidence_sha256 calibration')
        index = observation['frame_id']
        _require(type(index) is int and previous_id < index <= 20000); previous_id = index
        _sha(observation['frame_sha256']); _sha(observation['clock_evidence_sha256']); _identifier(observation['scene_id'])
        _sha(observation['world_error_bound_evidence_sha256'])
        _require(observation['frame_sha256'] not in hashes); hashes.add(observation['frame_sha256'])
        timestamp = _time(observation['physical_time'])
        try:
            physical_date = timestamp.astimezone(timezone(timedelta(hours=9))).strftime('%Y%m%d')
        except (OverflowError, ValueError):
            _require(False)
        _require(physical_date == track['race_id'][:8])
        time_error = observation['time_uncertainty_seconds']
        position_error = observation['total_world_position_error_bound_metres']
        _require(_finite(time_error) and 0 < time_error <= .02
                 and _finite(position_error) and 0 < position_error <= 1)
        world, residual, current_reference = _calibration(observation['calibration'], observation)
        # Sparse landmark residuals cannot bound the complete water plane. This
        # externally supplied total bound includes mapping AND contact-point
        # errors. The hash references its evidence; neither is certified here.
        _require(residual <= position_error)
        if points:
            gap = (timestamp-points[-1]['time']).total_seconds()
            _require(scene == observation['scene_id'] and reference == current_reference
                     and index == track['observations'][len(points)-1]['frame_id']+track['frame_step']
                     and time_error+points[-1]['time_error'] < gap <= .5)
        else:
            scene, reference = observation['scene_id'], current_reference
        points.append(dict(time=timestamp, time_error=float(time_error), world=world,
                           position_error=float(position_error)))
    _require((points[-1]['time']-points[0]['time']).total_seconds() <= 600)
    segments = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        duration = (b['time']-a['time']).total_seconds(); time_error = a['time_error']+b['time_error']
        distance = math.dist(a['world'], b['world']); error = a['position_error']+b['position_error']
        dx, dy = b['world'][0]-a['world'][0], b['world'][1]-a['world'][1]
        velocity_error = error/(duration-time_error)+distance*time_error/(duration*(duration-time_error))
        segments.append(dict(from_frame_id=track['observations'][i]['frame_id'], to_frame_id=track['observations'][i+1]['frame_id'],
            duration_seconds=duration, endpoint_displacement_metres=distance,
            endpoint_displacement_rate_metres_per_second=distance/duration,
            endpoint_displacement_rate_lower_metres_per_second=max(0, distance-error)/(duration+time_error),
            endpoint_displacement_rate_upper_metres_per_second=(distance+error)/(duration-time_error),
            mean_velocity_x_metres_per_second=dx/duration, mean_velocity_y_metres_per_second=dy/duration,
            mean_velocity_error_bound_metres_per_second=velocity_error))
    changes = []; turns = []
    for i, (a, b) in enumerate(zip(segments, segments[1:])):
        elapsed = (a['duration_seconds']+b['duration_seconds'])/2
        time_error = (points[i]['time_error']+points[i+2]['time_error'])/2
        delta_low = b['endpoint_displacement_rate_lower_metres_per_second']-a['endpoint_displacement_rate_upper_metres_per_second']
        delta_high = b['endpoint_displacement_rate_upper_metres_per_second']-a['endpoint_displacement_rate_lower_metres_per_second']
        limits = [delta/duration for delta in (delta_low, delta_high) for duration in (elapsed-time_error, elapsed+time_error)]
        dx = b['mean_velocity_x_metres_per_second']-a['mean_velocity_x_metres_per_second']
        dy = b['mean_velocity_y_metres_per_second']-a['mean_velocity_y_metres_per_second']
        magnitude = math.hypot(dx, dy)/elapsed
        vector_error = ((a['mean_velocity_error_bound_metres_per_second']+b['mean_velocity_error_bound_metres_per_second'])/(elapsed-time_error)
                        +math.hypot(dx, dy)*time_error/(elapsed*(elapsed-time_error)))
        changes.append(dict(at_frame_id=track['observations'][i+1]['frame_id'],
            displacement_rate_change_metres_per_second_squared=(b['endpoint_displacement_rate_metres_per_second']-a['endpoint_displacement_rate_metres_per_second'])/elapsed,
            displacement_rate_change_lower_metres_per_second_squared=min(limits),
            displacement_rate_change_upper_metres_per_second_squared=max(limits),
            vector_x_metres_per_second_squared=dx/elapsed, vector_y_metres_per_second_squared=dy/elapsed,
            magnitude_metres_per_second_squared=magnitude,
            magnitude_lower_metres_per_second_squared=max(0, magnitude-vector_error),
            magnitude_upper_metres_per_second_squared=magnitude+vector_error))
        if track['motion_phase'] == 'TURN':
            p, q, r = (points[i+j]['world'] for j in range(3))
            left = (q[0]-p[0], q[1]-p[1]); right = (r[0]-q[0], r[1]-q[1])
            cross = left[0]*right[1]-left[1]*right[0]
            separation = max(points[i+j]['position_error'] for j in range(3))*6
            chord = math.dist(p, r)
            good = min(a['endpoint_displacement_metres'], b['endpoint_displacement_metres'], chord) > separation and abs(cross) > separation*chord
            turns.append(dict(at_frame_id=track['observations'][i+1]['frame_id'],
                status='THREE_POINT_GEOMETRY_ONLY' if good else 'INSUFFICIENT_GEOMETRIC_SEPARATION',
                heading_change_degrees=math.degrees(math.atan2(cross, left[0]*right[0]+left[1]*right[1])) if good else None,
                circumradius_metres=a['endpoint_displacement_metres']*b['endpoint_displacement_metres']*chord/(2*abs(cross)) if good else None))
    result = dict(schema_version='conditional-world-motion/v1', race_id=track['race_id'],
        media_sha256=track['media_sha256'], program_identity_sha256=track['program_identity_sha256'],
        identity_evidence_sha256=track['identity_evidence_sha256'], hull_number=track['hull_number'], track_id=track['track_id'],
        input_sha256=hashlib.sha256(canonical(track)).hexdigest(), polyline_length_metres=sum(s['endpoint_displacement_metres'] for s in segments),
        segments=segments, finite_difference_velocity_changes=changes, turn_geometry=turns,
        metric_scope='CONDITIONAL_ON_SUPPLIED_WATER_CONTACT_WORLD_IDENTITY_AND_PHYSICAL_CLOCK_EVIDENCE',
        error_bounds_scope='SUPPLIED_TOTAL_WORLD_POSITION_AND_CLOCK_BOUNDS_NOT_DERIVED_FROM_LANDMARK_RESIDUALS',
        instantaneous_physical_speed='NOT_ESTIMATED', instantaneous_physical_acceleration='NOT_ESTIMATED',
        actual_travelled_path_length='NOT_ESTIMATED', between_frame_motion='UNVERIFIED',
        uncertainty_certification='NOT_ESTABLISHED_BY_THIS_CALCULATION',
        field_validation='NOT_ESTABLISHED_BY_THIS_CALCULATION', performance_rating='NOT_COMPUTED',
        automated_verified_hull_ids=0, prediction_eligible=False, boat_features=[])
    result['snapshot_id'] = hashlib.sha256(canonical(result)).hexdigest()
    return result
