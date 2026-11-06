"""Sequential passages in one reference image, never physical strength ratings.

The sealed evidence binds supplied number reads and observed image coordinates.
Camera/PTS declarations and hashes are not independent field certification.
No source is fetched, no position is interpolated, and originals stay unchanged.
"""
from copy import deepcopy
from fractions import Fraction
import math

from .actions_contract import digest
from .boat_video_calibration import _camera_frames, _hull, _inside
from .boat_video_evaluation import _JST, _race_day, _report, _roster, _time, _tree
from .boat_video_measurements import IDENTITIES, _crossings, _gate, measure_tracks
from .boat_video_model_context import FEATURE_IDS, FEATURE_SCHEMA, _CONTEXT_FIELDS, _sha, _LABEL
from .boat_video_physical_context import _identities, _uncertainty


SCHEMA = 'RACE_AI_BOAT_VIDEO_SEQUENTIAL_MODEL_CONTEXT_V1'
EVIDENCE_SCHEMA = 'RACE_AI_BOAT_VIDEO_SEQUENTIAL_COMPARISON_EVIDENCE_V1'
_ERROR = 'BOAT_VIDEO_SEQUENTIAL_CONTEXT_REJECTED'
_SCOPE = 'SUPPLIED_SHARED_IMAGE_PASSAGE_NOT_FIELD_CERTIFICATION'
_POINT_SCOPE = 'SUPPLIED_TRACK_POINT_REFERENCE_IMAGE_PROXY_NOT_WATER_CONTACT'
_EVIDENCE = set('schema_version report_sha256 source_tracking_sha256 media_sha256 race_id cutoff_at roster '
                'created_at identities comparisons heldout_evidence_sha256 evidence_sha256'.split())
_COMPARISON = set('comparison_id reference_frame_sha256 camera_scene camera_evidence_sha256 '
                  'corridor entry_gate exit_gate lanes'.split())
_LANE = {'frame_indices', 'uncertainty'}
_PROOF = _LANE | {'samples', 'number_frame_indices', 'camera_bindings', 'identity_status'}
_SAMPLE = set('frame_index t x y scene camera_scene valid position_error frame_sha256'.split())
_CAMERA = set('camera_scene source_pts_seconds decoded_frame_sha256 reference_frame_sha256 '
              'raw_to_reference camera_status'.split())
_FIELDS = _CONTEXT_FIELDS | {'source_tracking_sha256', 'camera_evidence_sha256', 'reference_image_size',
                            'max_gap_seconds', 'identity_supported_lanes', 'point_scope'}
_GAPS = ['CAMERA_REFERENCE_NOT_INDEPENDENTLY_VALIDATED', 'IMAGE_MOTION_PROXY_NOT_PHYSICAL_STRENGTH',
         'MEDIA_TIMELINE_NOT_PHYSICAL_CLOCK_CERTIFICATION', 'PASSAGE_PHASE_NOT_INDEPENDENTLY_VALIDATED']


def _need(condition):
    if not condition:
        raise ValueError(_ERROR)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _indices(value, *, minimum=3):
    _need(type(value) is list and minimum <= len(value) <= 20000 and
          all(type(i) is int and i >= 0 for i in value) and value == sorted(set(value)))


def _passage(comparison, size, *, proof=False):
    _need(type(comparison) is dict and set(comparison) == _COMPARISON)
    _need(type(comparison['comparison_id']) is str and _LABEL.fullmatch(comparison['comparison_id']))
    for name in ('reference_frame_sha256', 'camera_evidence_sha256'):
        _sha(comparison[name])
    _need(type(comparison['camera_scene']) is int and comparison['camera_scene'] >= 0)
    polygon = comparison['corridor']
    _need(type(polygon) is list and 3 <= len(polygon) <= 16)
    points = []
    for point in polygon:
        _need(type(point) is list and len(point) == 2 and all(_finite(v) for v in point) and
              0 <= point[0] <= size[0]-1 and 0 <= point[1] <= size[1]-1)
        points.append(tuple(point))
    hull = _hull(points)
    _need(len(hull) == len(points) and len(set(points)) == len(points) and len(hull) >= 3)
    for key in ('entry_gate', 'exit_gate'):
        gate = comparison[key]
        _need(type(gate) is dict and set(gate) == {'a', 'b', 'normal'})
        _gate(gate, 'REFERENCE_IMAGE_PX')
    lanes = comparison['lanes']
    _need(type(lanes) is dict and set(lanes) <= set(map(str, range(1, 7))))
    for part in lanes.values():
        _need(type(part) is dict and set(part) == (_PROOF if proof else _LANE))
        _indices(part['frame_indices'])
        _need(_finite(part['uncertainty']) and part['uncertainty'] >= 0)
    return hull


