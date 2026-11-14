"""Opt-in original-pixel marker execution; no source/identity authentication.

Explicit callbacks discover/read/classify actual image regions. Their declared
metadata, including development classifier pins, is not an accuracy attestation.
No ground-truth ROI, color identity, invisible position, production default or
forecast-model eligibility is introduced by this development pipeline.
"""
from copy import copy
from fractions import Fraction
from hashlib import sha256
import json
import math
import re

from .boat_video_identity import _finite, _iou, _pixels
from .boat_video_marker_flow import MarkerPixelFollower
from .boat_video_marker_identity import MarkerIdentityTracker, _cost, _predicted
from .boat_video_marker_reader import marker_regions
from .boat_video_marker_verifier import GLYPH_MODEL_SHA256
from .boat_video_ppocr import SCORE_SCOPE


SCHEMA = 'RACE_AI_BOAT_MARKER_PIPELINE_V1'
CTC_POLICY = 'CTC_AND_GLYPH_AGREEMENT'
CLASSIFIER_POLICY = 'DEVELOPMENT_GLYPH_CLASSIFIER'
_CLASSIFIER_SOURCE = 'DECLARED_DEVELOPMENT_GLYPH_CLASSIFIER'


def _need(condition):
    if not condition:
        raise ValueError('BOAT_MARKER_PIPELINE_REJECTED')


def _safe_record(row):
    _need(type(row) is dict)
    try:
        return json.loads(json.dumps(row, allow_nan=False))
    except (TypeError, ValueError):
        raise ValueError('BOAT_MARKER_PIPELINE_RECORD_REJECTED') from None


def _digest(image):
    return sha256(image.tobytes()).hexdigest()


