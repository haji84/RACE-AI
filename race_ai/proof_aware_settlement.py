"""Read-only race settlement: separate external proof from source claims.

No fetching, forecasting, model fitting, betting, mutable event store, or
public deployment. The caller must supply *independently audited* verifiers.
"""
from __future__ import annotations
from datetime import datetime
import re

class SettlementError(ValueError): pass

def _stamp(v):
    if not isinstance(v,str):raise SettlementError("timezone timestamp missing")
    try:t=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as e:raise SettlementError("invalid timestamp") from e
    if t.utcoffset() is None:raise SettlementError("naive timestamp")
    return t

def _ticket(v):
    return (isinstance(v,list) and len(v)==3 and
            all(type(x) is int and 1<=x<=99 for x in v)
            and len(set(v))==3)

def audit_settlement(ledger,results,forecasts,*,verify_result=None,verify_cutoff=None,
                     verify_freeze=None,verify_coverage=None):
    """Enforce full eligible denominator; do not self-certify official facts.

    Input results are normalized *claims*, not official authenticated results.
    Source, cutoff, forecast receipt and completeness checks are four distinct
    independent trust boundaries; all default to deny.
    """
    if not isinstance(ledger,dict) or ledger.get("schema")!="RACE_AI_FORECAST_AUDIT_V1" or ledger.get("dataset_status")!="AUDIT_ONLY":
        raise SettlementError("source discovery ledger required")
    rows=ledger.get("records")
    if not isinstance(rows,list) or not rows or len(rows)>10000:
        raise SettlementError("bounded discovery races required")
    ids=[x.get("race_id") for x in rows if isinstance(x,dict)]
    if len(ids)!=len(rows) or len(set(ids))!=len(ids):
        raise SettlementError("duplicated/malformed race identity")
    if not isinstance(results,list) or not isinstance(forecasts,list):
        raise SettlementError("separate outcome/proof arrays required")
    outcome_by_id={}; forecast_by_id={}
    for res in results:
        if not isinstance(res,dict) or set(res)!={"race_id","status","trifecta_offered",
              "payouts","refund_status","revision_no","confirmed_at","source_ref"}:
            raise SettlementError("strict result schema required")
        ident=res["race_id"]
        if ident in outcome_by_id or ident not in ids:
            raise SettlementError("duplicate/unlisted result identity")
        if res["status"] not in ("FINAL","VOID","PENDING","NOT_OFFERED") or type(res["trifecta_offered"]) is not bool:
            raise SettlementError("result status invalid")
        if type(res["revision_no"]) is not int or res["revision_no"]<1:
            raise SettlementError("result revision invalid")
        _stamp(res["confirmed_at"])
        if not isinstance(res["source_ref"],str) or not res["source_ref"].startswith("https://"):
            raise SettlementError("result URL missing")
        if res["refund_status"] not in ("NONE","PARTIAL","FULL","UNKNOWN"):
            raise SettlementError("refund status invalid")
        if not isinstance(res["payouts"],list) or len(res["payouts"])>20:
            raise SettlementError("payout list invalid")
        combos=set()
        for x in res["payouts"]:
            if (not isinstance(x,dict) or set(x)!={"combination","yen_per_100"}
                or not _ticket(x["combination"]) or type(x["yen_per_100"]) is not int or x["yen_per_100"]<=0):
                raise SettlementError("invalid 3ren-tan payout")
            combo=tuple(x["combination"])
            if combo in combos:raise SettlementError("duplicate payout")
            combos.add(combo)
        if res["status"]=="FINAL" and res["trifecta_offered"] and not combos:
            raise SettlementError("final 3ren-tan requires payout combinations")
        if res["status"]!="FINAL" and combos:
            raise SettlementError("nonfinal result cannot carry trusted 3ren-tan payout")
        outcome_by_id[ident]=res
    for f in forecasts:
        if not isinstance(f,dict) or set(f)!={"race_id","model_race_id","model_id",
                 "ordered_top8","prediction_sha256","generated_at","persisted_at",
                 "cutoff_at","receipt"}:
            raise SettlementError("strict frozen forecast contract required")
        ident=f["race_id"]
        if ident in forecast_by_id or ident not in ids:
            raise SettlementError("duplicate/unlisted forecast identity")
        if (not isinstance(f["prediction_sha256"],str)
            or not re.fullmatch(r"[0-9a-f]{64}",f["prediction_sha256"])):
            raise SettlementError("prediction fingerprint invalid")
        if (not isinstance(f["model_race_id"],str) or not f["model_race_id"]
            or not isinstance(f["model_id"],str) or not f["model_id"]):
            raise SettlementError("model/race identity missing")
        picks=f["ordered_top8"]
        if not isinstance(picks,list) or not 1<=len(picks)<=8 or any(not _ticket(t) for t in picks) or len({tuple(t) for t in picks})!=len(picks):
            raise SettlementError("invalid or duplicate top8")
        _stamp(f["generated_at"]);_stamp(f["persisted_at"]);_stamp(f["cutoff_at"])
        forecast_by_id[ident]=f
    # Source completeness is a separate upstream claim. A matching list of
    # races never means the official day's complete eligible denominator.
    full_coverage = callable(verify_coverage) and verify_coverage(ledger) is True
    known_eligible=0;freeze_count=0;hit1=0;hit8=0;paper_return=0
    all_proven=True;all_refunds_known=True;rows_out=[]
    for row in rows:
        ident=row["race_id"]
        result=outcome_by_id.get(ident)
        f=forecast_by_id.get(ident)
        source_ok=bool(result is not None and callable(verify_result)
                       and verify_result(result) is True)
        eligible=bool(source_ok and result["status"]=="FINAL" and result["trifecta_offered"])
        if not source_ok:
            all_proven=False
        if result is not None and result["status"]=="PENDING":
            all_proven=False
        cutoff_ok=bool(callable(verify_cutoff) and verify_cutoff(row) is True)
        before=bool(f and _stamp(f["generated_at"])<=_stamp(f["persisted_at"])<_stamp(f["cutoff_at"]))
        identical=bool(f and row.get("sales_cutoff_at")==f["cutoff_at"])
        frozen=bool(f and eligible and cutoff_ok and before and identical
                    and callable(verify_freeze) and verify_freeze(f,ident) is True)
        if eligible:
            known_eligible+=1
            if result["refund_status"]!="NONE":all_refunds_known=False
            if frozen:
                freeze_count+=1
                winners={tuple(x["combination"]):x["yen_per_100"] for x in result["payouts"]}
                hits=[tuple(x) for x in f["ordered_top8"] if tuple(x) in winners]
                if tuple(f["ordered_top8"][0]) in winners:hit1+=1
                if hits:hit8+=1
                paper_return+=sum(winners[x] for x in hits)
        rows_out.append({"race_id":ident,"official_result_verified":source_ok,
                         "eligible_confirmed":eligible,"pre_cutoff_freeze_verified":frozen,
                         "hit_at_1":bool(eligible and frozen and tuple(f["ordered_top8"][0]) in
                                         {tuple(x["combination"]) for x in result["payouts"]}) if f else False,
                         "missing_reason":None if frozen else
                             "RESULT_NOT_VERIFIED" if not source_ok else
                             "NOT_ELIGIBLE" if not eligible else
                             "MISSING_OR_UNVERIFIED_FREEZE"})
    can_score=bool(full_coverage and all_proven and known_eligible>0)
    # No ROI claim with refund/void ambiguity. A 100yen-per-ticket paper
    # strategy is distinct from proven actual purchases.
    stakes=100*sum(len(forecast_by_id[r["race_id"]]["ordered_top8"]) for r in rows_out
                   if r["pre_cutoff_freeze_verified"])
    return {"schema":"RACE_AI_PROOF_AWARE_DAILY_RECONCILIATION_V1",
            "evidence_status":"CALLBACK_ATTESTED_UNLESS_INDEPENDENTLY_AUDITED",
            "source_full_day_verified_by_callback":full_coverage,
            "all_listed_results_verified":all_proven,
            "eligible_verified_subset":known_eligible,
            "freeze_verified_subset":freeze_count,
            "hit1_verified_subset":hit1,"hit8_verified_subset":hit8,
            "formal_hit_at_1_all":hit1/known_eligible if can_score else None,
            "formal_hit_at_8_all":hit8/known_eligible if can_score else None,
            "formal_capture_rate":freeze_count/known_eligible if can_score else None,
            "paper_roi_on_frozen_picks":paper_return/stakes if can_score and
                                       all_refunds_known and stakes else None,
            "actual_purchase_roi":None,
            "brier_score":None,"log_loss":None,
            "source_records_preserved":len(rows),
            "rows":rows_out}
