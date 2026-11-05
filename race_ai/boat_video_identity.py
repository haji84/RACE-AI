"""Local generic hull detection, digit OCR and unverified temporal identities.

No downloads, color-to-lane mapping, certified identities or forecast features.
Callers explicitly supply local assets. Generic COCO boats can be missed or
misclassified; three consistent OCR frames are evidence, not field validation.

Detector preprocessing/decoding adapts OpenCV Zoo's NanoDet and YOLOX demos at
ea593dd89b88d4b3978273a16f0d8cfe93d2e3ea, Apache License 2.0, contributor
Sri Siddarth Chakaravarthy / OpenCV GSoC 2022. Local source/model notices and
licenses accompany the original assets. License: https://www.apache.org/licenses/LICENSE-2.0
Changes: pinned RAM loading, bounded tensors, boat-only NMS, safe metadata and
crop OCR/temporal association. No reference-repository imports are required.
"""
from collections import Counter
from copy import deepcopy
import csv
from functools import lru_cache
import hashlib
import io
import math
from pathlib import Path
import re
import stat
import subprocess
import time


MODEL_SPECS = {
    "yolox": {"name": "object_detection_yolox_2022nov.onnx", "bytes": 35858002,
              "sha256": "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"},
    "nanodet": {"name": "object_detection_nanodet_2022nov.onnx", "bytes": 3800954,
                "sha256": "4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186"},
}
STATUS = "NUMBER_TEMPORAL_CANDIDATE"


def _require(condition, message="invalid local boat identity input"):
    if not condition:
        raise ValueError(message)


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _pixels(frame):
    import numpy as np
    _require(type(frame) is np.ndarray and frame.dtype == np.uint8 and frame.ndim == 3
             and frame.shape[2] == 3 and min(frame.shape[:2]) > 0
             and max(frame.shape[:2]) <= 1920 and frame.shape[0] * frame.shape[1] <= 2073600,
             "bounded uint8 BGR pixels are required")
    return frame.shape[1], frame.shape[0]


def _box(box, width, height):
    _require(type(box) in (list, tuple) and len(box) == 4 and all(_finite(v) for v in box))
    x, y, w, h = box
    _require(w >= 1 and h >= 1 and 0 <= x < x+w <= width and 0 <= y < y+h <= height,
             "hull box must be inside the frame")
    return [float(v) for v in box]


def _detections(rows, width, height):
    _require(type(rows) is list and len(rows) <= 12, "at most twelve hull candidates are supported")
    checked = []
    for row in rows:
        _require(type(row) is dict and set(row) == {"box", "score"}
                 and _finite(row["score"]) and 0 <= row["score"] <= 1)
        checked.append({"box": _box(row["box"], width, height), "score": float(row["score"])})
    return checked


def _intersects(first, second):
    x, y, w, h = first
    a, b, c, d = second
    return x < a+c and a < x+w and y < b+d and b < y+h


def _iou(first, second):
    x, y, w, h = first
    a, b, c, d = second
    intersection = max(0., min(x+w, a+c)-max(x, a)) * max(0., min(y+h, b+d)-max(y, b))
    return intersection / max(1e-9, w*h+c*d-intersection)


def _center(box):
    return box[0]+box[2]/2, box[1]+box[3]/2


def _nms(proposals):
    kept = []
    for row in sorted(proposals, key=lambda r: (-r["score"], tuple(r["box"]))):
        if all(_iou(row["box"], old["box"]) <= .5 for old in kept):
            kept.append(row)
            if len(kept) == 12:
                break
    return kept


