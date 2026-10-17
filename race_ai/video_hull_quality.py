"""Offline hull/digit error counts from complete, separately reviewed labels.

Review times, identities and hashes are supplied evidence, not authentication.
This processor performs no I/O and never approves a detector or a forecast.
"""
from collections import Counter
from datetime import datetime
from functools import lru_cache
import hashlib
import math
import re

from .core import SourceError
from web.race_contract import canonical


def _require(condition):
    if not condition:
        raise SourceError('VIDEO_HULL_LABEL_CONTRACT_INVALID')


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _keys(value, expected):
    _require(type(value) is dict and set(value) == set(expected.split()))


def _sha(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None)


def _identifier(value):
    _require(type(value) is str and re.fullmatch('[A-Za-z0-9_-]{1,64}', value) is not None)


def _race(value):
    _require(type(value) is str and re.fullmatch(r'20[0-9]{6}-[0-9]{2}-[0-9]{2}', value) is not None)
    try:
        datetime.strptime(value[:8], '%Y%m%d')
    except ValueError:
        _require(False)
    _require(1 <= int(value[9:11]) <= 24 and 1 <= int(value[12:]) <= 12)


def _time(value):
    _require(type(value) is str and len(value) <= 40
             and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value) is not None)
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(result.utcoffset() is not None)
        return result
    except ValueError:
        _require(False)


def _box(value, width, height):
    _require(type(value) is list and len(value) == 4 and all(_finite(n) for n in value))
    x, y, w, h = value
    _require(w >= 1 and h >= 1 and 0 <= x < x+w <= width and 0 <= y < y+h <= height)
    return tuple(float(n) for n in value)


def _inside(inner, outer):
    x, y, w, h = inner; a, b, c, d = outer
    return a <= x and b <= y and x+w <= a+c and y+h <= b+d


def _overlap(a, b):
    return (a[0] < b[0]+b[2] and b[0] < a[0]+a[2]
            and a[1] < b[1]+b[3] and b[1] < a[1]+a[3])


def _iou(a, b):
    area = max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0])) * max(
        0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))
    return area / (a[2]*a[3]+b[2]*b[3]-area)


def _objects(rows, width, height, *, truth, overlays):
    _require(type(rows) is list and len(rows) <= (6 if truth else 12))
    id_key = 'hull_id' if truth else 'candidate_id'
    result = []
    for row in rows:
        _keys(row, id_key+' box number number_box'); _identifier(row[id_key])
        box = _box(row['box'], width, height)
        number = row['number']
        _require(number is None or (type(number) is int and 1 <= number <= 6))
        _require((number is None) == (row['number_box'] is None))
        digit = _box(row['number_box'], width, height) if number is not None else None
        if truth and digit is not None:
            _require(_inside(digit, box) and not any(_overlap(digit, b) for b in overlays))
        result.append(dict(id=row[id_key], box=box, number=number, digit=digit))
    _require(len({r['id'] for r in result}) == len(result))
    if truth:
        numbers = [r['number'] for r in result if r['number'] is not None]
        _require(len(set(numbers)) == len(numbers))
    return sorted(result, key=lambda r: r['id'])


def _labels(pack):
    _keys(pack, 'schema_version race_id media_sha256 program_identity_sha256 split observer_id frozen_at frames')
    _require(pack['schema_version'] == 'hull-number-labels/v1')
    _race(pack['race_id']); _sha(pack['media_sha256']); _sha(pack['program_identity_sha256'])
    _require(pack['split'] in ('DEVELOPMENT', 'HELD_OUT'))
    _identifier(pack['observer_id']); _time(pack['frozen_at'])
    _require(type(pack['frames']) is list and 1 <= len(pack['frames']) <= 400)
    result = []; previous = -1; hashes = set()
    for frame in pack['frames']:
        _keys(frame, 'frame_id frame_sha256 width height scene_id kind exhaustive hulls overlays')
        index = frame['frame_id']; width, height = frame['width'], frame['height']
        _require(type(index) is int and previous < index <= 20000); previous = index
        _sha(frame['frame_sha256']); _require(frame['frame_sha256'] not in hashes)
        hashes.add(frame['frame_sha256']); _identifier(frame['scene_id'])
        _require(type(width) is int and type(height) is int and 0 < width <= 1280 and 0 < height <= 720)
        _require(frame['kind'] in ('MOVING_EXHIBITION', 'NON_MEASUREMENT') and frame['exhaustive'] is True)
        _require(type(frame['overlays']) is list and len(frame['overlays']) <= 32)
        overlays = [_box(b, width, height) for b in frame['overlays']]
        hulls = _objects(frame['hulls'], width, height, truth=True, overlays=overlays)
        _require(frame['kind'] != 'NON_MEASUREMENT' or not hulls)
        result.append(dict(source=frame, hulls=hulls, overlays=overlays))
    return result


