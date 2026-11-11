"""Consent guards: approving ciphertext never approves plaintext or scraping."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from race_ai.keirin_public_ciphertext_consent import (
    check_public_ciphertext_consent,read_trusted_main_ciphertext_consent,
    ConsentError,CONSENT_PATH,
)

REPO_ROOT=Path(__file__).resolve().parents[1]


class OwnerCiphertextConsentTests(unittest.TestCase):
    def record(self):
        return json.loads((REPO_ROOT/CONSENT_PATH).read_text(encoding="utf-8"))

    def test_actual_owner_approved_scope_accepted_without_live_authority(self):
        result=read_trusted_main_ciphertext_consent(REPO_ROOT)
        self.assertTrue(result["owner_public_ciphertext_consent"])
        self.assertFalse(result["provider_machine_acquisition_rights_verified"])
        self.assertFalse(result["production_archiver_enabled"])
        self.assertFalse(result["independent_signature_present"])

    def test_expanded_publication_or_unauthorized_acquisition_denied(self):
        v=self.record()
        updates={
          "plaintext_publication_allowed":True,
          "private_predictions_plaintext_publication_allowed":True,
          "plaintext_odds_or_rider_data_publication_allowed":True,
          "encryption_key_publication_allowed":True,
          "automatic_wagering_authorized":True,
          "paid_data_contract_authorized":True,
          "automated_unlicensed_data_collection_authorized":True,
          "source_license_requirements_unchanged":False,
          "source_independently_notarized":True,
          "target_branch":"main",
          "target_repository":"other/repo",
          "allowed_material":"all records including plaintext",
          "recorded_on_jst":"2024-01-01",
          "status":"REVOKED",
          "production_mode_activation":"start with no provider"
        }
        for field,value in updates.items():
            with self.subTest(field=field):
                tampered=deepcopy(v)
                tampered[field]=value
                with self.assertRaises(ConsentError):
                    check_public_ciphertext_consent(tampered)

    def test_incomplete_or_duplicated_consent_rejected(self):
        valid=self.record()
        with TemporaryDirectory() as root:
            repo=Path(root)
            f=repo/CONSENT_PATH
            f.parent.mkdir(parents=True)
            with self.assertRaisesRegex(ConsentError,"MISSING"):
                read_trusted_main_ciphertext_consent(repo)
            f.write_text('{"schema":"a","schema":"b"}')
            with self.assertRaises(ConsentError):
                read_trusted_main_ciphertext_consent(repo)
            f.write_text(json.dumps(valid))
            self.assertTrue(read_trusted_main_ciphertext_consent(repo)[
                "owner_public_ciphertext_consent"])
            f.write_text("{}")
            with self.assertRaises(ConsentError):
                read_trusted_main_ciphertext_consent(repo)


if __name__=="__main__":
    unittest.main()
