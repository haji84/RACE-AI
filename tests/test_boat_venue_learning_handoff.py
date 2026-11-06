"""Invented fitted candidates, real owner crypto, and in-memory Git only."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.boat_venue_learning import fit_venue_rows, seal_candidate, read_candidate
from tests.test_boat_venue_history_handoff import MemoryGit
from tests.test_boat_venue_learning import venue_data, POINTER
from tests.test_observed_weight_learning import NOW


class LearningHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, observations = venue_data(8)
        cls.payload = fit_venue_rows(rows, observations, dataset_pointer=POINTER,
                                    now=NOW, allow_training=lambda *args: True)
        cls.owner = base64.b64encode(os.urandom(32)).decode()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.env = patch.dict(os.environ, RACE_AI_STATE_KEY=self.owner)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.candidate = self.root / 'candidate'
        seal_candidate(deepcopy(self.payload), self.candidate)
        self.git = MemoryGit()

    def apis(self):
        try:
            from race_ai.boat_venue_learning_handoff import (
                publish_learning_candidate, restore_learning_candidate)
        except ModuleNotFoundError:
            self.fail('encrypted learning candidates have no pinned Git persistence')
        return publish_learning_candidate, restore_learning_candidate

    def test_publish_restore_preserves_only_the_three_candidate_files_and_other_state(self):
        publish, restore = self.apis()
        (self.candidate / 'private-extra.sqlite').write_bytes(b'private original')
        pointer = publish(self.candidate, self.root, transport=self.git)
        sha = hashlib.sha256((self.candidate / 'learning.json').read_bytes()).hexdigest()
        prefix = 'state/boat-venue-history/v1/learning/' + sha + '/'
        self.assertEqual(pointer, dict(schema='RACE_AI_BOAT_VENUE_LEARNING_INPUT_V1',
            status='READY', repository_id='1416489937', source_commit=self.git.current,
            manifest_path=prefix + 'learning.json', manifest_sha256=sha,
            training_sha256=self.payload['training']['training_sha256']))
        self.assertEqual(set(self.git.trees[self.git.current]),
                         {'unrelated.enc'} | {prefix + name for name in
                             ('learning.enc', 'learning.json', 'summary.json')})
        self.assertEqual(self.git.trees[self.git.current]['unrelated.enc'], b'preserve')
        restored = self.root / 'restored'
        status = restore(pointer, restored, self.root, transport=self.git)
        self.assertEqual(read_candidate(restored), self.payload)
        self.assertEqual(status['status'], 'OWNER_VENUE_LEARNING_READBACK_VERIFIED')
        self.assertEqual(status['source_commit'], pointer['source_commit'])
        self.assertEqual(status['training_sha256'], pointer['training_sha256'])
        self.assertEqual(status['fitted_model_count'], 2)
        self.assertTrue(status['encrypted_readback_verified'])
        self.assertFalse(status['plaintext_published'])
        self.assertNotIn('weights', json.dumps(status))
        for name in ('learning.enc', 'learning.json', 'summary.json'):
            self.assertEqual((restored / name).read_bytes(), (self.candidate / name).read_bytes())

    def test_republish_is_idempotent_and_later_versions_do_not_replace_old_candidates(self):
        publish, restore = self.apis()
        first = publish(self.candidate, self.root, transport=self.git)
        original_tree = dict(self.git.trees[self.git.current])
        self.assertEqual(publish(self.candidate, self.root, transport=self.git), first)
        self.assertEqual(len(self.git.trees), 2)
        newer = deepcopy(self.payload)
        newer['excluded'].append(dict(reason='SYNTHETIC_ONLY'))
        seal_candidate(newer, self.root / 'newer')
        second = publish(self.root / 'newer', self.root, transport=self.git)
        self.assertNotEqual(first['manifest_sha256'], second['manifest_sha256'])
        self.assertTrue(original_tree.items() <= self.git.trees[self.git.current].items())
        restore(first, self.root / 'old-version', self.root, transport=self.git)
        self.assertEqual(read_candidate(self.root / 'old-version'), self.payload)

    def test_publish_refuses_forged_summary_before_git_access(self):
        publish, _ = self.apis()
        summary = json.loads((self.candidate / 'summary.json').read_text())
        summary['eligible_venue_races'] = 8000
        (self.candidate / 'summary.json').write_text(json.dumps(summary))
        with patch('race_ai.boat_venue_learning_handoff.GitStateRepository',
                   side_effect=AssertionError('must reject before Git')):
            with self.assertRaisesRegex(ValueError, 'SUMMARY'):
                publish(self.candidate, self.root)

    def test_publish_requires_two_fitted_families_before_git_access(self):
        publish, _ = self.apis()
        rows, observations = venue_data(7)
        held = fit_venue_rows(rows, observations, dataset_pointer=POINTER,
                             now=NOW, allow_training=lambda *args: True)
        seal_candidate(held, self.root / 'held')
        with patch('race_ai.boat_venue_learning_handoff.GitStateRepository',
                   side_effect=AssertionError('must reject before Git')):
            with self.assertRaisesRegex(ValueError, 'FITTED'):
                publish(self.root / 'held', self.root)

    def test_existing_namespace_bytes_are_immutable(self):
        publish, _ = self.apis()
        pointer = publish(self.candidate, self.root, transport=self.git)
        prefix = pointer['manifest_path'].removesuffix('learning.json')
        for name in ('learning.enc', 'learning.json', 'summary.json'):
            with self.subTest(name=name):
                path = prefix + name
                original = self.git.trees[self.git.current][path]
                self.git.trees[self.git.current][path] += b'corrupt'
                before = self.git.current
                with self.assertRaisesRegex(ValueError, 'IMMUTABLE'):
                    publish(self.candidate, self.root, transport=self.git)
                self.assertEqual(self.git.current, before)
                self.assertEqual(self.git.trees[before][path], original + b'corrupt')
                self.git.trees[before][path] = original

    def test_publish_verifies_the_entire_committed_readback(self):
        publish, _ = self.apis()
        class CorruptReadback(MemoryGit):
            def push(self, commit, parent):
                super().push(commit, parent)
                path = next(p for p in self.trees[commit] if p.endswith('/summary.json'))
                self.trees[commit][path] = b'{}'
        with self.assertRaisesRegex(ValueError, 'READBACK'):
            publish(self.candidate, self.root, transport=CorruptReadback())

    def test_restore_rejects_corrupt_manifest_cipher_and_summary_before_output(self):
        publish, restore = self.apis()
        pointer = publish(self.candidate, self.root, transport=self.git)
        prefix = pointer['manifest_path'].removesuffix('learning.json')
        for name in ('learning.enc', 'learning.json', 'summary.json'):
            with self.subTest(name=name):
                path = prefix + name
                original = self.git.trees[self.git.current][path]
                self.git.trees[self.git.current][path] += b'corrupt'
                output = self.root / ('corrupt-' + name)
                with self.assertRaises(ValueError):
                    restore(pointer, output, self.root, transport=self.git)
                self.assertFalse(output.exists())
                self.git.trees[self.git.current][path] = original

    def test_restore_rejects_valid_json_summary_with_forged_counts(self):
        publish, restore = self.apis()
        pointer = publish(self.candidate, self.root, transport=self.git)
        path = pointer['manifest_path'].removesuffix('learning.json') + 'summary.json'
        summary = json.loads(self.git.trees[self.git.current][path])
        summary['train_races'] = 999
        self.git.trees[self.git.current][path] = json.dumps(summary).encode()
        with self.assertRaisesRegex(ValueError, 'SUMMARY'):
            restore(pointer, self.root / 'forged', self.root, transport=self.git)
        self.assertFalse((self.root / 'forged').exists())

    def test_restore_rejects_foreign_inexact_or_traversing_pointer_before_git(self):
        publish, restore = self.apis()
        pointer = publish(self.candidate, self.root, transport=self.git)
        mutations = [dict(schema='FOREIGN'), dict(repository_id='123'),
                     dict(status='WAITING_ENCRYPTED_INPUT'), dict(source_commit='main'),
                     dict(source_commit='b' * 39), dict(manifest_sha256='D' * 64),
                     dict(manifest_path='../learning.json'), dict(extra=True)]
        for change in mutations:
            with self.subTest(change=change), patch(
                    'race_ai.boat_venue_learning_handoff.GitStateRepository',
                    side_effect=AssertionError('invalid pointer must not use Git')):
                with self.assertRaisesRegex(ValueError, 'INPUT'):
                    restore(dict(pointer, **change), self.root / 'invalid', self.root)
        changed = dict(pointer, training_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'TRAINING'):
            restore(changed, self.root / 'wrong-training', self.root, transport=self.git)
        self.assertFalse((self.root / 'wrong-training').exists())

    def test_missing_malformed_and_wrong_keys_do_not_publish(self):
        publish, restore = self.apis()
        pointer = publish(self.candidate, self.root, transport=self.git)
        for key in ('', 'invalid', base64.b64encode(os.urandom(32)).decode()):
            with self.subTest(key_kind='missing-or-invalid-or-wrong'), patch.dict(
                    os.environ, RACE_AI_STATE_KEY=key), patch(
                    'race_ai.boat_venue_learning_handoff.GitStateRepository',
                    side_effect=AssertionError('must reject before Git')):
                with self.assertRaises(ValueError):
                    publish(self.candidate, self.root)
                if key in ('', 'invalid'):
                    with self.assertRaises(ValueError):
                        restore(pointer, self.root / 'no-key', self.root)
        with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode()):
            with self.assertRaises(ValueError):
                restore(pointer, self.root / 'wrong-key', self.root, transport=self.git)
        self.assertFalse((self.root / 'wrong-key').exists())

    def test_restore_never_resets_existing_output_or_follows_symlinks(self):
        publish, restore = self.apis()
        pointer = publish(self.candidate, self.root, transport=self.git)
        existing = self.root / 'existing'
        existing.mkdir()
        (existing / 'original').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'DO_NOT_RESET'):
            restore(pointer, existing, self.root, transport=self.git)
        self.assertEqual(list(existing.iterdir()), [existing / 'original'])
        link = self.root / 'linked'
        link.symlink_to(existing, target_is_directory=True)
        for output in (link, link / 'child', self.root / '..' / 'traversal'):
            with self.subTest(output=str(output)), self.assertRaisesRegex(ValueError, 'PATH'):
                restore(pointer, output, self.root, transport=self.git)
        self.assertFalse((existing / 'child').exists())
        with self.assertRaisesRegex(ValueError, 'DO_NOT_RESET'):
            restore(pointer, self.candidate, self.root, transport=self.git)

    def test_publish_rejects_symlinked_source_folder_and_candidate_file(self):
        publish, _ = self.apis()
        linked = self.root / 'source-link'
        linked.symlink_to(self.candidate, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'PATH'):
            publish(linked, self.root, transport=self.git)
        real = self.root / 'cipher-original'
        (self.candidate / 'learning.enc').rename(real)
        (self.candidate / 'learning.enc').symlink_to(real)
        with self.assertRaises(ValueError):
            publish(self.candidate, self.root, transport=self.git)

    def test_restore_enforces_all_remote_file_bounds_even_with_permissive_transport(self):
        publish, restore = self.apis()
        class UnboundedGit(MemoryGit):
            def read(self, commit, path, limit):
                return self.trees[commit][path]
        git = UnboundedGit()
        pointer = publish(self.candidate, self.root, transport=git)
        prefix = pointer['manifest_path'].removesuffix('learning.json')
        for name, limit in (('learning.json', 1_000_000),
                            ('learning.enc', 12 * 1024 * 1024),
                            ('summary.json', 1_000_000)):
            with self.subTest(name=name):
                path = prefix + name
                original = git.trees[git.current][path]
                git.trees[git.current][path] = b'x' * (limit + 1)
                output = self.root / ('oversize-' + name)
                with self.assertRaises(ValueError):
                    restore(pointer, output, self.root, transport=git)
                self.assertFalse(output.exists())
                git.trees[git.current][path] = original

    def test_missing_existing_transfer_head_does_not_initialize_new_state(self):
        publish, _ = self.apis()
        self.git.current = None
        with self.assertRaisesRegex(ValueError, 'EXISTING_TRANSFER_REF_REQUIRED'):
            publish(self.candidate, self.root, transport=self.git)
        self.assertEqual(len(self.git.trees), 1)