def decode_yolox_regions(output, *, width, height):
    """Decode the exact pinned YOLOX_s head; return generic boat candidates."""
    import numpy as np
    _box([0, 0, width, height], width, height)
    _require(type(output) is np.ndarray and output.dtype == np.float32
             and output.shape == (1, 8400, 85) and np.isfinite(output).all()
             and np.all((output[:, :, 4:] >= 0) & (output[:, :, 4:] <= 1)))
    scale = min(640/width, 640/height)
    rw, rh = max(1, int(width*scale)), max(1, int(height*scale))
    values = output[0]
    scores = values[:, 4] * values[:, 13]
    selected = np.flatnonzero((values[:, 5:].argmax(axis=1) == 8) & (scores >= .5))
    proposed = []
    for i in selected[np.argsort(-scores[selected], kind="stable")[:256]]:
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
            proposed.append({"box": [x1, y1, x2-x1, y2-y1], "score": float(scores[i])})
    return _nms(proposed)


def decode_nanodet_regions(outputs, *, width, height):
    """Pair the exact pinned NanoDet heads by tensor shape, independent of order."""
    import numpy as np
    _box([0, 0, width, height], width, height)
    _require(type(outputs) in (list, tuple) and len(outputs) == 6)
    tensors = {}
    for value in outputs:
        _require(type(value) is np.ndarray and value.dtype == np.float32 and value.ndim == 3
                 and value.shape[0] == 1 and value.shape[1] in (2704, 676, 169)
                 and value.shape[2] in (80, 32) and np.isfinite(value).all())
        key = value.shape[1], value.shape[2]
        _require(key not in tensors)
        if key[1] == 80:
            _require(np.all((value >= 0) & (value <= 1)))
        tensors[key] = value[0]
    _require(set(tensors) == {(n, c) for n in (2704, 676, 169) for c in (80, 32)})
    scale = min(416/width, 416/height)
    rw, rh = max(1, round(width*scale)), max(1, round(height*scale))
    left, top = (416-rw)//2, (416-rh)//2
    proposed = []
    for stride, side in ((8, 52), (16, 26), (32, 13)):
        scores, distances = tensors[(side*side, 80)], tensors[(side*side, 32)]
        selected = np.flatnonzero((scores.argmax(axis=1) == 8) & (scores[:, 8] >= .5))
        for i in selected[np.argsort(-scores[selected, 8], kind="stable")[:256]]:
            logits = distances[i].astype(np.float64).reshape(4, 8)
            probabilities = np.exp(logits-logits.max(axis=1, keepdims=True))
            offsets = probabilities @ np.arange(8) / probabilities.sum(axis=1) * stride
            cx, cy = (i % side)*stride+(stride-1)*.5, (i//side)*stride+(stride-1)*.5
            x1, y1 = max(0., (cx-offsets[0]-left)*width/rw), max(0., (cy-offsets[1]-top)*height/rh)
            x2, y2 = min(float(width), (cx+offsets[2]-left)*width/rw), min(float(height), (cy+offsets[3]-top)*height/rh)
            if x2-x1 >= 1 and y2-y1 >= 1:
                proposed.append({"box": [float(x1), float(y1), float(x2-x1), float(y2-y1)],
                                 "score": float(scores[i, 8])})
    return _nms(proposed)


def _local_file(path, *, max_bytes):
    _require(isinstance(path, (str, Path)) and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", str(path)),
             "an explicit local asset path is required")
    candidate = Path(path)
    _require(not candidate.is_symlink() and candidate.is_file(), "local asset is unavailable")
    info = candidate.stat()
    _require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= max_bytes, "local asset has invalid size")
    return candidate, candidate.read_bytes()


