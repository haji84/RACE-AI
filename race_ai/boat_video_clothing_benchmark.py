"""Offline clothing-identity agreement on explicitly referenced rider parts.

Rider boxes never become hull tracks or physical positions. Original journal
rows and references are separately bound; source, annotation and split claims
remain declarations. No strength, calibration or prediction eligibility follows.
"""
from collections import Counter
from copy import deepcopy

from .actions_contract import digest
from .boat_video_benchmark import (_LABEL, _box, _finite, _finish, _matches,
    _metrics, _score_frame, _sha, validate_reference)


REFERENCE_SCHEMA = 'RACE_AI_RIDER_PART_REFERENCE_V1'
SCHEMA = 'RACE_AI_CLOTHING_IDENTITY_BENCHMARK_V1'
_ERROR = 'BOAT_CLOTHING_BENCHMARK_REJECTED'
_CURRENT = 'CURRENT_CLOTHING_COLOR'
_CARRIED = 'CURRENT_PIXEL_TRACK_PRIOR_CLOTHING_COLOR'


def _need(condition):
    if not condition:
        raise ValueError(_ERROR)


def _reference(value):
    _need(type(value) is dict and value.get('schema_version') == REFERENCE_SCHEMA
          and value.get('semantic_type') == 'RIDER_PART_TYPED' and type(value.get('frames')) is list)
    # Reuse the strict box/split/provenance structural validator. This private
    # arithmetic view is never exposed as a hull reference or tracking report.
    shape = deepcopy(value)
    shape.pop('semantic_type')
    shape['schema_version'] = 'RACE_AI_BOAT_VIDEO_REFERENCE_V1'
    for frame in shape['frames']:
        _need(type(frame) is dict and 'riders' in frame and 'boats' not in frame)
        frame['boats'] = frame.pop('riders')
    validate_reference(shape)
    return deepcopy(value)


def _observations(rows, ref):
    _need(type(rows) is list and len(rows) <= 20000)
    observations, previous_index, previous_pts, previous_scene, origin = [], -1, None, -1, None
    for row in rows:
        _need(type(row) is dict and row.get('schema_version') == 'RACE_AI_BOAT_MARKER_FRAME_JOURNAL_V1'
              and row.get('media_sha256') == ref['media_sha256'])
        index, pts, t = row.get('frame_index'), row.get('source_pts'), row.get('t')
        _need(type(index) is int and index > previous_index and _finite(pts)
              and _finite(t) and t >= 0 and (previous_pts is None or pts > previous_pts))
        _sha(row.get('decoded_bgr_sha256'))
        if origin is None:
            origin = pts - t
        _need(abs((pts - t) - origin) <= 1e-9)
        pipeline = row.get('pipeline_result')
        _need(type(pipeline) is dict and type(pipeline.get('frame_index')) is int
              and pipeline['frame_index'] == index and _finite(pipeline.get('t')) and pipeline['t'] == t
              and pipeline.get('frame_sha256') == row['decoded_bgr_sha256']
              and pipeline.get('identity_validated') is False and pipeline.get('model_eligible') is False)
        packet = pipeline.get('rider_part_tracking')
        observation = dict(frame_index=index, t=pts, scene=None, regions=None, quality_flags=[],
                           decoded_frame_sha256=row['decoded_bgr_sha256'])
        if packet is not None:
            _need(type(packet) is dict and packet.get('schema_version') == 'RACE_AI_RIDER_PART_TRACKS_V1'
                  and packet.get('semantic_type') == 'RIDER_PART_TYPED' and packet.get('coordinate_space') == 'IMAGE_PX'
                  and type(packet.get('frame_index')) is int and packet['frame_index'] == index
                  and _finite(packet.get('t')) and packet['t'] == t
                  and packet.get('frame_sha256') == row['decoded_bgr_sha256']
                  and packet.get('identity_validated') is False and packet.get('model_eligible') is False)
            scene = packet.get('scene')
            _need(type(scene) is int and scene >= previous_scene and scene >= 0 and pipeline.get('scene') == scene)
            previous_scene = scene
            flags = packet.get('quality_flags')
            _need(type(flags) is list and len(flags) <= 100 and
                  all(type(flag) is str and _LABEL.fullmatch(flag) for flag in flags))
            tracks = packet.get('tracks')
            _need(type(tracks) is list and len(tracks) <= 64)
            regions, ids = [], set()
            for track in tracks:
                _need(type(track) is dict and track.get('semantic_type') == 'RIDER_PART_TYPED'
                      and track.get('hull_box') is None and track.get('identity_source') == 'CLOTHING_COLOR'
                      and track.get('printed_number_observed') is False)
                key, number = track.get('track_id'), track.get('number')
                _need(type(key) is str and _LABEL.fullmatch(key) and key not in ids)
                ids.add(key)
                _box(track.get('rider_box'), ref['width'], ref['height'])
                _need(number is None or type(number) is int and 1 <= number <= 6)
                evidence = track.get('number_evidence_status')
                if number is not None:
                    _need((evidence, track.get('number_status')) in (
                        (_CURRENT, 'CLOTHING_COLOR_CANDIDATE'), (_CARRIED, 'PRIOR_CLOTHING_TRACK_CANDIDATE')))
                else:
                    _need(evidence is None)
                regions.append(dict(box=deepcopy(track['rider_box']), lane=number,
                                    track_id=key, clothing_evidence=evidence))
            observation.update(scene=scene, regions=regions, quality_flags=list(flags))
        observations.append(observation)
        previous_index, previous_pts = index, pts
    return observations