def _evidence(value, raw, roster):
    _need(type(value) is dict and set(value) == _EVIDENCE and value['schema_version'] == EVIDENCE_SCHEMA)
    _tree(value)
    _sha(value['evidence_sha256'])
    _need(value['evidence_sha256'] == digest({k:v for k,v in value.items() if k != 'evidence_sha256'}))
    _need(value['report_sha256'] == raw['report_sha256'] and value['media_sha256'] == raw['source']['media_sha256'] and
          value['source_tracking_sha256'] == digest(raw['tracking']) and value['race_id'] == raw['race_id'] and
          value['cutoff_at'] == raw['cutoff_at'] and _roster(value['roster']) == roster)
    _time(value['created_at']); _sha(value['heldout_evidence_sha256'], optional=True)
    identities = _identities(value['identities'], raw, roster)
    _need(type(value['comparisons']) is dict and set(value['comparisons']) <= {row[1] for row in FEATURE_SCHEMA})
    size = [raw['tracking']['width'], raw['tracking']['height']]
    for comparison in value['comparisons'].values():
        _passage(comparison, size)
    return deepcopy(value), identities


def _proof(part, track, cameras, identity):
    indices = part['frame_indices']
    # Include every source observation inside the declared window. A caller
    # cannot omit an invalid interior sample to manufacture continuity.
    rows = [r for r in track['samples'] if indices[0] <= r['frame_index'] <= indices[-1]]
    samples = [{k:deepcopy(row.get(k)) for k in _SAMPLE} for row in rows]
    frames = [] if identity is None else [r['frame_index'] for r in identity['frames']
                                         if r['frame_index'] in indices]
    return dict(frame_indices=deepcopy(indices), uncertainty=part['uncertainty'], samples=samples,
        camera_bindings=[deepcopy(cameras.get(r['frame_index'])) for r in rows],
        number_frame_indices=frames, identity_status=track.get('identity_status', 'UNRESOLVED'))


