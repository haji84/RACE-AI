"""Offline real PR71 *code* + AES-256-GCM Git persistence, synthetic riders.

No live bookmaker access, no real result, no public rider/plaintext upload.
Uses the actual existing 4-model engine and Node production codec.
"""
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import base64
import json
import os
import shutil
import subprocess
import unittest

from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from race_ai.four_sport_model_suite import ALL_MODELS
from scripts import keirin_cloud_pr71_state as cloud
from test_keirin_pr71_model_adapter import make_sources, RID


def sh(*args,cwd=None):
    return subprocess.run(args,cwd=cwd,capture_output=True,
                          text=True,check=True,timeout=18).stdout.strip()


class CloudPr71GitHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.repo=self.root/"main"
        self.remote=self.root/"origin.git"
        sh("git","init","--bare","--initial-branch=main",str(self.remote))
        sh("git","clone",str(self.remote),str(self.repo))
        (self.repo/"README.md").write_text("fictional offline test only\n")
        sh("git","add","README.md",cwd=self.repo)
        self.commit("main initial state")
        sh("git","push","origin","main",cwd=self.repo)
        sh("git","checkout","-b",cloud.STATE_BRANCH,cwd=self.repo)
        sy=self.repo/"state/keirin/v1/README.md"
        sy.parent.mkdir(parents=True)
        sy.write_text("EXISTING SYNTHETIC STATE MUST SURVIVE\n")
        sh("git","add",".",cwd=self.repo)
        self.commit("preserve existing synthetic lineage")
        sh("git","push","origin",cloud.STATE_BRANCH,cwd=self.repo)
        sh("git","checkout","main",cwd=self.repo)
        source=os.getenv("RACE_AI_PR71_PINNED_SOURCE_ROOT")
        self.source=Path(source).resolve() if source else Path(
            __file__).resolve().parents[1]
        self.assertTrue((self.source/"scripts/keirin_github_checkpoint.mjs").is_file())
        self.db=self.root/"model.sqlite3"
        self.key=base64.b64encode(os.urandom(32)).decode("ascii")
        env=patch.dict(os.environ,{"RACE_AI_STATE_KEY":self.key})
        env.start()
        self.addCleanup(env.stop)
        underlying_git=cloud.git
        def local(*args):
            repo,*commands=args
            if commands==["remote","get-url","origin"]:
                return "https://github.com/"+cloud.REPO
            return underlying_git(repo,*commands)
        gitpatch=patch.object(cloud,"git",side_effect=local)
        gitpatch.start()
        self.addCleanup(gitpatch.stop)

    def commit(self,description):
        sh("git","-c","user.name=unit",
           "-c","user.email=unit@example.invalid",
           "commit","-m",description,cwd=self.repo)

    def frozen(self):
        stamp=datetime.fromisoformat("2030-01-15T09:21:00+09:00")
        with PrivateKeirinStore(self.db,clock=lambda:stamp) as db:
            ledger=FourModelRankLedger(db)
            result=ledger.freeze_once(make_sources()[0])
            self.assertEqual(result,"FOUR_MODELS_FROZEN_ONCE")
            saved=ledger.read_suite(RID)
            self.assertEqual(tuple(saved["suite"]["models"]),ALL_MODELS)
            self.assertEqual(len(saved["suite"]["models"]),4)
            self.assertEqual(saved["suite"]["model_count"],4)
            return saved["suite"]["suite_sha256"]

    def test_real_four_model_code_aes_checkpoint_and_second_runner_restore(self):
        original=self.frozen()
        created=cloud.commit(self.repo,self.source,self.db,None)
        self.assertEqual(created["generation"],1)
        self.assertTrue(created["all_four_original_models_verified"])
        self.assertFalse(created["owner_plaintext_public"])
        new=self.root/"independent.sqlite3"
        head,verified=cloud.restore(self.repo,self.source,new)
        self.assertEqual(head["generation"],1)
        self.assertEqual(head["cipher_sha256"],created["cipher_sha256"])
        self.assertEqual(verified["frozen"],1)
        with PrivateKeirinStore(new) as store:
            reread=FourModelRankLedger(store).read_suite(RID)
            self.assertEqual(reread["suite"]["suite_sha256"],original)
            self.assertEqual(tuple(reread["suite"]["models"]),ALL_MODELS)
        state=sh("git","--git-dir",str(self.remote),
                 "ls-tree","-r","--name-only",cloud.STATE_BRANCH)
        self.assertIn("state/keirin/v1/README.md",state)
        self.assertIn("state/keirin/pr71-production/v1/latest.json",state)
        self.assertNotIn(".sqlite3",state)
        self.assertNotIn("fictional-rider",state)
        self.assertNotIn("result_revisions",state)

    def test_second_generation_retains_unchanged_4_model_original(self):
        original=self.frozen()
        first=cloud.commit(self.repo,self.source,self.db,None)
        restored=self.root/"restored.sqlite3"
        prior,verified=cloud.restore(self.repo,self.source,restored)
        self.assertEqual(verified["frozen"],1)
        with PrivateKeirinStore(restored) as db:
            # Only the pre-existing PR71 result-revision API can add the
            # result. No original model output can be overwritten.
            stamp=datetime.fromisoformat("2030-01-15T10:40:00+09:00")
            db.clock=lambda:stamp
            db.add_result_observation({
                "race_id":RID,"observed_at":"2030-01-15T10:15:00+09:00",
                "source_sha256":"a"*64,"status":"PENDING",
                "refund_status":"UNKNOWN",
                "winning_triples":[],"payouts_100yen":[],
            })
            FourModelRankLedger(db).replay_all()
        second=cloud.commit(self.repo,self.source,restored,prior)
        self.assertEqual(second["generation"],2)
        self.assertNotEqual(second["cipher_sha256"],first["cipher_sha256"])
        next_db=self.root/"third.sqlite3"
        head,verification=cloud.restore(self.repo,self.source,next_db)
        self.assertEqual(head["previous_cipher_sha256"],
                         first["cipher_sha256"])
        self.assertEqual(verification["frozen"],1)
        self.assertEqual(verification["revisions"],1)
        with PrivateKeirinStore(next_db) as store:
            self.assertEqual(FourModelRankLedger(store).read_suite(RID)[
                "suite"]["suite_sha256"],original)
        snap_paths=sh("git","--git-dir",str(self.remote),"ls-tree",
                      "-r","--name-only",cloud.STATE_BRANCH)
        self.assertIn(first["cipher_sha256"],snap_paths)
        self.assertIn(second["cipher_sha256"],snap_paths)

    def test_missing_original_refuses_production_archive(self):
        with PrivateKeirinStore(self.db):
            pass
        with self.assertRaisesRegex(cloud.ArchiveError,
                                    "PR71_FOUR_MODEL_DB_SCHEMA_REQUIRED"):
            cloud.commit(self.repo,self.source,self.db,None)
        files=sh("git","--git-dir",str(self.remote),"ls-tree",
                 "-r","--name-only",cloud.STATE_BRANCH)
        self.assertNotIn("pr71-production",files)

    def test_wrong_key_fails_before_claiming_readback(self):
        self.frozen()
        cloud.commit(self.repo,self.source,self.db,None)
        bad=base64.b64encode(os.urandom(32)).decode()
        with patch.dict(os.environ,{"RACE_AI_STATE_KEY":bad}):
            with self.assertRaises(cloud.ArchiveError):
                cloud.restore(self.repo,self.source,
                              self.root/"bad-key.sqlite3")

    def test_stale_prior_cannot_publish_over_another_generation(self):
        self.frozen()
        cloud.commit(self.repo,self.source,self.db,None)
        # A stale writer still believes there is no first generation.
        with self.assertRaisesRegex(cloud.ArchiveError,
                                    "STATE_BRANCH_CHANGED_SINCE_LAST_RESTORE"):
            cloud.commit(self.repo,self.source,self.db,None)

    def test_no_source_no_production_genesis_and_no_model_invention(self):
        env={
            "GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":cloud.REPO,
            "GITHUB_REPOSITORY_ID":cloud.REPOSITORY_ID,
            "GITHUB_REF":"refs/heads/main",
            "GITHUB_EVENT_NAME":"schedule",
        }
        with patch.dict(os.environ,env):
            report=cloud.cycle(self.repo,self.source)
        self.assertEqual(report["state"],
                         "HOLD_NO_LICENSED_FUTURE_SOURCE_AND_NO_PRODUCTION_ORIGINAL")
        self.assertEqual(report["new_forecasts"],0)
        files=sh("git","--git-dir",str(self.remote),"ls-tree",
                 "-r","--name-only",cloud.STATE_BRANCH)
        self.assertNotIn("pr71-production",files)

    def test_untrusted_pull_request_and_wrong_repo_cannot_run(self):
        for wrong in ({"GITHUB_EVENT_NAME":"pull_request"},
                      {"GITHUB_REPOSITORY":"another/repo"},
                      {"GITHUB_REF":"refs/heads/feature"}):
            env={"GITHUB_ACTIONS":"true",
                 "GITHUB_REPOSITORY":cloud.REPO,
                 "GITHUB_REPOSITORY_ID":cloud.REPOSITORY_ID,
                 "GITHUB_REF":"refs/heads/main",
                 "GITHUB_EVENT_NAME":"schedule",**wrong}
            with self.subTest(wrong=wrong),patch.dict(os.environ,env):
                with self.assertRaisesRegex(cloud.ArchiveError,
                                            "TRUSTED_GITHUB_MAIN_SCHEDULE_REQUIRED"):
                    cloud.cycle(self.repo,self.source)


if __name__=="__main__":
    unittest.main()
