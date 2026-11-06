"""Optional localized raw CRNN candidates; no calibrated identity probabilities.

The ordinary Tesseract factory and its confidence gate are unchanged. This
explicit experimental path uses the full published EN36 vocabulary plus blank,
actual grayscale pixels and existing geometric/three-frame association. Its
sequence likelihood is NOT accuracy, Tesseract confidence, or field validation.

CRNN preprocessing/decoder adapts OpenCV Zoo (Apache-2.0), copyright 2021
Shenzhen Institute of Artificial Intelligence and Robotics for Society. Only
an explicit, hash-pinned local FP32 asset is loaded; no download is performed.
"""
from copy import deepcopy
import hashlib
import math
import time

from .boat_video_identity import (
    BoatIdentityProvider, LocalOCRInferenceError, PinnedBoatDetector, CAMERA_IDENTITY_POLICY,
    identify_with_camera_evidence, _box, _finite, _intersects,
    _iou, _local_file, _pixels, _require,
)

MODEL_NAME = 'text_recognition_CRNN_EN_2021sep.onnx'
MODEL_BYTES = 33823087
MODEL_SHA256 = 'a84b1f6e11a65c2d733cb0cc1f014aae3f99051e3f11447dc282faa678eee544'
CHARSET = '0123456789abcdefghijklmnopqrstuvwxyz'
READING_SCHEMA = 'RACE_AI_RAW_CTC_NUMBER_READING_V1'
SCORE_SCOPE = 'UNCALIBRATED_FULL_VOCABULARY_CTC_SEQUENCE_LIKELIHOOD_NOT_ACCURACY'
ADMISSION_POLICY = 'RAW_CTC_LOCALIZED_SINGLE_DIGIT_GEOMETRY_AND_TEMPORAL_CANDIDATE_V1'


def single_ctc_likelihood(probabilities, symbol):
    """Sum ALL blank/one-symbol CTC paths; no digit-only renormalization."""
    _require(type(probabilities) is list and 1 <= len(probabilities) <= 512,
             'bounded full-vocabulary CTC rows required')
    _require(type(symbol) is int and 1 <= symbol <= 36, 'valid CTC symbol required')
    before, emitting, after = 1., 0., 0.
    for row in probabilities:
        _require(type(row) is list and len(row) == 37 and
                 all(_finite(p) and 0 <= p <= 1 for p in row) and
                 abs(math.fsum(row)-1.) <= 1e-9, 'normalized full-vocabulary rows required')
        blank, char = row[0], row[symbol]
        before, emitting, after = before*blank, (before+emitting)*char, (emitting+after)*blank
    return min(1., max(0., emitting+after))


def decode_ctc_logits(logits):
    """Stock EN36 greedy CTC text and uncalibrated exact one-symbol likelihood."""
    _require(type(logits) is list and 1 <= len(logits) <= 512,
             'bounded full-vocabulary CTC logits required')
    probabilities, symbols = [], []
    normalized = log_normalized = True
    for row in logits:
        _require(type(row) is list and len(row) == 37 and all(_finite(x) for x in row),
                 'finite full-vocabulary CTC logits required')
        normalized &= all(0 <= x <= 1 for x in row) and abs(math.fsum(row)-1.) <= 1e-6
        log_normalized &= all(x <= 0 for x in row) and abs(math.fsum(math.exp(x) for x in row)-1.) <= 1e-6
        maximum = max(row)
        exp = [math.exp(x-maximum) for x in row]
        total = math.fsum(exp)
        probabilities.append([x/total for x in exp])
        symbols.append(max(range(37), key=lambda i: row[i]))
    _require(not normalized and not log_normalized, 'verified logits required, not normalized outputs')
    text = ''.join(CHARSET[value-1] for i, value in enumerate(symbols)
                   if value and (not i or value != symbols[i-1]))
    likelihood = single_ctc_likelihood(probabilities, CHARSET.index(text)+1) if len(text) == 1 else None
    return text, likelihood


