"""Stage-conditioned six-phase tactical branches -> ranked 3-ren-tan RESEARCH.

Owner request: the competition class (CHALLENGE/A1_A2/S/GIRLS) and the round
(PRELIMINARY/SEMI_FINAL/FINAL etc.) must affect the simulated tactical paths
and final ranking, not merely a text explanation.

This is an offline SHA-bound shadow adapter to the existing PR71/PR291
pipeline, not a predictor trained on real races, a model replacement, a
provider GET, or a license/official-program certification. Each conditional
branch has pre-race source-backed numerical mass; NO fixed class odds,
post-race adaptation, or automatically "confident" 3-ren-tan.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re

from . import keirin_round_motivation as round_context
from .keirin_phase_overlay import STAGES, KNOWN_PR71

SCHEMA = "RACE_AI_KEIRIN_ROUND_SIX_PHASE_SHADOW_V1"
# Existing owner-generated forecasts can be a separate research parent.
# This is NOT another PR71 model and never validates a PR71 four-model suite.
CURRENT_GENERATED_SOURCE = "existing-generated-keirin-research-v3"
ADMITTED_RESEARCH_ORIGINALS = KNOWN_PR71 | {CURRENT_GENERATED_SOURCE}
WEIGHTS_SCHEMA = "RACE_AI_KEIRIN_PRE_CUTOFF_STAGE_BRANCH_MASS_V1"
PHASES = tuple(stage for stage, _ in STAGES)
ACTIONS = frozenset(("KAMASHI", "YIELD", "TSUPPARI", "FOLLOW_HELD",
                     "FOLLOW_GAPPED", "MAKURI", "THIRD_LINE_SURGE",
                     "SASHI", "SWITCH_WHEEL", "PACE_FADE", "WAIT"))
RESEARCH = "UNTRAINED_STAGE_CONDITIONAL_RESEARCH"
KEY = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class TacticalRoundError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise TacticalRoundError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _clock(value):
    return round_context._timestamp(value)


def _rider(car):
    return type(car) is int and 1 <= car <= 9


def _pair(ticket, riders):
    return (type(ticket) is list and len(ticket) == 3 and
            all(_rider(n) and n in riders for n in ticket) and
            len(set(ticket)) == 3)


def _lines(snapshot, ctx):
    require(type(snapshot) is dict and set(snapshot) == {
        "race_id", "input_sha256", "baseline_model_id",
        "baseline_prediction_sha256", "as_of", "official_cutoff_at",
        "starting_order", "line_groups", "baseline_top12"
    }, "ORIGINAL_SNAPSHOT_FIELDS_INVALID")
    require(snapshot["race_id"] == ctx["race_id"] and
            snapshot["input_sha256"] == ctx["parent_input_sha256"] and
            snapshot["baseline_model_id"] in ADMITTED_RESEARCH_ORIGINALS and
            round_context._sha(snapshot["baseline_prediction_sha256"]) and
            snapshot["as_of"] == ctx["as_of"] and
            snapshot["official_cutoff_at"] == ctx["official_cutoff_at"],
            "ORIGINAL_OR_TIME_NOT_BOUND")
    order = snapshot["starting_order"]
    require(type(order) is list and len(order) == ctx["race_size"] and
            all(_rider(x) for x in order) and len(set(order)) == len(order),
            "STARTING_ORDER_INVALID")
    groups = snapshot["line_groups"]
    require(type(groups) is list and 1 <= len(groups) <= 9 and
            all(type(g) is list and g and all(_rider(x) for x in g)
                for g in groups) and
            set(sum(groups, [])) == set(order) and
            len(sum(groups, [])) == len(order),
            "LINE_MEMBERSHIP_NOT_EXACT")
    if ctx["competition"] == "GIRLS":
        # Do not invent conventional permanent KEIRIN men's lines for girls.
        require(all(len(g) == 1 for g in groups),
                "GIRLS_FIXED_TEAM_LINE_NOT_SUPPORTED")
    baseline = snapshot["baseline_top12"]
    require(type(baseline) is list and 1 <= len(baseline) <= 12 and
            all(_pair(t, set(order)) for t in baseline) and
            len({tuple(t) for t in baseline}) == len(baseline),
            "BASELINE_TICKETS_INVALID")
    return order, groups


def objective(ctx):
    """Derive the *strategic evaluation objective* from stage + real rule.

    Direct qualification is a different objective from a title. It is NOT
    proof that any specific rider will attack, wait, or sacrifice a wheel.
    """
    plan = round_context.conditions(ctx)
    kind = plan["advancement_kind"]
    if ctx["round_stage"] == "FINAL":
        return "TITLE_WIN"
    if kind in ("DIRECT_RANK", "RANK_AND_CROSS_RACE"):
        return ("ALL_ADVANCE" if plan["guaranteed_rank_through"] ==
                ctx["race_size"] else "DIRECT_QUALIFY")
    if kind == "NO_ADVANCEMENT":
        return "PLACEMENT_POINTS"
    return None  # UNKNOWN or points-rule lacking current standings => HOLD.


def _validate_events(plan, riders, groups, at, input_sha):
    require(type(plan) is dict and set(plan) == {
        "scenario_id", "observed_at", "input_sha256", "events"
    } and type(plan["scenario_id"]) is str and
            KEY.fullmatch(plan["scenario_id"]) is not None and
            plan["input_sha256"] == input_sha and
            _clock(plan["observed_at"]) <= at,
            "TACTICAL_BRANCH_SOURCE_OR_TIME_MISMATCH")
    events = plan["events"]
    require(type(events) is list and 1 <= len(events) <= 25,
            "TACTICAL_EVENT_LIST_REQUIRED")
    order = -1
    for e in events:
        require(type(e) is dict and set(e) == {
            "phase", "action", "actor", "target", "success"
        } and e["phase"] in PHASES[1:] and e["action"] in ACTIONS and
                _rider(e["actor"]) and e["actor"] in riders and
                type(e["success"]) is bool,
                "TACTICAL_EVENT_FIELDS_INVALID")
        i = PHASES.index(e["phase"])
        require(i >= order, "TACTICAL_EVENTS_NOT_CHRONOLOGICAL")
        order = i
        if e["action"] in ("WAIT", "PACE_FADE"):
            require(e["target"] is None, "TACTICAL_EVENT_TARGET_MUST_BE_NONE")
        else:
            require(_rider(e["target"]) and
                    e["target"] in riders and e["target"] != e["actor"],
                    "TACTICAL_EVENT_TARGET_INVALID")
        if e["action"] in ("FOLLOW_HELD", "FOLLOW_GAPPED", "SASHI"):
            require(any(e["actor"] in g and e["target"] in g for g in groups),
                    "TACTICAL_WHEEL_NOT_ON_ORIGINAL_LINE")
        if e["action"] == "SWITCH_WHEEL":
            require(not any(e["actor"] in g and e["target"] in g for g in groups),
                    "SWITCH_WHEEL_MUST_CROSS_LINES")
        if e["action"] == "THIRD_LINE_SURGE":
            require(len(groups) >= 3 and e["actor"] in groups[2],
                    "THIRD_LINE_ACTOR_REQUIRED")

    # The *response* to a kamashi is another rider's explicit joint
    # decision. Cannot independently count successful attack+tsuppari.
    for attack in (x for x in events if x["action"] == "KAMASHI"):
        responses = [x for x in events if
                     x["phase"] == attack["phase"] and
                     x["actor"] == attack["target"] and
                     x["target"] == attack["actor"] and
                     x["action"] in ("TSUPPARI", "YIELD")]
        require(len(responses) == 1, "KAMASHI_REACTION_UNSPECIFIED")
        response = responses[0]
        require(response["success"] and
                response["action"] ==
                ("YIELD" if attack["success"] else "TSUPPARI"),
                "KAMASHI_AND_DEFENSE_CAUSALLY_INCONSISTENT")
    return events


def _move_before(order, actor, target):
    require(order.index(actor) > order.index(target),
            "ATTACK_TARGET_NOT_AHEAD")
    order.remove(actor)
    order.insert(order.index(target), actor)


def _move_after(order, actor, target, gap=0):
    order.remove(actor)
    order.insert(min(len(order),order.index(target)+1+gap),actor)


def _apply(order, event):
    if not event["success"] or event["action"] in ("WAIT","TSUPPARI"):
        return
    action, actor, target = event["action"],event["actor"],event["target"]
    if action in ("KAMASHI","MAKURI","THIRD_LINE_SURGE","SASHI"):
        _move_before(order,actor,target)
    elif action in ("FOLLOW_HELD","SWITCH_WHEEL","YIELD"):
        _move_after(order,actor,target)
    elif action == "FOLLOW_GAPPED":
        _move_after(order,actor,target,gap=1)
    elif action == "PACE_FADE":
        index=order.index(actor)
        if index+1<len(order):
            other=order[index+1]
            order[index],order[index+1]=other,actor


def _phase_view(order,groups,phase,actions):
    # A phase snapshot is a projected *hypothesis*, never video truth.
    connected=[]
    for group in groups:
        locations=sorted(order.index(x) for x in group)
        connected.append(locations == list(range(locations[0],
                                               locations[-1]+1)))
    return {
        "phase":phase,"projected_order":list(order),
        "projected_top3":order[:3],
        "front_car":order[0],
        "initial_line_still_contiguous":connected,
        "tactical_events":[dict(e) for e in actions],
        "observed_from_video":False,
    }


def simulate(snapshot, ctx, plan):
    """Generate six phase states from pre-cutoff scenario events and reactions."""
    initial, groups = _lines(snapshot,ctx)
    events=_validate_events(plan,set(initial),groups,_clock(ctx["as_of"]),
                             snapshot["input_sha256"])
    order=list(initial)
    views=[_phase_view(order,groups,PHASES[0],[])]
    for stage in PHASES[1:]:
        step=[e for e in events if e["phase"] == stage]
        for e in step:
            _apply(order,e)
        require(len(order)==len(initial) and set(order)==set(initial) and
                len(set(order))==len(order),
                "TACTICAL_TRANSITION_LOST_OR_DUPLICATED_RIDER")
        views.append(_phase_view(order,groups,stage,step))
    require(len(views)==6 and tuple(x["phase"] for x in views)==PHASES,
            "SIX_PHASE_CHAIN_INCOMPLETE")
    return views


def _weights(src, *, goal, scenario_ids, context, snapshot):
    require(type(src) is dict and set(src) == {
        "schema", "race_id", "source_sha256", "observed_at",
        "input_sha256", "scenario_masses_by_objective",
        "independent_calibration_verified"
    } and src["schema"] == WEIGHTS_SCHEMA and
            src["race_id"] == context["race_id"] and
            round_context._sha(src["source_sha256"]) and
            src["input_sha256"] == snapshot["input_sha256"] and
            src["independent_calibration_verified"] is False and
            _clock(src["observed_at"]) <= _clock(context["as_of"]),
            "TACTICAL_STAGE_PRIORS_SOURCE_INVALID")
    weights=src["scenario_masses_by_objective"]
    require(type(weights) is dict and
            set(weights) <= {"TITLE_WIN","DIRECT_QUALIFY",
                             "ALL_ADVANCE","PLACEMENT_POINTS"} and
            goal in weights and type(weights[goal]) is dict and
            set(weights[goal]) == set(scenario_ids),
            "TACTICAL_STAGE_PRIORS_OBJECTIVE_OR_SCENARIO_MISSING")
    for objective,table in weights.items():
        require(type(table) is dict and set(table)==set(scenario_ids) and
                all(type(v) in (int,float) and math.isfinite(v) and
                    0<=v<=1 for v in table.values()) and
                abs(math.fsum(table.values())-1)<=1e-8,
                "TACTICAL_STAGE_PRIORS_NOT_NORMALIZED")
    return weights[goal]


def forecast_shadow(*, context, snapshot, plans, priors,
                    independently_verified_parent=None):
    """An actual six-phase/shadow 3-ren-tan ranking, NOT a formal PR71 forecast.\n\n    Parent may be an independently verified owner-generated prediction instead\n    of a still-unavailable four-model suite. Both remain research-only.

    Existing before-cutoff original must be checked by a trusted caller;
    callback-based proof cannot independently certify official data by itself.
    Missing future-race admission or stage priors => explicit HOLD.
    """
    round_context.checked_context(context)
    goal=objective(context)
    if goal is None:
        return {"schema":SCHEMA,"race_id":context["race_id"],
                "state":"HOLD_ADVANCEMENT_OR_POINTS_UNVERIFIED",
                "ranked_top12":[], "six_phase_branches":[],
                "formal_model_promoted":False}
    require(callable(independently_verified_parent) and
            independently_verified_parent(snapshot) is True,
            "INDEPENDENT_PR71_ORIGINAL_NOT_ADMITTED")
    initial, groups = _lines(snapshot,context)
    require(type(plans) is list and 2<=len(plans)<=64 and
            all(type(x) is dict and type(x.get("scenario_id")) is str
                for x in plans) and
            len({x["scenario_id"] for x in plans})==len(plans),
            "MULTIPLE_DISTINCT_TACTICAL_BRANCHES_REQUIRED")
    scenario_ids=[plan["scenario_id"] for plan in plans]
    weights=_weights(priors,goal=goal,scenario_ids=scenario_ids,
                     context=context,snapshot=snapshot)
    scenarios=[]
    totals=defaultdict(float)
    for plan in plans:
        stages=simulate(snapshot,context,plan)
        ticket=tuple(stages[-1]["projected_top3"])
        mass=weights[plan["scenario_id"]]
        totals[ticket]+=mass
        scenarios.append({
            "scenario_id":plan["scenario_id"],
            "projected_3ren_tan":list(ticket),
            "research_relative_branch_mass":mass,
            "six_phases":stages,
            "tactical_events_sha256":digest(plan),
            "official_observation_verified":False,
        })
    rank=sorted(totals.items(),key=lambda kv:(-kv[1],kv[0]))
    tickets=[{"rank":i,"cars":list(ticket),
              "research_relative_mass":score}
             for i,(ticket,score) in enumerate(rank[:12],1)]
    base=snapshot["baseline_top12"]
    return {
        "schema":SCHEMA,"state":"STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY",
        "race_id":context["race_id"],
        "competition":context["competition"],
        "round_stage":context["round_stage"],
        "advancement_objective":goal,
        "context_sha256":round_context.digest(context),
        "pre_race_input_sha256":snapshot["input_sha256"],
        "parent_prediction_sha256":snapshot["baseline_prediction_sha256"],
        "original_rank1":base[0],
        "ranked_top12":tickets,
        "research_rank1_differs_from_original":bool(tickets and tickets[0]["cars"]!=base[0]),
        "six_phase_branches":scenarios,
        "scenario_priors_sha256":digest(priors),
        "as_of":context["as_of"],
        "official_cutoff_at":context["official_cutoff_at"],
        "pr71_original_replaced":False,
        "official_source_and_program_independently_authenticated":False,
        "empirical_accuracy_verified":False,
        "calibrated_win_probability":None,
        "formal_model_promoted":False,
        "real_forecast_count_claimed":0,
    }



def snapshot_from_existing_pr71(saved, *, context, line_receipt,
                                independently_verify_suite=None,
                                independently_verify_lines=None):
    """Adapt immutable PR71 full-rank model candidates without rebuilding them.

    Starting order/line hypotheses are separately timed pre-race input, NOT
    measured initial rider locations. Independent callbacks in a trusted
    runner must authenticate sources and frozen model SHA, not just return
    a synthetic true value. No historical race result is ever read.
    """
    round_context.checked_context(context)
    require(callable(independently_verify_suite) and
            independently_verify_suite(saved) is True,
            "EXISTING_FOUR_MODEL_SUITE_NOT_INDEPENDENTLY_VERIFIED")
    require(callable(independently_verify_lines) and
            independently_verify_lines(line_receipt) is True,
            "PRE_RACE_LINE_SOURCE_NOT_INDEPENDENTLY_VERIFIED")
    require(type(saved) is dict and
            type(saved.get("source")) is dict and
            type(saved.get("suite")) is dict and
            type(saved.get("persisted_at")) is str and
            round_context._sha(saved.get("source_sha256")),
            "ACTUAL_SAVED_PR71_SOURCE_REQUIRED")
    source,suite=saved["source"],saved["suite"]
    rider_ids=source.get("starters")
    require(type(rider_ids) is list and len(rider_ids) in (7,9) and
            all(_rider(x) for x in rider_ids) and
            len(set(rider_ids))==len(rider_ids) and
            source.get("race_id")==suite.get("race_id")==context["race_id"] and
            source.get("official_cutoff_at")==suite.get("sales_cutoff_at")==
                context["official_cutoff_at"] and
            source.get("as_of")==suite.get("as_of")==context["as_of"] and
            round_context._sha(suite.get("input_sha256")) and
            suite["input_sha256"]==context["parent_input_sha256"] and
            _clock(source["as_of"])<=_clock(saved["persisted_at"]) and
            (_clock(source["official_cutoff_at"]) -
             _clock(saved["persisted_at"])).total_seconds()>=65,
            "ACTUAL_PR71_SOURCE_CUTOFF_OR_RID_MISMATCH")
    require(type(line_receipt) is dict and set(line_receipt)=={
        "race_id","source_input_sha256","observed_at",
        "source_sha256","starting_order","line_groups"
    } and line_receipt["race_id"]==context["race_id"] and
            line_receipt["source_input_sha256"]==suite["input_sha256"] and
            round_context._sha(line_receipt["source_sha256"]) and
            _clock(line_receipt["observed_at"])<=_clock(source["as_of"]),
            "LINE_HYPOTHESIS_AFTER_CUTOFF_OR_FROM_OTHER_INPUT")
    require(type(suite.get("models")) is dict and
            set(suite["models"])==set(KNOWN_PR71),
            "EXISTING_FOUR_PR71_MODELS_REQUIRED")
    # Adapt one existing model, never synthesize a new model identifier.
    model_id="multisport-factor-interaction-v1"
    model=suite["models"][model_id]
    require(type(model) is dict and model.get("model_id")==model_id and
            round_context._sha(model.get("prediction_sha256")) and
            model.get("snapshot_sha256")==suite["input_sha256"] and
            type(model.get("candidates")) is list and
            len(model["candidates"])==len(rider_ids)*(len(rider_ids)-1)*(len(rider_ids)-2),
            "EXISTING_PR71_MODEL_RANKS_NOT_VERIFIED")
    ranks=[row.get("combination") if type(row) is dict else None
           for row in model["candidates"][:12]]
    require(all(_pair(ticket,set(rider_ids)) for ticket in ranks) and
            len(set(tuple(x) for x in ranks))==len(ranks),
            "PR71_ORIGINAL_TOP12_INVALID")
    snapshot={
        "race_id":context["race_id"],
        "input_sha256":suite["input_sha256"],
        "baseline_model_id":model_id,
        "baseline_prediction_sha256":model["prediction_sha256"],
        "as_of":source["as_of"],
        "official_cutoff_at":source["official_cutoff_at"],
        "starting_order":line_receipt["starting_order"],
        "line_groups":line_receipt["line_groups"],
        "baseline_top12":ranks,
    }
    _lines(snapshot,context)
    require(set(snapshot["starting_order"])==set(rider_ids),
            "LINE_RIDERS_DIFFER_FROM_FROZEN_PR71_SOURCE")
    return snapshot


def forecast_from_existing_pr71(*, saved, context, line_receipt,
                                tactical_plans, stage_priors,
                                independently_verify_suite,
                                independently_verify_lines):
    """Existing four-model saved row -> six phases -> research Top12 ranking."""
    snap=snapshot_from_existing_pr71(
        saved,context=context,line_receipt=line_receipt,
        independently_verify_suite=independently_verify_suite,
        independently_verify_lines=independently_verify_lines)
    return forecast_shadow(
        context=context,snapshot=snap,plans=tactical_plans,
        priors=stage_priors,
        independently_verified_parent=lambda accepted: accepted is snap)


def freeze_private_once(path, forecast):
    """Private create-once SHA; independent Git AES storage is a separate gate."""
    require(type(forecast) is dict and
            forecast.get("schema")==SCHEMA and
            forecast.get("state")=="STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY" and
            type(forecast.get("six_phase_branches")) is list and
            len(forecast["six_phase_branches"])>=2 and
            forecast.get("pr71_original_replaced") is False and
            forecast.get("formal_model_promoted") is False,
            "INVALID_TACTICAL_SHADOW_FOR_FREEZE")
    folder=Path(path).parent
    require(folder.is_dir() and not folder.is_symlink() and
            folder.stat().st_mode & 0o077 == 0 and
            not Path(path).exists() and not Path(path).is_symlink(),
            "TACTICAL_FREEZE_NEEDS_PRIVATE_CREATE_ONCE")
    raw=canonical(forecast)+b"\n"
    flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0)
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,"wb") as sink:
        sink.write(raw)
        sink.flush()
        os.fsync(sink.fileno())
    require(Path(path).read_bytes()==raw,"TACTICAL_PRIVATE_READBACK_MISMATCH")
    return sha256(raw).hexdigest()
