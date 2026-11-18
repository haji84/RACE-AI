"""Synthetic source table and RSA key only. NEVER count as real results."""
import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_auto_storage as seal
from scripts import keirin_evening_national_real_AB_20261118 as subject
from scripts import keirin_capture_public_two_sources as fetcher

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json"
INDEX = "https://keirin.kdreams.jp/kochi/racecard/74202611170200/"
DETAIL = "https://keirin.kdreams.jp/kochi/racedetail/7420261117020001/"
NET = "https://keirin.netkeiba.com/race/entry/?race_id=202611187401"
RID = "202611187401"


def pages():
    rows = []
    for car in range(1, 8):
        fields = [
            str(car), str(car), "", str(car), "研究用選手",
            f"{80-car:.2f}", "1逃" if car in (1,4) else "3追",
            "0", "1", str(car), "1", "0", "0", "0",
            "1", "1", "1", "14",
            f"{car*2:.1f}%", "25.0%", "30.0%", "3.92", "自力"
        ]
        rows.append("<tr>" + "".join("<td>"+v+"</td>" for v in fields) + "</tr>")
    net = ("<html><h1>高知競輪 1R</h1><table>" +
           "".join(rows) + "</table></html>").encode("utf-8")
    details = (
        "<html><h1>高知競輪 チャレンジ一般</h1>"
        "<p>投票締切20:35</p><h2>並び予想</h2>"
        "<p>← 1先行 3追込 2自在 4押え先 7追込 5追込 6追上</p>"
        "<h2>レース評</h2></html>").encode("utf-8")
    index = (
        '<html><a href="/kochi/racedetail/7420261117020001/">1R</a>'
        '</html>').encode("utf-8")
    return {
        INDEX:index,
        subject.SCHEDULE["24"][1]:b"<html><body></body></html>",
        DETAIL:details,NET:net
    }


class EveningProspectiveContracts(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.root.chmod(0o700)
        for name in ("cards","raw","sealed"):
            p=self.root/name
            p.mkdir(mode=0o700)
            p.chmod(0o700)
        self.registry=json.loads(REG.read_text(encoding="utf-8"))
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        self.public=key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        der=key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        self.pin=patch.object(
            seal,"PINNED_OWNER_SPKI_SHA256",sha256(der).hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.html=pages()
        self.calls=[]

    def fetch(self,url):
        self.calls.append(url)
        return self.html[url]

    def execute(self,**overrides):
        args={
            "registry":self.registry,
            "private_root":self.root,
            "owner_public_key_pem":self.public,
            "clock":lambda:datetime.fromisoformat(
                "2026-11-18T19:55:00+09:00"),
            "fetch":self.fetch,
            "max_new_races":1
        }
        args.update(overrides)
        return subject.run(**args)

    def test_one_future_research_A_B_encrypted_others_HOLD(self):
        out=self.execute()
        self.assertEqual(out["registered_races"],79)
        self.assertEqual(out["new_A_B_same_job_encrypted"],1)
        self.assertEqual(out["previously_sealed_A_B_do_not_recreate"],2)
        self.assertEqual(out["official_result_scored"],0)
        self.assertFalse(out["organizer_actual_sales_close_independently_verified"])
        row=next(x for x in out["records"] if x["race_id"]==RID)
        self.assertEqual(row["state"],"REAL_A_B_RSA_AES_SEALED_SAME_JOB")
        self.assertGreaterEqual(row["B_six_phase_scenarios"],2)
        self.assertEqual(seal.readback_file(
            self.root/"sealed"/(RID+".sealed.json"),
            expected_sha=row["ciphertext_file_sha256"])["race_id"],RID)
        self.assertNotIn("ranked_tickets",json.dumps(out))
        self.assertNotIn("202611182401",str(self.calls))

    def test_repeated_run_never_overwrites_initial_cipher(self):
        first=self.execute()
        self.assertEqual(first["new_A_B_same_job_encrypted"],1)
        target=self.root/"sealed"/(RID+".sealed.json")
        original=target.read_bytes()
        again=self.execute()
        self.assertEqual(again["new_A_B_same_job_encrypted"],0)
        self.assertEqual(target.read_bytes(),original)

    def test_supplement_admits_prior_cipher_only_after_exact_sha_readback(self):
        first=self.execute()
        target=self.root/"sealed"/(RID+".sealed.json")
        first_sha=sha256(target.read_bytes()).hexdigest()
        prior=self.root/"prior"/"sealed"
        prior.mkdir(parents=True,mode=0o700)
        prior.chmod(0o700)
        (prior/(RID+".sealed.json")).write_bytes(target.read_bytes())
        second=self.execute(prior_sealed_sha_by_race={RID:first_sha})
        self.assertEqual(second["previously_sealed_A_B_do_not_recreate"],3)
        self.assertEqual(second["new_A_B_same_job_encrypted"],0)
        self.assertEqual(target.read_bytes(),(prior/(RID+".sealed.json")).read_bytes())
        with self.assertRaises(Exception):
            self.execute(prior_sealed_sha_by_race={RID:"0"*64})

    def test_provider_denial_stops_all_races_without_retry(self):
        def blocked(url):
            self.calls.append(url)
            raise fetcher.SourceCaptureError(
                "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
        out=self.execute(fetch=blocked)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(out["new_A_B_same_job_encrypted"],0)
        self.assertTrue(out["provider_abort"])

    def test_after_all_cutoffs_cannot_make_backdated_A_B(self):
        out=self.execute(clock=lambda:datetime.fromisoformat(
            "2026-11-18T23:26:00+09:00"))
        self.assertEqual(out["venue_index_public_GETs"],0)
        self.assertEqual(out["new_A_B_same_job_encrypted"],0)
        self.assertEqual(len(self.calls),0)

    def test_conflicting_public_cutoff_prevents_forecast(self):
        self.html[DETAIL]=self.html[DETAIL].replace(b"20:35",b"20:40")
        out=self.execute()
        self.assertEqual(out["new_A_B_same_job_encrypted"],0)
        self.assertIn("HOLD_OFFICIAL_PROVIDER_CUTOFF_DIFFERENCE_HOLD",
                      out["statuses"])

    def test_missing_real_detail_link_keeps_no_forecast(self):
        self.html[INDEX]=b"<html><body>none</body></html>"
        out=self.execute()
        self.assertEqual(out["new_A_B_same_job_encrypted"],0)
        self.assertIn("HOLD_KDREAMS_RACE_DETAIL_LINK_NOT_SEEN",
                      out["statuses"])


if __name__=="__main__":
    unittest.main()
