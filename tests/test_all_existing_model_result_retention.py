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
        self.git = MemoryGit(); self.git.ref = TRANSFER_REF

    def write(self, raw, metadata):
        for name, body in (('archive.zip', raw), ('metadata.json', metadata)):
            path = self.folder/name; path.write_bytes(body); path.chmod(0o600)

    def retain(self):
        with patch.object(retention, 'GitStateRepository', return_value=self.git):
            return retention.retain_private_source_archives([self.folder], self.base, now=NOW)

    def test_authentic_result_archive_and_exact_metadata_retained_with_receipt_only_mac(self):
        before = dict(os.environ); output = io.StringIO()
        admission = observations_from_result_artifact(self.raw, self.metadata, now=NOW,
            expected_run_id=99, expected_head_sha=HEAD)
        with patch.object(retention, 'observations_from_result_artifact', wraps=observations_from_result_artifact) as verify, \
             patch.object(retention, 'verify_private_pairs_artifact', side_effect=AssertionError('RESULT is not a pair artifact')), \
             patch.object(retention, 'verify_private_p1_artifact', side_effect=AssertionError('RESULT is not a P1 artifact')), \
             contextlib.redirect_stdout(output):
            result = self.retain()
        verify.assert_called_once_with(self.raw, self.metadata, now=NOW, expected_run_id=99, expected_head_sha=HEAD)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(dict(os.environ), before)
        pointer = result['pointers'][0]; tree = self.git.trees[pointer['source_commit']]
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
        restored = observations_from_result_artifact(tree[pointer['archive_path']],
            json.loads(tree[pointer['metadata_path']]), now=NOW, expected_run_id=99, expected_head_sha=HEAD)
        self.assertEqual(restored, admission)
        head = self.git.current
        self.assertEqual(self.retain()['pointers'], [pointer]); self.assertEqual(self.git.current, head)
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
        self.git.trees[self.git.current][pointer['archive_path']] = b'changed-original-ciphertext'
        before = deepcopy(self.git.trees)
        with self.assertRaisesRegex(ValueError, 'SOURCE_IMMUTABLE_FILE_CHANGED'):
            self.retain()
        self.assertEqual(self.git.trees, before)


if __name__ == '__main__':
    unittest.main()
