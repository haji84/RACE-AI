"""Evidence-typed timing and reviewed-track processing for independent DT-R1.

No network video acquisition, recognition model, physiological measurement, or
independent PDCA authority. Supplied identities, line calibration, continuous
event clocks and source receipts require external review. Pixel coordinates
alone are relative motion. A whole bank is never treated as one flat plane.

CLI: python -m research.chatgpt_dt_r1.observations extract-frames local.mp4 out
     --rights-confirmed --duration 30 --every-n-frames 3
The private output includes original video PTS, never a fabricated event clock.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import subprocess
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


TIMINGS = ("full_last_lap_seconds", "home_back_seconds", "back_fourth_seconds",
           "fourth_goal_seconds", "agari_half_seconds")
PHASES = ("INITIAL", "BELL", "FINAL_HOME", "FINAL_BACK", "FOURTH_CORNER", "GOAL")
GATE_ROLES = (*PHASES[2:], "LAP_START", "AGARI_START")


def utc(value: str | datetime) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required; do not manufacture a cutoff from a date")
    return dt.astimezone(timezone.utc)


def day(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def finite(value: Any, name: str, *, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{name} is outside its valid range")
    return float(value)


class SourceKind(str, Enum):
    OFFICIAL_RECORD = "official_record"
    REVIEWED_VIDEO = "reviewed_video"
    USER_OBSERVATION = "user_observation"
    AI_ESTIMATE = "ai_estimate"


@dataclass(frozen=True)
class Provenance:
    kind: SourceKind | str
    source_url: str
    source_sha256: str
    retrieved_at: str
    available_at: str
    reviewer_id: str | None = None
    reviewed_at: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "kind", SourceKind(self.kind))
        if urlparse(self.source_url).scheme not in {"https", "http", "urn"}:
            raise ValueError("Source URL or content-addressed URN is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("Source SHA256 must identify the actual supplied source bytes")
        if utc(self.available_at) < utc(self.retrieved_at):
            raise ValueError("Observation availability cannot precede source retrieval")
        if self.kind == SourceKind.REVIEWED_VIDEO:
            if not self.reviewer_id or not self.reviewed_at:
                raise ValueError("Reviewed video requires a review identity and review timestamp")
            if not utc(self.retrieved_at) <= utc(self.reviewed_at) <= utc(self.available_at):
                raise ValueError("Video review must be after retrieval and before feature availability")


@dataclass(frozen=True)
class TrackSample:
    rider_id: str
    track_id: str
    t_seconds: float
    x: float
    y: float
    camera_id: str
    shot_id: str
    identity_confidence: float
    point_kind: str = "front_wheel_contact"
    occluded: bool = False
    timestamp_uncertainty_seconds: float = 0.0
    frame_index: int | None = None

    def __post_init__(self):
        if not all((self.rider_id, self.track_id, self.camera_id, self.shot_id)):
            raise ValueError("Stable rider, track, camera and shot identities are required")
        for key in ("t_seconds", "x", "y"):
            finite(getattr(self, key), key)
        finite(self.identity_confidence, "identity_confidence", low=0, high=1)
        finite(self.timestamp_uncertainty_seconds, "timestamp uncertainty", low=0)
        if type(self.occluded) is not bool:
            raise ValueError("Occlusion must be explicit boolean data")

    @classmethod
    def from_dict(cls, row):
        data = dict(row)
        if "identity_key" in data:
            data.setdefault("rider_id", data.pop("identity_key"))
        if "point" in data:
            data["x"], data["y"] = data.pop("point")
        return cls(**data)


@dataclass(frozen=True)
class VideoTimingConfig:
    fps: float
    timebase_verified: bool = False
    timebase_id: str = ""
    playback_rate: float | None = None
    min_identity_confidence: float = .9
    max_gap_seconds: float = .2

    def __post_init__(self):
        if type(self.timebase_verified) is not bool:
            raise ValueError("Event clock verification must be explicit boolean data")
        if finite(self.fps, "fps", low=0) == 0 or finite(self.max_gap_seconds, "max gap", low=0) == 0:
            raise ValueError("FPS and allowed interpolation gap must be positive")
        finite(self.min_identity_confidence, "identity threshold", low=0, high=1)
        if self.playback_rate is not None:
            finite(self.playback_rate, "playback rate", low=0)


@dataclass(frozen=True)
class Gate:
    gate_id: str
    role: str
    line_start: tuple[float, float]
    line_end: tuple[float, float]
    camera_id: str
    shot_id: str
    physical_line_id: str
    calibration_id: str
    lap_index: int | None = None
    remaining_laps: float | None = None
    time_window: tuple[float, float] | None = None
    crossing_direction: int = 1
    line_uncertainty_px: float = 0.

    def __post_init__(self):
        if self.role not in GATE_ROLES or not all((self.gate_id, self.physical_line_id, self.calibration_id, self.camera_id, self.shot_id)):
            raise ValueError("A gate requires a reviewed physical line and supported role")
        for point in (self.line_start, self.line_end):
            if len(point) != 2:
                raise ValueError("Gate endpoints must be 2D")
            for number in point:
                finite(number, "gate coordinate")
        if self.line_start == self.line_end or self.crossing_direction not in {-1, 1}:
            raise ValueError("Gate must have a nonzero line and a crossing direction")
        finite(self.line_uncertainty_px, "line error", low=0)
        if self.time_window and (len(self.time_window) != 2 or self.time_window[0] >= self.time_window[1]):
            raise ValueError("Gate time window must be increasing")


@dataclass(frozen=True)
class GateCrossing:
    rider_id: str
    gate_id: str
    role: str
    t_seconds: float
    uncertainty_seconds: float
    identity_confidence: float
    timebase_id: str
    physical_line_id: str
    calibration_id: str
    lap_index: int | None
    remaining_laps: float | None
    camera_id: str
    shot_id: str

    def __post_init__(self):
        if self.role not in GATE_ROLES or not all((self.rider_id,self.gate_id,self.timebase_id,
                self.physical_line_id,self.calibration_id,self.camera_id,self.shot_id)):
            raise ValueError("A crossing requires rider, line, calibration, camera and event-clock identities")
        finite(self.t_seconds,"crossing timestamp")
        finite(self.uncertainty_seconds,"crossing uncertainty",low=0)
        finite(self.identity_confidence,"crossing identity confidence",low=0,high=1)
        if self.lap_index is not None and (type(self.lap_index) is not int or self.lap_index < 0):
            raise ValueError("Lap index must be a nonnegative integer or null")
        if self.remaining_laps is not None:
            finite(self.remaining_laps,"remaining laps",low=0)


@dataclass
class CrossingExtraction:
    crossings: list[GateCrossing] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)


def _groups(samples: Iterable[TrackSample | Mapping]) -> list[list[TrackSample]]:
    groups = defaultdict(list)
    for row in samples:
        sample = row if isinstance(row, TrackSample) else TrackSample.from_dict(row)
        key = (sample.rider_id, sample.track_id)
        if groups[key] and sample.t_seconds <= groups[key][-1].t_seconds:
            raise ValueError("Track PTS must increase; duplicate or reversed frames cannot be timed")
        groups[key].append(sample)
    return list(groups.values())


def _pair_issue(a, b, config):
    if not config.timebase_verified or not config.timebase_id:
        return "unverified_continuous_event_clock"
    if config.playback_rate != 1.:
        return "unverified_or_non_realtime_playback"
    if (a.camera_id, a.shot_id) != (b.camera_id, b.shot_id):
        return "camera_cut"
    if a.occluded or b.occluded:
        return "occlusion"
    if min(a.identity_confidence, b.identity_confidence) < config.min_identity_confidence:
        return "low_identity_confidence"
    if a.point_kind != b.point_kind:
        return "inconsistent_tracking_anchor"
    if b.t_seconds - a.t_seconds > config.max_gap_seconds:
        return "interpolation_gap_too_large"
    return None


def extract_crossings(samples: Iterable[TrackSample | Mapping], gates: Iterable[Gate | Mapping],
                      config: VideoTimingConfig) -> CrossingExtraction:
    """Interpolate only a bracketed, finite, reviewed gate crossing.

    Time error conservatively includes the entire bracketing frame interval,
    half a source frame, supplied PTS error, and the reviewed line error.
    The caller must review the clock through cuts/replays; no image can prove it.
    """
    gates = [g if isinstance(g, Gate) else Gate(**g) for g in gates]
    result = CrossingExtraction()
    for group in _groups(samples):
        for a, b in zip(group, group[1:]):
            issue = _pair_issue(a, b, config)
            if issue or a.point_kind != "front_wheel_contact":
                result.issues.append({"rider_id":a.rider_id, "t_seconds":a.t_seconds,
                                      "reason":issue or "unreviewed_timing_anchor"})
                continue
            for gate in gates:
                if (gate.camera_id, gate.shot_id) != (a.camera_id, a.shot_id):
                    continue
                gx, gy = gate.line_end[0]-gate.line_start[0], gate.line_end[1]-gate.line_start[1]
                length = math.hypot(gx, gy)
                def distance(sample):
                    return gate.crossing_direction * (gx*(sample.y-gate.line_start[1])-gy*(sample.x-gate.line_start[0]))/length
                d0, d1 = distance(a), distance(b)
                if not d0 < 0 <= d1:
                    continue
                alpha = -d0/(d1-d0)
                x, y = a.x+alpha*(b.x-a.x), a.y+alpha*(b.y-a.y)
                along = ((x-gate.line_start[0])*gx+(y-gate.line_start[1])*gy)/length**2
                if not 0 <= along <= 1:
                    continue
                dt = b.t_seconds-a.t_seconds
                time = a.t_seconds+alpha*dt
                if gate.time_window and not gate.time_window[0] <= time <= gate.time_window[1]:
                    continue
                error = max(alpha, 1-alpha)*dt + .5/config.fps + max(a.timestamp_uncertainty_seconds, b.timestamp_uncertainty_seconds)
                error += gate.line_uncertainty_px*dt/abs(d1-d0)
                result.crossings.append(GateCrossing(a.rider_id, gate.gate_id, gate.role, time, error,
                    min(a.identity_confidence,b.identity_confidence), config.timebase_id, gate.physical_line_id,
                    gate.calibration_id, gate.lap_index, gate.remaining_laps, a.camera_id, a.shot_id))
    return result


@dataclass(frozen=True)
class RiderTimingObservation:
    observation_id: str
    race_id: str
    rider_id: str
    venue_id: str
    event_at: str | None
    provenance: Provenance
    timings: dict[str, float | None]
    uncertainties: dict[str, float | None] = field(default_factory=dict)
    identity_confidence: float | None = None
    event_day: str | None = None
    issues: tuple[str, ...] = ()
    role: str | None = None
    tactic: str | None = None
    weather: str | None = None

    def __post_init__(self):
        if not all((self.observation_id, self.race_id, self.rider_id, self.venue_id)):
            raise ValueError("Timing observation must identify its race, rider and venue")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("Typed provenance is required")
        if self.event_at:
            event = utc(self.event_at)
            if event > utc(self.provenance.available_at):
                raise ValueError("Timing cannot be available before the observed event")
            if self.event_day and day(self.event_day) != day(self.event_at):
                raise ValueError("Event date and timestamp disagree")
        elif not self.event_day:
            raise ValueError("Event time or explicit retrospective event day is required")
        if self.event_day:
            day(self.event_day)
        if set(self.timings) - set(TIMINGS) or set(self.uncertainties) - set(TIMINGS):
            raise ValueError("Unknown timing metric; physiological estimates are not timing observations")
        for key, value in self.timings.items():
            if value is not None and finite(value, key, low=0) == 0:
                raise ValueError("Measured elapsed time must be positive")
        for key, value in self.uncertainties.items():
            if value is not None:
                finite(value, key, low=0)
        if self.identity_confidence is not None:
            finite(self.identity_confidence, "identity confidence", low=0, high=1)

    @classmethod
    def from_dict(cls, row):
        data = dict(row)
        for alias, name in (("identity_key", "rider_id"), ("venue_code", "venue_id"), ("day", "event_day")):
            if alias in data:
                data.setdefault(name, data.pop(alias))
        data.setdefault("event_at", None)
        if not isinstance(data["provenance"], Provenance):
            data["provenance"] = Provenance(**data["provenance"])
        return cls(**data)


def build_lap_observation(crossings, **metadata) -> RiderTimingObservation:
    """Keep all five timing definitions separate, using this rider's crossings.

    LAP_START and GOAL must be the same physical finish line on consecutive
    laps. FINAL_HOME can be a different line. AGARI_START must explicitly be
    calibrated as half a lap remaining; FINAL_BACK alone does not establish it.
    """
    if metadata["provenance"].kind == SourceKind.OFFICIAL_RECORD:
        raise ValueError("Video-derived timing cannot be relabelled as an official timing record")
    selected = defaultdict(list)
    for crossing in crossings:
        if crossing.rider_id == metadata["rider_id"]:
            selected[crossing.role].append(crossing)
    timings, errors, issues, identities = {}, {}, [], []
    pairs = dict(zip(TIMINGS, (("LAP_START","GOAL"), ("FINAL_HOME","FINAL_BACK"),
        ("FINAL_BACK","FOURTH_CORNER"), ("FOURTH_CORNER","GOAL"), ("AGARI_START","GOAL"))))
    for metric, (start, finish) in pairs.items():
        timings[metric] = errors[metric] = None
        if len(selected[start]) != 1 or len(selected[finish]) != 1:
            issues.append(metric+":missing_or_ambiguous_own_crossing")
            continue
        a, b = selected[start][0], selected[finish][0]
        reason = None
        if a.timebase_id != b.timebase_id or not a.timebase_id:
            reason = "inconsistent_event_clock"
        elif b.t_seconds <= a.t_seconds:
            reason = "nonpositive_elapsed_time"
        elif b.t_seconds-a.t_seconds <= a.uncertainty_seconds+b.uncertainty_seconds:
            reason = "elapsed_time_not_resolved_by_uncertainty"
        elif start == "LAP_START" and (a.physical_line_id != b.physical_line_id or
                a.lap_index is None or b.lap_index != a.lap_index+1):
            reason = "full_lap_not_verified"
        elif start == "AGARI_START" and a.remaining_laps != .5:
            reason = "half_lap_start_not_verified"
        if reason:
            issues.append(metric+":"+reason)
            continue
        timings[metric] = b.t_seconds-a.t_seconds
        errors[metric] = a.uncertainty_seconds+b.uncertainty_seconds
        identities += [a.identity_confidence, b.identity_confidence]
    return RiderTimingObservation(**metadata, timings=timings, uncertainties=errors,
        identity_confidence=min(identities) if identities else None, issues=tuple(issues))


@dataclass(frozen=True)
class LocalPlaneCalibration:
    calibration_id: str
    camera_id: str
    shot_id: str
    homography: tuple
    valid_polygon: tuple
    max_span_m: float
    position_error_m: float
    source: Provenance
    scope: str = "local_planar_segment"

    def __post_init__(self):
        if self.scope != "local_planar_segment" or not all((self.calibration_id,self.camera_id,self.shot_id)):
            raise ValueError("Absolute speed requires an explicitly local calibrated plane")
        if len(self.homography) != 3 or any(len(row) != 3 for row in self.homography) or len(self.valid_polygon) < 3:
            raise ValueError("A 3x3 homography and local validity polygon are required")
        for row in self.homography:
            for value in row:
                finite(value, "homography")
        h = self.homography
        determinant = (h[0][0]*(h[1][1]*h[2][2]-h[1][2]*h[2][1])
            -h[0][1]*(h[1][0]*h[2][2]-h[1][2]*h[2][0])
            +h[0][2]*(h[1][0]*h[2][1]-h[1][1]*h[2][0]))
        if abs(determinant) < 1e-12:
            raise ValueError("Singular calibration cannot establish metre distances")
        if not isinstance(self.source,Provenance):
            raise ValueError("A local calibration requires source provenance")
        for point in self.valid_polygon:
            if len(point) != 2:
                raise ValueError("Local validity polygon coordinates must be 2D")
            for value in point:
                finite(value,"calibration polygon")
        area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(self.valid_polygon,(*self.valid_polygon[1:],self.valid_polygon[0])))
        if abs(area)<1e-12:
            raise ValueError("Local validity polygon must enclose a nonzero area")
        if finite(self.max_span_m, "local span", low=0) == 0:
            raise ValueError("The measured local calibration extent must be positive")
        finite(self.position_error_m, "calibration error", low=0)


def _inside(point, polygon):
    x, y = point
    inside = False
    for a, b in zip(polygon, (*polygon[1:],polygon[0])):
        if min(a[0],b[0]) <= x <= max(a[0],b[0]) and min(a[1],b[1]) <= y <= max(a[1],b[1]):
            if abs((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])) < 1e-10:
                return True
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def _metres(sample, calibration):
    if (sample.camera_id,sample.shot_id) != (calibration.camera_id,calibration.shot_id) or sample.point_kind != "front_wheel_contact":
        return None
    if not _inside((sample.x,sample.y),calibration.valid_polygon):
        return None
    values = [row[0]*sample.x+row[1]*sample.y+row[2] for row in calibration.homography]
    if abs(values[2]) < 1e-10:
        return None
    return values[0]/values[2], values[1]/values[2]


def motion_features(samples, config, calibration: LocalPlaneCalibration | None = None):
    """Per-track screen motion and optional local-plane speed; no bank-wide metres.

    A sequence must contain one rider and one track. Camera motion is not
    removed automatically; screen speed is a relative image feature only.
    """
    groups = _groups(samples)
    if len(groups) > 1:
        raise ValueError("Compute motion for one rider track at a time")
    screen, measured, uncertainty, issues = [], [], [], []
    screen_velocities, metre_velocities = [], []
    group = groups[0] if groups else []
    for index,(a,b) in enumerate(zip(group,group[1:])):
        issue = _pair_issue(a,b,config)
        if issue:
            issues.append(issue)
            continue
        dt = b.t_seconds-a.t_seconds
        screen.append(math.hypot(b.x-a.x,b.y-a.y)/dt)
        midpoint = (a.t_seconds+b.t_seconds)/2
        screen_velocities.append((index,midpoint,screen[-1],None))
        if calibration:
            start,end = _metres(a,calibration),_metres(b,calibration)
            if start is None or end is None:
                issues.append("outside_local_plane_calibration")
                continue
            distance = math.dist(start,end)
            if distance > calibration.max_span_m:
                issues.append("exceeds_calibrated_local_span")
                continue
            time_error = 1/config.fps+a.timestamp_uncertainty_seconds+b.timestamp_uncertainty_seconds
            if dt <= time_error:
                issues.append("time_uncertainty_exceeds_segment_duration")
                continue
            speed = distance/dt
            measured.append(speed)
            high = (distance+2*calibration.position_error_m)/(dt-time_error)
            low = max(0.,distance-2*calibration.position_error_m)/(dt+time_error)
            uncertainty.append(max(high-speed,speed-low))
            metre_velocities.append((index,midpoint,speed,uncertainty[-1]))
    def acceleration(velocities):
        values,errors = [],[]
        for a,b in zip(velocities,velocities[1:]):
            if b[0] != a[0]+1:
                continue
            dt = b[1]-a[1]
            values.append((b[2]-a[2])/dt)
            if a[3] is not None and b[3] is not None:
                errors.append((a[3]+b[3])/dt)
        return values,errors
    screen_acc,_ = acceleration(screen_velocities)
    metre_acc,acc_error = acceleration(metre_velocities)
    return {"screen_speed_mean_px_s":statistics.mean(screen) if screen else None,
        "screen_speed_max_px_s":max(screen) if screen else None,
        "measured_speed_mean_m_s":statistics.mean(measured) if measured else None,
        "measured_speed_max_m_s":max(measured) if measured else None,
        "measured_speed_uncertainty_m_s":max(uncertainty) if uncertainty else None,
        "screen_acceleration_mean_px_s2":statistics.mean(screen_acc) if screen_acc else None,
        "measured_acceleration_mean_m_s2":statistics.mean(metre_acc) if metre_acc else None,
        "measured_acceleration_uncertainty_m_s2":max(acc_error) if acc_error else None,
        "screen_motion_segments":len(screen), "measured_motion_segments":len(measured), "issues":issues}


class TimingBook:
    """Retain evidence separately and admit history against both event and availability clocks."""
    def __init__(self, observations: Iterable[RiderTimingObservation]):
        self.observations = tuple(observations)
        ids = [row.observation_id for row in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate observation IDs require explicit revision handling")

    @classmethod
    def from_records(cls, records):
        return cls(row if isinstance(row,RiderTimingObservation) else RiderTimingObservation.from_dict(row) for row in records)

    def features(self, rider_id, venue_id, target_event_at, prediction_at, window_days=None,
                 *, scope="prospective", role=None, tactic=None, weather=None):
        if scope not in {"prospective","retrospective"}:
            raise ValueError("Unknown evidence scope")
        if prediction_at is None:
            raise ValueError("An authentic prediction clock, or actual retrospective analysis clock, is required")
        cutoff = utc(prediction_at)
        target_day = day(target_event_at)
        target = utc(target_event_at) if scope == "prospective" else None
        if target is not None and cutoff >= target:
            raise ValueError("A prospective feature query must precede the target event")
        if window_days is not None and (type(window_days) is not int or window_days <= 0):
            raise ValueError("Window days must be a positive integer")
        admitted, late = [], 0
        for row in self.observations:
            if row.rider_id != str(rider_id) or row.venue_id != str(venue_id):
                continue
            if any(wanted is not None and getattr(row,key) != wanted for key,wanted in (("role",role),("tactic",tactic),("weather",weather))):
                continue
            event_day = day(row.event_day or row.event_at)
            if scope == "prospective":
                if row.event_at is None or utc(row.event_at) >= target:
                    continue
            elif event_day >= target_day:
                continue
            if utc(row.provenance.available_at) > cutoff:
                continue
            if window_days is not None and event_day < target_day-timedelta(days=window_days):
                continue
            admitted.append(row)
            late += int(day(row.provenance.available_at) >= target_day)
        result = {"timing_observation_count":len(admitted), "retrospective_only":int(scope=="retrospective"),
                  "late_source_count":late, "timing_identity_confidence_min":None}
        identities = [row.identity_confidence for row in admitted if row.identity_confidence is not None]
        if identities:
            result["timing_identity_confidence_min"] = min(identities)
        for kind in SourceKind:
            result[f"source_{kind.value}_count"] = sum(row.provenance.kind==kind for row in admitted)
        categories = {"":{SourceKind.OFFICIAL_RECORD,SourceKind.REVIEWED_VIDEO},
                      "user_observed_":{SourceKind.USER_OBSERVATION}, "estimated_":{SourceKind.AI_ESTIMATE}}
        for prefix,kinds in categories.items():
            for metric in TIMINGS:
                # At most one observation per rider/race/metric. Official records
                # take precedence, then the latest independently available review.
                best = {}
                for row in admitted:
                    if row.provenance.kind not in kinds or row.timings.get(metric) is None:
                        continue
                    priority = (row.provenance.kind==SourceKind.OFFICIAL_RECORD,
                                utc(row.provenance.available_at), row.observation_id)
                    if row.race_id not in best or priority > best[row.race_id][0]:
                        best[row.race_id] = priority,row
                def chronology(row):
                    # UTC ordinals are only sorting keys. A day-only observation
                    # remains day-only; it never acquires a synthetic event clock.
                    if row.event_at:
                        at = utc(row.event_at)
                        return at.date().toordinal(),at.hour*3600+at.minute*60+at.second+at.microsecond/1e6,row.race_id
                    return day(row.event_day).toordinal(),-1.,row.race_id
                rows = sorted((item[1] for item in best.values()),key=chronology)
                values = [row.timings[metric] for row in rows]
                root = prefix+metric+"_"
                result.update({root+"count":len(values), root+"min":min(values) if values else None,
                    root+"mean":statistics.mean(values) if values else None,
                    root+"recent":values[-1] if values else None,
                    root+"variance":statistics.pvariance(values) if values else None})
                errors = [row.uncertainties.get(metric) for row in rows if row.uncertainties.get(metric) is not None]
                result[root+"uncertainty_mean"] = statistics.mean(errors) if errors else None
        return result

    def window_features(self, *args, windows=(30,90,120,180,365,1095), **kwargs):
        return {"all":self.features(*args,**kwargs), **{str(n)+"d":self.features(*args,window_days=n,**kwargs) for n in windows}}


def context_features(record, as_of, *, scope="prospective"):
    """Optional sidecar adapter. Does not read same-race labels or raw agari results.

    Returns rider-ID keyed numeric dictionaries. Day-only normalized archive
    inputs require explicit retrospective scope and actual analysis ``as_of``.
    """
    snapshot = record.get("snapshot",record)
    records = record.get("timing_observations",snapshot.get("timing_observations",[]))
    book = TimingBook.from_records(records)
    venue = snapshot.get("venue_id",snapshot.get("venue_code"))
    target = snapshot.get("race_at",snapshot.get("event_at",snapshot.get("day")))
    if venue is None or target is None:
        return {}
    return {str(rider.get("identity_key",rider.get("rider_id"))):book.features(
        str(rider.get("identity_key",rider.get("rider_id"))),str(venue),target,as_of,scope=scope)
        for rider in snapshot.get("riders",[]) if rider.get("identity_key",rider.get("rider_id")) is not None}


@dataclass(frozen=True)
class PhaseObservation:
    race_id: str
    phase: str
    order: tuple[int, ...]
    complete: bool
    provenance: Provenance
    receipt: Any

    def __post_init__(self):
        if self.phase not in PHASES or not self.order or len(set(self.order)) != len(self.order):
            raise ValueError("Invalid observed phase order")
        if any(type(car) is not int or not 1 <= car <= 9 for car in self.order) or type(self.complete) is not bool:
            raise ValueError("Phase order requires observed car numbers and completeness")


@dataclass(frozen=True)
class TacticalOpportunity:
    opportunity_id: str
    race_id: str
    rider_id: str
    phase: str
    action: str
    outcome: str
    provenance: Provenance
    t_seconds: float | None = None
    opponent_id: str | None = None
    before_position: int | None = None
    after_position: int | None = None

    def __post_init__(self):
        if self.phase not in PHASES or self.outcome not in {"success","failure","unknown"}:
            raise ValueError("Tactical opportunity needs phase and explicit known/unknown outcome")
        if not all((self.opportunity_id,self.race_id,self.rider_id,self.action)):
            raise ValueError("Tactical opportunity identity is required")


def tactical_summary(opportunities):
    result, seen = {}, set()
    for row in opportunities:
        key = (row.race_id,row.rider_id,row.opportunity_id)
        if key in seen:
            raise ValueError("Duplicate tactical opportunities would inflate the denominator")
        seen.add(key)
        bucket = result.setdefault(row.action,{"opportunities":0,"success":0,"failure":0,"unknown":0,"known_success_rate":None})
        bucket["opportunities"] += 1
        bucket[row.outcome] += 1
    for bucket in result.values():
        known = bucket["success"]+bucket["failure"]
        bucket["known_success_rate"] = bucket["success"]/known if known else None
    return result


def to_pdca_observations(phases):
    """Convert evidence to the existing scorer's format; GOAL remains official order.

    This conversion is not authentication. The existing scorer still requires
    independent verifiers for forecast, finish order, and observation receipts.
    """
    sources = {SourceKind.OFFICIAL_RECORD:"official",SourceKind.REVIEWED_VIDEO:"video",
               SourceKind.USER_OBSERVATION:"user",SourceKind.AI_ESTIMATE:"estimate"}
    return [{"race_id":row.race_id,"aspect":row.phase,"source":sources[row.provenance.kind],
        "observed":list(row.order),"complete":row.complete,"receipt":row.receipt,
        "provenance":asdict(row.provenance)} for row in phases if row.phase != "GOAL"]


def compare_with_existing_pdca(*, phase_observations, **kwargs):
    from race_ai.keirin_form_fall_blind_pdca import compare_race_development
    return compare_race_development(observations=to_pdca_observations(phase_observations), **kwargs)


def extract_local_frames(video, output_dir, *, rights_confirmed=False, start_seconds=0.,
                         duration_seconds=30., every_n_frames=1):
    """Extract legally supplied local media with source PTS and a private manifest.

    ffmpeg reads only the local file protocol. No fetching, credentials or DRM
    handling. Source PTS are media time, not proof of a continuous race clock.
    """
    if not rights_confirmed:
        raise PermissionError("Confirm that the supplied local video may legally be processed")
    video = Path(video).expanduser().resolve()
    if not video.is_file():
        raise ValueError("A supplied local video file is required")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("Optional local ffmpeg and ffprobe are required")
    finite(start_seconds,"start",low=0)
    if finite(duration_seconds,"duration",low=0) == 0 or type(every_n_frames) is not int or every_n_frames < 1:
        raise ValueError("Duration and frame sampling interval must be positive")
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError("Output directory must be empty to preserve prior source receipts")
    probe = subprocess.run(["ffprobe","-v","error","-protocol_whitelist","file","-select_streams","v:0",
        "-show_entries","stream=avg_frame_rate,r_frame_rate,time_base","-of","json",str(video)],
        check=True,capture_output=True,text=True,timeout=60)
    streams = json.loads(probe.stdout).get("streams",[])
    if not streams:
        raise ValueError("No video stream found")
    numerator,denominator = streams[0]["avg_frame_rate"].split("/")
    fps = float(numerator)/float(denominator) if float(denominator) else None
    command = ["ffmpeg","-hide_banner","-loglevel","info","-nostdin","-protocol_whitelist","file",
        "-copyts","-ss",str(start_seconds),"-t",str(duration_seconds),"-i",str(video),"-map","0:v:0",
        "-vf",f"trim=start={start_seconds}:end={start_seconds+duration_seconds},select=not(mod(n\\,{every_n_frames})),showinfo","-fps_mode","vfr",
        str(output_dir/"frame_%08d.png")]
    run = subprocess.run(command,check=True,capture_output=True,text=True,timeout=max(60.,duration_seconds*4))
    timestamps = [float(value) for value in re.findall(r"\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:([\d.eE+-]+)",run.stderr)]
    paths = sorted(output_dir.glob("frame_*.png"))
    if len(paths) != len(timestamps) or not paths:
        raise RuntimeError("Frame extraction and source timestamp receipt disagree")
    with video.open("rb") as source:
        source_hash = hashlib.file_digest(source,"sha256").hexdigest()
    manifest = {"schema":"dt-r1-local-frames-v1","source_sha256":source_hash,
        "source_fps":fps,"source_time_base":streams[0].get("time_base"),
        "extracted_at":datetime.now(timezone.utc).isoformat(),"rights_confirmed":True,
        "event_clock_verified":False,"playback_rate":None,
        "frames":[{"file":p.name,"pts_seconds":ts} for p,ts in zip(paths,timestamps)]}
    (output_dir/"frames.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    frames = sub.add_parser("extract-frames")
    frames.add_argument("video")
    frames.add_argument("output_dir")
    frames.add_argument("--rights-confirmed",action="store_true")
    frames.add_argument("--start",type=float,default=0.)
    frames.add_argument("--duration",type=float,default=30.)
    frames.add_argument("--every-n-frames",type=int,default=1)
    args = parser.parse_args(argv)
    manifest = extract_local_frames(args.video,args.output_dir,rights_confirmed=args.rights_confirmed,
        start_seconds=args.start,duration_seconds=args.duration,every_n_frames=args.every_n_frames)
    print(json.dumps({"frames":len(manifest["frames"]),"source_sha256":manifest["source_sha256"],"event_clock_verified":False}))


if __name__ == "__main__":
    main()
