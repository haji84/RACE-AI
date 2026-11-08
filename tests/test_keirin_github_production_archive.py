"""End-to-end local-only production-format crypto regression with fictional riders.

No real RACE-AI owner DB, provider licence, GitHub secret or real race odds is
used. These tests exercise the strict promotion gate without ever granting
production permissions in a GitHub pull_request.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from itertools import permutations
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import base64
import json
import os
import shutil
import subprocess
import unittest

from race_ai.keirin_permissioned_owner import (
    load_operator_grants, MANIFEST
)
from race_ai.keirin_real_rider_shadow import forecast_from_real_observations
from race_ai.keirin_shadow_variable_pair import (
    choose_shadow_variable, ShadowVariablePairLedger
)
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_variable_selection import ODDS_SCHEMA
from scripts import keirin_github_production_archive as archive
from scripts.keirin_github_production_bundle import create_production_bundle
from test_keirin_real_rider_shadow import fixture

REPO="haji84/RACE-AI"
PRODUCER_SHA="a"*40
PRODUCER_RUN="123456"
NOW="2030-01-15T09:26:00+09:00"
SELECTED="2030-01-15T09:23:00+09:00"
CUTOFF="2030-01-15T10:00:00+09:00"
SOURCE="https://example.invalid/fictional-feed/one"
RIGHTS="FICTIONAL_MACHINE_RIGHTS_ONLY"
BUNDLE="FAKE_PROVIDER_DOCUMENT_CANNOT_AUTHORIZE_REAL_DATA"


def sh(*args,cwd=None):
    r=subprocess.run(args,cwd=cwd,capture_output=True,check=True,text=True,
                     timeout=20)
    return r.stdout.strip()


class ExistingProductionGateSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.src=Path(__file__).resolve().parents[1]
        self.key=base64.b64encode(os.urandom(32)).decode()
        self.db=self.root/"private"/"existing_owner.sqlite3"
        self.db.parent.mkdir()
        self.document=self.root/"private"/"fictional-rights.txt"
        self.document.write_text("FICTIONAL TEST: NOT A LIVE PROVIDER LICENCE")
        self.manifest=self.root/"private"/"grants.json"
        value={
            "schema":MANIFEST,
            "bundle_id":BUNDLE,
            "grants":[{
                "source_url_prefix":"https://example.invalid/fictional-feed/",
                "rights_ref":RIGHTS,
                "purposes":["schedule","pre_race","analysis",
                            "model_inference","private_retention","automated_fetch"],
                "valid_from":"2020-01-01T00:00:00+09:00",
                "valid_until":"2040-01-01T00:00:00+09:00",
                "license_document_path":str(self.document),
                "license_document_sha256":
                    sha256(self.document.read_bytes()).hexdigest(),
            }]
        }
        self.manifest.write_text(json.dumps(value))
        grants=load_operator_grants(self.manifest,now=NOW)
        packet=fixture()
        packet["race"]["permission_ref"]=BUNDLE
        for row in packet["observations"]:
            row["source_url"]=SOURCE
            row["rights_ref"]=RIGHTS
        self.packet=packet
        shadow=forecast_from_real_observations(
            packet,grant_check=grants.allowed,
            issued_at="2030-01-15T09:20:00+09:00")
        self.shadow=shadow
        odds={
            "schema":ODDS_SCHEMA,
            "race_id":packet["race"]["race_id"],
            "captured_at":"2030-01-15T09:22:00+09:00",
            "source_ref":"https://example.invalid/fictional-feed/odds",
            "source_rights_ref":RIGHTS,
            "prices":[{
                "triple":row["triple"],
                "decimal_odds":100.0+i/10
            } for i,row in enumerate(
                shadow["ranked_candidates_untrained_not_probabilities"])]
        }
        self.odds=odds
        selected=choose_shadow_variable(
            shadow,odds,decided_at=SELECTED,odds_allowed=grants.allowed)
        with PrivateKeirinStore(
                self.db,clock=lambda:datetime.fromisoformat(
                    "2030-01-15T09:25:00+09:00")) as store:
            ledger=ShadowVariablePairLedger(store)
            made=ledger.freeze_pair_once(
                shadow,selected,odds,source_packet=packet)
            self.assertEqual(made,"CREATED_PAIR_ONCE")
        self.out=self.root/"sealed"

    def seal(self):
        with patch.dict(os.environ,{"GITHUB_ACTIONS":"false",
                                     "RACE_AI_STATE_KEY":self.key}):
            return create_production_bundle(
                self.db,self.manifest,self.out,
                source_repo=self.src,
                race_id=self.packet["race"]["race_id"],
                generation=1,previous_cipher_sha256=None,
                producer_run_id=PRODUCER_RUN,
                producer_sha=PRODUCER_SHA,checked_at=NOW)

    def test_existing_db_frozen_pair_and_full_210_are_sealed_with_private_key(self):
        out=self.seal()
        self.assertEqual(out["state"],"READY_BUT_NOT_PUBLISHED")
        self.assertTrue(out["full_210_or_504_odds_checked"])
        self.assertFalse(out["trusted_git_archive_committed"])
        self.assertFalse(out["independent_external_pre_cutoff_witness"])
        with patch.dict(os.environ,{"RACE_AI_STATE_KEY":self.key}):
            scope,proof,cipher,digest=archive.validate_production_bundle(
                self.out,repo=self.src,license_manifest=self.manifest,
                expected_run_id=PRODUCER_RUN,
                expected_commit=PRODUCER_SHA)
        self.assertEqual(scope["mode"],"production")
        self.assertFalse(proof["synthetic_only"])
        self.assertEqual(sha256(cipher).hexdigest(),digest)
        self.assertEqual(proof["original_sha256"],
                         self.shadow["research_sha256"])
        self.assertFalse(proof["external_timestamp_attested"])
        self.assertEqual(len(list(self.out.glob("*.json"))),2)
        self.assertFalse(any(
            file.name.endswith((".db",".sqlite3")) for file in
            self.out.iterdir()))

    def test_private_key_cannot_be_replaced_with_synthetic_or_wrong_key(self):
        self.seal()
        with patch.dict(os.environ,{"RACE_AI_STATE_KEY":
                      base64.b64encode(os.urandom(32)).decode()}):
            with self.assertRaises(archive.ArchiveError):
                archive.validate_production_bundle(
                    self.out,repo=self.src,license_manifest=self.manifest,
                    expected_run_id=PRODUCER_RUN,
                    expected_commit=PRODUCER_SHA)
        self.assertTrue(self.db.is_file())

    def test_fake_source_permission_and_missing_existing_db_fail_closed(self):
        # A permission document digest is not a real external legal finding;
        # the mechanical gate still rejects removed/modified local evidence.
        self.document.write_text("DIFFERENT FICTIONAL DOCUMENT")
        with patch.dict(os.environ,{"GITHUB_ACTIONS":"false",
                                     "RACE_AI_STATE_KEY":self.key}):
            with self.assertRaises(Exception):
                create_production_bundle(
                    self.db,self.manifest,self.out,source_repo=self.src,
                    race_id=self.packet["race"]["race_id"],generation=1,
                    previous_cipher_sha256=None,producer_run_id=PRODUCER_RUN,
                    producer_sha=PRODUCER_SHA,checked_at=NOW)
        self.assertFalse(self.out.exists())

    def test_untrusted_pull_request_cannot_publish_even_with_valid_secret(self):
        self.seal()
        with patch.dict(os.environ,{"GITHUB_ACTIONS":"true",
            "GITHUB_REF":"refs/pull/103/merge","GITHUB_EVENT_NAME":"pull_request",
            "RACE_AI_STATE_KEY":self.key,
            "RACE_AI_PUBLIC_CIPHERTEXT_APPROVED":archive.ACK}):
            with self.assertRaisesRegex(
                archive.ArchiveError,
                "TRUSTED_MAIN_AND_EXPLICIT_CIPHERTEXT_APPROVAL_REQUIRED"):
                archive.archive_production_in_git(
                    self.out,repo=self.src,license_manifest=self.manifest,
                    expected_run_id=PRODUCER_RUN,
                    expected_commit=PRODUCER_SHA)

    def test_github_only_existing_state_branch_is_not_overwritten(self):
        self.seal()
        git=self.root/"remote.git"
        sh("git","init","--bare","--initial-branch=main",str(git))
        work=self.root/"git-checkout"
        sh("git","clone",str(git),str(work))
        (work/"scripts").mkdir()
        shutil.copy2(self.src/"scripts/keirin_github_checkpoint.mjs",
                     work/"scripts/keirin_github_checkpoint.mjs")
        (work/"README.md").write_text("EXISTING code only\n")
        sh("git","add",".",cwd=work)
        sh("git","-c","user.name=test","-c","user.email=test@example.invalid",
           "commit","-m","main",cwd=work)
        sh("git","push","origin","main",cwd=work)
        sh("git","checkout","-b",archive.STATE_BRANCH,cwd=work)
        synthetic=work/"state"/"keirin"/"v1"
        synthetic.mkdir(parents=True)
        (synthetic/"README.md").write_text("SYNTHETIC ARCHIVE MUST REMAIN\n")
        sh("git","add",".",cwd=work)
        sh("git","-c","user.name=test","-c","user.email=test@example.invalid",
           "commit","-m","existing state branch",cwd=work)
        sh("git","push","origin",archive.STATE_BRANCH,cwd=work)
        sh("git","checkout","main",cwd=work)
        event=self.root/"trusted-producer-event.json"
        event.write_text(json.dumps({
            "repository":{"id":int(archive.REPOSITORY_ID)},
            "workflow_run":{
                "id":int(PRODUCER_RUN),"head_sha":PRODUCER_SHA,
                "head_branch":"main","conclusion":"success",
                "event":"push",
                "name":"KEIRIN admitted real-race private producer",
                "pull_requests":[],
                "head_repository":{"id":int(archive.REPOSITORY_ID)}
            }
        }))
        origin=archive.command
        def local_git(args,**kwargs):
            if args[:4]==["git","remote","get-url","origin"]:
                return "https://github.com/"+REPO
            return origin(args,**kwargs)
        env={
            "GITHUB_ACTIONS":"true",
            "GITHUB_REPOSITORY":REPO,
            "GITHUB_REPOSITORY_ID":archive.REPOSITORY_ID,
            "GITHUB_REF":"refs/heads/main",
            "GITHUB_EVENT_NAME":"workflow_run",
            "GITHUB_EVENT_PATH":str(event),
            "RACE_AI_PUBLIC_CIPHERTEXT_APPROVED":archive.ACK,
            "RACE_AI_STATE_KEY":self.key,
        }
        with patch.object(archive,"command",side_effect=local_git):
            with patch.dict(os.environ,env):
                out=archive.archive_production_in_git(
                    self.out,repo=work,
                    license_manifest=self.manifest,
                    expected_run_id=PRODUCER_RUN,
                    expected_commit=PRODUCER_SHA)
        self.assertEqual(out["state"],
                         "PRODUCTION_RESEARCH_CIPHERTEXT_COMMITTED")
        self.assertFalse(out["independent_pre_cutoff_receipt"])
        fresh=self.root/"independent-checkout"
        sh("git","clone","--branch",archive.STATE_BRANCH,
           str(git),str(fresh))
        self.assertEqual((fresh/"state/keirin/v1/README.md").read_text(),
                         "SYNTHETIC ARCHIVE MUST REMAIN\n")
        pointer=json.loads((fresh/archive.HEAD).read_text())
        self.assertEqual(pointer["mode"],"production")
        self.assertEqual(pointer["generation"],1)
        self.assertEqual(pointer["cipher_sha256"],
                         out["cipher_sha256"])
        self.assertTrue((fresh/pointer["snapshot_file"]).is_file())
        self.assertEqual(list(fresh.rglob("*.sqlite3")),[])


if __name__=="__main__":
    unittest.main()
