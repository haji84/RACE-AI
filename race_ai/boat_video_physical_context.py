"""Conditional physical-coordinate contexts for the existing BOAT families.

Raw-frame calibration is replayed from the original immutable image report.
Per-boat exhibition windows can be sequential only within the same declared
survey frame and clock evidence. Neither the declarations, their hashes,
projected bounding-box centers, nor this adapter establish physical strength,
water contact, human-held-out validation or prediction eligibility.
"""
from copy import deepcopy
import math

from .actions_contract import digest
from .boat_video_calibration import measure_calibrated_tracks
from .boat_video_evaluation import _JST, _race_day, _report, _roster, _time, _tree
from .boat_video_measurements import measure_tracks
from .boat_video_model_context import FEATURE_IDS, FEATURE_SCHEMA, _CONTEXT_FIELDS, _CELL_FIELDS, _IDENTITY_FIELDS
from .boat_video_model_context import _sha, _LABEL


SCHEMA='RACE_AI_BOAT_VIDEO_PHYSICAL_MODEL_CONTEXT_V2'
EVIDENCE_SCHEMA='RACE_AI_BOAT_VIDEO_PHYSICAL_COMPARISON_EVIDENCE_V1'
PHYSICAL_FEATURE_SCHEMA=tuple((feature,phase,metric,unit.replace('px','m'))
                              for feature,phase,metric,unit in FEATURE_SCHEMA)
COMPARISON_SCOPE='SUPPLIED_WORLD_FRAME_PER_BOAT_WINDOWS_NOT_FIELD_CERTIFICATION'
_ERROR='BOAT_VIDEO_PHYSICAL_CONTEXT_REJECTED'
_EVIDENCE_FIELDS=set('schema_version report_sha256 media_sha256 race_id cutoff_at roster created_at '
    'identities comparisons heldout_evidence_sha256 evidence_sha256'.split())
_COMPARISON_FIELDS=set('comparison_id world_frame_id world_frame_source_sha256 calibration_evidence_sha256 '
    'clock_evidence_sha256 lanes'.split())
_LANE_FIELDS={'frame_indices','phase_evidence_sha256','uncertainty'}
_LANE_CONTEXT_FIELDS=_LANE_FIELDS|{'source_pts_seconds','t_start','t_end','scene','camera_scene','camera_evidence_sha256'}
_FIELDS=_CONTEXT_FIELDS|set('source_tracking_sha256 calibration_sha256 calibrated_envelope_sha256 world_frame_id '
    'world_frame_source_sha256 clock_evidence_sha256 point_scope identity_supported_lanes measurement_parameters'.split())
_GAPS=['SOURCE_PROVENANCE_AUTHENTICATION_NOT_ESTABLISHED','BOAT_GROUND_PLANE_CONTACT_UNVERIFIED',
       'SOURCE_POSITION_ERROR_HEURISTIC_UNCERTIFIED','CLOCK_CORRESPONDENCE_BETWEEN_REFERENCE_OBSERVATIONS_UNVERIFIED',
       'INDEPENDENT_HUMAN_HELDOUT_MEASUREMENT_VALIDATION_MISSING','PHASE_WINDOWS_NOT_INDEPENDENTLY_AUTHENTICATED']


def _need(condition):
    if not condition:raise ValueError(_ERROR)


def _nonnegative(value):
    return type(value) in (int,float) and math.isfinite(value) and value >= 0


def _seal(value):
    value['context_sha256']=digest(value)
    return value