def _window(part, comparison, camera_hash, size, duration):
    _need(type(part) is dict and set(part) == _PROOF)
    _indices(part['frame_indices']); _indices(part['number_frame_indices'], minimum=0)
    _need(set(part['number_frame_indices']) <= set(part['frame_indices']))
    _need(type(part['identity_status']) is str)
    rows, bindings = part['samples'], part['camera_bindings']
    _need(type(rows) is list and len(rows) <= 20000 and type(bindings) is list and len(bindings) == len(rows))
    previous_index = previous_t = -1
    for row, binding in zip(rows, bindings):
        _need(type(row) is dict and set(row) == _SAMPLE and type(row['frame_index']) is int and
              row['frame_index'] > previous_index and _finite(row['t']) and previous_t < row['t'] <= duration and
              type(row['scene']) is int and row['scene'] >= 0 and type(row['valid']) is bool)
        _need(row['camera_scene'] is None or type(row['camera_scene']) is int and row['camera_scene'] >= 0)
        _sha(row['frame_sha256'], optional=True)
        if row['valid']:
            _need(all(_finite(row[k]) for k in ('x', 'y')))
        _need(row['position_error'] is None or _finite(row['position_error']) and row['position_error'] >= 0)
        if binding is not None:
            _need(type(binding) is dict and set(binding) == _CAMERA)
            for key in ('decoded_frame_sha256', 'reference_frame_sha256'): _sha(binding[key])
            _need(type(binding['camera_scene']) is int and binding['camera_scene'] >= 0 and
                  _finite(binding['source_pts_seconds']) and type(binding['camera_status']) is str)
            matrix = binding['raw_to_reference']
            _need(type(matrix) is list and len(matrix) == 3 and all(type(r) is list and len(r) == 3 and
                  all(_finite(v) for v in r) for r in matrix))
            # Data-only readers do not need the optional video runtime.
            # Exact arithmetic prevents cancellation from making a singular
            # matrix look invertible. Keep the same normalized camera contract;
            # passing it does not authenticate the matrix or its accuracy.
            _need(abs(matrix[2][2]-1.) <= 1e-12)
            a,b,c,d,e,f,g,h,i = (Fraction(v) for row in matrix for v in row)
            determinant = a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
            _need(_finite(float(determinant)) and abs(determinant) > Fraction(1e-8))
        previous_index, previous_t = row['frame_index'], row['t']
    if [r['frame_index'] for r in rows] != part['frame_indices']:
        return 'EXACT_PHASE_FRAME_WINDOW_MISMATCH'
    if not all(r['valid'] for r in rows): return 'OCCLUDED_OR_INVALID_SAMPLE'
    if len({r['scene'] for r in rows}) != 1: return 'IDENTITY_SCENE_CHANGE'
    if comparison['camera_evidence_sha256'] != camera_hash: return 'CAMERA_EVIDENCE_MISMATCH'
    for row, binding in zip(rows, bindings):
        if binding is None or binding['camera_status'] != 'ACCEPTED': return 'CAMERA_COMPENSATION_UNVERIFIED'
        if (binding['camera_scene'] != comparison['camera_scene'] or row['camera_scene'] != comparison['camera_scene'] or
                binding['reference_frame_sha256'] != comparison['reference_frame_sha256']):
            return 'CAMERA_REFERENCE_MISMATCH'
        if binding['decoded_frame_sha256'] != row['frame_sha256'] or binding['source_pts_seconds'] != row['t']:
            return 'SAMPLE_FRAME_BINDING_MISMATCH'
    if any(r['position_error'] is None for r in rows): return 'POSITION_ERROR_MISSING'
    hull = _passage(comparison, size, proof=True)
    if any(not _inside((r['x'],r['y']), hull) for r in rows): return 'OUTSIDE_SHARED_PASSAGE_CORRIDOR'
    if not part['number_frame_indices']: return 'PHASE_NUMBER_EVIDENCE_MISSING'
    crossings = [_crossings([rows], _gate(comparison[k], 'REFERENCE_IMAGE_PX')) for k in ('entry_gate','exit_gate')]
    if any(not values for values in crossings): return 'PASSAGE_CROSSING_NOT_OBSERVED'
    if any(len(values) != 1 for values in crossings): return 'AMBIGUOUS_PASSAGE_CROSSING'
    entry, exit_ = [values[0] for values in crossings]
    if entry[0] >= exit_[0]: return 'PASSAGE_GATE_ORDER_MISMATCH'
    if entry[2] != tuple(part['frame_indices'][:2]) or exit_[2] != tuple(part['frame_indices'][-2:]):
        return 'PASSAGE_BOUNDARY_FRAMES_MISMATCH'
    return None


def _common(value, cutoff, instant):
    if instant >= cutoff or _time(value['analysis_completed_at']) >= cutoff: return 'POST_CUTOFF_ONLY'
    if _time(value['analysis_completed_at']) > instant: return 'ANALYSIS_NOT_AVAILABLE_AS_OF'
    if value['dataset_status'] == 'SYNTHETIC_ONLY': return 'SYNTHETIC_ONLY'
    if value['evidence_sha256'] is None: return 'INDEPENDENT_NUMBER_EVIDENCE_MISSING'
    if _time(value['evidence_created_at']) > instant: return 'EVIDENCE_NOT_AVAILABLE_AS_OF'
    if _time(value['evidence_created_at']) < _time(value['analysis_completed_at']): return 'EVIDENCE_PRECEDES_ANALYSIS'
    return None


