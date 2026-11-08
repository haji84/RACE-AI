#!/usr/bin/env python3
"""Private owner-side CLI: recorded video -> features -> reviewed model -> audit.

Run as: python -m scripts.keirin_video_ai_owner_cli <command> ...
The public RACE-AI CI must never access copyrighted source footage or private
prediction originals. This tool deliberately has no network or browser code.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from race_ai.keirin_video_learning import (
    sample_private_video,train_reviewed_classifier,
    bind_reviewed_labels_to_frames,SceneLearningError)
from race_ai.keirin_video_inference import to_review_queue

def private_output(p:Path, obj:dict):
    """Refuse overwrites and symlinks; keep local review data owner-private."""
    p=Path(p)
    if p.exists() or p.is_symlink():
        raise ValueError("PRIVATE_OUTPUT_ALREADY_EXISTS")
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY
    if hasattr(os,"O_NOFOLLOW"):flags|=os.O_NOFOLLOW
    fd=os.open(str(p),flags,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(obj,f,ensure_ascii=False,sort_keys=True,indent=2,
                  allow_nan=False)
        f.write("\n")
    return p

def load_private(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>30000000:
        raise ValueError("PRIVATE_INPUT_INVALID")
    return json.loads(p.read_text(encoding="utf-8"))

def main(argv=None):
    parser=argparse.ArgumentParser()
    subs=parser.add_subparsers(dest="command",required=True)
    extract=subs.add_parser("extract")
    extract.add_argument("--video",required=True)
    extract.add_argument("--race-id",required=True)
    extract.add_argument("--every-seconds",type=int,default=2)
    extract.add_argument("--panel",type=float,nargs=4,default=None,
       metavar=("X0","Y0","X1","Y1"),
       help="Relative browser video region, e.g. WINTICKET Yahiko popup: 0.30 0.30 0.70 0.71")
    extract.add_argument("--output",required=True)
    train=subs.add_parser("train")
    train.add_argument("--reviewed-labels",action="append",required=True)
    train.add_argument("--features",action="append",required=True,
                       help="Exactly one private feature file per reviewed-label file")
    train.add_argument("--development-race",action="append",default=[],
                       help="Race(s) already used during algorithm development. Never claim these as unseen.")
    train.add_argument("--output",required=True)
    infer=subs.add_parser("infer")
    infer.add_argument("--features",required=True)
    infer.add_argument("--model",required=True)
    infer.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    if (os.environ.get("GITHUB_ACTIONS")=="true"
        and args.command=="extract"
        and not args.race_id.startswith("synthetic-")):
        raise SystemExit("REAL_VIDEO_EXTRACTION_REQUIRES_PRIVATE_OWNER_RUNTIME")
    if args.command=="extract":
        args_panel=tuple(args.panel) if args.panel is not None else (.19,.42,.81,.93)
        doc=sample_private_video(args.video,race_id=args.race_id,
                                 every_s=args.every_seconds,panel=args_panel)
        private_output(Path(args.output),doc)
        print(json.dumps({"phase":"EXTRACT","race_id":doc["race_id"],
              "frames":len(doc["features"]),"raw_video_exported":False,
              "features_kept_owner_private":True},ensure_ascii=False))
    elif args.command=="train":
        if len(args.features)!=len(args.reviewed_labels):
            raise ValueError("FEATURE_REVIEW_PAIR_COUNT_MISMATCH")
        docs=[bind_reviewed_labels_to_frames(load_private(f),load_private(l))
              for f,l in zip(args.features,args.reviewed_labels)]
        model=train_reviewed_classifier(docs,dev_races=args.development_race)
        private_output(Path(args.output),model)
        print(json.dumps({"phase":"TRAIN","status":model["validation_status"],
              "heldout_races":len(model["heldout_races"]),
              "holdout_macro_f1":model["holdout_macro_f1"],
              "can_self_approve_four_laps":False},ensure_ascii=False))
    else:
        feature_doc=load_private(args.features)
        model=load_private(args.model)
        queue=to_review_queue(feature_doc,model)
        private_output(Path(args.output),queue)
        print(json.dumps({"phase":"INFER","race_id":feature_doc["race_id"],
              "status":queue["audit"]["status"],
              "review_needed":queue["private_review_required"],
              "lap_candidates":queue["audit"]["candidate_count"],
              "replay_intervals":len(queue["audit"]["replay_intervals"])},
            ensure_ascii=False))

if __name__=="__main__":
    try:main()
    except (ValueError,SceneLearningError) as e:
        print("STOP: "+str(e),file=sys.stderr)
        raise SystemExit(2)
