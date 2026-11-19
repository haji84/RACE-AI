"""Synthetic owner key and local Git only; no live data or external writes."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import base64
import json
import subprocess
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_run_history as history

DAY = "2026-11-19"
AT = "2026-11-19T18:00:00+09:00"
REPORT = {"day_jst": DAY, "registered_races": 2, "paired_A_B_scored": 0,
          "scorecard": {}, "statuses": {"HOLD_NO_OFFICIAL_RESULT": 2}}


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def payload(revision=1):
    return {"day_jst": DAY, "safe_report": deepcopy(REPORT),
            "revision": revision,
            "private_source": "RAW_PRIVATE_SOURCE_NOT_FOR_PUBLIC_GIT",
            "owner_view": {"private_forecast": "PRIVATE_FORECAST_NOT_FOR_PUBLIC_GIT"}}


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True).stdout.strip()


class EvidenceTestFixture:
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.public = cls.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.private = cls.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        cls.pin = sha256(cls.key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        pin = patch.object(storage, "PINNED_OWNER_SPKI_SHA256", self.pin)
        pin.start()
        self.addCleanup(pin.stop)

    def seal(self, value=None, observed_at=AT):
        return history.seal_evidence(
            payload=payload() if value is None else value,
            owner_public_pem=self.public, day=DAY, observed_at=observed_at)


class EncryptedOfficialEvidence(EvidenceTestFixture, unittest.TestCase):
    def test_actual_rsa_aead_round_trip_keeps_private_evidence_outside_envelope(self):
        value = payload()
        raw = self.seal(value)
        doc = json.loads(raw)
        self.assertEqual(history.decrypt_evidence(raw, self.private), value)
        self.assertEqual(doc["evidence_plaintext_sha256"], sha256(canonical(value)).hexdigest())
        self.assertEqual(doc["report_sha256"], sha256(canonical(REPORT)).hexdigest())
        self.assertNotIn(b"RAW_PRIVATE_SOURCE_NOT_FOR_PUBLIC_GIT", raw)
        self.assertNotIn(b"PRIVATE_FORECAST_NOT_FOR_PUBLIC_GIT", raw)
        self.assertNotIn(b"safe_report", raw)

    def test_same_plaintext_has_distinct_cipher_and_nonce_but_stable_revision_hash(self):
        first, second = map(json.loads, (self.seal(), self.seal()))
        self.assertNotEqual(first["ciphertext_b64"], second["ciphertext_b64"])
        self.assertNotEqual(first["aesgcm_nonce_b64"], second["aesgcm_nonce_b64"])
        self.assertNotEqual(first["rsa_oaep_sha256_wrapped_key_b64"],
                            second["rsa_oaep_sha256_wrapped_key_b64"])
        self.assertEqual(first["evidence_plaintext_sha256"],
                         second["evidence_plaintext_sha256"])

    def test_updated_cipher_hash_cannot_hide_aead_tampering(self):
        doc = json.loads(self.seal())
        cipher = bytearray(base64.b64decode(doc["ciphertext_b64"]))
        cipher[0] ^= 1
        doc["ciphertext_b64"] = base64.b64encode(cipher).decode()
        doc["ciphertext_sha256"] = sha256(cipher).hexdigest()
        with self.assertRaisesRegex(history.OfficialRunHistoryError, "DECRYPTION_FAILED"):
            history.decrypt_evidence(canonical(doc), self.private)

    def test_scope_and_observation_metadata_are_authenticated(self):
        original = json.loads(self.seal())
        for field, replacement in (("day_jst", "2026-11-18"),
                                   ("observed_at", "2026-11-19T19:00:00+09:00"),
                                   ("report_sha256", "0" * 64)):
            doc = dict(original, **{field: replacement})
            with self.subTest(field=field), self.assertRaisesRegex(
                    history.OfficialRunHistoryError, "DECRYPTION_FAILED"):
                history.decrypt_evidence(canonical(doc), self.private)

    def test_wrong_owner_key_is_rejected_before_decryption_or_resealing(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        private = other.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption())
        public = other.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaises(ValueError):
            history.decrypt_evidence(self.seal(), private)
        with self.assertRaises(ValueError):
            history.seal_evidence(payload(), public, DAY, AT)

    def test_invalid_date_naive_time_nonfinite_and_oversized_payload_are_rejected(self):
        with self.assertRaises(ValueError):
            history.seal_evidence(payload(), self.public, "2026-11-32", AT)
        with self.assertRaises(ValueError):
            history.seal_evidence(payload(), self.public, DAY, "2026-11-19T18:00:00")
        with self.assertRaises(ValueError):
            self.seal(dict(payload(), nonfinite=float("nan")))
        with patch.object(history, "MAX_PLAINTEXT_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "TOO_LARGE"):
                self.seal()


class OfficialEvidenceGitRevisions(EvidenceTestFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.origin = self.root / "origin.git"
        git(self.root, "init", "--bare", "-b", archive.BRANCH, str(self.origin))
        self.one = self.root / "one"
        self.two = self.root / "two"
        git(self.root, "clone", str(self.origin), str(self.one))
        git(self.one, "config", "user.name", "Fixture")
        git(self.one, "config", "user.email", "fixture@example.invalid")
        (self.one / "README.md").write_text("SYNTHETIC ONLY\n")
        git(self.one, "add", "README.md")
        git(self.one, "commit", "-m", "existing synthetic history")
        git(self.one, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
        git(self.root, "clone", str(self.origin), str(self.two))

    def append(self, repo, raw, report=None):
        return history.append_revision(
            repo=repo, day=DAY, raw_cipher=raw,
            safe_report=REPORT if report is None else report, synthetic_local=True)

    def read(self, repo=None):
        return history.read_revisions(repo=repo or self.two, day=DAY, synthetic_local=True)

    def test_two_runners_keep_distinct_revisions_and_deduplicate_random_reseal(self):
        original = self.seal()
        receipt = self.append(self.one, original)
        before = git(self.origin, "rev-parse", archive.BRANCH)
        duplicate = self.append(self.two, self.seal(observed_at="2026-11-19T19:00:00+09:00"))
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), before)
        self.assertEqual(duplicate["cipher_sha256"], sha256(original).hexdigest())
        self.assertEqual(duplicate["observed_at"], receipt["observed_at"])
        revised = self.seal(payload(2), observed_at="2026-11-19T19:00:00+09:00")
        self.append(self.two, revised)
        revisions = self.read(self.one)
        self.assertEqual([r["raw_cipher"] for r in revisions], [original, revised])
        self.assertEqual([history.decrypt_evidence(r["raw_cipher"], self.private)["revision"]
                          for r in revisions], [1, 2])
        for row in revisions:
            self.assertEqual(set(row["receipt"]) - {"producer_run_id"}, {
                "schema", "day_jst", "cipher_sha256", "evidence_plaintext_sha256",
                "observed_at", "report_sha256"})
        tree = git(self.one, "ls-tree", "-r", "--name-only",
                   "refs/remotes/origin/" + archive.BRANCH, "--", history.ROOT)
        self.assertEqual(len(tree.splitlines()), 4)
        for path in tree.splitlines():
            public = git(self.one, "show", "refs/remotes/origin/" + archive.BRANCH + ":" + path)
            self.assertNotIn("RAW_PRIVATE_SOURCE_NOT_FOR_PUBLIC_GIT", public)
            self.assertNotIn("PRIVATE_FORECAST_NOT_FOR_PUBLIC_GIT", public)
            self.assertNotIn("scorecard", public)

    def test_report_hash_or_wrong_day_cannot_be_substituted_before_write(self):
        raw = self.seal()
        before = git(self.origin, "rev-parse", archive.BRANCH)
        with self.assertRaisesRegex(history.OfficialRunHistoryError, "REPORT_SHA_MISMATCH"):
            self.append(self.one, raw, dict(REPORT, paired_A_B_scored=1))
        with self.assertRaises(ValueError):
            history.append_revision(repo=self.one, day="2026-11-18", raw_cipher=raw,
                                    safe_report=REPORT, synthetic_local=True)
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), before)

    def test_missing_remote_state_is_not_reinitialized(self):
        empty = self.root / "empty.git"
        other = self.root / "empty-clone"
        git(self.root, "init", "--bare", str(empty))
        git(self.root, "clone", str(empty), str(other))
        with self.assertRaises(archive.GitCipherArchiveError):
            self.append(other, self.seal())
        self.assertEqual(git(empty, "for-each-ref", "--format=%(refname)"), "")

    def test_incomplete_old_revision_holds_instead_of_overwriting(self):
        raw = self.seal()
        receipt = self.append(self.one, raw)
        prefix = f"{history.ROOT}/{DAY}/{receipt['evidence_plaintext_sha256']}"
        git(self.one, "fetch", "origin", archive.BRANCH)
        git(self.one, "checkout", "--detach", "FETCH_HEAD")
        git(self.one, "rm", prefix + ".receipt.json")
        git(self.one, "commit", "-m", "synthetic damaged receipt")
        git(self.one, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
        damaged_head = git(self.origin, "rev-parse", archive.BRANCH)
        with self.assertRaisesRegex(history.OfficialRunHistoryError, "PAIR_INCOMPLETE"):
            self.append(self.two, self.seal())
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), damaged_head)

    def test_git_blob_whitespace_changes_cannot_pass_original_byte_readback(self):
        raw = self.seal()
        receipt = self.append(self.one, raw)
        stem = f"{history.ROOT}/{DAY}/{receipt['evidence_plaintext_sha256']}"
        git(self.one, "fetch", "origin", archive.BRANCH)
        git(self.one, "checkout", "--detach", "FETCH_HEAD")
        path = self.one / (stem + ".sealed.json")
        path.write_bytes(b"\n" + raw + b"\n")
        git(self.one, "add", "--", str(path.relative_to(self.one)))
        git(self.one, "commit", "-m", "synthetic ciphertext whitespace change")
        git(self.one, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
        with self.assertRaisesRegex(history.OfficialRunHistoryError, "CANONICAL_BYTES"):
            self.read()

    def test_oversized_git_blob_is_refused_before_payload_read(self):
        self.append(self.one, self.seal())
        command = archive._cmd
        payload_reads = []

        def observe(repo, *args, **kwargs):
            if "show" in args and any(str(arg).endswith(".sealed.json") for arg in args):
                payload_reads.append(args)
            return command(repo, *args, **kwargs)

        with patch.object(history, "MAX_CIPHER_BYTES", 1000), \
             patch.object(archive, "_cmd", side_effect=observe):
            with self.assertRaises(ValueError):
                self.read()
        self.assertEqual(payload_reads, [])

    def test_aggregate_day_budget_is_checked_before_loading_any_revision(self):
        first, second = self.seal(), self.seal(payload(2))
        self.append(self.one, first)
        self.append(self.two, second)
        reader = archive.read_blob_bytes
        reads = []

        def track(*args, **kwargs):
            reads.append(args[2])
            return reader(*args, **kwargs)

        with patch.object(archive, "read_blob_bytes", side_effect=track):
            with self.assertRaisesRegex(history.OfficialRunHistoryError, "DAY_READ_BUDGET"):
                history.read_revisions(repo=self.one, day=DAY, synthetic_local=True,
                                       max_total_bytes=len(first) + len(second))
        self.assertEqual(reads, [])

    def test_day_revision_limit_refuses_whole_read_without_truncation(self):
        self.append(self.one, self.seal())
        self.append(self.two, self.seal(payload(2)))
        with self.assertRaisesRegex(history.OfficialRunHistoryError, "DAY_REVISION_LIMIT"):
            history.read_revisions(repo=self.one, day=DAY, synthetic_local=True,
                                   max_revisions=1)
        self.assertEqual(len(self.read()), 2)

    def test_day_read_budget_cannot_disable_the_safety_cap(self):
        for invalid in (True, 0, 128 * 1024 * 1024 + 1):
            with self.subTest(limit=invalid), self.assertRaises(ValueError):
                history.read_revisions(repo=self.one, day=DAY, synthetic_local=True,
                                       max_total_bytes=invalid)

    def test_actual_non_fast_forward_race_preserves_both_revisions(self):
        first, second = self.seal(), self.seal(payload(2))
        command = archive._cmd
        collided = []

        def race(repo, *args, **kwargs):
            if args and args[0] == "push" and not collided:
                collided.append(True)
                self.append(self.two, second)
            return command(repo, *args, **kwargs)

        with patch.object(archive, "_cmd", side_effect=race):
            self.append(self.one, first)
        self.assertEqual(len(collided), 1)
        revisions = self.read()
        self.assertEqual({r["raw_cipher"] for r in revisions}, {first, second})


if __name__ == "__main__":
    unittest.main()
