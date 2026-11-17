"""Synthetic RSA/AES 71R forecast intake tests: no live forecast or private key."""
from __future__ import annotations
import base64
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_manual71_owner_encrypted_intake as m

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "pr102-video" / "race_ai" / "keirin_private_sealed_payload.py"


def fixture():
    raw = {
        "forecast_v3.json": b'{"fictitious":true,"races":[]}',
        "baseline_v2.json": b'{"old":true,"dummy":1}',
        "categories.html": b"<article>synthetic only</article>",
        "template.html": b"<html>synthetic only</html>"
    }
    return raw, {k:sha256(v).hexdigest() for k,v in raw.items()}


class PrivateManualBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.private = cls.key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption())
        cls.public = cls.key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo)

    def test_authenticated_round_trip_against_immutable_pr102_helper(self):
        raw, expected = fixture()
        if not HELPER.is_file():
            self.skipTest("Pinned PR102 synthetic checkout not available")
        sealed=m.make_envelope(raw,public_key=self.public,helper_path=HELPER,
                               expected=expected)
        self.assertNotIn("fictitious",str(sealed))
        restored=m.open_envelope(sealed,private_key=self.private,helper_path=HELPER,
                                  expected=expected)
        self.assertEqual(restored,raw)

    def test_wrong_public_key_cannot_open(self):
        if not HELPER.is_file():
            self.skipTest("Pinned PR102 synthetic checkout not available")
        raw, expected = fixture()
        other=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        wrong=other.private_bytes(serialization.Encoding.PEM,
                 serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        sealed=m.make_envelope(raw,public_key=self.public,helper_path=HELPER,
                               expected=expected)
        with self.assertRaisesRegex(m.ManualBundleError,"AUTHENTICATION"):
            m.open_envelope(sealed,private_key=wrong,helper_path=HELPER,
                            expected=expected)

    def test_missing_or_forged_original_rejected(self):
        raw, expected=fixture()
        raw.pop("template.html")
        with self.assertRaisesRegex(m.ManualBundleError,"FOUR_ORIGINAL"):
            m.package_files(raw,expected=expected)
        raw,expected=fixture()
        raw["forecast_v3.json"]=b"false altered"
        with self.assertRaisesRegex(m.ManualBundleError,"SHA_MISMATCH"):
            m.package_files(raw,expected=expected)

    def test_compression_bomb_rejected(self):
        raw,expected=fixture()
        payload=m.package_files(raw,expected=expected)
        import zlib
        payload["files"]["forecast_v3.json"]["zlib_b64"]=base64.b64encode(
            zlib.compress(b"z"*(m.MAX_FILE+100),9)).decode()
        with self.assertRaisesRegex(m.ManualBundleError,"DECOMPRESSION_BOUNDS"):
            m.verify_payload(payload,expected=expected)

    def test_invalid_extra_file_and_truncated_cipher_rejected(self):
        raw,expected=fixture()
        payload=m.package_files(raw,expected=expected)
        payload["files"]["evil.py"]={"sha256":"0"*64,"bytes":1,
                                     "zlib_b64":"eA=="}
        with self.assertRaisesRegex(m.ManualBundleError,"FILE_SET_INVALID"):
            m.verify_payload(payload,expected=expected)

    def test_private_stage_0600_and_no_overwrite(self):
        raw,expected=fixture()
        with TemporaryDirectory() as d,patch.object(m,"EXPECTED",expected):
            base=Path(d)
            (base/"repo").mkdir()
            private=base/"source"
            result=m.stage_private(raw,private_folder=private,
                                    public_workspace=base/"repo")
            self.assertEqual(result["private_files"],4)
            self.assertEqual(result["forecast_sha256"],expected["forecast_v3.json"])
            self.assertEqual({p.name for p in private.iterdir()},set(raw))
            self.assertEqual(private.stat().st_mode & 0o777,0o700)
            self.assertTrue(all((p.stat().st_mode&0o777)==0o600 for p in private.iterdir()))
            with self.assertRaisesRegex(m.ManualBundleError,"PRIVATE_OUTPUT"):
                m.stage_private(raw,private_folder=private,
                                public_workspace=base/"repo")

    def test_public_workspace_staging_rejected(self):
        raw,expected=fixture()
        with TemporaryDirectory() as d,patch.object(m,"EXPECTED",expected):
            base=Path(d)
            workspace=base/"repo";workspace.mkdir()
            with self.assertRaisesRegex(m.ManualBundleError,"PRIVATE_OUTPUT"):
                m.stage_private(raw,private_folder=workspace/"raw",
                                public_workspace=workspace)

    def test_private_payload_does_not_assert_model_or_result_authenticity(self):
        raw,expected=fixture()
        p=m.package_files(raw,expected=expected)
        self.assertIs(p["live_result_authenticated"],False)
        self.assertIs(p["manual_predictions_are_pr71_models"],False)

if __name__=="__main__":
    unittest.main()
