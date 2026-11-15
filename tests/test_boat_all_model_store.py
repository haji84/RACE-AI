"""Invented forecasts, ephemeral test keys and local bare Git only."""
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.exceptions import InvalidTag
from race_ai.boat_pdca_state import PUBLIC_FIXTURE_KEY
from race_ai.boat_pdca_github_handoff import GitStateRepository

try:
    store = importlib.import_module("race_ai.boat_all_model_store")
except ModuleNotFoundError:
    store = None

KEY = os.urandom(32)


def invented():
    return {"schema": "SYNTHETIC_FORECAST_DISPATCH_V1", "as_of": "2030-04-01T09:00:00+09:00",
            "stage": "POST_EXHIBITION", "source_bindings": {"20300401-01-01": "a" * 64},
            "roster": [{"lane": lane, "registration_no": str(4000 + lane), "name": f"合成 選手{lane}"}
                       for lane in (1, 3, 6)],
            "dispatch_reports": [{"race_id": "20300401-01-01", "model_id": "synthetic-model",
                                  "status": "EXECUTED", "combinations": [[1, 3, 6]],
                                  "score": .25, "label": "synthetic-private-forecast"}]}


def repository(root):
    bare, checkout = root / "remote.git", root / "repo"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", str(bare)], check=True, capture_output=True)
    return checkout


class ForecastStoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(store, "encrypted all-model forecast store is missing")

    def seal(self, payload=None, *, round_no=0, key=KEY):
        return store.seal_forecasts(invented() if payload is None else payload, run_id="42", round_no=round_no, key=key)

    def git(self, repo):
        class LocalGit(store.GitForecastRepository):
            def _check_remote(self):
                self.fetch_url = self.push_url = self._run(["remote", "get-url", "origin"]).decode().strip()
        return LocalGit(repo)

    def test_roundtrip_exact_private_payload_and_authenticated_run_round(self):
        payload = invented()
        raw = self.seal(payload)
        self.assertIsInstance(raw, bytes)
        self.assertNotIn(b"synthetic-private-forecast", raw)
        self.assertNotIn("合成".encode(), raw)
        header = store.forecast_header(raw)
        self.assertEqual(header["schema"], "RACE_AI_BOAT_ALL_MODEL_FORECAST_V1")
        self.assertEqual((header["run_id"], header["round_no"], header["repository_id"]), ("42", 0, "1416489937"))
        self.assertEqual(store.open_forecasts(raw, key=KEY), payload)
        self.assertNotEqual(raw, self.seal(payload))

    def test_viewer_wrong_owner_missing_owner_and_public_fixture_keys_cannot_open(self):
        raw = self.seal()
        for key in (os.urandom(32), b"viewer-key", PUBLIC_FIXTURE_KEY):
            with self.subTest(size=len(key)), self.assertRaises(ValueError):
                store.open_forecasts(raw, key=key)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            store.open_forecasts(raw)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            self.seal(key=None)
        from race_ai.boat_model_runtime import open_runtime
        with self.assertRaises(ValueError):
            open_runtime(raw, key=KEY)

    def test_run_round_schema_json_and_bounds_reject_invalid_inputs(self):
        for run_id, round_no in (("0", 0), ("bad", 0), ("42", -1), ("42", True), ("42", 1000000)):
            with self.subTest(run_id=run_id, round_no=round_no), self.assertRaises(ValueError):
                store.seal_forecasts(invented(), run_id=run_id, round_no=round_no, key=KEY)
        for payload in ({}, [], {"schema": "", "x": 1}, {"schema": "fictional", "x": float("nan")},
                        {"schema": "fictional", "x": (1, 2)}, {"schema": "fictional", 2: "changed key"}):
            with self.subTest(kind=type(payload).__name__), self.assertRaises(ValueError):
                self.seal(payload)
        with patch.object(store, "MAX_PLAIN", 8), self.assertRaises(ValueError):
            self.seal()
        with patch.object(store, "MAX_WIRE", 8), self.assertRaises(ValueError):
            self.seal()

    def test_repo_header_hash_byte_and_framing_tampering_fail_closed(self):
        raw = self.seal()
        for bad in (raw[:-1], raw[:-1] + bytes([raw[-1] ^ 1]), b"different-purpose" + raw,
                    raw.replace(b'"repository_id":"1416489937"', b'"repository_id":"1416489938"', 1),
                    raw.replace(b'"round_no":0', b'"round_no":1', 1),
                    raw.replace(b'"run_id":"42"', b'"run_id":"43"', 1)):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                store.open_forecasts(bad, key=KEY)
        header_size = struct.unpack(">I", raw[8:12])[0]
        encoded = raw[12:12 + header_size]
        duplicate = b'{"run_id":"43",' + encoded[1:]
        bad = raw[:8] + struct.pack(">I", len(duplicate)) + duplicate + raw[12 + header_size:]
        with self.assertRaises(ValueError):
            store.open_forecasts(bad, key=KEY)

    def test_authenticated_wrong_plain_hash_duplicate_json_and_size_fail(self):
        raw = self.seal()
        header, nonce, _ = store._split(raw)
        bodies = [b'{"schema":"fictional","x":1,"x":2}', b'{"schema":"fictional","score":1e999}']
        for plain in bodies:
            changed = dict(header, plain_sha256=hashlib.sha256(plain).hexdigest(), plain_size=len(plain))
            cipher = AESGCM(store._key(KEY)).encrypt(nonce, plain, store._aad(changed, nonce))
            encoded = store._wire(changed)
            bad = store.MAGIC + struct.pack(">I", len(encoded)) + encoded + nonce + cipher
            with self.assertRaises(ValueError):
                store.open_forecasts(bad, key=KEY)
        for changed in (dict(header, plain_sha256="b" * 64), dict(header, plain_size=1)):
            plain = store._wire(invented())
            cipher = AESGCM(store._key(KEY)).encrypt(nonce, plain, store._aad(changed, nonce))
            encoded = store._wire(changed)
            with self.assertRaises(ValueError):
                store.open_forecasts(store.MAGIC + struct.pack(">I", len(encoded)) + encoded + nonce + cipher, key=KEY)

    def test_fixed_new_ref_keeps_canonical_allowlist_and_public_tree_has_no_plaintext(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = repository(root)
            with self.assertRaises(ValueError):
                GitStateRepository(repo, ref="state/boat-all-model-forecasts")
            git = self.git(repo)
            raw = self.seal()
            pointer = store.publish_forecasts(raw, repo, expected_parent=None, transport=git)
            self.assertEqual(pointer["ref"], "state/boat-all-model-forecasts")
            self.assertEqual(pointer["cipher_path"], "forecasts/" + hashlib.sha256(raw).hexdigest() + ".enc")
            names = git._run(["ls-tree", "-r", "--name-only", pointer["source_commit"]]).decode().splitlines()
            self.assertEqual(set(names), {"latest.json", pointer["cipher_path"]})
            for name in names:
                self.assertNotIn(b"synthetic-private-forecast", git.read(pointer["source_commit"], name, store.MAX_WIRE))
            self.assertEqual(store.restore_forecasts(pointer, repo, key=KEY, transport=git), invented())
            self.assertFalse(any(path.name.endswith(".json") for path in repo.iterdir()))
            self.assertEqual(pointer["commit_clock_authority"], "UNAUTHENTICATED_GIT_METADATA")
            actual = git._run(["show", "-s", "--format=%cI", pointer["source_commit"]]).decode().strip()
            self.assertEqual(pointer["git_commit_at"], actual)

    def test_next_round_retains_immutable_cipher_and_first_pointer_still_restores(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = repository(Path(folder))
            git = self.git(repo)
            first_raw = self.seal()
            first = store.publish_forecasts(first_raw, repo, expected_parent=None, transport=git)
            next_payload = invented()
            next_payload["dispatch_reports"][0]["score"] = .75
            next_raw = self.seal(next_payload, round_no=1)
            second = store.publish_forecasts(next_raw, repo, expected_parent=first["source_commit"], transport=git)
            self.assertEqual(git.read(second["source_commit"], first["cipher_path"], store.MAX_WIRE), first_raw)
            self.assertEqual(store.restore_forecasts(first, repo, key=KEY, transport=git), invented())
            self.assertEqual(store.restore_forecasts(second, repo, key=KEY, transport=git), next_payload)
            self.assertEqual(store.publish_forecasts(next_raw, repo, expected_parent=second["source_commit"], transport=git), second)
            with self.assertRaises(ValueError):
                store.publish_forecasts(first_raw, repo, expected_parent=None, transport=git)

    def test_exact_pointer_cipher_path_hash_repo_header_and_commit_metadata_required(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = repository(Path(folder))
            git = self.git(repo)
            pointer = store.publish_forecasts(self.seal(), repo, expected_parent=None, transport=git)
            for field, value in (("repository_id", "1"), ("ref", "main"), ("cipher_path", "../private.json"),
                                 ("cipher_sha256", "f" * 64), ("source_commit", "--bad"),
                                 ("git_commit_at", "1900-01-01T00:00:00Z")):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    store.restore_forecasts(dict(pointer, **{field: value}), repo, key=KEY, transport=git)
            bad = deepcopy(pointer)
            bad["header"]["round_no"] = 9
            with self.assertRaises(ValueError):
                store.restore_forecasts(bad, repo, key=KEY, transport=git)

    def test_inherited_plaintext_cipher_hash_and_tree_bounds_stop_publication(self):
        for name, body in (("plaintext.json", b'{"synthetic-private":"forecast"}'),
                           ("forecasts/" + "a" * 64 + ".enc", b"not-encrypted")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                repo = repository(Path(folder))
                git = self.git(repo)
                parent = git.commit({name: body}, None)
                git.push(parent, None)
                with self.assertRaises(ValueError):
                    store.publish_forecasts(self.seal(), repo, expected_parent=parent, transport=git)
                self.assertEqual(git.head(), parent)
        with tempfile.TemporaryDirectory() as folder:
            repo = repository(Path(folder))
            git = self.git(repo)
            raw = self.seal()
            pointer = store.publish_forecasts(raw, repo, expected_parent=None, transport=git)
            with patch.object(store, "MAX_TREE_TOTAL", 100), self.assertRaises(ValueError):
                store.publish_forecasts(raw, repo, expected_parent=pointer["source_commit"], transport=git)

    def test_missing_owner_key_is_rejected_before_restore_network(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = repository(Path(folder))
            git = self.git(repo)
            pointer = store.publish_forecasts(self.seal(), repo, expected_parent=None, transport=git)
            with patch.dict(os.environ, {}, clear=True), patch.object(git, "fetch", side_effect=AssertionError("unexpected fetch")):
                with self.assertRaises(ValueError):
                    store.restore_forecasts(pointer, repo, transport=git)

    def test_dedicated_hkdf_info_is_independently_compatible_and_other_domains_fail(self):
        raw = self.seal()
        header, nonce, cipher = store._split(raw)
        encoded = json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        aad = b"RACE_AI_BOAT_ALL_MODEL_FORECAST_V1\0" + encoded + nonce
        correct = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"1416489937",
                       info=b"RACE_AI_BOAT_ALL_MODEL_FORECAST_V1").derive(KEY)
        self.assertEqual(json.loads(AESGCM(correct).decrypt(nonce, cipher, aad)), invented())
        other = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"1416489937",
                     info=b"RACE_AI_BOAT_MODEL_RUNTIME_V1").derive(KEY)
        for wrong in (other, KEY):
            with self.assertRaises(InvalidTag):
                AESGCM(wrong).decrypt(nonce, cipher, aad)

    def test_competing_remote_commit_after_parent_check_does_not_publish_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = repository(Path(folder))
            git = self.git(repo)
            first = store.publish_forecasts(self.seal(), repo, expected_parent=None, transport=git)
            candidate = self.seal(round_no=1)
            original_push = git.push
            competing = []
            def racing_push(commit, parent):
                tree = git._run(["rev-parse", parent + "^{tree}"]).decode().strip()
                rival = git._run(["-c", "user.name=synthetic", "-c", "user.email=synthetic@example.invalid",
                                  "commit-tree", tree, "-p", parent], body=b"synthetic concurrent update\n").decode().strip()
                original_push(rival, parent)
                competing.append(rival)
                original_push(commit, parent)
            with patch.object(git, "push", side_effect=racing_push), self.assertRaises(ValueError):
                store.publish_forecasts(candidate, repo, expected_parent=first["source_commit"], transport=git)
            self.assertEqual(git.head(), competing[0])
            self.assertFalse(git.exists(competing[0], "forecasts/" + hashlib.sha256(candidate).hexdigest() + ".enc"))
            self.assertEqual(store.restore_forecasts(first, repo, key=KEY, transport=git), invented())

    def test_fast_forward_commit_that_drops_an_old_cipher_is_rejected_before_push(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = repository(Path(folder))
            git = self.git(repo)
            first = store.publish_forecasts(self.seal(), repo, expected_parent=None, transport=git)
            original_commit = git.commit
            def dropping_commit(files, parent):
                orphan = original_commit(files, None)
                tree = git._run(["rev-parse", orphan + "^{tree}"]).decode().strip()
                return git._run(["-c", "user.name=synthetic", "-c", "user.email=synthetic@example.invalid",
                                 "commit-tree", tree, "-p", parent], body=b"synthetic faulty tree construction\n").decode().strip()
            with patch.object(git, "commit", side_effect=dropping_commit), self.assertRaises(ValueError):
                store.publish_forecasts(self.seal(round_no=1), repo, expected_parent=first["source_commit"], transport=git)
            self.assertEqual(git.head(), first["source_commit"])


if __name__ == "__main__":
    unittest.main()
