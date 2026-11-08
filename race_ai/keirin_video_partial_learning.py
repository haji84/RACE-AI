"""Train a PRIVATE scene detector from reviewed full and/or short replay clips.

A short clip can teach the scene categories it *shows*. Its missing laps,
unseen attacks and unseen riders are NEVER treated as negatives. This research
model is separate from the FULL_LAP model and cannot certify lap counts or
modify existing official forecast model weights.

All real-video admission must be externally verified by the host at use time.
"""
from __future__ import annotations

from collections import Counter
import math

from .keirin_video_clip_policy import (
    ADMISSION_SCHEMA, CLASSES, LEARNABLE, TACTICAL,
    choose_preferred_clips, digest as clip_digest)
from .keirin_video_learning import FEATURE_SCHEMA, SceneLearningError, digest

PARTIAL_MODEL_SCHEMA="RACE_AI_KEIRIN_PARTIAL_SCENE_MODEL_V1"
FEATURE_VERSION="HSV_GRID_EDGE_7x28_v1"

def guard(ok,code):
    if not ok:
        raise SceneLearningError(code)

def extract_training_rows(bundles, *, trusted_admission_verifier):
    """Select one best source per race and join labels to its exact frame SHA.

    trusted_admission_verifier must be a separate owner-side witness, not a
    field inside the admission JSON and not a public Actions environment flag.
    """
    guard(type(bundles) is list and bundles,"NO_CLIP_BUNDLES")
    guard(callable(trusted_admission_verifier),
          "INDEPENDENT_ADMISSION_ATTESTOR_REQUIRED")
    for b in bundles:
        guard(type(b) is dict and set(b)=={"features","admission"},
              "INVALID_CLIP_BUNDLE")
    admissions=[b["admission"] for b in bundles]
    selected=choose_preferred_clips(admissions)["selected"]
    guard(selected,"NO_INDEPENDENTLY_ADMITTED_CLIP")
    picked=[]
    for race_id,admission in selected.items():
        found=[b for b in bundles
               if b["admission"]["race_id"]==race_id and
               b["admission"]["recording_sha256"]==
                  admission["recording_sha256"]]
        guard(len(found)==1,"AMBIGUOUS_VIDEO_SOURCE_FOR_RACE")
        picked.append(found[0])
    result=[]; source_sha=set(); frames_seen=set()
    for b in picked:
        admission=b["admission"];features=b["features"]
        guard(admission["schema"]==ADMISSION_SCHEMA and
              admission["training_eligible"] is True,
              "CLIP_NOT_ADMITTED")
        guard(admission["source_kind"]!="SYNTHETIC_FIXTURE",
              "SYNTHETIC_VIDEO_NOT_REAL_TRAINING")
        ok=False
        try:ok=trusted_admission_verifier(admission) is True
        except Exception:pass
        guard(ok,"OWNER_RIGHTS_AND_REVIEW_ATTESTATION_MISSING")
        guard(type(features) is dict and features.get("schema")==FEATURE_SCHEMA
              and features.get("feature_version")==FEATURE_VERSION,
              "FEATURE_DOCUMENT_VERSION_MISMATCH")
        guard(features.get("race_id")==admission["race_id"] and
              features.get("recording_sha256")==admission["recording_sha256"],
              "VIDEO_AND_FRAME_PROVENANCE_MISMATCH")
        source=admission["recording_sha256"]
        guard(source not in source_sha,
              "CROSS_RACE_DUPLICATE_RECORDING")
        source_sha.add(source)
        by_sha={}
        for frame in features.get("features",[]):
            key=frame.get("frame_sha256")
            guard(type(key) is str and len(key)==64 and key not in by_sha,
                  "INVALID_OR_DUPLICATE_SOURCE_FRAME")
            guard(type(frame.get("vector")) is list and
                  len(frame["vector"])==196 and all(
                   type(x) in (float,int) and math.isfinite(x) for x in frame["vector"]),
                  "INVALID_SOURCE_FEATURE_VECTOR")
            by_sha[key]=frame
        used=set();joined=[]
        for scene in admission.get("reviewed_scene_frames",[]):
            label=scene["label"];frame_hash=scene["frame_sha256"]
            guard(label in CLASSES,"UNKNOWN_PARTIAL_SCENE")
            guard(frame_hash in by_sha,"REVIEWED_FRAME_NOT_IN_VIDEO")
            # Identical frame reused twice is not a second training sample.
            guard(frame_hash not in used and frame_hash not in frames_seen,
                  "DUPLICATE_REVIEWED_FRAME")
            used.add(frame_hash);frames_seen.add(frame_hash)
            guard(type(scene["review_ref"]) is str and
                  len(scene["review_ref"])>=6,"REVIEW_REF_MISSING")
            joined.append({
                "label":label,"vector":by_sha[frame_hash]["vector"],
                "frame_sha256":frame_hash,
                "source_recording_sha256":source,
                "race_id":admission["race_id"],
                "review_ref":scene["review_ref"],
                "admitted_coverage":admission["admitted_coverage"],
            })
        guard(joined,"ADMITTED_CLIP_LACKS_SCENE_TRAINING_FRAMES")
        result.extend(joined)
    guard(len(result)<=50000,"EXCESSIVE_SCENE_TRAINING_ROWS")
    return result,selected

