"""Explicit optional DEVELOPMENT marker context/shape classifications only.

These two private local SVM assets derive from Nesnad's Wikimedia Commons
"Kyotei - Sept 7 2021", CC BY-SA 4.0, and synthetic font data. The original
Commons glyphs and weak shore negatives overlap development evaluation. No
Toda samples were trained. Attribution: https://commons.wikimedia.org/wiki/
File:Kyotei_-_Sept_7_2021.webm ; https://creativecommons.org/licenses/by-sa/4.0/ .
No weights are distributed or downloaded here. Class labels are uncalibrated
training similarities, never authenticated boat numbers, probabilities, field
validation or eligibility for forecast models. No default caller is changed.
"""
from hashlib import sha256
import os
from pathlib import Path
import re
import stat

from .boat_video_identity import _pixels


CONTEXT_MODEL_BYTES = 10395288
CONTEXT_MODEL_SHA256 = 'c60df21c802422ec35930f50d5fc60ed27808e4ed1073436c6007399eeafd6d4'
GLYPH_MODEL_BYTES = 7715667
GLYPH_MODEL_SHA256 = '4f8f9e9435bf92157b7b77524ec90106dbb18663bad0aa15e03422ac158e2fca'


def _need(condition):
    if not condition:
        raise ValueError('BOAT_DEVELOPMENT_MARKER_VERIFIER_REJECTED')


def _cv():
    try:
        import cv2
    except ImportError:
        raise ValueError('BOAT_DEVELOPMENT_MARKER_RUNTIME_UNAVAILABLE') from None
    return cv2


