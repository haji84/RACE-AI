"""Fixture-only independent-key tests, NOT two actual human review receipts."""
from __future__ import annotations

import base64
from copy import deepcopy
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from race_ai.keirin_blind_rider_holdout_gate import audit
from race_ai.keirin_signed_blind_review_gate import (
    SCHEMA,canonical,make_trusted_callback,
    verify_two_signed_independent_reviews,IndependentSignerError,
)
from tests.test_keirin_blind_rider_holdout_gate import get_prediction,review


def prepare(*,same_key=False):
    p=get_prediction()
    a=review(p,"reviewer_alpha")
    b=review(p,"reviewer_beta")
    signer_a=Ed25519PrivateKey.generate()
    signer_b=signer_a if same_key else Ed25519PrivateKey.generate()
    trust={}
    receipts=[]
    for i,(r,signer) in enumerate(((a,signer_a),(b,signer_b))):
        public=signer.public_key().public_bytes(
            serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        packet=f"{i+1}"*64
        challenge=f"{i+3}"*64
        trust[r["reviewer_id"]]={
            "reviewer_id":r["reviewer_id"],
            "trusted_public_key_pem":public,
            "preissued_challenge_sha256":challenge,
            "packet_manifest_sha256":packet,
            "identity_attested_out_of_band":True,
        }
        body={
            "schema":SCHEMA,
            "reviewer_id":r["reviewer_id"],
            "race_id":p["race_id"],
            "recording_sha256":p["recording_sha256"],
            "proposal_sha256":p["proposal_sha256"],
            "review_sha256":r["review_sha256"],
            "packet_manifest_sha256":packet,
            "preissued_challenge_sha256":challenge,
            "signed_at":"2030-01-15T10:01:00+09:00",
        }
        body["signature_b64"]=base64.b64encode(
            signer.sign(canonical(body))).decode("ascii")
        receipts.append(body)
    return p,a,b,trust,*receipts


class SignedBlindReviewTrustedInputs(unittest.TestCase):
    def test_two_distinct_keys_with_matching_receipts_allow_synthetic_gate(self):
        p,a,b,t,sa,sb=prepare()
        cb=make_trusted_callback(signed_a=sa,signed_b=sb,trusted_registry=t)
        self.assertTrue(cb(a,b,p))
        result=audit(
            p,a,b,
            original_video_verifier=lambda _:True,
            freeze_receipt_verifier=lambda _:True,
            holdout_lineage_verifier=lambda _:True,
            reviewer_receipt_verifier=cb)
        self.assertEqual(result["status"],
                         "TWO_REVIEW_JERSEY_COLOR_REGION_DETECTION_ADMITTED")
        self.assertEqual(result["true_positive_region_boxes"],2)
        self.assertFalse(result["official_phase_score_updated"])
        self.assertFalse(result["training_or_model_weights_modified"])
        self.assertIsNone(result["digit_OCR_accuracy_pct"])
        self.assertIsNone(result["confirmed_rider_person_ID_accuracy_pct"])

    def test_two_keys_registered_to_same_signer_are_rejected(self):
        p,a,b,t,sa,sb=prepare(same_key=True)
        cb=make_trusted_callback(signed_a=sa,signed_b=sb,trusted_registry=t)
        self.assertFalse(cb(a,b,p))
        result=audit(
            p,a,b,
            original_video_verifier=lambda _:True,
            freeze_receipt_verifier=lambda _:True,
            holdout_lineage_verifier=lambda _:True,
            reviewer_receipt_verifier=cb)
        self.assertEqual(result["status"],"HOLD_INDEPENDENT_GROUND_TRUTH_UNVERIFIED")
        self.assertIsNone(result["independent_region_detection_precision_pct"])

    def test_missing_or_untrusted_reviewers_cannot_be_replaced_by_model_flags(self):
        p,a,b,t,sa,sb=prepare()
        self.assertFalse(make_trusted_callback()(a,b,p))
        bad=deepcopy(t)
        bad["reviewer_alpha"]["identity_attested_out_of_band"]=False
        self.assertFalse(make_trusted_callback(
            signed_a=sa,signed_b=sb,trusted_registry=bad)(a,b,p))
        bad=deepcopy(t)
        bad["reviewer_beta"]["trusted_public_key_pem"]=b"not a key"
        self.assertFalse(make_trusted_callback(
            signed_a=sa,signed_b=sb,trusted_registry=bad)(a,b,p))

    def test_review_tampering_after_approval_causes_signature_hold(self):
        p,a,b,t,sa,sb=prepare()
        q=deepcopy(sa)
        q["review_sha256"]="f"*64
        cb=make_trusted_callback(signed_a=q,signed_b=sb,trusted_registry=t)
        self.assertFalse(cb(a,b,p))
        q=deepcopy(sa)
        q["signed_at"]="2030-01-15T10:02:00+09:00"
        cb=make_trusted_callback(signed_a=q,signed_b=sb,trusted_registry=t)
        self.assertFalse(cb(a,b,p))
        q=deepcopy(sa)
        q["signature_b64"]=base64.b64encode(b"\x00"*64).decode("ascii")
        cb=make_trusted_callback(signed_a=q,signed_b=sb,trusted_registry=t)
        self.assertFalse(cb(a,b,p))

    def test_packet_and_preissued_challenge_cannot_be_changed(self):
        p,a,b,t,sa,sb=prepare()
        for changed in ("packet_manifest_sha256","preissued_challenge_sha256"):
            q=deepcopy(sa)
            q[changed]="a"*64
            with self.subTest(field=changed):
                cb=make_trusted_callback(signed_a=q,signed_b=sb,trusted_registry=t)
                self.assertFalse(cb(a,b,p))

    def test_signature_before_review_is_rejected_even_if_cryptographically_valid(self):
        p,a,b,t,sa,sb=prepare()
        sa["signed_at"]="2030-01-15T09:59:00+09:00"
        self.assertFalse(make_trusted_callback(
            signed_a=sa,signed_b=sb,trusted_registry=t)(a,b,p))

    def test_trusted_registry_is_not_taken_from_review_json(self):
        p,a,b,t,sa,sb=prepare()
        a["trusted_public_key_pem"]=t[a["reviewer_id"]]["trusted_public_key_pem"]
        self.assertFalse(make_trusted_callback(
            signed_a=sa,signed_b=sb,trusted_registry=t)(a,b,p))


if __name__=="__main__":
    unittest.main()