def _identities(value,raw,roster):
    _need(type(value) is list and 0 <= len(value) <= 6)
    tracks={r['lane']:r for r in raw['tracking']['tracks']};result={}
    for row in value:
        _need(type(row) is dict and set(row)==_IDENTITY_FIELDS)
        lane=row['lane'];_need(type(lane) is int and lane in roster and lane not in result)
        _need(row['number']==lane and type(row['number']) is int and row['registration_number']==roster[lane])
        _need(row['method']=='INDEPENDENT_HULL_NUMBER_READ' and
            row['reviewer_kind'] in ('HUMAN_MANUAL','AGENT','AUTOMATED_DETECTOR') and
            type(row['reviewer_id']) is str and _LABEL.fullmatch(row['reviewer_id']) is not None)
        _need(row['track_sha256']==digest(tracks[lane]))
        observed={r['frame_index']:r for r in tracks[lane]['samples'] if r['valid']}
        frames=row['frames'];_need(type(frames) is list and 1 <= len(frames) <= 20000)
        previous=-1
        for frame in frames:
            _need(type(frame) is dict and set(frame)=={'frame_index','frame_sha256'})
            index=frame['frame_index'];_need(type(index) is int and index>previous and index in observed)
            _sha(frame['frame_sha256']);_need(frame['frame_sha256']==observed[index].get('frame_sha256'))
            previous=index
        result[lane]=row
    return result


def _evidence(value,raw,roster,calibrated):
    _need(type(value) is dict and set(value)==_EVIDENCE_FIELDS)
    _need(value['schema_version']==EVIDENCE_SCHEMA)
    _sha(value['evidence_sha256'])
    _need(value['evidence_sha256']==digest({k:v for k,v in value.items() if k!='evidence_sha256'}))
    _need(value['report_sha256']==raw['report_sha256'] and value['media_sha256']==raw['source']['media_sha256']
        and value['race_id']==raw['race_id'] and value['cutoff_at']==raw['cutoff_at'] and _roster(value['roster'])==roster)
    _time(value['created_at']);_sha(value['heldout_evidence_sha256'],optional=True)
    identities=_identities(value['identities'],raw,roster)
    comparisons=value['comparisons'];_need(type(comparisons) is dict and set(comparisons)<={r[1] for r in FEATURE_SCHEMA})
    for row in comparisons.values():
        _need(type(row) is dict and set(row)==_COMPARISON_FIELDS)
        _need(type(row['comparison_id']) is str and _LABEL.fullmatch(row['comparison_id']) is not None)
        _need(row['world_frame_id']==calibrated['world_frame_id'] and
            row['world_frame_source_sha256']==calibrated['world_frame_source_sha256'] and
            row['calibration_evidence_sha256']==calibrated['calibration_sha256'] and
            row['clock_evidence_sha256']==digest(calibrated['clock_evidence']))
        lanes=row['lanes'];_need(type(lanes) is dict and set(lanes)<=set(map(str,range(1,7))))
        for lane,part in lanes.items():
            _need(type(part) is dict and set(part)==_LANE_FIELDS and _nonnegative(part['uncertainty']))
            _sha(part['phase_evidence_sha256'])
            indices=part['frame_indices'];_need(type(indices) is list and 3<=len(indices)<=20000 and
                all(type(i) is int and i>=0 for i in indices) and indices==sorted(set(indices)))
    return deepcopy(value),identities


def _comparison_windows(evidence,calibrated):
    result=deepcopy(evidence['comparisons']) if evidence else {}
    tracks={r['lane']:r for r in calibrated['tracks']}
    frame_checks={r['frame_index']:r for r in calibrated['per_frame_validation']}
    for comparison in result.values():
        for lane,window in comparison['lanes'].items():
            window.update(source_pts_seconds=None,t_start=None,t_end=None,scene=None,camera_scene=None,
                          camera_evidence_sha256=None)
            indices=window['frame_indices'];rows=[r for r in tracks[int(lane)]['samples'] if r['frame_index'] in set(indices)]
            if ([r['frame_index'] for r in rows]!=indices or not all(r['valid'] for r in rows)
                or len({r['scene'] for r in rows})!=1 or len({r['camera_scene'] for r in rows})!=1):continue
            window.update(source_pts_seconds=[r['t'] for r in rows],t_start=rows[0]['t'],t_end=rows[-1]['t'],
                scene=rows[0]['scene'],camera_scene=rows[0]['camera_scene'],
                camera_evidence_sha256=digest([frame_checks[i] for i in indices]))
    return result


