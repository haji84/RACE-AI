"""Synthetic private reviewer signature receipts, no actual human review."""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import json
import os
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from race_ai.keirin_signed_blind_review_gate import verify_receipt
from race_ai.keirin_blind_rider_holdout_gate import digest
from scripts.keirin_sign_blind_review_private import (
    SignerError,sign_completed_private_review)
from tests.test_keirin_blind_rider_holdout_gate import get_prediction,review

JST=timezone(timedelta(hours=9))


class OwnerPrivateReviewSignerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        os.chmod(self.root,0o700)
        self.proposal=get_prediction()
        self.review=review(self.proposal,"trusted_reviewerA")
        self.packet={
          "schema":"RACE_AI_KEIRIN_PRIVATE_BLIND_REVIEW_PACKET_V1",
          "reviewer_id":self.review["reviewer_id"],
          "race_id":self.proposal["race_id"],
          "recording_sha256":self.proposal["recording_sha256"],
          "proposal_sha256":self.proposal["proposal_sha256"],
          "does_not_contain_model_predictions_or_rider_labels":True,
          "frames":[{"frame_sha256":x["frame_sha256"]} for x
                    in self.review["frames"]],
        }
        self.key=Ed25519PrivateKey.generate()
        private_key=self.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        self.keypath=self.root/"private_signer.pem"
        self.keypath.write_bytes(private_key)
        os.chmod(self.keypath,0o600)
        self.reviewpath=self.root/"review.json"
        self.manifest=self.root/"packet.json"
        self.output=self.root/"review_signature.json"
        self.challenge="f"*64
        self.save()

    def save(self):
        self.reviewpath.write_text(json.dumps(self.review))
        self.manifest.write_text(json.dumps(self.packet))
        os.chmod(self.reviewpath,0o600)
        os.chmod(self.manifest,0o600)

    def call(self,*,now=None):
        return sign_completed_private_review(
            review_file=self.reviewpath,
            packet_manifest_file=self.manifest,
            private_key_file=self.keypath,
            preissued_challenge_sha256=self.challenge,
            output_file=self.output,
            clock_now=lambda:now if now is not None else
                      datetime(2030,1,15,10,2,tzinfo=JST))

    def trust(self):
        return {
          "reviewer_id":self.review["reviewer_id"],
          "trusted_public_key_pem":self.key.public_key().public_bytes(
               serialization.Encoding.PEM,
               serialization.PublicFormat.SubjectPublicKeyInfo),
          "preissued_challenge_sha256":self.challenge,
          "packet_manifest_sha256":sha256(self.manifest.read_bytes()).hexdigest(),
          "identity_attested_out_of_band":True,
        }

    def test_signature_is_real_ed25519_and_reusable_by_existing_gate(self):
        summary=self.call()
        self.assertTrue(summary["reviewer_signature_created"])
        self.assertFalse(summary["reviewer_identity_independently_verified"])
        signature=json.loads(self.output.read_bytes())
        self.assertEqual(verify_receipt(self.review,self.proposal,
                                        signature,self.trust()),self.key.public_key().public_bytes(
                                            serialization.Encoding.Raw,
                                            serialization.PublicFormat.Raw))
        self.assertEqual(self.output.stat().st_mode&0o077,0)
        with self.assertRaises(FileExistsError):
            self.call()

    def test_signing_incomplete_review_never_becomes_independent_evidence(self):
        self.review["frames"][0]["exhaustive_visible_targets"]=False
        self.review["review_sha256"]=digest({
            k:v for k,v in self.review.items() if k!="review_sha256"})
        self.save()
        with self.assertRaisesRegex(
                SignerError,"ALL_UNBLINDED_FRAME_LABELS_MUST_BE_COMPLETE"):
            self.call()
        self.assertFalse(self.output.exists())

    def test_changed_packet_frame_or_review_holds(self):
        self.packet["frames"][0]["frame_sha256"]="a"*64
        self.save()
        with self.assertRaisesRegex(
                SignerError,"ALL_UNBLINDED_FRAME_LABELS_MUST_BE_COMPLETE"):
            self.call()
        self.packet["frames"][0]["frame_sha256"]=self.review["frames"][0]["frame_sha256"]
        self.review["review_sha256"]="b"*64
        self.save()
        with self.assertRaisesRegex(
                SignerError,"BLIND_COMPLETED_REVIEW_SHA_OR_SOURCE_MISMATCH"):
            self.call()

    def test_before_review_time_is_rejected(self):
        with self.assertRaisesRegex(
                SignerError,"REVIEW_CANNOT_BE_SIGNED_BEFORE_COMPLETION"):
            self.call(now=datetime(2030,1,15,9,59,tzinfo=JST))
        self.assertFalse(self.output.exists())

    def test_private_keys_and_review_files_must_not_be_readable_by_others(self):
        os.chmod(self.keypath,0o644)
        with self.assertRaisesRegex(
                SignerError,"PRIVATE_REVIEW_FILE_MUST_BE_OWNER_ONLY"):
            self.call()
        os.chmod(self.keypath,0o600)
        os.chmod(self.manifest,0o644)
        with self.assertRaisesRegex(
                SignerError,"PRIVATE_REVIEW_FILE_MUST_BE_OWNER_ONLY"):
            self.call()


if __name__=="__main__":
    unittest.main()
