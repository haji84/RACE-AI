"""A/B/C cohort research using ALREADY GENERATED predictions, not PR71 models.

A: owner-saved generated prediction; B: real six-phase forecast;
C: B with independently admitted prior line-follow history (optional).
Missing C never blocks the A/B cohort. No synthetic proof of real accuracy.
Original bytes/AES, official cutoff and result require trusted independent
caller verification. Never count skipped races as losses or discard HOLDs.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import re

from . import keirin_round_motivation as stage

ARM_SCHEMA = "RACE_AI_KEIRIN_AVAILABLE_FORECAST_ARM_V1"
COHORT_SCHEMA = "RACE_AI_KEIRIN_AVAILABLE_AB_COHORT_V1"
AUDIT_SCHEMA = "RACE_AI_KEIRIN_AVAILABLE_AB_OPTIONAL_C_AUDIT_V1"
PHASES=("INITIAL","BELL","FINAL_HOME","FINAL_BACK","FOURTH_CORNER","GOAL")
KINDS=("EXISTING_GENERATED","SIX_PHASE","SIX_PHASE_PLUS_LINE")
RID=re.compile(r"^20[0-9]{10}$")
HEX=re.compile(r"^[0-9a-f]{64}$")


class ActiveForecastError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ActiveForecastError(code)


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def when(value):
    try:
        return stage._timestamp(value)
    except (ValueError,TypeError,stage.RoundError):
        raise ActiveForecastError("AWARE_FORECAST_CLOCK_REQUIRED") from None


def sha(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def _tickets(picks):
    need(type(picks) is list and 1<=len(picks)<=12,
         "ACTIVE_FORECAST_1_TO_12_TICKETS_REQUIRED")
    seen=set()
    for triple in picks:
        need(type(triple) is list and len(triple)==3 and
             all(type(x) is int and 1<=x<=9 for x in triple) and
             len(set(triple))==3 and tuple(triple) not in seen,
             "ACTIVE_FORECAST_TRIPLE_INVALID_OR_REUSED")
        seen.add(tuple(triple))
    return picks


def make_arm(*,race_id,arm,source_document_sha256,common_input_sha256,
             generated_at,official_cutoff_at,ranked_tickets,
             observed_as_of,phase_hypotheses=None,
             historical_follow_history_sha256=None):
    """Create a research candidate document, NOT an immutable or AES receipt."""
    need(type(race_id) is str and RID.fullmatch(race_id) and
         arm in KINDS and
         sha(source_document_sha256) and sha(common_input_sha256),
         "SOURCE_NEUTRAL_RACE_ARM_OR_HASH_REQUIRED")
    t=when(generated_at); seen=when(observed_as_of); deadline=when(official_cutoff_at)
    need(seen<=t and (deadline-t).total_seconds()>=65,
         "ARM_NOT_GENERATED_65_SECONDS_BEFORE_CUTOFF")
    if arm=="EXISTING_GENERATED":
        need(phase_hypotheses in (None,{}) and
             historical_follow_history_sha256 is None,
             "EXISTING_RESEARCH_ORIGINAL_NOT_SIX_PHASE_ARM")
        phases=None
    else:
        need(type(phase_hypotheses) is dict and
             set(phase_hypotheses)==set(PHASES) and
             all(type(v) is str and bool(v.strip())
                 for v in phase_hypotheses.values()),
             "SIX_PHASE_RESEARCH_HYPOTHESES_REQUIRED")
        phases=dict(phase_hypotheses)
        if arm=="SIX_PHASE":
            need(historical_follow_history_sha256 is None,
                 "STAGE_ONLY_CANNOT_USE_HISTORY")
        else:
            need(sha(historical_follow_history_sha256),
                 "LINE_ADJUSTMENT_REQUIRES_REVIEWED_HISTORY_SHA")
    d={
        "schema":ARM_SCHEMA,"arm":arm,"race_id":race_id,
        "common_input_sha256":common_input_sha256,
        "source_document_sha256":source_document_sha256,
        "observed_as_of":observed_as_of,
        "generated_at":generated_at,
        "official_cutoff_at":official_cutoff_at,
        "ranked_tickets":_tickets(ranked_tickets),
        "phase_hypotheses":phases,
        "historical_follow_history_sha256":historical_follow_history_sha256,
        "research_only":True,
    }
    d["arm_digest_sha256"]=digest(d)
    return d


def checked_arm(arm):
    need(type(arm) is dict and
         arm.get("schema")==ARM_SCHEMA and
         sha(arm.get("arm_digest_sha256")),
         "ACTIVE_FORECAST_ARM_SCHEMA_REQUIRED")
    original={k:v for k,v in arm.items() if k!="arm_digest_sha256"}
    need(digest(original)==arm["arm_digest_sha256"],
         "ACTIVE_FORECAST_ARM_CONTENT_SHA_MISMATCH")
    expected=make_arm(
        race_id=arm["race_id"],arm=arm["arm"],
        source_document_sha256=arm["source_document_sha256"],
        common_input_sha256=arm["common_input_sha256"],
        observed_as_of=arm["observed_as_of"],
        generated_at=arm["generated_at"],
        official_cutoff_at=arm["official_cutoff_at"],
        ranked_tickets=arm["ranked_tickets"],
        phase_hypotheses=arm["phase_hypotheses"],
        historical_follow_history_sha256=arm["historical_follow_history_sha256"])
    need(expected==arm,"ACTIVE_FORECAST_ARM_MUTATED_OR_UNKNOWN_FIELDS")
    return arm


def register_cohort(*,race_ids,registered_at,race_cutoffs,baseline_label):
    need(type(race_ids) is list and 1<=len(race_ids)<=1000 and
         len(set(race_ids))==len(race_ids) and
         all(type(x) is str and RID.fullmatch(x) for x in race_ids) and
         type(race_cutoffs) is dict and set(race_cutoffs)==set(race_ids) and
         type(baseline_label) is str and 1<=len(baseline_label)<=120,
         "ACTIVE_COHORT_TARGETS_REQUIRED")
    when(registered_at)
    for rid in race_ids:
        need((when(race_cutoffs[rid])-when(registered_at)).total_seconds()>=65,
             "COHORT_REGISTERED_AFTER_CUTOFF")
    c={"schema":COHORT_SCHEMA,"race_ids":list(race_ids),
       "registered_at":registered_at,
       "race_cutoffs":dict(race_cutoffs),
       "baseline_label":baseline_label,
       "four_model_baseline_required":False}
    c["cohort_sha256"]=digest(c)
    return c


def checked_cohort(c):
    need(type(c) is dict and c.get("schema")==COHORT_SCHEMA and
         sha(c.get("cohort_sha256")), "ACTIVE_COHORT_INVALID")
    same=register_cohort(
        race_ids=c["race_ids"],registered_at=c["registered_at"],
        race_cutoffs=c["race_cutoffs"],baseline_label=c["baseline_label"])
    need(c==same,"ACTIVE_COHORT_SHA_OR_CONTENT_MISMATCH")
    return c


def _accepted(cb, *args):
    if not callable(cb):
        return False
    try:
        return cb(*args) is True
    except Exception:
        return False


def _hold(rid, reason):
    return {"schema":AUDIT_SCHEMA,"race_id":rid,"state":"HOLD",
            "reason":reason,"ab_evaluable":False,"abc_evaluable":False,
            "C_state":"HOLD","real_improvement_proven":False}


def _score(tickets,paid):
    stake=100*len(tickets)
    payment=sum(paid.get(tuple(t),0) for t in tickets)
    return {"hit_at_1":tuple(tickets[0]) in paid,
            "hit_at_all":any(tuple(t) in paid for t in tickets),
            "ticket_count":len(tickets),
            "stake_yen":stake,"payout_yen":payment,
            "roi":payment/stake,"wager_placed":False}


def compare(*,cohort,original,stage_forecast,line_forecast=None,
            original_receipt=None,stage_receipt=None,line_receipt=None,
            result=None,verify_original=None,verify_stage=None,
            verify_line=None,verify_official_cutoff=None,
            verify_result=None,verify_line_history=None):
    """Research score; C never prevents a qualified A/B report."""
    checked_cohort(cohort)
    rid=original.get("race_id") if type(original) is dict else None
    if rid not in cohort["race_ids"]:
        return _hold(rid,"RACE_NOT_PRE_REGISTERED")
    try:
        for forecast,arm in ((original,"EXISTING_GENERATED"),
                             (stage_forecast,"SIX_PHASE")):
            checked_arm(forecast)
            need(forecast["arm"]==arm and forecast["race_id"]==rid and
                 forecast["official_cutoff_at"]==cohort["race_cutoffs"][rid],
                 "A_B_RACE_CUTOFF_OR_ROLE_MISMATCH")
        need(original["common_input_sha256"]==
             stage_forecast["common_input_sha256"],
             "A_B_DIFFERENT_INPUT_ORIGINALS")
    except (ActiveForecastError,KeyError,TypeError):
        return _hold(rid,"A_B_INPUT_OR_ARM_INVALID")
    # Timestamp and byte SHA must be verified against actual separately saved
    # originals by an independent owner runner. A supplied True in synthetic CI
    # is NOT a real implementation of this requirement.
    for candidate,receipt,verify in (
        (original,original_receipt,verify_original),
        (stage_forecast,stage_receipt,verify_stage)):
        if not (type(receipt) is dict and
                set(receipt)=={"race_id","saved_at","arm_digest_sha256",
                               "persisted_content_sha256"} and
                receipt["race_id"]==rid and
                receipt["arm_digest_sha256"]==candidate["arm_digest_sha256"] and
                sha(receipt["persisted_content_sha256"]) and
                (when(receipt["saved_at"])-when(candidate["generated_at"])).total_seconds()>=0 and
                (when(cohort["race_cutoffs"][rid])-when(receipt["saved_at"])).total_seconds()>=65 and
                _accepted(verify,candidate,receipt)):
            return _hold(rid,"A_B_ORIGINALS_NOT_INDEPENDENTLY_READ_BACK_BEFORE_CUTOFF")
    if not _accepted(verify_official_cutoff,cohort,rid):
        return _hold(rid,"OFFICIAL_SALES_CUTOFF_NOT_ATTESTED")
    if (type(result) is not dict or result.get("race_id")!=rid or
        result.get("status")!="FINAL_NORMAL" or
        result.get("refund_status")!="NONE" or
        not _accepted(verify_result,result)):
        return _hold(rid,"OFFICIAL_RESULT_NOT_INDEPENDENTLY_ATTESTED_OR_SETTLED")
    try:
        need(when(result["source_published_at"]) >
             when(cohort["race_cutoffs"][rid]) and
             when(result["observed_at"]) >= when(result["source_published_at"]),
             "OFFICIAL_RESULT_REVIEWED_BEFORE_CUTOFF_OR_PUBLICATION")
    except (KeyError,TypeError,ActiveForecastError):
        return _hold(rid,"OFFICIAL_RESULT_PUBLICATION_CLOCK_UNVERIFIED")
    try:
        paid={}
        entries=result["payouts_100yen"]; wins=result["winning_triples"]
        need(type(entries) is list and bool(entries) and
             type(wins) is list and bool(wins),
             "RESULT_PAYOUTS_MISSING")
        for item in entries:
            need(type(item) is dict and set(item)=={"triple","yen"} and
                 type(item["yen"]) is int and 100<=item["yen"]<=10**9 and
                 type(item["triple"]) is list and len(item["triple"])==3 and
                 len(set(item["triple"]))==3 and
                 tuple(item["triple"]) not in paid,
                 "RESULT_PAYOUT_FORMAT_OR_DUPLICATE")
            paid[tuple(item["triple"])]=item["yen"]
        need({tuple(x) for x in wins}==set(paid),
             "RESULT_WINNER_PAYOUT_MISMATCH")
    except (ActiveForecastError,TypeError,KeyError,ValueError):
        return _hold(rid,"OFFICIAL_RESULT_PAYLOAD_INVALID")
    a=_score(original["ranked_tickets"],paid)
    b=_score(stage_forecast["ranked_tickets"],paid)
    report={"schema":AUDIT_SCHEMA,"race_id":rid,"state":"A_B_RESEARCH_SETTLED",
            "ab_evaluable":True,"abc_evaluable":False,"A_existing":a,
            "B_six_phase":b,
            "C_six_phase_plus_line":None,
            "C_state":"HOLD_NOT_AVAILABLE",
            "ab_hit_at_1_delta":int(b["hit_at_1"])-int(a["hit_at_1"]),
            "ab_hit_at_all_delta":int(b["hit_at_all"])-int(a["hit_at_all"]),
            "real_improvement_proven":False,
            "original_4model_required":False,
            "actual_wagers_placed":False}
    if line_forecast is None:
        return report
    try:
        checked_arm(line_forecast)
        eligible=(line_forecast["arm"]=="SIX_PHASE_PLUS_LINE" and
                  line_forecast["race_id"]==rid and
                  line_forecast["official_cutoff_at"]==cohort["race_cutoffs"][rid] and
                  line_forecast["common_input_sha256"]==original["common_input_sha256"] and
                  sha(line_forecast["historical_follow_history_sha256"]) and
                  type(line_receipt) is dict and
                  set(line_receipt)=={"race_id","saved_at",
                                     "arm_digest_sha256","persisted_content_sha256"} and
                  line_receipt["race_id"]==rid and
                  line_receipt["arm_digest_sha256"]==line_forecast["arm_digest_sha256"] and
                  sha(line_receipt["persisted_content_sha256"]) and
                  when(line_receipt["saved_at"])>=when(line_forecast["generated_at"]) and
                  (when(cohort["race_cutoffs"][rid])-when(line_receipt["saved_at"])).total_seconds()>=65 and
                  _accepted(verify_line_history,line_forecast) and
                  _accepted(verify_line,line_forecast,line_receipt))
    except (ActiveForecastError,ValueError,TypeError,KeyError):
        eligible=False
    if not eligible:
        report["C_state"]="HOLD_UNVERIFIED_LINE_HISTORY_OR_FREEZE"
        return report
    c=_score(line_forecast["ranked_tickets"],paid)
    report.update({"state":"A_B_C_RESEARCH_SETTLED","abc_evaluable":True,
                   "C_state":"EVALUABLE","C_six_phase_plus_line":c,
                   "bc_hit_at_1_delta":int(c["hit_at_1"])-int(b["hit_at_1"]),
                   "bc_hit_at_all_delta":int(c["hit_at_all"])-int(b["hit_at_all"])})
    return report


def summarize(cohort,reports):
    checked_cohort(cohort)
    need(type(reports) is list and len(reports)<=len(cohort["race_ids"]),
         "ACTIVE_COHORT_REPORTS_INVALID")
    seen={}
    for report in reports:
        need(type(report) is dict and report.get("schema")==AUDIT_SCHEMA and
             report.get("race_id") in cohort["race_ids"] and
             report["race_id"] not in seen,
             "ACTIVE_COHORT_OUT_OF_SCOPE_OR_DUPLICATE")
        seen[report["race_id"]]=report
    holds=defaultdict(int)
    c_hold=defaultdict(int)
    score={k:{"n":0,"hit_at_1":0,"hit_at_all":0,
              "stake_yen":0,"payout_yen":0}
           for k in ("A_existing","B_six_phase","C_six_phase_plus_line")}
    ab_n=abc_n=0
    bc_paired_b={"n":0,"hit_at_1":0,"hit_at_all":0,"stake_yen":0,"payout_yen":0}
    for rid in cohort["race_ids"]:
        item=seen.get(rid)
        if item is None or not item.get("ab_evaluable"):
            holds[item.get("reason","UNREPORTED") if item else "UNREPORTED"]+=1
            continue
        ab_n+=1
        for name in ("A_existing","B_six_phase"):
            z=score[name];x=item[name]
            z["n"]+=1;z["hit_at_1"]+=int(x["hit_at_1"])
            z["hit_at_all"]+=int(x["hit_at_all"])
            z["stake_yen"]+=x["stake_yen"];z["payout_yen"]+=x["payout_yen"]
        if item.get("abc_evaluable"):
            abc_n+=1
            x_b=item["B_six_phase"]
            bc_paired_b["n"]+=1
            bc_paired_b["hit_at_1"]+=int(x_b["hit_at_1"])
            bc_paired_b["hit_at_all"]+=int(x_b["hit_at_all"])
            bc_paired_b["stake_yen"]+=x_b["stake_yen"]
            bc_paired_b["payout_yen"]+=x_b["payout_yen"]
            z=score["C_six_phase_plus_line"];x=item["C_six_phase_plus_line"]
            z["n"]+=1;z["hit_at_1"]+=int(x["hit_at_1"])
            z["hit_at_all"]+=int(x["hit_at_all"])
            z["stake_yen"]+=x["stake_yen"];z["payout_yen"]+=x["payout_yen"]
        else:
            c_hold[item.get("C_state","HOLD_UNREPORTED")]+=1
    for x in (*score.values(), bc_paired_b):
        x["hit_1_rate"]=x["hit_at_1"]/x["n"] if x["n"] else None
        x["hit_all_rate"]=x["hit_at_all"]/x["n"] if x["n"] else None
        x["virtual_roi"]=x["payout_yen"]/x["stake_yen"] if x["stake_yen"] else None
    return {"schema":"RACE_AI_KEIRIN_AVAILABLE_AB_OPTIONAL_C_SUMMARY_V1",
            "cohort_sha256":cohort["cohort_sha256"],
            "registered_races":len(cohort["race_ids"]),
            "ab_comparable_races":ab_n,
            "abc_comparable_races":abc_n,
            "ab_holds":dict(sorted(holds.items())),
            "c_only_holds":dict(sorted(c_hold.items())),
            "arms":score,
            "B_on_the_same_C_eligible_races":bc_paired_b,
            "C_comparison_uses_identical_race_subset_not_AB_full_denominator":True,
            "four_model_dependency_removed":True,
            "real_uplift_proven":False,
            "actual_wagers_placed":False}