class PinnedBoatDetector:
    """CPU-only OpenCV DNN using one explicit, hash-pinned existing local asset."""
    def __init__(self, *, model_path, detector_kind="yolox"):
        import cv2
        import numpy as np
        _require(detector_kind in MODEL_SPECS, "unsupported local detector")
        spec = MODEL_SPECS[detector_kind]
        _, raw = _local_file(model_path, max_bytes=spec["bytes"])
        _require(len(raw) == spec["bytes"] and hashlib.sha256(raw).hexdigest() == spec["sha256"],
                 "local detector integrity check failed")
        try:
            self.net = cv2.dnn.readNetFromONNX(np.frombuffer(raw, dtype=np.uint8))
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except cv2.error:
            raise ValueError("local detector runtime is unavailable") from None
        self.kind, self.cv_version = detector_kind, cv2.__version__

    def metadata(self):
        return {"engine": "OPENCV_DNN_CPU", "opencv_version": self.cv_version,
                "model_name": MODEL_SPECS[self.kind]["name"],
                "model_sha256": MODEL_SPECS[self.kind]["sha256"],
                "class_scope": "GENERIC_COCO_BOAT_CANDIDATE", "license": "Apache-2.0",
                "source_commit": "ea593dd89b88d4b3978273a16f0d8cfe93d2e3ea"}

    def __call__(self, frame):
        import cv2
        import numpy as np
        width, height = _pixels(frame)
        side = 640 if self.kind == "yolox" else 416
        scale = min(side/width, side/height)
        if self.kind == "yolox":
            rw, rh = max(1, int(width*scale)), max(1, int(height*scale))
            canvas = np.full((side, side, 3), 114, dtype=np.uint8)
            canvas[:rh, :rw] = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (rw, rh))
        else:
            rw, rh = max(1, round(width*scale)), max(1, round(height*scale))
            left, top = (side-rw)//2, (side-rh)//2
            canvas = np.zeros((side, side, 3), dtype=np.float32)
            canvas[top:top+rh, left:left+rw] = cv2.resize(frame, (rw, rh)).astype(np.float32)
            canvas = (canvas-np.array([103.53, 116.28, 123.675], np.float32))/np.array([57.375, 57.12, 58.395], np.float32)
        try:
            self.net.setInput(cv2.dnn.blobFromImage(canvas))
            outputs = self.net.forward(self.net.getUnconnectedOutLayersNames())
            if self.kind == "yolox":
                _require(len(outputs) == 1)
                return decode_yolox_regions(outputs[0], width=width, height=height)
            return decode_nanodet_regions(outputs, width=width, height=height)
        except cv2.error:
            raise ValueError("local detector inference failed") from None


class LocalTesseractNumberReader:
    """Bounded local crop OCR; exact digits and their geometry remain candidates."""
    def __init__(self, *, tesseract_path, tessdata_path, timeout_seconds=3):
        executable, raw = _local_file(tesseract_path, max_bytes=32*1024*1024)
        _require(executable.is_absolute() and executable.stat().st_mode & 0o111,
                 "an explicit local OCR executable is required")
        data = Path(tessdata_path)
        _require(data.is_absolute() and data.is_dir(), "explicit local OCR data is required")
        _, language = _local_file(data/"eng.traineddata", max_bytes=32*1024*1024)
        _require(_finite(timeout_seconds) and 0 < timeout_seconds <= 10)
        try:
            version = subprocess.run([str(executable), "--version"], capture_output=True,
                                     check=True, timeout=timeout_seconds).stdout.decode("utf-8").splitlines()[0]
        except (OSError, subprocess.SubprocessError, UnicodeError, IndexError):
            raise ValueError("local OCR runtime is unavailable") from None
        _require(re.fullmatch(r"tesseract [0-9]+(?:\.[0-9]+){1,3}", version) is not None,
                 "unsupported local OCR executable")
        self.executable, self.data, self.timeout = str(executable), str(data), timeout_seconds
        self._metadata = {"engine": "TESSERACT_LOCAL", "version": version.split(" ")[1],
                          "engine_sha256": hashlib.sha256(raw).hexdigest(),
                          "language_sha256": hashlib.sha256(language).hexdigest(), "language": "eng"}

    def metadata(self):
        return dict(self._metadata)

    def __call__(self, crop):
        import cv2
        width, height = _pixels(crop)
        scale = min(3., 768/width, 384/height)
        rw, rh = max(1, round(width*scale)), max(1, round(height*scale))
        gray = cv2.cvtColor(cv2.resize(crop, (rw, rh)), cv2.COLOR_BGR2GRAY)
        ok, encoded = cv2.imencode(".png", gray)
        _require(ok and encoded.nbytes <= 1024*1024, "local OCR crop is too large")
        deadline = time.monotonic()+self.timeout
        try:
            # Sparse text finds marks in a hull crop. A single-character fallback
            # also handles tight isolated marks. Both share one bounded deadline.
            for mode in (11, 10):
                command = [self.executable, "stdin", "stdout", "--tessdata-dir", self.data,
                           "-l", "eng", "--psm", str(mode), "-c", "tessedit_char_whitelist=123456",
                           "-c", "load_system_dawg=0", "-c", "load_freq_dawg=0", "tsv"]
                remaining = deadline-time.monotonic()
                _require(remaining > 0, "local OCR timeout")
                completed = subprocess.run(command, input=encoded.tobytes(), capture_output=True,
                                           check=True, timeout=remaining)
                _require(len(completed.stdout) <= 262144, "local OCR output is too large")
                rows = list(csv.DictReader(io.StringIO(completed.stdout.decode("utf-8")), delimiter="\t"))
                _require(len(rows) <= 256, "local OCR row limit exceeded")
                found = []
                for row in rows:
                    if row.get("text") not in ("1", "2", "3", "4", "5", "6"):
                        continue
                    confidence = float(row["conf"])/100
                    x, y, w, h = (float(row[key]) for key in ("left", "top", "width", "height"))
                    if not (0 <= confidence <= 1 and w >= 1 and h >= 1
                            and 0 <= x < x+w <= rw and 0 <= y < y+h <= rh):
                        continue
                    found.append({"text": row["text"], "score": confidence,
                                  "box": [x*width/rw, y*height/rh, w*width/rw, h*height/rh]})
                if found:
                    return found[:32]
            return []
        except (OSError, subprocess.SubprocessError, UnicodeError, KeyError, TypeError, ValueError):
            raise ValueError("local OCR inference failed") from None


