"""Complete opt-in discovery of printed-character candidates in original pixels.

Component crops are not semantic text lines: a partial crop reading ``12`` does
not establish a parent equipment label, nor does reading ``2`` prove a boat ID.
This envelope deliberately retains every attempt separately from association.
It performs no download, deadline truncation, color identity or world inference.
"""
from collections import defaultdict
from hashlib import sha256

from .boat_video_crnn import all_candidate_regions, CHARSET, SCORE_SCOPE
from .boat_video_identity import _box, _finite, _iou, _pixels, _require


SCHEMA = 'RACE_AI_BOAT_MARKER_CANDIDATE_READING_V1'


def marker_regions(frame):
    """Fixed 128-pixel bands, half overlap, complete original component rules.

    Global NMS uses the same IoU/order as the frozen full-candidate experiment.
    Spatial buckets only avoid comparisons of nonintersecting rectangles.
    No top-K component limit is applied at either stage.
    """
    width, height = _pixels(frame)
    band_height = min(128, height)
    origins = list(range(0, height-band_height+1, 64))
    if origins[-1] != height-band_height:
        origins.append(height-band_height)
    proposals = []
    for origin in origins:
        for rank, row in enumerate(all_candidate_regions(frame[origin:origin+band_height].copy()), 1):
            x, y, xx, yy = row['box']
            proposals.append(dict(box=[x, y+origin, xx, yy+origin],
                source=row['source'], score=row['score'], band_origin_y=origin, band_rank=rank))
    selected, buckets = [], defaultdict(set)
    for row in sorted(proposals, key=lambda r:(-r['score'], r['box'], r['source'], r['band_origin_y'])):
        x, y, xx, yy = row['box']
        cells = [(a,b) for a in range(x//128, xx//128+1) for b in range(y//128, yy//128+1)]
        nearby = set().union(*(buckets[c] for c in cells))
        box = [x,y,xx-x,yy-y]
        if any(_iou(box, [selected[i]['box'][0], selected[i]['box'][1],
                selected[i]['box'][2]-selected[i]['box'][0],
                selected[i]['box'][3]-selected[i]['box'][1]]) > .5 for i in nearby):
            continue
        for cell in cells:
            buckets[cell].add(len(selected))
        selected.append(row)
    return selected


def read_marker_candidates(frame, *, infer):
    """Read all automatically localized original gray crops exactly once.

    ``infer`` is the explicit pinned full-vocabulary CRNN native inference
    dependency. Injected callbacks make no engine, provenance or accuracy claim.
    A failed native call stops with an explicit unread count, never COMPLETE.
    Multichar readings are preserved whole and cannot become digit substrings.
    """
    import cv2
    width, height = _pixels(frame)
    _require(callable(infer), 'explicit native inference dependency required')
    regions = marker_regions(frame)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    result = dict(schema_version=SCHEMA, frame_sha256=sha256(frame.tobytes()).hexdigest(),
        coordinate_space='IMAGE_PX', status='COMPLETE', total_candidates=len(regions),
        completed_candidates=0, unread_candidates=len(regions), readings=[],
        score_scope=SCORE_SCOPE, identity_validated=False, model_eligible=False,
        calibrated_identification_probability=False, engine='EXPLICIT_INFERENCE_DEPENDENCY',
        hull_context_established=False)
    for index, region in enumerate(regions):
        x, y, xx, yy = region['box']
        _box([x,y,xx-x,yy-y], width, height)
        crop = gray[y:yy,x:xx].copy()
        input_sha = sha256(crop.tobytes()).hexdigest()
        input_shape = list(crop.shape)
        try:
            text, likelihood = infer(crop)
            _require(type(text) is str and len(text) <= 512 and
                all(c in CHARSET for c in text), 'invalid full-vocabulary CTC text')
            _require(likelihood is None or _finite(likelihood) and 0 <= likelihood <= 1,
                'invalid raw CTC likelihood')
            _require((likelihood is not None) == (len(text)==1), 'full single-symbol score required')
            _require(list(crop.shape)==input_shape and sha256(crop.tobytes()).hexdigest()==input_sha,
                'source inference pixels were mutated')
        except Exception:
            result.update(status='INFERENCE_ERROR', error_code='NATIVE_RECOGNITION_FAILED',
                          failed_candidate_index=index)
            break
        result['readings'].append(dict(box=[x,y,xx-x,yy-y], text=text,
            sequence_likelihood=float(likelihood) if likelihood is not None else None,
            input_sha256=input_sha, input_shape=input_shape,
            source_kind='MSER_OR_CONNECTED_COMPONENT', semantic_parent_evidence=False,
            region_source=region['source'], band_origin_y=region['band_origin_y']))
        result['completed_candidates'] += 1
        result['unread_candidates'] -= 1
    return result


class PinnedMarkerCandidateReader:
    """Explicit local pinned CRNN; preserves the ordinary four-crop default."""
    def __init__(self, *, model_path):
        from .boat_video_crnn import PinnedCRNNNumberReader
        self._reader = PinnedCRNNNumberReader(model_path=model_path)

    def metadata(self):
        result = self._reader.metadata()
        result.pop('soft_budget_seconds')
        result.update(candidate_policy='COMPLETE_FIXED_128PX_BANDS_NATIVE_V1',
                      identity_validated=False, model_eligible=False)
        return result

    def __call__(self, frame):
        result = read_marker_candidates(frame, infer=self._reader._infer)
        result['engine'] = self.metadata()
        return result
