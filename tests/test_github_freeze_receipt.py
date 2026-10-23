"""Synthetic metadata contract tests. No live GitHub access or real forecasts."""
import base64
import json
import unittest

from race_ai.github_freeze_receipt import (
    verify_github_freeze, ReceiptVerificationError, BASE, ANCHOR_SCHEMA
)


class GitHubReceiptTest(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 64
        self.receipt = {"run_id": 9001, "path": "audit/freezes/2026-10-23/boat-kojima-1.json"}
        self.cutoff = "2026-10-23T12:00:00+09:00"
        self.claimed = "2026-10-23T11:45:00+09:00"
        self.run = {"id": 9001, "event": "push", "repository": {"full_name": "haji84/RACE-AI"},
                    "head_sha": "b" * 40, "created_at": "2026-10-23T02:46:00Z"}
        self.anchor = {"schema": ANCHOR_SCHEMA, "race_id": "boat:kojima:2026-10-23:1",
                       "prediction_sha256": self.sha, "cutoff_at": self.cutoff}

    def lookup(self, url):
        if url == f"{BASE}/actions/runs/9001":
            return self.run
        if url.endswith("?ref=" + "b" * 40):
            return {"type": "file", "encoding": "base64", "content":
                    base64.b64encode(json.dumps(self.anchor).encode()).decode()}
        raise AssertionError("unapproved fetch " + url)

    def verify(self):
        return verify_github_freeze(self.receipt, self.sha, self.claimed,
                                    self.cutoff, _fetch=self.lookup)

    def test_all_four_sports(self):
        for sport in ("boat", "keirin", "autorace", "horse"):
            with self.subTest(sport=sport):
                self.anchor["race_id"] = sport + ":venue:2026-10-23:1"
                self.assertTrue(self.verify())

    def test_server_time_cutoff(self):
        self.run["created_at"] = "2026-10-23T03:00:00Z"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_modified_hash(self):
        self.anchor["prediction_sha256"] = "f" * 64
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_forged_foreign_run(self):
        self.run["repository"]["full_name"] = "other/repo"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_dispatch_run_not_push(self):
        self.run["event"] = "workflow_dispatch"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_changed_cutoff(self):
        self.anchor["cutoff_at"] = "2026-10-23T12:10:00+09:00"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_path_traversal(self):
        self.receipt["path"] = "audit/freezes/2026-10-23/../../README.md"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()

    def test_naive_timestamp(self):
        with self.assertRaises(ReceiptVerificationError):
            verify_github_freeze(self.receipt, self.sha, self.claimed,
                                 "2026-10-23T12:00:00", _fetch=self.lookup)

    def test_claimed_time_cannot_override_server(self):
        self.run["created_at"] = "2026-10-23T03:01:00Z"
        self.claimed = "2026-10-23T10:00:00+09:00"
        with self.assertRaises(ReceiptVerificationError):
            self.verify()


if __name__ == "__main__":
    unittest.main()
