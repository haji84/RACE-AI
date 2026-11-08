"""Private-only trainable scene recognition for keirin browser recordings.

No betting, forecasts, outcomes, stream download, or source rights decisions.
Full-size image frames and labels stay on the owner runtime. Only numeric
features and hashes are considered for classifier inference. Each training
label needs a separately reviewed image/interval; never treat detected labels
as self-proving ground truth.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from hashlib import sha256
from pathlib import Path
import json
import math
import subprocess

CLASSES=("START","HOME_PASS","GOAL","REPLAY","RESULT","RACING","PRESTART")
FEATURE_SCHEMA="RACE_AI_KEIRIN_PRIVATE_VIDEO_FEATURES_V1"
MODEL_SCHEMA="RACE_AI_KEIRIN_PRIVATE_SCENE_MODEL_V1"
TRAIN_SCOPE="OWNER_REVIEWED_FRAME_LABELS_ONLY"

class SceneLearningError(ValueError):
    pass

def need(ok,code):
    if not ok: raise SceneLearningError(code)

def digest(obj):
    return sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,
        separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()

def frame_fingerprint(image):
    import cv2
    import numpy as np
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
    sm=cv2.resize(gray,(32,32),interpolation=cv2.INTER_AREA).astype("float32")
    dct=cv2.dct(sm)[:8,:8].reshape(-1)
    median=float(np.median(dct[1:]))
    bits=0
    for value in dct: bits=(bits<<1)|int(value>median)
    return f"{bits:016x}"

def features_from_rgb(image):
    import cv2
    import numpy as np
    # The crop is the WINTICKET inner video panel, not a site background.
    need(image.ndim==3 and image.shape[2]==3,"INVALID_IMAGE")
    h,w=image.shape[:2]
    need(h>=80 and w>=120,"IMAGE_TOO_SMALL")
    small=cv2.resize(image,(192,108),interpolation=cv2.INTER_AREA)
    hsv=cv2.cvtColor(small,cv2.COLOR_RGB2HSV)
    gray=cv2.cvtColor(small,cv2.COLOR_RGB2GRAY)
    edge=cv2.Canny(gray,55,140)
    # Explicitly include per-zone top-bar and track color patterns.
    values=[]
    for roi in (
        (0,0,192,108),(0,0,192,20),(0,20,192,64),
        (0,64,192,108),(0,24,64,100),(64,24,128,100),
        (128,24,192,100)):
        x0,y0,x1,y1=roi
        patch=hsv[y0:y1,x0:x1]
        values += [
           round(float(patch[:,:,0].mean())/179.0,5),
           round(float(patch[:,:,1].mean())/255.0,5),
           round(float(patch[:,:,2].mean())/255.0,5),
           round(float(edge[y0:y1,x0:x1].mean())/255.0,5)
        ]
        for idx in (0,1,2):
            hist=cv2.calcHist([patch],[idx],None,[8],
                              [0,180] if idx==0 else [0,256]).reshape(-1)
            hist=hist/max(1.,float(hist.sum()))
            values.extend(round(float(x),5) for x in hist)
    # All numeric; no copyrighted image pixels are copied to results.
    return values

def sample_private_video(path, *, race_id, every_s=2, max_seconds=9000,
                         panel=(.19,.42,.81,.93)):
    """Return in-memory features with frame digests, not raw image exports.

    ffmpeg decodes only a bounded stream of low-resolution RGB frames. Do not
    run this in a public CI on private video or log output rows.
    """
    import cv2
    import numpy as np
    p=Path(path)
    need(p.is_file() and not p.is_symlink(),"PRIVATE_VIDEO_UNAVAILABLE")
    need(1<=every_s<=10,"INVALID_SAMPLING_INTERVAL")
    need(len(panel)==4 and 0<=panel[0]<panel[2]<=1 and
         0<=panel[1]<panel[3]<=1,"INVALID_PLAYER_REGION")
    meta=subprocess.run(["ffprobe","-v","error","-show_entries",
           "format=duration","-of","json",str(p)],
        text=True,capture_output=True,timeout=20,check=True)
    seconds=float(json.loads(meta.stdout)["format"]["duration"])
    need(math.isfinite(seconds) and 20<=seconds<=max_seconds,
         "RECORDING_DURATION_OUT_OF_RANGE")
    size=(192,108)
    cmd=["ffmpeg","-v","error","-i",str(p),"-vf",
         f"fps=1/{every_s},scale={size[0]}:{size[1]}:flags=fast_bilinear",
         "-pix_fmt","rgb24","-f","rawvideo","pipe:1"]
    proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    frame_size=size[0]*size[1]*3
    data=[]
    try:
        for frame_idx in range(math.ceil(seconds/every_s)+1):
            chunk=proc.stdout.read(frame_size)
            if len(chunk)!=frame_size:break
            rgb=np.frombuffer(chunk,dtype=np.uint8).reshape(
                (size[1],size[0],3)).copy()
            x0=int(panel[0]*size[0]);x1=int(panel[2]*size[0])
            y0=int(panel[1]*size[1]);y1=int(panel[3]*size[1])
            crop=rgb[y0:y1,x0:x1]
            # Crop is sampled at reduced resolution; upscale to a standard
            # analysis grid while maintaining the image-region provenance.
            crop=cv2.resize(crop,(192,108),interpolation=cv2.INTER_AREA)
            data.append({"t":round(frame_idx*every_s,3),
                         "frame_sha256":sha256(crop.tobytes()).hexdigest(),
                         "phash64":frame_fingerprint(crop),
                         "vector":features_from_rgb(crop)})
    finally:
        if proc.stdout:proc.stdout.close()
        try:proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait()
    need(len(data)>=5 and proc.returncode==0,"VIDEO_FEATURE_EXTRACTION_FAILED")
    return {
        "schema":FEATURE_SCHEMA,"race_id":race_id,
        "recording_sha256":sha256(p.read_bytes()).hexdigest(),
        "duration_s":seconds,"sampling_seconds":every_s,
        "panel":list(panel),"feature_version":"HSV_GRID_EDGE_7x28_v1",
        "features":data,
        "raw_video_exported":False,"source_outcomes_used":False,
    }

def validated_rows(docs):
    """Join labels by exact frame digest; AI outputs are not training labels."""
    need(isinstance(docs,list) and docs,"TRAINING_DOCUMENTS_REQUIRED")
    rows=[]; races=set()
    for doc in docs:
        need(type(doc) is dict and set(doc)=={
            "schema","race_id","recording_sha256","samples"},
            "INVALID_LABEL_DOCUMENT")
        need(doc["schema"]=="RACE_AI_KEIRIN_REVIEWED_SCENES_V1",
             "UNREVIEWED_LABELS")
        need(len(doc["recording_sha256"])==64,"MISSING_SOURCE_SHA")
        need(type(doc["samples"]) is list,"INVALID_LABEL_ROWS")
        races.add(doc["race_id"])
        for row in doc["samples"]:
            need(type(row) is dict and set(row)=={
                "frame_sha256","label","vector","reviewed","review_ref"},
                "INVALID_LABEL_ROW")
            need(row["label"] in CLASSES and row["reviewed"] is True and
                 isinstance(row["review_ref"],str) and row["review_ref"],
                 "TRAINING_LABEL_NOT_HUMAN_REVIEWED")
            need(isinstance(row["vector"],list) and len(row["vector"])==len(
                 rows[0]["vector"]) if rows else isinstance(row["vector"],list)
                 and len(row["vector"])==196,"INCONSISTENT_FEATURES")
            need(all(type(x) in (int,float) and math.isfinite(x)
                     for x in row["vector"]),"NONFINITE_FEATURE")
            need(isinstance(row["frame_sha256"],str) and
                 len(row["frame_sha256"])==64,"INVALID_FRAME_SHA")
            rows.append({**row,"race_id":doc["race_id"],
                         "recording_sha256":doc["recording_sha256"]})
    need(len(rows)<=30000,"EXCESSIVE_TRAINING_ROWS")
    return rows,races

def train_reviewed_classifier(docs, *, minimum_races=3, min_f1=.85):
    """Group-held-out by race. Promotion is blocked if accuracy is unproven.

    Even a validated classifier proposes scenes; separate independent visual
    source approval is needed before any four-lap acceptance.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score,classification_report
    from sklearn.preprocessing import StandardScaler
    rows,races=validated_rows(docs)
    need(len(races)>=minimum_races,"NOT_ENOUGH_DISTINCT_VERIFIED_RACES")
    need(set(x["label"] for x in rows)==set(CLASSES),
         "INCOMPLETE_SCENE_CLASSES")
    n_features=len(rows[0]["vector"])
    need(n_features>0,"NO_FEATURES")
    # A stable deterministic holdout race avoids training/test row leakage.
    holdout=sorted(races)[-1]
    tr=[x for x in rows if x["race_id"]!=holdout]
    te=[x for x in rows if x["race_id"]==holdout]
    need(set(x["label"] for x in tr)==set(CLASSES) and
         set(x["label"] for x in te)==set(CLASSES) and
         len(tr)>=35 and len(te)>=14,"NOT_ENOUGH_TRAIN_HOLDOUT_SUPPORT")
    need(len({x["recording_sha256"] for x in tr})>=2,
         "TRAINING_RACE_SOURCE_VARIETY_REQUIRED")
    need(holdout not in {x["race_id"] for x in tr},"RACE_LEAKAGE")
    scaler=StandardScaler().fit(np.array([r["vector"] for r in tr]))
    x=scaler.transform(np.array([r["vector"] for r in tr]))
    model=LogisticRegression(C=0.5,class_weight="balanced",max_iter=700,
                             random_state=17).fit(
                             x,np.array([r["label"] for r in tr]))
    predictions=model.predict(scaler.transform(
        np.array([r["vector"] for r in te])))
    target=[r["label"] for r in te]
    measured=float(f1_score(target,predictions,labels=list(CLASSES),
                            average="macro",zero_division=0))
    hist=Counter(target)
    counts={k:hist[k] for k in CLASSES}
    model_out={
       "schema":MODEL_SCHEMA,"version":"0.1-PRIVATE-RESEARCH",
       "feature_version":"HSV_GRID_EDGE_7x28_v1",
       "train_scope":TRAIN_SCOPE,"classes":list(model.classes_),
       "mean":scaler.mean_.tolist(),"scale":scaler.scale_.tolist(),
       "weights":model.coef_.tolist(),"intercepts":model.intercept_.tolist(),
       "train_races":sorted(races-{holdout}),
       "heldout_races":[holdout],
       "holdout_rows":len(te),"holdout_support":counts,
       "holdout_macro_f1":round(measured,5),
       "calibrated_probabilities":False,
       "validation_status":("RESEARCH_HOLDOUT_PASSED" if measured>=min_f1
                            and min(counts.values())>=2 else "NOT_VALIDATED"),
       "not_authorized_for_official_prediction":True,
       "real_race_label_sources":sorted({r["recording_sha256"] for r in rows}),
       "input_video_or_results_exported":False,
    }
    model_out["model_sha256"]=digest(model_out)
    return model_out

def predict_scene(model,frame):
    """Score predictions. 'confidence' is a raw softmax score, NOT calibrated."""
    import numpy as np
    need(model.get("schema")==MODEL_SCHEMA,"INVALID_MODEL")
    need(model.get("model_sha256")==digest({
        k:v for k,v in model.items() if k!="model_sha256"}),"MODEL_SHA_MISMATCH")
    need(model.get("validation_status")=="RESEARCH_HOLDOUT_PASSED",
         "UNVALIDATED_MODEL_CANNOT_LABEL")
    v=np.array(frame["vector"],dtype="float64")
    mean=np.array(model["mean"]); scale=np.array(model["scale"])
    need(v.shape==mean.shape and np.all(np.isfinite(v)),"INVALID_FEATURE_VECTOR")
    z=np.array(model["weights"]).dot((v-mean)/scale)+np.array(
        model["intercepts"])
    z-=z.max()
    p=np.exp(z);p=p/p.sum()
    idx=int(p.argmax())
    return {"label":model["classes"][idx],"score":round(float(p[idx]),6),
            "score_not_calibrated":True,"model_sha256":model["model_sha256"],
            "frame_sha256":frame["frame_sha256"],"t":frame["t"]}
