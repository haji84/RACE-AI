"""PR64-style baseline versus course/motor shadow, on the SAME pre-cutoff facts.

No official source acquisition or result ingestion. Coefficients are fixed
research hypotheses, NOT trained, calibrated, proven or an auto-upgrade.
Python stdlib only; this does not depend on Vercel or mutate any PR64 asset.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import itertools
import json
import math
import re

BASELINE_ID = "boat-display-rating-PL-reference-v1-UNVALIDATED"
CHALLENGER_ID = "boat-course-motor-shadow-v0.1-UNTRAINED"
MODEL_IDS = (BASELINE_ID, CHALLENGER_ID)
COURSE_LOG_BONUS = (0.20, 0.10, 0.04, -0.04, -0.12, -0.18)
MOTOR_LOG_PER_PERCENT_POINT = 0.003
MIN_SECONDS_BEFORE_CUTOFF = 120
REQUIRED = {"race_id", "cutoff_at", "captured_at", "program_source_sha256",
            "beforeinfo_source_sha256", "boats"}


def _time(v):
    if not isinstance(v, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", v
    ):
        raise ValueError("timezone-aware source timestamp required")
    d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if d.utcoffset() is None:
        raise ValueError("timestamp offset absent")
    return d


def _digest(x):
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _valid(source, generated_at):
    if not isinstance(source, dict) or set(source) != REQUIRED:
        raise ValueError("exact pre-race observation contract required")
    match = re.fullmatch(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])", source["race_id"])
    if match is None:
        raise ValueError("official race id required")
    cutoff = _time(source["cutoff_at"])
    captured = _time(source["captured_at"])
    generated = _time(generated_at)
    event_day = match.group(1)
    if cutoff.strftime("%Y%m%d") != event_day or cutoff.utcoffset().total_seconds() != 9 * 3600:
        raise ValueError("JST cutoff/official date conflict")
    if not captured <= generated < cutoff or (cutoff-generated).total_seconds() <= MIN_SECONDS_BEFORE_CUTOFF:
        raise ValueError("must generate before the safety cutoff margin")
    for k in ("program_source_sha256", "beforeinfo_source_sha256"):
        if not isinstance(source[k], str) or re.fullmatch(r"[0-9a-f]{64}", source[k]) is None:
            raise ValueError("real source SHA absent")
    boats = source["boats"]
    if not isinstance(boats, list) or len(boats) != 6:
        raise ValueError("all six official entrants required")
    order = sorted(boats, key=lambda b:b["lane"] if isinstance(b, dict) and type(b.get("lane")) is int else 100)
    seen = set()
    for b in order:
        if not isinstance(b, dict) or set(b) != {
            "lane", "racer_id", "national_win_rate", "exhibition_time_seconds", "motor_two_place_rate_percent"
        }:
            raise ValueError("exact official feature fields required")
        lane = b["lane"]
        if type(lane) is not int or lane not in range(1,7) or lane in seen:
            raise ValueError("distinct lane identities required")
        seen.add(lane)
        if not isinstance(b["racer_id"], str) or re.fullmatch(r"\d{4}", b["racer_id"]) is None:
            raise ValueError("actual racer registration id required")
        for key, minimum, maximum in (("exhibition_time_seconds",4,12),
                                      ("motor_two_place_rate_percent",0,100)):
            n = b[key]
            if type(n) not in (float,int) or not math.isfinite(n) or not minimum <= n <= maximum:
                raise ValueError("source feature not measured")
        rate = b["national_win_rate"]
        if rate is not None and (type(rate) not in (float,int) or not math.isfinite(rate) or not 0 <= rate <= 10):
            raise ValueError("invalid observed national win rate")
    if len(seen) != 6 or len({r["racer_id"] for r in order}) != 6:
        raise ValueError("duplicate entrants")
    return order


def _rank(strengths):
    total = math.fsum(strengths)
    out = []
    for a,b,c in itertools.permutations(range(1,7),3):
        x,y,z = (strengths[i-1] for i in (a,b,c))
        p = x/total * y/(total-x) * z/(total-x-y)
        out.append({"ticket":[a,b,c], "score":p})
    mass = math.fsum(row["score"] for row in out)
    if len(out)!=120 or not math.isfinite(mass) or not math.isclose(mass,1.0,abs_tol=1e-9):
        raise ValueError("3-way PL distribution invalid")
    out.sort(key=lambda row:(-row["score"],row["ticket"]))
    return out


def build_pair(source, generated_at):
    boats = _valid(source, generated_at)
    avg = math.fsum(b["exhibition_time_seconds"] for b in boats)/6
    motor_avg = math.fsum(b["motor_two_place_rate_percent"] for b in boats)/6
    base = []
    candidate = []
    for b in boats:
        rate = max(b["national_win_rate"] if b["national_win_rate"] is not None else 1.0,0.01)
        raw = math.log(rate) + avg - b["exhibition_time_seconds"]
        base.append(math.exp(max(-20,min(20,raw))))
        # No hindsight or trained coefficient: fixed upfront shadow hypothesis.
        adjust = COURSE_LOG_BONUS[b["lane"]-1] + MOTOR_LOG_PER_PERCENT_POINT * (
            b["motor_two_place_rate_percent"] - motor_avg)
        candidate.append(math.exp(max(-20,min(20,raw+adjust))))
    out = {"schema":"RACE_AI_BOAT_PRE_CUTOFF_AB_PAIR_V1",
           "race_id":source["race_id"], "cutoff_at":source["cutoff_at"],
           "source_captured_at":source["captured_at"],"generated_at":generated_at,
           "source_sha256":_digest(source), "program_source_sha256":source["program_source_sha256"],
           "beforeinfo_source_sha256":source["beforeinfo_source_sha256"],
           "actual_result_at_forecast_time":None,
           "models":[]}
    for model, strengths in zip(MODEL_IDS,(base,candidate)):
        ranked = _rank(strengths)
        record = {"model_id":model, "trained":False,"calibrated":False,
                  "odds_independent":True,"purchase_decision":"NO_BET",
                  "full_120":[{"ticket":"-".join(map(str,r["ticket"])),"score":r["score"]} for r in ranked],
                  "top8":[{"ticket":"-".join(map(str,r["ticket"])),"score":r["score"]} for r in ranked[:8]],
                  "model_score_top8_sum":math.fsum(r["score"] for r in ranked[:8]),
                  "hypothesis":"No bonus; exact PR64-style rating and exhibition-time PL" if model==BASELINE_ID
                    else "Fixed exploratory course log bonuses +0.20,+0.10,+0.04,-0.04,-0.12,-0.18; motor log +0.003 per 2-place-rate percentage point deviation"}
        record["model_sha256"] = _digest(record)
        out["models"].append(record)
    out["bundle_sha256"] = _digest(out)
    return out
