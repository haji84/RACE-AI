"""Encrypted fictional RESULT originals retained byte-for-byte through MemoryGit."""
from copy import deepcopy
import base64
import contextlib
from hashlib import sha256
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import boat_venue_research_retention as retention
from race_ai.all_existing_model_result_intake import observations_from_result_artifact
from race_ai.boat_venue_history_handoff import TRANSFER_REF
from tests.test_all_existing_model_result_intake import fixture, KEY, HEAD, NOW
from tests.test_boat_venue_history_handoff import MemoryGit

TOKEN = 'public-fiction-retention-token-no-access'


class PublishedMemoryGit(MemoryGit):
    """Keep writer-local commits separate from the published fixture remote."""
    def __init__(self, repo):
        super().__init__()
        self.repo, self.ref = repo, TRANSFER_REF
        self.remote_trees = deepcopy(self.trees)

    def fetch(self, commit):
        self.trees[commit] = deepcopy(self.remote_trees[commit])

    def push(self, commit, parent):
        super().push(commit, parent)
        self.remote_trees[commit] = deepcopy(self.trees[commit])


class IndependentMemoryReader(MemoryGit):
    """Separate local objects, populated only by fetching the simulated remote."""
    def __init__(self, repo, remote_trees):
        super().__init__()
        self.repo, self.ref = repo, TRANSFER_REF
        self.remote_trees = remote_trees
        self.trees = {}
        self.reads = []

    def fetch(self, commit):
        assert commit in self.remote_trees, 'independent reader requires a published commit'
        self.trees[commit] = deepcopy(self.remote_trees[commit])

    def read(self, commit, path, limit):
        raw = super().read(commit, path, limit)
        self.reads.append((commit, path, raw))
        return raw