def benchmark_clothing_identity(journal, reference, *, configuration=None):
    """Compare original CLI clothing observations with typed rider references.

    Reference ``t`` is absolute source PTS; tracker-relative time is checked
    separately. Match every part before scoring known labels, so unknown parts
    remain observed identity misses. Config accepts IoU and transition-gap
    thresholds only. No engine, human or physical certification is inferred.
    """
    try:
        ref = _reference(reference)
        config = {} if configuration is None else deepcopy(configuration)
        _need(type(config) is dict and set(config) <= {'iou_threshold', 'max_transition_gap_seconds'})
        threshold, gap = config.get('iou_threshold', .5), config.get('max_transition_gap_seconds', .5)
        _need(_finite(threshold) and 0 < threshold <= 1 and _finite(gap) and gap > 0)
        config.update(iou_threshold=threshold, max_transition_gap_seconds=gap)
        observations = _observations(journal, ref)
        frames = {row['frame_index']: (n, row) for n, row in enumerate(ref['frames'])}
        scored = {r['frame_index'] for r in observations if r['frame_index'] in frames and r['regions'] is not None}
        partitions = {r['partition']: _metrics() for r in ref['frames']} if scored else None
        if partitions is not None:
            for metrics in partitions.values():
                metrics.update(matched_rider_parts=0, false_positive_rider_parts=0,
                    missed_reference_rider_parts=0, rider_predictions_scored=0,
                    unknown_clothing_matches=0, current_color_correct_matches=0,
                    carried_color_correct_matches=0, whole_six_current_color_correct_frames=0)
        state, previous = {}, None
        for observation in observations:
            index = observation['frame_index']
            if index not in frames:
                state, previous = {}, None
                continue
            position, frame = frames[index]
            _need(observation['t'] == frame['t'] and
                  observation['decoded_frame_sha256'] == frame['decoded_frame_sha256'])
            if observation['regions'] is None:
                state, previous = {}, None
                continue
            continuity = (frame['continuity_group'], frame['partition'], observation['scene'])
            if (previous is None or previous[0] + 1 != position or previous[1] != continuity
                or index != previous[3] + 1 or frame['t'] - previous[2] > gap):
                state = {}
            metrics = partitions[frame['partition']]
            regions, targets = observation['regions'], frame['riders']
            pairs = _matches(regions, targets, threshold)
            metrics['matched_rider_parts'] += len(pairs)
            metrics['missed_reference_rider_parts'] += len(targets) - len(pairs)
            if frame['exhaustive']:
                metrics['false_positive_rider_parts'] += len(regions) - len(pairs)
                metrics['rider_predictions_scored'] += len(regions)
            else:
                metrics['rider_predictions_scored'] += len(pairs)
            for i, j in pairs:
                if regions[i]['lane'] is None:
                    metrics['unknown_clothing_matches'] += 1
            # Reuse the existing identity arithmetic on the already fixed
            # geometric matches, without ever constructing a hull-track report.
            numbered = {i: row for i, row in enumerate(regions) if row['lane'] is not None}
            remap = {original: n for n, original in enumerate(numbered)}
            identity_pairs = [(remap[i], j) for i, j in pairs if i in remap]
            previous_six = metrics['whole_six_correct_frames']
            known = _score_frame(metrics, list(numbered.values()), dict(frame, boats=targets), identity_pairs)
            if len(regions) != 6:
                # The identity arithmetic sees numbered parts only; an extra
                # unknown proposal must still prevent perfect-frame acceptance.
                metrics['whole_six_correct_frames'] = previous_six
            current_correct = 0
            for lane, row in known.items():
                if lane == row['lane']:
                    field = 'current_color_correct_matches' if row['clothing_evidence'] == _CURRENT else 'carried_color_correct_matches'
                    metrics[field] += 1
                    current_correct += int(row['clothing_evidence'] == _CURRENT)
            if frame['exhaustive'] and {r['lane'] for r in targets} == set(range(1, 7)):
                metrics['whole_six_current_color_correct_frames'] += int(len(regions) == current_correct == 6)
            current = {}
            for target in targets:
                lane = target['lane']
                if lane is None:
                    continue
                seen, old = state.get(lane, (False, None))
                row = known.get(lane)
                if row is not None:
                    if old is not None:
                        metrics['matched_identity_transitions'] += 1
                        metrics['anonymous_id_switches'] += int(old[0] != row['track_id'])
                        metrics['number_id_switches'] += int(old[1] != row['lane'])
                    elif seen:
                        metrics['fragmentations'] += 1
                    current[lane] = (True, (row['track_id'], row['lane']))
                else:
                    current[lane] = (seen, None)
            state, previous = current, (position, continuity, frame['t'], index)
        for metrics in (partitions or {}).values():
            _finish(metrics)
            metrics['reference_visible_rider_parts'] = metrics.pop('reference_visible_boats')
            metrics['missed_reference_identities'] = metrics.pop('missed_reference_boats')
            denominator = metrics['rider_predictions_scored']
            metrics['rider_part_precision'] = metrics['matched_rider_parts'] / denominator if denominator else None
            denominator = metrics['reference_visible_rider_parts']
            metrics['rider_part_coverage'] = metrics['matched_rider_parts'] / denominator if denominator else None
        heldout = any(row['partition'] == 'HELDOUT' for row in ref['frames'])
        report = dict(schema_version=SCHEMA, media_sha256=ref['media_sha256'],
            reference_sha256=digest(ref), journal_rows_sha256=digest(journal), configuration=config,
            semantic_type='RIDER_PART_TYPED', prediction_scope='CLOTHING_IDENTITIES_ON_RIDER_PARTS_NOT_HULLS',
            media_class=ref['media_class'], reference_class=ref['reference_class'], human_verified=False,
            blind_to_predictions=ref['blind_to_predictions'], reference_authentication='NOT_ESTABLISHED',
            split_scope=ref['split_scope'], split_frozen_before_predictions=ref['split_frozen_before_predictions'],
            disjoint_source_heldout=False, heldout_scope=('NOT_FROZEN_BEFORE_PREDICTIONS' if not
                ref['split_frozen_before_predictions'] else 'WITHIN_CLIP_ONLY' if ref['split_scope'] == 'WITHIN_CLIP'
                else 'DECLARED_WHOLE_MEDIA') if heldout else 'NONE',
            status='UNAVAILABLE' if not scored else 'PARTIAL' if len(scored) != len(frames) else 'SCORED',
            reference_frames=len(frames), reference_frames_without_predictions=len(frames) - len(scored),
            unlabeled_prediction_frames=sum(row['frame_index'] not in frames for row in observations),
            quality_flag_counts=dict(sorted(Counter(flag for row in observations for flag in
                set(row['quality_flags'])).items())), partitions=partitions,
            identity_validated=False, independent_human_heldout_verified=False,
            physical_calibration_established=False, strength_established=False,
            prediction_eligible=False, production_eligible=False, accuracy_improvement_proven=False,
            source_clock_authentication='NOT_ESTABLISHED', engine_metadata_authenticated=False,
            continuous_unlabeled_tracking_established=False)
        report['benchmark_sha256'] = digest(report)
        return report
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None
