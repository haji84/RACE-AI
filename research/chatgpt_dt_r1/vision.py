"""CPU candidate detection and anonymous tracking from legally supplied frames.

HSV bands are supplied from caller-reviewed examples. There are no default
rider colours, helmet-to-car rules, downloaded weights, or learned detector.
Connected components are image candidates, not proof of a rider. Anonymous
tracklets use Hungarian assignment with motion, shape, gap and cut guards.

Automatic centroids remain AI estimates and cannot be used as measured wheel
crossings. A reviewed identity mapping bound to this exact track SHA, reviewed
wheel points bound to exact frame SHAs, and the observations module's verified
event-clock checks are required for reviewed timing. Receipt validation here
checks binding and metadata; it is not an independent identity attestation.

CLI: python -m research.chatgpt_dt_r1.vision process --manifest frames.json
     --config detector.json --output private-candidates.json
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.optimize import linear_sum_assignment

from .observations import Gate, Provenance, SourceKind, TrackSample, VideoTimingConfig, extract_crossings, finite


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class HSVBand:
    """Normalized hue/saturation/value thresholds; hue may wrap through zero."""
    name: str
    hue_min: float
    hue_max: float
    saturation_min: float
    value_min: float
    saturation_max: float = 1.
    value_max: float = 1.

    def __post_init__(self):
        if not self.name:
            raise ValueError("A caller-defined calibration band name is required")
        for key in ("hue_min","hue_max","saturation_min","saturation_max","value_min","value_max"):
            finite(getattr(self,key),key,low=0,high=1)
        if self.saturation_min>self.saturation_max or self.value_min>self.value_max:
            raise ValueError("HSV lower bounds cannot exceed upper bounds")


@dataclass(frozen=True)
class DetectorConfig:
    bands: tuple[HSVBand, ...]
    roi_xyxy: tuple[int,int,int,int] | None = None
    min_area_px: int = 4
    max_area_px: int = 10000
    min_aspect_ratio: float = .2
    max_aspect_ratio: float = 5.
    min_fill_ratio: float = .1
    opening_iterations: int = 0
    closing_iterations: int = 0
    overlap_iou_threshold: float = .7

    def __post_init__(self):
        bands = tuple(b if isinstance(b,HSVBand) else HSVBand(**b) for b in self.bands)
        object.__setattr__(self,"bands",bands)
        if not bands or len({b.name for b in bands})!=len(bands):
            raise ValueError("Distinct caller-calibrated HSV bands are required")
        for key in ("min_area_px","max_area_px","opening_iterations","closing_iterations"):
            value = getattr(self,key)
            if type(value) is not int or value<0:
                raise ValueError(key+" must be a nonnegative integer")
        if self.min_area_px<1 or self.max_area_px<self.min_area_px:
            raise ValueError("Component area bounds must be positive and ordered")
        finite(self.min_aspect_ratio,"minimum aspect",low=0)
        finite(self.max_aspect_ratio,"maximum aspect",low=self.min_aspect_ratio)
        finite(self.min_fill_ratio,"minimum fill",low=0,high=1)
        finite(self.overlap_iou_threshold,"overlap threshold",low=0,high=1)
        if self.roi_xyxy is not None and (len(self.roi_xyxy)!=4 or any(type(x) is not int for x in self.roi_xyxy)):
            raise ValueError("ROI must contain four integer image coordinates")


@dataclass(frozen=True)
class TrackingConfig:
    max_distance_px: float = 30.
    max_gap_seconds: float = .3
    max_missed_frames: int = 2
    max_speed_px_s: float = 1000.
    max_area_ratio: float = 2.5
    ambiguity_margin_px: float = 2.
    scene_cut_threshold: float | None = .4

    def __post_init__(self):
        for key in ("max_distance_px","max_gap_seconds","max_speed_px_s"):
            if finite(getattr(self,key),key,low=0)==0:
                raise ValueError(key+" must be positive")
        finite(self.max_area_ratio,"maximum area ratio",low=1)
        finite(self.ambiguity_margin_px,"ambiguity margin",low=0)
        if type(self.max_missed_frames) is not int or self.max_missed_frames<0:
            raise ValueError("Maximum missed frames must be a nonnegative integer")
        if self.scene_cut_threshold is not None:
            finite(self.scene_cut_threshold,"scene-cut threshold",low=0,high=1)


@dataclass(frozen=True)
class CandidateDetection:
    band: str
    bbox: tuple[int,int,int,int]
    centroid: tuple[float,float]
    area_px: int
    fill_ratio: float


def _iou(a,b):
    x0,y0,x1,y1 = max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])
    overlap = max(0,x1-x0)*max(0,y1-y0)
    area = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap
    return overlap/area if area else 0.


def detect_candidates(image, config: DetectorConfig) -> list[CandidateDetection]:
    """Calculate colour-mask components and geometry directly from actual pixels."""
    if not isinstance(image,Image.Image):
        with Image.open(image) as source:
            return detect_candidates(source.convert("RGB"),config)
    width,height = image.size
    roi = config.roi_xyxy or (0,0,width,height)
    x0,y0,x1,y1 = roi
    if not 0<=x0<x1<=width or not 0<=y0<y1<=height:
        raise ValueError("ROI must lie within the actual frame")
    hsv = np.asarray(image.convert("HSV"),dtype=np.float64)/255.
    hue,saturation,value = hsv[:,:,0],hsv[:,:,1],hsv[:,:,2]
    within = np.zeros((height,width),dtype=bool)
    within[y0:y1,x0:x1] = True
    candidates = []
    for band in config.bands:
        hue_mask = ((hue>=band.hue_min)&(hue<=band.hue_max) if band.hue_min<=band.hue_max
                    else (hue>=band.hue_min)|(hue<=band.hue_max))
        mask = within & hue_mask & (saturation>=band.saturation_min) & (saturation<=band.saturation_max)
        mask &= (value>=band.value_min)&(value<=band.value_max)
        if config.opening_iterations:
            mask = ndimage.binary_opening(mask,iterations=config.opening_iterations)
        if config.closing_iterations:
            mask = ndimage.binary_closing(mask,iterations=config.closing_iterations)&within
        components,_ = ndimage.label(mask,structure=np.ones((3,3),dtype=np.uint8))
        for component_id,box in enumerate(ndimage.find_objects(components),1):
            if box is None:
                continue
            ys,xs = box
            pixels_y,pixels_x = np.nonzero(components[box]==component_id)
            area = len(pixels_x)
            bbox = (xs.start,ys.start,xs.stop,ys.stop)
            aspect = (xs.stop-xs.start)/(ys.stop-ys.start)
            fill = area/((xs.stop-xs.start)*(ys.stop-ys.start))
            if not (config.min_area_px<=area<=config.max_area_px and
                    config.min_aspect_ratio<=aspect<=config.max_aspect_ratio and fill>=config.min_fill_ratio):
                continue
            candidates.append(CandidateDetection(band.name,bbox,
                (float(pixels_x.mean()+xs.start),float(pixels_y.mean()+ys.start)),area,float(fill)))
    # Overlapping calibration bands must not multiply the same image component.
    unique = []
    for candidate in sorted(candidates,key=lambda d:(-d.area_px,-d.fill_ratio,d.band,d.centroid)):
        if all(_iou(candidate.bbox,other.bbox)<=config.overlap_iou_threshold for other in unique):
            unique.append(candidate)
    return sorted(unique,key=lambda d:(d.centroid[0],d.centroid[1],d.band))


def _frame_path(root,filename):
    if not isinstance(filename,str) or not filename or Path(filename).is_absolute():
        raise ValueError("Frame manifest must use local relative image paths")
    path = (root/filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Frame path escapes the manifest directory")
    return path


def _append_detection(state,detection,*,index,time,frame_sha256):
    missed = state["missed"]
    if state["samples"]:
        previous = state["samples"][-1]
        dt = time-previous["t_seconds"]
        state["velocity"] = ((detection.centroid[0]-previous["x"])/dt,(detection.centroid[1]-previous["y"])/dt)
    state["samples"].append({"frame_index":index,"t_seconds":time,"x":detection.centroid[0],
        "y":detection.centroid[1],"bbox":list(detection.bbox),"area_px":detection.area_px,
        "fill_ratio":detection.fill_ratio,"band":detection.band,"occluded":bool(missed),
        "gap_before_frames":missed,"frame_sha256":frame_sha256,"source_kind":"ai_estimate"})
    state["missed"] = 0


def track_frames(manifest, detector_config: DetectorConfig, tracking_config: TrackingConfig, *, frame_root):
    """Detect each supplied image, then associate anonymous motion-consistent tracklets.

    Predicted positions are used only for assignment, never emitted as observed
    pixels. Ambiguous components receive no identity continuation. Missing frames
    and recovered tracks are explicit; a cut always starts fresh track IDs.
    """
    if not re.fullmatch(r"[0-9a-f]{64}",str(manifest.get("source_sha256",""))):
        raise ValueError("The original video SHA256 is required")
    entries = manifest.get("frames")
    if not isinstance(entries,list):
        raise ValueError("The local frame manifest must contain a frame list")
    root = Path(frame_root).resolve()
    quality = {key:0 for key in ("processed_frames","missing_frames","detected_candidates","matched_detections",
        "new_tracks","ambiguous_detections","occluded_track_frames","expired_tracks","camera_cut_resets")}
    active,all_tracks,frames = {},[],[]
    previous_time = None
    previous_signature = previous_camera = previous_shot = previous_size = None
    pending_cut = False
    epoch,serial = 0,0
    for index,entry in enumerate(entries):
        time = finite(entry.get("pts_seconds"),"source frame PTS")
        if previous_time is not None and time<=previous_time:
            raise ValueError("Frame manifest PTS must strictly increase; do not interpolate reordered frames")
        previous_time = time
        camera = str(entry.get("camera_id") or "unreviewed-camera")
        declared_shot = entry.get("shot_id")
        if "camera_cut" in entry and type(entry["camera_cut"]) is not bool:
            raise ValueError("Declared camera cut must be a boolean")
        pending_cut = pending_cut or entry.get("camera_cut",False) or (previous_signature is not None and
            (camera!=previous_camera or declared_shot!=previous_shot))
        for tid in list(active):
            state = active[tid]
            if time-state["samples"][-1]["t_seconds"]>tracking_config.max_gap_seconds or state["missed"]>tracking_config.max_missed_frames:
                del active[tid]
                quality["expired_tracks"] += 1
        path = _frame_path(root,entry.get("file"))
        if not path.is_file():
            quality["missing_frames"] += 1
            for state in active.values():
                state["missed"] += 1
                quality["occluded_track_frames"] += 1
            frames.append({"frame_index":index,"pts_seconds":time,"status":"missing_frame","candidates":[]})
            continue
        raw = path.read_bytes()
        frame_sha256 = hashlib.sha256(raw).hexdigest()
        with Image.open(path) as source:
            image = source.convert("RGB")
        signature = np.asarray(image.resize((32,24)),dtype=float)/255.
        cut = previous_signature is not None and (
            pending_cut or image.size!=previous_size or
            tracking_config.scene_cut_threshold is not None and float(np.abs(signature-previous_signature).mean())>tracking_config.scene_cut_threshold)
        if cut:
            active.clear()
            epoch += 1
            quality["camera_cut_resets"] += 1
        shot_id = f"{declared_shot or 'auto-shot'}:{epoch}"
        pending_cut = False
        previous_signature,previous_camera,previous_shot,previous_size = signature,camera,declared_shot,image.size
        detections = detect_candidates(image,detector_config)
        quality["processed_frames"] += 1
        quality["detected_candidates"] += len(detections)
        tids = list(active)
        cost = np.full((len(tids),len(detections)),1e12,dtype=float)
        for i,tid in enumerate(tids):
            state = active[tid]
            prior = state["samples"][-1]
            dt = time-prior["t_seconds"]
            predicted = (prior["x"]+state["velocity"][0]*dt,prior["y"]+state["velocity"][1]*dt)
            for j,candidate in enumerate(detections):
                displacement = math.dist((prior["x"],prior["y"]),candidate.centroid)
                distance = math.dist(predicted,candidate.centroid)
                ratio = max(prior["area_px"],candidate.area_px)/min(prior["area_px"],candidate.area_px)
                if (candidate.band==prior["band"] and distance<=tracking_config.max_distance_px and
                        displacement/dt<=tracking_config.max_speed_px_s and ratio<=tracking_config.max_area_ratio):
                    cost[i,j] = distance
        ambiguous = set()
        for row in cost:
            possible = np.flatnonzero(row<1e12)
            if len(possible)>1:
                ordered = possible[np.argsort(row[possible])]
                if row[ordered[1]]-row[ordered[0]]<=tracking_config.ambiguity_margin_px:
                    ambiguous.update(int(j) for j in possible if row[j]-row[ordered[0]]<=tracking_config.ambiguity_margin_px)
        for j in range(len(detections)):
            possible = sorted(value for value in cost[:,j] if value<1e12)
            if len(possible)>1 and possible[1]-possible[0]<=tracking_config.ambiguity_margin_px:
                ambiguous.add(j)
        for j in ambiguous:
            cost[:,j] = 1e12
        quality["ambiguous_detections"] += len(ambiguous)
        matches = {}
        matched_tracks = set()
        if cost.size:
            rows,columns = linear_sum_assignment(cost)
            for i,j in zip(rows,columns):
                if cost[i,j]>=1e12:
                    continue
                tid = tids[int(i)]
                _append_detection(active[tid],detections[int(j)],index=index,time=time,frame_sha256=frame_sha256)
                matches[int(j)] = tid
                matched_tracks.add(tid)
                quality["matched_detections"] += 1
        for tid in tids:
            if tid not in matched_tracks:
                active[tid]["missed"] += 1
                quality["occluded_track_frames"] += 1
        for j,candidate in enumerate(detections):
            if j in matches or j in ambiguous:
                continue
            serial += 1
            tid = f"track-{serial:06d}"
            state = {"track_id":tid,"camera_id":camera,"shot_id":shot_id,"velocity":(0.,0.),"missed":0,"samples":[]}
            _append_detection(state,candidate,index=index,time=time,frame_sha256=frame_sha256)
            active[tid] = state
            all_tracks.append(state)
            matches[j] = tid
            quality["new_tracks"] += 1
        frames.append({"frame_index":index,"pts_seconds":time,"status":"camera_cut" if cut else "processed",
            "frame_sha256":frame_sha256,"camera_id":camera,"shot_id":shot_id,
            "width":image.width,"height":image.height,
            "candidates":[dict(asdict(candidate),track_id=matches.get(j),ambiguous=j in ambiguous) for j,candidate in enumerate(detections)]})
    tracks = []
    for state in all_tracks:
        track = {key:state[key] for key in ("track_id","camera_id","shot_id","samples")}
        track["track_sha256"] = _digest(track)
        tracks.append(track)
    return {"schema":"dt-r1-vision-candidates-v1","source_kind":"ai_estimate",
        "source_video_sha256":manifest["source_sha256"],"detector_config_sha256":_digest(asdict(detector_config)),
        "tracking_config_sha256":_digest(asdict(tracking_config)),"candidate_only":True,
        "automatic_identity_validation":False,"real_recognition_validation_count":0,
        "frames":frames,"tracks":tracks,"quality":quality}


def _adapt_samples(result,manifest,identity_map,reviewed_points,minimum_identity_confidence):
    identities = identity_map or {}
    tracks = {track["track_id"]:track for track in result["tracks"]}
    if set(identities)-set(tracks):
        raise ValueError("Identity map refers to a different track extraction")
    assignments = {}
    for tid,raw in identities.items():
        source = Provenance(**raw["provenance"])
        if source.kind not in {SourceKind.REVIEWED_VIDEO,SourceKind.AI_ESTIMATE}:
            raise ValueError("A video identity must remain reviewed-video evidence or an AI estimate")
        if raw.get("source_video_sha256")!=manifest["source_sha256"] or not raw.get("rider_id"):
            raise ValueError("Identity mapping must identify this exact video and a supplied rider ID")
        confidence = finite(raw.get("confidence"),"identity confidence",low=0,high=1)
        if source.kind==SourceKind.REVIEWED_VIDEO:
            if raw.get("track_sha256")!=tracks[tid]["track_sha256"]:
                raise ValueError("Reviewed identity mapping must bind the exact anonymous track SHA")
        else:
            confidence = min(confidence,max(0.,minimum_identity_confidence-1e-6))
        assignments[tid] = (str(raw["rider_id"]),confidence,source)
    points = {}
    frame_metadata = {frame["frame_index"]:frame for frame in result["frames"]}
    for raw in reviewed_points or []:
        key = (raw["track_id"],raw["frame_index"])
        if key in points or raw["track_id"] not in tracks:
            raise ValueError("Wheel-point review is duplicated or belongs to a different track")
        source = Provenance(**raw["provenance"])
        if source.kind!=SourceKind.REVIEWED_VIDEO:
            raise ValueError("Measured wheel points require explicit video review")
        matching = [s for s in tracks[raw["track_id"]]["samples"] if s["frame_index"]==raw["frame_index"]]
        if len(matching)!=1 or matching[0]["frame_sha256"]!=raw.get("frame_sha256"):
            raise ValueError("Wheel-point review must bind the actual frame bytes")
        finite(raw.get("x"),"reviewed wheel x")
        finite(raw.get("y"),"reviewed wheel y")
        frame = frame_metadata[raw["frame_index"]]
        if not 0<=raw["x"]<frame["width"] or not 0<=raw["y"]<frame["height"]:
            raise ValueError("Reviewed wheel point must lie in the exact bound frame")
        points[key] = raw,source
    quality = result["quality"]
    for key in ("unmapped_samples","estimated_identity_samples","reviewed_identity_samples","reviewed_anchor_samples","timing_eligible_samples"):
        quality[key] = 0
    samples,evidence = [],[]
    seen_identities = set()
    fps = manifest.get("source_fps")
    pts_error = .5/finite(fps,"source FPS",low=1e-12) if fps is not None else 0.
    for tid,track in tracks.items():
        assignment = assignments.get(tid)
        for candidate in track["samples"]:
            mapped = assignment is not None
            reviewed_identity = mapped and assignment[2].kind==SourceKind.REVIEWED_VIDEO
            rider,confidence = assignment[:2] if mapped else ("anonymous:"+tid,0.)
            if mapped:
                key = (rider,candidate["frame_index"])
                if key in seen_identities:
                    raise ValueError("One rider is assigned to simultaneous different tracks")
                seen_identities.add(key)
            quality["reviewed_identity_samples" if reviewed_identity else "estimated_identity_samples" if mapped else "unmapped_samples"] += 1
            point = points.get((tid,candidate["frame_index"]))
            if point:
                quality["reviewed_anchor_samples"] += 1
            anchor_reviewed = bool(point and reviewed_identity)
            position = point[0] if anchor_reviewed else candidate
            eligible = anchor_reviewed and confidence>=minimum_identity_confidence and not candidate["occluded"]
            quality["timing_eligible_samples"] += int(eligible)
            sample = TrackSample(rider,tid,candidate["t_seconds"],position["x"],position["y"],
                track["camera_id"],track["shot_id"],confidence,
                point_kind="front_wheel_contact" if anchor_reviewed else "candidate_centroid",
                occluded=candidate["occluded"],timestamp_uncertainty_seconds=pts_error,frame_index=candidate["frame_index"])
            samples.append(sample)
            evidence.append({"track_id":tid,"frame_index":candidate["frame_index"],"candidate_source_kind":"ai_estimate",
                "identity_missing":not mapped,"identity_source_kind":assignment[2].kind.value if mapped else None,
                "wheel_point_reviewed":anchor_reviewed,"timing_evidence_kind":"reviewed_video" if eligible else "ai_estimate",
                "identity_provenance":asdict(assignment[2]) if mapped else None,
                "anchor_provenance":asdict(point[1]) if point else None})
    return samples,evidence


def process_manifest(path, detector_config, tracking_config, *, identity_map=None,reviewed_points=None,
                     gates=None,timing_config=None):
    """Run actual candidate detection/tracking, optionally applying supplied reviews."""
    path = Path(path).resolve()
    raw_manifest = path.read_bytes()
    manifest = json.loads(raw_manifest)
    detector_config = detector_config if isinstance(detector_config,DetectorConfig) else DetectorConfig(**detector_config)
    tracking_config = tracking_config if isinstance(tracking_config,TrackingConfig) else TrackingConfig(**tracking_config)
    result = track_frames(manifest,detector_config,tracking_config,frame_root=path.parent)
    result["frame_manifest_sha256"] = hashlib.sha256(raw_manifest).hexdigest()
    if timing_config is not None and not isinstance(timing_config,VideoTimingConfig):
        timing_config = VideoTimingConfig(**timing_config)
    threshold = timing_config.min_identity_confidence if timing_config else .9
    samples,evidence = _adapt_samples(result,manifest,identity_map,reviewed_points,threshold)
    result["track_samples"] = [asdict(sample) for sample in samples]
    result["sample_evidence"] = evidence
    result["crossings"],result["crossing_issues"] = [],[]
    result["event_clock_verified"] = bool(timing_config and timing_config.timebase_verified and
        timing_config.timebase_id and timing_config.playback_rate==1.)
    if gates:
        if timing_config is None:
            result["crossing_issues"].append({"reason":"explicit_reviewed_event_clock_configuration_required"})
        else:
            extracted = extract_crossings(samples,[gate if isinstance(gate,Gate) else Gate(**gate) for gate in gates],timing_config)
            result["crossings"] = [asdict(crossing) for crossing in extracted.crossings]
            result["crossing_issues"] = extracted.issues
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    process = sub.add_parser("process")
    for name in ("manifest","config","output"):
        process.add_argument("--"+name,required=True)
    for name in ("identity-map","reviewed-points","gates","timing-config"):
        process.add_argument("--"+name)
    args = parser.parse_args(argv)
    def read(path):
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else None
    config = read(args.config)
    result = process_manifest(args.manifest,config["detector"],config.get("tracking",{}),
        identity_map=read(args.identity_map),reviewed_points=read(args.reviewed_points),
        gates=read(args.gates),timing_config=read(args.timing_config))
    output = Path(args.output).resolve()
    output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with output.open("x",encoding="utf-8") as stream:
        output.chmod(0o600)
        json.dump(result,stream,ensure_ascii=False,allow_nan=False,indent=2)
        stream.write("\n")
    print(json.dumps({"tracks":len(result["tracks"]),"quality":result["quality"],
        "real_recognition_validation_count":0}))


if __name__ == "__main__":
    main()
