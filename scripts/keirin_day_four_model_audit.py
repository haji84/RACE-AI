"""Daily model-by-model audit for frozen PR71 predictions, never a predictor.

Uses the EXISTING keirin_pr71_four_model_rank result settlement code and the
original four model identities. All 78 race slots stay visible even without
permitted rider inputs or result evidence. No missing forecast is a loss.

On public GitHub Actions only aggregate COUNTS are printed; actual Top8,
Top12 and variable tickets, complete sorted rankings, source and payouts
stay solely inside the existing private encrypted SQLite lineage. Nothing
in this module collects results or manufactures model input factors.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import re
import sqlite3
from tempfile import TemporaryDirectory

SCHEMA="RACE_AI_KEIRIN_DAY_FOUR_MODEL_AUDIT_V1"
COHORT="RACE_AI_KEIRIN_20261110_78R_SOURCE_ONLY_COHORT_V1"
MODELS=(
    "multisport-factor-interaction-v1",
    "multisport-scenario-ensemble-v1",
    "multisport-conditional-duel-v1",
    "multisport-race-trajectory-v1",
)
MODES=("top8","top12","variable")


class DayAuditError(ValueError):
    pass


def need(condition,code):
    if not condition:
        raise DayAuditError(code)


def load_cohort(path):
    path=Path(path)
    need(path.is_file() and not path.is_symlink() and
         path.stat().st_size<=100_000,
         "TRUSTED_SMALL_SOURCE_ONLY_COHORT_REQUIRED")
    try: data=json.loads(path.read_bytes())
    except (OSError,ValueError):
        raise DayAuditError("COHORT_BAD_JSON") from None
    need(type(data) is dict and data.get("schema")==COHORT,
         "COHORT_SCHEMA_REQUIRED")
    date=data.get("event_day_jst")
    need(type(date) is str and bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}",date)),
         "COHORT_VALID_EVENT_DATE_REQUIRED")
    dt=datetime.fromisoformat(date)
    need(dt.strftime("%Y-%m-%d")==date,"COHORT_BAD_EVENT_DAY")
    rows=data.get("races")
    need(type(rows) is list and 1<=len(rows)<=150 and
         data.get("scheduled_races")==len(rows) and
         data.get("expected_model_race_pairs")==4*len(rows) and
         tuple(data.get("model_ids",[]))==MODELS,
         "COHORT_CARDINALITY_OR_FOUR_MODELS_INVALID")
    seen=set()
    counts=Counter()
    for r in rows:
        need(type(r) is dict and
             set(r)=={"race_id","venue","race_no","venue_code",
                      "prediction_expected_models"} and
             type(r["venue"]) is str and r["venue"] and
             type(r["race_no"]) is int and 1<=r["race_no"]<=12 and
             type(r["venue_code"]) is str and
             re.fullmatch(r"\d{2}",r["venue_code"]) and
             r["prediction_expected_models"]==4,
             "INVALID_EVENT_RACE_COHORT_ROW")
        expected=date.replace("-","")+r["venue_code"]+f"{r['race_no']:02d}"
        need(r["race_id"]==expected and expected not in seen,
             "COHORT_DUPLICATED_OR_UNGROUNDED_RACE_ID")
        seen.add(expected)
        counts[r["venue"]]+=1
    need(dict(counts)==data.get("venue_counts") and
         data.get("scheduled_venues")==len(counts),
         "COHORT_VENUES_OR_RACES_DISAGREE")
    return data


def _empty_metrics():
    return {"frozen_races":0,"result_pending_races":0,
            "settled_research_races":0,"unsettled_result_races":0,
            "variable_unselected_races":0,
            "modes":{m:{"active_races":0,"hit_races":0,
                         "reference_stake_yen":0,"reference_paid_yen":0,
                         "mansha_races_evaluable":0,"mansha_races_captured":0,
                         "pre_decided_skips":0} for m in MODES}}


def audit_day(cohort, db_file=None, *, include_private=False):
    """Audit original records. Validated model settlement is reused unchanged.

    db_file is a PRE-EXISTING, temporary, already independently AES-restored
    private SQLite on a trusted runner; this function never copies it out.
    """
    need(type(cohort) is dict and cohort.get("schema")==COHORT,
         "CALL_LOAD_COHORT_FIRST")
    need(tuple(cohort.get("model_ids",[]))==MODELS and
         len(cohort["races"])==cohort["scheduled_races"],
         "COHORT_MODEL_IDENTITIES_CHANGED")
    metrics={mid:_empty_metrics() for mid in MODELS}
    records=[]
    original_count=settled_count=0
    model_total=4*len(cohort["races"])
    no_original=0
    errors=[]
    store=None
    ledger=None
    variable=None
    if db_file is not None:
        db_file=Path(db_file)
        need(db_file.is_file() and not db_file.is_symlink() and
             db_file.stat().st_size>0,"PREEXISTING_PRIVATE_SQLITE_REQUIRED")
        # The existing ledger validates model hashes, source time, complete
        # 210/504 ordered candidates and model identities before evaluation.
        from race_ai.keirin_owner_sqlite import PrivateKeirinStore
        from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
        from race_ai.keirin_variable_integration import PrivateVariableLedger
        from race_ai.four_sport_model_suite import ALL_MODELS
        need(tuple(ALL_MODELS)==MODELS,"EXISTING_FOUR_MODEL_ROSTER_CHANGED")
        store=PrivateKeirinStore(db_file)
        ledger=FourModelRankLedger(store)
        variable=PrivateVariableLedger(store)
    try:
        for source in cohort["races"]:
            rid=source["race_id"]
            row={"race_id":rid,"venue":source["venue"],
                 "race_no":source["race_no"],
                 "original_state":"NOT_FROZEN_VERIFIABLY",
                 "models":{},"result_state":"NOT_EVALUABLE_NO_ORIGINAL"}
            saved=ledger.read_suite(rid) if ledger is not None else None
            if saved is None:
                no_original+=1
                for mid in MODELS:
                    row["models"][mid]={
                        "state":"NOT_RUN_SOURCE_OR_CUTOFF_GATE",
                        "top8":None,"top12":None,"variable_0_to_12":None,
                        "score":None,"hit":None}
                records.append(row)
                continue
            suite=saved["suite"]
            need(tuple(suite["models"])==MODELS,
                 "NOT_THE_EXISTING_FOUR_MODELS")
            original_count+=1
            row["original_state"]="IMMUTABLE_PRE_CUTOFF_FOUR_MODEL_READBACK"
            row["original_source_sha256"]=saved["source_sha256"]
            row["suite_sha256"]=suite["suite_sha256"]
            row["original_persisted_at"]=saved["persisted_at"]
            result=store.db.execute(
                "SELECT revision FROM result_revisions WHERE race_id=? "
                "ORDER BY revision DESC LIMIT 1",(rid,)).fetchone()
            audits=ledger.audit_revision(rid) if result else None
            row["result_state"]=(
                "NO_RESULT_REVISION" if result is None else
                "SETTLED_RESEARCH_NOT_FORMALLY_AUTHENTICATED" if
                audits[MODELS[0]]["result_status"]=="SETTLED_RESEARCH" else
                "UNSETTLED_OR_REFUNDED")
            if audits and row["result_state"]==(
                    "SETTLED_RESEARCH_NOT_FORMALLY_AUTHENTICATED"):
                settled_count+=1
            for mid in MODELS:
                m=suite["models"][mid]
                mstats=metrics[mid]
                mstats["frozen_races"]+=1
                top8=[list(x) for x in m["ordered_top8"]]
                top12=[list(r["combination"]) for r in m["candidates"][:12]]
                need(top8==top12[:8] and len(top8)==8 and len(top12)==12,
                     "EXISTING_MODEL_TOP8_TOP12_DISAGREEMENT")
                selected=variable.selection(rid,mid)
                chosen=None
                if selected:
                    document=selected["selection"]
                    need(document.get("model_prediction_sha256")==
                             m["prediction_sha256"] and
                         document.get("suite_sha256")==suite["suite_sha256"] and
                         document.get("official_cutoff_at")==suite["sales_cutoff_at"] and
                         0<=document.get("pick_count",-1)<=12 and
                         document["pick_count"]==len(document.get("tickets",[])),
                         "VARIABLE_NOT_BOUND_TO_ORIGINAL_PR71_SUITE")
                    chosen=[list(t["triple"]) for t in document["tickets"]]
                else:
                    mstats["variable_unselected_races"]+=1
                if not audits:
                    mstats["result_pending_races"]+=1
                elif row["result_state"].startswith("SETTLED"):
                    mstats["settled_research_races"]+=1
                    a=audits[mid]
                    for mode in MODES:
                        val=a["modes"][mode]
                        st=mstats["modes"][mode]
                        if val["state"]=="REFERENCE_PURCHASE":
                            st["active_races"]+=1
                            st["hit_races"]+=int(val["hit"])
                            st["reference_stake_yen"]+=val["investment_yen"]
                            st["reference_paid_yen"]+=val["payout_yen"]
                        if val["state"]=="PRE_DECIDED_SKIP":
                            st["pre_decided_skips"]+=1
                        if (a["mansha_winning_tickets_count"]>0 and
                                val["mansha_captured"] is not None):
                            st["mansha_races_evaluable"]+=1
                            st["mansha_races_captured"]+=int(
                                val["mansha_captured"])
                else:
                    mstats["unsettled_result_races"]+=1
                status={"state":"MODEL_ORIGINAL_FROZEN",
                        "model_version":m["model_version"],
                        "model_prediction_sha256":m["prediction_sha256"],
                        "top8_count":8,"top12_count":12,
                        "variable_frozen":selected is not None,
                        "variable_ticket_count":len(chosen) if chosen is not None else None,
                        "result_state":audits[mid]["result_status"] if audits else "PENDING"}
                if include_private:
                    status.update(top8=top8,top12=top12,variable_0_to_12=chosen)
                    if audits:
                        status["research_settlement"]=audits[mid]["modes"]
                row["models"][mid]=status
            records.append(row)
    finally:
        if store is not None:store.close()
    result_models={}
    for mid,stat in metrics.items():
        modes={}
        for name,v in stat["modes"].items():
            n=v["active_races"]
            s=v["reference_stake_yen"]
            c=v["mansha_races_evaluable"]
            modes[name]={**v,
                "hit_rate":v["hit_races"]/n if n else None,
                "reference_profit_yen":v["reference_paid_yen"]-s,
                "reference_roi":v["reference_paid_yen"]/s if s else None,
                "mansha_capture_rate":v["mansha_races_captured"]/c if c else None}
        result_models[mid]={**stat,"modes":modes}
    report={"schema":SCHEMA,"event_day_jst":cohort["event_day_jst"],
            "scheduled_races":cohort["scheduled_races"],"scheduled_venues":cohort["scheduled_venues"],
            "expected_model_race_pairs":model_total,
            "frozen_four_model_races":original_count,
            "missing_four_model_original_races":no_original,
            "frozen_model_race_pairs":4*original_count,
            "model_race_pairs_missing":model_total-4*original_count,
            "settled_research_races":settled_count,
            "formally_authenticated_model_race_scores":0,
            "independently_verified_external_cutoff_receipts":0,
            "provider_authorized_training_proven_by_report":False,
            "real_money_wagers":None,
            "missing_model_races_are_not_losses":True,
            "synthetic_forecasts_counted":False,
            "event_day_roster_changes_independently_verified":False,
            "public_release_contains_no_tickets":not include_private,
            "models":result_models,
            "races":records}
    return report


def public_summary(report):
    """Information safe for a Public repository's Actions log."""
    keys=("schema","event_day_jst","scheduled_races",
          "expected_model_race_pairs","frozen_four_model_races",
          "missing_four_model_original_races","frozen_model_race_pairs",
          "model_race_pairs_missing","settled_research_races",
          "formally_authenticated_model_race_scores",
          "independently_verified_external_cutoff_receipts",
          "missing_model_races_are_not_losses","synthetic_forecasts_counted")
    return {**{k:report[k] for k in keys},
            "models":{m:{"frozen_races":stat["frozen_races"],
                         "result_pending_races":stat["result_pending_races"],
                         "settled_research_races":stat["settled_research_races"],
                         "unsettled_result_races":stat["unsettled_result_races"],
                         "variable_unselected_races":stat["variable_unselected_races"],
                         "modes":stat["modes"]}
                      for m,stat in report["models"].items()}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort",required=True)
    parser.add_argument("--db")
    parser.add_argument("--encrypted-cloud-state",action="store_true")
    parser.add_argument("--repo")
    parser.add_argument("--source-root")
    args=parser.parse_args(argv)
    try:
        cohort=load_cohort(args.cohort)
        if args.encrypted_cloud_state:
            need(args.db is None and args.repo and args.source_root,
                 "EXACT_CLOUD_STATE_RESTORE_ARGUMENTS_REQUIRED")
            from scripts import keirin_cloud_pr71_state as cloud
            cloud.require_main_event()
            cloud.check_owner_cipher_consent(args.source_root)
            with TemporaryDirectory(prefix="pr71-78r-review-") as temp:
                checkpoint=Path(temp)/"readback.sqlite3"
                head,inventory=cloud.restore(
                    args.repo,args.source_root,checkpoint)
                report=audit_day(
                    cohort,checkpoint if head is not None else None)
        else:
            report=audit_day(cohort,args.db)
        print(json.dumps(public_summary(report),sort_keys=True,
                         separators=(",",":"),ensure_ascii=False))
        return 0
    except (DayAuditError,ValueError,KeyError,TypeError,sqlite3.Error,
            OSError):
        print('{"schema":"RACE_AI_KEIRIN_DAY_FOUR_MODEL_AUDIT_V1",'
              '"state":"HOLD_INPUT_OR_MODEL_EVIDENCE_UNVERIFIED",'
              '"formal_performance_claimed":false}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
