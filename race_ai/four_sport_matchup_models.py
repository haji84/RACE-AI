"""Four-sport conditional-matchup and race-trajectory research models.

These are mathematically distinct from the Plackett-Luce factor baseline:
P(first) * P(second | first, style / teammate) *
P(third | first, second, endurance / tactical interactions).

An additional model mixes FRONT, CHASE and DISRUPTED race trajectories
from ex-ante observed weather and pre-race participant style. Complete
N*(N-1)*(N-2) distributions are enumerated exactly (up to 18 entrants).

UNTRAINED RESEARCH ONLY. This module uses the same strict input validator as
comprehensive_four_sport_models and never reads odds, market signals, race
results, late records, performs IO, writes receipts, or issues picks to bet.
"""
from __future__ import annotations

import itertools
import math

from .comprehensive_four_sport_models import (
    ModelInputError, validate, digest, _utility
)

MODEL_IDS = (
    "multisport-conditional-duel-v1",
    "multisport-race-trajectory-v1",
)
SCENARIOS = ("FRONT", "CHASE", "DISRUPTED")


def _ratio(value, maximum=1.0):
    return min(max(float(value), 0.0), maximum)


def _softmax(scores):
    """Numerically stable, uniform fallback only for *equal valid scores*."""
    if not scores:
        raise ModelInputError("empty conditional candidate group")
    top = max(scores.values())
    exp = {k: math.exp(v-top) for k,v in scores.items()}
    total = math.fsum(exp.values())
    if not math.isfinite(total) or total <= 0:
        raise ModelInputError("invalid conditional distribution")
    return {k: v/total for k,v in exp.items()}


def _race_stress(env):
    e = {k: v["value"] for k,v in env.items()}
    wind = _ratio(e["wind_mps"]/24)
    rain = _ratio(e["rain_mm_h"]/45)
    surface = _ratio(e["surface_wetness"])
    sport_wet = _ratio(max(e.get("wet_track_factor",0),
                           e.get("going_wetness",0),
                           e.get("wave_cm",0)/150))
    return min(1,0.31*wind+0.26*rain+0.22*surface+0.21*sport_wet)


def _trajectory_weights(env):
    stress = _race_stress(env)
    e = {k: v["value"] for k,v in env.items()}
    early_pressure = _ratio(max(e.get("pace_pressure",0),
                                e.get("line_complexity",0),
                                e.get("starting_grid_bias",0)))
    disruptive = .13+.50*stress+.08*early_pressure
    chase = .28+.15*early_pressure-.06*stress
    front = 1-disruptive-chase
    if not 0 <= front <= 1 or not 0 <= chase <= 1 or not 0 <= disruptive <= 1:
        raise ModelInputError("invalid trajectory weights")
    return {"FRONT":front,"CHASE":chase,"DISRUPTED":disruptive}


def _runner_utility(row, *, sport, env, n):
    # The validated numeric observations are normalized 0..1, with documented
    # transforms and as-of source metadata. _utility supplies a baseline
    # from every available supported feature rather than discarding optional
    # pre-race information. Its coefficients are NOT learned or calibrated.
    return math.log(_utility(row,sport=sport,scenario="BASE",
                             conditions=env,n=n))


def _slot_score(row, *, stage, scenario, stress, n, sport):
    f = {key: val["value"] for key,val in row["features"].items()}
    draw = 1.0-(row["draw"]-1)/max(1,n-1)
    style = row["style"]
    base = (0.42 * f["start_reliability"] + 0.18*draw) if stage == 1 else (
           0.27*f["finishing_power"] + 0.18*f["stamina"] +
           0.16*f["tactical_adaptability"] + 0.09*f["consistency"])
    if stage == 3:
        base += 0.23*f["stamina"]+0.12*f["consistency"]
    if scenario == "FRONT":
        base += 0.42*f["start_reliability"] + 0.22*draw
        if style == "front":base += .22
    elif scenario == "CHASE":
        base += 0.36*f["finishing_power"]+0.24*f["tactical_adaptability"]
        if style in ("closer","stalker"):base += .18
    elif scenario == "DISRUPTED":
        base += stress*(.45*f["consistency"]+.55*f["tactical_adaptability"])
        if style == "allround":base += .12
    elif scenario != "BALANCED":
        raise ModelInputError("unknown trajectory")
    if sport == "boat":
        base += (.19 if stage == 1 else .10)*f["start_timing"]
        base += stress*.18*f.get("wave_response",f["course_compatibility"])
    elif sport == "keirin":
        base += (.14 if stage == 1 else .09)*f["attack_success"]
        base += (.16 if stage == 3 else .08)*f["line_coordination"]
    elif sport == "autorace":
        base += (.19 if stage == 1 else .07)*f["handicap_adjustment"]
        base += stress*.30*f["wet_track_fit"]
    elif sport == "horse":
        base += (.18 if stage == 1 else .08)*f.get("early_pace",f["start_reliability"])
        base += (.26 if stage == 3 else .12)*f["closing_sectional"]
        base += stress*.15*f["distance_surface_fit"]
    return base


