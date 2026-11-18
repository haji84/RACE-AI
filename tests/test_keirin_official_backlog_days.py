"""Date routing from local Git fixtures only; no provider or remote calls."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import subprocess
import unittest

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_run_history as history
from scripts import keirin_official_backlog_days as backlog

NOW = datetime.fromisoformat("2026-11-19T08:00:00+00:00")


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True).stdout.strip()


class BacklogSelection(unittest.TestCase):
    def test_no_history_still_selects_current_and_previous_jst_day(self):
        self.assertEqual(backlog.select_days(NOW, []), ["2026-11-19", "2026-11-18"])

    def test_only_existing_older_days_are_selected_without_inventing_gaps(self):
        self.assertEqual(backlog.select_days(NOW, ["2026-11-15"]),
                         ["2026-11-19", "2026-11-18", "2026-11-15"])

    def test_current_and_previous_dates_follow_jst_midnight(self):
        before = datetime.fromisoformat("2026-11-18T14:59:59+00:00")
        after = datetime.fromisoformat("2026-11-18T15:00:00+00:00")
        self.assertEqual(backlog.select_days(before, [])[:2], ["2026-11-18", "2026-11-17"])
        self.assertEqual(backlog.select_days(after, [])[:2], ["2026-11-19", "2026-11-18"])

    def test_every_older_day_gets_one_turn_per_complete_rotation(self):
        older = ["2026-11-02", "2026-11-04", "2026-11-10", "2026-11-17"]
        selected = []
        for index in range(len(older)):
            days = backlog.select_days(NOW + timedelta(minutes=10 * index),
                                       list(reversed(older)) + ["2026-11-19", "2026-11-18"])
            self.assertEqual(days[:2], ["2026-11-19", "2026-11-18"])
            self.assertEqual(len(days), 3)
            selected.append(days[2])
        self.assertEqual(set(selected), set(older))
        self.assertEqual(len(set(selected)), len(older))

    def test_equivalent_wall_clocks_use_the_same_utc_rotation_slot(self):
        days = ["2026-11-01", "2026-11-02", "2026-11-03"]
        jst = NOW.astimezone(timezone(timedelta(hours=9)))
        self.assertEqual(backlog.select_days(NOW, days), backlog.select_days(jst, days))
        self.assertEqual(backlog.select_days(NOW, days + days), backlog.select_days(NOW, days))

    def test_invalid_or_future_days_and_naive_clock_fail_closed(self):
        for invalid in ("2026-11-20", "2026-11-32", "20261118", "../2026-11-18", None):
            with self.subTest(day=invalid), self.assertRaises(ValueError):
                backlog.select_days(NOW, [invalid])
        with self.assertRaises(ValueError):
            backlog.select_days(NOW.replace(tzinfo=None), [])

    def test_cli_prints_only_dates_and_keeps_error_details_off_stdout(self):
        output, error = StringIO(), StringIO()
        with patch.object(backlog, "discover_days", return_value=["2026-11-15"]), \
             redirect_stdout(output), redirect_stderr(error):
            code = backlog.main(["--repo", "/not-contacted"], clock=lambda: NOW)
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "2026-11-19\n2026-11-18\n2026-11-15\n")
        self.assertEqual(error.getvalue(), "")
        output, error = StringIO(), StringIO()
        with patch.object(backlog, "discover_days", return_value=["2026-11-20"]), \
             redirect_stdout(output), redirect_stderr(error):
            code = backlog.main(["--repo", "/not-contacted"], clock=lambda: NOW)
        self.assertEqual(code, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("FUTURE", error.getvalue())


class ExistingGitDayDiscovery(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.origin, self.repo = self.root / "origin.git", self.root / "reader"
        git(self.root, "init", "--bare", "-b", archive.BRANCH, str(self.origin))
        git(self.root, "clone", str(self.origin), str(self.repo))
        git(self.repo, "config", "user.name", "Fixture")
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "README.md").write_text("SYNTHETIC LOCAL HISTORY\n")
        self.push()

    def push(self):
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "synthetic archive directories")
        git(self.repo, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)

    def add_day(self, prefix, day):
        target = self.repo / prefix / day / "fixture.sealed.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("SYNTHETIC CIPHERTEXT PLACEHOLDER\n")

    def test_discovers_unique_actual_day_directories_in_both_existing_roots(self):
        self.add_day(archive.ROOT, "2026-11-15")
        self.add_day(archive.ROOT, "2026-11-18")
        self.add_day(history.ROOT, "2026-11-15")
        self.add_day(history.ROOT, "2026-11-16")
        self.push()
        before = git(self.origin, "rev-parse", archive.BRANCH)
        self.assertEqual(backlog.discover_days(self.repo, synthetic_local=True),
                         ["2026-11-15", "2026-11-16", "2026-11-18"])
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), before)

    def test_absent_roots_are_empty_but_missing_state_branch_is_not_created(self):
        self.assertEqual(backlog.discover_days(self.repo, synthetic_local=True), [])
        empty, reader = self.root / "empty.git", self.root / "empty-reader"
        git(self.root, "init", "--bare", str(empty))
        git(self.root, "clone", str(empty), str(reader))
        with self.assertRaises(archive.GitCipherArchiveError):
            backlog.discover_days(reader, synthetic_local=True)
        self.assertEqual(git(empty, "for-each-ref", "--format=%(refname)"), "")

    def test_invalid_directory_is_not_silently_ignored(self):
        self.add_day(history.ROOT, "not-a-day")
        self.push()
        with self.assertRaises(ValueError):
            backlog.discover_days(self.repo, synthetic_local=True)

    def test_default_discovery_still_enforces_existing_repository_opt_in(self):
        with self.assertRaises(archive.GitCipherArchiveError):
            backlog.discover_days(self.repo)


if __name__ == "__main__":
    unittest.main()
