"""Public scheduling counters in local bare Git; no provider or key access."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from race_ai import keirin_nationwide_cipher_history as archive


DAY = "2026-11-18"
AT = "2026-11-19T00:00:00+09:00"
OP_A, OP_B = "a" * 64, "b" * 64


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True).stdout.strip()


class GitPollProgress(unittest.TestCase):
    def module(self):
        from race_ai import keirin_official_poll_progress
        return keirin_official_poll_progress

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.origin = self.root / "origin.git"
        git(self.root, "init", "--bare", "-b", archive.BRANCH, str(self.origin))
        self.worker1 = self.root / "one"
        git(self.root, "clone", str(self.origin), str(self.worker1))
        git(self.worker1, "config", "user.name", "Fixture")
        git(self.worker1, "config", "user.email", "fixture@example.invalid")
        self.originals = {
            "state/keirin/ab/v1/2026-11-18/existing.sealed.json": b"\nopaque original\x00\xff\n ",
            "state/keirin/ab/official-results/v1/2026-11-18/existing.sealed.json": b"opaque result revision\n",
            "state/keirin/private-store-head.json": b"existing unrelated history\n",
        }
        for path, raw in self.originals.items():
            dest = self.worker1 / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        git(self.worker1, "add", "state")
        git(self.worker1, "commit", "-m", "synthetic existing encrypted history")
        git(self.worker1, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
        self.initial = git(self.worker1, "rev-parse", "HEAD")
        self.worker2 = self.root / "two"
        git(self.root, "clone", str(self.origin), str(self.worker2))

    def advance(self, repo=None, **kwargs):
        options = dict(repo=repo or self.worker1, day=DAY, result_delta=1,
                       origin_delta=0, operation_id=OP_A, observed_at=AT,
                       synthetic_local=True)
        options.update(kwargs)
        return self.module().advance_day(**options)

    def head(self):
        return git(self.origin, "rev-parse", "refs/heads/" + archive.BRANCH)

    def test_two_clones_advance_one_metadata_file_and_preserve_original_bytes(self):
        module = self.module()
        self.assertIsNone(module.read_day(repo=self.worker2, day=DAY, synthetic_local=True))
        first = self.advance()
        first_head = self.head()
        self.assertEqual((first["result_poll_cursor"], first["origin_poll_cursor"]), (1, 0))
        self.assertEqual(module.read_day(repo=self.worker2, day=DAY, synthetic_local=True), first)
        second = self.advance(self.worker2, result_delta=0, origin_delta=1,
                              operation_id=OP_B, observed_at="2026-11-19T00:01:00+09:00")
        self.assertEqual((second["result_poll_cursor"], second["origin_poll_cursor"]), (1, 1))
        current = archive._refresh(self.worker1)
        path = f"{module.ROOT}/{DAY}.json"
        self.assertEqual(git(self.worker1, "diff", "--name-only", self.initial, current), path)
        expected = (json.dumps(second, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.assertEqual(archive.read_blob_bytes(self.worker1, current, path), expected)
        self.assertEqual(json.loads(archive.read_blob_bytes(self.worker1, first_head, path)), first)
        for name, original in self.originals.items():
            self.assertEqual(archive.read_blob_bytes(self.worker1, current, name), original)

    def test_repeating_the_last_operation_does_not_commit_or_increment(self):
        first = self.advance()
        head = self.head()
        duplicate = self.advance(self.worker2, observed_at="2026-11-19T00:02:00+09:00")
        self.assertEqual(duplicate, first)
        self.assertEqual(self.head(), head)

    def test_real_non_fast_forward_conflict_rereads_and_adds_both_operations(self):
        module = self.module()
        original_cmd = archive._cmd
        injected = False
        def interleave(repo, *args, **kwargs):
            nonlocal injected
            if args and args[0] == "push" and not injected:
                injected = True
                self.advance(self.worker2, result_delta=1, origin_delta=1,
                             operation_id=OP_B, observed_at="2026-11-19T00:01:00+09:00")
            return original_cmd(repo, *args, **kwargs)
        with patch.object(archive, "_cmd", side_effect=interleave):
            current = self.advance()
        self.assertTrue(injected)
        self.assertEqual((current["result_poll_cursor"], current["origin_poll_cursor"]), (2, 1))
        self.assertEqual(current["last_operation_id"], OP_A)
        self.assertEqual(module.read_day(repo=self.worker2, day=DAY, synthetic_local=True), current)
        self.assertEqual(git(self.origin, "rev-list", "--count", self.initial + ".." + self.head()), "2")

    def test_concurrent_same_operation_is_committed_once(self):
        original_cmd = archive._cmd
        injected = False
        def interleave(repo, *args, **kwargs):
            nonlocal injected
            if args and args[0] == "push" and not injected:
                injected = True
                self.advance(self.worker2)
            return original_cmd(repo, *args, **kwargs)
        with patch.object(archive, "_cmd", side_effect=interleave):
            current = self.advance()
        self.assertEqual(current["result_poll_cursor"], 1)
        self.assertEqual(git(self.origin, "rev-list", "--count", self.initial + ".." + self.head()), "1")

    def test_invalid_inputs_do_not_mutate_the_branch(self):
        self.module()
        invalid = ([{"result_delta": value} for value in (-1, 2, True, "1", 1.0)] +
                   [{"origin_delta": value} for value in (-1, 2, False)] +
                   [{"day": "2026-02-30"}, {"day": "../../outside"},
                    {"operation_id": "A" * 64}, {"operation_id": "a" * 63},
                    {"observed_at": "2026-11-19T00:00:00"}, {"observed_at": "invalid"}])
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.advance(**options)
        self.assertEqual(self.head(), self.initial)

    def test_zero_deltas_are_valid_and_overflow_cannot_wrap(self):
        module = self.module()
        empty = self.advance(result_delta=0, origin_delta=0)
        self.assertEqual((empty["result_poll_cursor"], empty["origin_poll_cursor"]), (0, 0))
        git(self.worker1, "merge", "--ff-only", "refs/remotes/origin/" + archive.BRANCH)
        target = self.worker1 / module.ROOT / (DAY + ".json")
        full = dict(empty, result_poll_cursor=module.MAX_CURSOR)
        target.write_bytes((json.dumps(full, sort_keys=True, separators=(",", ":")) + "\n").encode())
        git(self.worker1, "add", "--", str(target.relative_to(self.worker1)))
        git(self.worker1, "commit", "-m", "synthetic cursor bound")
        git(self.worker1, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
        before = self.head()
        with self.assertRaisesRegex(ValueError, "CURSOR"):
            self.advance(self.worker2, operation_id=OP_B)
        self.assertEqual(self.head(), before)

    def test_corrupt_noncanonical_or_oversized_metadata_is_not_reset(self):
        module = self.module()
        valid = {"schema": module.SCHEMA, "day_jst": DAY, "result_poll_cursor": 1,
                 "origin_poll_cursor": 0, "last_operation_id": OP_A, "observed_at": AT}
        mutations = [dict(valid, extra=True), dict(valid, result_poll_cursor=True),
                     dict(valid, origin_poll_cursor=-1), dict(valid, last_operation_id="bad"),
                     dict(valid, observed_at="2026-11-19T00:00:00"),
                     dict(valid, day_jst="2026-11-17")]
        values = [(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
                  for value in mutations]
        values += [json.dumps(valid, indent=2).encode(), b" " * module.MAX_BYTES,
                   b'{"schema":"duplicate","schema":"duplicate"}\n']
        path = f"{module.ROOT}/{DAY}.json"
        for raw in values:
            target = self.worker1 / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            git(self.worker1, "add", "--", path)
            git(self.worker1, "commit", "-m", "synthetic invalid progress")
            git(self.worker1, "push", "origin", "HEAD:refs/heads/" + archive.BRANCH)
            head = self.head()
            with self.subTest(raw_size=len(raw)):
                with self.assertRaises(ValueError):
                    module.read_day(repo=self.worker2, day=DAY, synthetic_local=True)
                with self.assertRaises(ValueError):
                    self.advance(self.worker2)
                self.assertEqual(self.head(), head)

    def test_absent_state_branch_is_not_created(self):
        module = self.module()
        empty = self.root / "empty.git"
        worker = self.root / "empty-worker"
        git(self.root, "init", "--bare", str(empty))
        git(self.root, "clone", str(empty), str(worker))
        with self.assertRaises(ValueError):
            module.read_day(repo=worker, day=DAY, synthetic_local=True)
        with self.assertRaises(ValueError):
            self.advance(worker)
        self.assertEqual(git(empty, "for-each-ref", "--format=%(refname)"), "")


if __name__ == "__main__":
    unittest.main()
