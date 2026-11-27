"""Synthetic local bare Git only. No real owner branch, model source or wagers."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import subprocess
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_nationwide_cipher_history as ledger
from race_ai import keirin_form_fall_shadow as shadow
from scripts import keirin_github_only_ab_day as live
from tests.test_keirin_nationwide_auto_generator import fixture, AT
from tests.test_keirin_rider_form_evidence import pack


def git(path, *args):
    return subprocess.run(
        ["git",*args],cwd=path,check=True,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()


class ArchiveFetchRetryTest(unittest.TestCase):
    def test_opted_in_archive_refresh_retries_only_the_same_timed_out_fetch(self):
        head = 'a' * 40
        with patch.object(ledger.subprocess, 'run', side_effect=[
                subprocess.TimeoutExpired('git fetch', 35),
                subprocess.CompletedProcess([], 0, ''),
                subprocess.CompletedProcess([], 0, head+'\n'),
        ]) as run:
            self.assertEqual(ledger._refresh('/fixture', retry_on_timeout=True), head)
        first, second, rev = run.call_args_list
        self.assertEqual(first.args, second.args)
        self.assertEqual(first.kwargs['timeout'], 35)
        self.assertEqual(second.kwargs['timeout'], 90)
        self.assertIn('rev-parse', rev.args[0])
        self.assertNotIn('--depth=1', first.args[0])
        self.assertNotIn('--filter=blob:none', first.args[0])

    def test_git_rejection_without_timeout_never_retries(self):
        with patch.object(ledger.subprocess, 'run',
                          return_value=subprocess.CompletedProcess([], 1, '')) as run:
            with self.assertRaisesRegex(ledger.GitCipherArchiveError, 'GIT_COMMAND_OR_REMOTE_UNAVAILABLE'):
                ledger._refresh('/fixture', retry_on_timeout=True)
        run.assert_called_once()


class SyntheticGitHubOnlyCipherHistory(unittest.TestCase):
    def setUp(self):
        self.d=TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.root=Path(self.d.name)
        self.origin=self.root/"origin.git"
        git(self.root,"init","--bare","-b",ledger.BRANCH,str(self.origin))
        self.worker1=self.root/"worker1"
        git(self.root,"clone",str(self.origin),str(self.worker1))
        git(self.worker1,"config","user.name","Fixture")
        git(self.worker1,"config","user.email","fixture@example.invalid")
        (self.worker1/"README.md").write_text("SYNTHETIC SOURCE-FREE\n")
        git(self.worker1,"add","README.md")
        git(self.worker1,"commit","-m","initial local test branch")
        git(self.worker1,"push","origin",f"HEAD:refs/heads/{ledger.BRANCH}")
        self.worker2=self.root/"worker2"
        git(self.root,"clone",str(self.origin),str(self.worker2))
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        self.pem=self.key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        pin=sha256(self.key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        mock=patch.object(storage,"PINNED_OWNER_SPKI_SHA256",pin)
        mock.start()
        self.addCleanup(mock.stop)

    def sealed(self,race_id):
        snap=fixture()
        snap["race_id"]=race_id
        predicted=model.generate_A_B(snap,generated_at=AT)
        out=self.root/(race_id+"-"+str(len(list(self.root.glob("*.json"))))+".json")
        stored=storage.seal_once(
            snapshot=snap,prediction=predicted,public_key_pem=self.pem,
            path=out,sealed_at="2026-11-18T09:01:05+09:00")
        data=out.read_bytes()
        return data, stored["cipher_sha256"]

    def put(self,repo,rid,raw=None,sha=None,run="123456"):
        if raw is None:
            raw,sha=self.sealed(rid)
        return ledger.append_once(
            repo=repo,raw_cipher=raw,expected_cipher_sha256=sha,
            producer_run_id=run,producer_commit="a"*40,
            synthetic_local=True)

    def test_two_distinct_runners_append_and_independently_retrieve(self):
        rid1="202611182601";rid2="202611182602"
        raw1,sha1=self.sealed(rid1)
        first=self.put(self.worker1,rid1,raw1,sha1)
        self.assertEqual(first["state"],"GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED")
        self.assertEqual(
            ledger.read_original(repo=self.worker2,race_id=rid1,
                                 expected_cipher_sha256=sha1,
                                 synthetic_local=True)["cipher_sha256"],sha1)
        self.assertEqual(
            self.put(self.worker2,rid1,raw1,sha1)["state"],
            "IDENTICAL_ORIGINAL_ALREADY_FROZEN_NO_NEW_WRITE")
        second=self.put(self.worker2,rid2)
        self.assertEqual(second["state"],"GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED")
        self.assertNotEqual(first["write_commit"],second["write_commit"])
        self.assertEqual(
            ledger.read_original(repo=self.worker1,race_id=rid2,
                                 expected_cipher_sha256=second["cipher_sha256"],
                                 synthetic_local=True)["state"],
            "ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK")
        # Cipher branch contains no unencrypted picks or pre-race fields.
        work=git(self.worker1,"show",
                 f"refs/remotes/origin/{ledger.BRANCH}:{ledger._refs(rid1)[0]}")
        self.assertNotIn("ranked_tickets",work)
        self.assertNotIn("athlete_id",work)

    def test_cold_append_preserves_unrelated_blobs_without_downloading_them(self):
        git(self.origin, "config", "uploadpack.allowFilter", "true")
        git(self.origin, "config", "uploadpack.allowReachableSHA1InWant", "true")
        old_path = "historical-ciphertext"
        (self.worker1 / old_path).write_bytes(b"retained encrypted fixture\x00\n")
        git(self.worker1, "add", old_path)
        git(self.worker1, "commit", "-m", "add unrelated ciphertext")
        git(self.worker1, "push", "origin", f"HEAD:refs/heads/{ledger.BRANCH}")
        parent = git(self.worker1, "rev-parse", "HEAD")
        old_blob = git(self.worker1, "rev-parse", f"{parent}:{old_path}")
        cold = self.root / "cold"
        git(self.root, "init", "-b", "main", str(cold))
        git(cold, "remote", "add", "origin", self.origin.as_uri())
        ref = f"refs/remotes/origin/{ledger.BRANCH}"
        git(cold, "fetch", "--filter=blob:none", "origin", f"refs/heads/{ledger.BRANCH}:{ref}")

        def has_old_blob():
            return subprocess.run(
                ["git", "cat-file", "-e", old_blob], cwd=cold,
                env=dict(os.environ, GIT_NO_LAZY_FETCH="1"), capture_output=True,
                check=False, timeout=5,
            ).returncode == 0

        self.assertFalse(has_old_blob(), "fixture must start without the historical blob")
        result = self.put(cold, "202611182601")
        head = result["write_commit"]
        self.assertEqual(git(self.origin, "rev-parse", f"{head}^"), parent)
        self.assertEqual(git(self.origin, "rev-parse", f"{head}:{old_path}"), old_blob)
        self.assertFalse(has_old_blob(), "appending one race must not hydrate unrelated ciphertext")

    def test_same_race_different_random_cipher_rejected_without_mutation(self):
        rid="202611182601"
        first=self.put(self.worker1,rid)
        original=first["cipher_sha256"]
        other,other_sha=self.sealed(rid)
        self.assertNotEqual(original,other_sha)
        with self.assertRaisesRegex(
                ledger.GitCipherArchiveError,"ALREADY_EXISTS_DIFFERENT"):
            self.put(self.worker2,rid,other,other_sha)
        self.assertEqual(ledger.read_original(
            repo=self.worker2,race_id=rid,
            expected_cipher_sha256=original,synthetic_local=True
        )["cipher_sha256"],original)

    def test_bad_expected_sha_is_rejected_before_git_write(self):
        raw,real=self.sealed("202611182601")
        before=git(self.worker1,"rev-parse","HEAD")
        with self.assertRaisesRegex(
                ledger.GitCipherArchiveError,"NOT_SHA_AUTHENTICATED"):
            self.put(self.worker1,"202611182601",raw,"0"*64)
        self.assertEqual(git(self.worker1,"rev-parse","HEAD"),before)

    def test_missing_state_branch_does_not_reset_an_empty_store(self):
        empty=self.root/"empty.git"
        git(self.root,"init","--bare",str(empty))
        worker=self.root/"other"
        git(self.root,"clone",str(empty),str(worker))
        with self.assertRaises(ledger.GitCipherArchiveError):
            self.put(worker,"202611182601")

    def test_wrong_expected_sha_cannot_read_old_original(self):
        first=self.put(self.worker1,"202611182601")
        with self.assertRaisesRegex(
                ledger.GitCipherArchiveError,"RECEIPT_OR_SHA_MISMATCH"):
            ledger.read_original(
                repo=self.worker2,race_id="202611182601",
                expected_cipher_sha256="0"*64,synthetic_local=True)

    def test_exact_cipher_bytes_survive_whitespace_and_second_runner_readback(self):
        rid = "202611182601"
        canonical, _ = self.sealed(rid)
        original = b"\n" + canonical + b"\n \t"
        digest = sha256(original).hexdigest()
        try:
            stored = self.put(self.worker1, rid, original, digest)
        except ledger.GitCipherArchiveError as exc:
            self.fail("Valid exact ciphertext bytes were not preserved: " + str(exc))
        readback = ledger.read_original(
            repo=self.worker2, race_id=rid,
            expected_cipher_sha256=digest, synthetic_local=True)
        self.assertEqual(readback["cipher_sha256"], digest)
        self.assertEqual(ledger.read_blob_bytes(
            self.worker2, readback["observed_branch_head"], ledger._refs(rid)[0]),
            original)
        second = self.put(self.worker2, rid, original, digest)
        self.assertEqual(second["state"], "IDENTICAL_ORIGINAL_ALREADY_FROZEN_NO_NEW_WRITE")
        self.assertEqual(second["readback_head"], stored["write_commit"])

    def test_binary_blob_reader_bounds_existing_data_and_returns_none_for_missing(self):
        oversized = self.worker1 / "oversized.sealed.json"
        oversized.write_bytes(b"x" * ledger.MAX_BYTES)
        git(self.worker1, "add", oversized.name)
        git(self.worker1, "commit", "-m", "synthetic oversized input")
        head = git(self.worker1, "rev-parse", "HEAD")
        self.assertTrue(hasattr(ledger, "read_blob_bytes"))
        with self.assertRaisesRegex(ledger.GitCipherArchiveError, "BLOB_SIZE"):
            ledger.read_blob_bytes(self.worker1, head, oversized.name)
        self.assertEqual(len(ledger.read_blob_bytes(
            self.worker1, head, oversized.name, max_bytes=ledger.MAX_BYTES + 1)),
            ledger.MAX_BYTES)
        for invalid in (0, -1, True, 32 * 1024 * 1024 + 1):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ledger.GitCipherArchiveError,
                                            "BLOB_READ_LIMIT"):
                    ledger.read_blob_bytes(self.worker1, head, oversized.name,
                                           max_bytes=invalid)
        self.assertIsNone(ledger.read_blob_bytes(
            self.worker1, head, "missing.sealed.json"))

    def condition_pair(self):
        snap = fixture()
        prediction = model.generate_A_B(snap, generated_at=AT)
        normal, normal_sha = self.sealed(snap["race_id"])
        supplement = pack()
        adjusted = shadow.generate_shadow(
            snap, supplement, baseline=prediction, generated_at=AT)
        path = self.root / (str(len(list(self.root.glob("*.json")))) + ".form.sealed.json")
        receipt = shadow.seal_shadow_once(
            snapshot=snap, supplement=supplement, shadow=adjusted,
            public_key_pem=self.pem, path=path,
            sealed_at="2026-11-18T09:01:10+09:00")
        return normal, normal_sha, path.read_bytes(), receipt, prediction

    def test_conditioned_original_survives_independent_git_clone_and_day_restore(self):
        self.assertTrue(callable(getattr(ledger, "append_conditioned_once", None)))
        normal, normal_sha, form, receipt, prediction = self.condition_pair()
        rid = prediction["race_id"]
        ledger.append_once(
            repo=self.worker1, raw_cipher=normal,
            expected_cipher_sha256=normal_sha,
            producer_run_id="123456", producer_commit="a"*40,
            cohort_sha256="d"*64, synthetic_local=True)
        args = dict(repo=self.worker1, raw_cipher=form,
                    expected_cipher_sha256=receipt["file_sha256"],
                    expected_baseline_cipher_sha256=normal_sha,
                    expected_baseline_prediction_sha256=prediction["prediction_sha256"],
                    cohort_sha256="d"*64, producer_run_id="123456",
                    producer_commit="a"*40, synthetic_local=True)
        saved = ledger.append_conditioned_once(**args)
        restored = ledger.read_conditioned_original(
            repo=self.worker2, race_id=rid,
            expected_cipher_sha256=receipt["file_sha256"],
            expected_baseline_cipher_sha256=normal_sha,
            expected_baseline_prediction_sha256=prediction["prediction_sha256"],
            cohort_sha256="d"*64, synthetic_local=True)
        self.assertEqual(restored["state"], "ENCRYPTED_GIT_CONDITIONED_SHA_READBACK_OK")
        self.assertEqual(restored["producer_run_id"], "123456")
        self.assertEqual(restored["cohort_sha256"], "d"*64)
        self.assertEqual(ledger.read_blob_bytes(
            self.worker2, restored["observed_branch_head"], ledger._form_refs(rid)[0]), form)
        again = ledger.append_conditioned_once(**dict(args, repo=self.worker2))
        self.assertEqual(again["state"], "IDENTICAL_CONDITIONED_ORIGINAL_ALREADY_FROZEN")
        self.assertEqual(again["readback_head"], saved["write_commit"])
        with patch.object(ledger, "_remote", side_effect=lambda repo, **_: Path(repo)), \
             patch.object(live.provider_stop, "read_for_observed_day", return_value=None):
            self.assertEqual(live.archived_day(self.worker2, "2026-11-18"),
                             {rid:normal_sha})

    def test_conditioned_archive_requires_matching_run_and_cohort_without_replacing_base(self):
        self.assertTrue(callable(getattr(ledger, "append_conditioned_once", None)))
        normal, normal_sha, form, receipt, prediction = self.condition_pair()
        rid = prediction["race_id"]
        ledger.append_once(
            repo=self.worker1, raw_cipher=normal,
            expected_cipher_sha256=normal_sha,
            producer_run_id="123456", producer_commit="a"*40,
            cohort_sha256="d"*64, synthetic_local=True)
        args = dict(repo=self.worker2, raw_cipher=form,
                    expected_cipher_sha256=receipt["file_sha256"],
                    expected_baseline_cipher_sha256=normal_sha,
                    expected_baseline_prediction_sha256=prediction["prediction_sha256"],
                    cohort_sha256="d"*64, producer_run_id="123456",
                    producer_commit="a"*40, synthetic_local=True)
        for changed in ({"producer_run_id":"999999"},
                        {"producer_commit":"b"*40}, {"cohort_sha256":"e"*64},
                        {"expected_baseline_prediction_sha256":"f"*64}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                ledger.append_conditioned_once(**dict(args, **changed))
        ledger.append_conditioned_once(**args)
        other = form + b"\n"
        with self.assertRaisesRegex(ledger.GitCipherArchiveError, "ALREADY_EXISTS_DIFFERENT"):
            ledger.append_conditioned_once(**dict(args, raw_cipher=other,
                expected_cipher_sha256=sha256(other).hexdigest()))
        restored = ledger.read_original(repo=self.worker2, race_id=rid,
            expected_cipher_sha256=normal_sha, synthetic_local=True)
        self.assertEqual(restored["cipher_sha256"], normal_sha)


if __name__=="__main__":
    unittest.main()