def _coupling(p, leader, second, *, stage, sport, scenario, stress):
    """Pre-race follower/leader relation, not inferred from final positions."""
    bonus = 0.0
    if sport == "keirin":
        group = p["group_id"]
        if group is not None and group == leader["group_id"]:
            bonus += .48*p["features"]["line_coordination"]["value"]
            if leader["style"]=="front" and p["style"] in ("stalker","closer"):
                bonus += .24
        if second is not None and group is not None and group == second["group_id"]:
            bonus += .17*p["features"]["line_coordination"]["value"]
    if sport == "horse":
        if leader["style"]=="front" and p["style"]=="closer":
            bonus += (.10 if scenario=="FRONT" else .30)*p["features"]["finishing_power"]["value"]
        if leader["style"]=="front" and p["style"]=="front":
            bonus -= .20*(1+stress)
    if sport == "boat":
        # Second/third place does not follow the leader deterministically;
        # tactical start/course adjustment is a deliberately weak prior.
        if p["draw"]>leader["draw"] and scenario=="DISRUPTED":
            bonus += .10*p["features"]["tactical_adaptability"]["value"]
    if sport == "autorace":
        if p["style"]=="closer" and leader["style"]=="front":
            bonus += .16*p["features"]["finishing_power"]["value"]
        if scenario=="DISRUPTED":
            bonus += .15*stress*p["features"]["wet_track_fit"]["value"]
    if stage == 3 and second is not None and p["style"]=="closer":
        bonus += .12*p["features"]["stamina"]["value"]
    return bonus


def _ordered_distribution(participants, env, sport, scenario):
    n = len(participants)
    by_id = {p["number"]:p for p in participants}
    stress = _race_stress(env)
    base = {p["number"]:_runner_utility(p,sport=sport,env=env,n=n)
            for p in participants}
    numbers = sorted(by_id)
    def logits(ids, stage, leader=None, second=None):
        return {j:base[j]+_slot_score(by_id[j],stage=stage,scenario=scenario,
                    stress=stress,n=n,sport=sport) +
                    (_coupling(by_id[j],by_id[leader],by_id[second] if second is not None else None,
                               stage=stage,sport=sport,scenario=scenario,stress=stress)
                     if leader is not None else 0)
                for j in ids}
    first = _softmax(logits(numbers,1))
    probability = {}
    # Exact factorization normalizes to one across all distinct triples.
    for a in numbers:
        remaining = [j for j in numbers if j!=a]
        second = _softmax(logits(remaining,2,leader=a))
        for b in remaining:
            last = [j for j in remaining if j!=b]
            third = _softmax(logits(last,3,leader=a,second=b))
            for c in last:
                probability[(a,b,c)] = first[a]*second[b]*third[c]
    required = n*(n-1)*(n-2)
    mass = math.fsum(probability.values())
    if len(probability)!=required or not math.isclose(mass,1.0,abs_tol=1e-10):
        raise ModelInputError("conditional outcome distribution not normalized")
    return probability


def predict(raw, *, allow_source=None):
    """Produce two independent research models with strict as-of provenance."""
    checked = validate(raw,allow_source=allow_source)
    sport = checked["sport"]
    rows = checked["participants"]
    env = raw["environment"]
    first = _ordered_distribution(rows,env,sport,"BALANCED")
    weight = _trajectory_weights(env)
    branches = {name:_ordered_distribution(rows,env,sport,name)
                for name in SCENARIOS}
    mixture = {combo:math.fsum(weight[name]*branches[name][combo]
                             for name in weight) for combo in first}
    output = {}
    for model,distribution in ((MODEL_IDS[0],first),(MODEL_IDS[1],mixture)):
        mass = math.fsum(distribution.values())
        ranked = sorted(({"combination":list(combo),"score":p/mass}
                         for combo,p in distribution.items()),
                        key=lambda item:(-item["score"],item["combination"]))
        n = len(rows)
        if len(ranked)!=n*(n-1)*(n-2):
            raise ModelInputError("incomplete trifecta permutations")
        record = {
            "model_id":model,
            "model_version":"0.1.0-UNTRAINED",
            "sport":sport,
            "race_id":raw["race"]["race_id"],
            "race_revision":raw["race"]["race_revision"],
            "as_of":raw["race"]["as_of"],
            "cutoff_at":raw["race"]["sales_cutoff_at"],
            "snapshot_sha256":checked["snapshot_sha256"],
            "scope":raw["scope"],
            "odds_independent":True,
            "trained":False,
            "calibrated":False,
            "official_prediction":False,
            "validation_status":"UNVALIDATED_RESEARCH",
            "source_rights_not_self_attested":True,
            "missing_optional_by_participant":checked["missing_optional"],
            "candidate_count":len(ranked),
            "candidates":ranked,
            "ordered_top8":[item["combination"] for item in ranked[:8]],
            "scenario_weights":weight if model==MODEL_IDS[1] else None,
            "explanation":("Conditioned pairwise and race-order interaction "
                           "model; untrained weights and unknown accuracy"),
            "external_pre_cutoff_receipt":None,
            "official_result":None,
            "purchase_decision":"NO_BET",
        }
        record["prediction_sha256"]=digest(record)
        output[model]=record
    return output