def train_partial_scene_model(bundles, *, trusted_admission_verifier,
                              min_races=3, min_macro_f1=.85,
                              dev_races=None):
    """Fit observed-scene labels, never four-lap or tactical absence labels."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.preprocessing import StandardScaler

    rows,selected=extract_training_rows(
        bundles,trusted_admission_verifier=trusted_admission_verifier)
    races=sorted(selected)
    guard(type(min_races) is int and min_races>=3,"MINIMUM_RACES_TOO_LOW")
    guard(len(races)>=min_races,"NOT_ENOUGH_REAL_REVIEWED_RACES")
    dev=[] if dev_races is None else dev_races
    guard(type(dev) is list and len(set(dev))==len(dev) and
          all(type(r) is str and r for r in dev),"INVALID_DEVELOPMENT_SET")
    guard(set(races).isdisjoint(set(dev)),"DEVELOPMENT_RACE_LEAK")
    holdout=races[-1]
    tr=[r for r in rows if r["race_id"]!=holdout]
    te=[r for r in rows if r["race_id"]==holdout]
    classes={r["label"] for r in rows}
    guard(len(classes)>=2 and bool(classes.intersection(LEARNABLE)),
          "NOT_ENOUGH_DISTINCT_VISIBLE_SCENE_CLASSES")
    guard(classes=={r["label"] for r in tr}==
          {r["label"] for r in te},"TRAIN_HOLDOUT_CLASS_GAP")
    guard(len(tr)>=12 and len(te)>=6,"INSUFFICIENT_SCENE_SAMPLE_SUPPORT")
    support=Counter(r["label"] for r in te)
    guard(all(support[c]>=2 for c in classes),
          "INSUFFICIENT_HELDOUT_LABEL_SUPPORT")
    guard({r["source_recording_sha256"] for r in tr}.isdisjoint(
          {r["source_recording_sha256"] for r in te}),
          "HELDOUT_SOURCE_LEAK")
    guard({r["frame_sha256"] for r in tr}.isdisjoint(
          {r["frame_sha256"] for r in te}),"HELDOUT_FRAME_LEAK")
    scaler=StandardScaler().fit(np.array([x["vector"] for x in tr]))
    model=LogisticRegression(max_iter=750,class_weight="balanced",
                             random_state=19,C=.6).fit(
                             scaler.transform(np.array([x["vector"] for x in tr])),
                             [x["label"] for x in tr])
    pred=model.predict(scaler.transform(
         np.array([x["vector"] for x in te])))
    score=float(f1_score([x["label"] for x in te],pred,
                   labels=sorted(classes),average="macro",zero_division=0))
    admitted_full=sum(x["admitted_coverage"]=="FULL_FOUR_LAPS"
                      for x in selected.values())
    result={
        "schema":PARTIAL_MODEL_SCHEMA,
        "feature_version":FEATURE_VERSION,
        "model_kind":"OBSERVED_SCENE_CLASSIFIER_NOT_A_LAP_COUNTER",
        "trained_on_visible_labels_only":True,
        "never_treats_unseen_attack_as_negative":True,
        "class_names":list(model.classes_),
        "scaler_mean":scaler.mean_.tolist(),
        "scaler_scale":scaler.scale_.tolist(),
        "coefficients":model.coef_.tolist(),
        "intercepts":model.intercept_.tolist(),
        "train_races":races[:-1],"heldout_races":[holdout],
        "dev_races":list(dev),
        "train_recording_sha256":sorted({x["source_recording_sha256"]
                                        for x in tr}),
        "train_count":len(tr),"holdout_count":len(te),
        "holdout_class_support":dict(sorted(support.items())),
        "holdout_macro_f1":round(score,5),
        "full_video_sources":admitted_full,
        "partial_video_sources":len(selected)-admitted_full,
        "validation_status":("RESEARCH_SCENE_HOLDOUT_PASSED"
                             if score>=min_macro_f1 else "NOT_VALIDATED"),
        "score_calibrated":False,
        "four_laps_certified":False,
        "official_prediction_modified":False,
        "raw_video_or_frames_exported":False,
    }
    result["model_sha256"]=digest(result)
    return result

def predict_visible_scene(model,frame, *, race_id):
    """Research scene candidate only; the model never identifies a rider."""
    import numpy as np
    guard(model.get("schema")==PARTIAL_MODEL_SCHEMA and
          model.get("model_sha256")==digest({
           k:v for k,v in model.items() if k!="model_sha256"}),
          "PARTIAL_MODEL_INTEGRITY_ERROR")
    guard(model.get("validation_status")=="RESEARCH_SCENE_HOLDOUT_PASSED",
          "PARTIAL_MODEL_NOT_VALIDATED")
    guard(model.get("four_laps_certified") is False,
          "PARTIAL_MODEL_CANNOT_CERTIFY_LAPS")
    guard(race_id not in model["train_races"] and
          race_id not in model["dev_races"] and
          race_id not in model["heldout_races"],"SCENE_TEST_RACE_CONTAMINATED")
    v=np.asarray(frame.get("vector"),dtype=float)
    mean=np.asarray(model["scaler_mean"]);scale=np.asarray(model["scaler_scale"])
    guard(v.shape==mean.shape and np.all(np.isfinite(v)),
          "INVALID_PARTIAL_FEATURE")
    z=np.asarray(model["coefficients"]).dot((v-mean)/scale)+np.asarray(
      model["intercepts"])
    # For binary LogisticRegression, coef_ is 1xN and classes_ is size 2.
    if len(model["class_names"])==2 and z.shape[0]==1:
        z=np.array([-z[0],z[0]])/2.0
    z=z-z.max()
    probs=np.exp(z);probs/=probs.sum()
    at=int(probs.argmax())
    return {
        "race_id":race_id,"frame_sha256":frame["frame_sha256"],
        "label":model["class_names"][at],
        "score":round(float(probs[at]),6),
        "score_is_calibrated_probability":False,
        "four_laps_proven":False,
        "rider_identity_proven":False,
        "model_sha256":model["model_sha256"],
        "event_is_reviewed":False,
    }
