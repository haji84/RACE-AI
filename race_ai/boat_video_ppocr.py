"""Optional pinned PP-OCRv4 recognition, never a calibrated identity score.

Recognition preprocessing and greedy decoding are adapted from PaddleOCR and
RapidOCR: Copyright (c) 2020 PaddlePaddle Authors, Apache License 2.0,
https://www.apache.org/licenses/LICENSE-2.0 . No trained asset is distributed
here. Only an explicit verified local model is loaded; nothing is downloaded.

The stock six-image aspect-sorted batches use all 6625 output symbols. An exact
one-symbol CTC path sum is separate from the stock mean selected-character
score. Neither is identity accuracy, calibrated confidence or field evidence.
"""
from hashlib import sha256
import json
import math

from .boat_video_identity import _finite, _local_file, _pixels


MODEL_NAME = 'ch_PP-OCRv4_rec_infer.onnx'
MODEL_BYTES = 10857958
MODEL_SHA256 = '48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b'
ORT_VERSION = '1.31.1'
VOCABULARY_SIZE = 6625
BATCH_SIZE = 6
IMAGE_HEIGHT = 48
BASE_WIDTH = 320
SCORE_SCOPE = 'UNCALIBRATED_FULL_6625_VOCABULARY_CTC_SEQUENCE_LIKELIHOOD_NOT_ACCURACY'
MEAN_SCORE_SCOPE = 'UNCALIBRATED_MEAN_CHARACTER_SCORE_NOT_PROBABILITY'
_ROW_SUM_TOLERANCE = 1e-5
# Explicit per-analysis memory guards; these never truncate or skip candidates.
_MAX_NORMALIZED_WIDTH = 8192
_MAX_CTC_STEPS = 2048


def _need(condition):
    if not condition:
        raise ValueError('BOAT_PPOCR_REJECTED')


def vocabulary_from_metadata(character):
    """Use the model's embedded dictionary, then stock space and blank tokens."""
    _need(type(character) is str)
    values = character.splitlines()
    _need(len(values) == VOCABULARY_SIZE-2 and all(len(c) == 1 for c in values)
          and len(set(values)) == len(values) and ' ' not in values)
    return tuple(['blank', *values, ' '])


def _characters(values):
    _need(type(values) in (list, tuple) and len(values) == VOCABULARY_SIZE
          and values[0] == 'blank' and all(type(c) is str and len(c) == 1 for c in values[1:])
          and len(set(values)) == VOCABULARY_SIZE)
    return values


def _probabilities(rows):
    import numpy as np
    _need(type(rows) is np.ndarray and rows.dtype in (np.dtype('float32'), np.dtype('float64'))
          and rows.ndim == 2 and 1 <= rows.shape[0] <= _MAX_CTC_STEPS
          and rows.shape[1] == VOCABULARY_SIZE)
    _need(np.isfinite(rows).all() and np.all(rows >= 0) and np.all(rows <= 1)
          and np.all(np.abs(rows.sum(axis=1, dtype=np.float64)-1.) <= _ROW_SUM_TOLERANCE))
    return rows


def _single(rows, symbol):
    before, emitting, after = 1., 0., 0.
    for blank, char in rows[:, [0, symbol]]:
        blank, char = float(blank), float(char)
        before, emitting, after = before*blank, (before+emitting)*char, (emitting+after)*blank
    # Roundoff only: full rows have already been checked; never renormalize a
    # digit subset or apply another softmax to the model's normalized output.
    return min(1., max(0., emitting+after))


def single_ctc_likelihood(probabilities, symbol):
    """Sum every full-softmax CTC path that collapses to exactly one symbol."""
    _need(type(symbol) is int and 1 <= symbol < VOCABULARY_SIZE)
    return _single(_probabilities(probabilities), symbol)


