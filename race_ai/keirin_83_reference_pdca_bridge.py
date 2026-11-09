"""Convert frozen 83R *reference* picks to the EXISTING settlement engine.

This is a source/status adapter only, not a new matcher, model or weight fitter.
Keep outsider research picks, manually frozen owner tickets, original PR71
four models (A) and independent-input four models (B) in separate ledgers.
Do not treat user-reported results as independently certified; do not pretend
a race start is its official betting cutoff. No raw GET, bets or rewriting.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re

from .keirin_pr71_four_model_rank import _payout_modes
from .keirin_result_delivery import utc

SCHEMA = "RACE_AI_KEIRIN_20261109_8_VENUES_83_RACES_EXTERNAL_REFERENCE_PROJECTIONS_V1"
REPORT = "RACE_AI_KEIRIN_20261109_FROZEN_REFERENCE_PDCA_BRIDGE_V1"
ID = re.compile(r"^20261109[0-9]{4}$")
EXPECTED_VENUES = {
    "青森":7, "弥彦":11, "宇都宮":11, "松戸":12,
    "奈良":9, "高知":12, "松山":9, "武雄":12,
}
REFERENCE_STATUS = "FUTURE_START_CUTOFF_NOT_VERIFIED_RESEARCH_ONLY"
PAST_STATUS = "ALREADY_STARTED_NO_NEW_FORECAST"


class ReferencePDCAError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise ReferencePDCAError(reason)


def ticket(value):
    require(type(value) is str and re.fullmatch(r"[1-9]-[1-9]-[1-9]", value),
            "TRIFECTA_FORMAT_INVALID")
    t = tuple(int(x) for x in value.split("-"))
    require(len(set(t)) == 3, "REPEATED_RIDER_NUMBER")
    return t


def validate_frozen_manifest(doc, *, original_file_sha256=None,
                             original_bytes=None):
    """Pin owner-private original file, never a post-result rewritten copy."""
    require(type(doc) is dict and doc.get("schema")==SCHEMA
            and doc.get("date_jst")=="2026-11-09"
            and doc.get("race_count")==83
            and doc.get("venue_count")==8
            and doc.get("new_reference_forecast_count")==77
            and doc.get("already_started_count")==6
            and doc.get("pr71_4_model_formal_forecasts_count_this_batch")==0
            and doc.get("new_reference_has_independent_third_party_pre_cutoff_witness") is False
            and doc.get("all_future_deadline_times_independently_verified") is False,
            "WRONG_OR_REWRITTEN_83R_RESEARCH_MANIFEST")
    if original_file_sha256 is not None:
        require(type(original_bytes) is bytes and
                sha256(original_bytes).hexdigest() == original_file_sha256,
                "PRIVATE_ORIGINAL_MANIFEST_SHA_MISMATCH")
        require(json.loads(original_bytes) == doc,
                "PRIVATE_ORIGINAL_MANIFEST_BYTES_CONTENT_CHANGED")
    try:
        created=utc(doc["created_at_jst"])
    except (KeyError,ValueError,TypeError) as exc:
        raise ReferencePDCAError("MANIFEST_ORIGINAL_TIMESTAMP_UNVERIFIED") from exc
    rows=doc.get("rows")
    require(type(rows) is list and len(rows)==83,
            "83R_COMPLETE_ROSTER_REQUIRED")
    status=Counter()
    venues=Counter()
    seen=set()
    for row in rows:
        require(type(row) is dict and ID.fullmatch(row.get("race_id","")) and
                row["race_id"] not in seen and row.get("venue") in EXPECTED_VENUES and
                type(row.get("race_no")) is int and
                row["race_no"]>=1 and row["race_no"]<=EXPECTED_VENUES[row["venue"]],
                "BAD_REFERENCE_RACE_ID_OR_VENUE")
        seen.add(row["race_id"])
        venues[row["venue"]]+=1
        state=row.get("status_at_batch_creation")
        require(state in (REFERENCE_STATUS,PAST_STATUS),
                "UNSUPPORTED_REFERENCE_PROVENANCE")
        status[state]+=1
        require(row.get("pr71_models_executed") is False and
                row.get("original_4_model_output_not_claimed") is True and
                row.get("official_cutoff_at_jst_verified") is None,
                "REFERENCE_IMPERSONATING_PR71_OR_CUTOFF")
        try:
            start=utc(row["scheduled_start_at_jst"])
        except (ValueError,TypeError,KeyError) as exc:
            raise ReferencePDCAError("UNVERIFIED_START_FORMAT") from exc
        if state == REFERENCE_STATUS:
            require(created < start and
                    row.get("generated_this_batch_ticket_count") in range(1,9)
                    and row.get("preexisting_separately_frozen_reference_tickets") is None
                    and row.get("independent_source_published_at_pre_cutoff_verified") is False,
                    "POST_START_FORECAST_OR_OLD_SOURCE_RECAST")
            candidates=row.get("new_research_reference_tickets")
            require(type(candidates) is list and
                    len(candidates)==row["generated_this_batch_ticket_count"],
                    "FUTURE_REFERENCE_TICKET_SET_MISSING")
            parsed=[ticket(t) for t in candidates]
            require(len(set(parsed))==len(parsed),"DUPLICATE_REFERENCE_COMBINATION")
        else:
            require(created >= start and
                    row.get("new_research_reference_tickets") is None and
                    row.get("generated_this_batch_ticket_count")==0,
                    "ALREADY_STARTED_RACE_RETROFIT")
    require(dict(venues)==EXPECTED_VENUES and
            status[REFERENCE_STATUS]==77 and status[PAST_STATUS]==6 and
            len(seen)==83, "REFERENCE_83R_COVERAGE_MISMATCH")
    return rows


def verify_published_observations(rows):
    """Validate evidence before invoking existing settlement calculations.

    A third-party published result is NOT a separately authenticated official
    organizer result. User-reported results are separately flagged.
    Duplicate submissions are forbidden (not silently double-counted).
    """
    require(type(rows) is list and len(rows)<=83,
            "RESULT_INPUT_LIST_REQUIRED")
    out={}
    for x in rows:
        require(type(x) is dict and set(x)=={
            "race_id", "observed_at", "source_url", "source_tier",
            "status", "refund_status", "winning_triples",
            "payouts_100yen", "official_organizer_independently_authenticated",
        }, "RESULT_WRAPPER_FIELDS_INVALID")
        rid=x["race_id"]
        require(type(rid) is str and ID.fullmatch(rid) and rid not in out,
                "RESULT_DUPLICATE_OR_BAD_RACE_ID")
        try:
            observed=utc(x["observed_at"])
        except (ValueError,TypeError,KeyError) as exc:
            raise ReferencePDCAError("RESULT_TIME_UNVERIFIABLE") from exc
        require(observed>=utc("2026-11-09T00:00:00+09:00")
                and type(x["source_url"]) is str and
                x["source_url"].startswith("https://") and
                x["source_tier"] in ("THIRD_PARTY_PUBLISHED",
                                     "USER_REPORTED") and
                x["official_organizer_independently_authenticated"] is False,
                "UNAUTHENTICATED_OR_MISLABELED_RESULT")
        status=x["status"]
        if status!="FINAL_NORMAL" or x["refund_status"]!="NONE":
            require(status in ("PENDING","CANCELLED","FINAL_NORMAL") and
                    x["refund_status"] in ("UNKNOWN","NONE","PARTIAL","FULL"),
                    "UNSUPPORTED_RESULT_OR_REFUND_STATUS")
            out[rid]=None
            continue
        winners=x["winning_triples"]
        paid=x["payouts_100yen"]
        require(type(winners) is list and len(winners)>0 and
                len(winners)==len(paid), "SETTLED_WINNING_SET_MISSING")
        payout_map={}
        for y in paid:
            require(type(y) is dict and set(y)=={"triple","yen"}
                    and type(y["triple"]) is list and
                    type(y["yen"]) is int and y["yen"]>0,
                    "PAYMENT_ROWS_INVALID")
            t=tuple(y["triple"])
            require(len(t)==3 and all(type(n) is int and 1<=n<=9 for n in t)
                    and len(set(t))==3 and t not in payout_map,
                    "DUPLICATED_OR_BAD_WINNING_TICKET")
            payout_map[t]=y["yen"]
        win={tuple(w) for w in winners if type(w) is list and
             len(w)==3 and len(set(w))==3}
        require(win==set(payout_map) and len(win)==len(winners),
                "PAYOUT_WINNER_MISMATCH")
        out[rid]={"payments":payout_map,"source_tier":x["source_tier"],
                  "observed_at":x["observed_at"],"source_url":x["source_url"]}
    return out


def reference_scoreboard(original, published, *, original_bytes=None,
                         original_sha256=None):
    """Score research references via existing PR71 _payout_modes() only.

    Uses the "variable" mode for each 4-8-point reference: a full original
    Top8 rank universe was NEVER created for outsider reference picks.
    No model A/B records are guessed from this manifest.
    """
    sources=validate_frozen_manifest(
        original, original_file_sha256=original_sha256,
        original_bytes=original_bytes)
    settlements=verify_published_observations(published)
    require(set(settlements).issubset({r["race_id"] for r in sources}),
            "RESULT_NOT_IN_ORIGINAL_83R_MANIFEST")
    output=[]
    venue=Counter()
    count=Counter()
    spent=paid=hit=mansha_count=mansha_hit=0
    for row in sources:
        rid=row["race_id"]
        venue[row["venue"]]+=1
        status=row["status_at_batch_creation"]
        result=settlements.get(rid, "NOT_CHECKED")
        if status==PAST_STATUS:
            category="SEPARATELY_PRE_FROZEN_OR_UNPROVEN_EARLY_REFERENCE"
        elif result=="NOT_CHECKED":
            category="RESULT_NOT_CHECKED"
        elif result is None:
            category="UNSETTLED_OR_REFUND_UNVERIFIED"
        else:
            category="SETTLED_THIRD_PARTY_RESEARCH_ONLY"
        entry={
            "race_id":rid,"venue":row["venue"],"race_no":row["race_no"],
            "reference_class":"NEW_REFERENCE" if status==REFERENCE_STATUS
                              else "EARLIER_ORIGINAL_SEPARATE",
            "state":category,
            "qualifies_as_formal_before_cutoff":False,
            "PR71_original_four_models_in_this_manifest":False,
            "B_distinct_four_models_in_this_manifest":False,
            "reference_tickets":row["new_research_reference_tickets"]
                                if status==REFERENCE_STATUS else None,
            "reference_ticket_count":row["generated_this_batch_ticket_count"]
                                      if status==REFERENCE_STATUS else None,
            "reference_hit":None,
            "reference_investment_yen":None,
            "reference_payout_yen":None,
            "reference_profit_yen":None,
            "reference_roi":None,
            "winning_triple":None,
            "winning_payout_per_100yen":None,
            "mansha_race":None,
            "source_tier":None,
            "source_url":None,
        }
        if category=="SETTLED_THIRD_PARTY_RESEARCH_ONLY":
            payments=result["payments"]
            tickets=[ticket(t) for t in row["new_research_reference_tickets"]]
            # Reuse PR71's SAME standardized staking/settlement arithmetic,
            # but no Top8/Top12/model inference is invented.
            calc=_payout_modes({"candidates":[]},payments,tickets,
                               settled=True)["variable"]
            require(calc["state"]=="REFERENCE_PURCHASE" and
                    calc["picks"]==len(tickets) and
                    calc["investment_yen"]==100*len(tickets),
                    "REUSED_SETTLEMENT_ENGINE_CONTRACT_BROKEN")
            entry.update(
                reference_hit=calc["hit"],
                reference_investment_yen=calc["investment_yen"],
                reference_payout_yen=calc["payout_yen"],
                reference_profit_yen=calc["profit_yen"],
                reference_roi=calc["roi"],
                winning_triple="-".join(str(x) for x in next(iter(payments)))
                               if len(payments)==1 else None,
                winning_payout_per_100yen=next(iter(payments.values()))
                                         if len(payments)==1 else None,
                mansha_race=any(y>=10000 for y in payments.values()),
                source_tier=result["source_tier"],
                source_url=result["source_url"],
            )
            spent+=calc["investment_yen"]
            paid+=calc["payout_yen"]
            hit+=int(calc["hit"])
            mansha_count+=int(entry["mansha_race"])
            mansha_hit+=int(entry["mansha_race"] and calc["mansha_captured"])
        count[category]+=1
        output.append(entry)
    n=count["SETTLED_THIRD_PARTY_RESEARCH_ONLY"]
    require(len(output)==83 and len(set(r["race_id"] for r in output))==83,
            "OUTPUT_83R_COVERAGE_CHANGED")
    return {
        "schema":REPORT,
        "original_manifest_sha256": original_sha256,
        "original_manifest_created_at":original["created_at_jst"],
        "source_reference_type":"OUTSIDER_PUBLISHED_RANK_RESEARCH",
        "race_count":83,
        "new_frozen_reference_candidates":77,
        "early_races_separate_reference_required":6,
        "venue_race_counts":dict(sorted(venue.items())),
        "state_counts":dict(sorted(count.items())),
        "reference_evaluable_published_results":n,
        "reference_hits":hit,
        "reference_misses":n-hit,
        "reference_hit_rate":hit/n if n else None,
        "reference_up_to_8_picks_only":True,
        "not_claiming_8_identical_points_for_each_race":True,
        "reference_investment_yen":spent,
        "reference_payout_yen":paid,
        "reference_profit_yen":paid-spent,
        "reference_roi":paid/spent if spent else None,
        "reference_mansha_results_count":mansha_count,
        "reference_mansha_captured":mansha_hit,
        "reference_mansha_capture_rate":(
            mansha_hit/mansha_count if mansha_count else None),
        "existing_PR71_four_model_formal_hits":None,
        "existing_PR71_four_model_formal_roi":None,
        "distinct_B_four_model_formal_hits":None,
        "paired_original_A_B_races_verified":0,
        "source_first_published_at_before_cutoff_independently_verified":False,
        "organizer_result_revisions_independently_verified":False,
        "formal_Hit8":None,
        "formal_roi":None,
        "actual_wagers_not_claimed":True,
        "observed_results_can_never_rewrite_original_picks":True,
        "rows":output,
    }
