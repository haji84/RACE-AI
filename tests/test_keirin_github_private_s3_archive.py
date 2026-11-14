"""Private S3 ciphertext-only package gate; never calls any storage service."""
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import unittest
from scripts.keirin_github_private_s3_archive import package_cipher_only,DurableArchiveError

class CipherOnlyStorageTests(unittest.TestCase):
 def test_zip_preserves_only_cipher_and_manifests(self):
  with TemporaryDirectory() as t:
   root=Path(t)/"keirin-sealed"
   clip=root/"202611091201"
   clip.mkdir(parents=True)
   (clip/"manifest.json").write_text('{"research":true}')
   (clip/"capture-0.webm.aesgcm").write_bytes(b"FAKE_RESEARCH_CIPHER")
   out=Path(t)/"cipher.zip"
   count=package_cipher_only([root],out)
   self.assertEqual(count,2)
   with ZipFile(out) as z:
    self.assertEqual(len(z.namelist()),2)
    self.assertTrue(all("webm.aesgcm" in x or
                        x.endswith("manifest.json") for x in z.namelist()))
 def test_raw_images_cannot_enter_durable_archive(self):
  with TemporaryDirectory() as t:
   root=Path(t)/"capture"
   root.mkdir()
   (root/"frame.jpg").write_bytes(b"RAW_PRIVATE_PIXELS")
   with self.assertRaisesRegex(DurableArchiveError,
                                "RAW_FILE_CANNOT_ENTER_PRIVATE_CIPHER_ARCHIVE"):
    package_cipher_only([root],Path(t)/"output.zip")
 def test_plaintext_private_feature_file_not_uploaded(self):
  with TemporaryDirectory() as t:
   root=Path(t)/"private"
   root.mkdir()
   (root/"private_features.json").write_text('{"private":"true"}')
   with self.assertRaises(DurableArchiveError):
    package_cipher_only([root],Path(t)/"output.zip")
 def test_sealed_research_envelope_is_archivable_without_plaintext(self):
  from cryptography.hazmat.primitives.asymmetric import rsa
  from cryptography.hazmat.primitives import serialization
  from race_ai.keirin_private_sealed_payload import seal_json
  with TemporaryDirectory() as t:
   root=Path(t)/"research";root.mkdir()
   key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
   pub=key.public_key().public_bytes(
      serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
   env=seal_json({"private_features":[.2,.8]},pub,
      aad="RACE_AI_PRIVATE_KEIRIN:2026-11-09:SCENE_RESEARCH_V1")
   file=root/"keirin_sealed_research.aesgcm.json"
   import json
   file.write_text(json.dumps(env))
   output=Path(t)/"cipher.zip"
   self.assertEqual(package_cipher_only([root],output),1)
   with ZipFile(output) as z:
    self.assertEqual(len(z.namelist()),1)
    self.assertNotIn("private_features",z.read(z.namelist()[0]).decode())
 def test_fake_encrypted_name_does_not_bypass_research_envelope_gate(self):
  with TemporaryDirectory() as t:
   root=Path(t)/"research";root.mkdir()
   (root/"falsely_encrypted.aesgcm.json").write_text(
       '{"private_features":"PLAINTEXT_ONLY"}')
   with self.assertRaisesRegex(DurableArchiveError,
                                 "INVALID_ENCRYPTED_RESEARCH_ENVELOPE"):
    package_cipher_only([root],Path(t)/"bad.zip")
if __name__=="__main__":
 unittest.main()
