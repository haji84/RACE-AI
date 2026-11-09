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

    def test_all_four_variable_selections_trigger_new_aes_generation(self):
        # Fully fictional odds and riders, no real provider and no public
        # plaintext. A sidecar-only update must be durably encrypted.
        from race_ai.keirin_variable_selection import ODDS_SCHEMA
        from scripts.keirin_cloud_pr71_variable import FourModelVariableLedger
        original = self.frozen()
        first = cloud.commit(self.repo,self.source,self.db,None)
        replay = self.root/"variable-restored.sqlite3"
        prior,verified = cloud.restore(self.repo,self.source,replay)
        self.assertEqual(verified["frozen"],1)
        now = datetime.fromisoformat("2030-01-15T09:21:00+09:00")
        with PrivateKeirinStore(replay,clock=lambda:now) as store:
            frozen=FourModelRankLedger(store).read_suite(RID)
            self.assertEqual(frozen["suite"]["suite_sha256"],original)
            candidate=frozen["suite"]["models"][ALL_MODELS[0]]["candidates"]
            odds={
                "schema":ODDS_SCHEMA,"race_id":RID,
                "captured_at":now.isoformat(),
                "source_ref":"synthetic://fictional-odds",
                "source_rights_ref":"SYNTHETIC_ONLY",
                "prices":[{"triple":r["combination"],"decimal_odds":1000.0}
                          for r in candidate]
            }
            sidecars=FourModelVariableLedger(store)
            self.assertEqual(sidecars.freeze_four_once(RID,odds),4)
            self.assertEqual(len(sidecars.inventory()),4)
            self.assertEqual(FourModelRankLedger(store).read_suite(RID)[
                "suite"]["suite_sha256"],original)
        second=cloud.commit(self.repo,self.source,replay,prior)
        self.assertEqual(second["generation"],2)
        self.assertNotEqual(second["cipher_sha256"],first["cipher_sha256"])
        fresh=self.root/"variable-independent-runner.sqlite3"
        new_head,new_inventory=cloud.restore(self.repo,self.source,fresh)
        self.assertEqual(new_head["generation"],2)
        self.assertEqual(new_head["previous_cipher_sha256"],
                         first["cipher_sha256"])
        self.assertEqual(new_inventory["frozen"],1)
        self.assertEqual(new_inventory["revisions"],0)
        with PrivateKeirinStore(fresh) as store:
            self.assertEqual(len(FourModelVariableLedger(store).inventory()),4)
            self.assertEqual(FourModelRankLedger(store).read_suite(RID)[
                "suite"]["suite_sha256"],original)
        self.assertEqual(cloud._pr71_inventory(fresh),new_inventory)

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

    def test_hosted_cycle_consumes_authorized_v3_revisions_without_new_forecast(self):
        # The actual cloud.cycle() must use the SAME source/4-model/AES code.
        # Every rider, supplier, grant and result below is synthetic.
        from hashlib import sha256
        from race_ai.keirin_permissioned_owner import (
            MANIFEST,load_operator_grants
        )
        from race_ai.keirin_licensed_result_stage import (
            ROW_SCHEMA,stage_licensed_result_export
        )
        original=self.frozen()
        first=cloud.commit(self.repo,self.source,self.db,None)
        doc=self.root/"synthetic-provider-rights.txt"
        doc.write_text("FICTIONAL TEST RECORD. NOT A REAL PROVIDER GRANT.")
        origin="https://example.invalid/fictional-feed/"
        grants_data={
            "schema":MANIFEST,"bundle_id":"FICTIONAL_PROVIDER_TEST_ONLY",
            "grants":[{
                "source_url_prefix":origin,
                "rights_ref":"FICTIONAL_RESULT_GRANT",
                "purposes":[
                    "schedule","pre_race","analysis","model_inference",
                    "private_retention","automated_fetch",
                    "result_collection","result_analysis"],
                "valid_from":"2030-01-01T00:00:00+09:00",
                "valid_until":"2030-02-01T00:00:00+09:00",
                "license_document_path":str(doc),
                "license_document_sha256":sha256(doc.read_bytes()).hexdigest(),
            }]
        }
        grants_file=self.root/"synthetic-provider-manifest.json"
        grants_file.write_text(json.dumps(grants_data))
        now="2030-01-15T10:40:00+09:00"
        grants=load_operator_grants(grants_file,now=now)
        row={
            "schema":ROW_SCHEMA,"race_id":RID,
            "source_url":origin+"results/one",
            "rights_ref":"FICTIONAL_RESULT_GRANT",
            "source_published_at":"2030-01-15T10:15:00+09:00",
            "observed_at":"2030-01-15T10:15:00+09:00",
            "provider_revision_ref":"fictional-revision-1",
            "status":"FINAL_NORMAL","refund_status":"NONE",
            "winning_triples":[[1,2,3]],
            "payouts_100yen":[{"triple":[1,2,3],"yen":18700}],
        }
        def fictitious_feed(inbox,_source_root):
            admitted=stage_licensed_result_export(
                inbox,[row],checked_at=now,grants=grants)
            self.assertEqual(admitted["private_results_created"],1)
            return grants,{"new_pre_race_inputs":0},"SYNTHETIC_FEED_FOR_CI_ONLY"
        trusted_event={
            "GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":cloud.REPO,
            "GITHUB_REPOSITORY_ID":cloud.REPOSITORY_ID,
            "GITHUB_REF":"refs/heads/main",
            "GITHUB_EVENT_NAME":"schedule",
        }
        with patch.dict(os.environ,trusted_event),patch.object(
            cloud,"_licensed_inputs",side_effect=fictitious_feed
        ),patch.object(cloud,"PrivateKeirinStore",
                       side_effect=lambda path:PrivateKeirinStore(
                           path,clock=lambda:datetime.fromisoformat(now))):
            result=cloud.cycle(self.repo,self.source)
            self.assertEqual(result["state"],
                             "CLOUD_PR71_ENCRYPTED_GIT_HISTORY_READBACK_VERIFIED")
            self.assertEqual(result["generation"],2)
            self.assertEqual(result["result_rows_appended"],1)
            self.assertFalse(result["official_result_independently_authenticated"])
            self.assertFalse(result["formal_accuracy_calculated"])
            repeated=cloud.cycle(self.repo,self.source)
            self.assertEqual(repeated["state"],
                             "CLOUD_PR71_RESTORED_NO_CHANGED_MODEL_OR_RESULT")
            self.assertEqual(repeated["result_rows_appended"],0)
            # A later provider revision is a NEW result generation, never a
            # replacement for the previously frozen prediction or result.
            row["provider_revision_ref"]="fictional-revision-2"
            row["source_published_at"]="2030-01-15T10:20:00+09:00"
            row["observed_at"]="2030-01-15T10:20:00+09:00"
            row["winning_triples"]=[[4,5,6]]
            row["payouts_100yen"]=[{"triple":[4,5,6],"yen":22000}]
            corrected=cloud.cycle(self.repo,self.source)
            self.assertEqual(corrected["state"],
                             "CLOUD_PR71_ENCRYPTED_GIT_HISTORY_READBACK_VERIFIED")
            self.assertEqual(corrected["generation"],3)
            self.assertEqual(corrected["result_rows_appended"],1)
            self.assertNotEqual(corrected["cipher_sha256"],
                                result["cipher_sha256"])
            self.assertEqual(cloud.cycle(self.repo,self.source)["state"],
                             "CLOUD_PR71_RESTORED_NO_CHANGED_MODEL_OR_RESULT")
        reread=self.root/"independent-real-code.sqlite3"
        head,verified=cloud.restore(self.repo,self.source,reread)
        self.assertEqual(head["generation"],3)
        self.assertEqual(head["previous_cipher_sha256"],
                         result["cipher_sha256"])
        self.assertEqual(verified["revisions"],2)
        with PrivateKeirinStore(reread) as store:
            ledger=FourModelRankLedger(store)
            self.assertEqual(ledger.read_suite(RID)["suite"]["suite_sha256"],
                             original)
            audited=ledger.audit_revision(RID)
            self.assertEqual(set(audited),set(ALL_MODELS))
            self.assertTrue(all(
                record["result_status"]=="SETTLED_RESEARCH" and
                record["result_revision"]==2 and
                record["official_result_independently_authenticated"] is False
                for record in audited.values()))
            self.assertEqual(ledger.replay_all()["latest_model_race_audits"],4)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM result_revisions").fetchone()[0],2)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM keirin_pr71_four_model_rank_audits"
            ).fetchone()[0],8)

    def test_restored_four_model_archive_survives_missing_new_licensed_feed(self):
        # Real unattended schedules may find no licensed source. A missing
        # feed must NOT reset the PR71 original or create a fake generation.
        original=self.frozen()
        saved=cloud.commit(self.repo,self.source,self.db,None)
        event={
            "GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":cloud.REPO,
            "GITHUB_REPOSITORY_ID":cloud.REPOSITORY_ID,
            "GITHUB_REF":"refs/heads/main",
            "GITHUB_EVENT_NAME":"schedule",
        }
        with patch.dict(os.environ,event),patch.object(
                cloud,"_licensed_inputs",
                return_value=(None,None,"SOURCE_FEED_NOT_CONFIGURED")):
            report=cloud.cycle(self.repo,self.source)
        self.assertEqual(report["state"],
                         "CLOUD_PR71_RESTORED_NO_CHANGED_MODEL_OR_RESULT")
        self.assertEqual(report["new_forecasts"],0)
        self.assertEqual(report["source_state"],"SOURCE_FEED_NOT_CONFIGURED")
        target=self.root/"recovered-without-new-feed.sqlite3"
        head,verified=cloud.restore(self.repo,self.source,target)
        self.assertEqual(head["generation"],1)
        self.assertEqual(head["cipher_sha256"],saved["cipher_sha256"])
        self.assertEqual(verified["frozen"],1)
        with PrivateKeirinStore(target) as store:
            self.assertEqual(FourModelRankLedger(store).read_suite(RID)[
                "suite"]["suite_sha256"],original)
        listing=sh("git","--git-dir",str(self.remote),"ls-tree","-r",
                   "--name-only",cloud.STATE_BRANCH)
        self.assertNotIn("g000002-",listing)

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
