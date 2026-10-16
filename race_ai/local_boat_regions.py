"""Offline generic vessel candidates and bounded crop OCR, never hull identity.

NanoDet tensor decoding follows OpenCV Zoo's Apache-2.0 reference at
ea593dd89b88d4b3978273a16f0d8cfe93d2e3ea; see models/NANODET_LICENSE.
The exact heads are paired by shape because their output order varies by runtime.
"""
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from .core import SourceError
from .video_number_marks import geometry, assess_marks
from web.race_contract import canonical

MODEL_NAME = 'object_detection_nanodet_2022nov.onnx'
MODEL_SHA256 = '4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186'
MODEL_BYTES = 3800954

def require(value):
    if not value:
        raise SourceError('LOCAL_BOAT_REGION_CONTRACT_INVALID')

def pixels_required(pixels):
    require(type(pixels) is np.ndarray and pixels.dtype == np.uint8 and pixels.ndim == 3
            and pixels.shape[2] == 3 and 0 < pixels.shape[0]*pixels.shape[1] <= 1280*720)

def letterbox(width, height):
    geometry(width, height, [])
    require(width*height <= 1280*720)
    scale = min(416/width, 416/height)
    w, h = max(1, round(width*scale)), max(1, round(height*scale))
    return w, h, (416-w)//2, (416-h)//2