def decode_softmax(probabilities, characters):
    """Stock full-dictionary greedy CTC, plus a separately scoped path sum."""
    import numpy as np
    rows, characters = _probabilities(probabilities), _characters(characters)
    indices = rows.argmax(axis=1)
    selected = np.ones(len(rows), dtype=bool)
    selected[1:] = indices[1:] != indices[:-1]
    selected &= indices != 0
    symbols = indices[selected]
    text = ''.join(characters[int(i)] for i in symbols)
    # Stock RapidOCR converts selected float32 values to a Python list before
    # np.mean; float64 accumulation preserves that same decoder behavior.
    score = float(rows.max(axis=1)[selected].astype(np.float64).mean()) if len(symbols) else 0.
    likelihood = _single(rows, int(symbols[0])) if len(text) == 1 else None
    return dict(text=text, sequence_likelihood=likelihood, mean_character_score=score,
        uncalibrated_mean_character_score_not_probability=score,
        score_scope=SCORE_SCOPE, mean_character_score_scope=MEAN_SCORE_SCOPE,
        softmax_sha256=sha256(np.ascontiguousarray(rows).tobytes()).hexdigest(),
        softmax_shape=list(rows.shape), softmax_dtype=str(rows.dtype),
        full_vocabulary_size=VOCABULARY_SIZE, model_eligible=False,
        field_validation='NOT_ESTABLISHED')


def plan_batches(crops):
    """Validate the entire call before any inference, retaining every index."""
    import numpy as np
    _need(type(crops) is list)
    ratios = []
    for crop in crops:
        width, height = _pixels(crop)
        ratios.append(width/float(height))
    # Exactly the stock default np.argsort, including its equal-ratio ordering.
    indices = np.argsort(np.array(ratios))
    result = []
    for begin in range(0, len(crops), BATCH_SIZE):
        batch = [int(i) for i in indices[begin:begin+BATCH_SIZE]]
        ratio = max(BASE_WIDTH/IMAGE_HEIGHT, *(ratios[i] for i in batch))
        _need(int(IMAGE_HEIGHT*ratio) <= _MAX_NORMALIZED_WIDTH)
        result.append(dict(indices=batch, max_wh_ratio=ratio))
    return result


def prepare_image(crop, *, max_wh_ratio):
    """Stock BGR aspect resize/CHW normalization/right normalized-zero padding."""
    import cv2
    import numpy as np
    width, height = _pixels(crop)
    _need(_finite(max_wh_ratio) and max_wh_ratio >= BASE_WIDTH/IMAGE_HEIGHT)
    image_width = int(IMAGE_HEIGHT*max_wh_ratio)
    _need(image_width <= _MAX_NORMALIZED_WIDTH)
    resized_width = min(image_width, math.ceil(IMAGE_HEIGHT*width/float(height)))
    resized = cv2.resize(crop, (resized_width, IMAGE_HEIGHT))
    resized = resized.astype('float32').transpose((2, 0, 1))/255
    resized -= .5
    resized /= .5
    padded = np.zeros((3, IMAGE_HEIGHT, image_width), dtype=np.float32)
    padded[:, :, :resized_width] = resized
    return padded


