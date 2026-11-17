"""Three-arm same-race evaluation: original PR71 vs round vs round+pair.

Research only. Every candidate must have a separate immutable pre-cutoff
private receipt and an independently verified official settlement. Fail
closed when independent proof is absent, keep all planned HOLD races in the
denominator, and never treat a 1-race winner as measured model improvement.
"""
from __future__ import annotations

from collections import defaultdict

from . import keirin_line_cohesion as line
from . import keirin_round_paired_audit as paired
from . import keirin_round_six_phase_rank as six
from . import keirin_round_motivation as stage

SCHEMA = "RACE_AI_KEIRIN_3ARM_PAIR_AUDIT_V1"


def _hold(rid, why):
    return {"schema":SCHEMA,"race_id":rid,"state":"HOLD","reason":why,
            "paired_evaluable":False,"formal_uplift_proven":False}


def _verified(cb, *args):
    if not callable(cb):
        return False
    try:
        return cb(*args) is True
    except Exception:
        return False


def compare_three(*, original, line_study, round_receipt, line_receipt,
                  original_receipt, event_context, result,
                  verify_original=None, verify_round=None, verify_line=None,
                  verify_video_labels=None, verify_result=None):
    """Do not accept a missing or unsealed opponent, even if one hit."""
    rid=original.get("race_id") if type(original) is dict else None
    if not rid or type(event_context) is not dict or event_context.get("race_id")!=rid:
        return _hold(rid,"COHORT_RACE_OR_EVENT_CONTEXT_MISMATCH")
    try:
        stage.checked_context(event_context)
    except (stage.RoundError,TypeError,ValueError,KeyError):
        return _hold(rid,"EVENT_PROGRAM_NOT_PRE_CUTOFF_VERIFIED")
    if (type(line_study) is not dict or
        line_study.get("schema")!=line.REPORT_SCHEMA or
        line_study.get("race_id")!=rid or
        line_study.get("state")!="RESEARCH_STAGE_PLUS_LINE" or
        type(line_study.get("conditioning")) is not dict):
        return _hold(rid,"NO_ADMITTED_LINE_CONDITIONING")
    context_sha=stage.digest(event_context)
    m=line_study["conditioning"]
    before=line_study.get("stage_only")
    after=line_study.get("stage_plus_line")
    if (type(before) is not dict or type(after) is not dict or
        before.get("schema")!=six.SCHEMA or after.get("schema")!=six.SCHEMA or
        before.get("state")!=after.get("state") or
        before.get("state")!="STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY" or
        before.get("context_sha256")!=context_sha or
        after.get("context_sha256")!=context_sha or
        m.get("context_sha256")!=context_sha or
        m.get("prior_model_sha256")!=before.get("scenario_priors_sha256") or
        m.get("adjusted_model_sha256")!=after.get("scenario_priors_sha256") or
        m.get("line_conditioning_applied") is not True or
        before.get("parent_prediction_sha256")!=after.get("parent_prediction_sha256") or
        before.get("pre_race_input_sha256")!=after.get("pre_race_input_sha256") or
        before.get("original_rank1")!=after.get("original_rank1")):
        return _hold(rid,"LINE_CONDITIONING_PROVENANCE_OR_LINEAGE_MISMATCH")
    if not _verified(verify_video_labels,line_study):
        return _hold(rid,"LINE_HISTORY_INDEPENDENT_READER_UNAVAILABLE")
    # The model must have computed its line-conditioned weights BEFORE
    # the sealed candidate receipt was persisted. A file SHA alone cannot
    # authenticate inference timing; the trusted readback must confirm it.
    try:
        computed=stage._timestamp(m.get("computed_at"))
        saved_line=stage._timestamp(line_receipt.get("saved_at"))
        cutoff=stage._timestamp(event_context["official_cutoff_at"])
        asof=stage._timestamp(event_context["as_of"])
        if not (asof <= computed <= saved_line and
                (cutoff-computed).total_seconds() >= 65):
            return _hold(rid,"LINE_MODEL_COMPUTED_AFTER_FREEZE_OR_CUTOFF")
    except (stage.RoundError,TypeError,ValueError,KeyError,AttributeError):
        return _hold(rid,"LINE_MODEL_COMPUTED_TIME_MISSING")
    first=paired.compare(
        original=original,candidate=before,
        original_receipt=original_receipt,candidate_receipt=round_receipt,
        result=result,verify_original=verify_original,
        verify_candidate=verify_round,
        verify_organizer_result=verify_result)
    if not first.get("paired_evaluable"):
        return _hold(rid,"ROUND_STAGE_ARM_"+first.get("reason","UNKNOWN"))
    second=paired.compare(
        original=original,candidate=after,
        original_receipt=original_receipt,candidate_receipt=line_receipt,
        result=result,verify_original=verify_original,
        verify_candidate=verify_line,
        verify_organizer_result=verify_result)
    if not second.get("paired_evaluable"):
        return _hold(rid,"COHESION_ARM_"+second.get("reason","UNKNOWN"))
    return {
        "schema":SCHEMA,"state":"PRIVATE_THREE_ARM_SAME_RACE_RESEARCH",
        "race_id":rid,
        "competition":after["competition"],"round_stage":after["round_stage"],
        "program_code":event_context["event_program_code"],
        "same_original_prediction_sha256":original["baseline_prediction_sha256"],
        "event_context_sha256":context_sha,
        "line_label_history_sha256":m["private_history_sha256"],
        "paired_evaluable":True,
        "original":first["original"],
        "round_stage_only":first["candidate"],
        "round_and_line":second["candidate"],
        "round_vs_original_hit1_delta":first["hit_at_1_delta"],
        "line_vs_round_hit1_delta":(
            int(second["candidate"]["hit_at_1"])-
            int(first["candidate"]["hit_at_1"])),
        "line_vs_round_all_delta":(
            int(second["candidate"]["hit_at_all"])-
            int(first["candidate"]["hit_at_all"])),
        "line_vs_round_virtual_payout_delta_yen":(
            second["candidate"]["virtual_payout_yen"]-
            first["candidate"]["virtual_payout_yen"]),
        "three_versions_of_predictions_frozen_pre_cutoff":True,
        "formal_uplift_proven":False,
        "actual_money_wagered":False,
    }


