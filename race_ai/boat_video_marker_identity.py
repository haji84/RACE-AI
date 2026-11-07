"""Opt-in printed-marker association in IMAGE_PX, never course or world motion.

Inputs are typed observations from a separate reader or declared development
glyph classifier. This algorithm does not authenticate their labels, model
hash, source pixels, capture clock or semantic context. Three
distinct supplied frame/pixel observations establish an unvalidated candidate,
not field accuracy. No detector, reader, weights or legacy policy is replaced.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import math

from .boat_video_identity import _box, _center, _finite, _intersects, _iou, _pixels


SCHEMA = 'RACE_AI_BOAT_MARKER_IDENTITY_OBSERVATION_V1'
_CONTEXTS = {'SINGLE_MARK', 'MULTIDIGIT_GROUP', 'NONTARGET', 'AMBIGUOUS'}
_FIELDS = {'box', 'text', 'sequence_likelihood', 'context_status'}
_SCOPE = 'UNCALIBRATED_CTC_SEQUENCE_LIKELIHOOD_NOT_ACCURACY'
_LABEL_SOURCE = 'DECLARED_DEVELOPMENT_GLYPH_CLASSIFIER'
_CLASSIFIER_FIELDS = _FIELDS | {'label_source', 'label_model_sha256'}
_CLASSIFIER_SCOPE = 'DISCRETE_DEVELOPMENT_CLASSIFICATION_NOT_PROBABILITY'
_MARGIN = .15


def _need(condition):
    if not condition:
        raise ValueError('BOAT_MARKER_IDENTITY_REJECTED')


def _age(now, then):
    # Decimal PTS boundaries should not gain/lose a frame through 0.7-0.2.
    return Fraction(str(now)) - Fraction(str(then))


class _Index:
    """Spatial neighborhood lookup; large context rectangles stay one entry."""
    def __init__(self):
        self.cells = defaultdict(set)
        self.large = set()

    @staticmethod
    def keys(box):
        x, y, w, h = box
        a, b, c, d = math.floor(x/64), math.floor(y/64), math.floor((x+w)/64), math.floor((y+h)/64)
        return a, b, c, d

    def add(self, ident, box):
        a, b, c, d = self.keys(box)
        if (c-a+1)*(d-b+1) > 64:
            self.large.add(ident)
        else:
            for x in range(a, c+1):
                for y in range(b, d+1):
                    self.cells[(x, y)].add(ident)

    def query(self, box):
        a, b, c, d = self.keys(box)
        result = set(self.large)
        for x in range(a, c+1):
            for y in range(b, d+1):
                result.update(self.cells.get((x, y), ()))
        return result


def _number(row):
    value = row['sequence_likelihood']
    return int(row['text']) if (row['text'] in ('1', '2', '3', '4', '5', '6')
        and ((value is not None and value > 0) or
             (value is None and row.get('label_source') == _LABEL_SOURCE))) else None


def _prepare(markers):
    """Separate forbidden parent context before deduplicating marker views."""
    blockers, eligible, unknown, flags = [], [], [], set()
    for row in markers:
        reason = None
        if row['context_status'] != 'SINGLE_MARK':
            reason = {'MULTIDIGIT_GROUP':'MULTIDIGIT_CONTEXT', 'NONTARGET':'NONTARGET_CONTEXT',
                      'AMBIGUOUS':'AMBIGUOUS_CONTEXT'}[row['context_status']]
        elif row['text'] != '' and _number(row) is None:
            reason = 'MULTIDIGIT_CONTEXT' if len(row['text']) > 1 else 'NON_NUMERIC_OR_UNRESOLVED_MARK'
        elif row['text'] == '' and row['sequence_likelihood'] is not None:
            reason = 'UNRESOLVED_READING'
        if reason:
            blockers.append(row['box']); flags.add(reason)
            unknown.append(dict(box=list(row['box']), reason=reason))
        else:
            eligible.append(row)
    context = _Index()
    for i, box in enumerate(blockers):
        context.add(i, box)
    clean = []
    for row in eligible:
        if any(_intersects(row['box'], blockers[i]) for i in context.query(row['box'])):
            unknown.append(dict(box=list(row['box']), reason='PARENT_CONTEXT_INTERSECTION'))
        else:
            clean.append(row)
    # Same-mark view duplicates do not create separate votes or identities.
    groups, index, blanks = [], _Index(), {}
    for row in sorted(clean, key=lambda r:(r['text'], tuple(r['box']), r['sequence_likelihood'] or 0)):
        if row['text'] == '':
            key = tuple(row['box'])
            if key in blanks:
                flags.add('DUPLICATE_VIEWS_COLLAPSED')
                continue
            blanks[key] = len(groups)
            groups.append(row)
            continue
        duplicate = next((i for i in sorted(index.query(row['box']))
            if groups[i]['text'] == row['text'] and _iou(groups[i]['box'], row['box']) >= .8), None)
        if duplicate is not None:
            flags.add('DUPLICATE_VIEWS_COLLAPSED')
            if (-(row['sequence_likelihood'] or 0), tuple(row['box'])) < (
                    -(groups[duplicate]['sequence_likelihood'] or 0), tuple(groups[duplicate]['box'])):
                groups[duplicate] = row
                index.add(duplicate, row['box'])
        else:
            index.add(len(groups), row['box'])
            groups.append(row)
    repeated = {n for n, count in Counter(_number(r) for r in groups if _number(r) is not None).items() if count > 1}
    blocked = {i for i, r in enumerate(groups) if _number(r) in repeated}
    if repeated:
        flags.add('DUPLICATE_NUMBER')
    numeric = [(i, r) for i, r in enumerate(groups) if _number(r) is not None and i not in blocked]
    for position, (i, left) in enumerate(numeric):
        for j, right in numeric[:position]:
            if _iou(left['box'], right['box']) >= .2:
                blocked.update((i, j)); flags.add('OVERLAPPING_CONFLICTING_MARKS')
    observed = []
    for i, row in enumerate(groups):
        if i in blocked:
            reason = 'DUPLICATE_NUMBER' if _number(row) in repeated else 'OVERLAPPING_CONFLICTING_MARKS'
            unknown.append(dict(box=list(row['box']), reason=reason)); blockers.append(row['box'])
        else:
            observed.append(row)
    return observed, blockers, repeated, unknown, flags


def _predicted(track, t):
    dt = float(t-track['t'])
    dx, dy = (v*dt for v in track['velocity'])
    x, y, w, h = track['box']
    result = [x+dx, y+dy, w, h]
    return result if all(math.isfinite(v) for v in result) else None


def _cost(predicted, box):
    if predicted is None:
        return None
    distance = math.dist(_center(predicted), _center(box))
    gate = max(12., 1.5*math.hypot(predicted[2], predicted[3]))
    ratio = box[2]*box[3]/(predicted[2]*predicted[3])
    if distance <= gate and .5 <= ratio <= 2:
        return distance/gate + .4*(1-_iou(predicted, box)) + .2*abs(math.log(ratio))
    return None


def _correspondences(previous, observed, blockers, repeated, t):
    """Sparse reciprocal-unique matches, bounded by at most six numeric tracks.

    We deliberately abstain from ambiguous alternatives rather than selecting
    an arbitrary maximum-cardinality assignment. There is no exponential DP.
    """
    rows, columns, ambiguous = {}, defaultdict(list), set()
    for i, old in enumerate(previous):
        if old['number'] in repeated:
            continue
        predicted = _predicted(old, t)
        if predicted is None:
            continue
        # Parent equipment/overlay regions need not have a marker-sized area.
        # An interrupted original must not transfer to an unread neighbor just
        # because the parent's area ratio fails the marker association gate.
        if any(_intersects(predicted, box) for box in blockers):
            continue
        require_fresh = (any(_cost(predicted, box) is not None for box in blockers) or
            any(_number(r) not in (None, old['number']) and _cost(predicted, r['box']) is not None for r in observed))
        choices = []
        for j, row in enumerate(observed):
            digit = _number(row)
            if digit is not None and digit != old['number'] or require_fresh and digit is None:
                continue
            cost = _cost(predicted, row['box'])
            if cost is not None:
                choices.append((cost, j)); columns[j].append((cost, i))
        if choices:
            choices.sort()
            if len(choices) > 1 and choices[1][0]-choices[0][0] <= _MARGIN:
                ambiguous.update(j for cost, j in choices if cost-choices[0][0] <= _MARGIN)
            else:
                rows[i] = choices[0][1]
    column_best = {}
    for j, choices in columns.items():
        choices.sort()
        if len(choices) > 1 and choices[1][0]-choices[0][0] <= _MARGIN:
            ambiguous.add(j)
        else:
            column_best[j] = choices[0][1]
    return {j:previous[i] for i,j in rows.items() if j not in ambiguous and column_best.get(j)==i}, ambiguous


class MarkerIdentityTracker:
    """Track visible printed marks; invisible marks never get predicted output."""
    def __init__(self, min_observations=3, max_gap_seconds=.5):
        _need(type(min_observations) is int and 3 <= min_observations <= 20)
        _need(_finite(max_gap_seconds) and 0 < max_gap_seconds <= .5)
        self.minimum = min_observations
        self.max_gap = float(max_gap_seconds)
        self._tracks = []
        self._time = self._frame_index = self._scene = self._shape = None
        self._next_id = 1
        self._seen_frames = set()

    def update(self, frame, markers, *, t, frame_index, scene):
        width, height = _pixels(frame)
        _need(_finite(t) and t >= 0 and type(frame_index) is int and 0 <= frame_index < 2**63
              and type(scene) is int and 0 <= scene < 2**63)
        _need(self._time is None or t > self._time and frame_index > self._frame_index)
        _need(self._scene is None or scene >= self._scene)
        _need(type(markers) is list and len(markers) <= 20000)
        checked = []
        for row in markers:
            _need(type(row) is dict and set(row) in (_FIELDS, _CLASSIFIER_FIELDS)
                  and type(row['context_status']) is str
                  and row['context_status'] in _CONTEXTS)
            _need(type(row['text']) is str and len(row['text']) <= 512 and
                  not any(ord(c)<32 or ord(c)==127 for c in row['text']))
            value = row['sequence_likelihood']
            _need(value is None or _finite(value) and 0 <= value <= 1)
            item = dict(box=_box(row['box'], width, height), text=row['text'],
                sequence_likelihood=float(value) if value is not None else None, context_status=row['context_status'])
            if set(row) == _CLASSIFIER_FIELDS:
                _need(row['label_source'] == _LABEL_SOURCE and value is None
                      and row['text'] in ('', '1', '2', '3', '4', '5', '6'))
                digest = row['label_model_sha256']
                _need(type(digest) is str and len(digest) == 64
                      and all(c in '0123456789abcdef' for c in digest))
                item.update(label_source=_LABEL_SOURCE, label_model_sha256=digest)
            checked.append(item)
        frame_sha = sha256(frame.tobytes()).hexdigest()
        frame_key = (width, height, frame_sha)
        new_pixels = frame_key not in self._seen_frames
        reset = (self._time is None or scene != self._scene or self._shape != (width, height)
                 or _age(t, self._time) >= Fraction(str(self.max_gap)))
        previous = [] if reset else self._tracks
        observed, blockers, repeated, unknown, flags = _prepare(checked)
        if not new_pixels:
            flags.add('REPEATED_FRAME_PIXELS')
        if reset:
            flags.add('IMAGE_SCENE_OR_TIME_RESET')
        matched, ambiguous = _correspondences(previous, observed, blockers, repeated, t)
        if ambiguous:
            flags.add('AMBIGUOUS_MARKER_ASSOCIATION')
        current, output, next_id = [], [], self._next_id
        for j, row in enumerate(observed):
            if j in ambiguous:
                unknown.append(dict(box=list(row['box']), reason='AMBIGUOUS_MARKER_ASSOCIATION'))
                continue
            digit = _number(row)
            fresh = digit is not None and new_pixels
            old = matched.get(j)
            if old is not None and not fresh and _age(t,old['last_number_t']) >= Fraction(str(self.max_gap)):
                old = None
            if old is None:
                if not fresh:
                    unknown.append(dict(box=list(row['box']), reason='NO_CURRENT_NUMERIC_ANCHOR'))
                    continue
                old = dict(track_id=f'M{next_id:06d}',number=digit,evidence=[],box=row['box'],t=float(t),
                           last_number_t=float(t),velocity=(0.,0.))
                next_id += 1; velocity = (0.,0.)
            else:
                before, after = _center(old['box']), _center(row['box'])
                velocity = tuple((after[k]-before[k])/(t-old['t']) for k in (0,1))
                _need(all(math.isfinite(v) for v in velocity))
            evidence = deepcopy(old['evidence'])
            last_number_t = old['last_number_t']
            if fresh:
                reading = dict(frame_index=frame_index,t=float(t),frame_sha256=frame_sha,
                    marker_box=list(row['box']),sequence_likelihood=row['sequence_likelihood'])
                if 'label_source' in row:
                    reading.update(label_source=row['label_source'], label_model_sha256=row['label_model_sha256'])
                evidence.append(reading)
                evidence = evidence[-20:]
                last_number_t = float(t)
            item = dict(track_id=old['track_id'],number=old['number'],evidence=evidence,box=list(row['box']),
                        t=float(t),velocity=velocity,last_number_t=last_number_t)
            current.append(item)
            if len(evidence) < self.minimum:
                unknown.append(dict(box=list(row['box']), reason='INSUFFICIENT_DISTINCT_NUMBER_OBSERVATIONS'))
                continue
            number_evidence = dict(observations=len(evidence),first_frame_index=evidence[0]['frame_index'],
                    last_frame_index=evidence[-1]['frame_index'],last_observed_t=last_number_t,
                    fresh_frames=deepcopy(evidence),sequence_likelihood_scope=_SCOPE)
            models = sorted({e['label_model_sha256'] for e in evidence if 'label_source' in e})
            if models:
                number_evidence.update(classifier_label_scope=_CLASSIFIER_SCOPE, label_model_sha256s=models,
                    sequence_likelihood_scope=_SCOPE if any(e['sequence_likelihood'] is not None for e in evidence) else None)
                if len(models) == 1:
                    number_evidence['label_model_sha256'] = models[0]
            output.append(dict(number=item['number'],marker_box=list(row['box']),track_id=item['track_id'],
                hull_box=None,status='FRESH_NUMBER' if fresh else 'HELD_NUMBER', number_evidence=number_evidence))
        duplicates={n for n,count in Counter(r['number'] for r in current).items() if count>1}
        if duplicates:
            flags.add('DUPLICATE_NUMBER')
            unknown.extend(dict(box=list(r['box']),reason='DUPLICATE_NUMBER')
                           for r in current if r['number'] in duplicates)
            current=[r for r in current if r['number'] not in duplicates]
            output=[r for r in output if r['number'] not in duplicates]
        _need(len(current) <= 6 and len({r['number'] for r in current}) == len(current))
        ids = {row['track_id'] for row in current}
        result = dict(schema_version=SCHEMA,coordinate_space='IMAGE_PX',t=float(t),frame_index=frame_index,
            scene=scene,frame_sha256=frame_sha,tracks=sorted(output,key=lambda r:r['number']),
            unknown_markers=sorted(unknown,key=lambda r:(tuple(r['box']),r['reason'])),
            lost_track_ids=sorted(r['track_id'] for r in self._tracks if r['track_id'] not in ids),
            quality_flags=sorted(flags),raw_candidate_count=len(markers),
            identity_validated=False,model_eligible=False,metric_positions_inferred=False,
            field_validation='NOT_ESTABLISHED',color_number_inference=False)
        # All validation and allocation above is local; invalid input commits nothing.
        self._tracks, self._next_id = current, next_id
        self._time,self._frame_index,self._scene,self._shape = float(t),frame_index,scene,(width,height)
        self._seen_frames.add(frame_key)
        return result
