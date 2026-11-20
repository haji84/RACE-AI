"""Synthetic owner-only RSA/AES test. No live rider material or credentials."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_nationwide_auto_storage as store
from race_ai import keirin_form_fall_shadow as shadow
from scripts import keirin_form_fall_owner_view as view
from tests.test_keirin_nationwide_auto_generator import fixture
from tests.test_keirin_rider_form_evidence import pack, result, AT


class OfflineConditionView(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.ownerdir=self.root/"owner"
        self.ownerdir.mkdir(mode=0o700)
        self.ownerdir.chmod(0o700)
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        self.pub=key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        self.private=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        der=key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        pin=sha256(der).hexdigest()
        self.patcher=patch.object(store,"PINNED_OWNER_SPKI_SHA256",pin)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.private_path=self.ownerdir/"key.pem"
        self.private_path.write_bytes(self.private)
        self.private_path.chmod(0o600)
        self.snapshot=fixture()
        self.baseline=core.generate_A_B(self.snapshot,generated_at=AT)
        self.extra=pack(
            results=[result(1,1),result(2,1),result(3,1),
                     result(4,None,status="FALL_DNF"),
                     result(5,7),result(6,7),result(7,7)],
            comments=[{"speaker":"RIDER","text":"<script>test</script>",
                       "published_at":"2026-11-18T08:00:00+09:00",
                       "source_sha256":"e"*64}])
        self.conditioned=shadow.generate_shadow(
            self.snapshot,self.extra,baseline=self.baseline,generated_at=AT)
        self.sealed_path=self.ownerdir/"202611182601.form.sealed.json"
        self.encoded=shadow.seal_shadow_once(
            snapshot=self.snapshot,supplement=self.extra,
            shadow=self.conditioned,public_key_pem=self.pub,
            path=self.sealed_path,sealed_at=AT)

    def test_real_crypto_decrypt_and_offline_mobile_safe_html(self):
        data, supplement=view.decrypt_owner_shadow(
            self.sealed_path.read_bytes(),self.private)
        self.assertEqual(data["sha256"],self.conditioned["sha256"])
        self.assertEqual(supplement,self.extra)
        html=view.render_html(data,supplement)
        soup=BeautifulSoup(html,"html.parser")
        self.assertIn("A｜基準方式",soup.text)
        self.assertIn("B｜6局面方式",soup.text)
        self.assertIn("下降傾向",soup.text)
        self.assertEqual(soup.select("script,iframe,form,link,img"),[])
        self.assertEqual(soup.select("[src],[srcset]"),[])
        self.assertIn("<script>test</script>",soup.get_text())
        self.assertNotIn("<script>test</script>",str(soup.find("body")))
        self.assertIn("width=device-width",html)

    def test_create_once_owner_file_and_validated_independent_shadow_bytes(self):
        dest=self.ownerdir/"owner-form-report.html"
        report=view.render_file(cipher_path=str(self.sealed_path),
                                private_pem_path=str(self.private_path),
                                out_path=str(dest))
        self.assertEqual(report["A_points"],12)
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.stat().st_mode&0o777,0o600)
        with self.assertRaises(ValueError):
            view.render_file(cipher_path=str(self.sealed_path),
                             private_pem_path=str(self.private_path),
                             out_path=str(dest))
        verify=shadow.readback_shadow(
            self.sealed_path,expected_sha=self.encoded["file_sha256"],
            expected_baseline_sha=self.baseline["prediction_sha256"],
            expected_race=self.snapshot["race_id"])
        self.assertFalse(verify["rsa_private_decryption_verified"])

    def test_corrupt_cipher_or_wrong_key_does_not_open(self):
        with self.assertRaisesRegex(view.PrivateFormViewError,
                                    "FORM_OWNER_DECRYPT_OR_DATA_INVALID"):
            view.decrypt_owner_shadow(self.sealed_path.read_bytes()+b"X",
                                      self.private)
        wrong=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        wrong_pem=wrong.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        with self.assertRaisesRegex(Exception,"FORM_OWNER"):
            view.decrypt_owner_shadow(self.sealed_path.read_bytes(),wrong_pem)


if __name__=="__main__":
    unittest.main()
