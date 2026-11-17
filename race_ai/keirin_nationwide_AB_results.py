"""Nationwide A/B outcome dashboard: independent official score receipts ONLY.

Never shrink denominator from 79 to only successful guesses; compare A and B
on EXACTLY the same settled races, C only when its history is independently
verified. An unsigned, self-reported 'win' is a HOLD. Missing or canceled
races count in coverage but never silently as model misses.
"""
from __future__ import annotations

from collections import Counter,defaultdict

from . import keirin_available_prediction_audit as ab
from . import keirin_nationwide_active_AB as national

SCHEMA="RACE_AI_KEIRIN_NATIONWIDE_AB_OUTCOME_SCORECARD_V1"


class NationwideScoreError(ValueError):
    pass


def require(ok,code):
    if not ok:
        raise NationwideScoreError(code)


def _verified(callback,*args):
    if not callable(callback):
        return False
    try:
        return callback(*args) is True
    except Exception:
        return False


def _rows(registry):
    if type(registry) is dict and registry.get("schema")==national.SCHEMA:
        national.checked_registry(registry)
        return registry["records"], True
    from . import keirin_dynamic_nationwide_registry as dynamic
    dynamic.checked_day(registry)
    return registry["races"],registry["nationwide_coverage_independently_verified"]


def _zero():
    return {"eligible":0,"hit_at_1":0,"hit_at_all":0,
            "stake_yen":0,"payout_yen":0}


def _add(acc,report):
    require(type(report) is dict and
            type(report.get("hit_at_1")) is bool and
            type(report.get("hit_at_all")) is bool and
            type(report.get("stake_yen")) is int and
            type(report.get("payout_yen")) is int and
            100<=report["stake_yen"]<=1200 and
            0<=report["payout_yen"]<=10**9 and
            (report["hit_at_all"] or report["payout_yen"]==0) and
            (not report["hit_at_1"] or report["hit_at_all"]),
            "PAIRED_RESULT_SCORE_CORRUPTED")
    acc["eligible"]+=1
    acc["hit_at_1"]+=int(report["hit_at_1"])
    acc["hit_at_all"]+=int(report["hit_at_all"])
    acc["stake_yen"]+=report["stake_yen"]
    acc["payout_yen"]+=report["payout_yen"]


def _rates(d):
    out=dict(d)
    out["hit_at_1_rate"]=(
        d["hit_at_1"]/d["eligible"] if d["eligible"] else None)
    out["hit_at_all_rate"]=(
        d["hit_at_all"]/d["eligible"] if d["eligible"] else None)
    out["virtual_roi"]=(
        d["payout_yen"]/d["stake_yen"] if d["stake_yen"] else None)
    out["virtual_profit_yen"]=d["payout_yen"]-d["stake_yen"]
    return out


def summarize(*,registry,paired_reports,independently_verify_settled_report=None):
    """Only owner-trusted actual result + immutable A/B records can pass."""
    all_races,national_complete=_rows(registry)
    require(type(paired_reports) is list and
            len(paired_reports)<=len(all_races),
            "NATIONWIDE_RESULT_REPORT_LIST_INVALID")
    by_id={}
    scope={r["race_id"] for r in all_races}
    for report in paired_reports:
        rid=report.get("race_id") if type(report) is dict else None
        require(rid in scope and rid not in by_id,
                "NATIONWIDE_OUTCOME_OUTSIDE_COHORT_OR_DUPLICATE")
        by_id[rid]=report
    all_A=_zero();all_B=_zero();paired_B_with_C=_zero();paired_C=_zero()
    states=Counter()
    venues=defaultdict(lambda:{
        "registered":0,"scored_AB":0,"holds":0,
        "A":_zero(),"B":_zero()})
    for row in all_races:
        rid=row["race_id"]; venue=row["venue"]
        venues[venue]["registered"]+=1
        r=by_id.get(rid)
        if r is None:
            states["HOLD_NO_OUTCOME_RECEIPT"]+=1
            venues[venue]["holds"]+=1
            continue
        if (not r.get("ab_evaluable") or r.get("schema")!=ab.AUDIT_SCHEMA or
            r.get("state") not in (
                "A_B_RESEARCH_SETTLED","A_B_C_RESEARCH_SETTLED")):
            states["HOLD_RESULT_OR_PRE_CUTOFF_EVIDENCE_MISSING"]+=1
            venues[venue]["holds"]+=1
            continue
        if not _verified(independently_verify_settled_report,rid,r):
            states["HOLD_SETTLEMENT_NOT_INDEPENDENTLY_RESTORED"]+=1
            venues[venue]["holds"]+=1
            continue
        a=r.get("A_existing"); b=r.get("B_six_phase")
        _add(all_A,a);_add(all_B,b)
        _add(venues[venue]["A"],a);_add(venues[venue]["B"],b)
        venues[venue]["scored_AB"]+=1
        states["AB_SCORED"]+=1
        if (r.get("abc_evaluable") is True and
            r.get("state")=="A_B_C_RESEARCH_SETTLED"):
            _add(paired_B_with_C,b)
            _add(paired_C,r["C_six_phase_plus_line"])
            states["C_SCORED_ON_SAME_RACE"]+=1
        else:
            states["C_OPTIONAL_HOLD"]+=1
    require(sum(x["registered"] for x in venues.values())==len(all_races) and
            all_A["eligible"]==all_B["eligible"],
            "NATIONWIDE_DENOMINATOR_INVARIANT")
    return {
        "schema":SCHEMA,"day_jst":registry["day_jst"],
        "registered_races":len(all_races),
        "national_day_universe_independently_verified":national_complete,
        "ab_independently_scored_races":all_A["eligible"],
        "not_yet_independently_scored_races":len(all_races)-all_A["eligible"],
        "c_subset_races":paired_C["eligible"],
        "A_existing":_rates(all_A),
        "B_six_phase":_rates(all_B),
        "B_on_same_races_as_C":_rates(paired_B_with_C),
        "C_optional":_rates(paired_C),
        "by_venue":{
            name:{"registered":entry["registered"],
                  "AB_scored":entry["scored_AB"],
                  "holds":entry["holds"],
                  "A":_rates(entry["A"]),
                  "B":_rates(entry["B"])}
            for name,entry in sorted(venues.items())},
        "states":dict(sorted(states.items())),
        "old_four_models_required":False,
        "C_not_prerequisite_for_AB":True,
        "no_real_bets_made":True,
        "one_race_does_not_prove_model_uplift":True,
        "missing_races_are_not_misses":True,
    }
