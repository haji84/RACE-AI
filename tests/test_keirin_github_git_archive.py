"""Actual local Git push/fetch archive tests, using SYNTHETIC SQLite only."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import shutil
import sqlite3
import subprocess
import unittest

from scripts import keirin_github_git_archive as archive

REPO="haji84/RACE-AI"
PRODUCER_RUN="123456"
PRODUCER_SHA="a"*40


def shell(*args,cwd=None):
    r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,check=True)
    return r.stdout.strip()


class EncryptedGitHistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        base=Path(self.folder.name)
        self.remote=base/"remote.git"
        shell("git","init","--bare","--initial-branch=main",str(self.remote))
        self.repo=base/"repo"
        shell("git","clone",str(self.remote),str(self.repo))
        (self.repo/"scripts").mkdir()
        shutil.copy2(Path(__file__).resolve().parents[1]/
                     "scripts"/"keirin_github_checkpoint.mjs",
                     self.repo/"scripts"/"keirin_github_checkpoint.mjs")
        (self.repo/"README.md").write_text("Synthetic test repo\n")
        shell("git","add",".",cwd=self.repo)
        shell("git","-c","user.email=local-test@example.test",
              "-c","user.name=fixture","commit","-m","base",cwd=self.repo)
        shell("git","push","origin","main",cwd=self.repo)
        shell("git","checkout","-b",archive.STATE_BRANCH,cwd=self.repo)
        (self.repo/"state"/"keirin"/"v1").mkdir(parents=True)
        (self.repo/"state"/"keirin"/"v1"/"README.md").write_text(
            "Only ciphertext. Never plaintext.\n")
        shell("git","add",".",cwd=self.repo)
        shell("git","-c","user.email=local-test@example.test",
              "-c","user.name=fixture","commit","-m","initialize",cwd=self.repo)
        shell("git","push","origin",archive.STATE_BRANCH,cwd=self.repo)
        shell("git","checkout","main",cwd=self.repo)
        self.artifacts=base/"artifacts"
        self.artifacts.mkdir()

    def bundle(self,generation=1,previous=None):
        path=self.artifacts/str(generation)
        path.mkdir()
        scope={"schema":"RACE_AI_GITHUB_SQLITE_V1",
               "repository_id":archive.REPOSITORY_ID,
               "mode":"synthetic",
               "generation":generation,
               "previous_cipher_sha256":previous}
        (path/"scope.json").write_text(json.dumps(scope))
        db=path/"sample.sqlite3"
        with sqlite3.connect(db) as con:
            con.execute("CREATE TABLE forecast (id TEXT PRIMARY KEY, pick TEXT)")
            con.execute("INSERT INTO forecast VALUES ('F1', '1-2-3')")
        shell("node",str(self.repo/"scripts"/"keirin_github_checkpoint.mjs"),
              "seal",str(db),str(path/"state.enc"),
              str(path/"scope.json"),cwd=self.repo)
        cipher=sha256((path/"state.enc").read_bytes()).hexdigest()
        proof={
            "synthetic_only":True,"cipher_sha256":cipher,
            "snapshot_sha256":sha256(db.read_bytes()).hexdigest(),
            "forecast_sha256":"f"*64,
            "producer_run_id":PRODUCER_RUN,
            "producer_sha":PRODUCER_SHA
        }
        (path/"fixture-proof.json").write_text(json.dumps(proof))
        return path,cipher

    def archive(self,artifact,**changes):
        original=archive.command
        def local_git(args,**kwargs):
            if args[:4]==["git","remote","get-url","origin"]:
                return "https://github.com/haji84/RACE-AI"
            return original(args,**kwargs)
        with patch.object(archive,"command",side_effect=local_git):
            with patch.dict(os.environ,{"GITHUB_ACTIONS":""}):
                return archive.archive_in_git(
                    artifact,repo=self.repo,
                    expected_run_id=PRODUCER_RUN,
                    expected_commit=PRODUCER_SHA,**changes)

    def test_real_git_commit_durable_two_generations(self):
        a,h1=self.bundle()
        first=self.archive(a)
        self.assertEqual(first["status"],"ENCRYPTED_GIT_HISTORY_ARCHIVED")
        self.assertEqual(first["generation"],1)
        self.assertTrue(first["public_ciphertext_visible"])
        again=self.archive(a)
        self.assertEqual(again["status"],"ARCHIVE_ALREADY_COMMITTED")
        b,h2=self.bundle(generation=2,previous=h1)
        second=self.archive(b)
        self.assertEqual(second["generation"],2)
        self.assertNotEqual(h1,h2)
        remote=Path(self.folder.name)/"readback"
        shell("git","clone","--branch",archive.STATE_BRANCH,
              str(self.remote),str(remote))
        manifest=json.loads((remote/"state"/"keirin"/"v1"/"latest.json").read_text())
        self.assertEqual(manifest["generation"],2)
        self.assertEqual(manifest["previous_cipher_sha256"],h1)
        self.assertEqual(manifest["cipher_sha256"],h2)
        self.assertEqual(sha256((remote/manifest["snapshot_file"]).read_bytes()).hexdigest(),h2)
        self.assertTrue(any(x.name.endswith(".enc") for x in (
            remote/"state"/"keirin"/"v1"/"snapshots").iterdir()))
        plaintext_files=list(remote.rglob("*.sqlite3"))+list(remote.rglob("*.db"))
        self.assertEqual(plaintext_files,[])
        self.assertIn(first["git_commit"],
                      shell("git","-C",str(remote),"log","--pretty=%H"))

    def test_rewind_and_wrong_history_fail_without_new_commit(self):
        a,h1=self.bundle()
        self.archive(a)
        b,h2=self.bundle(generation=2,previous="0"*64)
        with self.assertRaisesRegex(archive.ArchiveError,"NONCONTIGUOUS_OR_REWINDING"):
            self.archive(b)
        self.assertEqual(len(shell("git","--git-dir",str(self.remote),
                "log","--format=%h",archive.STATE_BRANCH).splitlines()),3)

    def test_new_git_clone_restores_cipher_without_actions_artifact(self):
        from scripts.keirin_github_git_archive_restore import restore_from_git
        a,digest=self.bundle()
        self.archive(a)
        fresh=Path(self.folder.name)/"fresh-independent-checkout"
        shell("git","clone",str(self.remote),str(fresh))
        original=archive.command
        def local_git(args,**kwargs):
            if args[:4]==["git","remote","get-url","origin"]:
                return "https://github.com/haji84/RACE-AI"
            return original(args,**kwargs)
        with patch.object(archive,"command",side_effect=local_git):
            with patch("scripts.keirin_github_git_archive_restore.command",
                       side_effect=local_git):
                with patch.dict(os.environ,{"GITHUB_ACTIONS":""}):
                    restored=restore_from_git(repo=fresh,
                                              continue_synthetic=False)
        self.assertEqual(restored["status"],
                         "CIPHERTEXT_VERIFIED_FROM_GIT_BRANCH")
        self.assertEqual(restored["cipher_sha256"],digest)
        self.assertFalse(restored["artifact_retention_dependency"])
        self.assertFalse(restored["plaintext_published"])

    def test_invalid_producer_or_cipher_mismatch_rejected(self):
        a,_=self.bundle()
        with self.assertRaisesRegex(archive.ArchiveError,"PRODUCER_IDENTITY_MISMATCH"):
            archive.validate_bundle(a,expected_run_id="999999",
                                   expected_commit=PRODUCER_SHA)
        with (a/"state.enc").open("ab") as out:
            out.write(b"tamper")
        with self.assertRaisesRegex(archive.ArchiveError,"CIPHERTEXT_HASH_MISMATCH"):
            archive.validate_bundle(a,expected_run_id=PRODUCER_RUN,
                                   expected_commit=PRODUCER_SHA)

    def test_public_key_ciphertext_cannot_be_promoted_to_production(self):
        a,_=self.bundle()
        scope=json.loads((a/"scope.json").read_text())
        scope["mode"]="production"
        (a/"scope.json").write_text(json.dumps(scope))
        with self.assertRaisesRegex(archive.ArchiveError,"UNEXPECTED_ARCHIVE_MODE"):
            archive.validate_bundle(a,expected_run_id=PRODUCER_RUN,
                                   expected_commit=PRODUCER_SHA)

    def test_remote_read_failure_must_not_be_claimed_success(self):
        a,_=self.bundle()
        shell("git","--git-dir",str(self.remote),
              "update-ref","-d","refs/heads/"+archive.STATE_BRANCH)
        with self.assertRaises(archive.ArchiveError):
            self.archive(a)

    def test_no_github_automation_from_untrusted_branch(self):
        a,_=self.bundle()
        with patch.dict(os.environ,{
            "GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":REPO,
            "GITHUB_REPOSITORY_ID":archive.REPOSITORY_ID,
            "GITHUB_REF":"refs/pull/5/merge",
            "GITHUB_EVENT_NAME":"pull_request"
        }):
            with self.assertRaisesRegex(archive.ArchiveError,
                                        "UNTRUSTED_ACTIONS_ARCHIVE_ORIGIN"):
                archive.archive_in_git(a,repo=self.repo,
                    expected_run_id=PRODUCER_RUN,
                    expected_commit=PRODUCER_SHA,
                    verify_snapshot=False)


if __name__=="__main__":
    unittest.main()
