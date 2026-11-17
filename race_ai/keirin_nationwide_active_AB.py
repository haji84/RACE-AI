"""All-day KEIRIN active A/B cohort, with optional C and no PR71 dependency.

Keep every scheduled national race in the denominator, including girls, GI,
midnight, six-rider races, and races with missing information. A venue calendar
is NOT a valid forecast, official cutoff or final result. No fallback that
silently turns missing cards into model inputs or marks skipped races as losses.

Source-free core used only after owner-verified out-of-band admission. External
verifiers must attest real files/clock/official source, not caller booleans.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
import re

from . import keirin_available_prediction_audit as ab

SCHEMA = "RACE_AI_KEIRIN_NATIONWIDE_ALL_20261118_AB_PRE_REGISTER_V1"
REPORT_SCHEMA = "RACE_AI_KEIRIN_NATIONWIDE_AB_COVERAGE_RECEIPT_V1"
SUMMARY_SCHEMA = "RACE_AI_KEIRIN_NATIONWIDE_AB_COVERAGE_SUMMARY_V1"
EXPECTED = {
    "81": ("小倉",12), "26": ("西武園",10),
    "44": ("大垣",10), "73": ("小松島",11),
    "75": ("松山",7), "38": ("静岡",11),
    "24": ("宇都宮",9), "74": ("高知",9),
}
RID = re.compile(r"^20[0-9]{10}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
STATE = frozenset({
    "HOLD_MISSING_RACE_INPUT",
    "HOLD_NO_INDEPENDENT_CUTOFF",
    "HOLD_INVALID_OR_UNVERIFIED_A",
    "HOLD_INVALID_OR_UNVERIFIED_B",
    "HOLD_AFTER_DEADLINE",
    "HOLD_SOURCE_CHANGED_OR_CANCELED",
    "A_B_BOTH_FORECASTS_SEALED_PRE_CUTOFF",
    "A_B_INDEPENDENT_CIPHERTEXT_READBACK",
    "A_B_INDEPENDENT_DECRYPTION_READBACK",
    "A_B_SETTLED_OFFICIAL",
})


class NationwideABError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise NationwideABError(code)


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _time(value):
    try:
        return ab.when(value)
    except (ValueError,TypeError,ab.ActiveForecastError):
        raise NationwideABError("AWARE_VERIFIED_SOURCE_TIME_REQUIRED") from None


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _trusted(cb,*args):
    if not callable(cb):
        return False
    try:
        return cb(*args) is True
    except Exception:
        return False


def checked_registry(registry):
    require(type(registry) is dict and registry.get("schema")==SCHEMA and
            registry.get("day_jst")=="2026-11-18" and
            registry.get("scope_race_count")==79 and
            registry.get("scope_venue_count")==8 and
            registry.get("old_four_model_PR71_required") is False and
            registry.get("new_forecasts_generated_by_registration")==0 and
            registry.get("pre_existing_one_race_A_B_reference_count")==1,
            "NATIONWIDE_REGISTRY_ID_SCOPE_OR_BASELINE_INVALID")
    venues=registry.get("venues")
    records=registry.get("records")
    require(type(venues) is list and len(venues)==8 and
            type(records) is list and len(records)==79,
            "NATIONWIDE_MUST_INCLUDE_EIGHT_VENUES_AND_79_RACES")
    actual={}
    for v in venues:
        require(type(v) is dict and
                type(v.get("code")) is str and
                v["code"] in EXPECTED and
                (v.get("name"),v.get("count"))==EXPECTED[v["code"]] and
                v["code"] not in actual,
                "NATIONWIDE_VENUE_ID_OR_RACE_COUNT_MISMATCH")
        actual[v["code"]]=v["count"]
    require(set(actual)==set(EXPECTED),
            "NATIONWIDE_EIGHT_VENUE_INVENTORY_REQUIRED")
    for row in records:
        require(type(row) is dict and
                type(row.get("race_id")) is str and
                RID.fullmatch(row["race_id"]) is not None and
                row["race_id"][:8]=="20261118" and
                row["venue_code"] in EXPECTED and
                row["venue"]==EXPECTED[row["venue_code"]][0] and
                type(row.get("race_no")) is int and
                row["race_id"]=="20261118"+row["venue_code"]+
                            f'{row["race_no"]:02d}' and
                1<=row["race_no"]<=EXPECTED[row["venue_code"]][1],
                "NATIONWIDE_RACE_ID_VENUE_DAY_MISMATCH")
        require(row["organizer_cutoff_independently_verified"] is False and
                row["planned_cutoff_at"] is None and
                row["result"]=="NOT_YET_VERIFIED" and
                row["formal_AB"]=="HOLD_EVIDENCE_PENDING",
                "REGISTRATION_CANNOT_CLAIM_PREDICTIONS_OR_RESULTS")
    expected={f"20261118{venue}{no:02d}"
              for venue,(_,count) in EXPECTED.items()
              for no in range(1,count+1)}
    ids=[row["race_id"] for row in records]
    require(set(ids)==expected and len(ids)==len(set(ids)),
            "NATIONWIDE_RACE_COHORT_INCOMPLETE_OR_DUPLICATE")
    return registry


def register_source_ready_receipt(*,registry, race_id,
                                  inspected_at,
                                  source_input_sha256=None,
                                  source_available_at=None,
                                  official_cutoff_at=None,
                                  verified_field_count=None,
                                  starters=None,
                                  competition=None,
                                  independent_source_admission=None,
                                  independent_cutoff_admission=None):
    """Select verified source-ready live races. Never synthesize A or B."""
    if type(registry) is dict and registry.get("schema")==SCHEMA:
        checked_registry(registry)
        need_ids={row["race_id"] for row in registry["records"]}
    else:
        from . import keirin_dynamic_nationwide_registry as dynamic
        dynamic.checked_day(registry)
        need_ids={row["race_id"] for row in registry["races"]}
    require(race_id in need_ids,"SOURCE_RACE_OUTSIDE_FROZEN_COHORT")
    at=_time(inspected_at)
    summary={
        "schema":REPORT_SCHEMA,"race_id":race_id,
        "state":"HOLD_MISSING_RACE_INPUT",
        "source_input_sha256":None,
        "official_cutoff_at":None,
        "is_model_A_generated":False,"is_model_B_generated":False,
        "eligible_to_attempt_AB":False,
        "C_missing_does_not_block_A_B":True,
        "official_result_verified":False}
    if (not _sha(source_input_sha256) or
        type(source_available_at) is not str or
        type(verified_field_count) is not int or
        verified_field_count<=0 or
        type(starters) is not list or
        len(starters) not in range(5,10) or
        len(starters)!=len(set(starters)) or
        any(type(x) is not int or not 1<=x<=9 for x in starters) or
        competition not in ("CHALLENGE","A1_A2","S","GIRLS","OTHER") or
        not _trusted(independent_source_admission,
                     race_id,source_input_sha256,source_available_at)):
        return summary
    if (type(official_cutoff_at) is not str or
        not _trusted(independent_cutoff_admission,race_id,official_cutoff_at)):
        summary["state"]="HOLD_NO_INDEPENDENT_CUTOFF"
        return summary
    cutoff=_time(official_cutoff_at)
    available=_time(source_available_at)
    if available>at or (cutoff-at).total_seconds()<65:
        summary["state"]="HOLD_AFTER_DEADLINE"
        return summary
    summary.update({
        "state":"VERIFIED_SOURCE_READY_FOR_NEW_A_AND_B",
        "source_input_sha256":source_input_sha256,
        "official_cutoff_at":official_cutoff_at,
        "verified_field_count":verified_field_count,
        "starter_count":len(starters),
        "competition":competition,
        "eligible_to_attempt_AB":True})
    return summary


def summarize_all(*,registry, verified_receipts, independent_receipt_reader=None):
    """All 79 are present even when 78 haven't generated predictions."""
    checked_registry(registry)
    require(type(verified_receipts) is list and len(verified_receipts)<=79,
            "NATIONWIDE_RECEIPT_COUNT_EXCEEDS_COHORT")
    indexed={}
    for row in verified_receipts:
        rid=row.get("race_id") if type(row) is dict else None
        require(rid in {p["race_id"] for p in registry["records"]} and
                rid not in indexed and
                row.get("schema")==REPORT_SCHEMA and
                type(row.get("state")) is str,
                "NATIONWIDE_DUPLICATE_OR_INVALID_RACE_RECEIPT")
        indexed[rid]=row
    final=Counter()
    for row in registry["records"]:
        id=row["race_id"]
        if id not in indexed:
            final["HOLD_UNREPORTED"]+=1
        else:
            state=indexed[id]["state"]
            if state!="VERIFIED_SOURCE_READY_FOR_NEW_A_AND_B" and state not in STATE:
                raise NationwideABError("UNADMITTED_NATIONWIDE_RESULT_STATE")
            # A job reporting itself successful is NOT independent proof.
            # The owner-controlled verifier must read original receipts and
            # source/cipher/official-result evidence from another trust path.
            if (state=="VERIFIED_SOURCE_READY_FOR_NEW_A_AND_B" or
                state.startswith("A_B_")) and not _trusted(
                    independent_receipt_reader,indexed[id]):
                final["HOLD_RECEIPT_NOT_INDEPENDENTLY_VERIFIED"]+=1
            elif state=="VERIFIED_SOURCE_READY_FOR_NEW_A_AND_B":
                final["VERIFIED_SOURCE_READY_A_B_NOT_YET_GENERATED"]+=1
            else:
                final[state]+=1
    return {
        "schema":SUMMARY_SCHEMA,
        "cohort_race_count":79,
        "cohort_venue_count":8,
        "pre_existing_seibuen_AB_cipher_source":registry[
            "only_existing_pre_cutoff_Seibuen1R_forecasts_in_git"],
        "reported_races":len(indexed),
        "unreported_races":79-len(indexed),
        "statuses":dict(sorted(final.items())),
        "successful_A_B_generated_claim_requires_independent_cipher_receipts":True,
        "settled_AB_claim_requires_organizer_result_and_actual_cipher_proof":True,
        "unreported_or_held_never_counted_as_miss":True,
        "C_optional":True,
        "PR71_shared_four_models_required":False,
    }
