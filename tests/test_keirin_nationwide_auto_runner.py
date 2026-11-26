"""Synthetic source bytes and TEST RSA key. Not actual real-race proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
        race_id = sample["race_id"]
        for j,receipt in enumerate([
                sample["cutoff_source"],*sample["source_pages"]]):
            raw=(f"<html><body>FAKE SOURCE {j} {race_id}</body></html>").encode()
            digest=sha256(raw).hexdigest()
            receipt["bytes_sha256"]=digest
            (self.raw/(digest+".html")).write_bytes(raw)
        (self.cards/(race_id+".json")).write_text(
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

    def test_winticket_reviewed_history_seals_only_the_conditioned_prediction(self):
        from race_ai import keirin_form_fall_shadow as condition
        from tests.test_keirin_form_history_admission import UP, STEADY, export, interview, result, reviewed_export

        snapshot = self.add_source()
        past = [interview(n, UP if n <= 3 else STEADY) for n in range(1, 7)]
        doc = export(past + [interview(18, UP)],
                     [result(n, 1 if n <= 3 else 7) for n in range(1, 7)])
        load, _ = reviewed_export(self.raw, snapshot, doc)
        report = self.run_it(form_evidence_loader=load)
        row = next(row for row in report["records"] if row["race_id"] == RID)
        self.assertEqual(row["form_fall_shadow_state"], "PRIVATE_CONDITIONED_SHADOW_SEALED")
        self.assertEqual(row["winticket_adjusted_riders"], 1)
        at = datetime.fromisoformat(NOW).astimezone(timezone.utc).isoformat()
        condition.readback_shadow(self.cipher / (RID + ".form.sealed.json"),
            expected_sha=row["form_fall_shadow_file_sha256"],
            expected_baseline_sha=generator.generate_A_B(snapshot, generated_at=at)["prediction_sha256"],
            expected_race=RID)
        self.assertTrue((self.cipher / (RID + ".sealed.json")).exists())
        self.assertNotIn(UP, json.dumps(report, ensure_ascii=False))

    def test_optional_history_checks_happen_after_baseline_and_cannot_block_it(self):
        self.add_source()
        second = fixture()
        second["race_id"] = "202611182602"
        self.add_source(snapshot=second)

        def failed_review(**_):
            self.assertTrue((self.cipher/(RID+".sealed.json")).exists())
            self.assertTrue((self.cipher/(second["race_id"]+".sealed.json")).exists())
            generator.when("0001-01-01T00:00:00+09:00")

        report = self.run_it(form_evidence_loader=failed_review)
        self.assertEqual(report["same_job_sealed"], 2)
        self.assertFalse((self.cipher/(RID+".form.sealed.json")).exists())

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

    def test_fresh_pre_cutoff_confidence_is_saved_privately_with_the_batch_original(self):
        from tests.test_keirin_nationwide_auto_storage import make_key
        from race_ai import keirin_nationwide_auto_settlement as settlement
        self.add_source();key,public,pin=make_key()
        private=key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        ticks=iter(datetime.fromisoformat(NOW)+timedelta(seconds=n) for n in range(10))
        with patch.object(storage,'PINNED_OWNER_SPKI_SHA256',pin):
            report=self.run_it(owner_public_key_pem=public,clock=lambda:next(ticks))
            raw=(self.cipher/(RID+'.sealed.json')).read_bytes()
            manifest,baseline,_,assessment=settlement.decrypt_original_with_assessment(raw_cipher=raw,
                expected_cipher_sha256=sha256(raw).hexdigest(),owner_private_pem=private)
        self.assertIsNotNone(assessment)
        self.assertGreater(generator.when(assessment['assessed_at']),generator.when(baseline['generated_at']))
        self.assertLessEqual(generator.when(assessment['assessed_at']),generator.when(manifest['sealed_at']))
        self.assertNotIn('confidence_assessment',baseline)
        self.assertNotIn('confidence_assessment',json.dumps(report))

    def test_clock_crossing_the_assessment_margin_does_not_seal_an_unassessed_original(self):
        self.add_source()
        times=iter((datetime.fromisoformat(NOW),datetime.fromisoformat('2026-11-18T11:58:56+09:00')))
        report=self.run_it(clock=lambda:next(times))
        self.assertEqual(report['same_job_sealed'],0)
        self.assertEqual(report['A_generated'],0)
        self.assertFalse((self.cipher/(RID+'.sealed.json')).exists())

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


    def add_private_form_source(self, *, broken_sha=False, late=False):
        history = b"<html><body>SYNTHETIC 2026 fall and results only</body></html>"
        sha = sha256(history).hexdigest()
        if not broken_sha:
            (self.raw/(sha+".html")).write_bytes(history)
        source = {
            "schema": "RACE_AI_KEIRIN_PRIVATE_FORM_SUPPLEMENT_V1",
            "race_id": RID,
            "source_pages": [{
                "kind": "PROGRAM",
                "url": "https://example.org/synthetic-result-history",
                "bytes_sha256": sha,
                "captured_at": "2026-11-18T09:04:00+09:00" if late else
                               "2026-11-18T09:00:00+09:00"}],
            "condition_evidence": {
                "schema": "RACE_AI_KEIRIN_RIDER_FORM_FALL_EVIDENCE_V1",
                "as_of": "2026-11-18T09:00:00+09:00",
                "riders": [{
                    "car": 1, "absences": [], "comments": [],
                    "results": [{
                        "race_id": "202611012601",
                        "race_date": "2026-11-01", "status": "FALL_DNF",
                        "place": None, "field_size": 7,
                        "published_at": "2026-11-18T08:30:00+09:00",
                        "source_sha256": sha}]}]}}
        (self.cards/(RID+".form.json")).write_text(
            json.dumps(source), encoding="utf-8")
        return source

    def synthetic_form_loader(self, *, snapshot, raw_pages_dir, captured_at):
        """Test-only stand-in for the separately reviewed original-byte parser.

        This fixture does not establish a real provider or rider identity.
        No production entry point installs this loader.
        """
        return json.loads((self.cards/(RID+".form.json")).read_text())

    def test_form_source_is_separate_owner_sealed_shadow_not_backfilled_baseline(self):
        self.add_source()
        self.add_private_form_source()
        report = self.run_it(form_evidence_loader=self.synthetic_form_loader)
        row = next(x for x in report["records"] if x["race_id"] == RID)
        self.assertEqual(row["state"],
                         "A_B_PRIVATE_CIPHER_CREATED_SAME_JOB_SHA_MATCH")
        self.assertEqual(row["form_fall_shadow_state"],
                         "PRIVATE_CONDITIONED_SHADOW_SEALED")
        self.assertTrue((self.cipher/(RID+".sealed.json")).is_file())
        shadowfile = self.cipher/(RID+".form.sealed.json")
        self.assertTrue(shadowfile.is_file())
        self.assertEqual(shadowfile.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("FALL_DNF", shadowfile.read_text())
        self.assertNotIn("ranked_tickets", json.dumps(report))
        independent = reader.verify(producer_report=report,
                                    cipher_dir=self.cipher)
        self.assertEqual(independent["independent_cipher_file_shas_ok"], 1)
        self.assertEqual(independent["independent_condition_cipher_shas_ok"], 1)

    def test_unverified_car_only_supplement_never_seals_conditioned_forecast(self):
        snapshot = fixture()
        for rider in snapshot["riders"]:
            rider["athlete_id"] = None
        self.add_source(snapshot=snapshot)
        self.add_private_form_source()
        report = self.run_it()
        row = next(x for x in report["records"] if x["race_id"] == RID)
        self.assertEqual(report["same_job_sealed"], 1)
        self.assertEqual(row["form_fall_shadow_state"],
                         "HOLD_CONDITION_SOURCE_IDENTITY_NOT_VERIFIED")
        self.assertFalse((self.cipher/(RID+".form.sealed.json")).exists())

    def test_broken_optional_condition_file_preserves_valid_baseline(self):
        self.add_source()
        (self.cards/(RID+".form.json")).write_text("{not valid JSON")
        report = self.run_it()
        row = next(x for x in report["records"] if x["race_id"] == RID)
        self.assertEqual(report["same_job_sealed"], 1)
        self.assertEqual(row["form_fall_shadow_state"],
                         "HOLD_CONDITION_SOURCE_IDENTITY_NOT_VERIFIED")
        self.assertFalse((self.cipher/(RID+".form.sealed.json")).exists())

    def test_form_unverified_raw_bytes_hold_only_conditioned_forecast(self):
        self.add_source()
        self.add_private_form_source(broken_sha=True)
        report = self.run_it(form_evidence_loader=self.synthetic_form_loader)
        self.assertEqual(report["A_generated"], 1)
        self.assertEqual(report["same_job_sealed"], 1)
        row = next(x for x in report["records"] if x["race_id"] == RID)
        self.assertEqual(row["form_fall_shadow_state"],
                         "HOLD_OWNER_RAW_SOURCE_BYTES_MISSING")

    def test_form_source_not_valid_before_cutoff_is_hold(self):
        self.add_source()
        self.add_private_form_source(late=True)
        report = self.run_it(form_evidence_loader=self.synthetic_form_loader)
        self.assertEqual(report["same_job_sealed"],1)
        row = next(x for x in report["records"] if x["race_id"] == RID)
        self.assertEqual(row["form_fall_shadow_state"],
                         "HOLD_FORM_SOURCE_AFTER_PREDICTION_OR_CUTOFF")

    def test_form_shadow_tamper_does_not_rewrite_valid_baseline(self):
        self.add_source()
        self.add_private_form_source()
        report=self.run_it(form_evidence_loader=self.synthetic_form_loader)
        basefile=self.cipher/(RID+".sealed.json")
        original=basefile.read_bytes()
        shadowfile=self.cipher/(RID+".form.sealed.json")
        shadowfile.write_bytes(shadowfile.read_bytes()+b"tampered")
        independent=reader.verify(producer_report=report,
                                  cipher_dir=self.cipher)
        row=next(x for x in independent["records"] if x["race_id"]==RID)
        self.assertEqual(row["state"],"INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK")
        self.assertEqual(row["form_fall_shadow_state"],
                         "HOLD_FORM_CIPHER_SHA_MISMATCH")
        self.assertEqual(independent["independent_condition_cipher_shas_ok"],0)
        self.assertEqual(basefile.read_bytes(),original)


if __name__=="__main__":
    unittest.main()
