"""2026-11-18 Seibuen1R actual pre-race owner ciphertext: no plaintext in CI.

This GitHub-hosted runner can verify the genuinely committed encrypted
artifact and prospective cohort, but cannot decrypt the owner-private A/B
forecast. No real pick/official-result accuracy claims from this test.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import base64
import json
import unittest

from race_ai import keirin_available_prediction_audit as research

ROOT=Path(__file__).resolve().parents[1]
SEALED=ROOT/"docs/evidence/2026-11-18/keirin_seibuen1r_AB_sealed_cipher_v1.json"
COHORT=ROOT/"docs/evidence/2026-11-18/keirin_seibuen1r_active_generated_AB_prereg_v1.json"
SEALED_SHA="8f9d79a4879353fd863d070535e7c4e0d7e171d1529d08d3813de38fd687be01"
COHORT_SHA="6305a4b97dfadc0e58d1206358754a8b500c459f487f9e34f7dd0a85a6600d9f"
PUBKEY_SHA="1963d13558d115ce261f224b97d385bd09c65a70c91fb23237f91aa9840bb3a1"


def validate_cipher_envelope(doc):
    if not isinstance(doc,dict) or doc.get("schema")!=(
            "RACE_AI_KEIRIN_OWNER_AB_DUAL_SEALED_ONE_RACE_V1"):
        raise ValueError("AB_CIPHER_WRONG_SCHEMA")
    if (doc.get("race_id")!="202611182601" or
        doc.get("cohort_sha256")!=COHORT_SHA or
        doc.get("rsa_public_key_spki_sha256")!=PUBKEY_SHA or
        doc.get("no_unencrypted_entrant_stats_or_tickets_in_public_git") is not True or
        doc.get("no_official_result_was_used") is not True or
        doc.get("official_cutoff_independent_organizer_proof") is not False or
        doc.get("real_outcome_verified") is not False):
        raise ValueError("AB_CIPHER_SOURCE_STATE_OR_RACE_INVALID")
    cutoff=datetime.fromisoformat(doc["published_sales_cutoff_at_jst"])
    generated=datetime.fromisoformat(doc["generated_at_jst"])
    if (generated >= cutoff or (cutoff-generated).total_seconds()<65 or
        generated < datetime.fromisoformat("2026-11-18T06:50:43+09:00")):
        raise ValueError("AB_CIPHER_NOT_PRE_CUTOFF_GENERATED")
    seen=set()
    for name in ("A","B"):
        row=doc[name]
        if (row.get("encoding")!="zlib-level9-then-AES-256-GCM" or
            row.get("aad_ascii") !=
            f"RACE_AI_SEIBUEN_AB_20261118_V1|202611182601|{name}|ZLIB" or
            len(row.get("plaintext_payload_sha256",""))!=64 or
            len(row.get("compressed_sha256",""))!=64):
            raise ValueError("AB_CIPHER_ARM_SCHEMA")
        try:
            ct=base64.b64decode(row["ciphertext_b64"],validate=True)
            nonce=base64.b64decode(row["aesgcm_nonce_b64"],validate=True)
            rsa=base64.b64decode(
                row["rsa_oaep_sha256_wrapped_key_b64"],validate=True)
        except (ValueError,KeyError):
            raise ValueError("AB_CIPHER_MALFORMED_B64") from None
        if (len(nonce)!=12 or len(rsa)!=384 or len(ct)<=16 or
            sha256(ct).hexdigest()!=row["ciphertext_sha256"]):
            raise ValueError("AB_CIPHER_BYTE_SHA_MISMATCH")
        seen.add((row["aesgcm_nonce_b64"],row["rsa_oaep_sha256_wrapped_key_b64"]))
    if len(seen)!=2:
        raise ValueError("AB_SAME_IV_OR_RSA_WRAPPED_KEY")
    return True


class RealSeibuenABPreCutoffCipher(unittest.TestCase):
    def test_remote_git_file_contents_are_exact_immutable_bytes(self):
        self.assertEqual(sha256(SEALED.read_bytes()).hexdigest(),SEALED_SHA)

    def test_pre_registered_cohort_is_independent_of_unfinished_PR71(self):
        obj=json.loads(COHORT.read_text(encoding="utf-8"))
        research.checked_cohort(obj)
        self.assertEqual(obj["cohort_sha256"],COHORT_SHA)
        self.assertFalse(obj["four_model_baseline_required"])
        self.assertEqual(obj["race_ids"],["202611182601"])

    def test_two_distinct_rsa_aes_gcm_ciphertext_SHA_values(self):
        doc=json.loads(SEALED.read_text(encoding="utf-8"))
        self.assertTrue(validate_cipher_envelope(doc))
        self.assertNotEqual(doc["A"]["ciphertext_sha256"],
                            doc["B"]["ciphertext_sha256"])
        self.assertNotEqual(doc["A"]["plaintext_payload_sha256"],
                            doc["B"]["plaintext_payload_sha256"])

    def test_public_Git_record_does_not_leak_decrypted_picks_or_roster(self):
        raw=SEALED.read_bytes()
        for needle in (b'"ranked_tickets"',b'"entrants"',b'"source_input":',
                       b'"six_phases"',b'"rider_name"',b'BEGIN RSA PRIVATE KEY'):
            self.assertNotIn(needle,raw)

    def test_cryptographic_readback_catches_tampered_encrypted_arm(self):
        doc=json.loads(SEALED.read_text(encoding="utf-8"))
        changed=deepcopy(doc)
        changed["B"]["ciphertext_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"AB_CIPHER_BYTE_SHA_MISMATCH"):
            validate_cipher_envelope(changed)

    def test_not_claiming_independent_AES_decryption_or_official_result(self):
        doc=json.loads(SEALED.read_text(encoding="utf-8"))
        self.assertTrue(doc["no_external_runner_decryption_confirmed"])
        self.assertFalse(doc["real_outcome_verified"])
        self.assertFalse(doc["official_cutoff_independent_organizer_proof"])


if __name__=="__main__":
    unittest.main()
