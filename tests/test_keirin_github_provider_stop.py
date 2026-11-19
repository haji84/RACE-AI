"""Local bare Git fixtures only; no live provider requests or external writes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock, get_ident
from unittest.mock import patch
import json
import subprocess
import unittest

from race_ai import keirin_github_provider_stop as stop
from scripts import keirin_github_only_ab_day as live


class ProviderStopGuard(unittest.TestCase):
    def test_untrusted_marker_and_wrong_day_rejected(self):
        with self.assertRaises(stop.ProviderStopError):
            stop._check({"schema":stop.SCHEMA,
                         "day_jst":"2026-11-19",
                         "code":"ANYTHING_IS_ALLOWED",
                         "observed_at":"2026-11-19T09:00:00+09:00"},
                        "2026-11-19")
        with self.assertRaises(stop.ProviderStopError):
            stop._path("2026-11-32")

    def test_refuses_provider_get_after_existing_git_stop(self):
        with TemporaryDirectory() as temp:
            repo=Path(temp)
            with patch.object(live.archive,"_remote",return_value=repo), \
                 patch.object(live.archive,"_refresh",
                              return_value="f"*40), \
                 patch.object(stop,"read_for_observed_day",return_value={
                     "schema":stop.SCHEMA,
                     "day_jst":"2026-11-19",
                     "code":"PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                     "observed_at":"2026-11-19T00:00:00+09:00"}), \
                 patch.object(live.archive,"_cmd") as git:
                with self.assertRaisesRegex(
                        live.GitHubOnlyDayError,"PREVIOUS_DAY_DENIAL"):
                    live.archived_day(repo,"2026-11-19")
                git.assert_not_called()

    def test_complete_stop_fields_validate_without_private_data(self):
        marker=stop._check({
            "schema":stop.SCHEMA,
            "day_jst":"2026-11-19",
            "code":"PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
            "observed_at":"2026-11-19T00:00:00+09:00",
        },"2026-11-19")
        self.assertEqual(marker["code"],
                         "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
        self.assertNotIn("html",json.dumps(marker).lower())

    def test_legacy_previous_race_key_still_blocks_same_observation_day(self):
        marker = {
            "schema": stop.SCHEMA, "day_jst": "2026-11-18",
            "code": "PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
            "observed_at": "2026-11-19T00:05:00+09:00",
        }

        def show(repo, head, path):
            return ((0, json.dumps(marker)) if path ==
                    f"{stop.ROOT}/2026-11-18.json" else None)

        with TemporaryDirectory() as temp:
            repo = Path(temp)
            with patch.object(live.archive, "_remote", return_value=repo), \
                 patch.object(live.archive, "_refresh", return_value="f" * 40), \
                 patch.object(live.archive, "_show", side_effect=show), \
                 patch.object(live.archive, "_cmd", return_value=(0, "")):
                with self.assertRaisesRegex(live.GitHubOnlyDayError,
                                            "DENIAL_NO_RETRY"):
                    live.archived_day(repo, "2026-11-19")

    def test_new_stop_write_cannot_use_race_day_instead_of_observed_day(self):
        with TemporaryDirectory() as temp:
            repo = Path(temp)
            with patch.object(stop.archive, "_remote", return_value=repo), \
                 patch.object(stop.archive, "_refresh", return_value="f" * 40), \
                 patch.object(stop, "read", return_value={"already": "stopped"}):
                with self.assertRaisesRegex(stop.ProviderStopError,
                                            "OBSERVED_DAY_MISMATCH"):
                    stop.append_once(
                        repo=repo, day="2026-11-18",
                        code="PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                        observed_at="2026-11-19T00:05:00+09:00")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True).stdout.strip()


class PersistedDenialAcrossRunners(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.origin = self.root / "origin.git"
        self.writer = self.root / "writer"
        self.reader = self.root / "reader"
        git(self.root, "init", "--bare", "-b", stop.archive.BRANCH, str(self.origin))
        git(self.root, "clone", str(self.origin), str(self.writer))
        git(self.writer, "config", "user.name", "Fixture")
        git(self.writer, "config", "user.email", "fixture@example.invalid")
        (self.writer / "fixture-original.enc").write_bytes(b"SYNTHETIC CIPHERTEXT ORIGINAL\n")
        git(self.writer, "add", "fixture-original.enc")
        git(self.writer, "commit", "-m", "synthetic pre-existing original")
        git(self.writer, "push", "origin", stop.archive.BRANCH)
        git(self.root, "clone", str(self.origin), str(self.reader))
        self.original_blob = git(self.origin, "rev-parse",
                                 stop.archive.BRANCH + ":fixture-original.enc")
        # Inject only the approved local-remote boundary. Fetch, object reads,
        # worktrees, commits, pushes and independent readback remain real Git.
        checked_remote = stop.archive._remote
        local = patch.object(stop.archive, "_remote", side_effect=lambda repo, **kwargs:
                             checked_remote(repo, synthetic_local=True))
        local.start()
        self.addCleanup(local.stop)

    def write_stop(self, code, *, repo=None, at="2026-11-18T23:59:00+09:00"):
        return stop.record_denial(repo=repo or self.writer, code=code, observed_at=at)

    def seed_entry(self, path, raw, *, symlink=False):
        git(self.writer, "fetch", "origin", stop.archive.BRANCH)
        git(self.writer, "reset", "--hard", "origin/" + stop.archive.BRANCH)
        target = self.writer / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if symlink:
            target.symlink_to(raw)
        else:
            target.write_text(raw, encoding="utf-8")
        git(self.writer, "add", "--", path)
        git(self.writer, "commit", "-m", "synthetic historical marker fixture")
        git(self.writer, "push", "origin", stop.archive.BRANCH)

    def marker(self, *, day="2026-11-01", at="2026-11-01T12:00:00+09:00",
               code="PROVIDER_DENIED_OR_RATE_LIMITED_STOP"):
        return {"schema": stop.SCHEMA, "day_jst": day, "code": code, "observed_at": at}

    def test_next_day_and_later_runner_retain_denial_without_mutating_original_or_marker(self):
        self.assertEqual(self.write_stop("PROVIDER_DENIED_OR_RATE_LIMITED_STOP"),
                         "PROVIDER_DAY_STOP_RECORDED")
        head = git(self.origin, "rev-parse", stop.archive.BRANCH)
        marker_path = f"{stop.ROOT}/2026-11-18.json"
        marker_blob = git(self.origin, "rev-parse", f"{head}:{marker_path}")
        for day in ("2026-11-19", "2026-11-25", "2027-01-01"):
            with self.subTest(day=day):
                restored = stop.read_for_observed_day(repo=self.reader, day=day)
                self.assertIsNotNone(restored, "an unresolved provider denial expired")
                self.assertEqual(restored["code"], "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
                self.assertEqual(restored["observed_at"], "2026-11-18T23:59:00+09:00")
                with self.assertRaisesRegex(live.GitHubOnlyDayError, "DENIAL_NO_RETRY"):
                    live.archived_day(self.reader, day)
        self.assertEqual(git(self.origin, "rev-parse", stop.archive.BRANCH), head)
        self.assertEqual(git(self.origin, "rev-parse", f"{head}:{marker_path}"), marker_blob)
        self.assertEqual(git(self.origin, "rev-parse", f"{head}:fixture-original.enc"),
                         self.original_blob)

    def test_old_denial_has_priority_over_current_daily_transport_failure(self):
        self.write_stop("PROVIDER_DENIED_OR_RATE_LIMITED_STOP", at="2026-10-01T10:00:00+09:00")
        self.write_stop("PUBLIC_PROVIDER_UNAVAILABLE_STOP", at="2026-11-19T10:00:00+09:00")
        restored = stop.read_for_observed_day(repo=self.reader, day="2026-11-19")
        self.assertEqual(restored["code"], "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
        self.assertEqual(restored["day_jst"], "2026-10-01")

    def test_daily_transport_errors_still_expire_after_their_observation_day(self):
        self.write_stop("PUBLIC_PROVIDER_HTTP_ERROR_STOP", at="2026-11-17T12:00:00+09:00")
        first = stop.read_for_observed_day(repo=self.reader, day="2026-11-17")
        self.assertEqual(first["code"], "PUBLIC_PROVIDER_HTTP_ERROR_STOP")
        self.assertIsNone(stop.read_for_observed_day(repo=self.reader, day="2026-11-18"))
        self.write_stop("PUBLIC_PROVIDER_UNAVAILABLE_STOP", at="2026-11-18T12:00:00+09:00")
        second = stop.read_for_observed_day(repo=self.reader, day="2026-11-18")
        self.assertEqual(second["code"], "PUBLIC_PROVIDER_UNAVAILABLE_STOP")
        self.assertIsNone(stop.read_for_observed_day(repo=self.reader, day="2026-11-19"))
        self.assertIsNone(stop.read_for_observed_day(repo=self.reader, day="2027-01-01"))

    def test_legacy_miskeyed_denial_remains_effective_many_days_later(self):
        old = self.marker(day="2026-11-01", at="2026-11-03T00:05:00+09:00")
        self.seed_entry(f"{stop.ROOT}/2026-11-01.json", json.dumps(old))
        self.assertEqual(stop.read_for_observed_day(repo=self.reader, day="2026-11-19"), old)

    def test_later_same_day_denial_is_appended_without_overwriting_temporary_marker(self):
        self.write_stop("PUBLIC_PROVIDER_HTTP_ERROR_STOP", at="2026-11-18T08:00:00+09:00")
        path = f"{stop.ROOT}/2026-11-18.json"
        first_blob = git(self.origin, "rev-parse", f"{stop.archive.BRANCH}:{path}")
        self.write_stop("PROVIDER_DENIED_OR_RATE_LIMITED_STOP", repo=self.reader,
                        at="2026-11-18T09:00:00+09:00")
        denied = stop.read_for_observed_day(repo=self.writer, day="2026-11-19")
        self.assertIsNotNone(denied, "a prior transient marker swallowed the later denial")
        self.assertEqual(denied["code"], "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
        self.assertEqual(denied["observed_at"], "2026-11-18T09:00:00+09:00")
        self.assertEqual(git(self.origin, "rev-parse", f"{stop.archive.BRANCH}:{path}"), first_blob)
        self.assertEqual(stop.read(repo=self.writer, day="2026-11-18")["code"],
                         "PUBLIC_PROVIDER_HTTP_ERROR_STOP")
        head = git(self.origin, "rev-parse", stop.archive.BRANCH)
        self.write_stop("PROVIDER_DENIED_OR_RATE_LIMITED_STOP", at="2026-11-18T10:00:00+09:00")
        self.assertEqual(git(self.origin, "rev-parse", stop.archive.BRANCH), head)
        self.assertEqual(git(self.origin, "rev-parse", f"{head}:fixture-original.enc"),
                         self.original_blob)

    def test_concurrent_temporary_and_denied_writers_cannot_lose_the_denial(self):
        real_command = stop.archive._cmd
        barrier, lock, reached = Barrier(2), Lock(), set()

        def synchronized_push(repo, *args, **kwargs):
            if args and args[0] == "push":
                with lock:
                    first = get_ident() not in reached
                    reached.add(get_ident())
                if first:
                    barrier.wait(timeout=10)
            return real_command(repo, *args, **kwargs)

        with patch.object(stop.archive, "_cmd", side_effect=synchronized_push):
            with ThreadPoolExecutor(max_workers=2) as workers:
                jobs = [workers.submit(self.write_stop, code, repo=repo) for repo, code in (
                    (self.writer, "PUBLIC_PROVIDER_UNAVAILABLE_STOP"),
                    (self.reader, "PROVIDER_DENIED_OR_RATE_LIMITED_STOP"))]
                for job in jobs:
                    self.assertIn(job.result(timeout=30),
                                  ("PROVIDER_DAY_STOP_RECORDED", "PROVIDER_DAY_ALREADY_STOPPED"))
        result = stop.read_for_observed_day(repo=self.reader, day="2026-11-19")
        self.assertIsNotNone(result, "a losing non-fast-forward writer lost its provider denial")
        self.assertEqual(result["code"], "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")

    def test_malformed_historical_json_does_not_authorize_a_new_get(self):
        self.seed_entry(f"{stop.ROOT}/2026-11-01.json", "{not-json")
        with self.assertRaises(stop.ProviderStopError):
            stop.read_for_observed_day(repo=self.reader, day="2026-11-19")

    def test_unknown_entry_name_is_not_silently_skipped(self):
        self.seed_entry(f"{stop.ROOT}/unexpected.json", json.dumps(self.marker()))
        with self.assertRaises(stop.ProviderStopError):
            stop.read_for_observed_day(repo=self.reader, day="2026-11-19")

    def test_symlink_marker_is_not_a_regular_immutable_record(self):
        self.seed_entry(f"{stop.ROOT}/2026-11-01.json", json.dumps(self.marker()), symlink=True)
        with self.assertRaises(stop.ProviderStopError):
            stop.read_for_observed_day(repo=self.reader, day="2026-11-19")

    def test_future_observation_does_not_become_permission_to_resume(self):
        future = self.marker(at="2026-11-20T00:00:00+09:00")
        self.seed_entry(f"{stop.ROOT}/2026-11-01.json", json.dumps(future))
        with self.assertRaises(stop.ProviderStopError):
            stop.read_for_observed_day(repo=self.reader, day="2026-11-19")

    def test_supplemental_denial_path_cannot_contain_a_temporary_failure(self):
        temporary = self.marker(code="PUBLIC_PROVIDER_HTTP_ERROR_STOP")
        self.seed_entry(f"{stop.ROOT}/denied/2026-11-01.json", json.dumps(temporary))
        with self.assertRaises(stop.ProviderStopError):
            stop.read_for_observed_day(repo=self.reader, day="2026-11-19")

    def test_marker_parent_blob_cannot_look_like_an_empty_stop_history(self):
        self.seed_entry(stop.ROOT.rsplit("/", 1)[0], json.dumps(self.marker()))
        with self.assertRaises(stop.ProviderStopError):
            stop.read_for_observed_day(repo=self.reader, day="2026-11-19")

    def test_marker_ancestor_symlink_cannot_look_like_an_empty_stop_history(self):
        self.seed_entry("state/keirin/ab", json.dumps(self.marker()), symlink=True)
        with self.assertRaises(stop.ProviderStopError):
            stop.read_for_observed_day(repo=self.reader, day="2026-11-19")

    def test_duplicate_json_code_cannot_downgrade_a_denial_to_an_expired_error(self):
        raw = json.dumps(self.marker())[:-1] + ', "code": "PUBLIC_PROVIDER_UNAVAILABLE_STOP"}'
        self.seed_entry(f"{stop.ROOT}/2026-11-01.json", raw)
        with self.assertRaises(stop.ProviderStopError):
            stop.read(repo=self.reader, day="2026-11-01")
        with self.assertRaises(stop.ProviderStopError):
            stop.read_for_observed_day(repo=self.reader, day="2026-11-19")


if __name__=="__main__":
    unittest.main()
