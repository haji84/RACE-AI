"""Recheck three owner-private *derived* KEIRIN history snapshots, offline.

This is a research-only cross-file consistency check.  Three derived copies do
NOT supply three independent providers, original source bytes, a trusted
pre-cutoff forecast witness, result revision assurance, or calibration.
Never turn these reference rows into authenticated official Hit@8/ROI.
"""
from __future__ import annotations

from collections import Counter
import math
import re

SCHEMAS=(
    "RACE_AI_KEIRIN_20261104_1520_ONE_CYCLE_INCREMENT_RESEARCH_V1",
    "keirin.round11.research_delta.v1",
    "keirin_research_once_v1",
)
ID=re.compile(r"^20[0-9]{10}$")


class HistoryRecheckError(ValueError):
    pass


def _need(test, reason):
    if not test:
        raise HistoryRecheckError(reason)


def _rows(document, schema, field):
    _need(type(document) is dict and document.get("schema")==schema,
          "HISTORY_SCHEMA_MISMATCH")
    for component in field[:-1]:
        document=document.get(component)
        _need(type(document) is dict, "HISTORY_NESTED_FIELD_MISSING")
    values=document.get(field[-1])
    _need(type(values) is list and 1<=len(values)<=200,
          "HISTORY_RACE_ROWS_REQUIRED")
    out={}
    for row in values:
        _need(type(row) is dict and type(row.get("race_id")) is str
              and ID.fullmatch(row["race_id"])
              and row["race_id"] not in out,
              "HISTORY_INVALID_OR_DUPLICATE_RACE_ID")
        out[row["race_id"]]=row
    return out


def _ticket(value):
    _need(type(value) is str and re.fullmatch(r"[1-9]-[1-9]-[1-9]",value),
          "HISTORY_TICKET_FORMAT_INVALID")
    triple=tuple(int(x) for x in value.split("-"))
    _need(len(set(triple))==3,"HISTORY_TRIFECTA_DUPLICATE_STARTERS")
    return triple


def _payload(row, pick, result, payout, hit):
    tickets=row.get(pick)
    _need(type(tickets) is list and len(tickets)==8,
          "HISTORY_EIGHT_PICKS_REQUIRED")
    pool=[_ticket(t) for t in tickets]
    _need(len(set(pool))==8,"HISTORY_DUPLICATE_PICKS")
    winner=_ticket(row.get(result))
    yen=row.get(payout)
    _need(type(yen) is int and 1<=yen<=1_000_000_000,
          "HISTORY_PAYOUT_INVALID")
    flag=row.get(hit)
    _need(type(flag) is int and flag in (0,1)
          and (winner in pool)==bool(flag),"HISTORY_HIT_MISMATCH")
    return (tuple(pool),winner,yen,flag)


def recheck_derived_references(first, second, third):
    """Cross-file matching only, not third-party official verification.

    Input shape matches previously preserved owner-only 2026-11-03 research
    records. No file is changed or written; no URLs fetched.
    """
    a=_rows(first,SCHEMAS[0],("reference_20261103",
             "all_76_reference_A_from_prior_audit_unmodified"))
    b=_rows(second,SCHEMAS[1],("nov03","rows"))
    c=_rows(third,SCHEMAS[2],("nov03_reference_comparisons_readonly",))
    all_ids=set(a)|set(b)|set(c)
    _need(set(a)==set(b)==set(c),"HISTORY_COVERAGE_MISMATCH")
    n=len(all_ids)
    winners=0
    payout_total=0
    reason_count=Counter()
    for rid in sorted(all_ids):
        one=a[rid]; two=b[rid]; three=c[rid]
        baseline=_payload(one,"A_top8_unmodified","third_party_published_order",
                          "three_trifecta_payout_jpy_per_100_yen","A_research_hit8")
        peer=_payload(two,"baseline_top8","published_trifecta",
                      "published_payout_jpy_per_100","hit8_reference_only")
        third_payload=_payload(three,"top8_reference_unchanged",
                               "published_result_3rentan","payout_per_100_yen",
                               "research_hit_at8")
        _need(baseline==peer==third_payload,"HISTORY_DERIVED_RECORDS_DISAGREE")
        _need(one.get("official_final_organizer_verified") is False
              and one.get("independent_external_timestamp_receipt_verified") is False
              and two.get("official_revisions_refunds_cancelations_checked") is False
              and two.get("independent_predeadline_receipt_verified") is False
              and three.get("organizer_official_result_independently_verified") is False
              and three.get("independently_issued_pre_cutoff_freeze_proof_available") is False,
              "HISTORY_CANNOT_PROMOTE_UNVERIFIED_EVIDENCE")
        tickets,winning,paid,hit=baseline
        winners+=hit
        payout_total+=paid if hit else 0
        if hit:
            reason_count["hit"]+=1
        elif all(ticket[0]!=winning[0] for ticket in tickets):
            reason_count["winner_absent"]+=1
        elif all(ticket[:2]!=winning[:2] for ticket in tickets):
            reason_count["first_second_pair_absent"]+=1
        else:
            reason_count["third_place_absent"]+=1
    money=n*800
    return {
        "schema":"RACE_AI_KEIRIN_DERIVED_REFERENCES_RECHECK_V1",
        "scope":"DERIVED_PUBLISHED_RESEARCH_NOT_INDEPENDENT",
        "matched_derived_records":n,
        "cross_file_disagreements":0,
        "reference_hits":winners,
        "reference_misses":n-winners,
        "reference_hit_rate":winners/n,
        "reference_investment_yen":money,
        "reference_payout_yen":payout_total,
        "reference_profit_yen":payout_total-money,
        "reference_roi":payout_total/money,
        "selection_only_miss_counts":dict(sorted(reason_count.items())),
        "independent_original_forecast_sha_verified":False,
        "independent_pre_cutoff_witness_verified":False,
        "official_result_all_revisions_verified":False,
        "refund_cancellation_entire_period_verified":False,
        "all_history_variable_0_to_12_picks_available":False,
        "model_probability_calibrated":False,
        "formal_hit_rate":None,
        "formal_return_rate":None,
        "actual_purchase_profit_yen":None,
        "valid_for_model_promotion":False,
    }