class ResultSourceRetentionTests(unittest.TestCase):
    def setUp(self):
        setting = patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),
                             GH_TOKEN=TOKEN, GIT_CONFIG_COUNT='0')
        setting.start(); self.addCleanup(setting.stop)
        temporary = tempfile.TemporaryDirectory(prefix='fictional-result-retention-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.folder = self.base/'result'; self.folder.mkdir(mode=0o700)
        self.raw, self.metadata, _, _ = fixture()
        self.metadata_raw = json.dumps(self.metadata, indent=2).encode()+b'\n'
        self.write(self.raw, self.metadata_raw)
        self.git = PublishedMemoryGit(self.base/'writer')
        self.reader = IndependentMemoryReader(self.base/'independent-reader', self.git.remote_trees)

    def write(self, raw, metadata):
        for name, body in (('archive.zip', raw), ('metadata.json', metadata)):
            path = self.folder/name; path.write_bytes(body); path.chmod(0o600)

    def retain(self):
        with patch.object(retention, 'GitStateRepository', return_value=self.git):
            return retention.retain_private_source_archives([self.folder], self.base, now=NOW,
                readback_transport=self.reader)

    def assert_selected_readback(self, pointer, fetch, read):
        commit = pointer['source_commit']
        expected = {pointer['archive_path']: self.raw, pointer['metadata_path']: self.metadata_raw,
                    pointer['manifest_path']: self.git.remote_trees[commit][pointer['manifest_path']]}
        fetch.assert_called_once_with(commit)
        self.assertEqual(len(read.call_args_list), 3)
        self.assertEqual({call.args[1] for call in read.call_args_list}, set(expected))
        self.assertTrue(all(call.args[0] == commit for call in read.call_args_list))
        actual_reads = self.reader.reads[-3:]
        self.assertTrue(all(record[0] == commit for record in actual_reads))
        self.assertEqual({path: raw for _, path, raw in actual_reads}, expected)
        for path, raw in expected.items():
            self.assertEqual(self.reader.trees[commit][path], raw)
        self.assertEqual(sha256(expected[pointer['manifest_path']]).hexdigest(), pointer['manifest_sha256'])

    def test_authentic_result_archive_and_exact_metadata_retained_with_receipt_only_mac(self):
        before = dict(os.environ); output = io.StringIO()
        admission = observations_from_result_artifact(self.raw, self.metadata, now=NOW,
            expected_run_id=99, expected_head_sha=HEAD)
        with patch.object(retention, 'observations_from_result_artifact', wraps=observations_from_result_artifact) as verify, \
             patch.object(retention, 'verify_private_pairs_artifact', side_effect=AssertionError('RESULT is not a pair artifact')), \
             patch.object(retention, 'verify_private_p1_artifact', side_effect=AssertionError('RESULT is not a P1 artifact')), \
             patch.object(self.git, 'read', side_effect=AssertionError('readback must not use the writer')), \
             patch.object(self.reader, 'fetch', wraps=self.reader.fetch) as independent_fetch, \
             patch.object(self.reader, 'read', wraps=self.reader.read) as independent_read, \
             contextlib.redirect_stdout(output):
            result = self.retain()
        verify.assert_called_once_with(self.raw, self.metadata, now=NOW, expected_run_id=99, expected_head_sha=HEAD)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(dict(os.environ), before)
        pointer = result['pointers'][0]; tree = self.git.trees[pointer['source_commit']]
        self.assertIsNot(self.git, self.reader)
        self.assertNotEqual(self.git.repo, self.reader.repo)
        self.assertIsNot(self.git.trees, self.reader.trees)
        self.assertIsNot(self.git.trees, self.git.remote_trees)
        self.assertIsNot(tree, self.git.remote_trees[pointer['source_commit']])
        self.assertIsNot(self.reader.trees[pointer['source_commit']], self.git.remote_trees[pointer['source_commit']])
        self.assertIsNot(tree, self.reader.trees[pointer['source_commit']])
        self.assert_selected_readback(pointer, independent_fetch, independent_read)
        self.assertEqual(tree[pointer['archive_path']], self.raw)
        self.assertEqual(tree[pointer['metadata_path']], self.metadata_raw)
        self.assertEqual(tree['unrelated.enc'], b'preserve')
        self.assertEqual(pointer['archive_sha256'], sha256(self.raw).hexdigest())
        self.assertEqual(pointer['metadata_sha256'], sha256(self.metadata_raw).hexdigest())
        manifest = json.loads(tree[pointer['manifest_path']]); state = manifest['state']
        self.assertEqual(state['schema'], 'RACE_AI_OWNER_PRIVATE_SOURCE_ARCHIVE_V1')
        self.assertEqual(state['source_admission_sha256'], digest(admission['receipt']))
        self.assertNotEqual(state['source_admission_sha256'], digest(admission))
        self.assertEqual(state['source_artifact_id'], self.metadata['id'])
        domain = hmac.digest(KEY, b'RACE_AI_OWNER_PRIVATE_SOURCE_ARCHIVE_MANIFEST_V1', 'sha256')
        self.assertTrue(hmac.compare_digest(manifest['mac'],
            hmac.new(domain, retention._bytes(state), sha256).hexdigest()))
        for private in ('observations', 'journal_index', 'source_url', 'roster', 'top3'):
            self.assertNotIn(private, json.dumps(manifest))
        # Independently admit the exact bytes read from the retained commit.
        fetched_tree = self.reader.trees[pointer['source_commit']]
        restored = observations_from_result_artifact(fetched_tree[pointer['archive_path']],
            json.loads(fetched_tree[pointer['metadata_path']]), now=NOW, expected_run_id=99, expected_head_sha=HEAD)
        self.assertEqual(restored, admission)
        head = self.git.current; before = deepcopy(self.git.trees)
        with patch.object(self.git, 'commit', side_effect=AssertionError('retry must not rewrite originals')), \
             patch.object(self.git, 'push', side_effect=AssertionError('retry must not republish originals')), \
             patch.object(self.reader, 'fetch', wraps=self.reader.fetch) as independent_fetch, \
             patch.object(self.reader, 'read', wraps=self.reader.read) as independent_read:
            self.assertEqual(self.retain()['pointers'], [pointer])
        self.assertEqual(self.git.current, head); self.assertEqual(self.git.trees, before)
        self.assertIsNot(self.reader.trees[pointer['source_commit']], fetched_tree)
        self.assert_selected_readback(pointer, independent_fetch, independent_read)
        self.assertFalse(result['plaintext_published']); self.assertFalse(result['production_promoted'])

    def test_wrong_scope_key_digest_report_and_cipher_fail_before_git(self):
        bad_metadata = []
        for name, value in (('name', 'race-existing-cycle-100'), ('expired', True),
                            ('digest', 'sha256:'+'0'*64), ('size_in_bytes', len(self.raw)+1),
                            ('created_at', '2030-04-01T03:00:00Z')):
            bad_metadata.append(dict(self.metadata, **{name:value}))
        for name, value in (('head_sha', 'b'*40), ('repository_id', 1), ('head_repository_id', 1)):
            value_meta = deepcopy(self.metadata); value_meta['workflow_run'][name] = value
            bad_metadata.append(value_meta)
        with patch.object(retention, 'GitStateRepository', side_effect=AssertionError('authenticate before Git')):
            for metadata in bad_metadata:
                self.write(self.raw, json.dumps(metadata).encode())
                with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                    retention.retain_private_source_archives([self.folder], self.base, now=NOW)
            for options in (dict(kind='P1'), dict(mutate_report=lambda report:report.update(code_sha='b'*40))):
                raw, metadata, _, _ = fixture(**options)
                self.write(raw, json.dumps(metadata).encode())
                with self.subTest(options=options), self.assertRaises(ValueError):
                    retention.retain_private_source_archives([self.folder], self.base, now=NOW)
            self.write(self.raw, self.metadata_raw)
            with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(bytes(reversed(KEY))).decode()), \
                 self.assertRaises(ValueError):
                retention.retain_private_source_archives([self.folder], self.base, now=NOW)
            changed = self.raw+b'changed'
            metadata = dict(self.metadata, digest='sha256:'+sha256(changed).hexdigest(), size_in_bytes=len(changed))
            self.write(changed, json.dumps(metadata).encode())
            with self.assertRaises(ValueError):
                retention.retain_private_source_archives([self.folder], self.base, now=NOW)

    def test_remote_source_tamper_is_never_overwritten_or_reinterpreted(self):
        pointer = self.retain()['pointers'][0]
        self.git.remote_trees[self.git.current][pointer['archive_path']] = b'changed-original-ciphertext'
        before = deepcopy(self.git.remote_trees); head = self.git.current
        with self.assertRaisesRegex(ValueError, '^VENUE_RESEARCH_BATCH_IMMUTABLE_FILE_CHANGED$'):
            self.retain()
        self.assertEqual(self.git.remote_trees, before); self.assertEqual(self.git.current, head)

    def test_each_corrupt_independent_readback_is_fatal_on_idempotent_retry_without_overwrite(self):
        pointer = self.retain()['pointers'][0]
        head = self.git.current; before = deepcopy(self.git.remote_trees)
        original_fetch = self.reader.fetch
        for field in ('archive_path', 'metadata_path', 'manifest_path'):
            target = pointer[field]
            def corrupt_fetch(commit):
                original_fetch(commit)
                self.reader.trees[commit][target] += b'corrupt-independent-read'
            with self.subTest(field=field), \
                 patch.object(self.reader, 'fetch', side_effect=corrupt_fetch), \
                 patch.object(self.git, 'commit', side_effect=AssertionError('corruption must not overwrite')), \
                 patch.object(self.git, 'push', side_effect=AssertionError('corruption must not republish')), \
                 self.assertRaisesRegex(ValueError, '^VENUE_RESEARCH_BATCH_INDEPENDENT_READBACK_MISMATCH$'):
                self.retain()
            self.assertEqual(self.git.current, head); self.assertEqual(self.git.remote_trees, before)
        self.assertEqual(self.retain()['pointers'], [pointer])

    def test_idempotent_retry_fetches_remote_bytes_instead_of_reusing_local_reader_objects(self):
        pointer = self.retain()['pointers'][0]; commit = pointer['source_commit']
        original = deepcopy(self.git.trees)
        stale = self.reader.trees[commit]
        for field in ('archive_path', 'metadata_path', 'manifest_path'):
            stale[pointer[field]] = b'corrupt-local-reader-cache'
        self.assertEqual(self.git.trees, original)
        with patch.object(self.reader, 'fetch', wraps=self.reader.fetch) as fetch, \
             patch.object(self.reader, 'read', wraps=self.reader.read) as read:
            self.assertEqual(self.retain()['pointers'], [pointer])
        self.assertIsNot(self.reader.trees[commit], stale)
        self.assert_selected_readback(pointer, fetch, read)
        self.assertEqual(self.git.trees, original)

    def test_shared_writer_repository_path_is_not_an_independent_reader(self):
        before = deepcopy(self.git.trees)
        with patch.object(self.reader, 'repo', self.git.repo), \
             self.assertRaisesRegex(ValueError, 'INDEPENDENT_GIT_READER_REQUIRED'):
            self.retain()
        self.assertEqual(self.git.trees, before)
        self.assertEqual(self.reader.trees, {})

    def test_unpublished_writer_objects_cannot_satisfy_independent_fetch(self):
        with patch.object(self.git, 'push', return_value=None), \
             self.assertRaisesRegex(AssertionError, 'independent reader requires a published commit'):
            self.retain()
        self.assertEqual(self.git.current, 'a' * 40)
        self.assertEqual(self.reader.trees, {})


if __name__ == '__main__':
    unittest.main()