def candidate_regions(crop):
    """Fixed development v2 Otsu/MSER geometry, never OCR an isolated mask."""
    import cv2
    import numpy as np
    _pixels(crop)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    proposals, seen = [], set()

    def add(x, y, w, h, mask, source):
        if (x, y, w, h) in seen or h < max(10, .1*height) or h > .8*height:
            return
        if w < 3 or not .13 <= w/h <= 1.6:
            return
        fill = float(np.count_nonzero(mask))/max(1, w*h)
        if not .08 <= fill <= .9 or y+h*.5 < .4*height:
            return
        if x < 1 or y < 1 or x+w >= width-1 or y+h >= height-1:
            return
        seen.add((x, y, w, h))
        score = h*(.6+.4*(y+h*.5)/height)*min(fill/.3, 1.)
        proposals.append(dict(box=[int(x), int(y), int(x+w), int(y+h)], score=float(score),
                              source=source, mask=mask))

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    for plane, source in ((binary, 'otsu_bright'), (255-binary, 'otsu_dark')):
        count, labels, stats, _ = cv2.connectedComponentsWithStats(plane, 8)
        for i in range(1, count):
            x, y, w, h, _ = stats[i]
            add(x, y, w, h, np.uint8(labels[y:y+h, x:x+w] == i)*255, source)
    mser = cv2.MSER_create()
    mser.setMinArea(12)
    mser.setMaxArea(max(13, int(width*height*.30)))
    for plane, source in ((gray, 'mser_dark'), (255-gray, 'mser_bright')):
        regions, boxes = mser.detectRegions(plane)
        for region, (x, y, w, h) in zip(regions, boxes):
            mask = np.zeros((h, w), np.uint8)
            mask[region[:, 1]-y, region[:, 0]-x] = 255
            add(x, y, w, h, mask, source)
    selected = []
    for item in sorted(proposals, key=lambda row: (-row['score'], row['box'], row['source'])):
        x, y, xx, yy = item['box']
        box = [x, y, xx-x, yy-y]
        if any(_iou(box, [old['box'][0], old['box'][1], old['box'][2]-old['box'][0],
                          old['box'][3]-old['box'][1]]) > .5 for old in selected):
            continue
        selected.append(item)
        if len(selected) == 4:
            break
    return selected


