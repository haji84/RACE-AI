"""Separate official-priced man-shu watch; never rewrite A/B forecasts.

A 100-yen trifecta pays 10,000 yen or more iff its recorded preclose decimal
odds were at least 100x at that observed instant. Final payout can change.
No odds snapshot: no priced man-shu claim. Probabilities are uncalibrated
research scores and score*odds is NOT a validated economic expected value.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit
import itertools
import math
import re

from .boat_ab_shadow import _digest, _time, MODEL_IDS

TICKETS={"-".join(map(str,t)) for t in itertools.permutations(range(1,7),3)}
SHA=re.compile(r"[a-f0-9]{64}\Z")
PAYOUT_THRESHOLD=10000
ODDS_THRESHOLD=Decimal(100)
MAX_ODDS=Decimal(1_000_000)


def _need(condition,reason):
    if not condition:raise ValueError(reason)


def _odds_row(x):
    _need(isinstance(x,dict) and set(x)=={"combination","odds","availability"},
          "official trifecta row identity and price required")
    ticket=x["combination"]
    _need(isinstance(ticket,list) and len(ticket)==3
          and all(type(n) is int and n in range(1,7) for n in ticket)
          and len(set(ticket))==3, "official ticket invalid")
    _need(x["availability"]=="AVAILABLE","only positive official observations allowed")
    value=x["odds"]
    _need(isinstance(value,str) and re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?",value),
          "no odds from a placeholder, estimation or unrelated money field")
    try:result=Decimal(value)
    except InvalidOperation as e:raise ValueError("decimal odds invalid") from e
    _need(Decimal(1)<=result<=MAX_ODDS,"official odds outside exact accepted range")
    return "-".join(map(str,ticket)),result


def _official_identity(s,race_id):
    url=urlsplit(s)
    expected={"rno":[str(int(race_id[-2:]))],"hd":[race_id[:8]],"jcd":[race_id[9:11]]}
    _need(url.scheme=="https" and url.netloc=="www.boatrace.jp"
          and url.path=="/owpc/pc/race/odds3t" and url.fragment==""
          and parse_qs(url.query)==expected,"official 3t odds endpoint/race identity mismatch")


def freeze_priced_tail(original,odds_observation, decision_at):
    """Make distinct 6-core/2-tail *comparison version*, without A/B refit.

    It must be saved independently with GitHub server timing before the
    official closing. No automatic wagers, no claims of guaranteed payouts.
    """
    _need(isinstance(original,dict) and original.get("schema")==
          "RACE_AI_BOAT_LIVE_AB_RESEARCH_V1"
          and original.get("status")=="REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT"
          and original.get("result_used") is False,"verified original A/B research pair required")
    pair=original.get("paired_forecast")
    _need(isinstance(pair,dict) and pair.get("bundle_sha256")==
          _digest({k:v for k,v in pair.items() if k!="bundle_sha256"}),
          "original A/B snapshot integrity mismatch")
    _need(original["race_id"]==pair["race_id"] and original["cutoff_at"]==pair["cutoff_at"],
          "paired source race mismatch")
    cutoff=_time(pair["cutoff_at"])
    observed=_time(decision_at)
    _need(_time(pair["generated_at"])<=observed and
          observed+timedelta(seconds=120)<cutoff,"no late result-aware longshot decision")
    models=pair["models"]
    _need(isinstance(models,list) and len(models)==2 and
          [m.get("model_id") for m in models]==list(MODEL_IDS),
          "original A/B must have same paired source")
    if odds_observation is None:
        return {"schema":"RACE_AI_BOAT_MANSYU_WATCH_V1",
                "race_id":original["race_id"],"as_of":decision_at,
                "state":"NO_PRE_CUTOFF_OFFICIAL_ODDS_NO_MANSYU_CLASSIFICATION",
                "paired_bundle_sha256":pair["bundle_sha256"],
                "observed_100x_candidates":[],
                "core_modified":False,
                "auto_bet":False}
    snapshot=odds_observation
    _need(isinstance(snapshot,dict) and snapshot.get("race_id")==original["race_id"]
          and snapshot.get("kind")=="odds3t"
          and snapshot.get("status")=="AVAILABLE"
          and snapshot.get("eligible_pre_race") is True
          and snapshot.get("closed_at")==original["cutoff_at"]
          and isinstance(snapshot.get("source_sha256"),str)
          and SHA.fullmatch(snapshot["source_sha256"])
          and _time(snapshot["captured_at"])<=observed
          and _time(snapshot["captured_at"])<cutoff,
          "actual official preclose 3t odds evidence required")
    _official_identity(snapshot["source_url"],original["race_id"])
    data=snapshot.get("data")
    _need(isinstance(data,dict) and isinstance(data.get("odds"),list)
          and len(data["odds"])==120,"all 120 official odds required")
    prices={}
    for row in data["odds"]:
        ticket,price=_odds_row(row)
        _need(ticket not in prices,"duplicate official 3t ticket")
        prices[ticket]=price
    _need(set(prices)==TICKETS,"all distinct trifecta odds must be complete")
    comparisons=[]
    for m in models:
        _need(m.get("model_sha256")==_digest({k:v for k,v in m.items() if k!="model_sha256"})
              and m.get("calibrated") is False and m.get("trained") is False,
              "original model cannot be modified for hindsight")
        ranking=m.get("full_120")
        main=m.get("top8")
        _need(isinstance(ranking,list) and len(ranking)==120
              and isinstance(main,list) and len(main)==8
              and main==ranking[:8] and {x["ticket"] for x in ranking}==TICKETS,
              "original ranked 120 and top8 evidence invalid")
        for row in ranking:
            _need(type(row["score"]) in (int,float) and math.isfinite(row["score"]) and
                  0<row["score"]<1,"uncalibrated model distribution malformed")
        watch=[
            {"ticket":x["ticket"],"observed_decimal_odds":str(prices[x["ticket"]]),
             "uncalibrated_model_score":x["score"],
             "score_times_odds_not_a_calibrated_EV":float(prices[x["ticket"]])*x["score"]}
            for x in ranking if prices[x["ticket"]]>=ODDS_THRESHOLD
        ]
        watch.sort(key=lambda x:(-x["score_times_odds_not_a_calibrated_EV"],x["ticket"]))
        # Pre-declared variant: six best core choices plus two *observed*
        # >=100x tickets outside the core; if fewer, keep original top8.
        original_tickets=[x["ticket"] for x in main]
        candidate=[x["ticket"] for x in watch if x["ticket"] not in original_tickets[:6]]
        variant=list(original_tickets[:6])
        for ticket in candidate[:2]:
            if ticket not in variant:variant.append(ticket)
        for ticket in original_tickets:
            if len(variant)==8:break
            if ticket not in variant:variant.append(ticket)
        _need(len(variant)==8 and len(set(variant))==8,
              "variant must not double-count a bet")
        comparisons.append({
            "model_id":m["model_id"],"model_sha256":m["model_sha256"],
            "original_hit8_top8":original_tickets,
            "experimental_6core2priced_tail_top8":variant,
            "observed_100x_tickets_total":len(watch),
            "observed_100x_outside_core_top4":watch[:4],
            "calibrated":False,
            "betting_decision":"NO_BET",
        })
    out={
        "schema":"RACE_AI_BOAT_MANSYU_WATCH_V1",
        "race_id":original["race_id"],"as_of":decision_at,
        "state":"OFFICIAL_PRE_CLOSE_100X_SCREEN_SNAPSHOT",
        "source_sha256":snapshot["source_sha256"],
        "odds_observed_at":snapshot["captured_at"],
        "cutoff_at":original["cutoff_at"],
        "paired_bundle_sha256":pair["bundle_sha256"],
        "models":comparisons,
        "wan_shu_threshold_100_yen_payout":PAYOUT_THRESHOLD,
        "odds_threshold":str(ODDS_THRESHOLD),
        "original_models_untouched":True,
        "future_final_payout_not_guaranteed":True,
        "core_modified":False,"auto_bet":False,
        "research_only":True,
    }
    out["watch_snapshot_sha256"]=_digest(out)
    return out
