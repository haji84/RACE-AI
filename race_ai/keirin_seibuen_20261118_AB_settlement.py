"""Owner-private real A/B settlement for pre-cutoff Seibuen1R forecasts.

Read the public Git SHA-pinned AES ciphertext, decrypt with the already-held
owner RSA private key only OUTSIDE the public repository, and compare only
after a trusted external verifier attests the result and actual cutoff.
This is research. Synthetic callbacks never establish an independent source.
No provider GET, wagering, model training or public plaintext output.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import base64
import json
import os
import zlib

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import keirin_available_prediction_audit as audit

SHA_FILE="8f9d79a4879353fd863d070535e7c4e0d7e171d1529d08d3813de38fd687be01"
COHORT_SHA="6305a4b97dfadc0e58d1206358754a8b500c459f487f9e34f7dd0a85a6600d9f"
COMMIT="5b4abe91cacfc13a876648e51b8f90fb9b086dc6"
COMMIT_AT="2026-11-18T06:55:57+09:00"
RID="202611182601"
SCHEMA="RACE_AI_KEIRIN_OWNER_1R_AB_ACTUAL_SETTLEMENT_V1"


class SealedSettlementError(ValueError):
    pass


def need(ok,code):
    if not ok:
        raise SealedSettlementError(code)


def h(b):
    return sha256(b).hexdigest()


def _original_record_hash(x):
    return h(audit.canonical(x)+b"\n")


def _verified(cb,*args):
    if not callable(cb):
        return False
    try:
        return cb(*args) is True
    except Exception:
        return False


def decode_owner_sealed(*, raw_cipher,owner_RSA_private_pem):
    """No file or secret is ever written; only trusted caller holds plaintext."""
    need(type(raw_cipher) is bytes and h(raw_cipher)==SHA_FILE,
         "GITHUB_CIPHER_COMMIT_BYTES_MISMATCH")
    try:
        manifest=json.loads(raw_cipher)
        key=serialization.load_pem_private_key(owner_RSA_private_pem,password=None)
    except (ValueError,TypeError):
        raise SealedSettlementError("RSA_PRIVATE_KEY_OR_CIPHER_JSON_INVALID") from None
    pub=key.public_key().public_bytes(
        serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    need(h(pub)==manifest["rsa_public_key_spki_sha256"],
         "OWNER_RSA_KEY_FINGERPRINT_MISMATCH")
    need(manifest["race_id"]==RID and manifest["cohort_sha256"]==COHORT_SHA and
         manifest["schema"]=="RACE_AI_KEIRIN_OWNER_AB_DUAL_SEALED_ONE_RACE_V1",
         "FROZEN_ACTUAL_AB_COHORT_MISMATCH")
    parts={}
    for role in ("A","B"):
        section=manifest[role]
        need(section["aad_ascii"]==
             f"RACE_AI_SEIBUEN_AB_20261118_V1|{RID}|{role}|ZLIB",
             "ENCRYPTED_ARM_AAD_MISMATCH")
        try:
            nonce=base64.b64decode(section["aesgcm_nonce_b64"],validate=True)
            cipher=base64.b64decode(section["ciphertext_b64"],validate=True)
            wrap=base64.b64decode(section["rsa_oaep_sha256_wrapped_key_b64"],
                                  validate=True)
            need(len(nonce)==12 and h(cipher)==section["ciphertext_sha256"],
                 "CIPHERTEXT_SHA_OR_NONCE_INVALID")
            aes=key.decrypt(
                wrap,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                  algorithm=hashes.SHA256(),label=None))
            compressed=AESGCM(aes).decrypt(nonce,cipher,
                                             section["aad_ascii"].encode())
            need(h(compressed)==section["compressed_sha256"],
                 "COMPRESSED_BYTES_SHA_INVALID")
            d=zlib.decompressobj()
            payload=d.decompress(compressed,100_000+1)
            need(d.eof and not d.unused_data and not d.unconsumed_tail and
                 len(payload)<=100_000 and
                 h(payload)==section["plaintext_payload_sha256"],
                 "DECRYPTED_PAYLOAD_SHA_OR_BOUNDS_INVALID")
            record=json.loads(payload)
        except (ValueError,TypeError,KeyError,UnicodeError,zlib.error,
                SealedSettlementError):
            raise SealedSettlementError("OWNER_REAL_ARM_AUTHENTICATED_DECRYPTION_FAILED") from None
        need(record.get("race_id")==RID and record.get("role")==role and
             record.get("source_input_sha256")==manifest["source_pre_race_facts_sha256"] and
             record.get("result_observation") is None and
             record.get("not_officially_cutoff_attested") is True,
             "DECRYPTED_AB_LINEAGE_OR_POSTRACE_TAMPER")
        pred=record["original_forecast"]
        arm=record["audit_arm"]
        try:
            audit.checked_arm(arm)
        except (audit.ActiveForecastError,KeyError,TypeError):
            raise SealedSettlementError("DECRYPTED_AB_ARM_NOT_ADMITTED") from None
        need(arm["arm"]==("EXISTING_GENERATED" if role=="A" else "SIX_PHASE") and
             arm["race_id"]==RID and arm["source_document_sha256"]==
                 _original_record_hash(pred) and
             arm["ranked_tickets"]==pred["ranked_tickets"] and
             arm["common_input_sha256"]==record["source_input_sha256"] and
             arm["official_cutoff_at"]==manifest["published_sales_cutoff_at_jst"],
             "DECRYPTED_PREDICTION_AND_RESEARCH_ARM_MISMATCH")
        parts[role]=arm
    return manifest,parts


def score_real(*,raw_cipher,owner_RSA_private_pem,cohort,
               official_result,verify_git_commit_receipt=None,
               verify_official_cutoff=None,verify_official_result=None):
    """Result scoring remains HOLD if independent receipts are absent."""
    audit.checked_cohort(cohort)
    manifest,arms=decode_owner_sealed(
        raw_cipher=raw_cipher,owner_RSA_private_pem=owner_RSA_private_pem)
    need(cohort["cohort_sha256"]==COHORT_SHA and
         cohort["race_ids"]==[RID] and
         cohort["race_cutoffs"][RID]==
             manifest["published_sales_cutoff_at_jst"],
         "AB_COHORT_SOURCE_MISMATCH")
    if not _verified(verify_git_commit_receipt,COMMIT,COMMIT_AT,SHA_FILE):
        return {"schema":SCHEMA,"race_id":RID,"state":"HOLD_GIT_COMMIT_TIME_UNATTESTED",
                "official_outcome_scored":False}
    if not _verified(verify_official_cutoff,cohort,RID):
        return {"schema":SCHEMA,"race_id":RID,"state":"HOLD_OFFICIAL_CUTOFF_UNATTESTED",
                "official_outcome_scored":False}
    if not _verified(verify_official_result,official_result):
        return {"schema":SCHEMA,"race_id":RID,"state":"HOLD_ORGANIZER_FINAL_RESULT_UNVERIFIED",
                "official_outcome_scored":False}
    if (not isinstance(official_result,dict) or
        official_result.get("race_id")!=RID or
        official_result.get("status")!="FINAL_NORMAL" or
        official_result.get("refund_status")!="NONE"):
        return {"schema":SCHEMA,"race_id":RID,"state":"HOLD_RESULT_NOT_FINAL_NORMAL",
                "official_outcome_scored":False}
    win=official_result.get("winning_triples")
    payouts=official_result.get("payouts_100yen")
    need(type(win) is list and len(win)==1 and
         type(win[0]) is list and len(win[0])==3 and
         len(set(win[0]))==3 and
         type(payouts) is list and len(payouts)==1 and
         payouts[0]["triple"]==win[0] and
         type(payouts[0]["yen"]) is int and
         100<=payouts[0]["yen"]<=10**9,
         "OFFICIAL_TRIFECTA_RESULT_FORMAT_INVALID")
    cutoff=audit.when(cohort["race_cutoffs"][RID])
    need(audit.when(official_result["source_published_at"])>cutoff and
         audit.when(official_result["observed_at"])>=
             audit.when(official_result["source_published_at"]),
         "RESULT_TIME_WRONG")
    winner=tuple(win[0])
    scored={}
    for name in ("A","B"):
        tickets=arms[name]["ranked_tickets"]
        hit=next((i for i,x in enumerate(tickets,1) if tuple(x)==winner),None)
        stake=100*len(tickets)
        payout=payouts[0]["yen"] if hit else 0
        scored[name]={
            "hit_at_1":hit==1,"hit_at_all":hit is not None,
            "hit_rank":hit,"stake_100yen_per_ticket_yen":stake,
            "virtual_payout_yen":payout,
            "virtual_roi":payout/stake,
            "no_real_bet_placed":True}
    return {
        "schema":SCHEMA,"state":"RESEARCH_A_B_RESULT_PAIRED",
        "race_id":RID,"winning_3ren_tan":win[0],
        "organizer_result_revision_sha256":h(audit.canonical(official_result)),
        "pre_cutoff_cipher_file_sha256":SHA_FILE,
        "A_existing":scored["A"],"B_six_phase":scored["B"],
        "C_state":"HOLD_NO_INDEPENDENT_FOLLOW_LABELS",
        "official_outcome_scored":True,"formal_accuracy_improvement_proven":False,
        "manual_private_reviewed_not_AUTONOMOUS_GITHUB_ACTIONS":True}
