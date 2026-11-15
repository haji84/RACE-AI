"""Offline contract tests for the owner-only private original reader."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.owner_private_file_reader import (
    OwnerPrivateFileReader, OwnerReadbackError, inspect_reference_bundle,
)


def reference(rid="203101050101", frozen=False):
    return {
        "version": "synthetic-research", "stamp_jst": "2031-01-05T09:00:00+09:00",
        "calibrated": False, "officially_frozen": frozen, "core_sha256": "a" * 64,
        "races": [{"id": rid, "total": 0.4,
                   "ranked": [{"pick": "1-2-3", "p": 0.3},
                              {"pick": "1-3-2", "p": 0.1}]}],
    }


class PrivateReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "reference.json"
        self.save(reference())

    def save(self, value):
        raw = json.dumps(value).encode("utf-8")
        self.path.write_bytes(raw)
        self.pin = sha256(raw).hexdigest()
        return raw

    def reader(self):
        return OwnerPrivateFileReader(
            self.root, {"private:one": ("reference.json", self.pin)})

    def test_real_file_readback_matches_sha_with_secret_free_report(self):
        raw = self.path.read_bytes()
        self.assertEqual(self.reader()("private:one"), raw)
        info = inspect_reference_bundle(self.reader(), "private:one")
        self.assertEqual(info["reference_races"], 1)
        self.assertEqual(info["whole_bundle_sha256"], self.pin)
        self.assertFalse(info["per_race_original_sha_verified"])
        self.assertFalse(info["external_pre_cutoff_receipts_verified"])
        self.assertIsNone(info["formal_hit_at_8_all"])
        self.assertNotIn("1-2-3", json.dumps(info))

    def test_self_declared_frozen_does_not_authenticate(self):
        self.save(reference(frozen=True))
        info = inspect_reference_bundle(self.reader(), "private:one")
        self.assertTrue(info["bundle_declares_officially_frozen"])
        self.assertFalse(info["external_pre_cutoff_receipts_verified"])
        self.assertIsNone(info["formal_hit_at_8_all"])

    def test_original_mutation_rejected(self):
        reader = self.reader()
        self.save(reference(rid="203101050102"))
        with self.assertRaises(OwnerReadbackError):
            reader("private:one")

    def test_missing_ref_rejected(self):
        with self.assertRaises(OwnerReadbackError):
            self.reader()("private:no-such-reference")

    def test_escape_and_absolute_paths_rejected(self):
        for path in ("../reference.json", "a/../../reference.json", str(self.path)):
            with self.subTest(path=path), self.assertRaises(OwnerReadbackError):
                OwnerPrivateFileReader(self.root, {"private:one": (path, self.pin)})

    def test_symlink_original_rejected(self):
        link = self.root / "link.json"
        try:
            link.symlink_to(self.path)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable in environment")
        with self.assertRaises(OwnerReadbackError):
            OwnerPrivateFileReader(
                self.root, {"private:one": ("link.json", self.pin)})("private:one")

    def test_duplicate_file_binding_rejected(self):
        with self.assertRaises(OwnerReadbackError):
            OwnerPrivateFileReader(self.root, {
                "private:one": ("reference.json", self.pin),
                "private:two": ("reference.json", self.pin),
            })

    def test_duplicate_race_rejected(self):
        doc = reference()
        doc["races"].append(dict(doc["races"][0]))
        self.save(doc)
        with self.assertRaises(OwnerReadbackError):
            inspect_reference_bundle(self.reader(), "private:one")

    def test_more_than_eight_predictions_rejected(self):
        doc = reference()
        doc["races"][0]["ranked"] = [
            {"pick": f"1-{b}-{c}", "p": 0.03}
            for b, c in [(2,3),(2,4),(2,5),(2,6),(2,7),
                         (2,8),(2,9),(3,2),(3,4)]
        ]
        self.save(doc)
        with self.assertRaises(OwnerReadbackError):
            inspect_reference_bundle(self.reader(), "private:one")

    def test_nonfinite_probability_rejected(self):
        doc = reference()
        doc["races"][0]["ranked"][0]["p"] = float("nan")
        self.save(doc)
        with self.assertRaises(OwnerReadbackError):
            inspect_reference_bundle(self.reader(), "private:one")

    def test_git_checkout_cannot_be_owner_root(self):
        (self.root / ".git").mkdir()
        with self.assertRaises(OwnerReadbackError):
            self.reader()

    def test_duplicate_json_key_rejected(self):
        raw = b'{"version":"x","version":"y"}'
        self.path.write_bytes(raw)
        pin = sha256(raw).hexdigest()
        reader = OwnerPrivateFileReader(
            self.root, {"private:one": ("reference.json", pin)})
        with self.assertRaises(OwnerReadbackError):
            inspect_reference_bundle(reader, "private:one")


if __name__ == "__main__":
    unittest.main()
