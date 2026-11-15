"""Pure agreement scores for numbered regions and independent frame references.

No decoding, files, training, calibration or forecast mutation occurs here.
Reference classes and engine metadata are declarations, not authentication.
AI visual references remain distinct from human annotations and controlled
fixtures. Geometry is matched before identity; these scores do not certify
boat identity, physical measurements, strength or prospective improvement.

REFERENCE_V1 frames use original-resolution [x,y,width,height] boxes and the
tracker's decoded BGR24 pixel hash, never an exported PNG/JPEG file hash.
WHOLE_MEDIA permits one partition; mixed roles require WITHIN_CLIP. Sparse
labels cannot establish false positives outside their annotated objects or
continuous tracking through unlabeled frames.
"""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import math
import re

from .actions_contract import digest
from .boat_video_identity import MODEL_SPECS


REFERENCE_SCHEMA = "RACE_AI_BOAT_VIDEO_REFERENCE_V1"
SCHEMA = "RACE_AI_BOAT_VIDEO_BENCHMARK_V1"
_ERROR = "BOAT_VIDEO_BENCHMARK_REJECTED"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_REFERENCE_FIELDS = set("schema_version media_sha256 width height media_class reference_class "
    "human_verified blind_to_predictions split_scope split_frozen_before_predictions frames".split())
_FRAME_FIELDS = set("frame_index t decoded_frame_sha256 continuity_group exhaustive partition boats".split())


def _need(condition):
    if not condition:
        raise ValueError(_ERROR)


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value) is not None)


def _box(box, width, height):
    _need(type(box) is list and len(box) == 4 and all(_finite(n) for n in box))
    x, y, w, h = box
    _need(0 <= x < x+w <= width and 0 <= y < y+h <= height and w > 0 and h > 0 and w*h > 0)