class PinnedPPOCRRecognizer:
    """Explicit CPU-only ORT recognizer; outputs are aligned to original crops."""
    def __init__(self, *, model_path):
        _, raw = _local_file(model_path, max_bytes=MODEL_BYTES)
        _need(len(raw) == MODEL_BYTES and sha256(raw).hexdigest() == MODEL_SHA256)
        try:
            import onnxruntime as ort
        except ImportError:
            raise ValueError('BOAT_PPOCR_RUNTIME_UNAVAILABLE') from None
        _need(ort.__version__ == ORT_VERSION)
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.log_severity_level = 4
        options.enable_cpu_mem_arena = False
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(raw, sess_options=options,
            providers=[('CPUExecutionProvider', {'arena_extend_strategy': 'kSameAsRequested'})])
        _need(self._session.get_providers() == ['CPUExecutionProvider'])
        inputs, outputs = self._session.get_inputs(), self._session.get_outputs()
        _need(len(inputs) == 1 and inputs[0].name == 'x' and inputs[0].type == 'tensor(float)'
              and len(outputs) == 1 and outputs[0].name == 'softmax_11.tmp_0'
              and outputs[0].type == 'tensor(float)' and outputs[0].shape[-1] == VOCABULARY_SIZE)
        metadata = self._session.get_modelmeta().custom_metadata_map
        self._characters = vocabulary_from_metadata(metadata.get('character'))
        self._vocabulary_sha = sha256(json.dumps(list(self._characters), ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')).hexdigest()
        self._character_metadata_sha = sha256(metadata['character'].encode('utf-8')).hexdigest()

    def metadata(self):
        return dict(engine='ONNXRUNTIME_CPU', onnxruntime_version=ORT_VERSION,
            model_name=MODEL_NAME, model_sha256=MODEL_SHA256, model_bytes=MODEL_BYTES,
            vocabulary_sha256=self._vocabulary_sha,
            character_metadata_sha256=self._character_metadata_sha,
            vocabulary_hash_format='UTF8_COMPACT_JSON_ORDERED_FULL_VOCABULARY',
            vocabulary_size=VOCABULARY_SIZE, batch_size=BATCH_SIZE,
            image_shape=[3, IMAGE_HEIGHT, BASE_WIDTH], input_channels='BGR',
            padding='RIGHT_ZERO_AFTER_NORMALIZATION', aspect_sort='NUMPY_ARGSORT_DEFAULT',
            score_scope=SCORE_SCOPE, mean_character_score_scope=MEAN_SCORE_SCOPE,
            maximum_analysis_width_px=_MAX_NORMALIZED_WIDTH,
            model_eligible=False, field_validation='NOT_ESTABLISHED', license='Apache-2.0')

    def __call__(self, crops):
        import numpy as np
        batches = plan_batches(crops)
        sources = tuple(crops)
        shapes = [tuple(crop.shape) for crop in sources]
        hashes = [sha256(crop.tobytes()).hexdigest() for crop in sources]
        result = [None]*len(sources)
        for batch_number, batch in enumerate(batches):
            snapshots = []
            for original in batch['indices']:
                snapshot = sources[original].copy()
                _pixels(snapshot)
                _need(tuple(snapshot.shape) == shapes[original] and
                      sha256(snapshot.tobytes()).hexdigest() == hashes[original])
                snapshots.append(snapshot)
            # Normalize only the verified private snapshots. A later caller
            # restore cannot disguise changed bytes consumed by another batch.
            blob = np.concatenate([prepare_image(snapshot, max_wh_ratio=batch['max_wh_ratio'])[None]
                                   for snapshot in snapshots]).astype(np.float32)
            batch_sha = sha256(blob.tobytes()).hexdigest()
            output = self._session.run(['softmax_11.tmp_0'], {'x': blob})
            _need(type(output) is list and len(output) == 1 and type(output[0]) is np.ndarray
                  and output[0].dtype == np.float32 and output[0].ndim == 3
                  and output[0].shape[0] == len(batch['indices'])
                  and output[0].shape[2] == VOCABULARY_SIZE)
            for position, original in enumerate(batch['indices']):
                row = decode_softmax(output[0][position], self._characters)
                row.update(input_sha256=hashes[original], input_shape=list(shapes[original]),
                    input_dtype='uint8', input_channels='BGR', batch_input_sha256=batch_sha,
                    batch_number=batch_number, batch_position=position,
                    model_sha256=MODEL_SHA256, vocabulary_sha256=self._vocabulary_sha)
                result[original] = row
        # Protect original-pixel provenance even if another thread or native
        # inference changes caller-owned buffers during the whole operation.
        _need(len(crops) == len(sources) and all(crop is sources[i] for i, crop in enumerate(crops)))
        for index, crop in enumerate(sources):
            _pixels(crop)
            after = sha256(crop.tobytes()).hexdigest()
            _need(tuple(crop.shape) == shapes[index] and after == hashes[index])
            result[index]['input_sha256_after'] = after
        return result