def _homography(value):
    import numpy as np
    if value is None:
        return np.eye(3)
    try:
        matrix = np.asarray(value)
        _require(matrix.shape == (3, 3) and matrix.dtype.kind in "fi" and np.isfinite(matrix).all()
                 and abs(float(matrix[2, 2])) > 1e-8 and abs(float(np.linalg.det(matrix))) > 1e-8,
                 "a finite nonsingular camera homography is required")
        return matrix.astype(np.float64)/matrix[2, 2]
    except (TypeError, OverflowError):
        raise ValueError("a finite nonsingular camera homography is required") from None


def _project(matrix, point):
    value = matrix @ [point[0], point[1], 1.]
    if not all(math.isfinite(float(v)) for v in value) or value[2] <= 1e-8:
        return None
    return float(value[0]/value[2]), float(value[1]/value[2])


def _predicted_box(track, matrix, duration):
    x, y, w, h = track["box"]
    dx, dy = (v*duration for v in track["velocity"])
    points = [_project(matrix, (a+dx, b+dy)) for a, b in ((x, y), (x+w, y), (x+w, y+h), (x, y+h))]
    if any(point is None for point in points):
        return None
    xs, ys = zip(*points)
    box = [min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)]
    return box if min(box[2:]) > 0 else None


def _assignment(costs, forbidden=None):
    """Maximum cardinality, then exact minimum total cost; deterministic ties."""
    @lru_cache(None)
    def solve(index, used):
        if index == len(costs):
            return 0, 0., ()
        best = solve(index+1, used)
        for column, cost in enumerate(costs[index]):
            if cost is None or used & (1 << column) or forbidden == (index, column):
                continue
            count, total, pairs = solve(index+1, used | (1 << column))
            candidate = count+1, total+cost, ((index, column),)+pairs
            if (-candidate[0], candidate[1], candidate[2]) < (-best[0], best[1], best[2]):
                best = candidate
        return best
    return solve(0, 0)