def validate_reference(reference):
    """Validate declared reference/split provenance; return a defensive copy.

    Human annotation is a separate declared class, not a verified-human flag.
    Reference creation must happen outside this scorer without reading model
    predictions. The blind/frozen flags record that declaration only.
    """
    try:
        _need(type(reference) is dict and set(reference) == _REFERENCE_FIELDS)
        r = reference
        _need(r["schema_version"] == REFERENCE_SCHEMA)
        _sha(r["media_sha256"])
        _need(all(type(r[k]) is int and 0 < r[k] <= 16384 for k in ("width", "height")))
        _need(r["media_class"] in ("REAL", "SYNTHETIC") and r["reference_class"] in
              ("INDEPENDENT_AI_VISUAL_REFERENCE", "HUMAN_ANNOTATION_DECLARED", "CONTROLLED_FIXTURE"))
        _need(r["human_verified"] is False and type(r["blind_to_predictions"]) is bool and
              type(r["split_frozen_before_predictions"]) is bool)
        _need(r["reference_class"] != "INDEPENDENT_AI_VISUAL_REFERENCE" or r["blind_to_predictions"])
        _need(r["split_scope"] in ("WHOLE_MEDIA", "WITHIN_CLIP"))
        _need(type(r["frames"]) is list and 0 < len(r["frames"]) <= 20000)
        last_index, last_t, roles = -1, -1, set()
        for frame in r["frames"]:
            _need(type(frame) is dict and _FRAME_FIELDS <= set(frame) <= _FRAME_FIELDS | {"image_file_sha256"})
            index, t = frame["frame_index"], frame["t"]
            _need(type(index) is int and index > last_index and _finite(t) and t > last_t and t >= 0)
            last_index, last_t = index, t
            _sha(frame["decoded_frame_sha256"])
            if "image_file_sha256" in frame:
                _sha(frame["image_file_sha256"])
            _need(type(frame["continuity_group"]) is str and _LABEL.fullmatch(frame["continuity_group"]) is not None)
            _need(type(frame["exhaustive"]) is bool and frame["partition"] in ("DEVELOPMENT", "HELDOUT"))
            roles.add(frame["partition"])
            _need(type(frame["boats"]) is list and len(frame["boats"]) <= 6)
            lanes = set()
            for boat in frame["boats"]:
                _need(type(boat) is dict and set(boat) == {"box", "lane", "readability"})
                _box(boat["box"], r["width"], r["height"])
                lane = boat["lane"]
                _need((lane is None and boat["readability"] == "UNREADABLE") or
                      (type(lane) is int and 1 <= lane <= 6 and boat["readability"] == "READABLE"))
                _need(lane is None or lane not in lanes)
                lanes.add(lane)
        _need(r["split_scope"] != "WHOLE_MEDIA" or len(roles) == 1)
        return deepcopy(r)
    except (KeyError, TypeError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None


def _engine(quality, supplied):
    provider = quality.get("identity_provider", {})
    provider = provider if type(provider) is dict else {}
    detector, reader = provider.get("detector", {}), provider.get("number_reader", {})
    detector = detector if type(detector) is dict else {}
    reader = reader if type(reader) is dict else {}
    engines = (detector.get("engine"), reader.get("engine"))
    inferred = "UNKNOWN"
    if any(type(e) is str and e.startswith("INJECTED_") for e in engines):
        inferred = "CONTROLLED"
    elif (engines == ("OPENCV_DNN_CPU", "TESSERACT_LOCAL") and
          detector.get("model_sha256") in {row["sha256"] for row in MODEL_SPECS.values()} and
          all(type(reader.get(k)) is str and _SHA.fullmatch(reader[k]) for k in ("engine_sha256", "language_sha256"))):
        inferred = "PINNED"
    choice = supplied.get("engine_class", inferred)
    _need(choice in ("PINNED", "CONTROLLED", "UNKNOWN") and (choice != "PINNED" or inferred == "PINNED"))
    _need(inferred != "CONTROLLED" or choice != "UNKNOWN")
    return choice


def _observations(tracking, reference, *, hulls=False):
    _need(type(tracking) is dict and tracking.get("schema_version") == "RACE_AI_BOAT_VIDEO_TRACKS_V1")
    _need(all(tracking.get(k) == reference[k] for k in ("media_sha256", "width", "height")))
    _need(tracking.get("timeline_source") == "MEDIA_PTS" and tracking.get("model_eligible") is False and
          tracking.get("validation_status") == "UNVALIDATED")
    quality = tracking.get("quality")
    _need(type(quality) is dict)
    rows = quality.get("identity_observations", [])
    _need(type(rows) is list and len(rows) <= 20000)
    last_index, last_t = -1, -1
    for row in rows:
        _need(type(row) is dict and type(row.get("frame_index")) is int and row["frame_index"] > last_index)
        _need(_finite(row.get("t")) and row["t"] >= 0 and row["t"] > last_t)
        last_index, last_t = row["frame_index"], row["t"]
        _sha(row.get("decoded_frame_sha256"))
        flags = row.get("quality_flags", [])
        _need(type(flags) is list and len(flags) <= 100 and
              all(type(flag) is str and _LABEL.fullmatch(flag) is not None for flag in flags))
        if hulls:
            if "exclusion_boxes" in row:
                boxes = row["exclusion_boxes"]
                _need(type(boxes) is list and len(boxes) <= 64)
                for box in boxes:
                    _box(box, reference["width"], reference["height"])
            continue
        regions = row.get("regions")
        _need(type(regions) is list and len(regions) <= 64)
        for region in regions:
            _need(type(region) is dict and type(region.get("lane")) is int and 1 <= region["lane"] <= 6)
            _box(region.get("box"), reference["width"], reference["height"])
            _need(type(region.get("track_id")) is str and _LABEL.fullmatch(region["track_id"]) is not None)
    return quality, rows


def _iou(a, b):
    overlap = max(0., min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0])) * max(
        0., min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))
    return overlap / (a[2]*a[3]+b[2]*b[3]-overlap)


def _matches(regions, boats, threshold):
    """Maximum cardinality, then total IoU, then deterministic index order."""
    overlaps = [[_iou(r["box"], b["box"]) for b in boats] for r in regions]

    @lru_cache(None)
    def solve(index, used):
        if index == len(regions):
            return 0, 0., ()
        best = solve(index+1, used)
        for j, overlap in enumerate(overlaps[index]):
            if used & (1 << j) or overlap < threshold:
                continue
            count, total, pairs = solve(index+1, used | (1 << j))
            candidate = count+1, total+overlap, ((index, j),)+pairs
            if (-candidate[0], -candidate[1], candidate[2]) < (-best[0], -best[1], best[2]):
                best = candidate
        return best

    return solve(0, 0)[2]


