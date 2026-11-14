#!/usr/bin/env python3
"""Read-only REAL historic forecast-vs-video-availability audit.

This does not fit or select new weights after learning a result. With no
independently validated *pre-as-of* rider tactical features or a frozen B
forecast, an observed win is NEVER attributed to video learning.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import unicodedata

METHODS=("mean","balanced","ability_plus","line_plus",
         "lead_2","lead_1","lead_6")
TACTICS=("ATTACK","POSITION_GAIN","LINE_SPLIT","FINAL_SPRINT",
         "initiative","attack","position_gain","line_survival")
TRAIN_ROSTERS={
 "20261030-yahiko-2R":[
  "桜井太士","武井大介","中村美千隆","山根泰道","吉岡伸太郎","柴田祐也","山中秀将"],
 "20261030-yahiko-3R":[
  "坂上忠克","米村光星","森田康嗣","石口慶多","高鍋邦彰","松尾淳","佐々木祐太"],
 "20261030-yahiko-4R":[
  "坪内恒","平総一","猪俣康一","本田拓也","杉浦康一","牛田樹希斗","川野深"],
}
ROSTER_URLS={
 "20261030-yahiko-2R":"https://keirin.tokyo-sports.co.jp/list/race/20261029_31314",
 "20261030-yahiko-3R":"https://keirin.tokyo-sports.co.jp/list/race/20261029_31313",
 "20261030-yahiko-4R":"https://keirin.tokyo-sports.co.jp/list/race/20261029_31307",
 "20261108-matsuyama-2R":"https://keirin.tokyo-sports.co.jp/list/race/20261107_33273",
}
VIDEO_RECEIPT_EXPECTED="RACE_AI_REAL_SHORT_CLIP_SCENE_RESEARCH_V1"
SOURCE="RACE_AI_KEIRIN_VIDEO_LIFT_REAL_ELIGIBILITY_AUDIT_V1"

def demand(c,code):
    if not c: raise ValueError(code)

def stamp(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    demand(d.utcoffset() is not None,"MISSING_TIMEZONE")
    return d.astimezone(timezone.utc)

def norm(s):
    s=unicodedata.normalize("NFKC",str(s))
    return s.replace(" ","").replace("　","").replace("櫻井","桜井")

def sha_bytes(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def probability_slate(p,method):
    actual=p["race"]
    racers=p["participants"]
    numbers={v["n"] for v in racers}
    demand(len(numbers)==7 and all(1<=n<=7 for n in numbers),
           "NOT_SEVEN_UNIQUE_RIDERS")
    source=p["all_210"]
    demand(len(source)==210,"NOT_ALL_210_COMBINATIONS")
    full={tuple(i) for i in itertools.permutations(numbers,3)}
    slate={}
    for row in source:
        key=tuple(int(x) for x in row["combination"].split("-"))
        demand(key in full and key not in slate,"BAD_OR_DUPLICATE_COMBINATION")
        v=row[method]
        demand(type(v) in (int,float) and math.isfinite(v) and v>0,
               "MISSING_OR_INVALID_PROBABILITY")
        slate[key]=float(v)
    demand(set(slate)==full,"INCOMPLETE_COMBINATION_UNIVERSE")
    total=math.fsum(slate.values())
    demand(abs(total-1)<1e-6,"PROBABILITIES_NOT_NORMALIZED")
    return slate

def event_metrics(slate,winner):
    ranked=sorted(slate,key=lambda k:(-slate[k],k))
    rank=ranked.index(winner)+1
    p=slate[winner]
    brier=math.fsum(v*v for v in slate.values())+1-2*p
    return {
     "outcome_rank":rank,"hit_at_8":rank<=8,
     "outcome_probability_research_only":p,
     "log_loss":-math.log(p),"multiclass_brier":brier
    }

def audit(forecast_path,video_receipt_path,*,outcome=(2,3,1),
          target_video_sha256="",
          freeze_source="USER_LIBRARY_METADATA"):
    forecast=json.loads(Path(forecast_path).read_text(encoding="utf-8"))
    research=json.loads(Path(video_receipt_path).read_text(encoding="utf-8"))
    demand(forecast["schema"]=="MATS2R_RESEARCH_SCENARIO_PREDICTION_V1",
           "NOT_A_KNOWN_RESEARCH_BASELINE")
    demand(research.get("schema")==VIDEO_RECEIPT_EXPECTED,
           "NOT_A_KNOWN_VIDEO_RESEARCH_RECEIPT")
    target=forecast["race"]
    start_asof=stamp(target["as_of_jst"])
    cutoff=stamp(f"{target['date_jst']}T{target['sales_cutoff_jst']}:00+09:00")
    demand(start_asof<cutoff,"FORECAST_AFTER_CUTOFF")
    model_trained_at=stamp(research["sha_frozen_at"])
    trained_races=research["train_races"]
    demand(set(trained_races)==set(TRAIN_ROSTERS),"WRONG_TRAIN_RACE_GROUP")
    real_classes=set(research["classes"])
    tactical_classes=sorted(real_classes.intersection(TACTICS))
    test_names={norm(x["name"]) for x in forecast["participants"]}
    trained_names={norm(name) for group in TRAIN_ROSTERS.values() for name in group}
    shared=sorted(test_names & trained_names)
    base={}
    for method in METHODS:
        base[method]=event_metrics(probability_slate(forecast,method),outcome)
    mean=base["mean"]
    previous_asof_model=model_trained_at<start_asof
    trained_tactics=bool(tactical_classes) and bool(
      research.get("real_rider_attack_identity_labels_trained"))
    obstacles=[]
    if not previous_asof_model:
        obstacles.append("VIDEO_MODEL_BUILT_AFTER_TARGET_FORECAST_AS_OF")
    if not trained_tactics:
        obstacles.append("NO_VERIFIED_RIDER_TACTICS_MODEL")
    if not shared:
        obstacles.append("NO_TRAINING_RIDER_APPEARS_IN_TARGET_RACE")
    if research.get("independent_second_review_complete") is not True:
        obstacles.append("SCENE_LABELS_NOT_INDEPENDENTLY_REVIEWED")
    if research.get("goal_scene_trained") and research.get(
          "real_rider_attack_identity_labels_trained") is False:
        obstacles.append("GOAL_SCENE_DETECTION_IS_NOT_TRIFECTA_PREDICTION")
    obstacles.append("NO_FROZEN_VIDEO_BASED_210_PROBABILITY_DISTRIBUTION")
    obstacles.append("NO_REAL_OUT_OF_TIME_VIDEO_AB_TEST_COHORT")
    comparison={
      "schema":SOURCE,
      "target_race":"20261108-matsuyama-2R",
      "target_start":f"{target['date_jst']}T{target['scheduled_start_jst']}:00+09:00",
      "target_cutoff":cutoff.isoformat(),
      "base_as_of":start_asof.isoformat(),
      "base_file_sha256":sha_bytes(forecast_path),
      "base_source_scope":forecast["status"],
      "base_probability_universe":210,
      "truth_triple":"-".join(map(str,outcome)),
      "score_source":"published race result (separately checked)",
      "baseline_methods":base,
      "baseline_mean":mean,
      "train_videos":list(TRAIN_ROSTERS),
      "training_video_scene_classes":sorted(real_classes),
      "training_video_reviewed_frame_count":research["labeled_rows"],
      "training_video_model_frozen_at":model_trained_at.isoformat(),
      "training_model_after_target_as_of":not previous_asof_model,
      "training_riders_unique":len(trained_names),
      "test_riders_unique":len(test_names),
      "same_riders_in_training_and_target":shared,
      "verified_rider_tactics_labels_trained":trained_tactics,
      "target_historical_clip_sha256":target_video_sha256,
      "video_model_210_probabilities_available":False,
      "real_eligible_ab_races":0,
      "uplift_top8_pct_points":None,
      "uplift_log_loss":None,
      "uplift_brier":None,
      "future_live_predictive_lift": "NOT_MEASURED",
      "promotion_decision":"FAIL_CLOSED_NO_VERIFIED_VIDEO_FORECAST_UPLIFT",
      "failed_requirements":sorted(obstacles),
      "research_other_scenarios_do_not_prove_video_uplift":True,
      "private_forecast_original_modified":False,
      "official_model_weights_modified":False,
      "video_trained_source_sha256":research["model_sha256"],
      "source_urls":ROSTER_URLS,
      "evidence_timestamp_authority":freeze_source,
    }
    canonical=json.dumps(comparison,sort_keys=True,ensure_ascii=False,
                         separators=(",",":"),allow_nan=False).encode()
    comparison["report_sha256"]=hashlib.sha256(canonical).hexdigest()
    return comparison

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--forecast",type=Path,required=True)
    p.add_argument("--video-training-receipt",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args()
    result=audit(args.forecast,args.video_training_receipt,
       target_video_sha256="e59d9a235a76c2c9d5ec1224853e5bb0e689cd3a254fcac51c8aa240a87b4012")
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2,ensure_ascii=False),
                           encoding="utf-8")
    print(json.dumps({k:result.get(k) for k in (
      "target_race","baseline_mean","training_riders_unique",
      "test_riders_unique","same_riders_in_training_and_target",
      "training_model_after_target_as_of",
      "video_model_210_probabilities_available",
      "real_eligible_ab_races","promotion_decision",
      "failed_requirements")},ensure_ascii=False))
if __name__=="__main__":main()