def _hex(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _xyxy(box, width, height):
    _need(type(box) in (list, tuple) and len(box) == 4 and all(type(v) is int for v in box))
    x, y, right, bottom = box
    _need(0 <= x < right <= width and 0 <= y < bottom <= height)
    return [x, y, right, bottom]


def _wh(box):
    x, y, right, bottom = box
    return [x, y, right-x, bottom-y]


def _printed(item, offsets):
    x, y, _, _ = item['box']
    dx, dy, width, height = offsets[item['key']]
    return [x+dx, y+dy, width, height]


def _context_image_track(flowed, row, *, frame_sha, frame_index, scene, diagnostic=None):
    """Expose actual context point lineage; never an existing M-ID selector."""
    _need(type(flowed) is dict and type(row) is dict and (diagnostic is None or type(diagnostic) is dict))
    def report(status,reasons):
        if diagnostic is not None:
            diagnostic.update(status=status,reasons=reasons,
                              fallback='GEOMETRY_ONLY' if status != 'ELIGIBLE' else None)
    if flowed.get('schema_version') != 'RACE_AI_BOAT_MARKER_PIXEL_FLOW_V1':
        report('UNAVAILABLE',['NONSTANDARD_FLOW_ENVELOPE'])
        return None  # Nonstandard controlled test providers have no LK proof.
    _need(flowed.get('coordinate_space') == 'IMAGE_PX' and flowed.get('frame_sha256') == frame_sha
          and type(flowed.get('frame_index')) is int and flowed['frame_index'] == frame_index
          and type(flowed.get('scene')) is int and flowed['scene'] == scene)
    names = ('key','status','previous_frame_sha256','box','point_count','median_displacement_px',
             'median_forward_backward_error_px','displacement_dispersion_px','affine_area_ratio')
    _need(all(name in row for name in names))
    result = _safe_record({name: row[name] for name in names})
    _need(type(result['key']) is str and 0 < len(result['key']) <= 128
          and not any(ord(c)<32 or ord(c)==127 for c in result['key'])
          and type(result['status']) is str and result['status'] in ('SEEDED','TRACKED')
          and type(result['point_count']) is int and result['point_count'] >= 0
          and type(result['box']) is list and len(result['box']) == 4
          and all(_finite(v) for v in result['box']) and min(result['box'][:2]) >= 0
          and min(result['box'][2:]) >= 1)
    reasons=[]
    if not 4 <= result['point_count'] <= 40:
        reasons.append('POINT_SUPPORT_OUTSIDE_HINT_BOUND')
    quality=('median_displacement_px','median_forward_backward_error_px','displacement_dispersion_px','affine_area_ratio')
    if result['status'] == 'SEEDED':
        _need(result['previous_frame_sha256'] is None and all(result[k] is None for k in quality))
    else:
        move=result['median_displacement_px']
        _need(_hex(result['previous_frame_sha256']) and type(move) is list and len(move)==2
              and all(_finite(v) for v in move)
              and _finite(result['median_forward_backward_error_px']) and result['median_forward_backward_error_px'] >= 0
              and _finite(result['displacement_dispersion_px']) and result['displacement_dispersion_px'] >= 0
              and _finite(result['affine_area_ratio']) and result['affine_area_ratio'] > 0)
        movement=math.hypot(*move)
        _need(math.isfinite(movement))
        # The producer checks the pre-refit median/dispersion, then reports
        # recomputed values for its final affine inliers. A finite accepted
        # flow may therefore be usable without meeting optional hint bounds.
        if movement > max(8.,.75*math.hypot(*result['box'][2:])):
            reasons.append('POST_REFIT_DISPLACEMENT_EXCEEDS_HINT_BOUND')
        if result['displacement_dispersion_px'] > 2:
            reasons.append('POST_REFIT_DISPERSION_EXCEEDS_HINT_BOUND')
        if result['median_forward_backward_error_px'] > 1:
            reasons.append('FORWARD_BACKWARD_ERROR_EXCEEDS_HINT_BOUND')
        if not .75 <= result['affine_area_ratio'] <= 1.33:
            reasons.append('AFFINE_AREA_OUTSIDE_HINT_BOUND')
    if reasons:
        report('OMITTED',reasons)
        return None
    result.update(scope='CONTEXT_IMAGE_TRACK',frame_sha256=frame_sha,frame_index=frame_index,scene=scene)
    report('ELIGIBLE',[])
    return result


def _containment(a, b):
    x, y, w, h = a
    u, v, c, d = b
    intersection = max(0., min(x+w, u+c)-max(x, u))*max(0., min(y+h, v+d)-max(y, v))
    return intersection/min(w*h, c*d)


def _mutual_centers(a, b):
    """Half-open mutual center inclusion for partial views of one marker."""
    x, y, w, h = a
    u, v, c, d = b
    return (x <= u+c/2 < x+w and y <= v+d/2 < y+h and
            u <= x+w/2 < u+c and v <= y+h/2 < v+d)


def _collapse_views(boxes, labels):
    """Complete-link same-label views; a bridge never merges distinct ends."""
    same, bad = [set() for _ in boxes], set()
    for i, box in enumerate(boxes):
        for j, other in enumerate(boxes[:i]):
            if _containment(box, other) >= .8 or _mutual_centers(box, other):
                if labels[i] == labels[j]:
                    same[i].add(j); same[j].add(i)
                else: bad.update((i, j))
    # Preserve fail-closed conflict propagation to aliases. This can only
    # abstain; it never creates a collapsed group or a numeric observation.
    ambiguous, pending = set(bad), list(bad)
    while pending:
        for other in same[pending.pop()]:
            if other not in ambiguous:
                ambiguous.add(other); pending.append(other)
    groups, collapsed = [], {}
    order = sorted(range(len(boxes)), key=lambda i: (-boxes[i][2]*boxes[i][3], i))
    for i in order:
        if i in ambiguous:
            continue
        group = next((g for g in groups if all(j in same[i] for j in g)), None)
        if group is None:
            groups.append([i])
        else:
            # The first member has the largest geometry. Every member must
            # directly match every other, including both sides of a chain.
            collapsed[i] = group[0]; group.append(i)
    # M's existing IoU.8 view dedupe must not rejoin representatives of
    # different complete-link groups and erase their distinct endpoints.
    for i, group in enumerate(groups):
        for other in groups[:i]:
            if labels[group[0]] == labels[other[0]] and _iou(boxes[group[0]], boxes[other[0]]) >= .8:
                ambiguous.update(group); ambiguous.update(other)
    collapsed = {i: winner for i, winner in collapsed.items()
                 if i not in ambiguous and winner not in ambiguous}
    return collapsed, ambiguous


class MarkerIdentityPipeline:
    """Atomic staged flow/identity with explicit original-image callbacks."""
    def __init__(self, recognizer, verifier, *, discover=marker_regions, refresh_frames=8,
                 label_policy=CTC_POLICY):
        _need(callable(recognizer) and callable(verifier) and callable(discover)
              and type(refresh_frames) is int and refresh_frames > 0
              and label_policy in (CTC_POLICY, CLASSIFIER_POLICY))
        self.recognizer, self.verifier, self.discover = recognizer, verifier, discover
        self.refresh_frames, self.label_policy = refresh_frames, label_policy
        self._flow, self._tracker = MarkerPixelFollower(), MarkerIdentityTracker()
        self._offsets, self._verified, self._serial = {}, {}, 0
        self._time = self._index = self._scene = self._shape = self._last_scan = None
        self._classifier_metadata()

    def _classifier_metadata(self):
        if self.label_policy != CLASSIFIER_POLICY:
            return None
        _need(callable(getattr(self.verifier, 'metadata', None)))
        metadata = _safe_record(self.verifier.metadata())
        _need(metadata.get('development_opt_in') is True
              and metadata.get('glyph_model_sha256') == GLYPH_MODEL_SHA256
              and metadata.get('training_scope') == 'DEVELOPMENT_TRAIN_OVERLAP')
        return metadata

    def _read(self, image, boxes, expected_sha, shape):
        def verify():
            arguments = [list(box) for box in boxes]
            classes = self.verifier(image, arguments) if boxes else []
            _need(arguments == boxes and type(classes) is list and len(classes) == len(boxes)
                  and tuple(image.shape) == shape and _digest(image) == expected_sha)
            verified = []
            for row in classes:
                value = _safe_record(row)
                _need(type(value.get('context_class')) is int and value['context_class'] in (0, 1)
                      and type(value.get('glyph_class')) is int and 0 <= value['glyph_class'] <= 6)
                verified.append(value)
            return verified
        classes = verify() if self.label_policy == CLASSIFIER_POLICY else None
        selected = ([i for i, row in enumerate(classes) if row['context_class'] == 1 and row['glyph_class'] > 0]
                    if classes is not None else list(range(len(boxes))))
        crops = [image[boxes[i][1]:boxes[i][3], boxes[i][0]:boxes[i][2]].copy() for i in selected]
        hashes = [_digest(crop) for crop in crops]
        crop_shapes = [tuple(crop.shape) for crop in crops]
        readings = self.recognizer(crops) if crops else []
        _need(type(readings) is list and len(readings) == len(crops))
        checked = [dict(status='CLASSIFIER_REJECTED_NO_CTC_ATTEMPT', text=None,
                        sequence_likelihood=None) for _ in boxes]
        for i, row in enumerate(readings):
            value = _safe_record(row)
            text, likelihood = value.get('text'), value.get('sequence_likelihood')
            _need(type(text) is str and len(text) <= 512 and
                  not any(ord(c) < 32 or ord(c) == 127 for c in text)
                  and (likelihood is None or _finite(likelihood) and 0 <= likelihood <= 1)
                  and (likelihood is not None) == (len(text) == 1)
                  and type(value.get('full_vocabulary_size')) is int
                  and value['full_vocabulary_size'] == 6625 and value.get('score_scope') == SCORE_SCOPE
                  and _hex(value.get('softmax_sha256'))
                  and value.get('input_sha256') == hashes[i]
                  and value.get('input_sha256_after') == hashes[i]
                  and value.get('input_shape') == list(crop_shapes[i]))
            _pixels(crops[i])
            _need(tuple(crops[i].shape) == crop_shapes[i] and _digest(crops[i]) == hashes[i])
            value['status'] = 'CTC_RECOGNIZED'
            checked[selected[i]] = value
        _need(tuple(image.shape) == shape and _digest(image) == expected_sha)
        return checked, classes if classes is not None else verify()

    def _global_eligible(self, reading, verification):
        if verification['context_class'] != 1:
            return False
        if self.label_policy == CLASSIFIER_POLICY:
            return 1 <= verification['glyph_class'] <= 6
        return reading['text'] in ('1', '2', '3', '4', '5', '6') and reading['sequence_likelihood'] > 0

    @staticmethod
    def _reconcile(eligible, boxes, live, offsets, labels, verified):
        """A unique physical overlap suppresses refresh reseeding, never a label."""
        positions = {row['key']: _printed(row, offsets) for row in live}
        matches = {i: [key for key, box in positions.items() if _iou(_wh(boxes[i]), box) > .5 or
                       labels[i] == verified.get(key) and _containment(_wh(boxes[i]), box) >= .8]
                   for i in eligible}
        reverse = {}
        for i, keys in matches.items():
            for key in keys: reverse.setdefault(key, []).append(i)
        ambiguous, suppressed, retired = set(), {}, set()
        for i, keys in matches.items():
            if len(keys) == 1 and len(reverse[keys[0]]) == 1:
                suppressed[i] = keys[0]
            elif keys:
                ambiguous.add(i); retired.update(keys)
        # Multiple fresh regions on the same physical location cannot gain a
        # winner from likelihood. The default discoverer already uses NMS .5.
        fresh = [i for i in eligible if not matches[i]]
        for position, i in enumerate(fresh):
            for j in fresh[:position]:
                if _iou(_wh(boxes[i]), _wh(boxes[j])) > .5:
                    ambiguous.update((i, j))
        return suppressed, ambiguous, retired

    def update(self, frame, *, t, frame_index, scene):
        width, height = _pixels(frame)
        _need(_finite(t) and t >= 0 and type(frame_index) is int and 0 <= frame_index < 2**63
              and type(scene) is int and 0 <= scene < 2**63)
        _need(self._time is None or t > self._time and frame_index > self._index)
        _need(self._scene is None or scene >= self._scene)
        classifier_metadata = self._classifier_metadata()
        original_shape, original_sha = tuple(frame.shape), _digest(frame)
        image = frame.copy()
        _need(tuple(image.shape) == original_shape and _digest(image) == original_sha)
        reset = (self._time is None or scene != self._scene or self._shape != (width, height)
                 or Fraction(str(t))-Fraction(str(self._time)) >= Fraction('.5'))
        scan = reset or self._last_scan is None or frame_index-self._last_scan >= self.refresh_frames
        flow, tracker = copy(self._flow), copy(self._tracker)
        # Identity updates copy tracks/evidence but append to this set.
        tracker._seen_frames = set(self._tracker._seen_frames)
        offsets = {} if reset else dict(self._offsets)
        verified = {} if reset else dict(self._verified)
        serial, seeds, current_printed = self._serial, [], {}
        global_scan = dict(performed=scan, attempts=[], candidate_count=0,
            suppressed_reseed_count=0, ambiguous_candidates=[], retired_refresh_keys=[],
            ctc_requested_images=0, classified_regions=0, collapsed_nested_view_count=0)
        if scan:
            regions = self.discover(image)
            _need(type(regions) is list and tuple(image.shape) == original_shape and _digest(image) == original_sha)
            regions = [_safe_record(row) for row in regions]
            boxes = [_xyxy(row.get('box'), width, height) for row in regions]
            readings, classes = self._read(image, boxes, original_sha, original_shape)
            eligible = [i for i, pair in enumerate(zip(readings, classes)) if self._global_eligible(*pair)]
            labels = {i: classes[i]['glyph_class'] if self.label_policy == CLASSIFIER_POLICY
                      else int(readings[i]['text']) for i in eligible}
            nested, nested_ambiguous = _collapse_views([_wh(boxes[i]) for i in eligible], [labels[i] for i in eligible])
            nested = {eligible[i]: eligible[j] for i, j in nested.items()}
            nested_ambiguous = {eligible[i] for i in nested_ambiguous}
            eligible = [i for i in eligible if i not in nested and i not in nested_ambiguous]
            # A current-pixel probe supports refresh reconciliation only. It is
            # not OCR or an independent number observation. Final flow starts
            # from the same old baseline, so time/evidence is advanced once.
            probe = copy(self._flow)
            probed = probe.update(image, [], t=t, frame_index=frame_index, scene=scene)
            live = [] if reset else probed['tracked']
            suppressed, ambiguous, retired = self._reconcile(eligible, boxes, live, offsets, labels, verified)
            ambiguous.update(nested_ambiguous)
            for row in live:
                if any(_containment(_printed(row, offsets), _wh(boxes[i])) >= .8 or
                       _iou(_printed(row, offsets), _wh(boxes[i])) > .5 for i in nested_ambiguous):
                    retired.add(row['key'])
            positions = {row['key']: row for row in live}
            corrections, outside = {}, {}
            for i, key in list(suppressed.items()):
                if key in retired:
                    del suppressed[i]; ambiguous.add(i)
                    continue
                item = positions[key]
                old_printed = _printed(item, offsets)
                cx, cy, cw, ch = item['box']
                x, y, right, bottom = boxes[i]
                details = dict(previous_marker_box=list(old_printed), corrected_marker_box=_wh(boxes[i]),
                               correction_flow_context_box=list(item['box']))
                if cx <= x < right <= cx+cw and cy <= y < bottom <= cy+ch:
                    # Current automatic discovery corrects the printed ROI;
                    # only the actual context feature points retain flow state.
                    offsets[key] = (x-cx, y-cy, right-x, bottom-y)
                    current_printed[key] = _wh(boxes[i])
                    corrections[i] = dict(details, key=key)
                else:
                    retired.add(key); del suppressed[i]
                    outside[i] = dict(details, retired_key=key)
            if retired:
                flow._tracks = {key: value for key, value in flow._tracks.items() if key not in retired}
            global_scan.update(candidate_count=len(boxes), suppressed_reseed_count=len(suppressed),
                ambiguous_candidates=sorted(ambiguous), retired_refresh_keys=sorted(retired),
                ctc_requested_images=sum(r['status'] == 'CTC_RECOGNIZED' for r in readings),
                classified_regions=len(classes), collapsed_nested_view_count=len(nested))
            for i, (region, reading, classification) in enumerate(zip(regions, readings, classes)):
                action, key = 'INELIGIBLE', None
                if i in nested: action = 'COLLAPSED_NESTED_VIEW'
                elif i in suppressed:
                    action, key = 'CORRECTED_LIVE_MARKER', suppressed[i]
                elif i in ambiguous: action = 'AMBIGUOUS_REFRESH'
                elif i in eligible:
                    x, y, right, bottom = boxes[i]
                    h = bottom-y
                    cx, cy = max(0, int(x-h)), max(0, int(y-.5*h))
                    cr, cb = min(width, int(right+h)), min(height, int(bottom+.5*h))
                    serial += 1; key = f'S{serial:06d}'
                    offsets[key] = (x-cx, y-cy, right-x, bottom-y)
                    seeds.append(dict(key=key, box=[cx, cy, cr-cx, cb-cy]))
                    action = 'RESEEDED_OUTSIDE_LIVE_CONTEXT' if i in outside else 'SEEDED'
                attempt = dict(region=region, box_xyxy=list(boxes[i]),
                    recognition=reading, verification=classification, action=action, key=key)
                attempt.update(corrections.get(i, outside.get(i, {})))
                global_scan['attempts'].append(attempt)
        flowed = flow.update(image, seeds, t=t, frame_index=frame_index, scene=scene)
        keys = {row['key'] for row in flowed['tracked']}
        offsets = {key: value for key, value in offsets.items() if key in keys}
        verified = {key: value for key, value in verified.items() if key in keys}
        live, boxes = [], []
        for row in flowed['tracked']:
            printed = current_printed.get(row['key'], _printed(row, offsets))
            x, y, w, h = printed
            box = _xyxy([math.floor(x), math.floor(y), math.ceil(x+w), math.ceil(y+h)], width, height)
            live.append((row, printed)); boxes.append(box)
        readings, classes = self._read(image, boxes, original_sha, original_shape)
        markers, attempts, marker_labels, marker_attempts = [], [], [], []
        for (row, printed), box, reading, classification in zip(live, boxes, readings, classes):
            context, glyph, text = classification['context_class'], classification['glyph_class'], reading['text']
            admission, marker, blank_hold_evidence = 'UNKNOWN', None, None
            hint_diagnostic=dict(status='NOT_REQUESTED',reasons=['NO_FRESH_NUMBER'],fallback=None)
            if self.label_policy == CLASSIFIER_POLICY:
                if context == 1 and 1 <= glyph <= 6:
                    marker = dict(box=list(printed), text=str(glyph), sequence_likelihood=None,
                        context_status='SINGLE_MARK', label_source=_CLASSIFIER_SOURCE,
                        label_model_sha256=GLYPH_MODEL_SHA256)
                    admission = 'FRESH_DEVELOPMENT_CLASSIFIER_LABEL'; verified[row['key']] = glyph
            elif context == 1 and text in ('1', '2', '3', '4', '5', '6') and glyph == int(text) and reading['sequence_likelihood'] > 0:
                marker = dict(box=list(printed), text=text, sequence_likelihood=reading['sequence_likelihood'],
                              context_status='SINGLE_MARK')
                admission = 'FRESH_CTC_GLYPH_AGREEMENT'; verified[row['key']] = glyph
            elif (text == '' and row['status'] == 'TRACKED' and context == 1
                  and row['key'] in verified and glyph == verified[row['key']]):
                # Classifier mode never reaches here: reject0 is not unread.
                expected, compatible = verified[row['key']], []
                for old in tracker._tracks:
                    predicted = _predicted(old, t)
                    cost = _cost(predicted, printed)
                    if cost is not None:
                        compatible.append(dict(track_id=old['track_id'], number=old['number'],
                            predicted_marker_box=list(predicted), association_cost=cost))
                compatible.sort(key=lambda r: (r['number'], r['track_id']))
                blank_hold_evidence = dict(expected_number=expected, compatible_previous_tracks=compatible)
                if len(compatible) == 1 and compatible[0]['number'] == expected:
                    marker = dict(box=list(printed), text='', sequence_likelihood=None, context_status='SINGLE_MARK')
                    admission = 'VISIBLE_BLANK_HOLD'
                else:
                    admission = 'HOLD_EXPECTATION_MISMATCH'
            if marker is not None:
                if marker['text'] in ('1','2','3','4','5','6'):
                    hint = _context_image_track(flowed,row,frame_sha=original_sha,frame_index=frame_index,scene=scene,
                                                diagnostic=hint_diagnostic)
                    if hint is not None:
                        marker['context_image_track'] = hint
                markers.append(marker); marker_labels.append(glyph); marker_attempts.append(len(attempts))
            attempts.append(dict(key=row['key'], marker_box=list(printed), box_xyxy=box,
                flow_context_box=list(row['box']), flow_status=row['status'], recognition=reading,
                verification=classification, admission=admission,
                blank_hold_evidence=blank_hold_evidence,
                context_image_track_diagnostic=hint_diagnostic,
                pp_classifier_disagreement=bool(text and glyph > 0 and text != str(glyph))))
        nested, ambiguous = _collapse_views([m['box'] for m in markers], marker_labels)
        for i in nested: attempts[marker_attempts[i]]['admission'] = 'COLLAPSED_NESTED_VIEW'
        for i in ambiguous: attempts[marker_attempts[i]]['admission'] = 'AMBIGUOUS_OVERLAPPING_LABELS'
        markers = [m for i, m in enumerate(markers) if i not in nested and i not in ambiguous]
        identity = tracker.update(image, markers, t=t, frame_index=frame_index, scene=scene)
        _pixels(frame)
        _need(tuple(frame.shape) == original_shape and _digest(frame) == original_sha
              and tuple(image.shape) == original_shape and _digest(image) == original_sha)
        result = dict(schema_version=SCHEMA, coordinate_space='IMAGE_PX', frame_sha256=original_sha,
            t=float(t), frame_index=frame_index, scene=scene, label_policy=self.label_policy,
            global_scan=global_scan, flow=flowed, local_attempts=attempts, marker_observations=markers,
            local_ctc_requested_images=sum(r['status'] == 'CTC_RECOGNIZED' for r in readings),
            local_classified_regions=len(classes),
            identity=identity, callback_provenance='EXPLICIT_CALLBACKS_NOT_AUTHENTICATED',
            declared_development_verifier=classifier_metadata, model_eligible=False,
            field_validation='NOT_ESTABLISHED', metric_positions_inferred=False,
            identity_validated=False, color_number_inference=False)
        self._flow, self._tracker = flow, tracker
        self._offsets, self._verified, self._serial = offsets, verified, serial
        self._time, self._index, self._scene, self._shape = float(t), frame_index, scene, (width, height)
        if scan: self._last_scan = frame_index
        return result
