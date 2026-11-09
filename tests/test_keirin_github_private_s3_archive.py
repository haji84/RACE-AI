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
if __name__=="__main__":
 unittest.main()
