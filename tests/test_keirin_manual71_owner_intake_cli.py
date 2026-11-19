"""Bounded, synthetic, GitHub-main-secret contract for manual71 encrypted intake.

RSA key, result and rider bytes here are fabricated. Never print private
materials to Actions; never mark CI a real-race completion.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_manual71_owner_encrypted_intake as pack
from scripts import keirin_manual71_owner_intake_cli as owner

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "pr102-video/race_ai/keirin_private_sealed_payload.py"


class Manual71OwnerActionsIntakeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.private = cls.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode("utf-8")
        cls.public = cls.key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        der = cls.key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.public_sha = sha256(der).hexdigest()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "repo"
        self.workspace.mkdir()
        self.target = self.base / "private"
        self.env = {
            "GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":"haji84/RACE-AI",
            "GITHUB_REPOSITORY_ID":"1416489937",
            "GITHUB_REF":"refs/heads/main",
            "GITHUB_EVENT_NAME":"workflow_dispatch",
            "RACE_AI_KEIRIN_PRIVATE_RSA_PEM":self.private,
        }
        self.files = {
            "forecast_v3.json":b'{"races":[],"fictional":true}',
            "baseline_v2.json":b'{"races":[],"fictional-baseline":true}',
            "categories.html":b"<html>fictional category</html>",
            "template.html":b"<html>fictional template</html>",
        }
        self.hashes = {name:sha256(data).hexdigest()
                       for name,data in self.files.items()}

    def _sealed(self):
        if not HELPER.is_file():
            self.skipTest("Immutable PR102 checkout unavailable")
        env = pack.make_envelope(self.files, public_key=self.public,
                                 helper_path=HELPER, expected=self.hashes)
        raw = json.dumps(env,sort_keys=True,separators=(",",":")).encode()
        cipher=self.workspace/owner.CIPHER_RELATIVE
        cipher.parent.mkdir(parents=True,exist_ok=True)
        cipher.write_bytes(raw)
        return env,raw

    def _run(self,*,env=None,file_hash=None,cipher_hash=None,public_sha=None):
        current,raw=self._sealed()
        return owner.restore_existing_owner_bundle(
            env=self.env if env is None else env,
            workspace=self.workspace,
            helper=HELPER,
            private_dir=self.target,
            expected_file_sha=file_hash or sha256(raw).hexdigest(),
            expected_cipher_sha=cipher_hash or current["ciphertext_sha256"],
            expected_public_sha=public_sha or self.public_sha,
            expected_originals=self.hashes,
        )

    def test_registered_real_ciphertext_has_exact_sha_and_no_plaintext(self):
        # Reads only ciphertext metadata; never decrypts owner predictions.
        import base64
        f = ROOT / owner.CIPHER_RELATIVE
        self.assertTrue(f.is_file() and not f.is_symlink())
        data = f.read_bytes()
        self.assertEqual(len(data),185773)
        self.assertEqual(sha256(data).hexdigest(),owner.CIPHER_FILE_SHA256)
        env=json.loads(data)
        self.assertEqual(env["schema"],"RACE_AI_PRIVATE_KEIRIN_ENCRYPTED_JSON_V1")
        self.assertEqual(env["context"],pack.AAD)
        self.assertIs(env["plaintext_embedded"],False)
        self.assertIs(env["source_is_private"],True)
        self.assertEqual(env["ciphertext_sha256"],owner.CIPHER_PAYLOAD_SHA256)
        ciphertext=base64.b64decode(env["ciphertext_b64"],validate=True)
        self.assertEqual(sha256(ciphertext).hexdigest(),owner.CIPHER_PAYLOAD_SHA256)
        self.assertEqual(len(base64.b64decode(env["nonce_b64"],validate=True)),12)
        self.assertEqual(len(base64.b64decode(env["wrapped_key_b64"],validate=True)),384)

    def test_real_race_claims_require_trusted_main_run(self):
        env=dict(self.env,GITHUB_REF="refs/heads/research/test")
        result=owner.restore_existing_owner_bundle(
            env=env,workspace=self.workspace,helper=HELPER,
            private_dir=self.target)
        self.assertEqual(result["state"],"HOLD_NO_TRUSTED_MAIN_OWNER_RUN")
        self.assertFalse(self.target.exists())

    def test_no_existing_key_stays_hold_and_does_not_stage(self):
        env=dict(self.env)
        env.pop("RACE_AI_KEIRIN_PRIVATE_RSA_PEM")
        result=owner.restore_existing_owner_bundle(
            env=env,workspace=self.workspace,helper=HELPER,
            private_dir=self.target)
        self.assertEqual(result["state"],"HOLD_EXISTING_RSA_SECRET_UNCONFIGURED")
        self.assertFalse(self.target.exists())

    def test_production_accepts_only_bound_secret_on_fake_existing_runner(self):
        result=self._run()
        self.assertEqual(result["state"],"OWNER_MANUAL71_PRIVATE_SOURCE_STAGED")
        self.assertFalse(result["real_result_authenticated"])
        self.assertEqual(result["source_files"],4)
        self.assertEqual(self.target.stat().st_mode & 0o777,0o700)
        for name,raw in self.files.items():
            path=self.target/name
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_second_intake_never_overwrites_existing_files(self):
        self._run()
        with self.assertRaisesRegex(pack.ManualBundleError,"PRIVATE_OUTPUT"):
            self._run()

    def test_wrong_rsa_secret_rejected_before_decoding(self):
        other=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        wrong=other.private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode()
        env=dict(self.env,RACE_AI_KEIRIN_PRIVATE_RSA_PEM=wrong)
        with self.assertRaisesRegex(pack.ManualBundleError,
                                    "PUBLIC_KEY_NOT_PINNED"):
            self._run(env=env)

    def test_cipher_file_digest_rejects_unreviewed_change(self):
        with self.assertRaisesRegex(pack.ManualBundleError,"BUNDLE_SHA_CHANGED"):
            self._run(file_hash="f"*64)
        self.assertFalse(self.target.exists())

    def test_cipher_payload_digest_rejects_wrong_revision(self):
        with self.assertRaisesRegex(pack.ManualBundleError,"CIPHER_MISMATCH"):
            self._run(cipher_hash="f"*64)
        self.assertFalse(self.target.exists())

    def test_key_fingerprint_is_exact_not_a_presence_check(self):
        with self.assertRaisesRegex(pack.ManualBundleError,"PUBLIC_KEY_NOT_PINNED"):
            self._run(public_sha="f"*64)

    def test_public_workspace_decryption_is_rejected(self):
        self.target = self.workspace / "bad-private"
        with self.assertRaisesRegex(pack.ManualBundleError,"PRIVATE_OUTPUT"):
            self._run()
        self.assertFalse(self.target.exists())


if __name__=="__main__":
    unittest.main()
