"""Nationwide 79-race candidate execution with independent proof boundaries.

Bring evidence from an already owner-permitted PRIVATE source, run the
source-neutral existing-forecast -> six-phase A/B research engine, then call
the existing owner-private RSA/AES seal interface. This module NEVER fetches
an arbitrary website, invents a winner or treats 79 registrations as 79
forecasts. Outbound reporting contains NO ticket/rider/player bytes.

The C tactical-follow history is optional. The four unfinished shared PR71
models are NEVER an input dependency.
"""
from __future__ import annotations

from . import keirin_nationwide_active_AB as country
from . import keirin_available_prediction_audit as audit

SCHEMA="RACE_AI_KEIRIN_NATIONWIDE_ACTIVE_AB_EXECUTION_V1"


def _hold(rid,code):
    return {"race_id":rid,"state":code,
            "A_generated":False,"B_generated":False,
            "saved_cipher":False,"independent_readback":False,
            "official_result_scored":False,
            "C_state":"HOLD_OPTIONAL_HISTORY"}


def _trusted(fn,*args):
    if not callable(fn):
        return False
    try:
        return fn(*args)
    except Exception:
        return False


def _admitted_generated(arms,rid,input_sha,cutoff):
    if type(arms) is not dict or set(arms)!={"A_existing","B_six_phase"}:
        return False
    try:
        a=arms["A_existing"]
        b=arms["B_six_phase"]
        audit.checked_arm(a)
        audit.checked_arm(b)
        return (
            a["arm"]=="EXISTING_GENERATED" and
            b["arm"]=="SIX_PHASE" and
            a["race_id"]==b["race_id"]==rid and
            a["common_input_sha256"]==b["common_input_sha256"]==input_sha and
            a["official_cutoff_at"]==b["official_cutoff_at"]==cutoff and
            a["historical_follow_history_sha256"] is None and
            b["historical_follow_history_sha256"] is None)
    except (audit.ActiveForecastError,ValueError,TypeError,KeyError):
        return False


def execute_all(*,registry,source_by_race,inspected_at,
                generate_private_AB=None,
                seal_private_AB=None,
                verify_owner_source=None,
                verify_official_cutoff=None,
                verify_independent_cipher=None):
    """Process each fixed race_id exactly once in the registered order.

    Input per race is an owner-private *admitted* source:
      source_sha256,source_available_at,cutoff_at,verified_field_count,
      starters,competition
    Other reader-specific live facts stay in the callback's private context.
    A/B forecast bytes go directly to the private sealer, never to reports.
    """
    country.checked_registry(registry)
    country.require(type(source_by_race) is dict and
                    set(source_by_race).issubset(
                      {r["race_id"] for r in registry["records"]}),
                    "NATIONWIDE_PRIVATE_SOURCE_OUTSIDE_COHORT")
    results=[]
    for race in registry["records"]:
        rid=race["race_id"]
        x=source_by_race.get(rid)
        if type(x) is not dict:
            results.append(_hold(rid,"HOLD_MISSING_RACE_INPUT"))
            continue
        expected_fields={
            "source_sha256","source_available_at","cutoff_at",
            "verified_field_count","starters","competition"}
        if set(x)!=expected_fields:
            results.append(_hold(rid,"HOLD_MALFORMED_OR_UNVERIFIED_SOURCE"))
            continue
        try:
            readiness=country.register_source_ready_receipt(
                registry=registry,race_id=rid,inspected_at=inspected_at,
                source_input_sha256=x["source_sha256"],
                source_available_at=x["source_available_at"],
                official_cutoff_at=x["cutoff_at"],
                verified_field_count=x["verified_field_count"],
                starters=x["starters"],competition=x["competition"],
                independent_source_admission=verify_owner_source,
                independent_cutoff_admission=verify_official_cutoff)
        except (country.NationwideABError,TypeError,KeyError,ValueError):
            results.append(_hold(rid,"HOLD_MALFORMED_OR_UNVERIFIED_SOURCE"))
            continue
        if not readiness["eligible_to_attempt_AB"]:
            results.append(_hold(rid,readiness["state"]))
            continue
        generated=_trusted(generate_private_AB,rid,x)
        if not _admitted_generated(generated,rid,x["source_sha256"],
                                   x["cutoff_at"]):
            results.append(_hold(rid,"HOLD_NO_VALID_GENERATED_A_B"))
            continue
        out=_hold(rid,"A_B_COMPUTED_PRIVATE_NOT_YET_SEALED")
        out.update({"A_generated":True,"B_generated":True,
                    "A_arm_sha256":generated["A_existing"]["arm_digest_sha256"],
                    "B_arm_sha256":generated["B_six_phase"]["arm_digest_sha256"]})
        # Private sealer MUST atomically create two independent AES payloads
        # and time-stamp them in its own trust path.
        sealing=_trusted(seal_private_AB,rid,generated,x)
        if (type(sealing) is not dict or
            set(sealing)!={
                "race_id","A_arm_sha256","B_arm_sha256",
                "A_cipher_sha256","B_cipher_sha256",
                "sealed_at"} or
            sealing.get("race_id")!=rid or
            sealing.get("A_arm_sha256")!=out["A_arm_sha256"] or
            sealing.get("B_arm_sha256")!=out["B_arm_sha256"] or
            not country._sha(sealing.get("A_cipher_sha256")) or
            not country._sha(sealing.get("B_cipher_sha256")) or
            sealing["A_cipher_sha256"]==sealing["B_cipher_sha256"]):
            results.append(out)
            continue
        try:
            at=country._time(sealing["sealed_at"])
            cutoff=country._time(x["cutoff_at"])
            if (cutoff-at).total_seconds()<65:
                out["state"]="HOLD_AFTER_DEADLINE"
                results.append(out)
                continue
        except (country.NationwideABError,TypeError,ValueError):
            out["state"]="HOLD_SEAL_TIME_NOT_AUTHENTICATED"
            results.append(out)
            continue
        out["state"]="A_B_ENCRYPTED_CIPHER_CREATED_READBACK_PENDING"
        out["saved_cipher"]=True
        if _trusted(verify_independent_cipher,rid,sealing) is True:
            out["state"]="A_B_INDEPENDENT_CIPHERTEXT_READBACK"
            out["independent_readback"]=True
        # Independently verified official settlement happens in a SEPARATE
        # postrace job, never inside this before-race preparation.
        results.append(out)
    country.require(len(results)==79 and
                    len({r["race_id"] for r in results})==79,
                    "NATIONWIDE_EXECUTION_DID_NOT_COVER_ALL_RACES")
    counts={}
    for row in results:
        state=row["state"]
        counts[state]=counts.get(state,0)+1
    return {
        "schema":SCHEMA,
        "day_jst":registry["day_jst"],
        "cohort_race_count":79,
        "A_generated":sum(r["A_generated"] for r in results),
        "B_generated":sum(r["B_generated"] for r in results),
        "cipher_created":sum(r["saved_cipher"] for r in results),
        "independent_cipher_readback":sum(r["independent_readback"] for r in results),
        "official_results_settled":0,
        "C_optional_awaiting_real_labels":True,
        "old_four_models_required":False,
        "states":dict(sorted(counts.items())),
        "records":results,
        "no_plaintext_tickets_or_riders_in_output":True,
    }
