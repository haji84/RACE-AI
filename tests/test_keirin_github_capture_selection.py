"""Durable selection metadata using synthetic local Git only."""
from pathlib import Path
from datetime import datetime
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import json
import os
import subprocess
import unittest

from race_ai import keirin_github_capture_selection as selection
from race_ai import keirin_nationwide_cipher_history as archive
from scripts import keirin_github_only_ab_day as live

DAY = "2026-11-19"
AT = "2026-11-19T09:00:00+09:00"
IDS = [f"2026111926{n:02d}" for n in range(1, 9)]


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True).stdout.strip()


class GitCaptureSelection(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.origin = self.root / "origin.git"
        self.first, self.second = self.root / "first", self.root / "second"
        git(self.root, "init", "--bare", "-b", archive.BRANCH, str(self.origin))
        git(self.root, "clone", str(self.origin), str(self.first))
        git(self.first, "config", "user.name", "Fixture")
        git(self.first, "config", "user.email", "fixture@example.invalid")
        (self.first / "README.md").write_text("SYNTHETIC LOCAL STATE\n")
        git(self.first, "add", ".")
        git(self.first, "commit", "-m", "existing synthetic state")
        git(self.first, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
        git(self.root, "clone", str(self.origin), str(self.second))

    def append(self, repo=None, **overrides):
        args = dict(repo=repo or self.first, day=DAY, selected_race_ids=IDS,
                    selected_at=AT, producer_run_id="12345", producer_run_attempt="1",
                    synthetic_local=True)
        args.update(overrides)
        return selection.append_selected(**args)

    def test_separate_runner_reads_counts_and_same_attempt_is_immutable(self):
        before = git(self.origin, "rev-parse", archive.BRANCH)
        receipt = self.append()
        self.assertEqual(receipt["state"], "CAPTURE_SELECTION_RECORDED_NOT_GET_EVIDENCE")
        self.assertEqual(selection.read_day(repo=self.second, day=DAY, synthetic_local=True),
                         dict.fromkeys(IDS, 1))
        first_head = git(self.origin, "rev-parse", archive.BRANCH)
        self.assertNotEqual(first_head, before)
        self.append(repo=self.second, selected_at="2026-11-19T09:01:00+09:00")
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), first_head)
        with self.assertRaisesRegex(ValueError, "DIFFERENT_SELECTION"):
            self.append(repo=self.second, selected_race_ids=["202611192609"])
        self.append(repo=self.second, producer_run_attempt="2")
        self.assertEqual(selection.read_day(repo=self.first, day=DAY, synthetic_local=True),
                         dict.fromkeys(IDS, 2))
        raw = git(self.origin, "show", f"{archive.BRANCH}:{selection.ROOT}/{DAY}/12345.1.json")
        doc = json.loads(raw)
        self.assertEqual(set(doc), {"schema", "day_jst", "selected_at", "selected_race_ids",
                                    "producer_run_id", "producer_run_attempt"})
        self.assertNotIn("attempted_race_ids", doc)
        self.assertNotIn("source", raw)
        self.assertNotIn("ranked_tickets", raw)

    def test_non_fast_forward_retries_preserve_both_selections(self):
        command = archive._cmd
        collided = []

        def racing(repo, *args, **kwargs):
            if args[:2] == ("push", "origin") and not collided:
                collided.append(True)
                self.append(repo=self.second, producer_run_id="22222",
                            selected_race_ids=["202611192609"])
            return command(repo, *args, **kwargs)

        with patch.object(archive, "_cmd", side_effect=racing):
            self.append()
        self.assertEqual(selection.read_day(repo=self.second, day=DAY, synthetic_local=True),
                         dict.fromkeys(IDS + ["202611192609"], 1))

    def test_failed_normalization_on_first_runner_does_not_starve_second_batch(self):
        ids = sorted([f"20261119{venue}{number:02d}"
                      for venue in ("24", "26") for number in range(1, 9)])
        manifest = {"schema": live.collector.SCHEMA, "day_jst": DAY,
                    "source_use_scope": "OWNER_PERSONAL_RESEARCH_ONLY", "races": []}
        for rid in ids:
            manifest["races"].append({
                "race_id": rid,
                "netkeirin_url": f"https://keirin.netkeiba.com/race/entry/?race_id={rid}",
                "kdreams_url": "https://keirin.kdreams.jp/synthetic/racedetail/"
                               f"{rid[8:10]}{rid[:8]}0100{rid[10:]}/",
                "cutoff_hint": "2026-11-19T10:00:00+09:00"})
        original_remote = archive._remote
        fetched_batches = []
        for index, repo in enumerate((self.first, self.second)):
            private = self.root / f"private-{index}"
            private.mkdir(mode=0o700)
            public_key = private / "public.pem"
            public_key.write_bytes(b"SYNTHETIC PUBLIC KEY PLACEHOLDER")
            fetched = []

            def fetch(url):
                fetched.append(url)
                return b"<html>Synthetic page missing the required racecard</html>"

            at = datetime.fromisoformat(f"2026-11-19T09:{index * 10:02d}:00+09:00")
            with patch.object(archive, "_remote", side_effect=lambda path, **kw:
                              original_remote(path, synthetic_local=True)), \
                 patch.object(live.registration, "register_day", return_value=(
                     {"races": manifest["races"]}, manifest, {})), \
                 patch.object(live.generator, "registered_race_ids", return_value=ids), \
                 patch.object(live.generator, "run_cycle", return_value={
                     "registered_races": 16, "same_job_sealed": 0,
                     "statuses": {}, "records": []}), \
                 patch.dict(os.environ, {"GITHUB_RUN_ID": str(12345 + index),
                                         "GITHUB_RUN_ATTEMPT": "1"}):
                report = live.run_day(day=DAY, workspace=repo, private_dir_path=private,
                                      owner_public_pem=public_key, clock=lambda: at,
                                      fetch=fetch)
            self.assertEqual(report["racecard_pairs_attempted"], 8)
            self.assertEqual(report["normalized_cards"], 0)
            self.assertEqual(report["racecard_pairs_selected"], 8)
            self.assertTrue(report["selection_record_is_not_get_evidence"])
            self.assertEqual(report["new_A_B_git_archived"], 0)
            fetched_batches.append([parse_qs(urlsplit(url).query)["race_id"][0]
                                    for url in fetched if "netkeiba.com" in url])
        self.assertEqual(fetched_batches, [ids[:8], ids[8:]])
        self.assertEqual(selection.read_day(repo=self.second, day=DAY, synthetic_local=True),
                         dict.fromkeys(ids, 1))

    def test_missing_branch_is_a_stop_and_never_initializes_state(self):
        origin, repo = self.root / "empty.git", self.root / "empty-reader"
        git(self.root, "init", "--bare", str(origin))
        git(self.root, "clone", str(origin), str(repo))
        with self.assertRaises(archive.GitCipherArchiveError):
            self.append(repo=repo)
        self.assertEqual(git(origin, "for-each-ref", "--format=%(refname)"), "")

    def test_invalid_identity_clock_or_private_fields_fail_closed(self):
        for override in ({"producer_run_attempt": "0"}, {"producer_run_id": "../1"},
                         {"selected_at": "2026-11-18T09:00:00+09:00"},
                         {"selected_race_ids": IDS + ["202611192609"]},
                         {"selected_race_ids": [IDS[0], IDS[0]]},
                         {"selected_race_ids": ["202611182601"]}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.append(**override)
        with self.assertRaises(archive.GitCipherArchiveError):
            self.append(synthetic_local=False)

    def test_noncanonical_bytes_and_unknown_fields_are_rejected(self):
        self.append()
        git(self.first, "fetch", "origin", archive.BRANCH)
        git(self.first, "checkout", "--detach", "FETCH_HEAD")
        target = self.first / selection.ROOT / DAY / "12345.1.json"
        target.write_bytes(target.read_bytes() + b" ")
        git(self.first, "add", ".")
        git(self.first, "commit", "-m", "synthetic malformed metadata")
        git(self.first, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
        with self.assertRaisesRegex(ValueError, "CANONICAL"):
            selection.read_day(repo=self.second, day=DAY, synthetic_local=True)
        doc = json.loads(target.read_bytes())
        doc["raw_source"] = "PRIVATE MUST NEVER BE ACCEPTED"
        target.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n")
        git(self.first, "add", ".")
        git(self.first, "commit", "-m", "synthetic forbidden metadata field")
        git(self.first, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
        with self.assertRaisesRegex(ValueError, "UNTRUSTED"):
            selection.read_day(repo=self.second, day=DAY, synthetic_local=True)


if __name__ == "__main__":
    unittest.main()
