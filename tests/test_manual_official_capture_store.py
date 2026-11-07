"""Fictional official responses and fixture keys exercise private persistence.

No provider request, owner key lookup, Git mutation or real source is used.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from email.message import Message
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch


KEY = bytes(range(32))  # Public fixture only; never a production owner key.
DAY = "2030-01-15"
NOW = datetime.fromisoformat("2030-01-15T09:05:00+09:00")
URLS = ["https://autorace.jp/race_info/Program/kawaguchi/2030-01-15_1",
        "https://autorace.jp/race_info/Program/kawaguchi/2030-01-15_2"]
RAW = {URLS[0]: "<html><p>架空の私的な試走表１</p></html>".encode("cp932"),
       URLS[1]: b"<html><p>FICTIONAL_PRIVATE_SECOND_RACE_SOURCE</p></html>"}


def terms(urls):
    return dict(schema="RACE_AI_MANUAL_OFFICIAL_TERMS_V1", execution_day=DAY,
        purpose="PRIVATE_FACTUAL_ANALYSIS", public_redistribution=False,
        provider_model_training_permission_confirmed=False,
        owner_instruction_ref="SYNTHETIC_FIXTURE_ONLY_NO_PROVIDER_GRANT",
        terms=[dict(sport="autorace", terms_url="https://autorace.jp/policy/",
            policy_sha256=hashlib.sha256(b"fictional observed terms").hexdigest(),
            policy_captured_at="2030-01-14T09:00:00+09:00", source_urls=list(urls),
            uses=["private_retention", "private_factual_analysis"])])


class FixtureClock:
    def __init__(self):
        self.elapsed = 0.0

    def now(self):
        return NOW + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError("negative collection delay")
        self.elapsed += seconds


class Response:
    def __init__(self, url, raw):
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=shift_jis"
        self.headers["Content-Length"] = str(len(raw))
        self.url = url
        self.body = io.BytesIO(raw)

    def geturl(self):
        return self.url

    def read(self, size=-1):
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.body.close()


class ManualOfficialCaptureStoreTests(unittest.TestCase):
    def setUp(self):
        network = patch("urllib.request.OpenerDirector.open",
                        side_effect=AssertionError("real provider transport forbidden in fixtures"))
        network.start(); self.addCleanup(network.stop)
        self.assertIsNotNone(importlib.util.find_spec("race_ai.manual_official_capture"),
                             "manual captures need an owner-encrypted store and restore path")
        self.capture = importlib.import_module("race_ai.manual_official_capture")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.cache = self.root / "captured"
        self.sealed = self.root / "sealed"
        self.restored = self.root / "restored"
        self.acquire(self.cache)

    def acquire(self, folder, sources=None):
        sources = RAW if sources is None else sources
        clock = FixtureClock()
        requested = []
        def opener(request, *, timeout):
            self.assertEqual(timeout, 12)
            url = request.full_url
            self.assertIn(url, sources)
            requested.append(url)
            return Response(url, sources[url])
        self.capture.collect_once(list(sources), execution_day=DAY,
            terms_manifest=terms(sources), cache_dir=folder, clock=clock.now,
            opener=opener, sleeper=clock.sleep, monotonic=clock.monotonic)
        self.assertEqual(requested, list(sources))

    def seal(self, cache=None, output=None, *, key=KEY):
        return self.capture.seal_cache(self.cache if cache is None else cache,
            self.sealed if output is None else output, key=key, run_id="42", round_no=1)

    def restore(self, proof, sealed=None, output=None, *, key=KEY):
        return self.capture.restore_cache(self.sealed if sealed is None else sealed,
            self.restored if output is None else output, key=key,
            expected_index_sha256=proof["index_sha256"])

    def files(self, folder):
        return sorted(path for path in folder.rglob("*") if path.is_file())

    def bytes_at(self, folder):
        return {str(path.relative_to(folder)): path.read_bytes() for path in self.files(folder)}

    def index_file(self, folder, fingerprint):
        matches = [path for path in self.files(folder)
                   if hashlib.sha256(path.read_bytes()).hexdigest() == fingerprint]
        self.assertEqual(len(matches), 1, "returned index SHA must pin exactly one encrypted index")
        return matches[0]

    def source_file(self, folder, proof):
        index = self.index_file(folder, proof["index_sha256"])
        candidates = [path for path in self.files(folder) if path != index]
        self.assertEqual(len(candidates), 2)
        return candidates[0]

    def test_separate_restore_recovers_exact_bytes_and_metadata_without_plaintext_bundle(self):
        from race_ai.boat_all_model_store import open_forecasts
        original = {url: deepcopy(self.capture.read_capture(self.cache, url)) for url in URLS}
        before = self.bytes_at(self.cache)
        proof = self.seal()
        self.assertRegex(proof["index_sha256"], r"^[a-f0-9]{64}$")
        self.index_file(self.sealed, proof["index_sha256"])
        encrypted = self.files(self.sealed)
        self.assertEqual(len(encrypted), 3)
        self.assertEqual(stat.S_IMODE(self.sealed.stat().st_mode), 0o700)
        for path in encrypted:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            raw = path.read_bytes()
            self.assertIsInstance(open_forecasts(raw, key=KEY), dict)
            for secret in [*RAW.values(), *(url.encode() for url in URLS)]:
                self.assertNotIn(secret, raw)
        # Restoration is a fresh read of persisted ciphertext, with all
        # acquisition transport disabled; in-memory acquisition objects cannot
        # serve as a substitute for authenticated encrypted source bodies.
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden")):
            restored_report = self.restore(proof)
        self.assertIsInstance(restored_report, dict)
        reports = json.dumps([proof, restored_report], ensure_ascii=False).encode()
        for private in [*RAW.values(), *(url.encode() for url in URLS)]:
            self.assertNotIn(private, reports)
        self.assertEqual(stat.S_IMODE(self.restored.stat().st_mode), 0o700)
        for url in URLS:
            self.assertEqual(self.capture.read_capture(self.restored, url), original[url])
            self.assertEqual(original[url]["raw"], RAW[url])
        for path in self.files(self.restored):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(self.bytes_at(self.cache), before)

    def test_large_batch_uses_per_source_ciphertexts_below_the_existing_codec_bound(self):
        # Ten 2-MiB responses require over 26 MiB after base64 encoding, beyond
        # the existing codec's 24-MiB single-payload limit. Per-source sealing
        # must still preserve the entire batch, with no clipping or omissions.
        sources = {}
        for number in range(1, 11):
            url = f"https://autorace.jp/race_info/Program/kawaguchi/{DAY}_{number}"
            prefix = f"FICTIONAL_SOURCE_{number}:".encode()
            sources[url] = prefix + b"x" * (2*1024*1024-len(prefix))
        cache = self.root / "large-cache"
        self.acquire(cache, sources)
        proof = self.seal(cache=cache)
        self.assertEqual(len(self.files(self.sealed)), 11)
        self.restore(proof)
        for url, raw in sources.items():
            self.assertEqual(self.capture.read_capture(self.restored, url)["raw"], raw)

    def test_wrong_key_and_wrong_external_index_pin_reject_without_touching_raw_cache(self):
        before = self.bytes_at(self.cache)
        proof = self.seal()
        with self.assertRaises(ValueError):
            self.restore(proof, output=self.root/"wrong-key", key=b"\xff"*32)
        with self.assertRaises(ValueError):
            self.restore(dict(proof, index_sha256="0"*64), output=self.root/"wrong-pin")
        self.assertEqual(self.bytes_at(self.cache), before)

    def test_source_cipher_tamper_and_inexact_member_inventory_are_rejected(self):
        proof = self.seal()
        for kind in ("tamper", "missing", "extra"):
            folder = self.root / ("bad-"+kind)
            shutil.copytree(self.sealed, folder)
            source = self.source_file(folder, proof)
            if kind == "tamper":
                raw = bytearray(source.read_bytes()); raw[-1] ^= 1; source.write_bytes(raw)
            elif kind == "missing":
                source.unlink()
            else:
                (folder/"unlisted-source.enc").write_bytes(source.read_bytes())
                (folder/"unlisted-source.enc").chmod(0o600)
            with self.subTest(kind=kind), self.assertRaises((ValueError, OSError)):
                self.restore(proof, sealed=folder, output=self.root/("restore-"+kind))

    def test_valid_ciphertexts_from_a_different_capture_cannot_replace_the_pinned_bundle(self):
        proof = self.seal()
        other_cache = self.root/"other-cache"
        self.acquire(other_cache, {url: raw+b"ALTERED_CAPTURE" for url, raw in RAW.items()})
        other_sealed = self.root/"other-sealed"
        other_proof = self.seal(cache=other_cache, output=other_sealed)
        with self.assertRaises(ValueError):
            self.restore(proof, sealed=other_sealed, output=self.root/"swapped-index")
        other_source = self.source_file(other_sealed, other_proof)
        self.source_file(self.sealed, proof).write_bytes(other_source.read_bytes())
        with self.assertRaises(ValueError):
            self.restore(proof, output=self.root/"swapped-source")

    def test_existing_restore_output_and_failed_seal_never_overwrite_originals(self):
        proof = self.seal()
        self.restored.mkdir(mode=0o700)
        sentinel = self.restored/"keep-original"
        sentinel.write_bytes(b"untouched"); sentinel.chmod(0o600)
        with self.assertRaises(ValueError):
            self.restore(proof)
        self.assertEqual(sentinel.read_bytes(), b"untouched")
        before = self.bytes_at(self.cache)
        with self.assertRaises(ValueError):
            self.seal(output=self.root/"failed-seal", key=b"too-short")
        self.assertEqual(self.bytes_at(self.cache), before)
        for url in URLS:
            self.assertEqual(self.capture.read_capture(self.cache, url)["raw"], RAW[url])

    def test_source_integrity_failure_during_seal_preserves_the_entire_raw_cache(self):
        source = next(path for path in self.files(self.cache) if path.read_bytes() == RAW[URLS[0]])
        source.write_bytes(source.read_bytes()+b"TAMPERED_SOURCE")
        before = self.bytes_at(self.cache)
        with self.assertRaises(ValueError):
            self.seal()
        self.assertEqual(self.bytes_at(self.cache), before)

    def test_overlapping_sealed_output_is_rejected_before_the_raw_cache_is_changed(self):
        before = {path.name for path in self.cache.iterdir()}
        original = self.bytes_at(self.cache)
        with self.assertRaises(ValueError):
            self.seal(output=self.cache/"nested-sealed")
        self.assertEqual({path.name for path in self.cache.iterdir()}, before)
        self.assertEqual(self.bytes_at(self.cache), original)

    def test_seal_and_restore_reject_symlink_directories_and_source_members(self):
        proof = self.seal()
        cache_link = self.root/"cache-link"; cache_link.symlink_to(self.cache, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.seal(cache=cache_link, output=self.root/"from-cache-link")
        sealed_link = self.root/"sealed-link"; sealed_link.symlink_to(self.sealed, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.restore(proof, sealed=sealed_link, output=self.root/"from-sealed-link")
        unsafe = self.root/"member-link"; shutil.copytree(self.sealed, unsafe)
        member = self.source_file(unsafe, proof)
        genuine = self.sealed/member.relative_to(unsafe)
        member.unlink(); member.symlink_to(genuine)
        with self.assertRaises((ValueError, OSError)):
            self.restore(proof, sealed=unsafe, output=self.root/"from-member-link")

    def test_sealed_and_restored_sources_cannot_be_written_inside_a_git_tree(self):
        repository = self.root/"fake-repository"; repository.mkdir(mode=0o700)
        (repository/".git").write_text("gitdir: /fictional/worktree/control\n")
        with self.assertRaises(ValueError):
            self.seal(output=repository/"sealed")
        proof = self.seal()
        with self.assertRaises(ValueError):
            self.restore(proof, output=repository/"restored")
        self.assertFalse((repository/"sealed").exists())
        self.assertFalse((repository/"restored").exists())

    def test_restore_parent_replacement_cannot_write_plaintext_into_git(self):
        proof = self.seal()
        repository = self.root/"concurrent-fake-git"; repository.mkdir(mode=0o700)
        (repository/".git").write_text("gitdir: /fictional/control\n")
        original_output = self.root/"original-restore-directory"
        raw_names = {self.capture.read_capture(self.cache, url)["metadata"]["raw_file"] for url in URLS}
        real_open = os.open
        replaced = False
        def replace_parent_at_write(path, flags, *args, **kwargs):
            nonlocal replaced
            if not replaced and Path(path).name in raw_names and flags & os.O_CREAT:
                self.restored.rename(original_output)
                self.restored.symlink_to(repository, target_is_directory=True)
                replaced = True
            return real_open(path, flags, *args, **kwargs)
        with patch.object(self.capture.os, "open", side_effect=replace_parent_at_write):
            with self.assertRaises((ValueError, OSError)):
                self.restore(proof)
        self.assertTrue(replaced, "exercise the directory replacement at the actual raw-file write")
        self.assertEqual({path.name for path in repository.iterdir()}, {".git"},
                         "a checked parent replaced by a symlink must never receive plaintext source bytes")

    def test_omitted_explicit_key_cannot_trigger_an_owner_environment_lookup(self):
        # Guard both bindings of the existing codec's key boundary. A missing
        # explicit key must fail before either can consult owner configuration.
        proof = self.seal()
        with patch("race_ai.boat_all_model_store.state_key", side_effect=AssertionError("owner key lookup forbidden")), \
             patch("race_ai.boat_pdca_state.state_key", side_effect=AssertionError("owner key lookup forbidden")), \
             patch("os.environ.get", side_effect=AssertionError("owner environment lookup forbidden")):
            with self.assertRaises(ValueError):
                self.seal(output=self.root/"no-explicit-key", key=None)
            with self.assertRaises(ValueError):
                self.restore(proof, output=self.root/"no-explicit-restore-key", key=None)


if __name__ == "__main__":
    unittest.main()
