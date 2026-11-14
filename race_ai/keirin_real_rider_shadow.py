"""Pre-cutoff, source-grounded KEIRIN *partial shadow research* for real riders.

Existing PR71 remains the full-input baseline and MUST NOT be passed
fabricated acceleration, stamina or teammate strengths. When the real-world
source only offers scores, S/H/B and anticipated lines, this separate,
UNTRAINED and UNCALIBRATED model can still produce a labelled research
ranking from only measured observations. It is NEVER an official PR71 result,
never a formal Hit@8 A/B trial, and NEVER a recommendation to place bets.

No web calls. Inputs are owner-saved legally supplied source observations.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from itertools import permutations
import json
import math
from pathlib import Path

from .keirin_allowed_delivery import assemble_permitted_pre_race
from .keirin_result_delivery import canonical, utc

SCHEMA = "RACE_AI_KEIRIN_REAL_OBSERVED_SHADOW_V1"
MODEL = "keirin-observed-sparse-shadow-v1"
MIN_MARGIN_SECONDS = 65


class SparseRealForecastError(ValueError):
    pass


def _need(condition, reason):
    if not condition:
        raise SparseRealForecastError(reason)


def _numeric(value, lo, hi, code):
    _need(type(value) in (int,float) and math.isfinite(value) and
          lo <= value <= hi, code)
    return float(value)


def _source_value(verified, packet, key, *, required):
    if key not in verified:
        _need(not required, "MISSING_REAL_OBSERVATION_" + key)
        return None
    row = next((item for item in packet["observations"] if item["key"] == key),
               None)
    _need(row is not None, "VERIFIED_OBSERVATION_NOT_PRESENT")
    return row


def _line_roles(packet, verified, starters):
    line = _source_value(
        verified,packet,"race/line_order_all_riders",required=True
    )["value"]
    _need(type(line) is dict and set(line) == {"lines","solos"},
          "LINEUP_NOT_SOURCE_BOUND")
    positions = {}
    groups = {}
    for data in line["lines"]:
        _need(type(data) is dict and
              set(data)=={"group_id","order"} and
              type(data["group_id"]) is str and
              type(data["order"]) is list,
              "LINEUP_STRUCTURE_INVALID")
        for position, rider in enumerate(data["order"],1):
            _need(rider in starters and rider not in positions,
                  "LINEUP_RIDER_COLLISION")
            positions[rider] = position
            groups[rider] = data["group_id"]
    for rider in line["solos"]:
        _need(rider in starters and rider not in positions,
              "INVALID_SOLO_POSITION")
        positions[rider] = 1
        groups[rider] = None
    _need(set(positions)==set(starters),
          "INCOMPLETE_ANTICIPATED_LINEUP")
    return positions,groups


def _rank_trifectas(scored, linepositions, linegroups):
    """Explicit heuristic, NOT model-calibrated probabilities."""
    strength={}
    for rider in scored:
        n=rider["number"]
        ability=rider["score"]/(100 + rider["score"])
        # These terms are all sourced, measured before cutoff. Missing
        # 3-line-rate fields are OMITTED globally; never impute a zero.
        proxy = (
            1.55*ability
            + 0.24*rider["b_per_start"]
            + 0.12*rider["escape_per_start"]
            + 0.10*rider["makuri_per_start"]
        )
        if "top_three_rate" in rider:
            proxy += 0.30*rider["top_three_rate"]
        if "win_rate" in rider:
            proxy += 0.15*rider["win_rate"]
        strength[n] = math.exp(proxy)
    tickets=[]
    for trio in permutations(sorted(strength),3):
        a,b,c=trio
        first=strength[a]/sum(strength.values())
        second=strength[b]/sum(v for k,v in strength.items() if k!=a)
        third=strength[c]/sum(v for k,v in strength.items() if k not in (a,b))
        # A mild untrained same-line correlation for the anticipated
        # relationship, including the possibility of a second-rider pass.
        def follow(x,y):
            if linegroups[x] is None or linegroups[x]!=linegroups[y]:
                return 1.0
            if linepositions[x]==1 and linepositions[y]==2:
                return 1.14
            if linepositions[x]==2 and linepositions[y]==1:
                return 1.10
            if linepositions[x]<linepositions[y]:
                return 1.06
            return 1.0
        raw_score=first*second*third*follow(a,b)*follow(b,c)
        tickets.append({"triple":[a,b,c],
                        "relative_score":raw_score})
    # Normalize for displaying ranking only. DO NOT call calibrated p(win).
    z=math.fsum(p["relative_score"] for p in tickets)
    _need(z>0 and math.isfinite(z),"INVALID_SHADOW_SCORE")
    for row in tickets:
        row["relative_score"] /= z
    tickets.sort(key=lambda x:(-x["relative_score"],x["triple"]))
    _need(len(tickets)==len(scored)*(len(scored)-1)*(len(scored)-2),
          "UNEXPECTED_TRIFECTA_UNIVERSE")
    return tickets


def forecast_from_real_observations(packet, *, grant_check, issued_at):
    """Run independently of PR71, returning only documented shadow picks.

    Requires real pre-cutoff score & S/H/B evidence for all riders and a
    verified anticipated lineup. All 347/437 feature statuses are checked
    via the existing audit, but missing PR71-required signals stay missing.
    """
    issued = utc(issued_at)
    race = packet.get("race",{}) if type(packet) is dict else {}
    try:
        cutoff=utc(race["official_cutoff_at"])
        as_of=utc(race["as_of"])
    except (TypeError,KeyError,ValueError) as exc:
        raise SparseRealForecastError("RACE_SOURCE_TIME_INVALID") from exc
    _need(as_of <= issued and
          (cutoff-issued).total_seconds()>MIN_MARGIN_SECONDS,
          "NO_PROSPECTIVE_SHADOW_FORECAST_AFTER_MARGIN")
    try:
        assembled=assemble_permitted_pre_race(
            packet, grant_check=grant_check, checked_at=issued_at)
    except (ValueError,KeyError,TypeError) as exc:
        raise SparseRealForecastError("347_AUDIT_REJECTED_REAL_INPUT") from exc
    audit=assembled["audit"]
    _need(len(audit["items"]) == assembled["status"]["checked_count"],
          "INCOMPLETE_RACE_FACTOR_AUDIT")
    verified={row["key"] for row in audit["items"]
              if row["status"]=="verified"}
    competitors=race["starters"]
    starters=[v["number"] for v in competitors]
    _need(len(starters) in (7,9),"UNSUPPORTED_RIDER_COUNT")
    positions,groups=_line_roles(packet,verified,starters)
    score_values={}
    toplist=[]
    winlist=[]
    for rider in competitors:
        n=rider["number"]
        _need("rider/%d/identity_number_and_grade"%n in verified,
              "RIDER_IDENTITY_NOT_OBSERVED")
        s=_source_value(verified,packet,"rider/%d/race_score"%n,required=True)
        _need(s is not None,"MISSING_REAL_RACE_SCORE")
        points=_numeric(s["value"],0,float("inf"),"INVALID_RACE_SCORE")
        starts=_source_value(
            verified,packet,"rider/%d/back_B_count"%n,required=True)
        b=_numeric(starts["value"],0,1e7,"INVALID_BACK_B_COUNT")
        k=starts["sample_n"]
        _need(type(k) is int and 1<=k<=1e7 and
              b<=k,"BACK_B_SAMPLE_INVALID")
        esc=_source_value(
            verified,packet,"rider/%d/style_escape"%n,required=True)
        mak=_source_value(
            verified,packet,"rider/%d/style_makuri"%n,required=True)
        escv=_numeric(esc["value"],0,1,"INVALID_ESCAPE_RATIO")
        makv=_numeric(mak["value"],0,1,"INVALID_MAKURI_RATIO")
        top=_source_value(
            verified,packet,"rider/%d/top_three_rate"%n,required=False)
        win=_source_value(
            verified,packet,"rider/%d/win_rate"%n,required=False)
        if top is not None:
            toplist.append(_numeric(top["value"],0,1,"INVALID_TOP3_RATE"))
        if win is not None:
            winlist.append(_numeric(win["value"],0,1,"INVALID_WIN_RATE"))
        score_values[n]={
            "number":n,"score":points,"b_per_start":b/k,
            "escape_per_start":escv,
            "makuri_per_start":makv,
        }
        if top is not None:
            score_values[n]["top_three_rate"]=float(top["value"])
        if win is not None:
            score_values[n]["win_rate"]=float(win["value"])
    # Optional missingness should not penalize only one competitor.
    for opt,collection in (("top_three_rate",toplist),("win_rate",winlist)):
        if len(collection)!=len(starters):
            for row in score_values.values():
                row.pop(opt,None)
    scores=_rank_trifectas(list(score_values.values()),positions,groups)
    top8=scores[:8]
    source_sha=sha256(canonical(packet)).hexdigest()
    output={
        "schema":SCHEMA,"race_id":race["race_id"],
        "event_date_jst":race["event_date_jst"],
        "model_id":MODEL,
        "model_version":"1.0.0-UNTRAINED-HEURISTIC",
        "input_sha256":source_sha,"generated_at":issued_at,
        "declared_cutoff":race["official_cutoff_at"],
        "starters":sorted(starters),
        "all_factor_statuses_checked":len(audit["items"]),
        "verified_factor_count":assembled["status"]["verified_items"],
        "unknown_or_unusable_factor_count":
            assembled["status"]["unavailable_items"],
        "unverified_critical_keys":assembled["status"]["unverified_critical_keys"],
        "missing_pr71_model_inputs":assembled["status"]["missing_model_inputs"],
        "full_pr71_model_ran":False,
        "all_347_raw_values_collected":False,
        "shadow_model_used_only_observed_data":True,
        "score_transform":"score/(100+score), uncapped/untrained",
        "source_lineup_is_only_an_anticipated_formation":True,
        "used_optional_top_three_all_riders":len(toplist)==len(starters),
        "used_optional_win_rate_all_riders":len(winlist)==len(starters),
        "candidate_count":len(scores),
        "ordered_top8":[r["triple"] for r in top8],
        "relative_scores_untrained_not_hit_probabilities":
            [round(r["relative_score"],8) for r in top8],
        "probabilities_calibrated":False,
        "official_prediction":False,
        "eligible_for_formal_hit_at_8":False,
        "independent_pre_cutoff_timestamp_verified":False,
        "real_purchase_status":"UNKNOWN_NOT_INFERRED",
        "betting_action":"NONE",
    }
    output["research_sha256"]=sha256(canonical(output)).hexdigest()
    return output


def save_private_shadow_once(path, forecast):
    """Immutable private research output, separate from PR71 official store."""
    p=Path(path).expanduser()
    _need(p.is_absolute() and p.parent.is_dir() and not p.parent.is_symlink(),
          "PRIVATE_RESEARCH_PATH_REQUIRED")
    _need(type(forecast) is dict and forecast.get("schema")==SCHEMA,
          "RESEARCH_SHADOW_SCHEMA_INVALID")
    buf=canonical(forecast)
    import os
    try:
        fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        _need(not p.is_symlink() and p.is_file() and
              p.read_bytes()==buf,"SHADOW_ORIGINAL_IMMUTABILITY_CONFLICT")
        return False
    with os.fdopen(fd,"wb") as file:
        file.write(buf)
        file.flush()
        os.fsync(file.fileno())
    return True