def summarize(cohort, reports):
    """Use the existing pre-registered 100%-denominator cohort contract."""
    paired.require(type(cohort) is dict and
                   cohort.get("schema")==paired.COHORT_SCHEMA and
                   cohort.get("cohort_sha256")==stage.digest({
                       k:v for k,v in cohort.items() if k!="cohort_sha256"}),
                   "THREE_ARM_COHORT_NOT_FROZEN")
    paired.require(type(reports) is list and len(reports)<=len(cohort["race_ids"]),
                   "THREE_ARM_TOO_MANY_REPORTS")
    seen={}
    for row in reports:
        paired.require(type(row) is dict and row.get("schema")==SCHEMA and
                       row.get("race_id") in cohort["race_ids"] and
                       row["race_id"] not in seen,
                       "THREE_ARM_OUT_OF_COHORT_OR_DUPLICATE")
        seen[row["race_id"]]=row
    keys=("original","round_stage_only","round_and_line")
    empty=lambda:{"hit_at_1":0,"hit_at_all":0,
                  "virtual_stake_yen":0,"virtual_payout_yen":0}
    groups=defaultdict(lambda:{"evaluable":0,**{k:empty() for k in keys}})
    holds=defaultdict(int)
    for rid in cohort["race_ids"]:
        row=seen.get(rid)
        if row is None or row.get("state")!="PRIVATE_THREE_ARM_SAME_RACE_RESEARCH":
            holds[row.get("reason","UNREPORTED") if row else "UNREPORTED"]+=1
            continue
        key=":".join((row["competition"],row["round_stage"],row["program_code"]))
        g=groups[key];g["evaluable"]+=1
        for k in keys:
            for field in empty():
                g[k][field]+=row[k][field]
    output={}
    for label,g in sorted(groups.items()):
        for k in keys:
            sub=g[k]
            sub["hit_at_1_rate"]=sub["hit_at_1"]/g["evaluable"]
            sub["hit_at_all_rate"]=sub["hit_at_all"]/g["evaluable"]
            sub["virtual_roi"]=(sub["virtual_payout_yen"]/sub["virtual_stake_yen"]
                                if sub["virtual_stake_yen"] else None)
        output[label]=g
    return {
        "schema":"RACE_AI_KEIRIN_LINE_3ARM_PROSPECTIVE_COHORT_SUMMARY_V1",
        "cohort_sha256":cohort["cohort_sha256"],
        "planned_races":len(cohort["race_ids"]),
        "three_arm_paired_races":sum(x["evaluable"] for x in groups.values()),
        "unpaired_holds":dict(sorted(holds.items())),
        "by_class_round_program":output,
        "future_independent_result_and_cohort_attestation":False,
        "real_accuracy_uplift_proven":False,
        "actual_wagers_recorded":False,
    }
