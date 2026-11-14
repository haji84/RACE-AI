"""Synthetic cipher and completeness tests for user-confirmed WINTICKET replay."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.keirin_replay_probe import encrypt_recordings
from scripts.keirin_yahiko_1r_encrypted_replay_capture import (
    RACE_ID,recording_complete)

class YahikoEncryptedCaptureContracts(unittest.TestCase):
    def test_race_specific_manifest_encryption_and_owner_only_decryption(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            public=private.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo)
            public_path=p/"public-only.pem"
            public_path.write_bytes(public)
            fake=b"SYNTHETIC_SCREEN_CAPTURE_NOT_REAL_VIDEO"
            fake_path=p/"fixture.webm"
            fake_path.write_bytes(fake)
            output=p/"encrypted"
            self.assertEqual(encrypt_recordings(
                [fake_path],public_path,output,race_id=RACE_ID),1)
            data=json.loads((output/"manifest.json").read_text())
            self.assertEqual(data["race_id"],RACE_ID)
            self.assertNotIn("PRIVATE KEY",(output/"manifest.json").read_text())
            item=data["files"][0]
            self.assertEqual(hashlib.sha256(fake).hexdigest(),
                             item["plaintext_sha256"])
            wrapped=base64.b64decode(item["wrapped_key"])
            key=private.decrypt(wrapped,padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),label=None))
            actual=AESGCM(key).decrypt(
                base64.b64decode(item["nonce"]),
                (output/item["file"]).read_bytes(),
                base64.b64decode(item["aad"]))
            self.assertEqual(actual,fake)
            self.assertNotEqual((output/item["file"]).read_bytes(),fake)
            self.assertEqual(base64.b64decode(item["aad"]),
                             (RACE_ID+":webm:0").encode())
            self.assertFalse((output/"fixture.webm").exists())

    def test_player_duration_and_stored_recording_both_essential(self):
        first={"currentTime":1.0}
        last={"duration":80.164,"currentTime":80.164,"ended":True}
        technical={"ffprobe":{
          "format":{"duration":"92.3"},
          "streams":[{"width":1280,"height":720}]}}
        self.assertTrue(recording_complete(first,last,technical))
        too_short={"ffprobe":{"format":{"duration":"19.2"},
                   "streams":[{"width":1280,"height":720}]}}
        self.assertFalse(recording_complete(first,last,too_short))
        self.assertFalse(recording_complete(
            first,{**last,"ended":False},technical))
        self.assertFalse(recording_complete(
            {"currentTime":10},last,technical))
        self.assertFalse(recording_complete(first,last,{"ffprobe":{}}))

    def test_invalid_race_identity_never_accepted_for_encryption(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            pub=p/"public.pem"
            pub.write_bytes(private.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo))
            f=p/"test.webm";f.write_bytes(b"synthetic")
            with self.assertRaisesRegex(ValueError,"INVALID_ENCRYPTED_RACE_ID"):
                encrypt_recordings([f],pub,p/"encrypted",race_id="../../unsafe")

if __name__=="__main__":
    unittest.main()
