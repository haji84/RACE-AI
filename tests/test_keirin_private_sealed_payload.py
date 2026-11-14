"""AES envelope confidentiality and temporal boundary regression; synthetic only."""
import copy
from hashlib import sha256
import json
import unittest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from race_ai.keirin_private_sealed_payload import (
    SealedResearchError,seal_json,open_sealed_json
)

class SealedDailyResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.private=cls.priv.private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        cls.public=cls.priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.aad="RACE_AI_PRIVATE_KEIRIN:2026-11-09:SCENE_RESEARCH_V1"
    def test_encrypt_only_ciphertext_no_plaintext_features(self):
        data={
            "race_id":"202611091201",
            "private_frame_sha256":sha256(b"private owner capture").hexdigest(),
            "feature_rows":[0.112233,0.445566],
            "true_tactics_verified":False,
        }
        env=seal_json(data,self.public,aad=self.aad)
        self.assertNotIn("feature_rows",json.dumps(env))
        self.assertNotIn("202611091201",json.dumps(env))
        self.assertFalse(env["plaintext_embedded"])
        self.assertEqual(open_sealed_json(env,self.private,aad=self.aad),data)
    def test_wrong_event_or_corrupted_cipher_fails(self):
        data={"rider_actions":"UNKNOWN"}
        env=seal_json(data,self.public,aad=self.aad)
        with self.assertRaisesRegex(SealedResearchError,"ENVELOPE_PROVENANCE_INVALID"):
            open_sealed_json(env,self.private,aad=self.aad+"-other")
        altered=copy.deepcopy(env)
        altered["ciphertext_sha256"]=sha256(b"altered").hexdigest()
        with self.assertRaisesRegex(SealedResearchError,"CIPHER_TAMPER"):
            open_sealed_json(altered,self.private,aad=self.aad)
        altered=copy.deepcopy(env)
        altered["wrapped_key_b64"]=env["nonce_b64"]
        with self.assertRaises(Exception):
            open_sealed_json(altered,self.private,aad=self.aad)
    def test_small_rsa_rejected(self):
        small=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pub=small.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaisesRegex(SealedResearchError,"RSA_KEY_TOO_SMALL"):
            seal_json({},pub,aad=self.aad)
    def test_cannot_be_used_with_unscoped_key(self):
        with self.assertRaisesRegex(SealedResearchError,"INVALID_ENCRYPTION_CONTEXT"):
            seal_json({"label":"GOAL"},self.public,aad="PUBLIC")
if __name__=="__main__":
    unittest.main()