def _metrics():
    fields = ("evaluated_frames matched_regions false_positive_regions missed_reference_boats "
              "reference_visible_boats wrong_id_matches identity_unknown_matches unmatched_predictions_excluded "
              "whole_six_eligible_frames whole_six_correct_frames anonymous_id_switches number_id_switches "
              "fragmentations matched_identity_transitions").split()
    result = dict.fromkeys(fields, 0)
    result["lanes"] = {str(n): dict.fromkeys(("correct", "predictions_scored", "reference_visible",
                          "wrong_id_predictions", "false_positives"), 0) for n in range(1, 7)}
    result["confusion"] = {str(n): dict.fromkeys(map(str, range(1, 7)), 0) for n in range(1, 7)}
    return result


def _score_frame(metrics, regions, frame, pairs):
    boats = frame["boats"]
    metrics["evaluated_frames"] += 1
    metrics["reference_visible_boats"] += len(boats)
    metrics["matched_regions"] += len(pairs)
    metrics["missed_reference_boats"] += len(boats)-len(pairs)
    matched = {i for i, _ in pairs}
    known_matches = {}
    for boat in boats:
        if boat["lane"] is not None:
            metrics["lanes"][str(boat["lane"])]["reference_visible"] += 1
    for i, j in pairs:
        truth, prediction = boats[j]["lane"], regions[i]["lane"]
        if truth is None:
            metrics["identity_unknown_matches"] += 1
            continue
        known_matches[truth] = regions[i]
        lane = metrics["lanes"][str(prediction)]
        lane["predictions_scored"] += 1
        metrics["confusion"][str(truth)][str(prediction)] += 1
        if truth == prediction:
            lane["correct"] += 1
        else:
            lane["false_positives"] += 1
            lane["wrong_id_predictions"] += 1
            metrics["wrong_id_matches"] += 1
    for i, region in enumerate(regions):
        if i not in matched:
            if frame["exhaustive"]:
                metrics["false_positive_regions"] += 1
                lane = metrics["lanes"][str(region["lane"])]
                lane["predictions_scored"] += 1
                lane["false_positives"] += 1
            else:
                metrics["unmatched_predictions_excluded"] += 1
    if frame["exhaustive"] and {b["lane"] for b in boats} == set(range(1, 7)):
        metrics["whole_six_eligible_frames"] += 1
        if len(regions) == len(known_matches) == 6 and all(lane == row["lane"] for lane, row in known_matches.items()):
            metrics["whole_six_correct_frames"] += 1
    return known_matches


def _finish(metrics):
    for row in metrics["lanes"].values():
        row["misses"] = row["reference_visible"]-row["correct"]
        row["precision"] = row["correct"]/row["predictions_scored"] if row["predictions_scored"] else None
        row["coverage"] = row["correct"]/row["reference_visible"] if row["reference_visible"] else None
    denominator = metrics["whole_six_eligible_frames"]
    metrics["whole_six_accuracy"] = metrics["whole_six_correct_frames"]/denominator if denominator else None


