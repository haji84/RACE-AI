"""Synthetic regression of existing-only KEIRIN recovery admission.

These fixtures are *metadata*; they do not claim any real saved race, odds,
valid secret or independent timestamp. No GitHub network, writes or secrets.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_existing_asset_reuse import (
    ExistingStateError, inspect_archive_metadata,
    inspect_existing_sqlite, report_existing_asset_reuse
)
from race_ai.keirin_owner_sqlite import PrivateKeirinStore


def synthetic_metadata():
    digest="c1bddac6a6b18b7a88a5eac1509ec27dcead28f4ecdb1a0b5fc9503dac84885b"
    prefix="state/keirin/v1/snapshots/g000001-"+digest
    head={
        "schema":"RACE_AI_KEIRIN_GIT_ARCHIVE_HEAD_V1",
        "mode":"synthetic","repository_id":"1416489937",
        "generation":1,"cipher_sha256":digest,
        "previous_cipher_sha256":None,
        "snapshot_file":prefix+".enc",
        "scope_file":prefix+".scope.json",
        "proof_file":prefix+".proof.json",
        "producer_run_id":"41661810084",
        "producer_commit":"0e45c029e18d5f3f1e7a04aecedab3c4af261748"
    }
    scope={
        "schema":"RACE_AI_GITHUB_SQLITE_V1",
        "mode":"synthetic","repository_id":"1416489937",
        "generation":1,"previous_cipher_sha256":None
    }
    proof={
        "synthetic_only":True,"cipher_sha256":digest,
        "producer_run_id":"41661810084",
        "producer_sha":"0e45c029e18d5f3f1e7a04aecedab3c4af261748",
        "forecast_sha256":"93fdb38f441675bac0f120e8f3304b8b57121bcdcda3b7c8995d90b73fa87818",
        "snapshot_sha256":"4ae69dd66423fe3b871d7a13af2242839ed2162f71862fa9365bcbf7210b8371"
    }
    return head,scope,proof


class ExistingKeirinAssetTests(unittest.TestCase):
    def test_current_synthetic_only_archive_blocks_production(self):
        h,s,p=synthetic_metadata()
        report=report_existing_asset_reuse(h,s,p)
        self.assertEqual(report["archive"]["archive_generation"],1)
        self.assertEqual(report["archive"]["status"],
                         "SYNTHETIC_ONLY_NO_OWNER_HISTORY")
        self.assertEqual(report["owner_store"]["status"],
                         "OWNER_SQLITE_NOT_CONNECTED")
        self.assertFalse(report["ready_for_live_two_version_freeze"])
        self.assertFalse(report["new_empty_db_created"])
        self.assertFalse(report["full_210_odds_present"])
        self.assertFalse(report["archive"]["aead_decryption_verified"])

    def test_wrong_ref_repo_producer_and_generation_rejected(self):
        for changed,value in (
            (("head","repository_id"),"another-repo"),
            (("head","producer_run_id"),"0"),
            (("head","snapshot_file"),"../../secrets.enc"),
            (("head","generation"),2),
            (("scope","mode"),"production"),
            (("proof","producer_sha"),"f"*40),
            (("proof","synthetic_only"),False),
        ):
            with self.subTest(changed=changed):
                h,s,p=synthetic_metadata()
                target={"head":h,"scope":s,"proof":p}[changed[0]]
                target[changed[1]]=value
                with self.assertRaises(ExistingStateError):
                    inspect_archive_metadata(h,s,p)

    def test_production_label_is_not_cryptographic_recovery(self):
        h,s,p=synthetic_metadata()
        h["mode"]=s["mode"]="production"
        p["synthetic_only"]=False
        d=inspect_archive_metadata(h,s,p)
        self.assertEqual(d["status"],
                         "PRODUCTION_METADATA_ONLY_NOT_RECOVERED")
        self.assertFalse(d["aead_decryption_verified"])
        self.assertFalse(d["production_state_recovered"])

    def test_missing_owner_db_does_not_get_created(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"private.sqlite3"
            with self.assertRaisesRegex(
                    ExistingStateError,"NO_AUTO_CREATE"):
                inspect_existing_sqlite(path)
            self.assertFalse(path.exists())
            h,s,p=synthetic_metadata()
            with self.assertRaisesRegex(
                    ExistingStateError,"NO_AUTO_CREATE"):
                report_existing_asset_reuse(h,s,p,owner_db=path)
            self.assertFalse(path.exists())

    def test_existing_owner_sqlite_checked_readonly_and_empty_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"original.sqlite3"
            with PrivateKeirinStore(
                    path,clock=lambda:datetime.fromisoformat(
                        "2030-01-15T09:20:00+09:00")):
                pass
            size_before=path.stat().st_size
            d=inspect_existing_sqlite(path)
            self.assertTrue(d["existing_owner_db_verified"])
            self.assertEqual(d["status"],"EXISTING_OWNER_SQLITE_EMPTY")
            self.assertEqual(d["forecast_original_count"],0)
            self.assertEqual(d["result_revision_count"],0)
            self.assertEqual(path.stat().st_size,size_before)
            h,s,p=synthetic_metadata()
            report=report_existing_asset_reuse(h,s,p,owner_db=path)
            self.assertFalse(report["ready_for_live_two_version_freeze"])

    def test_fake_sqlite_rejected_and_never_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"fake.sqlite3"
            path.write_bytes(b"not a sqlite file")
            with self.assertRaisesRegex(ExistingStateError,"INVALID_SQLITE_HEADER"):
                inspect_existing_sqlite(path)
            self.assertEqual(path.read_bytes(),b"not a sqlite file")


if __name__=="__main__":
    unittest.main()