def normalize_region(mask, deslant, source_gray):
    """Moment shear comes from segmentation; OCR pixels come from original gray."""
    import cv2
    import numpy as np
    _require(type(mask) is np.ndarray and type(source_gray) is np.ndarray and
             mask.dtype == source_gray.dtype == np.uint8 and mask.ndim == source_gray.ndim == 2 and
             mask.shape == source_gray.shape and min(mask.shape) >= 1 and type(deslant) is bool,
             'bounded actual grayscale region required')
    height, width = mask.shape
    _require(height <= 1080 and width <= 1920, 'bounded actual grayscale region required')
    mask_canvas = np.zeros((height+4, width+max(4, height)), np.uint8)
    offset = (mask_canvas.shape[1]-width)//2
    mask_canvas[2:2+height, offset:offset+width] = mask
    border = np.r_[source_gray[0, :], source_gray[-1, :], source_gray[:, 0], source_gray[:, -1]]
    inverted = bool(np.median(border) < 127)
    canvas = np.full(mask_canvas.shape, 255, np.uint8)
    canvas[2:2+height, offset:offset+width] = 255-source_gray if inverted else source_gray
    shear = 0.
    if deslant:
        moments = cv2.moments(mask_canvas)
        if abs(moments['mu02']) > 1e-6:
            shear = float(np.clip(moments['mu11']/moments['mu02'], -1, 1))
            matrix = np.float32([[1, shear, -.5*canvas.shape[0]*shear], [0, 1, 0]])
            canvas = cv2.warpAffine(canvas, matrix, (canvas.shape[1], canvas.shape[0]),
                                    flags=cv2.WARP_INVERSE_MAP | cv2.INTER_CUBIC, borderValue=255)
    scale = min(6., 96/canvas.shape[0])
    result = cv2.resize(canvas, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    padding = max(12, round(result.shape[0]*.25))
    result = cv2.copyMakeBorder(result, padding, padding, padding, padding,
                               cv2.BORDER_CONSTANT, value=255)
    return result, dict(shear=shear, normalization_scale=scale, white_padding=padding,
                        segmentation_isolated_mask=False, actual_grayscale_pixels_preserved=True,
                        polarity_inverted_by_source_border_median=inverted)


def prepare_crnn_blob(image):
    """Use the published100x32 perspective warp, BGR grayscale and normalization."""
    import cv2
    import numpy as np
    _require(type(image) is np.ndarray and image.dtype == np.uint8 and image.ndim in (2, 3),
             'uint8 local OCR pixels required')
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    width, height = _pixels(image)
    _require(min(width, height) >= 2, 'nondegenerate local OCR pixels required')
    source = np.float32([[0, height-1], [0, 0], [width-1, 0], [width-1, height-1]])
    target = np.float32([[0, 31], [0, 0], [99, 0], [99, 31]])
    warped = cv2.warpPerspective(image, cv2.getPerspectiveTransform(source, target), (100, 32))
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    return cv2.dnn.blobFromImage(gray, size=(100, 32), mean=127.5, scalefactor=1/127.5)


def read_number_regions(crop, *, infer, soft_budget_seconds=3., monotonic=time.monotonic):
    """Retain all attempts, including native-call overruns; never promise a hard cap.

    A whole-hull view is diagnostic only. Only automatic localized region views
    can propose a mark. The caller is responsible for pinning the supplied infer
    dependency; this pure orchestration function itself makes no engine claim.
    """
    import cv2
    _pixels(crop)
    _require(callable(infer) and callable(monotonic) and _finite(soft_budget_seconds) and
             0 < soft_budget_seconds <= 3, 'bounded raw CTC inference required')
    start = monotonic()
    deadline = start+soft_budget_seconds
    result = dict(schema_version=READING_SCHEMA, proposals=[], attempts=[], status='COMPLETE',
                  soft_budget_seconds=float(soft_budget_seconds), soft_budget_exceeded=False,
                  skipped_views=0, score_scope=SCORE_SCOPE, accepted_identity=False,
                  hard_deadline_guaranteed=False)
    try:
        regions = candidate_regions(crop)
        _require(type(regions) is list and len(regions) <= 4, 'bounded actual pixel regions required')
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        views = [(crop, None, 'WHOLE_HULL_DIAGNOSTIC')]
        for region in regions:
            x, y, xx, yy = region['box']
            _box([x, y, xx-x, yy-y], crop.shape[1], crop.shape[0])
            for deslant in (False, True):
                view, _ = normalize_region(region['mask'], deslant, gray[y:yy, x:xx])
                views.append((view, [x, y, xx-x, yy-y], 'REGION_DESLANT' if deslant else 'REGION_PADDED'))
    except Exception:
        result.update(status='INFERENCE_ERROR')
        result['attempts'].append(dict(status='ERROR', stage='SEGMENTATION', error_code='LOCAL_REGION_EXTRACTION_FAILED'))
        return result
    for view, box, kind in views:
        before = monotonic()
        if before >= deadline:
            result['skipped_views'] += 1
            result['attempts'].append(dict(kind=kind, box=box, status='NOT_RUN_SOFT_BUDGET_EXHAUSTED', seconds=0.))
            result.update(status='INCOMPLETE_BUDGET', soft_budget_exceeded=True)
            continue
        try:
            text, likelihood = infer(view)
            _require(type(text) is str and len(text) <= 512 and
                     (likelihood is None or _finite(likelihood) and 0 <= likelihood <= 1),
                     'invalid raw CTC output')
            if len(text) == 1:
                _require(text in CHARSET and likelihood is not None, 'invalid raw CTC output')
            else:
                _require(likelihood is None, 'invalid raw CTC output')
            completed = monotonic()
            _require(_finite(completed) and completed >= before >= start, 'invalid local OCR clock')
            overrun = completed > deadline
            result['attempts'].append(dict(kind=kind, box=box, status='OK', text=text,
                sequence_likelihood=likelihood, seconds=completed-before, soft_budget_exceeded=overrun))
            if box is not None and text in ('1', '2', '3', '4', '5', '6'):
                result['proposals'].append(dict(text=text, sequence_likelihood=likelihood, box=box))
            if overrun:
                result.update(status='INCOMPLETE_BUDGET', soft_budget_exceeded=True)
        except Exception:
            result.update(status='INFERENCE_ERROR')
            result['attempts'].append(dict(kind=kind, box=box, status='ERROR', error_code='LOCAL_CTC_INFERENCE_FAILED'))
            # No subsequent views can hide a failed view or recover completeness.
            break
    return result


class PinnedCRNNNumberReader:
    """Actual local FP32 inference, explicit paths only, unchanged full vocabulary."""
    def __init__(self, *, model_path, soft_budget_seconds=3., diagnostic_callback=None):
        _require(diagnostic_callback is None or callable(diagnostic_callback),
                 'optional diagnostic observer must be callable')
        _, raw = _local_file(model_path, max_bytes=MODEL_BYTES)
        _require(len(raw) == MODEL_BYTES and hashlib.sha256(raw).hexdigest() == MODEL_SHA256,
                 'local CRNN model integrity check failed')
        _require(_finite(soft_budget_seconds) and 0 < soft_budget_seconds <= 3,
                 'bounded raw CTC inference required')
        import cv2
        import numpy as np
        try:
            self._net = cv2.dnn.readNetFromONNX(np.frombuffer(raw, dtype=np.uint8))
            self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except cv2.error:
            raise ValueError('local CRNN runtime is unavailable') from None
        self.soft_budget_seconds, self.cv_version = float(soft_budget_seconds), cv2.__version__
        self.diagnostic_callback = diagnostic_callback

    def metadata(self):
        return dict(engine='OPENCV_CRNN_FP32_LOCAL', model_name=MODEL_NAME, model_sha256=MODEL_SHA256,
                    opencv_version=self.cv_version, license='Apache-2.0', full_vocabulary_classes=37,
                    score_scope=SCORE_SCOPE, soft_budget_seconds=self.soft_budget_seconds,
                    hard_deadline_guaranteed=False, calibrated_identification_probability=False,
                    actual_grayscale_pixels_preserved=True)

    def _infer(self, view):
        import numpy as np
        self._net.setInput(prepare_crnn_blob(view))
        output = self._net.forward()
        _require(type(output) is np.ndarray and output.dtype == np.float32 and output.ndim == 3 and
                 1 <= output.shape[0] <= 512 and output.shape[1:] == (1, 37) and np.isfinite(output).all(),
                 'invalid full-vocabulary CRNN network output')
        return decode_ctc_logits(output[:, 0, :].astype(np.float64).tolist())

    def __call__(self, crop):
        reading = read_number_regions(crop, infer=self._infer, soft_budget_seconds=self.soft_budget_seconds)
        if self.diagnostic_callback is not None:
            try:
                self.diagnostic_callback(deepcopy(reading))
            except Exception:
                # An observer failure aborts explicitly; it cannot silently
                # change admission or reveal caller-specific exception text.
                raise ValueError('local CRNN diagnostic observer failed') from None
        return reading


class ExperimentalCRNNIdentityProvider(BoatIdentityProvider):
    """Explicit uncalibrated admission policy; unchanged temporal/geometry gates.

    The base tracker's private aggregation slot named ``confidence`` carries the
    ACTUAL likelihood solely for code reuse. Every emitted evidence dictionary
    renames it, declares its scope, and never exposes it as confidence. Raw reader
    envelopes cannot be accidentally consumed by the legacy Tesseract contract.
    """
    def metadata(self):
        result = super().metadata()
        result['number_reader'] = (self.number_reader.metadata()
            if type(self.number_reader) is PinnedCRNNNumberReader else dict(engine='INJECTED_RAW_CTC_READER'))
        result.update(identity_admission_policy=ADMISSION_POLICY, score_scope=SCORE_SCOPE,
                      camera_gap_identity_policy=CAMERA_IDENTITY_POLICY,
                      metric_camera_compensation_inferred_from_identity=False,
                      calibrated_identification_probability=False)
        return result

    def identify_with_camera_status(self, frame, detections, *, t, frame_index, scene,
                                    camera_status, previous_to_current=None):
        """Explicit fresh-identity opt-in; never infer missing camera geometry."""
        return identify_with_camera_evidence(self, frame, detections, t=t, frame_index=frame_index,
            scene=scene, camera_status=camera_status, previous_to_current=previous_to_current)

    def _number(self, frame, hull, overlays):
        x, y, width, height = hull
        left, top, right, bottom = math.floor(x), math.floor(y), math.ceil(x+width), math.ceil(y+height)
        reading = self.number_reader(frame[top:bottom, left:right].copy())
        _require(type(reading) is dict and reading.get('schema_version') == READING_SCHEMA and
                 reading.get('score_scope') == SCORE_SCOPE and reading.get('accepted_identity') is False,
                 'explicit raw CTC reading envelope required')
        status = reading.get('status')
        if status == 'INCOMPLETE_BUDGET':
            raise LocalOCRInferenceError('TIMEOUT')
        if status == 'INFERENCE_ERROR':
            raise LocalOCRInferenceError('PROCESS_FAILED')
        _require(status == 'COMPLETE' and reading.get('soft_budget_exceeded') is False and
                 reading.get('skipped_views') == 0, 'complete raw CTC reading required')
        rows = reading.get('proposals')
        _require(type(rows) is list and len(rows) <= 8, 'bounded localized CTC proposals required')
        found = []
        for row in rows:
            if not (type(row) is dict and set(row) <= {'text', 'sequence_likelihood', 'box', 'localized'} and
                    row.get('localized', True) is True and row.get('text') in ('1', '2', '3', '4', '5', '6') and
                    _finite(row.get('sequence_likelihood')) and 0 < row['sequence_likelihood'] <= 1):
                continue
            try:
                px, py, w, h = _box(row.get('box'), right-left, bottom-top)
            except ValueError:
                continue
            box = [left+px, top+py, w, h]
            if not (x <= box[0] and y <= box[1] and box[0]+w <= x+width and box[1]+h <= y+height):
                continue
            if any(_intersects(box, overlay) for overlay in overlays):
                continue
            duplicate = next((old for old in found if old['number'] == int(row['text']) and _iou(old['box'], box) >= .5), None)
            if duplicate is not None:
                # Duplicate views are one hypothesis, not independent observations.
                duplicate['confidence'] = max(duplicate['confidence'], float(row['sequence_likelihood']))
                continue
            found.append(dict(number=int(row['text']), confidence=float(row['sequence_likelihood']), box=box))
        return (found[0], False) if len(found) == 1 else (None, len(found) > 1)

    def identify(self, *args, **kwargs):
        result = super().identify(*args, **kwargs)
        for region in result['regions']:
            evidence = region['number_evidence']
            evidence['minimum_sequence_likelihood'] = evidence.pop('minimum_confidence')
            evidence.update(score_scope=SCORE_SCOPE, admission_policy=ADMISSION_POLICY,
                            source='RAW_CTC_LOCALIZED_REGION_TEMPORAL_CANDIDATE')
        result['identity_admission_policy'] = ADMISSION_POLICY
        result['score_scope'] = SCORE_SCOPE
        result['quality_flags'] = sorted(set(result['quality_flags']) | {'RAW_CTC_LIKELIHOOD_IS_NOT_ACCURACY'})
        return result


def create_crnn_identity_provider(*, model_path, crnn_model_path, detector_kind='yolox',
        tiled_hulls=False, exclusions=(), min_observations=3, max_gap_seconds=.5,
        soft_budget_seconds=3.):
    """Explicit optional engine path; no Tesseract policy/default is replaced."""
    _require(type(tiled_hulls) is bool, 'tiled_hulls must be an explicit boolean')
    detector = PinnedBoatDetector(model_path=model_path, detector_kind=detector_kind)
    if tiled_hulls:
        from .boat_video_identity import TiledBoatDetector
        detector = TiledBoatDetector(detector=detector)
    reader = PinnedCRNNNumberReader(model_path=crnn_model_path, soft_budget_seconds=soft_budget_seconds)
    return ExperimentalCRNNIdentityProvider(detector=detector, number_reader=reader,
        exclusions=exclusions, min_observations=min_observations, max_gap_seconds=max_gap_seconds)


def make_crnn_identity_extractor(*, model_path, crnn_model_path, detector_kind='yolox',
        tiled_hulls=False, exclusions=(), min_observations=3, max_gap_seconds=.5,
        soft_budget_seconds=3.):
    """Delay local asset loading; each media receives fresh temporal state."""
    excluded = deepcopy(exclusions)

    def extract(path, *, options=None):
        provider = create_crnn_identity_provider(model_path=model_path, crnn_model_path=crnn_model_path,
            detector_kind=detector_kind, tiled_hulls=tiled_hulls, exclusions=deepcopy(excluded),
            min_observations=min_observations, max_gap_seconds=max_gap_seconds,
            soft_budget_seconds=soft_budget_seconds)
        from .boat_video_tracking import extract_tracks
        return extract_tracks(path, options=options, identity_provider=provider)

    return extract
