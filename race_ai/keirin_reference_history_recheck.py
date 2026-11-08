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
