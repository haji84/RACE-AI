"""Synthetic settlement controls; none of these are actual official race results."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_nationwide_auto_settlement as settle
from tests.test_keirin_nationwide_auto_generator import fixture, AT

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json"
RID = "202611182601"


class NationwideEncryptedABSettlement(unittest.TestCase):
    def setUp(self):
        self.work = TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.root.chmod(0o700)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        self.pub = self.key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        self.pem = self.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        fingerprint = sha256(self.key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        pin = patch.object(storage, "PINNED_OWNER_SPKI_SHA256", fingerprint)
        pin.start()
        self.addCleanup(pin.stop)
        self.registry = json.loads(COHORT.read_text(encoding="utf-8"))
        self.snap = fixture()
        self.forecast = model.generate_A_B(self.snap, generated_at=AT)
        self.file = self.root / (RID + ".sealed.json")
        self.receipt = storage.seal_once(
            snapshot=self.snap, prediction=self.forecast, public_key_pem=self.pub,
            path=self.file, sealed_at="2026-11-18T09:01:05+09:00")
        self.result = {
            "race_id": RID,
            "status": "FINAL_NORMAL",
            "refund_status": "NONE",
            "official_cutoff_at": "2026-11-18T12:00:00+09:00",
            "source_published_at": "2026-11-18T12:30:00+09:00",
            "observed_at": "2026-11-18T12:31:00+09:00",
            "source_url": "https://keirin.jp/pc/race/result",
            "source_sha256": "a" * 64,
            "provider_revision_ref": "test-only-final-v1",
            "winning_triples": [self.forecast["A"]["ranked_tickets"][0]],
            "payouts_100yen": [{
                "triple": self.forecast["A"]["ranked_tickets"][0],
                "yen": 6700}],
        }

    def check(self, *, data=None, result=None, key=None, digest=None,
              origin=True, cutoff=True, final=True):
        return settle.settle_day(
            registry=self.registry,
            sealed_by_race={RID: self.file.read_bytes() if data is None else data},
            expected_sha_by_race={RID: self.receipt["cipher_sha256"]
                                  if digest is None else digest},
            final_results_by_race={RID: self.result if result is None else result},
            owner_private_pem=self.pem if key is None else key,
            independently_verify_immutable_origin=(
                (lambda *args: True) if origin else None),
            independently_verify_official_cutoff=(
                (lambda *args: True) if cutoff else None),
            independently_verify_final_result=(
                (lambda *args: True) if final else None))

    def test_real_cryptography_replay_and_paired_one_of_79_synthetic_score(self):
        envelope, original, starters = settle.decrypt_original_pair(
            raw_cipher=self.file.read_bytes(),
            expected_cipher_sha256=self.receipt["cipher_sha256"],
            owner_private_pem=self.pem)
        self.assertEqual(envelope["race_id"], RID)
        self.assertEqual(starters, set(range(1, 8)))
        self.assertEqual(original["prediction_sha256"],
                         self.forecast["prediction_sha256"])
        result = self.check()
        self.assertEqual(result["registered_races"], 79)
        self.assertEqual(result["paired_A_B_scored"], 1)
        self.assertEqual(result["scorecard"]["not_yet_independently_scored_races"], 78)
        self.assertEqual(result["scorecard"]["A_existing"]["hit_at_1"], 1)
        self.assertEqual(result["scorecard"]["A_existing"]["payout_yen"], 6700)
        self.assertEqual(result["scorecard"]["C_optional"]["eligible"], 0)
        self.assertEqual(result["statuses"][0]["state"],
                         "AB_SETTLED_FROM_INDEPENDENT_RECEIPTS" if
                         result["statuses"][0]["race_id"] == RID else
                         result["statuses"][0]["state"])
        self.assertNotIn("ranked_tickets", json.dumps(result))
        self.assertNotIn("athlete_id", json.dumps(result))
        self.assertFalse(result["formal_accuracy_proven"])

    def test_every_independent_attestation_gate_is_required(self):
        for disabled in ("origin", "cutoff", "final"):
            with self.subTest(disabled=disabled):
                result = self.check(**{disabled: False})
                self.assertEqual(result["paired_A_B_scored"], 0)
                self.assertEqual(result["scorecard"]["A_existing"]["eligible"], 0)
                row = next(x for x in result["statuses"] if x["race_id"] == RID)
                self.assertEqual(row["state"],
                                 "HOLD_UNVERIFIED_CIPHER_CUTOFF_OR_RESULT")

    def test_missing_cipher_or_result_never_becomes_loss(self):
        out = settle.settle_day(
            registry=self.registry,
            sealed_by_race={},
            expected_sha_by_race={},
            final_results_by_race={},
            owner_private_pem=self.pem)
        self.assertEqual(out["paired_A_B_scored"], 0)
        self.assertEqual(out["scorecard"]["not_yet_independently_scored_races"], 79)
        self.assertEqual(out["scorecard"]["A_existing"]["hit_at_all_rate"], None)
        self.assertTrue(all(x["state"] == "HOLD_NO_PRE_CUTOFF_FORECAST"
                            for x in out["statuses"]))

    def test_wrong_key_or_tampered_cipher_is_HOLD_not_a_result(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        pem = other.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        self.assertEqual(self.check(key=pem)["paired_A_B_scored"], 0)
        invalid = self.file.read_bytes() + b"tampered"
        self.assertEqual(self.check(data=invalid)["paired_A_B_scored"], 0)

    def test_cutoff_advance_or_refund_or_wrong_result_is_HOLD(self):
        early = deepcopy(self.result)
        early["official_cutoff_at"] = "2026-11-18T09:01:30+09:00"
        self.assertEqual(self.check(result=early)["paired_A_B_scored"], 0)
        refund = deepcopy(self.result)
        refund["refund_status"] = "PARTIAL"
        self.assertEqual(self.check(result=refund)["paired_A_B_scored"], 0)
        other = deepcopy(self.result)
        other["race_id"] = "202611182602"
        self.assertEqual(self.check(result=other)["paired_A_B_scored"], 0)

    def test_tied_finals_and_multiple_payouts_are_scored_without_double_count(self):
        second = next(t for t in self.forecast["B"]["ranked_tickets"]
                      if t != self.forecast["A"]["ranked_tickets"][0])
        both = deepcopy(self.result)
        both["winning_triples"].append(second)
        both["payouts_100yen"].append({"triple": second, "yen": 4200})
        report = self.check(result=both)
        self.assertEqual(report["paired_A_B_scored"], 1)
        self.assertEqual(report["scorecard"]["A_existing"]["eligible"], 1)
        self.assertGreaterEqual(report["scorecard"]["B_six_phase"]["payout_yen"], 4200)

    def test_outside_national_registry_is_rejected(self):
        with self.assertRaisesRegex(settle.AutoSettlementError,
                                    "OUTSIDE_REGISTERED_DAY"):
            settle.settle_day(
                registry=self.registry, sealed_by_race={"202611189901": b"x"},
                expected_sha_by_race={}, final_results_by_race={},
                owner_private_pem=self.pem)


if __name__ == "__main__":
    unittest.main()
