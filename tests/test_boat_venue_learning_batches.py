"""Invented encrypted candidates and offline Git exercise bounded retention."""
import base64
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai import boat_venue_learning_handoff as handoff
from race_ai import boat_venue_research_retention as retention
from race_ai.boat_pdca_github_handoff import GitStateRepository, TRANSFER_REF
from race_ai.boat_venue_learning import fit_venue_rows, read_candidate, seal_candidate
from tests.test_boat_venue_history_handoff import MemoryGit
from tests.test_boat_venue_learning import venue_data, POINTER
from tests.test_observed_weight_learning import NOW


class CountingGit(MemoryGit):
    def __init__(self):
        super().__init__()
        self.ref = TRANSFER_REF
        self.commits = []
        self.pushes = []

    def commit(self, files, parent):
        self.commits.append((dict(files), parent))
        return super().commit(files, parent)

    def push(self, commit, parent):
        self.pushes.append((commit, parent))
        if parent != self.current:
            raise ValueError('STATE_REF_CONCURRENT_UPDATE')
        return super().push(commit, parent)


class LearningBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, observations = venue_data(8)
        cls.payload = fit_venue_rows(rows, observations, dataset_pointer=POINTER,
                                    now=NOW, allow_training=lambda *args: True)
        cls.owner = base64.b64encode(os.urandom(32)).decode()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='learning-batch-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root/'repo'
        self.repo.mkdir(mode=0o700)
        environment = patch.dict(os.environ, RACE_AI_STATE_KEY=self.owner,
                                 GH_TOKEN='synthetic-retention-token-no-real-access')
        environment.start()
        self.addCleanup(environment.stop)
        self.git = CountingGit()

    def candidates(self, count):
        folders = []
        for index in range(count):
            folder = self.root/('candidate-'+str(index))
            seal_candidate(deepcopy(self.payload), folder)
            folders.append(folder)
        return folders

    def publish(self, folders, *, git=None):
        self.assertTrue(callable(getattr(handoff, 'publish_learning_candidates', None)),
                        'bounded multi-candidate learning publication is missing')
        return handoff.publish_learning_candidates(folders, self.repo,
            transport=self.git if git is None else git)

    def test_retaining_210_encrypted_candidates_uses_one_commit_and_preserves_counts(self):
        folders = self.candidates(210)
        original = [{name: (folder/name).read_bytes() for name in handoff.FILES}
                    for folder in folders]
        self.assertLessEqual(sum(len(raw) for files in original for raw in files.values()),
                             64*1024*1024)
        before = dict(os.environ)
        with patch.object(handoff, 'GitStateRepository', return_value=self.git):
            result = retention.retain_private_research(folders+[folders[0]], self.repo)
        self.assertEqual(len(self.git.commits), 1)
        self.assertEqual(len(self.git.pushes), 1)
        self.assertEqual((result['requested_folders'], result['retained_folders']), (211, 210))
        self.assertEqual(len(result['pointers']), 210)
        self.assertEqual({p['source_commit'] for p in result['pointers']}, {self.git.current})
        self.assertEqual(dict(os.environ), before)
        self.assertFalse(result['plaintext_published'])
        self.assertFalse(result['production_promoted'])
        tree = self.git.trees[self.git.current]
        self.assertEqual(tree['unrelated.enc'], b'preserve')
        self.assertEqual(len(tree), 631)
        for pointer, files in zip(result['pointers'], original):
            prefix = pointer['manifest_path'].removesuffix('learning.json')
            for name, raw in files.items():
                self.assertEqual(tree[prefix+name], raw)

    def test_mixed_existing_new_and_duplicate_bytes_restore_with_old_pinned_locator(self):
        folders = self.candidates(3)
        old = handoff.publish_learning_candidate(folders[0], self.repo, transport=self.git)
        old_tree = dict(self.git.trees[old['source_commit']])
        duplicate = self.root/'duplicate'
        shutil.copytree(folders[1], duplicate)
        pointers = self.publish([folders[0], folders[1], duplicate, folders[2]])
        self.assertEqual(len(self.git.commits), 2)
        self.assertEqual(len(self.git.pushes), 2)
        self.assertEqual(pointers[1], pointers[2])
        self.assertEqual(len(self.git.trees[self.git.current]), 10)
        self.assertEqual(self.git.trees[old['source_commit']], old_tree)
        for index, pointer in enumerate([old]+pointers):
            output = self.root/('restored-'+str(index))
            status = handoff.restore_learning_candidate(pointer, output, self.repo,
                                                         transport=self.git)
            self.assertTrue(status['encrypted_readback_verified'])
            self.assertEqual(read_candidate(output), self.payload)
        head = self.git.current
        self.assertEqual(self.publish([folders[0], folders[1], duplicate, folders[2]]), pointers)
        self.assertEqual(self.git.current, head)
        self.assertEqual(len(self.git.commits), 2)
        self.assertEqual(len(self.git.pushes), 2)

    def test_existing_conflict_in_later_candidate_prevents_the_batch_write(self):
        folders = self.candidates(2)
        pointer = handoff.publish_learning_candidate(folders[1], self.repo, transport=self.git)
        path = pointer['manifest_path'].removesuffix('learning.json')+'summary.json'
        self.git.trees[self.git.current][path] = b'changed prior bytes'
        head = self.git.current
        with self.assertRaisesRegex(ValueError, 'IMMUTABLE'):
            self.publish(folders)
        self.assertEqual(self.git.current, head)
        self.assertEqual(len(self.git.commits), 1)
        self.assertEqual(len(self.git.pushes), 1)
        self.assertEqual(self.git.trees[head][path], b'changed prior bytes')

    def test_bad_later_candidate_authenticates_before_any_batch_can_write(self):
        folders = self.candidates(2)
        (folders[1]/'summary.json').write_bytes(b'{}')
        with patch.object(handoff, 'MAX_BATCH_CANDIDATES', 1, create=True), \
                patch.object(self.git, 'head',
                             side_effect=AssertionError('bad candidate must precede Git')):
            with self.assertRaisesRegex(ValueError, 'SUMMARY'):
                self.publish(folders)
        self.assertEqual(len(self.git.commits), 0)

    def test_remote_corruption_of_one_candidate_cannot_report_batch_success(self):
        folders = self.candidates(2)
        class CorruptReadback(CountingGit):
            def push(self, commit, parent):
                super().push(commit, parent)
                path = sorted(p for p in self.trees[commit] if p.endswith('/summary.json'))[-1]
                self.trees[commit][path] = b'{}'
        git = CorruptReadback()
        with self.assertRaisesRegex(ValueError, 'READBACK'):
            self.publish(folders, git=git)
        self.assertEqual(len(git.commits), 1)
        self.assertEqual(len(git.pushes), 1)

    def test_changed_authenticated_source_between_passes_stops_before_git(self):
        folders = self.candidates(1)
        manifest = folders[0]/'learning.json'
        read = handoff._read
        reads = 0
        def changed(path, limit):
            nonlocal reads
            if path == manifest:
                reads += 1
                if reads == 2:
                    manifest.write_bytes(manifest.read_bytes()+b'\n')
            return read(path, limit)
        with patch.object(handoff, '_read', side_effect=changed), \
                patch.object(self.git, 'head', side_effect=AssertionError('changed source must precede Git')):
            with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
                self.publish(folders)
        self.assertEqual(self.git.commits, [])

    def test_later_batch_failure_restores_credentials_without_partial_success_output(self):
        folders = self.candidates(3)
        class CorruptSecondBatch(CountingGit):
            def push(self, commit, parent):
                super().push(commit, parent)
                if len(self.pushes) == 2:
                    path = next(path for path in self.commits[-1][0] if path.endswith('/summary.json'))
                    self.trees[commit][path] = b'{}'
        git = CorruptSecondBatch()
        before = dict(os.environ)
        output = io.StringIO()
        with patch.object(handoff, 'MAX_BATCH_CANDIDATES', 1), \
                patch.object(handoff, 'GitStateRepository', return_value=git), redirect_stdout(output):
            with self.assertRaisesRegex(ValueError, 'READBACK'):
                retention.retain_private_research(folders, self.repo)
        self.assertEqual(len(git.commits), 2)
        self.assertEqual(len(git.pushes), 2)
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(output.getvalue(), '')

    def test_stale_parent_fails_once_and_preserves_the_concurrent_writer(self):
        folders = self.candidates(2)
        class RacingGit(CountingGit):
            def commit(self, files, parent):
                commit = super().commit(files, parent)
                self.current = MemoryGit.commit(self, {'concurrent.enc': b'other owner'}, parent)
                return commit
        git = RacingGit()
        with self.assertRaisesRegex(ValueError, 'CONCURRENT'):
            self.publish(folders, git=git)
        self.assertEqual(len(git.commits), 1)
        self.assertEqual(len(git.pushes), 1)
        self.assertEqual(git.trees[git.current],
                         {'unrelated.enc': b'preserve', 'concurrent.enc': b'other owner'})

    def test_byte_and_candidate_limits_flush_multiple_bounded_batches(self):
        folders = self.candidates(5)
        size = sum((folders[0]/name).stat().st_size for name in handoff.FILES)
        for limit in ('bytes', 'candidates'):
            with self.subTest(limit=limit):
                git = CountingGit()
                maximum_bytes = 2*size if limit == 'bytes' else 64*1024*1024
                maximum_candidates = 2 if limit == 'candidates' else 256
                with patch.object(handoff, 'MAX_BATCH_BYTES', maximum_bytes, create=True), \
                        patch.object(handoff, 'MAX_BATCH_CANDIDATES', maximum_candidates, create=True):
                    pointers = self.publish(folders, git=git)
                self.assertEqual(len(git.commits), 3)
                self.assertEqual(len(git.pushes), 3)
                self.assertEqual(sorted(Counter(p['source_commit'] for p in pointers).values()),
                                 [1, 2, 2])
                self.assertTrue(all(sum(map(len, files.values())) <= maximum_bytes
                                    for files, _ in git.commits))
                self.assertEqual(len(pointers), 5)
                for pointer in pointers:
                    self.assertIn(pointer['manifest_path'], git.trees[pointer['source_commit']])

    def test_empty_and_invalid_lists_or_missing_anchor_never_initialize_state(self):
        folders = self.candidates(1)
        self.assertEqual(self.publish([]), [])
        self.assertEqual(self.git.commits, [])
        for invalid in (None, tuple(folders), folders*10001):
            with self.subTest(kind=type(invalid).__name__), self.assertRaises(ValueError):
                self.publish(invalid)
        self.git.current = None
        with self.assertRaisesRegex(ValueError, 'EXISTING_TRANSFER_REF_REQUIRED'):
            self.publish(folders)
        self.assertEqual(self.git.commits, [])

    def test_real_local_git_publishes_two_candidates_in_one_atomic_commit(self):
        folders = self.candidates(2)
        bare = self.root/'remote.git'
        subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
        subprocess.run(['git', 'init', str(self.repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin', str(bare)],
                       check=True, capture_output=True)
        class LocalGit(GitStateRepository):
            def _check_remote(self):
                self.fetch_url = self.push_url = self._run(['remote', 'get-url', 'origin']).decode().strip()
        git = LocalGit(self.repo, ref=TRANSFER_REF)
        first = git.commit({'unrelated.enc': b'preserve'}, None)
        git.push(first, None)
        pointers = self.publish(folders, git=git)
        self.assertEqual(pointers[0]['source_commit'], pointers[1]['source_commit'])
        self.assertEqual(git._run(['rev-list', '--count', git.head()]).decode().strip(), '2')
        self.assertEqual(git._run(['rev-parse', git.head()+'^']).decode().strip(), first)
        self.assertEqual(git.read(git.head(), 'unrelated.enc', 100), b'preserve')
        for index, pointer in enumerate(pointers):
            output = self.root/('local-restored-'+str(index))
            handoff.restore_learning_candidate(pointer, output, self.repo, transport=git)
            for name in handoff.FILES:
                self.assertEqual((output/name).read_bytes(), (folders[index]/name).read_bytes())


if __name__ == '__main__':
    unittest.main()
