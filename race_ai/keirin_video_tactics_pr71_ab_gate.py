"""One-event rider video evidence -> PR71 model A / experimental video B.

This module NEVER synthesizes a missing existing PR71 model A. It consumes
the original, complete, 210-way immutable A candidate distribution from one
of the four pinned research models, verifies it, and only then produces a B
with a deliberately weak *pre-registered* positive-history adjustment.

B is a research hypothesis, not a model fitted/calibrated from video. To
claim genuinely learned predictive uplift requires a separately validated
multi-race tactical coefficient receipt, paired unseen outcomes and margins.

No input/result after the target cutoff, no current race footage, no odds,
no negative labels from off-camera actions, no betting, no overwrite.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import math
import os
import itertools
import re

SCHEMA="RACE_AI_KEIRIN_PRIOR_RIDER_VIDEO_AB_V1"
TYPES={"MAKURI":0.08,"SASHI":0.06,"NIGE":0.05}
KNOWN_PR71=frozenset({
  "multisport-factor-interaction-v1",
  "multisport-scenario-ensemble-v1",
  "multisport-conditional-duel-v1",
  "multisport-race-trajectory-v1",
})
HEX=re.compile(r"^[0-9a-f]{64}$")

class ABGateError(ValueError): pass

def require(test,code):
    if not test:raise ABGateError(code)

def canonical(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"),allow_nan=False)

def digest(obj):
    return sha256(canonical(obj).encode("utf-8")).hexdigest()

def when(value):
    try:
        stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
        require(stamp.utcoffset() is not None,"TIMEZONE_REQUIRED")
        return stamp.astimezone(timezone.utc)
    except (AttributeError,TypeError,ValueError):
        raise ABGateError("INVALID_TIME") from None

def video_events(race_id,asof,rider_by_no,events,verifier):
    require(callable(verifier),"INDEPENDENT_VIDEO_EVIDENCE_ATTESTOR_REQUIRED")
    extras={}
    known_race=set()
    for e in events:
        require(type(e) is dict,"INVALID_RIDER_EVIDENCE")
        require(type(e.get("historical_race_id")) is str and
                e["historical_race_id"]!=race_id,"SAME_RACE_VIDEO_LEAK")
        require(when(e.get("reviewed_at"))<=asof,"FUTURE_VIDEO_REVIEW_LEAK")
        require(e.get("action") in TYPES,"UNSUPPORTED_TECHNIQUE")
        require(type(e.get("rider_name")) is str and e["rider_name"],
                "RIDER_NAME_REQUIRED")
        require(type(e.get("source_video_sha256")) is str and
                HEX.fullmatch(e["source_video_sha256"]),
                "VIDEO_DIGEST_REQUIRED")
        require(type(e.get("frame_sha256")) is list and
                len(e["frame_sha256"])>=2 and all(
                type(x) is str and HEX.fullmatch(x)
                for x in e["frame_sha256"]),
                "ORIGINAL_VIDEO_FRAME_EVIDENCE_REQUIRED")
        require(e.get("owner_scoped_rights") is True and
                e.get("visible_positive_only") is True,
                "RIGHTS_OR_UNOBSERVED_NEGATIVE_RISK")
        require(e.get("review_level") in ("SINGLE_WITH_RESULT_CROSSCHECK",
                                         "INDEPENDENT_DOUBLE_REVIEW"),
                "REVIEW_LEVEL_UNSUPPORTED")
        require(verifier(e) is True,"VIDEO_EVIDENCE_NOT_INDEPENDENTLY_ATTESTED")
        rider=next((n for n,item in rider_by_no.items()
                    if item["rider_name"]==e["rider_name"]),None)
        if rider is None: continue
        token=(rider,e["historical_race_id"],e["action"])
        require(token not in known_race,"DUPLICATE_PRIOR_VIDEO_EVENT")
        known_race.add(token)
        require(rider not in extras,"ONE_PRIOR_POSITIVE_PER_RIDER_PILOT")
        extras[rider]={
            "prior_race_id":e["historical_race_id"],
            "action":e["action"],
            "video_sha256":e["source_video_sha256"],
            "review_level":e["review_level"],
            "reviewed_at":e["reviewed_at"],
            "single_positive_event":True,
            "negative_if_absent":False,
            "logit_delta":TYPES[e["action"]],
        }
    return extras

def validate_existing_a(a, *, attestor, clock):
    require(type(a) is dict and a.get("model_id") in KNOWN_PR71,
            "EXISTING_PR71_A_REQUIRED")
    require(callable(attestor) and attestor(a) is True,
            "EXISTING_A_ORIGINAL_NOT_INDEPENDENTLY_ATTESTED")
    require(a.get("model_version")=="0.1.0-UNTRAINED" and
            a.get("trained") is False and
            a.get("official_prediction") is False and
            a.get("odds_independent") is True,
            "NOT_ORIGINAL_RESEARCH_A")
    require(type(a.get("prediction_sha256")) is str and
            a["prediction_sha256"]==digest({
                k:v for k,v in a.items() if k!="prediction_sha256"}),
            "A_FORECAST_DIGEST_CHANGED")
    require(type(a.get("snapshot_sha256")) is str and
            HEX.fullmatch(a["snapshot_sha256"]), "A_SNAPSHOT_SHA_REQUIRED")
    asof=when(a.get("as_of"));cutoff=when(a.get("cutoff_at"))
    require(asof<=clock<cutoff and asof<cutoff,"A_AFTER_CUTOFF")
    candidate=a.get("candidates")
    require(type(candidate) is list and len(candidate)==210 and
            a.get("candidate_count")==210,"PR71_A_210_DISTRIBUTION_MISSING")
    group={};mass=0.
    for row in candidate:
        require(type(row) is dict and
                set(row)=={"combination","score"},"INVALID_A_CANDIDATE")
        combo=row["combination"]
        require(type(combo) is list and len(combo)==3 and
                all(type(x) is int and 1<=x<=7 for x in combo) and
                len(set(combo))==3, "INVALID_TRIPLE")
        key=tuple(combo)
        require(key not in group,"DUPLICATE_A_TRIPLE")
        p=row["score"]
        require(type(p) in (int,float) and math.isfinite(p) and p>0,
                "INVALID_A_PROBABILITY")
        mass+=p;group[key]=p
    require(len(group)==210 and set(group)==set(itertools.permutations(
            range(1,8),3)), "A_NOT_COMPLETE_7_RIDER_UNIVERSE")
    require(abs(mass-1.0)<1e-8,"A_PROBABILITY_MASS_INVALID")
    return asof,cutoff,group

def build_ab(original_a, starters, prior_events, *, clock,
             attest_existing_a, attest_video):
    """Make a paired forecast at a real time before the same race cutoff."""
    now=when(clock)
    asof,cutoff,base=validate_existing_a(original_a,attestor=attest_existing_a,
                                          clock=now)
    require(type(starters) is list and len(starters)==7,"SEVEN_RIDERS_REQUIRED")
    rider_by_no={}
    for r in starters:
        require(type(r) is dict and set(r)=={"number","rider_name"},
                "RIDERS_MUST_HAVE_PROVEN_NAME")
        require(type(r["number"]) is int and r["number"] not in rider_by_no,
                "RIDERS_NOT_DISTINCT")
        rider_by_no[r["number"]]=r
    require(sorted(rider_by_no)==list(range(1,8)) and
            len({r["rider_name"] for r in starters})==7,
            "MISMATCHED_RACE_STARTERS")
    evidences=video_events(original_a["race_id"],asof,rider_by_no,
                           prior_events,attest_video)
    require(evidences,"NO_MATCHING_PREVIOUS_RIDER_ACTION")
    raw={}
    for combo,p in base.items():
        first,second,third=combo
        def effect(num,ratio):
            return ratio*evidences.get(num,{}).get("logit_delta",0)
        raw[combo]=math.log(p)+effect(first,1)+effect(second,.35)+effect(third,.2)
    shift=max(raw.values())
    unnorm={combo:math.exp(v-shift) for combo,v in raw.items()}
    z=math.fsum(unnorm.values())
    b={combo:v/z for combo,v in unnorm.items()}
    require(len(b)==210 and math.isclose(math.fsum(b.values()),1,abs_tol=1e-12),
            "UNNORMALIZED_VIDEO_B")
    def dist(items):return [
        {"combination":list(k),"score":float(v)} for k,v in sorted(
            items.items(),key=lambda x:(-x[1],x[0]))]
    result={
        "schema":SCHEMA,"race_id":original_a["race_id"],
        "as_of":original_a["as_of"],
        "cutoff_at":original_a["cutoff_at"],
        "frozen_at":now.isoformat(),
        "snapshot_sha256":original_a["snapshot_sha256"],
        "existing_A_model_id":original_a["model_id"],
        "existing_A_sha256":original_a["prediction_sha256"],
        "source_policy":"OWNER_ATTESTED_RESEARCH_ONLY",
        "retained_rider_positive_events":evidences,
        "video_B_mode":"PRESPECIFIED_WEAK_POSITIVE_EVENT_HEURISTIC",
        "video_B_coefficients_learned":False,
        "independent_holdout_proof":False,
        "calibrated":False,"official_prediction":False,"bets_placed":False,
        "forecast_orig_A_untouched":True,
        "A":{"candidates":dist(base)},
        "B":{"candidates":dist(b)},
        "outcomes_or_odds_used":False,
    }
    result["research_ab_sha256"]=digest(result)
    return result

def freeze_once(path,record):
    """No overwrite, owner-local only, written + readback checksummed."""
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_symlink() or target.exists():raise ABGateError("AB_ALREADY_FROZEN")
    data=(json.dumps(record,ensure_ascii=False,sort_keys=True,
        indent=2,allow_nan=False)+"\n").encode()
    fd=os.open(str(target),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        assert target.read_bytes()==data
        return sha256(data).hexdigest()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
