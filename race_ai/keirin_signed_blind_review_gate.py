"""Verify two blinded review receipts with DISTINCT externally trusted keys.

This extends the EXISTING keirin_blind_rider_holdout_gate.audit callback.
It does not create labels, assign reviewers, train models or self-certify a
human. Reviewer public keys, source identity, preissued challenge and packet
digests MUST originate from a separate owner-controlled trust registry, not
any reviewer JSON or public GitHub PR. In their absence audit stays HOLD.
"""
from __future__ import annotations

import base64
from datetime import datetime
from hashlib import sha256
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .keirin_blind_rider_holdout_gate import (
    checked_proposal,checked_review,digest,
)

SCHEMA="RACE_AI_KEIRIN_SIGNED_BLIND_REVIEW_RECEIPT_V1"
HEX=re.compile(r"^[a-f0-9]{64}$")
REVIEWER=re.compile(r"^[A-Za-z0-9_.-]{5,80}$")


class IndependentSignerError(ValueError):
    pass


def need(ok,code):
    if not ok:
        raise IndependentSignerError(code)


def timestamp(value):
    need(type(value) is str,"MISSING_AWARE_REVIEW_TIME")
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise IndependentSignerError("INVALID_REVIEW_TIME") from None
    need(d.utcoffset() is not None,"INVALID_REVIEW_TIME")
    return d.timestamp()


def sha(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def public_bytes(entry):
    need(type(entry) is dict and set(entry)=={
        "reviewer_id","trusted_public_key_pem","preissued_challenge_sha256",
        "packet_manifest_sha256","identity_attested_out_of_band"},
        "TRUST_REGISTRY_ENTRY_INVALID")
    need(type(entry["reviewer_id"]) is str and
         REVIEWER.fullmatch(entry["reviewer_id"]) is not None and
         entry["identity_attested_out_of_band"] is True and
         sha(entry["preissued_challenge_sha256"]) and
         sha(entry["packet_manifest_sha256"]),
         "REVIEWER_NOT_INDEPENDENTLY_ADMITTED")
    key=entry["trusted_public_key_pem"]
    need(type(key) is bytes and len(key)<=2500,
         "TRUSTED_PUBLIC_KEY_REQUIRED")
    try:
        verified=serialization.load_pem_public_key(key)
    except (TypeError,ValueError):
        raise IndependentSignerError("PUBLIC_REVIEW_SIGNER_KEY_INVALID") from None
    need(isinstance(verified,Ed25519PublicKey),
         "ED25519_EXTERNAL_SIGNER_REQUIRED")
    return verified.public_bytes(
        serialization.Encoding.Raw,serialization.PublicFormat.Raw)


def verify_receipt(review,proposal,receipt,registry_entry):
    """Verify a review SHA signature from an externally authenticated signer.

    Reviewer's own 'independent' boolean or reviewer ID isn't authority.
    The private reviewer key never enters this process or public GitHub.
    """
    checked_proposal(proposal)
    checked_review(review,proposal)
    public=public_bytes(registry_entry)
    need(type(receipt) is dict and set(receipt)=={
        "schema","reviewer_id","race_id","recording_sha256",
        "proposal_sha256","review_sha256","packet_manifest_sha256",
        "preissued_challenge_sha256","signed_at","signature_b64"},
        "SIGNATURE_RECEIPT_SCHEMA_INVALID")
    need(receipt["schema"]==SCHEMA and
         receipt["reviewer_id"]==review["reviewer_id"]==
         registry_entry["reviewer_id"] and
         receipt["race_id"]==proposal["race_id"] and
         receipt["recording_sha256"]==proposal["recording_sha256"] and
         receipt["proposal_sha256"]==proposal["proposal_sha256"] and
         receipt["review_sha256"]==review["review_sha256"] and
         sha(receipt["review_sha256"]) and
         receipt["packet_manifest_sha256"]==
         registry_entry["packet_manifest_sha256"] and
         receipt["preissued_challenge_sha256"]==
         registry_entry["preissued_challenge_sha256"] and
         timestamp(receipt["signed_at"])>=timestamp(review["reviewed_at"]) and
         timestamp(receipt["signed_at"])>timestamp(proposal["frozen_at"]),
         "SIGNED_REVIEW_SOURCE_OR_CHALLENGE_MISMATCH")
    try:
        signed=base64.b64decode(receipt["signature_b64"],validate=True)
        key=serialization.load_pem_public_key(
            registry_entry["trusted_public_key_pem"])
        key.verify(signed,canonical({
            k:v for k,v in receipt.items() if k!="signature_b64"}))
    except (ValueError,TypeError,InvalidSignature):
        raise IndependentSignerError("INDEPENDENT_REVIEW_SIGNATURE_INVALID") from None
    need(len(signed)==64, "INVALID_ED25519_SIGNATURE_LENGTH")
    return public


def verify_two_signed_independent_reviews(
        review_a,review_b,proposal,*,signed_a,signed_b,
        trusted_registry,registry_attestor=None):
    """Callable implementation for the existing callback, not an approval.

    Requires two separately approved public keys and two private signatures.
    A self-created JSON trust registry is NOT authority: an independently
    trusted owner callback must verify actual reviewer-person assignments,
    distinct independently controlled keys and pre-issued challenges.
    This cannot itself prove what the reviewer saw.
    """
    checked_proposal(proposal)
    need(callable(registry_attestor),
         "INDEPENDENT_TRUST_REGISTRY_ATTESTOR_REQUIRED")
    try:
        trust_accepted=registry_attestor(trusted_registry,proposal) is True
    except Exception:
        trust_accepted=False
    need(trust_accepted,
         "REVIEWER_TRUST_REGISTRY_NOT_INDEPENDENTLY_ATTESTED")
    need(type(trusted_registry) is dict and
         set(trusted_registry)=={
             review_a.get("reviewer_id"),review_b.get("reviewer_id")} and
         len(trusted_registry)==2,
         "TWO_DISTINCT_EXTERNAL_REVIEWER_TRUSTS_REQUIRED")
    for r in (review_a,review_b):
        need(type(r) is dict,"REVIEWER_DOCUMENT_INVALID")
    one=verify_receipt(
        review_a,proposal,signed_a,trusted_registry[review_a["reviewer_id"]])
    two=verify_receipt(
        review_b,proposal,signed_b,trusted_registry[review_b["reviewer_id"]])
    need(one!=two,"SAME_REVIEWER_KEY_CANNOT_SIGN_BOTH")
    return True


def make_trusted_callback(*,signed_a=None,signed_b=None,
                          trusted_registry=None,registry_attestor=None):
    """Existing scorer calls callback(a,b,p); missing inputs fail closed."""
    def verify(a,b,p):
        if (signed_a is None or signed_b is None or
            trusted_registry is None or registry_attestor is None):
            return False
        try:
            return verify_two_signed_independent_reviews(
                a,b,p,signed_a=signed_a,signed_b=signed_b,
                trusted_registry=trusted_registry,
                registry_attestor=registry_attestor) is True
        except (IndependentSignerError,ValueError,TypeError,KeyError):
            return False
    return verify