def decode_regions(outputs, *, width, height, exclusions=None):
    """Exact fixed model tensors to image boxes; no body/number verification."""
    masks = geometry(width, height, [] if exclusions is None else exclusions)
    w, h, left, top = letterbox(width, height)
    require(type(outputs) in (list, tuple) and len(outputs) == 6)
    tensors = {}
    for a in outputs:
        require(type(a) is np.ndarray and a.dtype == np.float32 and a.ndim == 3
                and a.shape[0] == 1 and a.shape[1] in (2704,676,169)
                and a.shape[2] in (80,32) and np.isfinite(a).all())
        key = a.shape[1], a.shape[2]
        require(key not in tensors)
        if key[1] == 80:
            require(np.all((a >= 0) & (a <= 1)))
        tensors[key] = a[0]
    require(set(tensors) == {(n,c) for n in (2704,676,169) for c in (80,32)})
    proposed = []
    for stride, side in ((8,52),(16,26),(32,13)):
        scores, distances = tensors[(side*side,80)], tensors[(side*side,32)]
        selected = np.flatnonzero((scores.argmax(axis=1) == 8) & (scores[:,8] >= .5))
        for i in selected[np.argsort(-scores[selected,8],kind='stable')[:256]]:
            logits = distances[i].astype(np.float64).reshape(4,8)
            probabilities = np.exp(logits-logits.max(axis=1,keepdims=True))
            offsets = probabilities @ np.arange(8) / probabilities.sum(axis=1) * stride
            cx, cy = (i%side)*stride+(stride-1)*.5, (i//side)*stride+(stride-1)*.5
            x1, y1 = max(0.,(cx-offsets[0]-left)*width/w), max(0.,(cy-offsets[1]-top)*height/h)
            x2, y2 = min(float(width),(cx+offsets[2]-left)*width/w), min(float(height),(cy+offsets[3]-top)*height/h)
            if x2 <= x1 or y2 <= y1:
                continue
            if any(x1 < a+c and a < x2 and y1 < b+d and b < y2 for a,b,c,d in masks):
                continue
            proposed.append(dict(box=[float(x1),float(y1),float(x2-x1),float(y2-y1)],
                                 confidence=float(scores[i,8])))
    kept = []
    for candidate in sorted(proposed,key=lambda r:-r['confidence']):
        x,y,bw,bh = candidate['box']
        overlap = False
        for old in kept:
            a,b,c,d = old['box']
            intersection = max(0.,min(x+bw,a+c)-max(x,a))*max(0.,min(y+bh,b+d)-max(y,b))
            if intersection/(bw*bh+c*d-intersection) > .5:
                overlap = True; break
        if not overlap:
            kept.append(candidate)
        if len(kept) == 12:
            break
    return dict(schema_version='local-boat-regions/v1',regions=kept,
                class_scope='GENERIC_COCO_BOAT_CANDIDATE',boat_identity='UNVERIFIED',
                world_calibration='UNVERIFIED',prediction_eligible=False,boat_features=[])

class LocalBoatRegions:
    def __init__(self, *, model_path=None):
        try:
            path = Path(model_path) if model_path is not None else Path(__file__).parent/'models'/MODEL_NAME
            require(path.is_file() and path.stat().st_size == MODEL_BYTES)
            raw = path.read_bytes()
            require(len(raw) == MODEL_BYTES and hashlib.sha256(raw).hexdigest() == MODEL_SHA256)
            self.net = cv2.dnn.readNetFromONNX(np.frombuffer(raw,dtype=np.uint8))
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except SourceError:
            raise
        except Exception:
            raise SourceError('LOCAL_BOAT_REGION_RUNTIME_UNAVAILABLE') from None

    def __call__(self, pixels, *, exclusions=None):
        try:
            return self._infer(pixels,exclusions=exclusions)
        except SourceError:
            raise
        except Exception:
            raise SourceError('LOCAL_BOAT_REGION_INFERENCE_FAILED') from None

    def _infer(self, pixels, *, exclusions=None):
        pixels_required(pixels)
        height, width = pixels.shape[:2]
        w,h,left,top = letterbox(width,height)
        canvas = np.zeros((416,416,3),dtype=np.float32)
        canvas[top:top+h,left:left+w] = cv2.resize(pixels,(w,h)).astype(np.float32)
        canvas = (canvas-np.array([103.53,116.28,123.675],np.float32))/np.array([57.375,57.12,58.395],np.float32)
        try:
            self.net.setInput(cv2.dnn.blobFromImage(canvas))
            outputs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        except Exception:
            raise SourceError('LOCAL_BOAT_REGION_INFERENCE_FAILED') from None
        return decode_regions(outputs,width=width,height=height,exclusions=exclusions)

class BoatRegionOCR:
    """Run OCR on copied vessel candidate crops; mappings remain unverified."""
    def __init__(self, *, detector, ocr):
        require(callable(detector) and callable(ocr))
        self.detector,self.ocr,self._last = detector,ocr,None

    @property
    def last_observation(self):
        return json.loads(canonical(self._last))

    def __call__(self, pixels):
        self._last = None
        try:
            return self._observe(pixels)
        except SourceError:
            raise
        except Exception:
            raise SourceError('LOCAL_BOAT_REGION_OCR_FAILED') from None

    def _observe(self, pixels):
        pixels_required(pixels)
        height,width = pixels.shape[:2]
        detected = self.detector(pixels.copy())
        require(type(detected) is dict and type(detected.get('regions')) is list and len(detected['regions']) <= 12)
        checked = []
        for r in detected['regions']:
            require(type(r) is dict and set(r) == {'box','confidence'})
            require(type(r['confidence']) in (int,float) and math.isfinite(r['confidence']) and .5 <= r['confidence'] <= 1)
            masks = geometry(width,height,[r['box']]);x,y,w,h = masks[0]
            require(w >= 1 and h >= 1)
            checked.append(dict(box=[float(x),float(y),float(w),float(h)],confidence=float(r['confidence'])))
        # No callback sees aliases to the validated region collection/evidence.
        rows,regions = [],[]
        for r in checked:
            x,y,w,h = r['box']
            a,b,c,d = math.floor(x),math.floor(y),math.ceil(x+w),math.ceil(y+h)
            crop = pixels[b:d,a:c].copy()
            factor = min(2.,720/crop.shape[0],1280/crop.shape[1])
            cw,ch = max(1,round(crop.shape[1]*factor)),max(1,round(crop.shape[0]*factor))
            resized = cv2.resize(crop,(cw,ch))
            marks = assess_marks(self.ocr(resized),width=cw,height=ch,exclusions=[])
            sx,sy = (c-a)/cw,(d-b)/ch
            starting_count = len(rows)
            for candidate in marks['candidates']:
                px,py,pw,ph = candidate['box']
                x1,y1,x2,y2 = a+px*sx,b+py*sy,a+(px+pw)*sx,b+(py+ph)*sy
                if x1 < x or y1 < y or x2 > x+w or y2 > y+h:
                    continue
                rows.append(dict(text=str(candidate['candidate_number']),score=candidate['confidence'],
                                 box=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]))
            regions.append(dict(box=list(r['box']),confidence=float(r['confidence']),
                                ambiguous_numbers=marks['ambiguous_numbers'],number_candidates=len(rows)-starting_count,
                                crop_candidates_before_roi_filter=len(marks['candidates'])))
        self._last = json.loads(canonical(dict(regions=regions,number_marks=rows,
            boat_identity='UNVERIFIED',prediction_eligible=False,boat_features=[])))
        return rows
