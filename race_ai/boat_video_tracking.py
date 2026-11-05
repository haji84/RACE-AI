"""Experimental local-video color candidates in a stabilized reference image.

This is classical CV input measurement, not verified boat identification, physical
speed, racer strength or a forecast. Achromatic lanes remain unresolved. Camera
fits and position errors are heuristic diagnostics, never certified uncertainty.
Only local regular media is read; both FFmpeg subprocesses restrict protocols and
demuxers. OpenCV is imported lazily for image analysis, never network decoding.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import tempfile
import time


_DEFAULTS = {"sampling_fps": 10.0, "water_roi": [0.03, 0.15, 0.97, 0.90],
             "min_area": 24, "max_area": 2000, "max_bytes": 268435456,
             "max_duration_seconds": 120.0, "max_decoded_frames": 3600,
             "max_pixels": 2073600, "max_dimension": 1920,
             "max_gap_seconds": 0.5, "processing_timeout_seconds": 120.0}
_PROTOCOL_ARGS = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,avi"]


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _options(options):
    if options is not None and not isinstance(options, dict):
        raise ValueError("options must be an object")
    if options and set(options) - set(_DEFAULTS):
        raise ValueError("unknown tracking option")
    result = dict(_DEFAULTS, **(options or {}))
    for key, value in result.items():
        if key == "water_roi":
            if (not isinstance(value, (list, tuple)) or len(value) != 4
                    or not all(_finite(v) for v in value)
                    or not 0 <= value[0] < value[2] <= 1
                    or not 0 <= value[1] < value[3] <= 1):
                raise ValueError("water_roi requires normalized x0,y0,x1,y1")
        elif not _finite(value) or value <= 0:
            raise ValueError(f"invalid positive option: {key}")
        elif key in ("min_area", "max_area", "max_bytes", "max_decoded_frames", "max_pixels", "max_dimension") and type(value) is not int:
            raise ValueError(f"integer option required: {key}")
    if result["sampling_fps"] > 60 or result["max_area"] < result["min_area"]:
        raise ValueError("invalid sampling or candidate area limits")
    return result


@contextmanager
def _local_media(path, options):
    raw = os.fspath(path)
    if not isinstance(raw, str) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw) or raw.startswith("//"):
        raise ValueError("only local regular media paths are accepted")
    candidate = Path(raw).absolute()
    if any(p.is_symlink() for p in (candidate, *candidate.parents)):
        raise ValueError("symlink media paths are not accepted")
    try:
        descriptor = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError("local regular media could not be opened") from exc
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("only local regular media is accepted")
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("only local regular media is accepted")
        if info.st_size > options["max_bytes"]:
            raise ValueError("media resource limit: max_bytes")
        header = source.read(64)
        container = ("avi" if header[:4] == b"RIFF" and header[8:12] == b"AVI " else
                     "matroska" if header[:4] == b"\x1aE\xdf\xa3" else
                     "mov" if header[4:8] == b"ftyp" else None)
        if container is None:
            raise ValueError("unsupported local media signature (playlists are rejected)")
        source.seek(0)
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        # Decode from a held descriptor, avoiding replacement of the validated path.
        source.seek(0)
        yield source, f"/proc/self/fd/{source.fileno()}", digest, container
        final = os.fstat(source.fileno())
        if (final.st_size, final.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
            raise ValueError("media changed during extraction")


def _probe_json(source, path, arguments, timeout, max_pixels):
    command = ["ffprobe", "-v", "error", *_PROTOCOL_ARGS, "-max_pixels", str(max_pixels),
               *arguments, "-of", "json", path]
    try:
        completed = subprocess.run(command, capture_output=True, check=True, timeout=timeout,
                                   pass_fds=(source.fileno(),))
        if completed.stderr.strip():
            raise ValueError("local media probe rejected malformed or resource-limited frames")
        return json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError("local media probe failed or exceeded resource timeout") from exc


def _probe_frames(source, path, timeout, max_frames, max_pixels):
    return _probe_json(source, path, ["-select_streams", "v:0", "-show_frames", "-show_entries",
                       "frame=pts_time,duration_time,pkt_duration_time,width,height", "-read_intervals",
                       f"%+#{max_frames+1}"], timeout, max_pixels).get("frames", [])


def _metadata(source, path, options):
    data = _probe_json(source, path, ["-show_streams", "-show_format"],
                       options["processing_timeout_seconds"], options["max_pixels"])
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        raise ValueError("no video stream")
    stream = streams[0]
    width, height = stream.get("width"), stream.get("height")
    if (type(width) is not int or type(height) is not int or min(width, height) < 32
            or max(width, height) > options["max_dimension"] or width * height > options["max_pixels"]):
        raise ValueError("media resource limit: decoded dimensions")
    for item in stream.get("side_data_list", []):
        if item.get("rotation", 0) != 0:
            raise ValueError("rotated media must be normalized explicitly before analysis")
    try:
        frame_count = int(stream.get("nb_frames", 0))
    except (ValueError, TypeError):
        frame_count = 0
    if frame_count > options["max_decoded_frames"]:
        raise ValueError("media resource limit: max_decoded_frames")
    frames = _probe_frames(source, path, options["processing_timeout_seconds"],
                           options["max_decoded_frames"], options["max_pixels"])
    if not frames or len(frames) > options["max_decoded_frames"]:
        raise ValueError("media resource limit: missing or excessive displayed frames")
    timestamps = []
    for frame in frames:
        if (frame.get("width"), frame.get("height")) != (width, height):
            raise ValueError("changing decoded frame dimensions are not supported")
        try:
            stamp = float(frame["pts_time"])
        except (TypeError, KeyError, ValueError) as exc:
            raise ValueError("actual display PTS required; no fps fallback") from exc
        if not math.isfinite(stamp) or (timestamps and stamp <= timestamps[-1]):
            raise ValueError("display PTS must be finite and strictly increasing")
        timestamps.append(stamp)
    # Container duration may be an absolute ending PTS (notably Matroska).
    # Use displayed-video PTS extent, with the final frame's explicit duration
    # when present. Never infer timing from an advertised frame rate.
    try:
        last_duration = float(frames[-1].get("duration_time", frames[-1].get("pkt_duration_time", 0)))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid displayed-frame duration") from exc
    if not math.isfinite(last_duration) or last_duration < 0:
        raise ValueError("invalid displayed-frame duration")
    duration = timestamps[-1] - timestamps[0] + last_duration
    if duration <= 0:
        raise ValueError("positive displayed-video duration evidence required")
    if duration > options["max_duration_seconds"]:
        raise ValueError("media resource limit: max_duration_seconds")
    return width, height, duration, timestamps


def _decode(source, path, width, height, options, np):
    command = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1", *_PROTOCOL_ARGS,
               "-max_pixels", str(options["max_pixels"]), "-noautorotate", "-i", path,
               "-map", "0:v:0", "-an", "-sn", "-dn", "-noautoscale",
               "-fps_mode", "passthrough", "-threads", "1", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
    size = width * height * 3
    deadline = time.monotonic() + options["processing_timeout_seconds"]
    try:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                       pass_fds=(source.fileno(),), bufsize=0)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    chunk = bytearray()
                    count = 0
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(max(0, remaining)):
                            raise ValueError("media resource limit: decoding timeout")
                        part = os.read(process.stdout.fileno(), min(size - len(chunk), 1048576))
                        if not part:
                            if chunk:
                                raise ValueError("incomplete decoded frame")
                            break
                        chunk.extend(part)
                        if len(chunk) == size:
                            count += 1
                            if count > options["max_decoded_frames"]:
                                raise ValueError("media resource limit: max_decoded_frames")
                            yield np.frombuffer(chunk, dtype=np.uint8).reshape(height, width, 3).copy()
                            chunk = bytearray()
                process.wait(timeout=max(0.01, deadline-time.monotonic()))
                if process.returncode:
                    raise ValueError("local media decode failed")
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.kill()
                    process.wait()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("local media decoder unavailable or timed out") from exc


def _masks(frame, roi, cv2, np):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    chromatic = (saturation >= 130) & (value >= 80) & (roi > 0)
    ranges = {3: ((hue <= 12) | (hue >= 168)), 4: ((hue >= 95) & (hue <= 135)),
              5: ((hue >= 18) & (hue <= 37)), 6: ((hue >= 40) & (hue <= 90))}
    return {lane: cv2.morphologyEx((chromatic & band).astype(np.uint8)*255,
            cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) for lane, band in ranges.items()}


def _camera(previous, current, previous_masks, current_masks, roi, cv2, np):
    quality = {"status": "INSUFFICIENT_BACKGROUND", "inlier_count": 0, "inlier_ratio": 0.0,
               "residual_rms_px": None, "spatial_coverage": 0.0, "grid_cells": 0}
    before, after = (cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in (previous, current))
    masks = []
    for colored in (previous_masks, current_masks):
        excluded = np.maximum.reduce(list(colored.values()))
        excluded = cv2.dilate(excluded, np.ones((21, 21), np.uint8))
        masks.append(cv2.bitwise_and(roi, cv2.bitwise_not(excluded)))
    points = cv2.goodFeaturesToTrack(before, maxCorners=400, qualityLevel=.02, minDistance=7,
                                    mask=masks[0], blockSize=5)
    quality["feature_count"] = 0 if points is None else len(points)
    if points is None or len(points) < 24:
        return None, quality, None
    params = dict(winSize=(21, 21), maxLevel=3,
                  criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01))
    moved, found, error = cv2.calcOpticalFlowPyrLK(before, after, points, None, **params)
    if moved is None or found is None:
        return None, quality, None
    returned, backward, _ = cv2.calcOpticalFlowPyrLK(after, before, moved, None, **params)
    if returned is None or backward is None or not np.isfinite(moved).all():
        return None, quality, None
    origin, destination = points.reshape(-1, 2), moved.reshape(-1, 2)
    height, width = before.shape
    inside = ((destination[:, 0] >= 0) & (destination[:, 0] < width) &
              (destination[:, 1] >= 0) & (destination[:, 1] < height))
    background = np.zeros(len(points), dtype=bool)
    bounded = destination[inside].astype(int)
    background[inside] = masks[1][bounded[:, 1], bounded[:, 0]] > 0
    usable = (found.ravel().astype(bool) & backward.ravel().astype(bool) & background &
              (error.ravel() < 20) & (np.linalg.norm(returned.reshape(-1, 2)-origin, axis=1) < 1))
    origin, destination = origin[usable], destination[usable]
    quality["tracked_count"] = len(origin)
    if len(origin) < 24:
        return None, quality, None
    homography, membership = cv2.findHomography(origin, destination, method=cv2.RANSAC,
                    ransacReprojThreshold=1.5, maxIters=2000, confidence=.995)
    if (homography is None or membership is None or not np.isfinite(homography).all()
            or abs(homography[2, 2]) < 1e-8):
        return None, quality, None
    homography /= homography[2, 2]
    inliers = membership.ravel().astype(bool)
    quality.update(inlier_count=int(inliers.sum()), inlier_ratio=float(inliers.mean()))
    if inliers.sum() < 20 or inliers.mean() < .75:
        return None, quality, None
    support = origin[inliers]
    quality["spatial_coverage"] = float(cv2.contourArea(cv2.convexHull(support)) / (width*height))
    quality["grid_cells"] = len({(min(3, int(x*4/width)), min(2, int(y*3/height))) for x, y in support})
    projected = cv2.perspectiveTransform(origin.reshape(-1, 1, 2), homography).reshape(-1, 2)
    residual = np.linalg.norm(projected - destination, axis=1)
    rms = float(np.sqrt(np.mean(residual[inliers]**2)))
    quality["residual_rms_px"] = rms
    corners = np.array([[0, 0], [width-1, 0], [0, height-1], [width-1, height-1]], dtype=np.float64)
    denominators = corners @ homography[2, :2] + homography[2, 2]
    projected_corners = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), homography).reshape(-1, 2)
    center = np.array([[width/2, height/2], [width/2+1, height/2], [width/2, height/2+1]], dtype=np.float64)
    projected_center = cv2.perspectiveTransform(center.reshape(-1, 1, 2), homography).reshape(-1, 2)
    jacobian = np.column_stack((projected_center[1]-projected_center[0], projected_center[2]-projected_center[0]))
    scales = np.linalg.svd(jacobian, compute_uv=False)
    rotation = abs(math.degrees(math.atan2(jacobian[1, 0], jacobian[0, 0])))
    if (quality["spatial_coverage"] < .20 or quality["grid_cells"] < 6 or rms > 1.0
            or not np.all((scales >= .95) & (scales <= 1.05)) or rotation > 8
            or np.any(denominators < .5) or np.any(denominators > 2)
            or np.linalg.det(jacobian) <= 0
            or np.max(np.linalg.norm(projected_corners-corners, axis=1)) > .15*math.hypot(width, height)):
        quality["status"] = "CAMERA_FIT_REJECTED"
        return None, quality, None
    warped = cv2.warpPerspective(before, homography, (width, height))
    common = (cv2.warpPerspective(masks[0], homography, (width, height)) > 250) & (masks[1] > 0)
    if not common.any():
        return None, quality, None
    difference = cv2.absdiff(warped, after)
    photometric = float(difference[common].mean())
    quality["photometric_mean_error"] = photometric
    if photometric > 14:
        quality["status"] = "SCENE_CHANGE_OR_BACKGROUND_MISMATCH"
        return None, quality, None
    quality["status"] = "ACCEPTED"
    quality["camera_model"] = "HOMOGRAPHY"
    quality["homography_previous_to_current"] = homography.tolist()
    motion = cv2.dilate((difference > 18).astype(np.uint8)*255, np.ones((5, 5), np.uint8))
    return homography, quality, motion


def _reference_point(transform, point, np):
    homogeneous = transform @ np.array([*point, 1.0])
    if not np.isfinite(homogeneous).all() or abs(homogeneous[2]) < 1e-8:
        raise ValueError("camera reference projection is not finite")
    return homogeneous[:2] / homogeneous[2]


def _candidates(masks, motion, options, cv2, np):
    found = {}
    for lane, mask in masks.items():
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if not options["min_area"] <= area <= options["max_area"]:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            if max(width/height, height/width) > 8 or min(width, height) < 3:
                continue
            component = np.zeros(mask.shape, np.uint8)
            cv2.drawContours(component, [contour], -1, 255, -1)
            changed = (0.0 if motion is None else
                       float(((component > 0) & (motion > 0)).sum() / (component > 0).sum()))
            moments = cv2.moments(contour)
            if not moments["m00"]:
                continue
            candidates.append({"point": [moments["m10"]/moments["m00"], moments["m01"]/moments["m00"]],
                               "box": [x, y, width, height], "area": area, "motion_fraction": changed})
        found[lane] = candidates
    # Nearby or overlapping colors cannot establish separate boat identities.
    ambiguous = set()
    for lane, candidates in found.items():
        for other, others in found.items():
            if other <= lane:
                continue
            for first in candidates:
                x, y, width, height = first["box"]
                for second in others:
                    a, b, w, h = second["box"]
                    if x-4 <= a+w and a-4 <= x+width and y-4 <= b+h and b-4 <= y+height:
                        ambiguous.update((lane, other))
    return found, ambiguous


def _provider_detections(provider, frame, roi, np):
    """Exclude every detected hull, including hulls whose number is unresolved."""
    detections = provider.detect(frame)
    if type(detections) is not list or len(detections) > 64:
        raise ValueError("bounded hull detections required")
    height, width = frame.shape[:2]
    exclusion = np.zeros((height, width), np.uint8)
    for detection in detections:
        if type(detection) is not dict:
            raise ValueError("invalid hull detection")
        x, y, w, h = _provider_box(detection.get("box"), width, height)
        exclusion[math.floor(y):math.ceil(y+h), math.floor(x):math.ceil(x+w)] = 255
    return detections, np.minimum(exclusion, roi)


def _provider_box(box, width, height):
    if (type(box) not in (list, tuple) or len(box) != 4 or not all(_finite(v) for v in box)):
        raise ValueError("invalid hull box")
    x, y, w, h = map(float, box)
    if not (0 <= x < x+w <= width and 0 <= y < y+h <= height and w >= 1 and h >= 1):
        raise ValueError("hull box outside media")
    return x, y, w, h


def _provider_candidates(observation, roi, motion, cv2, np):
    if type(observation) is not dict or type(observation.get("regions")) is not list or len(observation["regions"]) > 6:
        raise ValueError("invalid numbered hull observation")
    height, width = roi.shape
    found = {n: [] for n in range(1, 7)}
    for region in observation["regions"]:
        if (type(region) is not dict or type(region.get("lane")) is not int or not 1 <= region["lane"] <= 6
                or region.get("identity_status") != "NUMBER_TEMPORAL_CANDIDATE"
                or type(region.get("track_id")) is not str
                or re.fullmatch(r"T[0-9]{6,12}", region["track_id"]) is None
                or type(region.get("number_evidence")) is not dict):
            raise ValueError("invalid hull number evidence")
        x, y, w, h = _provider_box(region.get("box"), width, height)
        if w < 3 or h < 3:
            continue
        center = (x+w/2-.5, y+h/2-.5)
        if roi[min(height-1, int(center[1])), min(width-1, int(center[0]))] == 0:
            continue
        mask = np.zeros_like(roi)
        mask[math.floor(y):math.ceil(y+h), math.floor(x):math.ceil(x+w)] = 255
        changed = 0. if motion is None else float(((mask > 0) & (motion > 0)).sum()/(mask > 0).sum())
        found[region["lane"]].append({"point": center, "box": [x, y, w, h],
            "motion_fraction": changed, "track_id": region["track_id"],
            "number_evidence": json.loads(json.dumps(region["number_evidence"], allow_nan=False))})
    ambiguous = {lane for lane, rows in found.items() if len(rows) > 1}
    for lane, rows in found.items():
        for other, others in found.items():
            if other <= lane:
                continue
            for first in rows:
                x, y, w, h = first["box"]
                for second in others:
                    a, b, c, d = second["box"]
                    if min(x+w, a+c)+3 > max(x, a) and min(y+h, b+d)+3 > max(y, b):
                        ambiguous.update((lane, other))
    return found, ambiguous


def extract_tracks(path, *, options=None, identity_provider=None):
    """Return JSON-safe color candidates; absent detections are explicit nulls.

    Options are bounded processing limits, HSV component areas in image pixels,
    sampling_fps and a normalized water_roi [x0,y0,x1,y1]. Limits reject complete
    inputs rather than returning truncated tracks. Times use actual frame PTS
    relative to the first displayed PTS. Camera/occlusion discontinuities reset
    each lane's scene; no interpolation or zero filling is performed.
    """
    config = _options(options)
    if identity_provider is not None and not all(callable(getattr(identity_provider, name, None))
                                                  for name in ("detect", "identify", "metadata")):
        raise ValueError("a local hull and number provider is required")
    with _local_media(path, config) as (source, local_path, digest, container):
        width, height, duration, stamps = _metadata(source, local_path, config)
        try:
            import cv2
            import numpy as np
        except (ImportError, OSError) as exc:
            raise RuntimeError("optional OpenCV and numpy are required for local video tracking") from exc
        roi = np.zeros((height, width), np.uint8)
        x0, y0, x1, y1 = config["water_roi"]
        roi[math.ceil(y0*height):math.floor(y1*height), math.ceil(x0*width):math.floor(x1*width)] = 255
        tracks = [{"lane": lane, "identity_status": "COLOR_CANDIDATE" if identity_provider is None else
                   "NUMBER_TEMPORAL_CANDIDATE", "samples": []} for lane in range(1, 7)]
        states = {lane: {"scene": 0, "previous_valid": False, "previous_point": None,
                         "last_visible_point": None, "last_visible_t": None} for lane in range(1, 7)}
        color_occlusions = set()
        camera_estimates, flags = [], {"COLOR_DOES_NOT_VERIFY_BOAT_IDENTITY", "ACHROMATIC_LANES_UNRESOLVED",
                                       "SYNTHETIC_TESTS_DO_NOT_ESTABLISH_FIELD_VALIDATION", "POSITION_ERROR_HEURISTIC_UNCERTIFIED"}
        identity_observations, camera_scene = [], 0
        if identity_provider is not None:
            flags -= {"COLOR_DOES_NOT_VERIFY_BOAT_IDENTITY", "ACHROMATIC_LANES_UNRESOLVED"}
            flags.add("OCR_TEMPORAL_CANDIDATES_DO_NOT_VERIFY_BOAT_IDENTITY")
        previous, previous_masks, previous_t = None, None, None
        previous_candidates = None
        previous_transform = np.eye(3)
        transform = np.eye(3)
        drift_error = 0.0
        next_sample = -math.inf
        decoded_count = 0
        decoder = _decode(source, local_path, width, height, config, np)
        try:
            for frame_index, frame in enumerate(decoder):
                decoded_count += 1
                if frame_index >= len(stamps):
                    raise ValueError("decoded frame count differs from display PTS")
                t = stamps[frame_index]-stamps[0]
                if t + 1e-7 < next_sample:
                    continue
                next_sample = t + 1/config["sampling_fps"]
                masks = _masks(frame, roi, cv2, np)
                detections = None
                if identity_provider is not None:
                    detections, masks[0] = _provider_detections(identity_provider, frame, roi, np)
                camera_homography, motion = None, None
                camera = {"status": "REFERENCE_INITIALIZATION", "residual_rms_px": None}
                if previous is not None and t-previous_t <= config["max_gap_seconds"]:
                    camera_homography, camera, motion = _camera(previous, frame, previous_masks, masks, roi, cv2, np)
                elif previous is not None:
                    camera["status"] = "DISPLAY_PTS_GAP"
                camera.update(frame_index=frame_index, t=float(t))
                camera_estimates.append(camera)
                observation = None
                frame_sha256 = None
                if identity_provider is not None:
                    if previous is not None and camera_homography is None:
                        camera_scene += 1
                    observation = identity_provider.identify(frame, detections, t=float(t),
                        frame_index=frame_index, scene=camera_scene,
                        previous_to_current=camera_homography)
                    frame_sha256 = hashlib.sha256(frame.tobytes()).hexdigest()
                    observation = {**observation, "decoded_frame_sha256": frame_sha256}
                    identity_observations.append(json.loads(json.dumps(observation, allow_nan=False)))
                if camera_homography is not None:
                    transform = transform @ np.linalg.inv(camera_homography)
                    transform /= transform[2, 2]
                    drift_error += camera["residual_rms_px"]
                    candidates, ambiguous = (_candidates(masks, motion, config, cv2, np) if identity_provider is None else
                                             _provider_candidates(observation, roi, motion, cv2, np))
                    positions = {lane: _reference_point(transform, items[0]["point"], np)
                                 for lane, items in candidates.items() if len(items) == 1}
                    # A color replacing another nearby color is an occlusion, not
                    # evidence of a newly identified boat. Keep both missing until
                    # the original returns or both colors separate visibly.
                    for hidden, state in states.items():
                        if (hidden in positions or state["last_visible_point"] is None
                                or t-state["last_visible_t"] > config["max_gap_seconds"]):
                            continue
                        for visible, point in positions.items():
                            box = candidates[visible][0]["box"]
                            radius = max(24, math.hypot(box[2], box[3])*1.5)
                            if np.linalg.norm(point-state["last_visible_point"]) < radius:
                                color_occlusions.add((hidden, visible))
                    for hidden, visible in list(color_occlusions):
                        both_separate = (hidden in positions and visible in positions and
                                         np.linalg.norm(positions[hidden]-positions[visible]) > 32)
                        original_restored = hidden in positions and visible not in positions
                        if both_separate or original_restored:
                            color_occlusions.remove((hidden, visible))
                        else:
                            ambiguous.update((hidden, visible))
                else:
                    transform = np.eye(3)
                    drift_error = 0.0
                    candidates, ambiguous = (_candidates(masks, None, config, cv2, np) if identity_provider is None else
                                             _provider_candidates(observation, roi, None, cv2, np))
                    color_occlusions.clear()
                    for state in states.values():
                        state["last_visible_point"] = state["last_visible_t"] = None
                    if previous is not None:
                        flags.add("CAMERA_OR_TIME_DISCONTINUITY")
                for track in tracks:
                    lane = track["lane"]
                    state = states[lane]
                    sample = {"frame_index": frame_index, "t": float(t), "x": None, "y": None,
                              "scene": state["scene"], "valid": False, "position_error": None}
                    reason = ("ACHROMATIC_IDENTITY_AMBIGUOUS" if lane <= 2 and identity_provider is None else
                              camera["status"] if camera_homography is None else
                              "OVERLAPPING_COLOR_CANDIDATES" if lane in ambiguous else
                              "AMBIGUOUS_COLOR_CANDIDATES" if len(candidates.get(lane, [])) > 1 else
                              "NO_COLOR_MOTION_CANDIDATE")
                    if (lane > 2 or identity_provider is not None) and camera_homography is not None and lane not in ambiguous and len(candidates[lane]) == 1:
                        item = candidates[lane][0]
                        point = _reference_point(transform, item["point"], np)
                        prior = [] if previous_candidates is None else previous_candidates[lane]
                        prior_point = (_reference_point(previous_transform, prior[0]["point"], np)
                                       if len(prior) == 1 else None)
                        motion_floor = max(1.5, 3*camera["residual_rms_px"])
                        independent_motion = (prior_point is not None and item["motion_fraction"] >= .12
                                              and np.linalg.norm(point-prior_point) > motion_floor)
                        # A large jump within a continuous segment is an association failure.
                        if (identity_provider is not None and state.get("identity_track_id") is not None
                                and state["identity_track_id"] != item["track_id"]):
                            reason = "IDENTITY_TRACK_DISCONTINUITY"
                        elif not independent_motion:
                            reason = "INDEPENDENT_MOTION_NOT_OBSERVED"
                        elif state["previous_point"] is not None and state["previous_valid"] and np.linalg.norm(point-state["previous_point"]) > .15*math.hypot(width, height):
                            reason = "ASSOCIATION_JUMP"
                        else:
                            sample.update(valid=True, x=float(point[0]), y=float(point[1]),
                                          position_error=float(1.0+drift_error))
                            if identity_provider is not None:
                                sample.update(identity_track_id=item["track_id"], camera_scene=camera_scene,
                                              identity_evidence=item["number_evidence"], frame_sha256=frame_sha256)
                    if not sample["valid"]:
                        sample["reason"] = reason
                        if state["previous_valid"] or (camera_homography is None and previous is not None):
                            state["scene"] += 1
                            sample["scene"] = state["scene"]
                        state["previous_point"] = None
                        if identity_provider is not None:
                            state["identity_track_id"] = None
                    else:
                        state["previous_point"] = np.array([sample["x"], sample["y"]])
                        state["last_visible_point"] = state["previous_point"]
                        state["last_visible_t"] = t
                        if identity_provider is not None:
                            state["identity_track_id"] = sample["identity_track_id"]
                    state["previous_valid"] = sample["valid"]
                    track["samples"].append(sample)
                previous, previous_masks, previous_t = frame, masks, t
                previous_candidates = candidates
                previous_transform = transform.copy()
        finally:
            decoder.close()
        if decoded_count != len(stamps):
            raise ValueError("decoded frame count differs from display PTS")
        result = {"schema_version": "RACE_AI_BOAT_VIDEO_TRACKS_V1", "media_sha256": digest,
                "width": width, "height": height, "duration_seconds": duration if duration is not None else stamps[-1]-stamps[0],
                "timeline_source": "MEDIA_PTS", "media_pts_origin_seconds": stamps[0],
                "coordinate_space": "REFERENCE_IMAGE_PX", "model_eligible": False,
                "validation_status": "UNVALIDATED", "tracks": tracks,
                "quality": {"flags": sorted(flags), "camera_estimates": camera_estimates,
                            "decoded_frame_count": decoded_count, "sampled_frame_count": len(camera_estimates),
                            "water_roi": list(config["water_roi"]), "container": container,
                            "position_error_scope": "ACCUMULATED_CAMERA_RESIDUAL_PLUS_ONE_PIXEL_HEURISTIC_UNCERTIFIED",
                            "valid_sample_counts": {str(t["lane"]): sum(p["valid"] for p in t["samples"]) for t in tracks}}}
        if identity_provider is not None:
            result["quality"].update(identity_provider=identity_provider.metadata(),
                                      identity_observations=identity_observations)
        return result
