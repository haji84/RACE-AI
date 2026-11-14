"""Synthetic SQLite/JSON and ephemeral test keys; no production payloads."""
from copy import deepcopy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from race_ai.boat_pdca_recipient import receiver_document, _private
from race_ai.boat_pdca_github_handoff import GitStateRepository

try:
    runtime = importlib.import_module("race_ai.boat_model_runtime")
except ModuleNotFoundError:
    runtime = None

KEY = os.urandom(32)
AT = "2030-04-01T09:00:00+09:00"


def invented_files():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE synthetic (source_sha TEXT, value INTEGER)")
    db.execute("INSERT INTO synthetic VALUES (?,?)", ("a" * 64, 3))
    db.commit()
    raw = db.serialize()
    db.close()
    return {"history.sqlite": raw, "racers.sqlite": raw,
            "ranker.json": b'{"schema":"SYNTHETIC_FITTED_RANKER","weights":[0.25]}',
            "metadata.json": b'{"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'}


def local_repos(root):
    bare, repo = root / "remote.git", root / "checkout"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True, capture_output=True)
    return repo


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime, "model runtime adapter is missing")
        self.receiver = receiver_document(key=KEY, run_id="42", source_head="a" * 40)

    def seal(self, files=None):
        return runtime.seal_runtime(invented_files() if files is None else files, self.receiver, created_at=AT)

    def local_git(self, repo):
        class LocalRuntimeGit(runtime.GitRuntimeRepository):
            def _check_remote(self):
                self.fetch_url = self.push_url = self._run(["remote", "get-url", "origin"]).decode().strip()
        return LocalRuntimeGit(repo)

    def replace_zip(self, raw, transform):
        """Create authenticated malicious archive bytes with an invented owner key."""
        header, ephemeral, nonce, cipher = runtime._split(raw)
        public = _private(KEY).public_key().public_bytes_raw()
        shared = _private(KEY).exchange(X25519PublicKey.from_public_bytes(ephemeral))
        session = runtime._session(shared, header, ephemeral, public)
        archive = AESGCM(session).decrypt(nonce, cipher, runtime._aad(header, ephemeral, nonce))
        archive = transform(archive)
        encrypted = AESGCM(session).encrypt(nonce, archive, runtime._aad(header, ephemeral, nonce))
        encoded = runtime._wire(header)
        return runtime.MAGIC + struct.pack(">I", len(encoded)) + encoded + ephemeral + nonce + encrypted

    def test_public_recipient_seal_roundtrip_preserves_exact_files_and_hashes(self):
        files = invented_files()
        files["native-view.json"] = b'{"forecasts":[{"private":"invented-only"}]}'
        with patch.dict(os.environ, {}, clear=True):
            raw, header = self.seal(files)
        self.assertIsInstance(raw, bytes)
        self.assertNotIn(b"invented-only", raw)
        self.assertEqual(header["schema"], "RACE_AI_BOAT_MODEL_RUNTIME_V1")
        self.assertEqual(header["repository_id"], "1416489937")
        self.assertEqual(header["recipient_key_id"], self.receiver["key_id"])
        self.assertEqual(header["files"]["history.sqlite"]["sha256"], hashlib.sha256(files["history.sqlite"]).hexdigest())
        self.assertEqual(runtime.open_runtime(raw, key=KEY), files)
        with self.assertRaises(ValueError):
            runtime.open_runtime(raw, key=os.urandom(32))

    def test_optional_saved_p0_packet_is_encrypted_without_becoming_required(self):
        files = invented_files()
        files["p0-source.json"] = b'{"document":{"schema":"SYNTHETIC_P0"},"receipt":{"independently_verified":true}}'
        raw, header = self.seal(files)
        self.assertEqual(runtime.open_runtime(raw, key=KEY), files)
        self.assertEqual(header["files"]["p0-source.json"]["size"], len(files["p0-source.json"]))
        with patch.dict(runtime.FILE_LIMITS, {"p0-source.json": 8}), self.assertRaises(ValueError):
            self.seal(files)

    def test_frozen_prospective_plan_is_exact_and_owner_encrypted(self):
        files=invented_files()
        files['prospective-budget-plan.json']=b'{"schema":"RACE_AI_PRE_OUTCOME_BUDGET_PLAN_V1","invented_ticket":"2-3-4"}'
        raw,_=self.seal(files)
        self.assertNotIn(b'invented_ticket',raw)
        self.assertEqual(runtime.open_runtime(raw,key=KEY),files)
        with patch.dict(runtime.FILE_LIMITS,{'prospective-budget-plan.json':16}),self.assertRaises(ValueError):
            self.seal(files)

    def test_required_whitelist_and_actual_sqlite_json_validity(self):
        for mutation in (lambda f: f.pop("history.sqlite"), lambda f: f.update({"../extra": b"private"}),
                         lambda f: f.update({"history.sqlite": b"not-sqlite"}),
                         lambda f: f.update({"ranker.json": b'{"x":1,"x":2}'}),
                         lambda f: f.update({"ranker.json": b'{"weight":1e999}'}),
                         lambda f: f.update({"metadata.json": b'{"x":NaN}'})):
            files = invented_files()
            mutation(files)
            with self.subTest(names=sorted(files)), self.assertRaises(ValueError):
                self.seal(files)

    def test_file_and_cipher_bounds_are_enforced_before_publication(self):
        files = invented_files()
        with patch.dict(runtime.FILE_LIMITS, {"history.sqlite": 8}):
            with self.assertRaises(ValueError):
                self.seal(files)
        with patch.object(runtime, "MAX_SEALED", 100):
            with self.assertRaises(ValueError):
                self.seal(files)
        for at in ("2030-04-01T09:00:00", "not-a-time"):
            with self.assertRaises(ValueError):
                runtime.seal_runtime(files, self.receiver, created_at=at)

    def test_tampering_truncation_wrong_purpose_and_header_duplicate_fail(self):
        raw, _ = self.seal()
        variants = [raw[:-1], raw[:-1] + bytes([raw[-1] ^ 1]), b"wrong" + raw,
                    raw.replace(b'"repository_id":"1416489937"', b'"repository_id":"1416489938"', 1),
                    raw.replace(b'RACE_AI_BOAT_MODEL_RUNTIME_V1', b'RACE_AI_BOAT_OWNER_TRANSFER2', 1)]
        header_size = struct.unpack(">I", raw[8:12])[0]
        body = raw[12:12 + header_size]
        duplicate = b'{"schema":"wrong",' + body[1:]
        variants.append(raw[:8] + struct.pack(">I", len(duplicate)) + duplicate + raw[12 + header_size:])
        for bad in variants:
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                runtime.open_runtime(bad, key=KEY)

    def test_authenticated_zip_rejects_duplicate_traversal_symlink_and_hash_change(self):
        raw, _ = self.seal()
        def modified(archive, kind):
            with zipfile.ZipFile(io.BytesIO(archive)) as source:
                files = [(info.filename, source.read(info)) for info in source.infolist()]
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as target:
                for name, body in files:
                    if kind == "hash" and name == "ranker.json": body = body.replace(b"0.25", b"0.75")
                    if kind == "traversal" and name == "ranker.json": name = "../ranker.json"
                    info = zipfile.ZipInfo(name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = ((stat.S_IFLNK if kind == "symlink" and name == "ranker.json" else stat.S_IFREG) | 0o600) << 16
                    target.writestr(info, body)
                if kind == "duplicate":
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        target.writestr("ranker.json", b"{}")
            return out.getvalue()
        for kind in ("duplicate", "traversal", "symlink", "hash"):
            bad = self.replace_zip(raw, lambda archive: modified(archive, kind))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                runtime.open_runtime(bad, key=KEY)

    def test_zip_crc_and_trailing_bytes_are_rejected_even_with_valid_aead(self):
        raw, _ = self.seal()
        def corrupt_crc(archive):
            damaged = bytearray(archive)
            central = damaged.index(b"PK\x01\x02")
            damaged[central + 16] ^= 1
            return bytes(damaged)
        for mutate in (corrupt_crc, lambda archive: archive + b"unexpected", lambda archive: b"unexpected" + archive):
            with self.assertRaises(ValueError):
                runtime.open_runtime(self.replace_zip(raw, mutate), key=KEY)

    def test_separate_fixed_ref_does_not_expand_canonical_repository_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = local_repos(Path(folder))
            with self.assertRaises(ValueError):
                GitStateRepository(repo, ref="state/boat-model-runtime")
            git = self.local_git(repo)
            self.assertEqual(git.ref, "state/boat-model-runtime")

    def test_local_git_publication_restore_pins_blob_and_never_overwrites_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = local_repos(root)
            git = self.local_git(repo)
            raw, header = self.seal()
            pointer = runtime.publish_runtime(raw, repo, expected_parent=None, transport=git)
            self.assertEqual(pointer["cipher_path"], "runtime/" + hashlib.sha256(raw).hexdigest() + ".enc")
            self.assertEqual(pointer["ref"], "state/boat-model-runtime")
            restored = runtime.restore_runtime(pointer, repo, root / "private", key=KEY, transport=git)
            self.assertEqual(restored["status"], "OWNER_MODEL_RUNTIME_RESTORED")
            self.assertEqual((root / "private" / "ranker.json").read_bytes(), invented_files()["ranker.json"])
            self.assertEqual(stat.S_IMODE((root / "private").stat().st_mode), 0o700)
            self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in (root / "private").iterdir()))
            with self.assertRaises(ValueError):
                runtime.restore_runtime(pointer, repo, root / "private", key=KEY, transport=git)
            with self.assertRaises(ValueError):
                runtime.restore_runtime(pointer, repo, repo / "forbidden-private", key=KEY, transport=git)
            self.assertFalse((repo / "forbidden-private").exists())
            self.assertEqual(runtime.publish_runtime(raw, repo, expected_parent=pointer["source_commit"], transport=git), pointer)

    def test_three_runtime_updates_bound_head_and_restore_every_old_pointer_from_fresh_checkouts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = local_repos(root)
            git = self.local_git(repo)
            publications = []
            parent = None
            for number in range(1, 4):
                files = invented_files()
                files['metadata.json'] = json.dumps({'synthetic_generation': number}).encode()
                files['prospective-budget-plan.json'] = json.dumps({'synthetic_frozen_plan': number}).encode()
                raw, _ = runtime.seal_runtime(files, self.receiver, created_at=f'2030-04-01T09:0{number}:00+09:00')
                pointer = runtime.publish_runtime(raw, repo, expected_parent=parent, transport=git)
                self.assertEqual(set(git._run(['ls-tree', '-r', '--name-only', pointer['source_commit']]).decode().splitlines()),
                                 {'latest.json', pointer['cipher_path']})
                if parent is not None:
                    self.assertEqual(git._run(['rev-parse', pointer['source_commit'] + '^']).decode().strip(), parent)
                publications.append((pointer, raw, files))
                parent = pointer['source_commit']
            self.assertEqual(runtime.publish_runtime(publications[-1][1], repo, expected_parent=parent, transport=git), publications[-1][0])
            self.assertEqual(git.head(), parent)
            for number, (pointer, raw, files) in enumerate(publications):
                reader_repo = root / ('fresh-' + str(number))
                subprocess.run(['git', 'init', str(reader_repo)], check=True, capture_output=True)
                subprocess.run(['git', '-C', str(reader_repo), 'remote', 'add', 'origin', str(root / 'remote.git')], check=True, capture_output=True)
                reader = self.local_git(reader_repo)
                self.assertFalse(reader.exists(pointer['source_commit'], pointer['cipher_path']))
                output = root / ('restored-' + str(number))
                restored = runtime.restore_runtime(pointer, reader_repo, output, key=KEY, transport=reader)
                self.assertEqual({name: Path(path).read_bytes() for name, path in restored['files'].items()}, files)
                self.assertEqual(reader.read(pointer['source_commit'], pointer['cipher_path'], runtime.MAX_SEALED), raw)
                self.assertEqual(git._run(['merge-base', '--is-ancestor', pointer['source_commit'], parent]), b'')

    def test_legacy_accumulated_runtime_tree_is_audited_before_bounded_successor(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = local_repos(root)
            git = self.local_git(repo)
            first_raw, _ = self.seal()
            first = runtime.publish_runtime(first_raw, repo, expected_parent=None, transport=git)
            second_files = invented_files();second_files['metadata.json'] = b'{"synthetic_legacy_generation":2}'
            second_raw, second_header = self.seal(second_files)
            latest = {name: value for name, value in first.items() if name not in {'status', 'source_commit'}}
            latest.update(cipher_sha256=hashlib.sha256(second_raw).hexdigest(), header=second_header)
            latest['cipher_path'] = 'runtime/' + latest['cipher_sha256'] + '.enc'
            legacy = git.commit({latest['cipher_path']: second_raw, 'latest.json': runtime._wire(latest) + b'\n'}, first['source_commit'])
            git.push(legacy, first['source_commit'])
            self.assertEqual(len(git._run(['ls-tree', '-r', '--name-only', legacy]).decode().splitlines()), 3)
            third_raw, _ = self.seal()
            third = runtime.publish_runtime(third_raw, repo, expected_parent=legacy, transport=git)
            self.assertEqual(set(git._run(['ls-tree', '-r', '--name-only', third['source_commit']]).decode().splitlines()),
                             {'latest.json', third['cipher_path']})
            self.assertEqual(git.read(first['source_commit'], first['cipher_path'], runtime.MAX_SEALED), first_raw)
            self.assertEqual(git.read(legacy, latest['cipher_path'], runtime.MAX_SEALED), second_raw)
            legacy_pointer = dict(latest, status='READY', source_commit=legacy)
            restored = runtime.restore_runtime(legacy_pointer, repo, root / 'legacy-private', key=KEY, transport=git)
            self.assertEqual({name: Path(path).read_bytes() for name, path in restored['files'].items()}, second_files)

    def test_corrupt_nonlatest_legacy_cipher_blocks_snapshot_without_pruning(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = local_repos(root)
            git = self.local_git(repo)
            old_raw, _ = self.seal()
            old = runtime.publish_runtime(old_raw, repo, expected_parent=None, transport=git)
            current_raw, current_header = self.seal()
            latest = {name: value for name, value in old.items() if name not in {'status', 'source_commit'}}
            latest.update(cipher_sha256=hashlib.sha256(current_raw).hexdigest(), header=current_header)
            latest['cipher_path'] = 'runtime/' + latest['cipher_sha256'] + '.enc'
            corrupted = old_raw[:-1] + bytes([old_raw[-1] ^ 1])
            bad_parent = git.commit({old['cipher_path']: corrupted, latest['cipher_path']: current_raw,
                                     'latest.json': runtime._wire(latest) + b'\n'}, old['source_commit'])
            git.push(bad_parent, old['source_commit'])
            incoming, _ = self.seal()
            with self.assertRaisesRegex(ValueError, 'IMMUTABLE_CIPHER_HASH_INVALID'):
                runtime.publish_runtime(incoming, repo, expected_parent=bad_parent, transport=git)
            self.assertEqual(git.head(), bad_parent)
            self.assertEqual(git.read(bad_parent, old['cipher_path'], runtime.MAX_SEALED), corrupted)

    def test_git_inherited_plaintext_symlink_and_cipher_path_hash_are_rejected(self):
        for path, body in (("exposed.json", b'{"private":"invented"}'), ("runtime/" + "a" * 64 + ".enc", b"wrong")):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                repo = local_repos(root)
                git = self.local_git(repo)
                parent = git.commit({path: body}, None)
                git.push(parent, None)
                raw, _ = self.seal()
                with self.assertRaises(ValueError):
                    runtime.publish_runtime(raw, repo, expected_parent=parent, transport=git)
                self.assertEqual(git.head(), parent)

    def test_pointer_wrong_ref_hash_or_race_with_existing_head_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = local_repos(root)
            git = self.local_git(repo)
            raw, _ = self.seal()
            pointer = runtime.publish_runtime(raw, repo, expected_parent=None, transport=git)
            for field, value in (("ref", "state/boat-pdca-encrypted-history"), ("cipher_sha256", "b" * 64),
                                 ("source_commit", "--bad"), ("cipher_path", "../runtime.enc")):
                bad = dict(pointer, **{field: value})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    runtime.restore_runtime(bad, repo, root / "output", key=KEY, transport=git)
                self.assertFalse((root / "output").exists())
            with self.assertRaises(ValueError):
                runtime.publish_runtime(raw, repo, expected_parent=None, transport=git)

    def test_concurrent_ref_update_after_snapshot_build_is_not_force_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = local_repos(root)
            git = self.local_git(repo)
            raw, _ = self.seal()
            first = runtime.publish_runtime(raw, repo, expected_parent=None, transport=git)
            incoming, _ = self.seal()
            original_snapshot = git.commit_snapshot
            competing = []
            def build_while_other_writer_advances(files, parent):
                candidate = original_snapshot(files, parent)
                other = git.commit({'latest.json': git.read(parent, 'latest.json', runtime.MAX_HEADER * 2)}, parent)
                GitStateRepository.push(git, other, parent)
                competing.append(other)
                return candidate
            with patch.object(git, 'commit_snapshot', side_effect=build_while_other_writer_advances), \
                 self.assertRaisesRegex(ValueError, 'REF_CONCURRENT_UPDATE'):
                runtime.publish_runtime(incoming, repo, expected_parent=first['source_commit'], transport=git)
            self.assertEqual(git.head(), competing[0])
            self.assertEqual(git.read(competing[0], first['cipher_path'], runtime.MAX_SEALED), raw)

    def test_inherited_tree_has_total_bounds_without_replacing_current_ref(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = local_repos(root)
            git = self.local_git(repo)
            raw, _ = self.seal()
            pointer = runtime.publish_runtime(raw, repo, expected_parent=None, transport=git)
            with patch.object(runtime, "MAX_TREE_TOTAL", 128, create=True):
                with self.assertRaises(ValueError):
                    runtime.publish_runtime(raw, repo, expected_parent=pointer["source_commit"], transport=git)
            self.assertEqual(git.head(), pointer["source_commit"])

    def test_symlink_in_inherited_runtime_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = local_repos(root)
            git = self.local_git(repo)
            raw, _ = self.seal()
            pointer = runtime.publish_runtime(raw, repo, expected_parent=None, transport=git)
            blob = git._run(["hash-object", "-w", "--stdin"], body=b"../private").decode().strip()
            tree = git._run(["mktree"], body=f"120000 blob {blob}\truntime.enc\n".encode()).decode().strip()
            parent = git._run(["-c", "user.name=synthetic", "-c", "user.email=synthetic@example.invalid",
                               "commit-tree", tree, "-p", pointer["source_commit"]], body=b"synthetic symlink test\n").decode().strip()
            git.push(parent, pointer["source_commit"])
            with self.assertRaises(ValueError):
                runtime.publish_runtime(raw, repo, expected_parent=parent, transport=git)


if __name__ == "__main__":
    unittest.main()
