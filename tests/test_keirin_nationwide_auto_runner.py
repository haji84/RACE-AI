"""Synthetic source bytes and TEST RSA key. Not actual real-race proof."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_auto_generator as generator
from race_ai import keirin_nationwide_auto_storage as storage
from scripts import keirin_nationwide_auto_forecast as runner
from scripts import keirin_nationwide_independent_cipher_readback as reader
from tests.test_keirin_nationwide_auto_generator import fixture

COHORT=(Path(__file__).resolve().parents[1] /
        "docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json")
NOW="2026-11-18T09:01:00+09:00"
RID="202611182601"


def public():
    key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    pem=key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    fp=sha256(key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    return pem,fp


class NationwideRealAutomationCode(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cards=self.root/"cards"
        self.raw=self.root/"raw"
        self.cipher=self.root/"sealed"
        for d in (self.cards,self.raw,self.cipher):
            d.mkdir(mode=0o700)
            d.chmod(0o700)
        self.pem,self.fp=public()
        self.patched=patch.object(storage,"PINNED_OWNER_SPKI_SHA256",self.fp)
        self.patched.start()
        self.addCleanup(self.patched.stop)
        self.registry=json.loads(COHORT.read_text())

    def add_source(self,*,snapshot=None):
        sample=snapshot or fixture()
        for j,receipt in enumerate([
                sample["cutoff_source"],*sample["source_pages"]]):
            raw=(f"<html><body>FAKE SOURCE {j} {RID}</body></html>").encode()
            digest=sha256(raw).hexdigest()
            receipt["bytes_sha256"]=digest
            (self.raw/(digest+".html")).write_bytes(raw)
        (self.cards/(RID+".json")).write_text(
            json.dumps(sample,ensure_ascii=False),encoding="utf-8")
        return sample

    def run_it(self,**kwargs):
        x={
            "registry":self.registry,
            "private_racecards_dir":self.cards,
            "raw_pages_dir":self.raw,
            "private_cipher_dir":self.cipher,
            "owner_public_key_pem":self.pem,
            "clock":lambda:datetime.fromisoformat(NOW),
        }
        x.update(kwargs)
        return runner.run_cycle(**x)

    def test_79_missing_inputs_are_sanitized_NO_FORECAST_not_losses(self):
        out=self.run_it()
        self.assertEqual(out["registered_races"],79)
        self.assertEqual(out["A_generated"],0)
        self.assertEqual(out["B_generated"],0)
        self.assertEqual(out["statuses"],{"NO_FORECAST_INPUT_MISSING":79})

    def test_one_real_automatic_source_bound_AB_sealed_and_78_hold(self):
        self.add_source()
        out=self.run_it()
        self.assertEqual(out["registered_races"],79)
        self.assertEqual(out["A_generated"],1)
        self.assertEqual(out["B_generated"],1)
        self.assertEqual(out["same_job_sealed"],1)
        self.assertEqual(out["statuses"]["NO_FORECAST_INPUT_MISSING"],78)
        self.assertEqual(out["statuses"][
            "A_B_PRIVATE_CIPHER_CREATED_SAME_JOB_SHA_MATCH"],1)
        filename=self.cipher/(RID+".sealed.json")
        self.assertTrue(filename.is_file())
        self.assertEqual(filename.stat().st_mode&0o777,0o600)
        self.assertEqual(out["organizer_results_scored"],0)
        self.assertNotIn("ranked_tickets",json.dumps(out))
        self.assertFalse(out["source_provider_access_verified"])

    def test_second_runner_cipher_check_not_RSA_decryption(self):
        self.add_source()
        report=self.run_it()
        out=reader.verify(producer_report=report,cipher_dir=self.cipher)
        self.assertEqual(out["registered_races"],79)
        self.assertEqual(out["independent_cipher_file_shas_ok"],1)
        self.assertFalse(out["RSA_private_decryption_verified"])
        self.assertEqual(out["statuses"]["HOLD_NO_CIPHER_TO_VERIFY"],78)
        self.assertEqual(out["statuses"][
            "INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK"],1)

    def test_no_second_runner_receipt_if_cipher_changed(self):
        self.add_source()
        report=self.run_it()
        doc=self.cipher/(RID+".sealed.json")
        doc.write_bytes(doc.read_bytes()+b"tampered")
        out=reader.verify(producer_report=report,cipher_dir=self.cipher)
        self.assertEqual(out["independent_cipher_file_shas_ok"],0)
        self.assertEqual(out["statuses"]["HOLD_INDEPENDENT_CIPHER_SHA_MISMATCH"],1)

    def test_raw_html_missing_or_tampered_prevents_generation(self):
        sample=self.add_source()
        digest=sample["source_pages"][0]["bytes_sha256"]
        (self.raw/(digest+".html")).unlink()
        out=self.run_it()
        self.assertEqual(out["same_job_sealed"],0)
        self.assertEqual(out["A_generated"],0)
        self.assertIn("HOLD_OWNER_RAW_SOURCE_BYTES_MISSING",out["statuses"])

    def test_does_not_create_late_forecast(self):
        self.add_source()
        late=self.run_it(clock=lambda:datetime.fromisoformat(
            "2026-11-18T11:59:15+09:00"))
        self.assertEqual(late["same_job_sealed"],0)
        self.assertEqual(late["A_generated"],0)
        self.assertTrue(any("TOO_CLOSE" in s for s in late["statuses"]))

    def test_file_already_exists_never_overwrites(self):
        self.add_source()
        once=self.run_it()
        path=self.cipher/(RID+".sealed.json")
        original=path.read_bytes()
        again=self.run_it()
        self.assertEqual(once["same_job_sealed"],1)
        self.assertEqual(again["same_job_sealed"],0)
        self.assertEqual(original,path.read_bytes())
        self.assertIn(
            "HOLD_CREATE_ONCE_EXISTING_CIPHER_REQUIRES_READBACK",again["statuses"])

    def test_partial_unnamed_rider_mark_not_assumed(self):
        s=self.add_source()
        s["riders"][3].pop("mark_rank")
        (self.cards/(RID+".json")).write_text(json.dumps(s))
        out=self.run_it()
        self.assertEqual(out["A_generated"],0)
        self.assertIn("HOLD_RIDER_FACTS_INCOMPLETE",out["statuses"])

    def test_unmarked_athletes_supported_not_made_up_ordinal_ranks(self):
        s=self.add_source()
        for row in s["riders"][3:]:
            row["mark_rank"]="UNMARKED"
        (self.cards/(RID+".json")).write_text(json.dumps(s))
        out=self.run_it()
        self.assertEqual(out["A_generated"],1)
        self.assertEqual(out["B_generated"],1)

    def test_wrong_race_in_source_fails_as_HOLD(self):
        s=self.add_source()
        s["race_id"]="202611182602"
        (self.cards/(RID+".json")).write_text(json.dumps(s))
        out=self.run_it()
        self.assertEqual(out["A_generated"],0)
        self.assertIn("HOLD_SOURCE_OTHER_RACE_OR_DATE",out["statuses"])


if __name__=="__main__":
    unittest.main()