class BoatIdentityProvider:
    """Observe hulls on every call; never emit predictions through missing hulls.

    ``number_reader(crop)`` returns crop-local rows containing text, score 0..1
    and an [x,y,w,h] digit box. Injected components are for explicit caller use;
    the factory below wires actual local detector and OCR engines.
    """
    def __init__(self, *, detector, number_reader, exclusions=(), min_observations=3,
                 max_gap_seconds=.5):
        _require(callable(detector) and callable(number_reader))
        _require(type(min_observations) is int and 3 <= min_observations <= 20)
        _require(_finite(max_gap_seconds) and 0 < max_gap_seconds <= 3)
        _require(type(exclusions) in (list, tuple) and len(exclusions) <= 32)
        self.detector, self.number_reader = detector, number_reader
        self.exclusions = deepcopy(list(exclusions))
        self.minimum, self.max_gap = min_observations, max_gap_seconds
        self._tracks, self._scene, self._time, self._frame, self._shape = [], None, None, None, None
        self._next_id = 1

    def metadata(self):
        detector = self.detector.metadata() if type(self.detector) is PinnedBoatDetector else {"engine": "INJECTED_DETECTOR"}
        reader = self.number_reader.metadata() if type(self.number_reader) is LocalTesseractNumberReader else {"engine": "INJECTED_NUMBER_READER"}
        return {"schema_version": "RACE_AI_LOCAL_BOAT_IDENTITY_PROVIDER_V1", "detector": detector,
                "number_reader": reader, "minimum_digit_observations": self.minimum,
                "identity_status": STATUS, "identity_validated": False, "model_eligible": False,
                "field_validation": "NOT_ESTABLISHED", "color_lane_inference": False}

    def detect(self, frame):
        width, height = _pixels(frame)
        return _detections(self.detector(frame.copy()), width, height)

    def _number(self, frame, hull, overlays):
        x, y, w, h = hull
        a, b, c, d = math.floor(x), math.floor(y), math.ceil(x+w), math.ceil(y+h)
        rows = self.number_reader(frame[b:d, a:c].copy())
        _require(type(rows) is list and len(rows) <= 32, "bounded OCR rows are required")
        found = []
        for row in rows:
            if not (type(row) is dict and set(row) == {"text", "score", "box"}
                    and type(row["text"]) is str and row["text"] in ("1", "2", "3", "4", "5", "6")
                    and _finite(row["score"]) and .90 <= row["score"] <= 1):
                continue
            try:
                px, py, pw, ph = _box(row["box"], c-a, d-b)
            except ValueError:
                continue
            digit = [a+px, b+py, pw, ph]
            if not (x <= digit[0] and y <= digit[1] and digit[0]+pw <= x+w and digit[1]+ph <= y+h):
                continue
            if any(_intersects(digit, overlay) for overlay in overlays):
                continue
            value = {"number": int(row["text"]), "confidence": float(row["score"]), "box": digit}
            if any(old["number"] == value["number"] and _iou(old["box"], digit) >= .5 for old in found):
                continue
            found.append(value)
        return (found[0], False) if len(found) == 1 else (None, len(found) > 1)

    def identify(self, frame, detections, *, t, frame_index, scene, previous_to_current=None):
        width, height = _pixels(frame)
        _require(_finite(t) and t >= 0 and type(frame_index) is int and frame_index >= 0
                 and type(scene) is int and scene >= 0)
        _require(self._time is None or (t > self._time and frame_index > self._frame),
                 "identity observations require strictly increasing PTS and frames")
        _require(self._scene is None or scene >= self._scene, "scene identifiers must not decrease")
        matrix = _homography(previous_to_current)
        raw = _detections(detections, width, height)
        overlays = [_box(box, width, height) for box in self.exclusions]
        flags = {"NUMBER_IDENTITY_UNVERIFIED", "SYNTHETIC_TESTS_DO_NOT_ESTABLISH_FIELD_VALIDATION"}
        reset = (scene != self._scene or self._shape != (width, height)
                 or self._time is None or t-self._time > self.max_gap)
        previous = [] if reset else self._tracks
        blocked = set()
        for i, row in enumerate(raw):
            if row["score"] < .5:
                blocked.add(i)
            if any(_intersects(row["box"], overlay) for overlay in overlays):
                blocked.add(i)
                flags.add("OVERLAY_INTERSECTION")
            for j in range(i):
                if _iou(row["box"], raw[j]["box"]) >= .2:
                    blocked.update((i, j))
                    flags.add("OVERLAPPING_HULL_CANDIDATES")
        observed = []
        for index, row in enumerate(raw):
            if index in blocked:
                continue
            number, ambiguous = self._number(frame, row["box"], overlays)
            if ambiguous:
                flags.add("AMBIGUOUS_NUMBER_MARKS")
                blocked.add(index)
                continue
            observed.append({**row, "raw_index": index, "number": number})
        duplicate = {number for number, count in Counter(
            row["number"]["number"] for row in observed if row["number"] is not None).items() if count > 1}
        if duplicate:
            flags.add("DUPLICATE_NUMBER_OBSERVATIONS")
            observed = [row for row in observed if row["number"] is None or row["number"]["number"] not in duplicate]
        # A blocked observation is evidence of an interruption, not permission to
        # transfer that hull's old identity onto a nearby unread candidate.
        surviving = []
        for old in previous:
            predicted = _predicted_box(old, matrix, t-old["t"])
            if (old["number"] in duplicate or predicted is None
                    or any(_intersects(predicted, raw[index]["box"]) for index in blocked)):
                continue
            conflicting_number = old["number"] is not None and any(
                row["number"] is not None and row["number"]["number"] != old["number"]
                and _intersects(predicted, row["box"]) for row in observed)
            if conflicting_number:
                flags.add("CONFLICTING_NUMBER_OBSERVATIONS")
                # A spatial contradiction prevents inheritance by an unread
                # neighbor. A positively matching mark may still anchor a real
                # crossing; it must also pass the normal temporal/geometry gates.
                if not any(row["number"] is not None and row["number"]["number"] == old["number"]
                           for row in observed):
                    continue
            surviving.append({**old, "requires_current_number": conflicting_number})
        previous = surviving
        costs = []
        for old in previous:
            predicted = _predicted_box(old, matrix, t-old["t"])
            row_costs = []
            for row in observed:
                cost = None
                digit = row["number"]
                if (predicted is not None and not (old["requires_current_number"] and digit is None)
                        and not (digit is not None and old["number"] is not None
                                 and digit["number"] != old["number"])):
                    distance = math.dist(_center(predicted), _center(row["box"]))
                    gate = max(12., 1.5*math.hypot(predicted[2], predicted[3]))
                    ratio = row["box"][2]*row["box"][3]/(predicted[2]*predicted[3])
                    if distance <= gate and .5 <= ratio <= 2:
                        cost = distance/gate + .4*(1-_iou(predicted, row["box"])) + .2*abs(math.log(ratio))
                row_costs.append(cost)
            costs.append(row_costs)
        count, total, pairs = _assignment(costs)
        ambiguous_tracks, ambiguous_rows = set(), set()
        for pair in pairs:
            alt_count, alt_total, alternative = _assignment(costs, forbidden=pair)
            if alt_count == count and alt_total-total <= .15:
                changed = set(pairs).symmetric_difference(alternative)
                ambiguous_tracks.update(i for i, _ in changed)
                ambiguous_rows.update(j for _, j in changed)
        if ambiguous_rows:
            flags.add("AMBIGUOUS_TEMPORAL_ASSOCIATION")
        matched = {j: previous[i] for i, j in pairs if i not in ambiguous_tracks and j not in ambiguous_rows}
        current = []
        for j, row in enumerate(observed):
            if j in ambiguous_rows:
                continue
            old = matched.get(j)
            if old is None:
                old = {"track_id": f"T{self._next_id:06d}", "number": None, "evidence": [],
                       "box": row["box"], "t": float(t), "velocity": (0., 0.)}
                self._next_id += 1
                velocity = (0., 0.)
            else:
                projected = _project(matrix, _center(old["box"]))
                center = _center(row["box"])
                velocity = tuple((center[k]-projected[k])/(t-old["t"]) for k in (0, 1))
            evidence = list(old["evidence"])
            number = old["number"]
            if row["number"] is not None:
                number = row["number"]["number"]
                evidence.append({**row["number"], "frame_index": frame_index, "t": float(t)})
                evidence = evidence[-20:]
            current.append({"track_id": old["track_id"], "number": number, "evidence": evidence,
                            "box": list(row["box"]), "score": row["score"], "t": float(t),
                            "velocity": velocity, "current_number_observed": row["number"] is not None})
        current_duplicates = {number for number, n in Counter(
            row["number"] for row in current if row["number"] is not None).items() if n > 1}
        regions = []
        for track in current:
            if track["number"] in current_duplicates:
                track["number"], track["evidence"] = None, []
                flags.add("DUPLICATE_NUMBER_OBSERVATIONS")
            if track["number"] is None or len(track["evidence"]) < self.minimum:
                continue
            evidence = track["evidence"]
            regions.append({"lane": track["number"], "box": list(track["box"]), "score": track["score"],
                "track_id": track["track_id"], "identity_status": STATUS,
                "number_evidence": {"number": track["number"], "observations": len(evidence),
                    "first_frame_index": evidence[0]["frame_index"], "last_frame_index": evidence[-1]["frame_index"],
                    "minimum_confidence": min(item["confidence"] for item in evidence),
                    "last_number_box": list(evidence[-1]["box"]),
                    "current_observation": track["current_number_observed"], "source": "LOCAL_CROP_OCR"}})
        self._tracks, self._time, self._frame, self._scene = current, float(t), frame_index, scene
        self._shape = width, height
        return {"schema_version": "RACE_AI_BOAT_IDENTITY_OBSERVATION_V1", "scene": scene,
                "frame_index": frame_index, "t": float(t), "regions": sorted(regions, key=lambda row: row["lane"]),
                "exclusion_boxes": [list(row["box"]) for row in raw], "quality_flags": sorted(flags),
                "raw_candidate_count": len(raw), "unresolved_candidate_count": len(raw)-len(regions),
                "identity_validated": False, "model_eligible": False, "field_validation": "NOT_ESTABLISHED"}


