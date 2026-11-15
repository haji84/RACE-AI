"""Fail-closed research segmentation of color-blob tracks at weak video transitions.

This is a safety improvement to existing PR #291 untrusted color-region track
research, NOT an athlete identity verifier or forecasting model. It reuses
the existing frame SHA, existing color proposals and existing sparse LK/RANSAC
camera-quality assessment. An unknown camera transition cannot be bridged
by two visually similar jerseys: the underlying link_untrusted_color_blobs
candidate tracker restarts from the new scene.

Never promote this output into leader/second-wheel/line/tactic scores, model
training, official accuracy, or PDCA.
"""
from __future__ import annotations

import math
import re

from .keirin_visual_jersey_proposals import link_untrusted_color_blobs
from .keirin_camera_motion_quality import SCHEMA as MOTION_SCHEMA

SCHEMA="RACE_AI_KEIRIN_COLOR_BLOB_SCENE_GUARDED_TRACK_RESEARCH_V1"
SHA=re.compile(r"^[a-f0-9]{64}$")
ACCEPT="BACKGROUND_FLOW_GEOMETRY_CANDIDATE_ONLY"
ALLOWED_STATES=frozenset((
    ACCEPT,"REPEATED_FRAME_NO_FLOW_PROOF","INSUFFICIENT_SOURCE_FEATURES",
    "FLOW_TRACKING_FAILED","INSUFFICIENT_TRACKED_FEATURES",
    "RANSAC_NO_GLOBAL_TRANSFORM","LOW_INLIER_GLOBAL_FLOW",
    "UNSTABLE_CAMERA_GEOMETRY",
))


class ColorSceneGateError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise ColorSceneGateError(reason)


def color_scene_guarded_tracks(frames,transition_receipts):
    """Research-only per-scene restart using exact adjacent source SHA pairs.

    frames follow link_untrusted_color_blobs contract, are frozen SHA-bound,
    and must be ordered. Each receipt provides pair SHA + assess_pair motion.
    The method does not inspect manual annotations, official finish results,
    numeric rider IDs or a hidden second model. Even an ACCEPT transition
    only means a plausible global background transform was measured; two
    consecutive color blobs are NOT proven to be the same racer.
    """
    need(type(frames) is list and 2<=len(frames)<=300 and
         type(transition_receipts) is list and
         len(transition_receipts)==len(frames)-1,
         "ADJACENT_REAL_FRAME_AND_FLOW_RECEIPTS_REQUIRED")
    seen=set()
    last=-1
    for row in frames:
        need(type(row) is dict and set(row)=={
            "sample_sec","source_crop_sha256","proposals"} and
            type(row["sample_sec"]) in (int,float) and
            math.isfinite(row["sample_sec"]) and
            row["sample_sec"]>last and
            type(row["source_crop_sha256"]) is str and
            SHA.fullmatch(row["source_crop_sha256"]) is not None and
            row["source_crop_sha256"] not in seen and
            type(row["proposals"]) is list and
            len(row["proposals"])<=150,
            "INVALID_FROZEN_COLOR_FRAME_OR_SHA")
        seen.add(row["source_crop_sha256"])
        last=row["sample_sec"]
    # Validate all receipts before calculating even a research track count.
    states=[]
    for i,row in enumerate(transition_receipts):
        a,b=frames[i],frames[i+1]
        need(type(row) is dict and set(row)=={
            "previous_frame_sha256","current_frame_sha256","motion"} and
            row["previous_frame_sha256"]==a["source_crop_sha256"] and
            row["current_frame_sha256"]==b["source_crop_sha256"] and
            type(row["motion"]) is dict and
            row["motion"].get("schema")==MOTION_SCHEMA and
            row["motion"].get("camera_transform_quality_state") in
                ALLOWED_STATES and
            type(row["motion"].get("gap_seconds")) in (int,float) and
            math.isfinite(row["motion"]["gap_seconds"]) and
            abs(row["motion"]["gap_seconds"]-(
                 b["sample_sec"]-a["sample_sec"]))<1e-6 and
            row["motion"].get("reliable_for_person_id_or_tactics") is False and
            row["motion"].get("phase_scoring_admitted") is False,
            "INVALID_SHA_BOUND_CAMERA_PAIR_RECEIPT")
        states.append(row["motion"]["camera_transform_quality_state"])
    # Historical raw candidate tracks computed for side-by-side diagnostics
    # only, NOT for any downstream promotion.
    baseline=link_untrusted_color_blobs(frames)
    boundaries=[0]
    for i,state in enumerate(states):
        if state!=ACCEPT:
            boundaries.append(i+1)
    boundaries.append(len(frames))
    guarded_tracks=guarded_repeat=0
    segment_sizes=[]
    for start,end in zip(boundaries,boundaries[1:]):
        if end<=start:continue
        segment=link_untrusted_color_blobs(frames[start:end])
        guarded_tracks+=segment["untrusted_track_candidates_total"]
        guarded_repeat+=segment["track_candidates_seen_in_at_least_two_frames"]
        segment_sizes.append(end-start)
    need(sum(segment_sizes)==len(frames),
         "SCENE_SEGMENT_FRAME_COUNT_MISMATCH")
    need(guarded_repeat<=baseline["track_candidates_seen_in_at_least_two_frames"],
         "SCENE_SEGMENT_TRACK_CONTINUITY_INCREASED")
    return {
        "schema":SCHEMA,
        "source_frames":len(frames),
        "adjacent_source_transitions":len(states),
        "background_geometry_candidate_transitions":states.count(ACCEPT),
        "untrusted_or_unverifiable_transitions":
            len(states)-states.count(ACCEPT),
        "camera_ambiguous_transitions_are_linked":False,
        "research_scene_segments":len(segment_sizes),
        "single_frame_segments":sum(x==1 for x in segment_sizes),
        "largest_research_scene_segment_frames":max(segment_sizes),
        "baseline_untrusted_color_track_candidates":
            baseline["untrusted_track_candidates_total"],
        "baseline_untrusted_color_tracks_seen_twice":
            baseline["track_candidates_seen_in_at_least_two_frames"],
        "scene_guarded_untrusted_color_track_candidates":guarded_tracks,
        "scene_guarded_untrusted_color_tracks_seen_twice":guarded_repeat,
        "baseline_tracks_not_independently_verified":True,
        "camera_model_not_independent_rider_identity":True,
        "confirmed_rider_track_accuracy_pct":None,
        "confirmed_rider_number_OCR_accuracy_pct":None,
        "confirmed_line_position_accuracy_pct":None,
        "confirmed_phase_accuracy_pct":None,
        "verified_human_independent_reference_count":0,
        "eligible_for_formal_PDCA_or_training":False,
        "existing_PR71_model_weights_modified":False,
        "public_frame_data_or_private_coordinates_in_output":False,
    }
