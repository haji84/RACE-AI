"""Paired prospective research audit for original PR71 vs stage-six-phase shadow.

This is an adapter to independently admitted and frozen originals/results,
not a collector, a model/scorer replacement, evidence of rights, or a claim
of actual wagering. Official truth and protected-Git AES readback must come
from the existing trusted owner runtime, not from caller booleans alone.

Return HOLD (never a loss) for missing results, late forecast, refunds,
unverified source, or unmatched race. No post-hoc changes to old/new picks.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import os
import json

from . import keirin_round_motivation as round_context
from . import keirin_round_six_phase_rank as rounds

SCHEMA = "RACE_AI_KEIRIN_ROUND_PROSPECTIVE_PAIRED_AUDIT_V1"
RESULT_SCHEMA = "RACE_AI_KEIRIN_LICENSED_RESULT_REVISION_V1"
COHORT_SCHEMA = "RACE_AI_KEIRIN_STAGE_AB_PRE_REGISTERED_COHORT_V1"


class PairedAuditError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise PairedAuditError(code)


def _safe_cb(cb, *args):
    if not callable(cb):
        return False
    try:
        return cb(*args) is True
    except Exception:
        return False


def _hold(race_id, code):
    return {"schema":SCHEMA, "race_id":race_id,
            "state":"HOLD", "reason":code,
            "paired_evaluable":False,
            "original":None, "candidate":None,
            "formal_production_improvement_proven":False}


def _score(picks, paid):
    total_stake=100*len(picks)
    received=sum(paid.get(tuple(x),0) for x in picks)
    winner=set(paid)
    return {
        "hit_at_1":tuple(picks[0]) in winner,
        "hit_at_all":any(tuple(x) in winner for x in picks),
        "ticket_count":len(picks), "virtual_stake_yen":total_stake,
        "virtual_payout_yen":received,
        "virtual_profit_yen":received-total_stake,
        "virtual_roi":received/total_stake if total_stake>0 else None,
        "real_wagers_placed":False,
    }


def compare(*, original, candidate, original_receipt, candidate_receipt,
            result, verify_original=None, verify_candidate=None,
            verify_organizer_result=None):
    """Require independently verified, same-race, pre-cutoff frozen pair.

    The callback must check the existing secured Git/SQLite original and the
    actual official source/revision; synthetic lambda True is not proof.
    """
    rid=original.get("race_id") if type(original) is dict else None
    require(type(rid) is str,"ORIGINAL_RACE_ID_REQUIRED")
    if type(candidate) is not dict or candidate.get("race_id") != rid:
        return _hold(rid,"NO_SAME_RACE_TACTICAL_CANDIDATE")
    if candidate.get("state") != "STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY":
        return _hold(rid,"TACTICAL_STAGE_NOT_RANKED")
    if (type(original_receipt) is not dict or
        type(candidate_receipt) is not dict):
        return _hold(rid,"ORIGINAL_AND_SHADOW_FREEZE_RECEIPTS_REQUIRED")
    if not (_safe_cb(verify_original,original,original_receipt) and
            _safe_cb(verify_candidate,candidate,candidate_receipt)):
        return _hold(rid,"INDEPENDENT_ORIGINAL_AND_CANDIDATE_READBACK_REQUIRED")
    require(set(original) == {
        "race_id","input_sha256","baseline_model_id",
        "baseline_prediction_sha256","as_of","official_cutoff_at",
        "starting_order","line_groups","baseline_top12"
    }, "ORIGINAL_SNAPSHOT_FIELDS_INVALID")
    if (candidate["pre_race_input_sha256"] != original["input_sha256"] or
        candidate["parent_prediction_sha256"] != original["baseline_prediction_sha256"] or
        candidate["as_of"] != original["as_of"] or
        candidate["official_cutoff_at"] != original["official_cutoff_at"]):
        return _hold(rid,"ORIGINAL_CANDIDATE_SOURCE_OR_TIME_MISMATCH")
    # The original prediction SHA and candidate file SHA are distinct.
    # candidate freeze writes canonical JSON followed by newline.
    target_sha=sha256(rounds.canonical(candidate)+b"\n").hexdigest()
    if (original_receipt.get("race_id") != rid or
        original_receipt.get("model_prediction_sha256") != original["baseline_prediction_sha256"] or
        candidate_receipt.get("race_id") != rid or
        candidate_receipt.get("private_forecast_file_sha256") != target_sha):
        return _hold(rid,"PREDICTION_RECEIPT_SHA_MISMATCH")
    cutoff=round_context._timestamp(original["official_cutoff_at"])
    at=round_context._timestamp(original["as_of"])
    saved0=round_context._timestamp(original_receipt.get("saved_at"))
    saved1=round_context._timestamp(candidate_receipt.get("saved_at"))
    if not (at<=saved0 and at<=saved1 and
            (cutoff-saved0).total_seconds()>=65 and
            (cutoff-saved1).total_seconds()>=65):
        return _hold(rid,"NOT_BOTH_FORECASTS_FROZEN_PRE_CUTOFF")
    if type(result) is not dict or result.get("race_id")!=rid:
        return _hold(rid,"RESULT_UNOBSERVED_OR_OTHER_RACE")
    if result.get("schema") != RESULT_SCHEMA or result.get("status")!="FINAL_NORMAL":
        return _hold(rid,"NO_FINAL_SETTLED_RESULT")
    if result.get("refund_status")!="NONE":
        return _hold(rid,"REFUND_OR_PARTIAL_SETTLEMENT_UNSUPPORTED")
    published=round_context._timestamp(result.get("source_published_at"))
    observed=round_context._timestamp(result.get("observed_at"))
    if not cutoff < published<=observed:
        return _hold(rid,"RESULT_SOURCE_CLOCK_INVALID")
    if not _safe_cb(verify_organizer_result,result):
        return _hold(rid,"OFFICIAL_RESULT_NOT_INDEPENDENTLY_AUTHENTICATED")
    winners=result.get("winning_triples")
    payouts=result.get("payouts_100yen")
    if type(winners) is not list or type(payouts) is not list or not winners:
        return _hold(rid,"OFFICIAL_PAYOUTS_MISSING")
    starters=set(original["starting_order"])
    paid={}
    for it in payouts:
        require(type(it) is dict and set(it)=={"triple","yen"} and
                rounds._pair(it["triple"],starters) and
                type(it["yen"]) is int and 100<=it["yen"]<=10**9,
                "PAYOUT_ROW_INVALID")
        ticket=tuple(it["triple"])
        require(ticket not in paid,"DUPLICATE_PAYOUT")
        paid[ticket]=it["yen"]
    require(all(rounds._pair(w,starters) for w in winners) and
            set(map(tuple,winners))==set(paid), "WINNING_TRIPLES_AND_PAYOUTS_DIFFER")
    baseline=original["baseline_top12"]
    candidate_picks=[r["cars"] for r in candidate["ranked_top12"]]
    require(bool(candidate_picks) and
            all(rounds._pair(x,starters) for x in candidate_picks) and
            len({tuple(x) for x in candidate_picks})==len(candidate_picks),
            "CANDIDATE_3REN_TAN_INVALID")
    old=_score(baseline,paid)
    new=_score(candidate_picks,paid)
    return {
        "schema":SCHEMA, "state":"PRIVATE_PAIRED_RESEARCH_SETTLED",
        "race_id":rid,"competition":candidate["competition"],
        "round_stage":candidate["round_stage"],
        "source_sha256":round_context.digest(result),
        "old_prediction_sha256":original["baseline_prediction_sha256"],
        "new_prediction_file_sha256":target_sha,
        "paired_evaluable":True,
        "original":old,"candidate":new,
        "hit_at_1_delta":int(new["hit_at_1"])-int(old["hit_at_1"]),
        "hit_at_all_delta":int(new["hit_at_all"])-int(old["hit_at_all"]),
        "virtual_profit_delta_yen":
            new["virtual_profit_yen"]-old["virtual_profit_yen"],
        "no_actual_money_at_risk":True,
        "formal_production_improvement_proven":False,
    }


def make_cohort(*, race_ids, registered_at, race_cutoffs,
                candidate_model_version, original_model_id):
    """Pre-register the entire future denominator BEFORE inspecting results."""
    require(type(race_ids) is list and 1<=len(race_ids)<=1000 and
            len(set(race_ids))==len(race_ids) and
            all(type(x) is str and round_context.ID.fullmatch(x) for x in race_ids),
            "COHORT_FUTURE_RACE_IDS_INVALID")
    when=round_context._timestamp(registered_at)
    require(type(race_cutoffs) is dict and
            set(race_cutoffs)==set(race_ids), "COHORT_OFFICIAL_CUTOFF_MANIFEST_REQUIRED")
    for race_id, deadline in race_cutoffs.items():
        cutoff=round_context._timestamp(deadline)
        require((cutoff-when).total_seconds()>=65,
                "COHORT_MUST_BE_REGISTERED_BEFORE_ALL_CUTOFFS")
    require(type(candidate_model_version) is str and
            1<=len(candidate_model_version)<=80 and
            original_model_id in rounds.KNOWN_PR71,
            "COHORT_MODEL_IDS_REQUIRED")
    value={"schema":COHORT_SCHEMA,"registered_at":registered_at,
           "race_ids":race_ids,
           "race_cutoffs":race_cutoffs,
           "original_model_id":original_model_id,
           "candidate_model_version":candidate_model_version,
           "model_promotion_allowed":False}
    value["cohort_sha256"]=round_context.digest(value)
    return value


def freeze_cohort_once(path, cohort):
    """Create-only private roster; Git SHA/time witness is a separate live gate."""
    require(type(cohort) is dict and cohort.get("schema")==COHORT_SCHEMA and
            cohort.get("cohort_sha256")==round_context.digest({
                k:v for k,v in cohort.items() if k!="cohort_sha256"
            }),"COHORT_SHA_MISMATCH")
    p=Path(path)
    require(p.parent.is_dir() and not p.parent.is_symlink() and
            p.parent.stat().st_mode & 0o077 == 0 and
            not p.exists() and not p.is_symlink(),
            "COHORT_PRIVATE_CREATE_ONCE_REQUIRED")
    raw=round_context.canonical(cohort)+b"\n"
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
               getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as dest:
        dest.write(raw)
        dest.flush()
        os.fsync(dest.fileno())
    require(p.read_bytes()==raw,"COHORT_PRIVATE_READBACK_CHANGED")
    return sha256(raw).hexdigest()


def summarize(cohort, reports):
    """Never exclude a cohort race just because that prediction missed."""
    require(type(cohort) is dict and
            cohort.get("schema")==COHORT_SCHEMA and
            cohort.get("cohort_sha256")==round_context.digest({
                k:v for k,v in cohort.items() if k!="cohort_sha256"
            }),"COHORT_SHA_MISMATCH")
    require(type(reports) is list and len(reports)<=len(cohort["race_ids"]),
            "COHORT_REPORT_SIZE")
    by_race={}
    for item in reports:
        require(type(item) is dict and item.get("schema")==SCHEMA and
                item.get("race_id") in cohort["race_ids"] and
                item["race_id"] not in by_race,"OUT_OF_COHORT_OR_DUPLICATE_REPORT")
        by_race[item["race_id"]]=item
    fields=("hit_at_1","hit_at_all","virtual_stake_yen","virtual_payout_yen")
    groups=defaultdict(lambda:{
        "evaluable":0,
        "original":{key:0 for key in fields},
        "candidate":{key:0 for key in fields},
    })
    held=defaultdict(int)
    for rid in cohort["race_ids"]:
        row=by_race.get(rid)
        if not row or row.get("state")!="PRIVATE_PAIRED_RESEARCH_SETTLED":
            held[row.get("reason","UNREPORTED") if row else "UNREPORTED"]+=1
            continue
        key=(row["competition"],row["round_stage"])
        g=groups[key];g["evaluable"]+=1
        for version in ("original","candidate"):
            for field in fields:
                g[version][field]+=row[version][field]
    overall={
        "total_planned":len(cohort["race_ids"]),
        "paired_evaluable":sum(g["evaluable"] for g in groups.values()),
        "hold_reasons":dict(sorted(held.items())),
        "by_competition_and_round":{},
    }
    for key,g in sorted(groups.items()):
        title=":".join(key)
        for version in ("original","candidate"):
            score=g[version]
            score["hit_at_1_rate"]=score["hit_at_1"]/g["evaluable"]
            score["hit_at_all_rate"]=score["hit_at_all"]/g["evaluable"]
            score["virtual_roi"]=(
                score["virtual_payout_yen"]/score["virtual_stake_yen"]
                if score["virtual_stake_yen"]>0 else None)
        overall["by_competition_and_round"][title]=g
    return {
        "schema":"RACE_AI_KEIRIN_STAGE_PROSPECTIVE_COHORT_AUDIT_V1",
        "cohort_sha256":cohort["cohort_sha256"],
        **overall,
        "future_cohort_registration_independently_attested":False,
        "real_race_improvement_proven":False,
        "actual_wagers_recorded":False,
    }