def recheck_original_saved_baseline_against_published(earliest, published):
    """Recheck saved *historical* Top8 against later research result records.

    Original prediction source core is still absent; this verifies the
    immutable 76-row Top8 reference fingerprint against the earliest owner
    ledger, NOT an independent pre-cutoff forecast receipt. No web I/O.
    Full Top12/variable 0..12 cannot be derived from only Top8.
    """
    from hashlib import sha256
    _need(type(earliest) is dict and type(published) is dict
          and earliest.get("prediction_origin") ==
            "conversation-generated reference, not official sealed"
          and earliest.get("results_status") == "NOT_VERIFIED"
          and earliest.get("source_version") ==
            "20261103-am-reference-v1"
          and earliest.get("date_jst") == "2026-11-03"
          and published.get("forecast_file_verified") is False
          and published.get("formal_hits") is None,
          "ORIGINAL_REFERENCE_STATUS_NOT_TRUSTED")
    original=earliest.get("races")
    results=published.get("races")
    _need(type(original) is list and type(results) is list
          and 1 <= len(original) <= 200 and
          len(original) == len(results), "ORIGINAL_REFERENCE_COVERAGE_GAP")
    old={}
    line_parts=[]
    for row in original:
        _need(type(row) is dict and type(row.get("id")) is str
              and ID.fullmatch(row["id"]) and row["id"] not in old,
              "ORIGINAL_REFERENCE_DUPLICATE_ID")
        picks=row.get("baseline_top8")
        _need(type(picks) is list and len(picks)==8 and
              len({_ticket(t) for t in picks})==8,
              "ORIGINAL_REFERENCE_TOP8_INVALID")
        probs=row.get("baseline_probabilities_unvalidated")
        _need(type(probs) is list and len(probs)==8 and
              all(type(v) in (int,float) and math.isfinite(v)
                  and 0 <= v <= 1 for v in probs),
              "ORIGINAL_REFERENCE_NOT_SAVED_EIGHT_SCORES")
        old[row["id"]]=row
        line_parts.append(row["id"]+":"+",".join(picks))
    # Preserve original row order; sorting would alter the fixed legacy digest.
    recalculated=sha256("\n".join(line_parts).encode("utf-8")).hexdigest()
    _need(type(published.get("fallback_sha256")) is str and
          recalculated == published["fallback_sha256"],
          "ORIGINAL_REFERENCE_FALLBACK_SHA_MISMATCH")
    updated={}
    for row in results:
        _need(type(row) is dict and type(row.get("race_id")) is str
              and row["race_id"] in old and row["race_id"] not in updated,
              "PUBLISHED_REFERENCE_DUPLICATE_OR_UNMATCHED")
        updated[row["race_id"]]=row
    _need(set(updated)==set(old),"PUBLISHED_REFERENCE_COVERAGE_DIFFERENT")
    hits=mansha=mansha_hit=return_yen=0
    for rid,row in old.items():
        result=updated[rid]
        tickets=row["baseline_top8"]
        _need(result.get("ordered_top8")==tickets
              and result.get("official_organizer_checked") is False
              and result.get("refund_and_revision_checked") is False,
              "PUBLISHED_REFERENCE_CHANGED_OR_UNVERIFIED_FLAGS")
        win=result.get("provider_trifecta")
        _ticket(win)
        paid=result.get("payout_yen_per_100")
        _need(type(paid) is int and 1<=paid<=1_000_000_000,
              "PUBLISHED_REFERENCE_PAYOUT_INVALID")
        captured=win in tickets
        _need(result.get("hit8_research") == int(captured),
              "PUBLISHED_REFERENCE_HIT_FLAG_CHANGED")
        hits+=captured
        mansha+=(paid>=10000)
        mansha_hit+=(captured and paid>=10000)
        if captured:
            return_yen+=paid
    total=len(old)
    spent=total*800
    return {
        "schema":"RACE_AI_KEIRIN_SAVED_HISTORICAL_BASELINE_REPLAY_V1",
        "scope":"OWNER_REFERENCE_ONLY_NOT_PROSPECTIVE_FORMAL",
        "source_version":earliest["source_version"],
        "baseline_record_count":total,
        "fallback_pre_result_top8_sha256":recalculated,
        "fallback_sha_recomputed_and_equal":True,
        "matched_published_result_rows":len(updated),
        "source_full_original_file_verified":False,
        "independent_pre_cutoff_all_races_verified":False,
        "third_party_result_match_crosschecked_by_this_function":False,
        "top8_hits":hits,"top8_hit_rate":hits/total,
        "mansha_races":mansha,"mansha_top8_captured":mansha_hit,
        "mansha_capture_rate":mansha_hit/mansha if mansha else None,
        "top12_hit_rate":None,
        "variable_pick_hit_rate":None,
        "reference_investment_yen":spent,
        "reference_return_yen":return_yen,
        "reference_profit_yen":return_yen-spent,
        "reference_roi":return_yen/spent,
        "formal_hit_rate":None,"formal_roi":None,
        "actual_purchase_profit_yen":None,
        "new_model_trained_on_results":False,
        "valid_for_model_promotion":False,
    }