def _turn_uncertainty(measurement,rows):
    """Bound chord-radius geometry using only the supplied position disks.

    Segment endpoints can change orientation by asin((e_a+e_b)/length).
    Principal-angle branch ambiguity or a heading interval containing zero
    leaves radius unresolved; a declared zero must not override these errors.
    These conditional arithmetic bounds do not certify the input error disks.
    """
    lengths,headings,errors,angles=[],[],[],[]
    for first,second in zip(rows,rows[1:]):
        dx,dy=second['x']-first['x'],second['y']-first['y']
        length=math.hypot(dx,dy);error=first['position_error']+second['position_error']
        if length<=error:return None
        lengths.append(length);headings.append(math.atan2(dy,dx));errors.append(error)
        angles.append(math.asin(min(1.,error/length)))
    heading,heading_error=0.,0.
    for index,(first,second) in enumerate(zip(headings,headings[1:])):
        change=math.atan2(math.sin(second-first),math.cos(second-first))
        error=angles[index]+angles[index+1]
        if math.pi-abs(change)<=error+1e-12:return None
        heading+=change;heading_error+=error
    theta=abs(heading)
    if theta<=heading_error+1e-12:return None
    path,path_error=sum(lengths),sum(errors)
    lower=max(0.,path-path_error)/(theta+heading_error)
    upper=(path+path_error)/(theta-heading_error)
    radius=next(m['value'] for m in measurement['metrics'] if m['name']=='equivalent_sampled_radius')
    error=max(0.,radius-lower,upper-radius)
    return error if math.isfinite(error) else None


def _uncertainty(measurement,rows,declared,phase):
    result=declared;metrics={m['name']:m for m in measurement['metrics']}
    if phase=='turn':
        bound=_turn_uncertainty(measurement,rows)
        if bound is None:return None
        result=max(result,bound)
    if phase in ('exit','runup') and 'sampled_speed_trend_error_bound' in metrics:
        result=max(result,metrics['sampled_speed_trend_error_bound']['value'])
    if phase=='straight':
        result=max(result,sum(a['position_error']+b['position_error'] for a,b in zip(rows,rows[1:]))/
                   (rows[-1]['t']-rows[0]['t']))
    return result