def _participants(value, target):
    participants = {lane:dict(lane=lane, registration_number=target[lane], feature_cells={}) for lane in range(1,7)}
    common = _common(value, _time(value['cutoff_at']), _time(value['as_of']))
    for feature, phase, metric, unit in FEATURE_SCHEMA:
        comparison = value['comparisons'].get(phase); cells = []
        for lane, participant in participants.items():
            part = comparison['lanes'].get(str(lane)) if comparison else None
            rows = part['samples'] if part else []
            reason = common
            if reason is None and lane not in value['identity_supported_lanes']: reason = 'INDEPENDENT_NUMBER_EVIDENCE_MISSING'
            if reason is None and part is None: reason = 'PAIRED_COMPARISON_EVIDENCE_MISSING'
            if reason is None:
                reason = _window(part, comparison, value['camera_evidence_sha256'],
                                 value['reference_image_size'], value['media_duration_seconds'])
            cell = dict(feature_id=feature, phase=phase, metric_name=metric, unit=unit, value=None,
                uncertainty=None, status='MISSING', missing_reason=reason,
                comparison_id=comparison['comparison_id'] if comparison else None,
                scene=rows[0]['scene'] if rows else None, t_start=rows[0]['t'] if rows else None,
                t_end=rows[-1]['t'] if rows else None)
            participant['feature_cells'][feature] = cell; cells.append(cell)
            if reason: continue
            selected = rows
            if phase == 'runup':
                # The final observed bracket proves the crossing, but its
                # post-crossing endpoint must not enter a pre-start trend.
                crossing = _crossings([rows], _gate(comparison['exit_gate'], 'REFERENCE_IMAGE_PX'))[0][0]
                selected = [row for row in rows if row['t'] <= crossing+1e-12]
            cell.update(t_start=selected[0]['t'], t_end=selected[-1]['t'])
            if not set(part['number_frame_indices']).intersection(row['frame_index'] for row in selected):
                cell['missing_reason'] = 'PHASE_NUMBER_EVIDENCE_MISSING'
                continue
            if len(selected) < 3:
                cell['missing_reason'] = 'INSUFFICIENT_SAMPLES'
                continue
            track = dict(lane=lane, identity_status=part['identity_status'], samples=rows)
            measured = measure_tracks([track], coordinate_space='REFERENCE_IMAGE_PX',
                phase_windows={str(lane):{phase:[selected[0]['t'],selected[-1]['t']]}},
                start_gate=comparison['exit_gate'] if phase == 'runup' else None,
                max_gap_seconds=value['max_gap_seconds'])['lanes'][0]['phases'][phase]
            if measured['status'] != 'MEASURED': cell['missing_reason'] = measured['reason']; continue
            uncertainty = _uncertainty(measured, selected, part['uncertainty'], phase)
            if uncertainty is None: cell['missing_reason'] = 'TURN_HEADING_UNCERTAINTY_UNRESOLVED'; continue
            number = next(m['value'] for m in measured['metrics'] if m['name'] == metric and m['unit'] == unit)
            cell['uncertainty'] = uncertainty
            if uncertainty > 0 and uncertainty >= abs(number): cell['missing_reason'] = 'MEASUREMENT_UNCERTAINTY_EXCEEDS_SIGNAL'
            else: cell.update(value=number, status='EXPERIMENTAL_COMPARABLE', missing_reason=None)
        if sum(c['value'] is not None for c in cells) == 1:
            for cell in cells:
                if cell['value'] is not None:
                    cell.update(value=None, status='MISSING', missing_reason='INSUFFICIENT_COMPARABLE_PARTICIPANTS')
    return list(participants.values())