def _matching(hulls, predictions):
    """Maximum cardinality, then total IoU, then stable ID order; no greedy loss."""
    edges = [[_iou(p['box'], h['box']) for h in hulls] for p in predictions]

    @lru_cache(None)
    def solve(index, used):
        if index == len(predictions):
            return (0, 0., ())
        best = solve(index+1, used)
        for j, overlap in enumerate(edges[index]):
            if used & (1 << j) or overlap < .5:
                continue
            count, total, pairs = solve(index+1, used | (1 << j))
            candidate = count+1, total+overlap, ((index, j),)+pairs
            if (candidate[:2] > best[:2]
                    or (candidate[:2] == best[:2] and candidate[2] < best[2])):
                best = candidate
        return best

    return [(i, j, edges[i][j]) for i, j in solve(0, 0)[2]]


def evaluate_hull_labels(reference, independent_reference, predictions):
    """Count a frozen finite dataset; declared reviewers/splits are not certified."""
    frames = _labels(reference); _labels(independent_reference)
    _require(reference['observer_id'] != independent_reference['observer_id'])
    for key in ('race_id', 'media_sha256', 'program_identity_sha256', 'split', 'frames'):
        _require(canonical(reference[key]) == canonical(independent_reference[key]))
    _keys(predictions, 'schema_version race_id media_sha256 program_identity_sha256 split model_sha256 revealed_at frames')
    _require(predictions['schema_version'] == 'hull-number-candidates/v1'); _sha(predictions['model_sha256'])
    for key in ('race_id', 'media_sha256', 'program_identity_sha256', 'split'):
        _require(predictions[key] == reference[key])
    disclosed = _time(predictions['revealed_at'])
    _require(disclosed > max(_time(reference['frozen_at']), _time(independent_reference['frozen_at'])))
    _require(type(predictions['frames']) is list and len(predictions['frames']) == len(frames))
    totals = dict(tp=0, fp=0, fn=0)
    numbers = dict(correct=0, incorrect=0, missed=0, unverifiable=0); outputs = []
    for label, frame in zip(frames, predictions['frames']):
        _keys(frame, 'frame_id frame_sha256 candidates')
        source = label['source']
        _require(type(frame['frame_id']) is int and frame['frame_id'] == source['frame_id']
                 and frame['frame_sha256'] == source['frame_sha256'])
        candidates = _objects(frame['candidates'], source['width'], source['height'], truth=False, overlays=[])
        hulls = label['hulls']; pairs = _matching(hulls, candidates)
        matched = {i: j for i, j, _ in pairs}
        duplicates = Counter(c['number'] for c in candidates if c['number'] is not None)
        correct = set(); digit_results = []
        for i, candidate in enumerate(candidates):
            if candidate['number'] is None:
                continue
            j = matched.get(i); truth = hulls[j] if j is not None else None
            if (truth is None or duplicates[candidate['number']] > 1
                    or not _inside(candidate['digit'], candidate['box'])
                    or not _inside(candidate['digit'], truth['box'])
                    or any(_overlap(candidate['digit'], b) for b in label['overlays'])):
                status = 'incorrect'
            elif truth['number'] is None:
                status = 'unverifiable'
            elif candidate['number'] == truth['number'] and _iou(candidate['digit'], truth['digit']) >= .5:
                status = 'correct'; correct.add(j)
            else:
                status = 'incorrect'
            numbers[status] += 1
            digit_results.append(dict(candidate_id=candidate['id'], status=status))
        numbers['missed'] += sum(h['number'] is not None and j not in correct for j, h in enumerate(hulls))
        counts = dict(tp=len(pairs), fp=len(candidates)-len(pairs), fn=len(hulls)-len(pairs))
        for key in totals:
            totals[key] += counts[key]
        outputs.append(dict(frame_id=source['frame_id'], frame_sha256=source['frame_sha256'],
            kind=source['kind'], **counts, matches=[dict(candidate_id=candidates[i]['id'],
                hull_id=hulls[j]['id'], iou=overlap) for i, j, overlap in pairs], numbers=digit_results))
    result = dict(schema_version='hull-number-quality/v1', race_id=reference['race_id'],
        media_sha256=reference['media_sha256'], program_identity_sha256=reference['program_identity_sha256'],
        declared_split=reference['split'], model_sha256=predictions['model_sha256'],
        reference_sha256=hashlib.sha256(canonical(reference)).hexdigest(),
        independent_reference_sha256=hashlib.sha256(canonical(independent_reference)).hexdigest(),
        predictions_sha256=hashlib.sha256(canonical(predictions)).hexdigest(),
        frames=outputs, hulls=totals, numbers=numbers, iou_threshold=.5,
        evaluation_scope='SUPPLIED_EXHAUSTIVE_FRAME_LABELS_ONLY_NOT_POPULATION_ACCURACY',
        observer_clock_and_split_authentication='NOT_ESTABLISHED_BY_THIS_CALCULATION',
        automated_verified_hull_ids=0, prediction_eligible=False, boat_features=[])
    result['snapshot_id'] = hashlib.sha256(canonical(result)).hexdigest()
    return result