def prepare_physical_video_context(report,identity_evidence,calibration_manifest,*,race_id,cutoff_at,roster,as_of,
                                   phase_windows=None,start_gate=None,max_gap_seconds=.3):
    """Recompute typed raw metre measurements; hashes never confer eligibility.

    Number references must overlap each lane's phase. Comparability is only a
    supplied shared world/clock declaration, with at least two observed lanes.
    An independent external receipt is still mandatory before learning/scoring.
    """
    try:
        raw=_report(report);target=_roster(roster);instant,cutoff=_time(as_of),_time(cutoff_at)
        _need(start_gate is None or type(start_gate) is dict and
              start_gate.get('coordinate_space')=='WATER_PLANE_METRES')
        _need(raw['race_id']==race_id and raw['cutoff_at']==cutoff_at and _roster(raw['roster'])==target)
        parameters=raw['analysis_parameters']
        original=measure_tracks(raw['tracking']['tracks'],coordinate_space='REFERENCE_IMAGE_PX',
            phase_windows=parameters.get('phase_windows'),start_gate=parameters.get('start_gate'),
            max_gap_seconds=parameters.get('max_gap_seconds',.3))
        _need(digest(original)==digest(raw['measurements']))
        _need(type(calibration_manifest) is dict and calibration_manifest.get('report_sha256')==raw['report_sha256']
              and calibration_manifest.get('dataset_status')==raw['dataset_status'])
        derived=measure_calibrated_tracks(raw['tracking'],calibration_manifest,phase_windows=phase_windows,
            start_gate=start_gate,max_gap_seconds=max_gap_seconds)
        calibrated=derived['calibrated_tracking'];measurements={r['lane']:r for r in derived['measurements']['lanes']}
        evidence,identities=(None,{}) if identity_evidence is None else _evidence(identity_evidence,raw,target,calibrated)
        common_reason=None
        if instant>=cutoff or not raw['pre_cutoff_available']:common_reason='POST_CUTOFF_ONLY'
        elif _time(raw['analysis_completed_at'])>instant:common_reason='ANALYSIS_NOT_AVAILABLE_AS_OF'
        elif raw['dataset_status']=='SYNTHETIC_ONLY':common_reason='SYNTHETIC_ONLY'
        elif evidence is None:common_reason='INDEPENDENT_NUMBER_EVIDENCE_MISSING'
        elif _time(evidence['created_at'])>instant:common_reason='EVIDENCE_NOT_AVAILABLE_AS_OF'
        elif _time(evidence['created_at'])<_time(raw['analysis_completed_at']):common_reason='EVIDENCE_PRECEDES_ANALYSIS'
        comparisons=_comparison_windows(evidence,calibrated)
        heldout=evidence['heldout_evidence_sha256'] if evidence else None
        out=dict(schema_version=SCHEMA,race_id=race_id,cutoff_at=cutoff_at,as_of=as_of,
            report_sha256=raw['report_sha256'],media_sha256=raw['source']['media_sha256'],
            evidence_sha256=evidence['evidence_sha256'] if evidence else None,
            source_captured_at=raw['source']['captured_at'],analysis_started_at=raw['analysis_started_at'],
            analysis_completed_at=raw['analysis_completed_at'],evidence_created_at=evidence['created_at'] if evidence else None,
            dataset_status=raw['dataset_status'],media_duration_seconds=raw['tracking']['duration_seconds'],
            raw_report_validation_status='UNVALIDATED',
            feature_schema=[dict(feature_id=f,phase=p,metric_name=m,unit=u) for f,p,m,u in PHYSICAL_FEATURE_SCHEMA],
            coordinate_space='WATER_PLANE_METRES',time_basis='MEDIA_TIMELINE_SECONDS',comparison_scope=COMPARISON_SCOPE,
            default_coefficients=dict.fromkeys(FEATURE_IDS,0.),learned_direction='UNTRAINED',
            normalization_status='DEFERRED_TO_EXISTING_VERSIONED_TRAINING',
            identity_reviewer_kinds=sorted({r['reviewer_kind'] for r in identities.values()}),
            identity_supported_lanes=sorted(identities),identity_evidence_authentication='NOT_ESTABLISHED',
            independent_human_heldout_verified=False,
            heldout_evidence_status='REFERENCE_SUPPLIED_NOT_AUTHENTICATED' if heldout else 'NOT_SUPPLIED',
            heldout_evidence_sha256=heldout,
            validation_gaps=sorted(_GAPS+['INDEPENDENT_HUMAN_HELDOUT_AUTHENTICATION_MISSING' if heldout else
                                        'INDEPENDENT_HUMAN_HELDOUT_VALIDATION_MISSING']),
            prediction_eligible=False,production_eligible=False,performance_rating='NOT_COMPUTED',
            comparisons=comparisons,participants=[],source_tracking_sha256=calibrated['source_tracking_sha256'],
            calibration_sha256=calibrated['calibration_sha256'],calibrated_envelope_sha256=calibrated['envelope_sha256'],
            world_frame_id=calibrated['world_frame_id'],world_frame_source_sha256=calibrated['world_frame_source_sha256'],
            clock_evidence_sha256=digest(calibrated['clock_evidence']),point_scope=calibrated['point_scope'],
            measurement_parameters=dict(phase_windows=deepcopy(phase_windows),start_gate=deepcopy(start_gate),
                                        max_gap_seconds=max_gap_seconds))
        tracks={r['lane']:r for r in calibrated['tracks']}
        participants={lane:dict(lane=lane,registration_number=target[lane],feature_cells={}) for lane in range(1,7)}
        for feature,phase,metric,unit in PHYSICAL_FEATURE_SCHEMA:
            cells=[];comparison=comparisons.get(phase)
            for lane,participant in participants.items():
                measurement=measurements[lane]['phases'][phase]
                window=comparison['lanes'].get(str(lane)) if comparison else None
                reason=common_reason
                if reason is None and lane not in identities:reason='INDEPENDENT_NUMBER_EVIDENCE_MISSING'
                if reason is None and window is None:reason='PAIRED_COMPARISON_EVIDENCE_MISSING'
                if reason is None and measurement['status']!='MEASURED':reason=measurement['reason']
                if reason is None and (window['source_pts_seconds'] is None or
                    (measurement['t_start'],measurement['t_end'])!=(window['t_start'],window['t_end'])):
                    reason='PER_BOAT_PHASE_WINDOW_MISMATCH'
                rows=[]
                if reason is None:
                    # The metric used every observed row in this interval.
                    # A subset with identical endpoints must not omit interior
                    # localization errors or borrow another continuity segment.
                    rows=[r for r in tracks[lane]['samples']
                          if measurement['t_start']-1e-12<=r['t']<=measurement['t_end']+1e-12]
                    if ([r['frame_index'] for r in rows]!=window['frame_indices'] or
                        [r['t'] for r in rows]!=window['source_pts_seconds'] or
                        len(rows)!=measurement['sample_count'] or
                        not all(r['valid'] and r['scene']==window['scene'] and
                                r['camera_scene']==window['camera_scene'] for r in rows)):
                        reason='PER_BOAT_PHASE_WINDOW_MISMATCH'
                if reason is None and not set(window['frame_indices']).intersection(r['frame_index'] for r in identities[lane]['frames']):
                    reason='PHASE_NUMBER_EVIDENCE_MISSING'
                cell=dict(feature_id=feature,phase=phase,metric_name=metric,unit=unit,value=None,uncertainty=None,
                    status='MISSING',missing_reason=reason,comparison_id=comparison['comparison_id'] if comparison else None,
                    scene=window['scene'] if window else None,t_start=measurement['t_start'],t_end=measurement['t_end'])
                participant['feature_cells'][feature]=cell;cells.append(cell)
                if reason:continue
                metrics={r['name']:r for r in measurement['metrics']};_need(metric in metrics and metrics[metric]['unit']==unit)
                uncertainty=_uncertainty(measurement,rows,window['uncertainty'],phase);value=metrics[metric]['value']
                if uncertainty is None:
                    cell['missing_reason']='TURN_HEADING_UNCERTAINTY_UNRESOLVED'
                    continue
                cell['uncertainty']=uncertainty
                if uncertainty>0 and uncertainty>=abs(value):cell['missing_reason']='MEASUREMENT_UNCERTAINTY_EXCEEDS_SIGNAL'
                else:cell.update(value=value,status='EXPERIMENTAL_COMPARABLE',missing_reason=None)
            if sum(c['value'] is not None for c in cells)==1:
                for cell in cells:
                    if cell['value'] is not None:cell.update(value=None,status='MISSING',missing_reason='INSUFFICIENT_COMPARABLE_PARTICIPANTS')
        out['participants']=list(participants.values())
        cells=[c for r in out['participants'] for c in r['feature_cells'].values()]
        out['eligible_for_research']=any(c['value'] is not None for c in cells)
        out['missing_reasons']=sorted({c['missing_reason'] for c in cells if c['missing_reason']})
        return validate_physical_video_context(_seal(out),race_id=race_id,cutoff_at=cutoff_at,roster=roster,as_of=as_of)
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError):raise ValueError(_ERROR) from None