def prepare_sequential_video_context(report, evidence, *, race_id, cutoff_at, roster, as_of):
    """Measure source-bound sequential passages in the same reference image.

    Observed boundary brackets can extend beyond the gates. Their raw sampled
    rates/radius are image proxies, not exact gate-to-gate travel measurements.
    Runup uses only observed pre-crossing samples and retains the real bracket.
    """
    try:
        raw = _report(report); target = _roster(roster); _time(as_of); _time(cutoff_at)
        _need(raw['race_id'] == race_id and raw['cutoff_at'] == cutoff_at and _roster(raw['roster']) == target)
        parameters = raw['analysis_parameters']; tracking = raw['tracking']
        original = measure_tracks(tracking['tracks'], coordinate_space='REFERENCE_IMAGE_PX',
            phase_windows=parameters.get('phase_windows'), start_gate=parameters.get('start_gate'),
            max_gap_seconds=parameters.get('max_gap_seconds', .3))
        _need(digest(original) == digest(raw['measurements']))
        checked, identities = (None,{}) if evidence is None else _evidence(evidence, raw, target)
        cameras = _camera_frames(tracking) if checked is not None else {}
        comparisons = deepcopy(checked['comparisons']) if checked is not None else {}
        tracks = {r['lane']:r for r in tracking['tracks']}
        for comparison in comparisons.values():
            comparison['lanes'] = {lane:_proof(part, tracks[int(lane)], cameras, identities.get(int(lane)))
                                   for lane,part in comparison['lanes'].items()}
        heldout = checked['heldout_evidence_sha256'] if checked else None
        out = dict(schema_version=SCHEMA, race_id=race_id, cutoff_at=cutoff_at, as_of=as_of,
            report_sha256=raw['report_sha256'], media_sha256=raw['source']['media_sha256'],
            evidence_sha256=checked['evidence_sha256'] if checked else None,
            source_captured_at=raw['source']['captured_at'], analysis_started_at=raw['analysis_started_at'],
            analysis_completed_at=raw['analysis_completed_at'], evidence_created_at=checked['created_at'] if checked else None,
            dataset_status=raw['dataset_status'], media_duration_seconds=tracking['duration_seconds'],
            raw_report_validation_status='UNVALIDATED',
            feature_schema=[dict(feature_id=f,phase=p,metric_name=m,unit=u) for f,p,m,u in FEATURE_SCHEMA],
            coordinate_space='REFERENCE_IMAGE_PX', time_basis='MEDIA_TIMELINE_SECONDS', comparison_scope=_SCOPE,
            default_coefficients=dict.fromkeys(FEATURE_IDS,0.), learned_direction='UNTRAINED',
            normalization_status='DEFERRED_TO_EXISTING_VERSIONED_TRAINING',
            identity_reviewer_kinds=sorted({r['reviewer_kind'] for r in identities.values()}),
            identity_evidence_authentication='NOT_ESTABLISHED', independent_human_heldout_verified=False,
            heldout_evidence_status='REFERENCE_SUPPLIED_NOT_AUTHENTICATED' if heldout else 'NOT_SUPPLIED',
            heldout_evidence_sha256=heldout, validation_gaps=sorted(_GAPS+[
                'INDEPENDENT_HUMAN_HELDOUT_AUTHENTICATION_MISSING' if heldout else 'INDEPENDENT_HUMAN_HELDOUT_VALIDATION_MISSING']),
            prediction_eligible=False, production_eligible=False, performance_rating='NOT_COMPUTED',
            comparisons=comparisons, source_tracking_sha256=digest(tracking), camera_evidence_sha256=digest(tracking['quality']),
            reference_image_size=[tracking['width'],tracking['height']], max_gap_seconds=parameters.get('max_gap_seconds',.3),
            identity_supported_lanes=sorted(identities), point_scope=_POINT_SCOPE)
        out['participants'] = _participants(out,target)
        cells = [c for row in out['participants'] for c in row['feature_cells'].values()]
        out['eligible_for_research'] = any(c['value'] is not None for c in cells)
        out['missing_reasons'] = sorted({c['missing_reason'] for c in cells if c['missing_reason']})
        out['context_sha256'] = digest(out)
        return validate_sequential_video_context(out, race_id=race_id, cutoff_at=cutoff_at, roster=roster, as_of=as_of)
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError,StopIteration):
        raise ValueError(_ERROR) from None