def _verified_bytes(path, *, size, digest):
    """Read a regular local file once; parsing uses these authenticated bytes."""
    _need(isinstance(path, (str, Path)) and
          not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', str(path)))
    candidate = Path(path)
    try:
        _need(not candidate.is_symlink())
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(candidate, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            _need(stat.S_ISREG(info.st_mode) and info.st_size == size)
            raw = stream.read(size+1)
    except (OSError, ValueError):
        raise ValueError('BOAT_DEVELOPMENT_MARKER_ASSET_REJECTED') from None
    _need(len(raw) == size and sha256(raw).hexdigest() == digest)
    return raw


def _glyph_feature(gray):
    """Exact frozen synthetic/Commons training feature, including native aspect."""
    import numpy as np
    cv = _cv()
    height, width = gray.shape
    scale = min(24/width, 40/height)
    new_width, new_height = max(1, round(width*scale)), max(1, round(height*scale))
    resized = cv.resize(gray, (new_width, new_height),
        interpolation=cv.INTER_AREA if scale < 1 else cv.INTER_LINEAR)
    edge = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
    normalized = np.full((48, 32), float(np.median(edge)), np.uint8)
    top, left = (48-new_height)//2, (32-new_width)//2
    normalized[top:top+new_height, left:left+new_width] = resized
    low, high = np.percentile(normalized, [2, 98])
    normalized = np.clip((normalized.astype(np.float32)-low)*255/max(high-low, 1),
                         0, 255).astype(np.uint8)
    hog = cv.HOGDescriptor((32, 48), (16, 16), (8, 8), (8, 8), 9)
    descriptor = hog.compute(normalized).reshape(-1)
    return np.r_[descriptor, np.float32(np.clip(np.log(width/height), -3, 3))].astype(np.float32)


def _context_feature(frame, box):
    """Exact frozen context: ±one glyph height X and ±half glyph height Y."""
    cv = _cv()
    x, y, right, bottom = box
    height = bottom-y
    frame_height, frame_width = frame.shape[:2]
    crop = frame[max(0, int(y-.5*height)):min(frame_height, int(bottom+.5*height)),
                 max(0, int(x-height)):min(frame_width, int(right+height))].copy()
    gray = cv.cvtColor(crop, cv.COLOR_BGR2GRAY)
    hog = cv.HOGDescriptor((96, 64), (16, 16), (8, 8), (8, 8), 9)
    return hog.compute(cv.resize(gray, (96, 64))).reshape(-1)


def _load_model(raw, *, dimensions):
    """Never reopen an asset pathname after verifying it."""
    cv = _cv()
    storage = None
    try:
        storage = cv.FileStorage(raw.decode('utf-8'), cv.FILE_STORAGE_READ | cv.FILE_STORAGE_MEMORY)
        _need(storage.isOpened())
        node = storage.getFirstTopLevelNode()
        _need(not node.empty())
        model = cv.ml.SVM_create()
        model.read(node)
        _need(model.isTrained() and model.getVarCount() == dimensions and
              model.getType() == cv.ml.SVM_C_SVC and model.getKernelType() == cv.ml.SVM_LINEAR)
    except (cv.error, UnicodeError, ValueError):
        raise ValueError('BOAT_DEVELOPMENT_MARKER_MODEL_REJECTED') from None
    finally:
        if storage is not None:
            storage.release()
    return model


def _classes(model, features, *, count, maximum):
    import numpy as np
    try:
        _, result = model.predict(features)
    except _cv().error:
        raise ValueError('BOAT_DEVELOPMENT_MARKER_INFERENCE_REJECTED') from None
    _need(type(result) is np.ndarray and result.dtype == np.float32 and
          result.shape == (count, 1) and
          np.isfinite(result).all() and np.all(result >= 0) and np.all(result <= maximum) and
          np.all(result == np.floor(result)))
    return [int(value) for value in result[:, 0]]


class PinnedDevelopmentMarkerVerifier:
    """Opt-in local diagnostics; output order exactly follows integer XYXY boxes."""
    def __init__(self, *, context_model_path, glyph_model_path, development_opt_in=False):
        _need(development_opt_in is True)
        # Both asset pins are checked before importing/loading the optional CV runtime.
        context_raw = _verified_bytes(context_model_path, size=CONTEXT_MODEL_BYTES,
                                      digest=CONTEXT_MODEL_SHA256)
        glyph_raw = _verified_bytes(glyph_model_path, size=GLYPH_MODEL_BYTES,
                                    digest=GLYPH_MODEL_SHA256)
        self._context_model = _load_model(context_raw, dimensions=2772)
        self._glyph_model = _load_model(glyph_raw, dimensions=541)

    def metadata(self):
        return dict(engine='PINNED_LOCAL_DEVELOPMENT_MARKER_HOG_SVM',
            context_model_sha256=CONTEXT_MODEL_SHA256, glyph_model_sha256=GLYPH_MODEL_SHA256,
            license='CC-BY-SA-4.0-DERIVATIVE-PRIVATE-DEVELOPMENT',
            training_scope='DEVELOPMENT_TRAIN_OVERLAP', development_opt_in=True, Toda_training=False,
            calibrated_identification_probability=False, model_eligible=False,
            field_eligible=False, authenticated_number_identity=False)

    def __call__(self, frame, boxes_xyxy):
        import numpy as np
        width, height = _pixels(frame)
        _need(type(boxes_xyxy) is list)
        boxes = []
        for box in boxes_xyxy:
            _need(type(box) in (list, tuple) and len(box) == 4 and
                  all(type(value) is int for value in box))
            x, y, right, bottom = box
            _need(0 <= x < right <= width and 0 <= y < bottom <= height)
            boxes.append(tuple(box))
        if not boxes:
            return []
        # Crops/features are owned copies. No class result certifies an identity.
        cv = _cv()
        contexts, glyphs = [], []
        for x, y, right, bottom in boxes:
            contexts.append(_context_feature(frame, (x, y, right, bottom)))
            gray = cv.cvtColor(frame[y:bottom, x:right].copy(), cv.COLOR_BGR2GRAY)
            glyphs.append(_glyph_feature(gray))
        context_classes = _classes(self._context_model, np.asarray(contexts, np.float32),
                                   count=len(boxes), maximum=1)
        glyph_classes = _classes(self._glyph_model, np.asarray(glyphs, np.float32),
                                 count=len(boxes), maximum=6)
        return [dict(context_class=context, glyph_class=glyph)
                for context, glyph in zip(context_classes, glyph_classes)]
