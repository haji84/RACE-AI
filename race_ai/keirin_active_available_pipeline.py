"""Owner-generated A -> verified six-phase B -> optional signed line C.

This is the ACTIVE research path. It does not require or synthesize any
shared PR71 four-model forecast. Independent witnesses must be supplied by
the trusted owner runner, not by source-controlled true-returning lambdas.
All candidates remain research-only; publication/AES/new runner are later gates.
"""
from __future__ import annotations

from . import keirin_available_forecast_sources as available
from . import keirin_available_prediction_audit as audit
from . import keirin_line_cohesion as line
from . import keirin_round_six_phase_rank as six

SCHEMA = "RACE_AI_KEIRIN_ACTIVE_AVAILABLE_AB_OPTIONAL_C_PREPARED_V1"


def _phase_text(research_forecast):
    # Only projected race stages, not video-confirmed observations.
    branch=research_forecast["six_phase_branches"][0]
    stages=branch["six_phases"]
    if tuple(x["phase"] for x in stages)!=six.PHASES:
        raise ValueError("SIX_PHASE_PREDICTION_ORDER_INVALID")
    return {x["phase"]:"PREDICTION_ONLY order:"+
            "-".join(str(car) for car in x["projected_order"])
            for x in stages}


def prepare(*, saved_generated_race, context, official_line_receipt,
            starting_order, line_groups, tactical_plans, stage_priors,
            b_generated_at, c_generated_at=None,
            historical_line_labels=None, rider_ids_by_car=None,
            line_config=None, line_computed_at=None,
            verify_owner_generated=None, verify_source_roster=None,
            verify_official_cutoff=None,
            verify_historical_follow=None, verify_rider_id_mapping=None):
    """Generate A/B as independent research arms, C only when real history.

    A is EXISTING (already produced) and is NEVER rewritten here.
    B uses the existing six-stage simulation from the A input.
    C uses the same B plus independently admitted pair history.
    """
    rid=saved_generated_race.get("race_id") if type(saved_generated_race) is dict else None
    snap=available.make_stage_snapshot_from_generated(
        record=saved_generated_race,context=context,
        official_line_receipt=official_line_receipt,
        starting_order=starting_order,line_groups=line_groups,
        verify_owner_original=verify_owner_generated,
        verify_source_roster=verify_source_roster,
        verify_official_cutoff=verify_official_cutoff)
    a=audit.make_arm(
        race_id=rid,arm="EXISTING_GENERATED",
        source_document_sha256=saved_generated_race["source_forecast_document_sha256"],
        common_input_sha256=snap["input_sha256"],
        generated_at=saved_generated_race["forecast_generated_at"],
        official_cutoff_at=context["official_cutoff_at"],
        ranked_tickets=saved_generated_race["ranked_tickets"],
        observed_as_of=context["as_of"])
    b_forecast=six.forecast_shadow(
        context=context,snapshot=snap,plans=tactical_plans,priors=stage_priors,
        independently_verified_parent=verify_owner_generated and
            (lambda x: x is snap))
    if b_forecast.get("state")!="STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY":
        return {"schema":SCHEMA,"race_id":rid,"state":"HOLD_B_STAGE_NOT_READY",
                "A_existing":a,"B_six_phase":None,"C_six_phase_plus_line":None,
                "four_model_dependencies":0,"formal_accuracy_proven":False}
    b=audit.make_arm(
        race_id=rid,arm="SIX_PHASE",
        source_document_sha256=six.digest(b_forecast),
        common_input_sha256=snap["input_sha256"],
        generated_at=b_generated_at,
        official_cutoff_at=context["official_cutoff_at"],
        observed_as_of=context["as_of"],
        ranked_tickets=[x["cars"] for x in b_forecast["ranked_top12"]],
        phase_hypotheses=_phase_text(b_forecast))
    output={
        "schema":SCHEMA,"race_id":rid,
        "state":"A_B_RESEARCH_READY_C_HISTORY_HOLD",
        "A_existing":a,"B_six_phase":b,"C_six_phase_plus_line":None,
        "B_stage_original_sha256":six.digest(b_forecast),
        "C_hold":"NO_VALIDATED_HISTORICAL_PAIR_FOLLOW_DATA",
        "four_model_dependencies":0,
        "all_phases_are_predictions_not_verified_actual_video":True,
        "formal_accuracy_proven":False,
        "AES_private_originals_and_independent_runner_proven":False,
    }
    if not historical_line_labels:
        return output
    if not (callable(verify_historical_follow) and
            callable(verify_rider_id_mapping) and
            type(rider_ids_by_car) is dict and
            line_config is not None and
            type(line_computed_at) is str and
            type(c_generated_at) is str):
        output["C_hold"]="HISTORICAL_IDENTITY_LABEL_OR_COMPUTE_WITNESS_MISSING"
        return output
    study=line.forecast_with_pair_evidence(
        context=context,snapshot=snap,plans=tactical_plans,priors=stage_priors,
        history=historical_line_labels,
        athlete_ids_by_car=rider_ids_by_car,
        config=line_config,
        independently_verify_label=verify_historical_follow,
        independently_verify_identity=verify_rider_id_mapping,
        independently_verify_original=lambda x:x is snap,
        computed_at=line_computed_at)
    if study.get("state")!="RESEARCH_STAGE_PLUS_LINE":
        output["C_hold"]="INSUFFICIENT_REVIEWED_PAIR_CONDITIONING"
        return output
    adjusted=study["stage_plus_line"]
    output["C_six_phase_plus_line"]=audit.make_arm(
        race_id=rid,arm="SIX_PHASE_PLUS_LINE",
        source_document_sha256=six.digest(adjusted),
        common_input_sha256=snap["input_sha256"],
        generated_at=c_generated_at,
        official_cutoff_at=context["official_cutoff_at"],
        observed_as_of=context["as_of"],
        ranked_tickets=[x["cars"] for x in adjusted["ranked_top12"]],
        phase_hypotheses=_phase_text(adjusted),
        historical_follow_history_sha256=study["conditioning"]["private_history_sha256"])
    output["state"]="A_B_C_RESEARCH_READY_FOR_PRIVATE_FREEZE"
    output["C_hold"]=None
    output["C_history_sha256"]=study["conditioning"]["private_history_sha256"]
    return output
