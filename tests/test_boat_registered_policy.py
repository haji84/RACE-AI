"""No-key regression: frozen JS modules are anchored to immutable commit/hash."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.boat_registered_policy import (
    POLICY_PATHS, SUPPORT_PATHS, SETTLEMENT, staged_registered_policy,
)


class RegisteredPolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reference = self.root / "registered-policy-reference"
        self.reference.mkdir()
        self.runner = self.root / "runner"
        self.runner.mkdir()
        self.policy = {}
        for path in (*POLICY_PATHS, *SUPPORT_PATHS):
            dest = self.reference / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("/* registered immutable module " + path + " */\n", encoding="utf-8")
        for path in POLICY_PATHS:
            self.policy[path] = hashlib.sha256((self.reference / path).read_bytes()).hexdigest()
        script = self.root / SETTLEMENT
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("/* current settlement reader, no allocator */\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.reference)], check=True)
        subprocess.run(["git", "-C", str(self.reference), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.reference),
                        "-c", "user.name=RACE Policy Test",
                        "-c", "user.email=policy-test@example.invalid",
                        "commit", "-q", "-m", "Frozen pre-outcome policy"], check=True)
        self.commit = subprocess.check_output(
            ["git", "-C", str(self.reference), "rev-parse", "HEAD"], text=True).strip()
        self.registration = dict(policy_commit=self.commit, policy_files_sha256=self.policy)

    def tearDown(self):
        self.temp.cleanup()

    def stage(self, registration=None):
        return staged_registered_policy(
            registration or self.registration, repository=self.root, temporary=self.runner)

    def test_registered_files_not_current_mutable_files(self):
        # A newer current product-data module must never rewrite the frozen evaluation.
        mutable = self.root / "web/product-data.js"
        mutable.parent.mkdir(exist_ok=True)
        mutable.write_text("/* updated result cutoff reference rule */\n", encoding="utf-8")
        with self.stage() as staged:
            for path in POLICY_PATHS:
                self.assertEqual(hashlib.sha256((staged / path).read_bytes()).hexdigest(), self.policy[path])
            self.assertNotEqual((staged / "web/product-data.js").read_bytes(), mutable.read_bytes())
            self.assertEqual((staged / SETTLEMENT).read_bytes(), (self.root / SETTLEMENT).read_bytes())
            self.assertEqual(os.stat(staged).st_mode & 0o777, 0o700)
            directory = staged
        self.assertFalse(directory.exists())

    def test_commit_mismatch_rejected_before_execution(self):
        wrong = dict(self.registration, policy_commit="0" * 40)
        with self.assertRaisesRegex(ValueError, "REGISTERED_POLICY_COMMIT_MISMATCH"):
            with self.stage(wrong):
                pass

    def test_modified_archived_module_rejected(self):
        (self.reference / "web/product-data.js").write_text("/* adulterated */\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "REGISTERED_POLICY_REGISTERED_DIGEST_MISMATCH"):
            with self.stage():
                pass

    def test_wrong_registered_digest_rejected(self):
        wrong = dict(self.registration,
                     policy_files_sha256={**self.policy, "web/product-data.js": "f" * 64})
        with self.assertRaisesRegex(ValueError, "REGISTERED_POLICY_REGISTERED_DIGEST_MISMATCH"):
            with self.stage(wrong):
                pass

    def test_missing_reference_fails_closed(self):
        (self.reference / "web/forecast-audit-model.js").unlink()
        with self.assertRaisesRegex(ValueError, "REGISTERED_POLICY_REGULAR_FILE_REQUIRED"):
            with self.stage():
                pass


if __name__ == "__main__":
    unittest.main()
