"""Synthetic-only: existing PR71 four models survive GitHub-hosted AES restore.

No external data, official result, private key, live runner, or source rights.
The production forecast acceptance remains completely separate.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from scripts.keirin_github_checkpoint_fixture import produce, consume
from tests.test_keirin_pr71_model_adapter import RID

SHA = "a" * 40
RUN = "123456"


class GitHubHostedFourModelAesHandoffTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.work = self.root / "first-run"
        self.artifact = self.root / "aes"
        self.restore = self.root / "other-run"
        self.env = patch.dict(os.environ, {
            "GITHUB_SHA": SHA,
            "GITHUB_RUN_ID": RUN,
            "EXPECTED_PRODUCER_SHA": SHA,
            "EXPECTED_PRODUCER_RUN_ID": RUN,
            "GITHUB_OUTPUT": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_four_actual_existing_model_codes_aes_readback_then_revised_result_pdca(self):
        produce(self.work, self.artifact)
        proof = json.loads((self.artifact / "fixture-proof.json").read_text())
        self.assertEqual(proof["four_model_ids"], list(ALL_MODELS))
        self.assertEqual(len(proof["four_model_suite_sha256"]), 64)
        self.assertTrue((self.artifact / "state.enc").is_file())
        self.assertFalse(any(p.suffix in (".db", ".sqlite3")
                             for p in self.artifact.iterdir()))
        consume(self.artifact, self.restore)
        with PrivateKeirinStore(self.restore / "restored.sqlite3",
                clock=lambda: datetime.fromisoformat(
                    "2030-01-15T10:40:00+09:00")) as owner:
            ledger = FourModelRankLedger(owner)
            read = ledger.read_suite(RID)
            self.assertEqual(read["suite"]["suite_sha256"],
                             proof["four_model_suite_sha256"])
            self.assertEqual(tuple(read["suite"]["models"]), ALL_MODELS)
            self.assertEqual([m["candidate_count"] for m in
                              read["suite"]["models"].values()], [210]*4)
            audits = ledger.audit_revision(RID)
            self.assertEqual(set(audits), set(ALL_MODELS))
            for model in audits.values():
                self.assertEqual(model["result_status"], "SETTLED_RESEARCH")
                self.assertFalse(model["official_result_independently_authenticated"])
                self.assertFalse(model["independent_external_cutoff_receipt_verified"])
                self.assertIsNone(model["formal_roi"])
            self.assertEqual(ledger.replay_all()["latest_model_race_audits"], 4)

    def test_modified_four_model_receipt_never_verifies_restored_models(self):
        produce(self.work, self.artifact)
        path = self.artifact / "fixture-proof.json"
        proof = json.loads(path.read_text())
        proof["four_model_suite_sha256"] = "0"*64
        path.write_text(json.dumps(proof))
        with self.assertRaisesRegex(ValueError, "FOUR_MODEL_AES_READBACK_MISMATCH"):
            consume(self.artifact, self.restore)

    def test_old_synthetic_history_without_new_suite_receipt_remains_readable(self):
        produce(self.work, self.artifact)
        path = self.artifact / "fixture-proof.json"
        proof = json.loads(path.read_text())
        proof.pop("four_model_suite_sha256")
        proof.pop("four_model_ids")
        path.write_text(json.dumps(proof))
        consume(self.artifact, self.restore)
        self.assertTrue((self.restore / "restored.sqlite3").is_file())


if __name__ == "__main__":
    unittest.main()
