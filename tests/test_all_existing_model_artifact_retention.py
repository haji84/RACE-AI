"""Invented GitHub metadata and actual encrypted fixture archives; no live I/O."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import cycle_recovery
from race_ai import boat_venue_research_retention as retention
from race_ai.all_existing_model_receipt import verify_private_pairs_artifact
from race_ai.boat_venue_history_handoff import TRANSFER_REF
from tests import test_all_existing_model_pairs as pair_tests
from tests.test_boat_venue_history_handoff import MemoryGit
from tests.test_observed_weight_learning import NOW

TOKEN = 'fiction-only-artifact-retention-token'


class AllModelArtifactDiscoveryTests(unittest.TestCase):
    def metadata(self, ident=800, prefix='all-existing-model-pairs-'):
        return dict(id=ident, name=prefix+'99-1', expired=False, size_in_bytes=100,
            digest='sha256:'+'d'*64, created_at=(NOW+timedelta(minutes=10)).isoformat(),
            workflow_run=dict(id=99, repository_id=1416489937,
                              head_repository_id=1416489937, head_sha='a'*40))

    def recover(self, metadata):
        documents = {row['id']:deepcopy(row) for row in metadata}
        calls = []
        run = dict(id=99, created_at=NOW.isoformat(), head_branch=cycle_recovery.BRANCH,
                   head_sha='a'*40, status='completed', event='push')
        def github(path):
            calls.append(path)
            if path == f'actions/workflows/{cycle_recovery.WORKFLOW}/runs?per_page=100&page=1':
                return json.dumps(dict(workflow_runs=[run])).encode()
            if path == 'actions/runs/99/artifacts?per_page=100':
                return json.dumps(dict(total_count=len(documents), artifacts=[
                    dict(id=key, name=value['name']) for key,value in documents.items()])).encode()
            for ident, document in documents.items():
                if path == f'actions/artifacts/{ident}':
                    return json.dumps(document).encode()
            self.fail('discovery must not request ZIPs, sources or unlisted metadata: '+path)
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, RACE_AI_STATE_KEY=''):
            result = cycle_recovery.recover(github, '2030-04-01', current_run=100,
                out=Path(temporary), clock=lambda:NOW+timedelta(hours=1))
        return result, calls

    def test_new_and_legacy_handles_are_discovered_without_key_zip_or_admission(self):
        documents = [self.metadata(), self.metadata(801, 'boat-venue-research-p1-')]
        result, calls = self.recover(documents)
        self.assertEqual(result['venue_research_artifact_refs'], [dict(
            artifact_id=row['id'], run_id=99, head_sha='a'*40, digest=row['digest']) for row in documents])
        self.assertFalse(any(path.endswith('/zip') for path in calls))
        self.assertEqual(result['rows'], []); self.assertEqual(result['receipts'], [])
        self.assertIsNone(result['learning_context'])

    def test_new_prefix_preserves_run_head_repository_digest_size_and_clock_checks(self):
        good = self.metadata()
        invalid = []
        for field, value in (('name', 'all-existing-model-pairs-98-1'),
                             ('name', 'all-existing-model-pairs-99-0'),
                             ('name', 'all-existing-model-pairs-99-01'),
                             ('name', 'all-existing-model-pairs-99-1-extra'),
                             ('expired', True), ('digest', 'sha256:'+'D'*64),
                             ('size_in_bytes', 0), ('size_in_bytes', 64*1024*1024+1),
                             ('created_at', (NOW+timedelta(hours=2)).isoformat())):
            invalid.append(dict(good, **{field:value}))
        for field, value in (('id', 100), ('repository_id', 1), ('head_repository_id', 1),
                             ('head_sha', 'b'*40)):
            bad = deepcopy(good); bad['workflow_run'][field] = value; invalid.append(bad)
        for metadata in invalid:
            with self.subTest(metadata=metadata):
                result, _ = self.recover([metadata])
                self.assertEqual(result.get('venue_research_artifact_refs', []), [])
                self.assertEqual(result['venue_research_ref_rejections'], 1)

    def test_other_day_private_artifact_never_becomes_a_current_day_handle(self):
        metadata = self.metadata(); metadata['created_at'] = (NOW-timedelta(days=1)).isoformat()
        result, _ = self.recover([metadata])
        self.assertEqual(result.get('venue_research_artifact_refs', []), [])


class AllModelSourceArchiveRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pair_tests.AllExistingModelPrivatePairsTests.setUpClass()
        cls.addClassCleanup(pair_tests.AllExistingModelPrivatePairsTests.doClassCleanups)

    def setUp(self):
        fixture = pair_tests.AllExistingModelPrivatePairsTests(methodName='runTest')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.make()
        self.fixture = fixture; self.raw, _ = fixture.archive()
        self.metadata = fixture.metadata(self.raw)
        self.metadata_raw = json.dumps(self.metadata, indent=2).encode()+b'\n'
        self.root = fixture.root/'source-archive'; self.root.mkdir(mode=0o700)
        self.write_archive(self.raw, self.metadata_raw)
        environment = patch.dict(os.environ, GH_TOKEN=TOKEN, GIT_CONFIG_COUNT='0')
        environment.start(); self.addCleanup(environment.stop)
        self.git = MemoryGit(); self.git.ref = TRANSFER_REF
        self.now = pair_tests.FORECAST_NOW+timedelta(hours=1)

    def write_archive(self, raw, metadata_raw):
        for name, data in (('archive.zip', raw), ('metadata.json', metadata_raw)):
            path = self.root/name; path.write_bytes(data); path.chmod(0o600)

    def retain(self):
        with patch.object(retention, 'GitStateRepository', return_value=self.git):
            return retention.retain_private_source_archives([self.root], self.fixture.root, now=self.now)

    def test_actual_new_pair_admission_retains_exact_source_bytes_and_is_idempotent(self):
        before = dict(os.environ)
        with patch.object(retention, 'verify_private_pairs_artifact', wraps=verify_private_pairs_artifact) as verify, \
             patch.object(retention, 'verify_private_p1_artifact', side_effect=AssertionError('new prefix must use new verifier')):
            result = self.retain()
        verify.assert_called_once_with(self.raw, self.metadata, now=self.now,
                                       expected_run_id=99, expected_head_sha=pair_tests.HEAD)
        self.assertEqual(dict(os.environ), before)
        pointer = result['pointers'][0]; tree = self.git.trees[pointer['source_commit']]
        self.assertEqual(tree[pointer['archive_path']], self.raw)
        self.assertEqual(tree[pointer['metadata_path']], self.metadata_raw)
        self.assertEqual(tree['unrelated.enc'], b'preserve')
        admission = verify_private_pairs_artifact(self.raw, self.metadata, now=self.now,
            expected_run_id=99, expected_head_sha=pair_tests.HEAD)
        manifest = json.loads(tree[pointer['manifest_path']])
        self.assertEqual(manifest['state']['source_admission_sha256'], digest(admission))
        self.assertEqual(pointer['archive_sha256'], hashlib.sha256(self.raw).hexdigest())
        head = self.git.current
        self.assertEqual(self.retain()['pointers'], [pointer]); self.assertEqual(self.git.current, head)
        self.assertFalse(result['plaintext_published']); self.assertFalse(result['production_promoted'])

    def test_new_prefix_cannot_hide_wrong_schema_or_invalid_receipt_before_git(self):
        variants = [dict(self.metadata, name='all-existing-model-pairs-99-0'),
            dict(self.metadata, name='boat-venue-research-p1-99-1'),
            dict(self.metadata, expired=True), dict(self.metadata, digest='sha256:'+'0'*64),
            dict(self.metadata, created_at=(self.now+timedelta(seconds=1)).isoformat())]
        foreign = deepcopy(self.metadata); foreign['workflow_run']['repository_id'] = 1
        variants.append(foreign)
        with patch.object(retention, 'GitStateRepository', side_effect=AssertionError('must authenticate before Git')):
            for metadata in variants:
                self.write_archive(self.raw, json.dumps(metadata).encode())
                with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                    retention.retain_private_source_archives([self.root], self.fixture.root, now=self.now)

    def test_new_prefix_also_retains_authenticated_input_only_archives_without_forecasts(self):
        from race_ai.all_existing_model_pairs import make_private_pairs
        output = self.fixture.root/'frozen-inputs'
        requests = self.fixture.extra_native_requests()
        # Fictional native inputs remain explicitly synthetic in this fixture.
        make_private_pairs(self.fixture.context, requests, output,
            now=pair_tests.FORECAST_NOW, allow_source=lambda *args: True)
        members = {folder.name+'/'+name:(folder/name).read_bytes()
            for folder in output.iterdir() if folder.is_dir()
            for name in ('learning.enc', 'learning.json', 'summary.json')}
        raw = self.fixture.zip_members(members); metadata = self.fixture.metadata(raw)
        metadata_raw = json.dumps(metadata, indent=2).encode()+b'\n'
        self.write_archive(raw, metadata_raw)
        admission = verify_private_pairs_artifact(raw, metadata, now=self.now,
            expected_run_id=99, expected_head_sha=pair_tests.HEAD)
        self.assertEqual(admission['status'], 'PRIVATE_NATIVE_INPUTS_ARTIFACT_PRE_CUTOFF_VERIFIED')
        self.assertEqual((admission['baseline_forecast_count'], admission['learned_forecast_count']), (0, 0))
        self.assertEqual(admission['captured_native_input_count'], 3)
        result = self.retain(); pointer = result['pointers'][0]
        tree = self.git.trees[pointer['source_commit']]
        self.assertEqual(tree[pointer['archive_path']], raw)
        self.assertEqual(tree[pointer['metadata_path']], metadata_raw)
        manifest = json.loads(tree[pointer['manifest_path']])
        self.assertEqual(manifest['state']['source_admission_sha256'], digest(admission))


if __name__ == '__main__':
    unittest.main()
