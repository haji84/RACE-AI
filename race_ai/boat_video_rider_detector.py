"""Explicit pinned COCO person parts, separate from boat hulls and numbers.

Same local YOLOX asset, preprocessing, threshold and optional native tiles as
boat detection. A person proposal can include background or equipment and does
not establish a rider, its parent boat, a printed number or model eligibility.
The ordinary boat detector and production factories are unchanged.
"""
from hashlib import sha256
import math

from .boat_video_identity import (
    PinnedBoatDetector, TiledBoatDetector, _box, _nms, _pixels, _require,
)


SCHEMA = 'RACE_AI_RIDER_PART_DETECTIONS_V1'


def decode_yolox_person_regions(output, *, width, height):
    """Decode the pinned head for COCO class0, retaining its raw score scope.

    Fixed .5 objectness*class score and raw full-80 argmax; scores are not
    calibrated identification probabilities. The existing 256/view and 12/NMS
    input resource guards are explicit in metadata, not source polling limits.
    """
    import numpy as np
    _box([0, 0, width, height], width, height)
    _require(type(output) is np.ndarray and output.dtype == np.float32
             and output.shape == (1, 8400, 85) and np.isfinite(output).all()
             and np.all((output[:, :, 4:] >= 0) & (output[:, :, 4:] <= 1)))
    scale = min(640/width, 640/height)
    rw, rh = max(1, int(width*scale)), max(1, int(height*scale))
    values = output[0]
    scores = values[:, 4] * values[:, 5]
    selected = np.flatnonzero((values[:, 5:].argmax(axis=1) == 0) & (scores >= .5))
    proposed = []
    for i in selected[np.argsort(-scores[selected], kind='stable')[:256]]:
        if i < 6400:
            stride, side, j = 8, 80, int(i)
        elif i < 8000:
            stride, side, j = 16, 40, int(i)-6400
        else:
            stride, side, j = 32, 20, int(i)-8000
        dx, dy, logw, logh = map(float, values[i, :4])
        _require(abs(logw) <= 32 and abs(logh) <= 32)
        cx, cy = (dx+j % side)*stride, (dy+j//side)*stride
        bw, bh = math.exp(logw)*stride, math.exp(logh)*stride
        x1, y1 = max(0., (cx-bw/2)*width/rw), max(0., (cy-bh/2)*height/rh)
        x2, y2 = min(float(width), (cx+bw/2)*width/rw), min(float(height), (cy+bh/2)*height/rh)
        if x2-x1 >= 1 and y2-y1 >= 1:
            proposed.append({'box': [x1, y1, x2-x1, y2-y1], 'score': float(scores[i])})
    return _nms(proposed)


class PinnedRiderPartDetector:
    """CPU local inference; no download, GT crop, colour or number inference."""
    def __init__(self, *, model_path, tiled=True):
        _require(type(tiled) is bool, 'explicit bool tiling flag required')
        self._model = PinnedBoatDetector(model_path=model_path, detector_kind='yolox')
        self._tiled = tiled

    def metadata(self):
        result = self._model.metadata()
        result.update(class_scope='GENERIC_COCO_PERSON_PART_CANDIDATE',
                      coco_class_id=0, score_scope='RAW_OBJECTNESS_TIMES_CLASS_NOT_ID_PROBABILITY',
                      score_threshold=.5, raw_argmax_class_required=True,
                      max_selected_proposals_per_view=256, max_candidates=12,
                      identity_validated=False, parent_boat_established=False,
                      model_eligible=False)
        if self._tiled:
            result['tiling'] = TiledBoatDetector(detector=self._infer).metadata()['tiling']
        return result

    def _infer(self, frame):
        import cv2
        import numpy as np
        width, height = _pixels(frame)
        scale = min(640/width, 640/height)
        rw, rh = max(1, int(width*scale)), max(1, int(height*scale))
        canvas = np.full((640, 640, 3), 114, dtype=np.uint8)
        canvas[:rh, :rw] = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (rw, rh))
        try:
            self._model.net.setInput(cv2.dnn.blobFromImage(canvas))
            outputs = self._model.net.forward(self._model.net.getUnconnectedOutLayersNames())
            _require(len(outputs) == 1)
            return decode_yolox_person_regions(outputs[0], width=width, height=height)
        except cv2.error:
            raise ValueError('local person-part detector inference failed') from None

    def __call__(self, frame):
        _pixels(frame)
        digest = sha256(frame.tobytes()).hexdigest()
        if self._tiled:
            rows = TiledBoatDetector(detector=self._infer)(frame.copy())
        else:
            rows = self._infer(frame.copy())
        return dict(schema_version=SCHEMA, frame_sha256=digest,
                    coordinate_space='IMAGE_PX', semantic_type='RIDER_PART_TYPED',
                    detections=[dict(row, semantic_type='RIDER_PART_TYPED', coco_class_id=0)
                                for row in rows], engine=self.metadata(),
                    identity_validated=False, model_eligible=False)
