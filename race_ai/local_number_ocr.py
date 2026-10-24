"""Offline, pinned-model OCR on caller-owned RAM pixels; no image I/O or uploads."""
import hashlib
from importlib.metadata import version
from pathlib import Path

from .core import SourceError

MODELS = {
    'Det': ('PP-OCRv6_det_small.onnx', '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f'),
    'Cls': ('ch_ppocr_mobile_v2.0_cls_mobile.onnx', 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c'),
    'Rec': ('PP-OCRv6_rec_small.onnx', '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884'),
}


class LocalNumberOCR:
    def __init__(self, *, model_dir=None):
        try:
            import rapidocr
            if version('rapidocr') != '3.10.0' or version('onnxruntime') != '1.31.0':
                raise SourceError('LOCAL_OCR_RUNTIME_VERSION_INVALID')
            root = Path(model_dir) if model_dir is not None else Path(rapidocr.__file__).parent/'models'
            params = {'Global.log_level':'critical', 'Det.limit_type':'max', 'Det.limit_side_len':736,
                      'EngineConfig.onnxruntime.intra_op_num_threads':1,
                      'EngineConfig.onnxruntime.inter_op_num_threads':1}
            self.model_sha256 = {}
            for component, (name, expected) in MODELS.items():
                path = root/name
                if not path.is_file() or not 0 < path.stat().st_size <= 32*1024*1024:
                    raise SourceError('LOCAL_OCR_MODEL_UNAVAILABLE')
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != expected:
                    raise SourceError('LOCAL_OCR_MODEL_HASH_INVALID')
                # Explicit paths avoid the dependency's auto-download branch.
                params[f'{component}.model_path'] = str(path.resolve())
                self.model_sha256[name] = digest
            self.engine = rapidocr.RapidOCR(params=params)
        except SourceError:
            raise
        except (ImportError, OSError):
            raise SourceError('LOCAL_OCR_RUNTIME_UNAVAILABLE') from None
        except Exception:
            raise SourceError('LOCAL_OCR_INITIALIZATION_FAILED') from None

    def __call__(self, pixels):
        try:
            import numpy as np
            if (type(pixels) is not np.ndarray or pixels.dtype != np.uint8 or pixels.ndim != 3
                    or pixels.shape[2] != 3 or not 0 < pixels.shape[0]*pixels.shape[1] <= 1280*720):
                raise SourceError('LOCAL_OCR_PIXELS_INVALID')
            value = self.engine(pixels)
            if value.txts is None:
                return []
            if value.boxes is None or value.scores is None or not len(value.txts) == len(value.boxes) == len(value.scores) <= 128:
                raise SourceError('LOCAL_OCR_OUTPUT_INVALID')
            return [dict(text=str(t), score=float(s), box=b.tolist())
                    for t,s,b in zip(value.txts,value.scores,value.boxes)]
        except SourceError:
            raise
        except Exception:
            raise SourceError('LOCAL_OCR_INFERENCE_FAILED') from None
