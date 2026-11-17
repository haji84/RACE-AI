"""Real fixture AES and bounded immutable research batches, without networking."""
import base64
from copy import deepcopy
from pathlib import Path
import tempfile
import os
import subprocess
import unittest
from unittest.mock import patch

from race_ai import boat_venue_learning_handoff as H
from race_ai.boat_venue_learning import fit_venue_rows, seal_candidate, read_candidate
from race_ai.boat_venue_history_handoff import TRANSFER_REF
from tests.test_boat_venue_history_handoff import MemoryGit
from tests.test_boat_venue_learning import venue_data, POINTER
from tests.test_observed_weight_learning import NOW


class CountingGit(MemoryGit):
    def __init__(self, repo, *, shared=None):
        super().__init__()
        self.repo, self.ref = repo, TRANSFER_REF
        self.fetches, self.commits, self.pushes = [], [], []
        if shared is not None:
            self.trees = shared.trees

    def fetch(self, commit):
        self.fetches.append(commit)

    def commit(self, files, parent):
        self.commits.append((set(files), parent))
        return super().commit(files, parent)

    def push(self, commit, parent):
        self.pushes.append((commit, parent))
        return super().push(commit, parent)


class ResearchBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, observations = venue_data(8)
        cls.payload = fit_venue_rows(rows, observations, dataset_pointer=POINTER,
                                    now=NOW, allow_training=lambda *args: True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = patch.dict('os.environ', RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode())
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.folders, self.payloads = [], []
        for index in range(3):
            payload = deepcopy(self.payload)
            payload['excluded'].append({'reason': 'SYNTHETIC_ONLY_' + str(index)})
            folder = self.root / str(index)
            seal_candidate(payload, folder)
            self.folders.append(folder)
            self.payloads.append(payload)
        self.writer = CountingGit(self.root / 'writer')
        self.reader = CountingGit(self.root / 'independent-reader', shared=self.writer)

    def publish(self, folders=None, **options):
        function = getattr(H, 'publish_learning_candidates', None)
        self.assertTrue(callable(function), 'immutable partitions still publish one Git commit at a time')
        return function(self.folders if folders is None else folders, self.root,
                        transport=self.writer, readback_transport=self.reader, **options)

    def test_three_authenticated_candidates_share_one_append_and_independent_readback(self):
        pointers = self.publish()
        self.assertEqual(len(pointers), 3)
        self.assertEqual(len(self.writer.commits), 1)
        self.assertEqual(len(self.writer.pushes), 1)
        self.assertEqual(self.writer.fetches, ['a' * 40])
        self.assertEqual(self.reader.fetches, [self.writer.current])
        self.assertEqual(len(self.writer.trees[self.writer.current]), 10)
        self.assertEqual(self.writer.trees[self.writer.current]['unrelated.enc'], b'preserve')
        for index, pointer in enumerate(pointers):
            self.assertEqual(pointer['source_commit'], self.writer.current)
            output = self.root / ('restored-' + str(index))
            H.restore_learning_candidate(pointer, output, self.root, transport=self.reader)
            self.assertEqual(read_candidate(output), self.payloads[index])
            for name in H.FILES:
                self.assertEqual((output / name).read_bytes(), (self.folders[index] / name).read_bytes())

    def test_every_candidate_authenticates_before_any_git_or_partial_publication(self):
        summary = self.folders[-1] / 'summary.json'
        summary.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.writer.fetches + self.writer.commits + self.writer.pushes, [])

    def test_existing_immutable_bytes_and_corrupt_independent_readback_fail_closed(self):
        pointers = self.publish()
        path = pointers[0]['manifest_path'].removesuffix('learning.json') + 'learning.enc'
        original = self.writer.trees[self.writer.current][path]
        self.writer.trees[self.writer.current][path] = original + b'changed'
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(len(self.writer.commits), 1)
        self.writer.trees[self.writer.current][path] = original
        with patch.object(self.reader, 'read', return_value=b'corrupt'):
            with self.assertRaises(ValueError):
                self.publish()
        self.assertEqual(len(self.writer.commits), 1)

    def test_republish_is_idempotent_but_rechecks_independent_bytes(self):
        first = self.publish()
        again = self.publish()
        self.assertEqual(again, first)
        self.assertEqual(len(self.writer.commits), 1)
        self.assertEqual(self.reader.fetches, [self.writer.current] * 2)

    def test_memory_bound_splits_batches_without_dropping_any_candidate(self):
        sizes = [sum((folder / name).stat().st_size for name in H.FILES) for folder in self.folders]
        self.assertTrue(hasattr(H, 'MAX_RESEARCH_BATCH_BYTES'))
        with patch.object(H, 'MAX_RESEARCH_BATCH_BYTES', max(sizes)):
            pointers = self.publish()
        self.assertEqual(len(pointers), 3)
        self.assertEqual(len(self.writer.commits), 3)
        self.assertEqual(len(self.writer.pushes), 3)
        self.assertEqual(len(self.writer.trees[self.writer.current]), 10)
        for index, pointer in enumerate(pointers):
            output = self.root / ('chunk-restored-' + str(index))
            H.restore_learning_candidate(pointer, output, self.root, transport=self.reader)
            self.assertEqual(read_candidate(output), self.payloads[index])

    def test_same_object_database_cannot_be_called_independent(self):
        function = getattr(H, 'publish_learning_candidates', None)
        self.assertTrue(callable(function))
        with self.assertRaises(ValueError):
            function(self.folders, self.root, transport=self.writer, readback_transport=self.writer)
        self.assertEqual(self.writer.commits, [])

    def test_fresh_research_transfer_restores_only_requested_blobs_and_preserves_unrelated_oid(self):
        from tests.test_boat_private_original_vault import VaultTests
        fixture = VaultTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)

        class LocalResearchRepository(H.GitStateRepository):
            def _check_remote(self):
                self.fetch_url = self.push_url = self._run(['remote', 'get-url', 'origin']).decode().strip()

        root = fixture.root / 'fresh-research-writer'
        subprocess.run(['git', 'init', str(root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(root), 'remote', 'add', 'origin', str(fixture.remote)],
                       check=True, capture_output=True)
        writer = LocalResearchRepository(root, ref=TRANSFER_REF)
        oid = fixture.writer._run(['rev-parse', fixture.parent + ':unrelated/retained.enc']).decode().strip()
        writer.fetch(fixture.parent)
        present = lambda: subprocess.run(['git', '-C', str(root), 'cat-file', '-e', oid],
            env=dict(os.environ, GIT_NO_LAZY_FETCH='1'), capture_output=True).returncode == 0
        self.assertFalse(present(), 'research transfer fetched unrelated ciphertext before using any candidate')
        pointers = H.publish_learning_candidates(self.folders, root, transport=writer,
                                                readback_transport=fixture.reader)
        self.assertFalse(present(), 'research append hydrated the inherited ciphertext tree')
        retained = writer._run(['rev-parse', pointers[-1]['source_commit'] + ':unrelated/retained.enc']).decode().strip()
        self.assertEqual(retained, oid)
        for index, pointer in enumerate(pointers):
            output = self.root / ('sparse-restored-' + str(index))
            H.restore_learning_candidate(pointer, output, root, transport=fixture.reader)
            self.assertEqual(read_candidate(output), self.payloads[index])


if __name__ == '__main__':
    unittest.main()