def create_local_identity_provider(*, model_path, tesseract_path, tessdata_path,
                                   detector_kind="yolox", exclusions=(), min_observations=3,
                                   max_gap_seconds=.5):
    """Explicit local paths only; importing this module never loads/downloads assets."""
    detector = PinnedBoatDetector(model_path=model_path, detector_kind=detector_kind)
    reader = LocalTesseractNumberReader(tesseract_path=tesseract_path, tessdata_path=tessdata_path)
    return BoatIdentityProvider(detector=detector, number_reader=reader, exclusions=exclusions,
                                min_observations=min_observations, max_gap_seconds=max_gap_seconds)


def make_local_identity_extractor(*, model_path, tesseract_path, tessdata_path,
                                  detector_kind="yolox", exclusions=(), min_observations=3,
                                  max_gap_seconds=.5):
    """Configure local intake; instantiate isolated tracking state for each media.

    Assets load only when the returned extractor is called. Configured paths stay
    in this callable and are never added to its returned tracking report.
    """
    excluded = deepcopy(exclusions)

    def extract(path, *, options=None):
        provider = create_local_identity_provider(
            model_path=model_path, tesseract_path=tesseract_path, tessdata_path=tessdata_path,
            detector_kind=detector_kind, exclusions=deepcopy(excluded),
            min_observations=min_observations, max_gap_seconds=max_gap_seconds)
        from .boat_video_tracking import extract_tracks
        return extract_tracks(path, options=options, identity_provider=provider)

    return extract
