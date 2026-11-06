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
    ModelInputError, validate, digest, _utility, HISTORICAL_HORSE_FEATURES, SCHEMA_SPARSE
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
    wind = _ratio(e.get("wind_mps",0)/24)
    rain = _ratio(e.get("rain_mm_h",0)/45)
    surface = _ratio(e.get("surface_wetness",0))
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


def _runner_utility(row, *, sport, env, n, parameters=None):
    # The validated numeric observations are normalized 0..1, with documented
    # transforms and as-of source metadata. _utility supplies a baseline
    # from every available supported feature rather than discarding optional
    # pre-race information. Its coefficients are NOT learned or calibrated.
    return math.log(_utility(row,sport=sport,scenario="BASE",
                             conditions=env,n=n,parameters=parameters))


def _slot_score(row, *, stage, scenario, stress, n, sport, parameters=None):
    f = {key: val["value"] for key,val in row["features"].items()}
    draw = 1.0-(row["draw"]-1)/max(1,(6 if sport=="boat" else n)-1)
    style = row["style"]
    parameters = parameters or {}
    base = (parameters.get("slot.first_start",.42) * f.get("start_reliability",0) + parameters.get("slot.first_draw",.18)*draw) if stage == 1 else (
           parameters.get("slot.later_finish",.27)*f.get("finishing_power",0) + parameters.get("slot.later_stamina",.18)*f.get("stamina",0) +
           0.16*f.get("tactical_adaptability",0) + 0.09*f.get("consistency",0))
    if stage == 3:
        base += parameters.get("slot.third_stamina",.23)*f.get("stamina",0)+0.12*f.get("consistency",0)
    if scenario == "FRONT":
        base += parameters.get("trajectory.front_start",.42)*f.get("start_reliability",0) + 0.22*draw
        if style == "front":base += .22
    elif scenario == "CHASE":
        base += parameters.get("trajectory.chase_finish",.36)*f.get("finishing_power",0)+0.24*f.get("tactical_adaptability",0)
        if style in ("closer","stalker"):base += .18
    elif scenario == "DISRUPTED":
        base += stress*(.45*f.get("consistency",0)+parameters.get("trajectory.disrupted_tactics",.55)*f.get("tactical_adaptability",0))
        if style == "allround":base += .12
    elif scenario != "BALANCED":
        raise ModelInputError("unknown trajectory")
    if sport == "boat":
        base += (.19 if stage == 1 else .10)*f.get("start_timing",0)
        base += stress*.18*f.get("wave_response",f.get("course_compatibility",0))
    elif sport == "keirin":
        base += (.14 if stage == 1 else .09)*f.get("attack_success",0)
        base += (.16 if stage == 3 else .08)*f.get("line_coordination",0)
    elif sport == "autorace":
        base += (.19 if stage == 1 else .07)*f.get("handicap_adjustment",0)
        base += stress*.30*f.get("wet_track_fit",0)
    elif sport == "horse":
        base += (.18 if stage == 1 else .08)*f.get("early_pace",f.get("start_reliability",0))
        base += (.26 if stage == 3 else .12)*f.get("closing_sectional",0)
        base += stress*.15*f.get("distance_surface_fit",0)
        # Experimental research win-pattern prior, stronger for first place.
        if stage == 1:
            base += .10*sum(f[k]-.5 for k in HISTORICAL_HORSE_FEATURES if k in f)
    return base


def _coupling(p, leader, second, *, stage, sport, scenario, stress, parameters=None):
    """Pre-race follower/leader relation, not inferred from final positions."""
    bonus = 0.0
    parameters = parameters or {}
    if sport == "keirin":
        group = p["group_id"]
        if group is not None and group == leader["group_id"]:
            bonus += parameters.get("coupling.line_leader",.48)*p["features"].get("line_coordination",{}).get("value",0)
            if leader["style"]=="front" and p["style"] in ("stalker","closer"):
                bonus += .24
        if second is not None and group is not None and group == second["group_id"]:
            bonus += parameters.get("coupling.line_second",.17)*p["features"].get("line_coordination",{}).get("value",0)
    if sport == "horse":
        if leader["style"]=="front" and p["style"]=="closer":
            bonus += (.10 if scenario=="FRONT" else .30)*p["features"].get("finishing_power",{}).get("value",0)
        if leader["style"]=="front" and p["style"]=="front":
            bonus += parameters.get("coupling.horse_front_competition",-.20)*(1+stress)
    if sport == "boat":
        # Second/third place does not follow the leader deterministically;
        # tactical start/course adjustment is a deliberately weak prior.
        if p["draw"]>leader["draw"] and scenario=="DISRUPTED":
            bonus += .10*p["features"].get("tactical_adaptability",{}).get("value",0)
    if sport == "autorace":
        if p["style"]=="closer" and leader["style"]=="front":
            bonus += parameters.get("coupling.autorace_closer",.16)*p["features"].get("finishing_power",{}).get("value",0)
        if scenario=="DISRUPTED":
            bonus += .15*stress*p["features"].get("wet_track_fit",{}).get("value",0)
    if stage == 3 and second is not None and p["style"]=="closer":
        bonus += parameters.get("coupling.third_closer_stamina",.12)*p["features"].get("stamina",{}).get("value",0)
    return bonus


def _ordered_distribution(participants, env, sport, scenario, parameters=None):
    n = len(participants)
    by_id = {p["number"]:p for p in participants}
    stress = _race_stress(env)
    base = {p["number"]:_runner_utility(p,sport=sport,env=env,n=n,parameters=parameters)
            for p in participants}
    numbers = sorted(by_id)
    def logits(ids, stage, leader=None, second=None):
        return {j:base[j]+_slot_score(by_id[j],stage=stage,scenario=scenario,
                    stress=stress,n=n,sport=sport,parameters=parameters) +
                    (_coupling(by_id[j],by_id[leader],by_id[second] if second is not None else None,
                               stage=stage,sport=sport,scenario=scenario,stress=stress,parameters=parameters)
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


def predict(raw, *, allow_source=None, research_parameters=None):
    """Produce two independent research models with strict as-of provenance."""
    checked = validate(raw,allow_source=allow_source)
    sport = checked["sport"]
    rows = checked["participants"]
    env = raw["environment"]
    from .existing_common_parameter_adapters import _resolve_model_sets, _stamp
    parameters = _resolve_model_sets(research_parameters,sport,MODEL_IDS)
    first = _ordered_distribution(rows,env,sport,"BALANCED",parameters.get(MODEL_IDS[0]))
    weight = _trajectory_weights(env)
    branches = {name:_ordered_distribution(rows,env,sport,name,parameters.get(MODEL_IDS[1]))
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
        if raw["schema"]==SCHEMA_SPARSE:
            record.update(model_version="0.2.0-SPARSE-UNTRAINED",input_schema=SCHEMA_SPARSE,
                          missing_features_by_participant={p["number"]:p["missing"] for p in rows},
                          missing_environment=raw["environment_missing"],
                          missing_input_semantics="Unavailable terms omitted; no observed values imputed",
                          unknown_publication_time_allowed=True)
        _stamp(record,parameters.get(model))
        record["prediction_sha256"]=digest(record)
        output[model]=record
    return output