def benchmark_identity(tracking, reference, *, configuration=None):
    """Score supplied numbered regions against declared, pixel-bound labels.

    Config accepts iou_threshold (default .5), engine_class and a maximum
    transition gap in seconds (default .5). Engine metadata remains unverified.
    Empty regions are observed misses; absent observation mode is UNAVAILABLE.
    Reference frames not supplied by the sampler are explicit missing inputs.
    Unknown identity matches and unmatched sparse predictions are excluded from
    identity precision. Switches need consecutive scored observations in the
    same labeled continuity group/partition; observed misses cause fragments.
    """
    try:
        ref = validate_reference(reference)
        config = {} if configuration is None else deepcopy(configuration)
        _need(type(config) is dict and set(config) <= {"iou_threshold", "engine_class", "max_transition_gap_seconds"})
        threshold, gap = config.get("iou_threshold", .5), config.get("max_transition_gap_seconds", .5)
        _need(_finite(threshold) and 0 < threshold <= 1 and _finite(gap) and gap > 0)
        quality, observations = _observations(tracking, ref)
        engine_class = _engine(quality, config)
        config.update(iou_threshold=threshold, max_transition_gap_seconds=gap, engine_class=engine_class)
        frames = {row["frame_index"]: (n, row) for n, row in enumerate(ref["frames"])}
        scored = set(frames).intersection(row["frame_index"] for row in observations)
        heldout = any(row["partition"] == "HELDOUT" for row in ref["frames"])
        report = dict(schema_version=SCHEMA, media_sha256=ref["media_sha256"],
            reference_sha256=digest(ref), tracking_sha256=digest(tracking), configuration=config,
            media_class=ref["media_class"], reference_class=ref["reference_class"], human_verified=False,
            blind_to_predictions=ref["blind_to_predictions"], reference_authentication="NOT_ESTABLISHED",
            engine_class=engine_class, engine_metadata_authenticated=False, real_engine_performance_established=False,
            split_scope=ref["split_scope"], split_frozen_before_predictions=ref["split_frozen_before_predictions"],
            disjoint_source_heldout=False, heldout_scope=("NOT_FROZEN_BEFORE_PREDICTIONS" if not
                ref["split_frozen_before_predictions"] else "WITHIN_CLIP_ONLY" if ref["split_scope"] == "WITHIN_CLIP"
                else "DECLARED_WHOLE_MEDIA") if heldout else "NONE",
            prediction_scope="NUMBERED_REGIONS_NOT_ALL_HULL_DETECTIONS", status="UNAVAILABLE" if not scored else
                "PARTIAL" if len(scored) != len(frames) else "SCORED",
            reference_frames=len(frames), reference_frames_without_predictions=len(frames)-len(scored),
            unlabeled_prediction_frames=sum(row["frame_index"] not in frames for row in observations),
            quality_flag_counts=dict(sorted(Counter(flag for row in observations for flag in
                set(row.get("quality_flags", []))).items())),
            partitions=None, production_eligible=False, accuracy_improvement_proven=False)
        if scored:
            partitions = {row["partition"]: _metrics() for row in ref["frames"]}
            state, previous = {}, None
            for observation in observations:
                if observation["frame_index"] not in frames:
                    state, previous = {}, None
                    continue
                position, frame = frames[observation["frame_index"]]
                _need(observation["t"] == frame["t"] and
                      observation["decoded_frame_sha256"] == frame["decoded_frame_sha256"])
                continuity = (frame["continuity_group"], frame["partition"])
                if previous is None or previous[0]+1 != position or previous[1] != continuity or frame["t"]-previous[2] > gap:
                    state = {}
                metrics = partitions[frame["partition"]]
                regions = observation["regions"]
                known = _score_frame(metrics, regions, frame, _matches(regions, frame["boats"], threshold))
                current = {}
                for boat in frame["boats"]:
                    lane = boat["lane"]
                    if lane is None:
                        continue
                    seen, old = state.get(lane, (False, None))
                    row = known.get(lane)
                    if row is not None:
                        if old is not None:
                            metrics["matched_identity_transitions"] += 1
                            metrics["anonymous_id_switches"] += int(old[0] != row["track_id"])
                            metrics["number_id_switches"] += int(old[1] != row["lane"])
                        elif seen:
                            metrics["fragmentations"] += 1
                        current[lane] = (True, (row["track_id"], row["lane"]))
                    else:
                        current[lane] = (seen, None)
                state, previous = current, (position, continuity, frame["t"])
            for metrics in partitions.values():
                _finish(metrics)
            report["partitions"] = partitions
        report["benchmark_sha256"] = digest(report)
        return report
    except (KeyError, TypeError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None


def benchmark_hulls(tracking, reference, *, configuration=None):
    """Measure raw hull-candidate geometry, never identities or strength.

    ``exclusion_boxes`` contains all detector candidates BEFORE overlay and
    identity filtering. Empty boxes are observed misses; omitted raw data is
    unavailable input. Unknown numeral references remain useful hull targets.
    Sparse references exclude unmatched predictions from precision. Config
    accepts iou_threshold (default .5) and the same declared engine_class as
    benchmark_identity. This function does not evaluate numbered regions.
    """
    try:
        ref = validate_reference(reference)
        config = {} if configuration is None else deepcopy(configuration)
        _need(type(config) is dict and set(config) <= {"iou_threshold", "engine_class"})
        threshold = config.get("iou_threshold", .5)
        _need(_finite(threshold) and 0 < threshold <= 1)
        quality, observations = _observations(tracking, ref, hulls=True)
        engine_class = _engine(quality, config)
        config.update(iou_threshold=threshold, engine_class=engine_class)
        frames = {row["frame_index"]: row for row in ref["frames"]}
        scored = set()
        partitions = {}
        for observation in observations:
            frame = frames.get(observation["frame_index"])
            if frame is None:
                continue
            _need(observation["t"] == frame["t"] and
                  observation["decoded_frame_sha256"] == frame["decoded_frame_sha256"])
            if "exclusion_boxes" not in observation:
                continue
            scored.add(frame["frame_index"])
            metrics = partitions.setdefault(frame["partition"], dict.fromkeys(
                ("evaluated_frames", "reference_visible_boats", "matched_regions", "false_positive_regions",
                 "missed_reference_boats", "predictions_scored", "unmatched_predictions_excluded"), 0))
            regions = [{"box": box} for box in observation["exclusion_boxes"]]
            matched = len(_matches(regions, frame["boats"], threshold))
            unmatched = len(regions)-matched
            false_positives = unmatched if frame["exhaustive"] else 0
            metrics["evaluated_frames"] += 1
            metrics["reference_visible_boats"] += len(frame["boats"])
            metrics["matched_regions"] += matched
            metrics["false_positive_regions"] += false_positives
            metrics["missed_reference_boats"] += len(frame["boats"])-matched
            metrics["predictions_scored"] += matched+false_positives
            metrics["unmatched_predictions_excluded"] += unmatched-false_positives
        for metrics in partitions.values():
            metrics["precision"] = (metrics["matched_regions"]/metrics["predictions_scored"]
                                    if metrics["predictions_scored"] else None)
            metrics["coverage"] = (metrics["matched_regions"]/metrics["reference_visible_boats"]
                                   if metrics["reference_visible_boats"] else None)
        heldout = any(row["partition"] == "HELDOUT" for row in ref["frames"])
        report = dict(schema_version="RACE_AI_BOAT_VIDEO_HULL_BENCHMARK_V1", media_sha256=ref["media_sha256"],
            reference_sha256=digest(ref), tracking_sha256=digest(tracking), configuration=config,
            scope="HULL_CANDIDATE_COVERAGE_ONLY", prediction_scope="RAW_HULL_EXCLUSION_BOXES_BEFORE_OVERLAY_FILTER",
            identity_evaluated=False, media_class=ref["media_class"], reference_class=ref["reference_class"],
            human_verified=False, blind_to_predictions=ref["blind_to_predictions"],
            reference_authentication="NOT_ESTABLISHED", engine_class=engine_class,
            engine_metadata_authenticated=False, real_engine_performance_established=False,
            split_scope=ref["split_scope"], split_frozen_before_predictions=ref["split_frozen_before_predictions"],
            disjoint_source_heldout=False, heldout_scope=("NOT_FROZEN_BEFORE_PREDICTIONS" if not
                ref["split_frozen_before_predictions"] else "WITHIN_CLIP_ONLY" if ref["split_scope"] == "WITHIN_CLIP"
                else "DECLARED_WHOLE_MEDIA") if heldout else "NONE",
            status="UNAVAILABLE" if not scored else "PARTIAL" if len(scored) != len(frames) else "SCORED",
            reference_frames=len(frames), reference_frames_without_predictions=len(frames)-len(scored),
            unlabeled_prediction_frames=sum(row["frame_index"] not in frames for row in observations),
            quality_flag_counts=dict(sorted(Counter(flag for row in observations for flag in
                set(row.get("quality_flags", []))).items())),
            partitions=partitions or None, production_eligible=False, accuracy_improvement_proven=False)
        report["benchmark_sha256"] = digest(report)
        return report
    except (KeyError, TypeError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None
