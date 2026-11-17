"""Pre-cutoff rider-ID pair history, line continuity and tactical branch conditioning.

A newly formed line is NOT automatically weak. A pair with no independently
reviewed previous co-rides is UNKNOWN, not "first-ever" or a failed pair.
Only verified pre-cutoff video/position labels can enter the numerator or
denominator. Results/finishing orders cannot stand in for FOLLOW_HELD.

This source-free research adapter adjusts the *relative mass of already
generated six-phase hypotheses*, not original PR71 weights or actual wagers.
Ratios are empirical-shrinkage research proxies, NOT validated probabilities
of success. Independent trusted intake/holdout is still required.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import json
import math
import re

from . import keirin_round_motivation as stage
from . import keirin_round_six_phase_rank as six

EVENT_SCHEMA = "RACE_AI_KEIRIN_PRIOR_LINE_RIDE_LABEL_V1"
CONFIG_SCHEMA = "RACE_AI_KEIRIN_PAIR_SHRINKAGE_RESEARCH_CONFIG_V1"
REPORT_SCHEMA = "RACE_AI_KEIRIN_PRIOR_LINE_COHESION_REPORT_V1"
JOINT_OUTCOMES = ("HELD", "GAPPED", "SWITCHED")
LABEL_OUTCOMES = frozenset((*JOINT_OUTCOMES, "UNKNOWN"))
TACTICS = frozenset(("KAMASHI", "MAKURI", "TSUPPARI", "NIGE", "OTHER"))
ROLES = frozenset(("SECOND_WHEEL", "THIRD_WHEEL"))
ATHLETE = re.compile(r"^[0-9]{4,8}$")
RACE_ID = re.compile(r"^20[0-9]{10}$")


class LineHistoryError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise LineHistoryError(code)


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),
                      ensure_ascii=False,allow_nan=False).encode("utf-8")


def digest(obj):
    return sha256(canonical(obj)).hexdigest()


def _time(value):
    return stage._timestamp(value)


def make_config(*, min_group, min_pair, alpha, pair_shrinkage, max_factor,
                frozen_at):
    """Research hyperparameters MUST be fixed before the evaluated race."""
    need(type(min_group) is int and 6<=min_group<=10000 and
         type(min_pair) is int and 2<=min_pair<=100 and
         type(alpha) in (int,float) and 0<alpha<=20 and
         type(pair_shrinkage) in (int,float) and 1<=pair_shrinkage<=100 and
         type(max_factor) in (int,float) and 1<max_factor<=3,
         "UNREGISTERED_OR_UNSAFE_LINE_SHRINKAGE_CONFIG")
    _time(frozen_at)
    doc={"schema":CONFIG_SCHEMA, "min_group":min_group,
         "min_pair":min_pair,"alpha":alpha,
         "pair_shrinkage":pair_shrinkage,"max_factor":max_factor,
         "frozen_at":frozen_at}
    doc["config_sha256"]=digest(doc)
    return doc


def _check_config(config, at):
    need(type(config) is dict and
         set(config)=={"schema","min_group","min_pair","alpha",
                       "pair_shrinkage","max_factor","frozen_at","config_sha256"} and
         config["schema"]==CONFIG_SCHEMA,
         "LINE_RESEARCH_CONFIG_REQUIRED")
    expected=make_config(
        min_group=config["min_group"],min_pair=config["min_pair"],
        alpha=config["alpha"],pair_shrinkage=config["pair_shrinkage"],
        max_factor=config["max_factor"],frozen_at=config["frozen_at"])
    need(expected==config and _time(config["frozen_at"]) <= at,
         "LINE_CONFIG_MODIFIED_OR_FROZEN_LATE")
    return config


def make_label(**data):
    """A labelled historical ride needs an independently reviewable SHA.

    Caller must have real rider registration IDs and source/frame receipts;
    this builder does not authenticate a video, reviewer or result.
    """
    doc={"schema":EVENT_SCHEMA,**data}
    validate_label(doc, check_digest=False)
    doc["label_sha256"]=digest(doc)
    return doc


def validate_label(row, *, check_digest=True):
    fields={"schema","race_id","event_ended_at","source_published_at",
            "available_at","source_sha256","review_receipt_sha256",
            "leader_athlete_id","follower_athlete_id","role",
            "competition","round_stage","leader_tactic","outcome"}
    need(type(row) is dict and set(row)==fields|(
        {"label_sha256"} if check_digest else set()) and
        row.get("schema")==EVENT_SCHEMA, "LINE_HISTORY_LABEL_SCHEMA")
    need(type(row["race_id"]) is str and
         RACE_ID.fullmatch(row["race_id"]) is not None and
         type(row["leader_athlete_id"]) is str and
         ATHLETE.fullmatch(row["leader_athlete_id"]) is not None and
         type(row["follower_athlete_id"]) is str and
         ATHLETE.fullmatch(row["follower_athlete_id"]) is not None and
         row["leader_athlete_id"]!=row["follower_athlete_id"],
         "LINE_PAIR_MUST_USE_DISTINCT_RIDER_IDS")
    need(row["role"] in ROLES and row["competition"] in stage.CLASS and
         row["round_stage"] in stage.ROUND and
         row["leader_tactic"] in TACTICS and
         row["outcome"] in LABEL_OUTCOMES and
         stage._sha(row["source_sha256"]) and
         stage._sha(row["review_receipt_sha256"]),
         "LINE_VIDEO_LABEL_OR_SOURCE_MISSING")
    event=_time(row["event_ended_at"])
    published=_time(row["source_published_at"])
    available=_time(row["available_at"])
    need(event <= published <= available,
         "LINE_LABEL_AVAILABLE_BEFORE_HISTORICAL_EVENT")
    if check_digest:
        expected=digest({k:v for k,v in row.items()
                         if k!="label_sha256"})
        need(row["label_sha256"]==expected,
             "LINE_LABEL_TAMPERED")
    return row


def _history(history, *, context, verify_label):
    """Admit only earlier races with an externally verified review receipt."""
    as_of=_time(context["as_of"])
    need(type(history) is list and len(history)<=10000,
         "LINE_HISTORY_BATCH_BOUNDS")
    if not history:
        return [],"NO_REVIEWED_HISTORY"
    need(callable(verify_label),"INDEPENDENT_LINE_LABEL_READER_REQUIRED")
    cohort=set()
    accepted=[]
    for row in history:
        validate_label(row)
        # All data must actually have been available before today's as_of.
        need(row["race_id"]!=context["race_id"] and
             _time(row["available_at"])<=as_of,
             "LINE_HISTORY_USES_FUTURE_OR_SAME_RACE")
        key=(row["race_id"],row["leader_athlete_id"],
             row["follower_athlete_id"],row["role"],
             row["leader_tactic"])
        need(key not in cohort, "REUSED_OR_DUPLICATED_LINE_LABEL")
        cohort.add(key)
        try:
            verified=(verify_label(row) is True)
        except Exception:
            verified=False
        need(verified,"LINE_LABEL_RECEIPT_NOT_INDEPENDENTLY_ADMITTED")
        accepted.append(row)
    return sorted(accepted,key=lambda x:(
        x["race_id"],x["leader_athlete_id"],
        x["follower_athlete_id"],x["leader_tactic"],x["role"])),"REVIEWED_HISTORY_ADMITTED"


def _identity(snapshot, athlete_ids_by_car, context):
    riders, groups=six._lines(snapshot,context)
    need(type(athlete_ids_by_car) is dict and
         set(athlete_ids_by_car)=={str(x) for x in riders} and
         all(type(a) is str and ATHLETE.fullmatch(a) is not None
             for a in athlete_ids_by_car.values()) and
         len(set(athlete_ids_by_car.values()))==len(riders),
         "CURRENT_RIDER_IDENTITY_NOT_VERIFIED")
    return groups


def _query(plan, groups, athlete_ids_by_car):
    """One FINAL explicit follow outcome per rider pair, not per frame."""
    last={}
    # simulate() in forecast_shadow separately validates event semantics.
    for event in plan["events"]:
        act=event["action"]
        if not event["success"] or act not in (
            "FOLLOW_HELD","FOLLOW_GAPPED","SWITCH_WHEEL"):
            continue
        car=event["actor"]
        found=[g for g in groups if car in g]
        need(len(found)==1,"LINE_HISTORY_ACTOR_NOT_IN_LINE")
        group=found[0]
        if car==group[0] or group.index(car) not in (1,2):
            continue
        leader=group[0]
        tactic="OTHER"
        for earlier in plan["events"]:
            if (six.PHASES.index(earlier["phase"])<=
                six.PHASES.index(event["phase"]) and
                earlier["actor"]==leader and
                earlier["action"] in TACTICS and
                earlier["success"]):
                tactic=earlier["action"]
        outcome={"FOLLOW_HELD":"HELD","FOLLOW_GAPPED":"GAPPED",
                 "SWITCH_WHEEL":"SWITCHED"}[act]
        key=(athlete_ids_by_car[str(leader)],
             athlete_ids_by_car[str(car)],
             "SECOND_WHEEL" if group.index(car)==1 else "THIRD_WHEEL",
             tactic)
        last[key]=outcome
    return last


def condition_stage_priors(*, context, snapshot, plans, priors, history,
                           athlete_ids_by_car, config,
                           independently_verify_label,
                           independently_verify_identity,
                           independently_verify_original,
                           computed_at):
    """Condition existing stage objective masses by reviewed pair continuity.

    For each role/tactic/context, compute a smoothed historical group base
    and pair estimate. Reweight by pair/group likelihood RATIO, not by pair
    rate outright, so missing pair samples never impose a penalty.
    Multiple pair labels in one scenario use geometric-mean ratios, not
    unjustified independent multiplication of correlated teammates.

    Each candidate branch is already separately validated by six.simulate.
    """
    stage.checked_context(context)
    at=_time(context["as_of"])
    need(_time(computed_at)<=at,"LINE_FORECAST_COMPUTED_AFTER_CUTOFF")
    _check_config(config,at)
    need(callable(independently_verify_identity) and
         independently_verify_identity(athlete_ids_by_car) is True,
         "CURRENT_LINE_ATHLETE_IDENTITIES_UNVERIFIED")
    need(callable(independently_verify_original) and
         independently_verify_original(snapshot) is True,
         "CURRENT_FROZEN_ORIGINAL_UNVERIFIED")
    groups=_identity(snapshot,athlete_ids_by_car,context)
    old=six._weights(priors,goal=six.objective(context),
                     scenario_ids=[p["scenario_id"] for p in plans],
                     context=context,snapshot=snapshot)
    all_rows,state=_history(history,context=context,
                             verify_label=independently_verify_label)
    # Future prediction uses only historical labels from matching class/round
    # and exact leader tactic. Unknown labels are excluded from denominators.
    pool=defaultdict(Counter)
    pair=defaultdict(Counter)
    ride_ids=defaultdict(set)
    for row in all_rows:
        comp,round_stage,role,tactic=(row["competition"],row["round_stage"],
                                      row["role"],row["leader_tactic"])
        gkey=(comp,round_stage,role,tactic)
        pkey=(row["leader_athlete_id"],row["follower_athlete_id"])+gkey
        ride_ids[pkey].add(row["race_id"])
        if row["outcome"] in JOINT_OUTCOMES:
            pool[gkey][row["outcome"]]+=1
            pair[pkey][row["outcome"]]+=1
    masses={}; lines_used=0; limited=0; unknowns=0; queried=0
    detail={}
    for plan in plans:
        # Protect against malformed future action paths before weighting.
        six.simulate(snapshot,context,plan)
        factors=[]; p_summary=[]
        for key,outcome in _query(plan,groups,athlete_ids_by_car).items():
            queried+=1
            leader,follower,role,tactic=key
            gkey=(context["competition"],context["round_stage"],role,tactic)
            pkey=(leader,follower)+gkey
            n_group=sum(pool[gkey].values())
            n_pair=sum(pair[pkey].values())
            rides=len(ride_ids[pkey])
            if n_group < config["min_group"]:
                unknowns+=1
                p_summary.append({"state":"GROUP_HISTORY_INSUFFICIENT",
                                  "verified_pair_races":rides,
                                  "labelled_pair_samples":n_pair})
                continue
            if n_pair < config["min_pair"]:
                limited+=1
                p_summary.append({"state":"PAIR_EVIDENCE_INSUFFICIENT_NO_PENALTY",
                                  "verified_pair_races":rides,
                                  "labelled_pair_samples":n_pair})
                continue
            alpha=config["alpha"]
            p_group=(pool[gkey][outcome]+alpha)/(
                n_group+len(JOINT_OUTCOMES)*alpha)
            shr=config["pair_shrinkage"]
            p_pair=(pair[pkey][outcome]+shr*p_group)/(n_pair+shr)
            ratio=p_pair/p_group
            factor=max(1/config["max_factor"],
                       min(config["max_factor"],ratio))
            factors.append(factor)
            lines_used+=1
            p_summary.append({"state":"RESEARCH_SHRUNK_CONDITIONAL_RATIO",
                              "verified_pair_races":rides,
                              "labelled_pair_samples":n_pair,
                              "group_sample_count":n_group,
                              "group_rate":p_group,
                              "shrunk_pair_rate":p_pair,
                              "bounded_ratio":factor,
                              "calibrated":False})
        score=(math.exp(math.fsum(math.log(v) for v in factors)/len(factors))
               if factors else 1.0)
        masses[plan["scenario_id"]]=old[plan["scenario_id"]]*score
        detail[plan["scenario_id"]]={
            "independent_pair_ratios_not_assumed":True,
            "pair_condition_count":len(factors),
            "pair_evidence":p_summary,
        }
    denominator=math.fsum(masses.values())
    need(denominator>0 and math.isfinite(denominator),
         "LINE_CONDITIONED_MASSES_NOT_POSITIVE")
    adjusted={k:v/denominator for k,v in masses.items()}
    # Preserve other objective contexts untouched, but the current goal's
    # research branch masses are updated for the same cohort and same as_of.
    new_priors=dict(priors)
    new_priors["scenario_masses_by_objective"]={
        k:dict(v) for k,v in priors["scenario_masses_by_objective"].items()}
    new_priors["scenario_masses_by_objective"][six.objective(context)]=adjusted
    new_priors["source_sha256"]=digest({
        "parent_priors_sha256":six.digest(priors),
        "line_history_sha256":digest(all_rows),
        "line_config_sha256":config["config_sha256"],
        "current_rider_id_mapping_sha256":digest(athlete_ids_by_car),
        "computed_at":computed_at,
    })
    new_priors["observed_at"]=computed_at
    counts={
        "schema":REPORT_SCHEMA,
        "race_id":context["race_id"],"history_state":state,
        "historical_reviewed_rows":len(all_rows),
        "queried_rider_pairs":queried,
        "conditioned_pair_events":lines_used,
        "insufficient_pair_events":limited,
        "missing_group_events":unknowns,
        "line_conditioning_applied":lines_used>0,
        "never_classifies_zero_history_as_first_ride":True,
        "untrained_and_uncalibrated":True,
        "not_an_independent_human_review":True,
        "private_history_sha256":digest(all_rows),
        "config_sha256":config["config_sha256"],
        "context_sha256":stage.digest(context),
        "prior_model_sha256":six.digest(priors),
        "adjusted_model_sha256":six.digest(new_priors),
        "per_scenario":detail,
    }
    return new_priors, counts


def forecast_with_pair_evidence(*, context, snapshot, plans, priors,
                                history, athlete_ids_by_car, config,
                                independently_verify_label,
                                independently_verify_identity,
                                independently_verify_original,
                                computed_at):
    """Stage-only vs stage+line forecast without rewriting either parent."""
    need(callable(independently_verify_original) and
         independently_verify_original(snapshot) is True,
         "CURRENT_FROZEN_ORIGINAL_UNVERIFIED")
    raw=six.forecast_shadow(
        context=context,snapshot=snapshot,plans=plans,priors=priors,
        independently_verified_parent=independently_verify_original)
    if raw.get("state")!="STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY":
        return {"schema":REPORT_SCHEMA,"race_id":context["race_id"],
                "state":"HOLD_STAGE_SIX_PHASE_UNAVAILABLE",
                "stage_only":raw,"stage_plus_line":None,
                "actual_model_promoted":False}
    applied,report=condition_stage_priors(
        context=context,snapshot=snapshot,plans=plans,priors=priors,
        history=history,athlete_ids_by_car=athlete_ids_by_car,config=config,
        independently_verify_label=independently_verify_label,
        independently_verify_identity=independently_verify_identity,
        independently_verify_original=independently_verify_original,
        computed_at=computed_at)
    follow=six.forecast_shadow(
        context=context,snapshot=snapshot,plans=plans,priors=applied,
        independently_verified_parent=independently_verify_original)
    return {
        "schema":REPORT_SCHEMA,"race_id":context["race_id"],
        "state":"RESEARCH_STAGE_PLUS_LINE" if report["line_conditioning_applied"]
                else "HOLD_NO_ADMITTED_PAIR_CONDITIONING",
        "stage_only":raw,"stage_plus_line":follow,
        "conditioning":report,
        "stage_original_rank1":raw["ranked_top12"][0]["cars"],
        "line_research_rank1":follow["ranked_top12"][0]["cars"],
        "line_conditioning_changed_rank1":(
            raw["ranked_top12"][0]["cars"]!=follow["ranked_top12"][0]["cars"]),
        "real_race_pair_training_proven":False,
        "actual_model_promoted":False,
        "formal_accuracy_improvement_proven":False,
    }
