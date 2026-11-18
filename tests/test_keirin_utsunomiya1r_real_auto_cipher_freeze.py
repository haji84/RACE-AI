"""REAL immutable Utsunomiya1R encrypted forecast provenance regression.

This test does not decrypt source values, certify official sales-close
instant, or score race results. All bytes were generated and sealed before
the published cutoff in a separate actual GitHub workflow run.
"""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import json
import unittest

from race_ai import keirin_nationwide_auto_storage as seal

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/"docs/evidence/2026-11-18/keirin_utsunomiya1r_real_auto_AB_sealed_v1.json"
RECEIPT=ROOT/"docs/evidence/2026-11-18/keirin_utsunomiya1r_real_auto_AB_source_to_aes_readback_v1.json"
SHA="dffc7303bfb722f75671751cee9a6356258263ec59b630f9dbdc6fc7953b5dfb"
SOURCE="58374408389f6d575e3ff2cb4d605b16fcce9adf4bc3910c42ef1f59b3516f76"


class RealAutoABImmutableEvidence(unittest.TestCase):
    def setUp(self):
        self.raw=FILE.read_bytes()
        self.cipher=json.loads(self.raw)
        self.receipt=json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_real_cipher_bit_exact_permanent_Git_SHA256(self):
        self.assertEqual(len(self.raw),6245)
        self.assertEqual(sha256(self.raw).hexdigest(),SHA)
        self.assertEqual(self.receipt["sealed_envelope_sha256"],SHA)
        self.assertEqual(self.receipt["aes_envelope_bytes"],6245)

    def test_real_cipher_arms_validate_against_RSAPIN_and_captured_source(self):
        seal.validate_cipher(self.cipher)
        self.assertEqual(self.cipher["race_id"],"202611182401")
        self.assertEqual(self.cipher["original_source_sha256"],SOURCE)
        self.assertEqual(self.receipt["actual_pre_race_source_input_sha256"],SOURCE)
        self.assertNotEqual(self.cipher["A"]["ciphertext_sha256"],
                            self.cipher["B"]["ciphertext_sha256"])

    def test_original_frozen_before_published_cutoff_with_no_postrace_label(self):
        sealed=seal.model.when(self.cipher["sealed_at"])
        cutoff=seal.model.when(self.cipher["published_cutoff_at"])
        self.assertGreaterEqual((cutoff-sealed).total_seconds(),65)
        self.assertIs(self.cipher["official_result_included"],False)
        self.assertIs(self.cipher["cross_runner_RSA_decryption_attested"],False)
        self.assertFalse(self.receipt["official_sales_close_instant_independently_verified"])
        self.assertEqual(self.receipt["formal_organizer_result_settlement_count"],0)

    def test_external_independent_SHA_and_local_key_decrypt_are_distinct(self):
        self.assertTrue(self.receipt["independent_GitHub_runner_cipher_SHA_confirmed"])
        self.assertTrue(self.receipt["isolated_second_environment_owner_RSA_AES_authenticated_decryption_confirmed"])
        self.assertTrue(self.receipt["local_private_decryption_raw_plaintext_SHA_A_B_confirmed"])
        self.assertFalse(self.receipt["automated_full_national_completion"])
        self.assertEqual(self.receipt["national_79_races_auto_generated_in_this_run"],1)


if __name__=="__main__":
    unittest.main()