def validate_physical_video_context(context,*,race_id,cutoff_at,roster,as_of):
    """Strict sealed structure only; rebuild from source for independent replay."""
    try:
        _need(type(context) is dict and set(context)==_FIELDS);value=deepcopy(context);_tree(value)
        _sha(value['context_sha256']);_need(value['context_sha256']==digest({k:v for k,v in value.items() if k!='context_sha256'}))
        _need(value['schema_version']==SCHEMA and value['race_id']==race_id and value['cutoff_at']==cutoff_at and value['as_of']==as_of)
        target=_roster(roster);instant,cutoff=_time(as_of),_time(cutoff_at);day=_race_day(race_id)
        _need(cutoff.astimezone(_JST).date()==day)
        captured,started,completed=(_time(value[k]) for k in ('source_captured_at','analysis_started_at','analysis_completed_at'))
        _need(captured<=started<=completed and captured.astimezone(_JST).date()>=day)
        evidence_at=_time(value['evidence_created_at']) if value['evidence_created_at'] else None
        for key in ('report_sha256','media_sha256','source_tracking_sha256','calibration_sha256',
                    'calibrated_envelope_sha256','world_frame_source_sha256','clock_evidence_sha256'):_sha(value[key])
        for key in ('evidence_sha256','heldout_evidence_sha256'):_sha(value[key],optional=True)
        _need(type(value['world_frame_id']) is str and _LABEL.fullmatch(value['world_frame_id']) is not None)
        _need(value['raw_report_validation_status']=='UNVALIDATED' and value['identity_evidence_authentication']=='NOT_ESTABLISHED'
              and value['point_scope']=='SUPPLIED_TRACK_POINT_NOT_VERIFIED_WATER_CONTACT')
        _need(all(value[k] is False for k in ('prediction_eligible','production_eligible','independent_human_heldout_verified')))
        _need(value['performance_rating']=='NOT_COMPUTED' and value['learned_direction']=='UNTRAINED'
              and value['coordinate_space']=='WATER_PLANE_METRES' and value['time_basis']=='MEDIA_TIMELINE_SECONDS'
              and value['comparison_scope']==COMPARISON_SCOPE and value['normalization_status']=='DEFERRED_TO_EXISTING_VERSIONED_TRAINING')
        _need(value['feature_schema']==[dict(feature_id=f,phase=p,metric_name=m,unit=u) for f,p,m,u in PHYSICAL_FEATURE_SCHEMA])
        coefficients=value['default_coefficients'];_need(type(coefficients) is dict and set(coefficients)==set(FEATURE_IDS)
            and all(type(v) in (int,float) and v==0 for v in coefficients.values()))
        heldout=value['heldout_evidence_sha256'] is not None
        _need(value['heldout_evidence_status']==('REFERENCE_SUPPLIED_NOT_AUTHENTICATED' if heldout else 'NOT_SUPPLIED'))
        _need(value['validation_gaps']==sorted(_GAPS+['INDEPENDENT_HUMAN_HELDOUT_AUTHENTICATION_MISSING' if heldout else
                                                    'INDEPENDENT_HUMAN_HELDOUT_VALIDATION_MISSING']))
        kinds=value['identity_reviewer_kinds'];_need(type(kinds) is list and kinds==sorted(set(kinds))
            and all(k in ('HUMAN_MANUAL','AGENT','AUTOMATED_DETECTOR') for k in kinds))
        identities=value['identity_supported_lanes'];_need(type(identities) is list and identities==sorted(set(identities))
            and all(type(n) is int and 1<=n<=6 for n in identities) and bool(identities)==bool(kinds))
        _need(value['dataset_status'] in ('REAL_REPORTED','SYNTHETIC_ONLY'))
        duration=value['media_duration_seconds'];_need(_nonnegative(duration))
        parameters=value['measurement_parameters'];_need(type(parameters) is dict and
            set(parameters)=={'phase_windows','start_gate','max_gap_seconds'})
        from .boat_video_measurements import _windows,_gate
        _need(parameters['start_gate'] is None or type(parameters['start_gate']) is dict and
              parameters['start_gate'].get('coordinate_space')=='WATER_PLANE_METRES')
        _windows(parameters['phase_windows'],range(1,7));_gate(parameters['start_gate'],'WATER_PLANE_METRES')
        _need(_nonnegative(parameters['max_gap_seconds']) and parameters['max_gap_seconds']>0)
        comparisons=value['comparisons'];_need(type(comparisons) is dict and set(comparisons)<={r[1] for r in FEATURE_SCHEMA})
        for comparison in comparisons.values():
            _need(type(comparison) is dict and set(comparison)==_COMPARISON_FIELDS)
            _need(type(comparison['comparison_id']) is str and _LABEL.fullmatch(comparison['comparison_id']) is not None)
            for key in ('world_frame_id','world_frame_source_sha256'):_need(comparison[key]==value[key])
            _need(comparison['calibration_evidence_sha256']==value['calibration_sha256']
                  and comparison['clock_evidence_sha256']==value['clock_evidence_sha256'])
            _need(type(comparison['lanes']) is dict and set(comparison['lanes'])<=set(map(str,range(1,7))))
            for window in comparison['lanes'].values():
                _need(type(window) is dict and set(window)==_LANE_CONTEXT_FIELDS and _nonnegative(window['uncertainty']))
                _sha(window['phase_evidence_sha256']);_sha(window['camera_evidence_sha256'],optional=True)
                indices=window['frame_indices'];_need(type(indices) is list and 3<=len(indices)<=20000 and
                    all(type(i) is int and i>=0 for i in indices) and indices==sorted(set(indices)))
                points=window['source_pts_seconds']
                if points is None:_need(all(window[k] is None for k in ('t_start','t_end','scene','camera_scene','camera_evidence_sha256')))
                else:
                    _need(type(points) is list and len(points)==len(indices) and
                        all(_nonnegative(t) and t<=duration for t in points) and all(a<b for a,b in zip(points,points[1:]))
                        and window['t_start']==points[0] and window['t_end']==points[-1] and window['camera_evidence_sha256'] is not None)
                    _need(all(type(window[k]) is int and window[k]>=0 for k in ('scene','camera_scene')))
        participants=value['participants'];_need(type(participants) is list and len(participants)==6)
        found,reasons,counts={},set(),dict.fromkeys(FEATURE_IDS,0)
        for participant in participants:
            _need(type(participant) is dict and set(participant)=={'lane','registration_number','feature_cells'})
            lane=participant['lane'];_need(type(lane) is int and lane in target and lane not in found
                and participant['registration_number']==target[lane]);found[lane]=target[lane]
            cells=participant['feature_cells'];_need(type(cells) is dict and set(cells)==set(FEATURE_IDS))
            for feature,phase,metric,unit in PHYSICAL_FEATURE_SCHEMA:
                cell=cells[feature];_need(type(cell) is dict and set(cell)==_CELL_FIELDS and cell['feature_id']==feature
                    and cell['phase']==phase and cell['metric_name']==metric and cell['unit']==unit)
                comparison=comparisons.get(phase);window=comparison['lanes'].get(str(lane)) if comparison else None
                _need(cell['comparison_id']==(comparison['comparison_id'] if comparison else None)
                      and cell['scene']==(window['scene'] if window else None))
                _need(cell['uncertainty'] is None or _nonnegative(cell['uncertainty']))
                _need(all(cell[k] is None or _nonnegative(cell[k]) and cell[k]<=duration for k in ('t_start','t_end')))
                if cell['value'] is None:
                    _need(cell['status']=='MISSING' and type(cell['missing_reason']) is str
                          and _LABEL.fullmatch(cell['missing_reason']) is not None);reasons.add(cell['missing_reason']);continue
                _need(type(cell['value']) in (int,float) and math.isfinite(cell['value']) and
                    cell['status']=='EXPERIMENTAL_COMPARABLE' and cell['missing_reason'] is None
                    and lane in identities and window is not None and window['source_pts_seconds'] is not None
                    and (cell['t_start'],cell['t_end'])==(window['t_start'],window['t_end'])
                    and cell['uncertainty'] is not None and cell['uncertainty']>=window['uncertainty']
                    and (cell['uncertainty']==0 or cell['uncertainty']<abs(cell['value'])))
                _need(phase not in ('turn','straight') or cell['value']>=0);counts[feature]+=1
        _need(found==target and all(n!=1 for n in counts.values()))
        eligible=any(counts.values());_need(type(value['eligible_for_research']) is bool and value['eligible_for_research']==eligible
                                          and value['missing_reasons']==sorted(reasons))
        if eligible:_need(value['dataset_status']=='REAL_REPORTED' and value['evidence_sha256'] is not None
                          and evidence_at is not None and completed<=evidence_at<=instant<cutoff)
        return value
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError):raise ValueError(_ERROR) from None
