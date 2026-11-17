"""Source-free actual RSA/AES cryptography, using an invented test-only key."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import zlib
import base64

from race_ai import keirin_nationwide_auto_generator as generator
from race_ai import keirin_nationwide_auto_storage as storage
from tests.test_keirin_nationwide_auto_generator import fixture, AT


def make_key():
    key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    pem=key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    fingerprint=sha256(key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    return key,pem,fingerprint


def prepare(root, *, pem, stamp="2026-11-18T09:01:05+09:00"):
    original=fixture()
    prediction=generator.generate_A_B(original,generated_at=AT)
    dest=Path(root,"202611182601.json")
    return storage.seal_once(snapshot=original,prediction=prediction,
              public_key_pem=pem,path=dest,sealed_at=stamp)


class ActualAutomaticEncryptionContracts(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.root.chmod(0o700)
        self.rsa_key,self.pem,self.fingerprint=make_key()
        self.patch=patch.object(storage,"PINNED_OWNER_SPKI_SHA256",
                                self.fingerprint)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_a_and_b_are_independently_encrypted_and_read_back(self):
        receipt=prepare(self.root,pem=self.pem)
        path=self.root/"202611182601.json"
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertEqual(sha256(path.read_bytes()).hexdigest(),receipt["cipher_sha256"])
        response=storage.readback_file(path,expected_sha=receipt["cipher_sha256"])
        self.assertTrue(response["ciphertext_integrity_rechecked"])
        self.assertTrue(response["RSA_decryption_and_real_source_unproven"])
        self.assertNotEqual(receipt["A_cipher_sha256"],receipt["B_cipher_sha256"])
        contents=json.loads(path.read_text(encoding="utf-8"))
        originals=[]
        for role in ("A","B"):
            data=contents[role]
            aes=self.rsa_key.decrypt(
                base64.b64decode(data["rsa_oaep_sha256_wrapped_key_b64"]),
                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                             algorithm=hashes.SHA256(),label=None))
            encrypted=base64.b64decode(data["ciphertext_b64"])
            clear=zlib.decompress(AESGCM(aes).decrypt(
                base64.b64decode(data["aesgcm_nonce_b64"]),
                encrypted,data["aad_ascii"].encode()))
            self.assertEqual(sha256(clear).hexdigest(),data["plaintext_sha256"])
            decoded=json.loads(clear)
            self.assertEqual(decoded["race_id"],"202611182601")
            self.assertEqual(decoded["role"],role)
            self.assertEqual(decoded["generated_at"],AT)
            self.assertEqual(len(decoded["prediction"]["ranked_tickets"])>=1,True)
            originals.append(clear)
        self.assertNotEqual(originals[0],originals[1])

    def test_second_attempt_cannot_change_first_stored_original(self):
        receipt=prepare(self.root,pem=self.pem)
        before=(self.root/"202611182601.json").read_bytes()
        with self.assertRaisesRegex(storage.AutoSealError,
                                    "PRIVATE_CREATE_ONCE_DIRECTORY_REQUIRED"):
            prepare(self.root,pem=self.pem)
        self.assertEqual((self.root/"202611182601.json").read_bytes(),before)

    def test_wrong_RSA_key_or_key_fingerprint_fails_without_file(self):
        wrong=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        pem=wrong.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaisesRegex(storage.AutoSealError,
                                    "OWNER_PUBLIC_SPKI_PIN_MISMATCH"):
            prepare(self.root,pem=pem)
        self.assertFalse((self.root/"202611182601.json").exists())

    def test_world_readable_output_directory_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaisesRegex(storage.AutoSealError,
                                    "PRIVATE_CREATE_ONCE_DIRECTORY_REQUIRED"):
            prepare(self.root,pem=self.pem)

    def test_late_stamping_refused_before_any_write(self):
        with self.assertRaisesRegex(storage.AutoSealError,
                                    "SEAL_AFTER_OR_TOO_CLOSE_TO_PUBLISHED_CUTOFF"):
            prepare(self.root,pem=self.pem,
                    stamp="2026-11-18T11:59:15+09:00")
        self.assertFalse((self.root/"202611182601.json").exists())

    def test_ciphertext_tampering_detected_even_with_valid_json(self):
        receipt=prepare(self.root,pem=self.pem)
        path=self.root/"202611182601.json"
        v=json.loads(path.read_text())
        v["B"]["ciphertext_sha256"]="f"*64
        path.write_text(json.dumps(v))
        with self.assertRaisesRegex(storage.AutoSealError,
                                    "AUTO_CIPHER_SHA_OR_LENGTH_INVALID"):
            storage.readback_file(
                path,expected_sha=sha256(path.read_bytes()).hexdigest())

    def test_same_nonce_or_key_payload_prohibited(self):
        receipt=prepare(self.root,pem=self.pem)
        path=self.root/"202611182601.json"
        v=json.loads(path.read_text())
        v["B"]["aesgcm_nonce_b64"]=v["A"]["aesgcm_nonce_b64"]
        v["B"]["rsa_oaep_sha256_wrapped_key_b64"] = v["A"]["rsa_oaep_sha256_wrapped_key_b64"]
        with self.assertRaisesRegex(storage.AutoSealError,
                                    "AUTO_A_B_MUST_USE_DISTINCT"):
            storage.validate_cipher(v)

    def test_cipher_includes_no_source_plaintext_without_key(self):
        prepare(self.root,pem=self.pem)
        raw=(self.root/"202611182601.json").read_bytes()
        for item in (b'"ranked_tickets"',b'"athlete_id"',b'"line_groups"',
                     b'"competition_points"'):
            self.assertNotIn(item,raw)


if __name__=="__main__":
    unittest.main()