def validate_sequential_video_context(context, *, race_id, cutoff_at, roster, as_of):
    """Replay retained image measurements; hashes still require external receipts."""
    try:
        _need(type(context) is dict and set(context) == _FIELDS); value = deepcopy(context); _tree(value)
        _sha(value['context_sha256']); _need(value['context_sha256'] == digest({k:v for k,v in value.items() if k!='context_sha256'}))
        _need(value['schema_version'] == SCHEMA and value['race_id'] == race_id and value['cutoff_at'] == cutoff_at and value['as_of'] == as_of)
        target = _roster(roster); instant, cutoff = _time(as_of),_time(cutoff_at)
        _need(cutoff.astimezone(_JST).date() == _race_day(race_id))
        captured,started,completed = [_time(value[k]) for k in ('source_captured_at','analysis_started_at','analysis_completed_at')]
        _need(captured <= started <= completed and captured.astimezone(_JST).date() >= _race_day(race_id))
        for key in ('report_sha256','media_sha256','source_tracking_sha256','camera_evidence_sha256'): _sha(value[key])
        for key in ('evidence_sha256','heldout_evidence_sha256'): _sha(value[key],optional=True)
        _need(value['raw_report_validation_status'] == 'UNVALIDATED' and value['point_scope'] == _POINT_SCOPE and
              value['identity_evidence_authentication'] == 'NOT_ESTABLISHED' and
              all(value[k] is False for k in ('prediction_eligible','production_eligible','independent_human_heldout_verified')))
        _need(value['performance_rating'] == 'NOT_COMPUTED' and value['learned_direction'] == 'UNTRAINED' and
              value['coordinate_space'] == 'REFERENCE_IMAGE_PX' and value['time_basis'] == 'MEDIA_TIMELINE_SECONDS' and
              value['comparison_scope'] == _SCOPE and value['normalization_status'] == 'DEFERRED_TO_EXISTING_VERSIONED_TRAINING')
        _need(value['feature_schema'] == [dict(feature_id=f,phase=p,metric_name=m,unit=u) for f,p,m,u in FEATURE_SCHEMA])
        weights = value['default_coefficients']; _need(type(weights) is dict and set(weights) == set(FEATURE_IDS) and
            all(type(v) in (int,float) and v == 0 for v in weights.values()))
        heldout = value['heldout_evidence_sha256'] is not None
        _need(value['heldout_evidence_status'] == ('REFERENCE_SUPPLIED_NOT_AUTHENTICATED' if heldout else 'NOT_SUPPLIED') and
            value['validation_gaps'] == sorted(_GAPS+['INDEPENDENT_HUMAN_HELDOUT_AUTHENTICATION_MISSING' if heldout else
                                                    'INDEPENDENT_HUMAN_HELDOUT_VALIDATION_MISSING']))
        kinds, lanes = value['identity_reviewer_kinds'],value['identity_supported_lanes']
        _need(type(kinds) is list and kinds == sorted(set(kinds)) and all(k in ('HUMAN_MANUAL','AGENT','AUTOMATED_DETECTOR') for k in kinds))
        _need(type(lanes) is list and lanes == sorted(set(lanes)) and all(type(n) is int and 1<=n<=6 for n in lanes) and bool(lanes)==bool(kinds))
        _need((value['evidence_created_at'] is None) == (value['evidence_sha256'] is None))
        if value['evidence_created_at'] is not None: _time(value['evidence_created_at'])
        _need(value['dataset_status'] in ('REAL_REPORTED','SYNTHETIC_ONLY') and _finite(value['media_duration_seconds']) and
              value['media_duration_seconds'] >= 0 and _finite(value['max_gap_seconds']) and value['max_gap_seconds'] > 0)
        size = value['reference_image_size']; _need(type(size) is list and len(size) == 2 and
              all(type(n) is int and 0<n<=16384 for n in size))
        comparisons = value['comparisons']; _need(type(comparisons) is dict and set(comparisons) <= {r[1] for r in FEATURE_SCHEMA})
        for comparison in comparisons.values():
            _passage(comparison,size,proof=True)
            for part in comparison['lanes'].values():
                _window(part,comparison,value['camera_evidence_sha256'],size,value['media_duration_seconds'])
        expected = _participants(value,target)
        _need(digest(expected) == digest(value['participants']))
        cells = [c for row in expected for c in row['feature_cells'].values()]
        eligible = any(c['value'] is not None for c in cells)
        _need(type(value['eligible_for_research']) is bool and value['eligible_for_research'] == eligible and
              value['missing_reasons'] == sorted({c['missing_reason'] for c in cells if c['missing_reason']}))
        return value
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError,StopIteration):
        raise ValueError(_ERROR) from None
