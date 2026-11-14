"""Owner-private daily video feature learning, NEVER a rider-tactics oracle.

After decrypting authorized WINTICKET browser captures, this module extracts
source-bound visual descriptors, ranks motion/scene-shift candidate frames,
and fits a *self-supervised* KMeans scene representation only on TRAIN clips.
A true untouched HOLDOUT can measure visual drift, not classification skill.
To teach a model 捲り/差し/逃げ, independently proven rider-ID and action labels
must be added by a separate review gate. Unobserved actions stay UNKNOWN.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path

FEATURE_SCHEMA="RACE_AI_KEIRIN_DAILY_PRIVATE_FRAME_FEATURES_V1"
MODEL_SCHEMA="RACE_AI_KEIRIN_DAILY_SELF_SUPERVISED_SCENE_V1"
CLASSES=("TRAIN_CANDIDATE","UNSEEN_VIDEO_HOLDOUT")
SIZE=(192,108)
REGIONS=((0,0,192,108),(0,0,192,20),(0,20,192,64),
         (0,64,192,108),(0,24,64,100),(64,24,128,100),
         (128,24,192,100))
class ResearchInputError(ValueError):pass
def check(ok,reason):
 if not ok:raise ResearchInputError(reason)
def canonical(x):
 return json.dumps(x,sort_keys=True,ensure_ascii=False,
                   separators=(",",":"),allow_nan=False)
def digest(x):return sha256(canonical(x).encode()).hexdigest()

def frame_features(frame):
    import cv2
    import numpy as np
    check(getattr(frame,"ndim",0)==3 and frame.shape[2]==3,
          "INVALID_BGR_FRAME")
    # The WINTICKET player is embedded in a 1280x720 page screenshot.
    # A fixed crop is only a research visual window; it is NOT proof that
    # we isolated the track or identified any rider.
    height,width=frame.shape[:2]
    crop=frame[int(height*.303):int(height*.709),
               int(width*.299):int(width*.701)]
    check(crop.size>0,"EMPTY_PLAYER_CROP")
    view=cv2.resize(crop,SIZE,interpolation=cv2.INTER_AREA)
    hsv=cv2.cvtColor(view,cv2.COLOR_BGR2HSV)
    gray=cv2.cvtColor(view,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,55,140)
    out=[]
    for x0,y0,x1,y1 in REGIONS:
        part=hsv[y0:y1,x0:x1]
        out.extend([float(part[:,:,0].mean()/179),
                    float(part[:,:,1].mean()/255),
                    float(part[:,:,2].mean()/255),
                    float(edges[y0:y1,x0:x1].mean()/255)])
        for channel in (0,1,2):
            bins=cv2.calcHist([part],[channel],None,[8],
                  [0,180] if channel==0 else [0,256]).ravel()
            out.extend((bins/max(1,float(bins.sum()))).tolist())
    check(len(out)==196 and all(math.isfinite(x) for x in out),
          "INVALID_196_FEATURES")
    low=cv2.resize(gray,(32,32)).astype("float32")
    dct=cv2.dct(low)[:8,:8].ravel()
    threshold=float(__import__("numpy").median(dct[1:]))
    bits=0
    for x in dct:
        bits=(bits<<1)|int(float(x)>threshold)
    return {"vector":out,"p_hash64":f"{bits:016x}",
            "crop_sha256":sha256(crop.tobytes()).hexdigest(),
            "gray192":gray}

def read_private_video(path, *, race_id, cohort, every_s=2):
    """Read bounded frames and export NO picture pixels to JSON."""
    import cv2
    import numpy as np
    check(cohort in CLASSES,"COHORT_NOT_PREDECLARED")
    check(type(every_s) is int and 1<=every_s<=5,"INVALID_FRAME_RATE")
    p=Path(path)
    check(p.is_file() and p.stat().st_size>=10000,"REAL_VIDEO_NOT_PRESENT")
    source_sha=sha256(p.read_bytes()).hexdigest()
    cap=cv2.VideoCapture(str(p))
    check(cap.isOpened(),"UNDECODABLE_WEBM")
    duration=float(cap.get(cv2.CAP_PROP_FRAME_COUNT)/
                   max(.01,cap.get(cv2.CAP_PROP_FPS)))
    check(30<=duration<=3600,"INVALID_BROWSER_VIDEO_DURATION")
    frames=[];before=None
    for sec in range(0,int(duration),every_s):
        cap.set(cv2.CAP_PROP_POS_MSEC,sec*1000)
        ok,frame=cap.read()
        if not ok:continue
        features=frame_features(frame)
        current=features.pop("gray192")
        delta=(float(np.mean(np.abs(current.astype("float32")-
                    before.astype("float32")))/255.0)
               if before is not None else 0.0)
        before=current
        frames.append({
          "capture_second":sec,"frame_sha256":features["crop_sha256"],
          "p_hash64":features["p_hash64"],
          "motion_scene_change_score":round(delta,5),
          "features":features["vector"],
          "action_identity_verified":False,
          "tactical_label":"UNKNOWN_UNREVIEWED"})
    cap.release()
    check(len(frames)>=12,"INSUFFICIENT_DECODED_VIDEO_FRAMES")
    result={
      "schema":FEATURE_SCHEMA,
      "race_id":race_id,"cohort":cohort,
      "browser_video_sha256":source_sha,
      "source_bytes":p.stat().st_size,
      "browser_recording_duration_s":round(duration,3),
      "sampling_seconds":every_s,
      "frames":frames,
      "real_source":True,
      "video_visible_event_labels_are_unknown":True,
      "all_four_laps_claimed":False,
      "official_prediction_modified":False,
    }
    result["feature_sha256"]=digest(result)
    return result

def make_review_queue(docs, *, peak_count=12):
    """Suggest inspection timestamps; NEVER produce a rider/action truth label."""
    check(type(docs) is list,"FEATURE_DOCS_REQUIRED")
    items=[]
    for doc in docs:
        check(doc.get("schema")==FEATURE_SCHEMA and
              doc.get("feature_sha256")==digest({
                k:v for k,v in doc.items() if k!="feature_sha256"}),
              "MUTATED_FEATURE_SOURCE")
        ranking=sorted(doc["frames"],
                       key=lambda r:(-r["motion_scene_change_score"],
                                     r["capture_second"]))
        chosen=[]
        for frame in ranking:
            if all(abs(frame["capture_second"]-v["capture_second"])>=6
                   for v in chosen):
                chosen.append(frame)
                if len(chosen)>=peak_count:break
        for f in sorted(chosen,key=lambda r:r["capture_second"]):
            items.append({
                "race_id":doc["race_id"],
                "cohort":doc["cohort"],
                "browser_video_sha256":doc["browser_video_sha256"],
                "frame_sha256":f["frame_sha256"],
                "capture_second":f["capture_second"],
                "motion_scene_change_score":f["motion_scene_change_score"],
                "candidate":"POSSIBLE_SCENE_CHANGE_OR_CAMERA_MOTION",
                "rider_id":None,"tactical_label":"UNKNOWN_UNREVIEWED",
                "independent_review_completed":False,
                "learnable_yet":False,
            })
    return {"schema":"RACE_AI_KEIRIN_PRIVATE_FRAME_REVIEW_QUEUE_V1",
        "candidate_count":len(items),"candidates":items,
        "forecast_accuracy_proven":False}

def fit_private_representation(docs, *, min_train_races=2,
                               min_holdout_races=1, n_clusters=6):
    """Unsupervised self-training with clean train/holdout source split.

    The returned model cannot be promoted to betting prediction and is not a
    validated attack or finish classifier. 'Improvement' cannot be inferred
    from KMeans inertia or unseen-feature shift alone.
    """
    import numpy as np
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.preprocessing import StandardScaler
    check(type(docs) is list,"FEATURE_DOCS_REQUIRED")
    sources=set()
    for d in docs:
        check(d.get("schema")==FEATURE_SCHEMA and
              d.get("feature_sha256")==digest({
                k:v for k,v in d.items() if k!="feature_sha256"}),
              "FEATURE_SOURCE_INTEGRITY_FAILURE")
        check(d["browser_video_sha256"] not in sources,
              "DUPLICATE_SOURCE_VIDEO_ACROSS_RACES")
        sources.add(d["browser_video_sha256"])
    train=[d for d in docs if d["cohort"]=="TRAIN_CANDIDATE"]
    held=[d for d in docs if d["cohort"]=="UNSEEN_VIDEO_HOLDOUT"]
    if len(train)<min_train_races or len(held)<min_holdout_races:
        return {
         "schema":MODEL_SCHEMA,
         "status":"TRAIN_OR_HOLDOUT_EVIDENCE_INSUFFICIENT",
         "train_races":len(train),"heldout_races":len(held),
         "verified_rider_tactics_labels":0,
         "official_prediction_model_updated":False,
         "empirical_forecast_improvement":None}
    train_races={x["race_id"] for x in train}
    test_races={x["race_id"] for x in held}
    check(train_races.isdisjoint(test_races),"TRAIN_HOLDOUT_RACE_OVERLAP")
    xs=np.asarray([row["features"] for d in train for row in d["frames"]])
    xt=np.asarray([row["features"] for d in held for row in d["frames"]])
    check(xs.ndim==2 and xs.shape[1]==196 and
          len(xs)>=n_clusters*5 and xt.shape[1]==196,
          "INSUFFICIENT_REAL_FRAME_SUPPORT")
    scaler=StandardScaler().fit(xs)
    a=scaler.transform(xs);b=scaler.transform(xt)
    km=MiniBatchKMeans(n_clusters=n_clusters,batch_size=64,
                       n_init=5,max_iter=250,random_state=19)
    km.fit(a)
    train_d=float(km.transform(a).min(axis=1).mean())
    hold_d=float(km.transform(b).min(axis=1).mean())
    out={
        "schema":MODEL_SCHEMA,
        "status":"RESEARCH_SELF_SUPERVISED_MODEL_FITTED_NOT_PREDICTIVE_PROOF",
        "model_version":"v1-UNSUPERVISED-NO-TOP8-PROMOTION",
        "train_races":sorted(train_races),
        "heldout_races":sorted(test_races),
        "train_source_sha256":sorted(d["browser_video_sha256"] for d in train),
        "heldout_source_sha256":sorted(d["browser_video_sha256"] for d in held),
        "train_frames":len(xs),"holdout_frames":len(xt),
        "n_clusters":n_clusters,
        "scaler_mean":scaler.mean_.tolist(),
        "scaler_scale":scaler.scale_.tolist(),
        "centers":km.cluster_centers_.tolist(),
        "train_mean_nearest_center_distance":train_d,
        "heldout_mean_nearest_center_distance":hold_d,
        "heldout_scene_shift_is_not_classification_accuracy":True,
        "verified_rider_tactics_labels":0,
        "real_trifecta_A_B_forecasts_compared":0,
        "improvement_proven":False,
        "production_model_weights_updated":False,
    }
    out["model_sha256"]=digest(out)
    return out
