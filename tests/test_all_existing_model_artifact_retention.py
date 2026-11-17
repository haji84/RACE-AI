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
from race_ai import all_existing_model_learning as learning
from race_ai import all_existing_model_registry as registry
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
        self.git.repo = fixture.root/'writer'
        self.reader = MemoryGit(); self.reader.ref = TRANSFER_REF
        self.reader.repo = fixture.root/'independent-reader'
        self.reader.trees = self.git.trees  # Shared simulated remote; distinct reader object/path.
        self.now = pair_tests.FORECAST_NOW+timedelta(hours=1)

    def write_archive(self, raw, metadata_raw):
        for name, data in (('archive.zip', raw), ('metadata.json', metadata_raw)):
            path = self.root/name; path.write_bytes(data); path.chmod(0o600)

    def retain(self):
        with patch.object(retention, 'GitStateRepository', return_value=self.git):
            return retention.retain_private_source_archives([self.root], self.fixture.root, now=self.now,
                readback_transport=self.reader)

    def test_actual_new_pair_admission_retains_exact_source_bytes_and_is_idempotent(self):
        before = dict(os.environ)
        with patch.object(retention, 'verify_private_pairs_artifact', wraps=verify_private_pairs_artifact) as verify, \
             patch.object(retention, 'verify_private_p1_artifact', side_effect=AssertionError('new prefix must use new verifier')), \
             patch.object(self.reader, 'read', wraps=self.reader.read) as independent_read:
            result = self.retain()
        verify.assert_called_once_with(self.raw, self.metadata, now=self.now,
                                       expected_run_id=99, expected_head_sha=pair_tests.HEAD)
        self.assertEqual(dict(os.environ), before)
        pointer = result['pointers'][0]; tree = self.git.trees[pointer['source_commit']]
        self.assertIsNot(self.git, self.reader)
        self.assertNotEqual(self.git.repo, self.reader.repo)
        selected = {pointer[name] for name in ('archive_path', 'metadata_path', 'manifest_path')}
        self.assertEqual({call.args[1] for call in independent_read.call_args_list}, selected)
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


class NativeGenerationRegistrySnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_all_existing_model_common_eight_per_sport import common_records, FIXTURE_NOW
        cls.clock = FIXTURE_NOW
        cls.cell = next(cell['cell_key'] for cell in registry.cells()
                        if cell['group'] == 'boat_observed')
        rows = [row for row in common_records()
                if registry.cell_key(row['sport'], row['model_id']) == cls.cell]
        cls.training = learning.fit(rows, now=cls.clock, allow_order_only=True)

    def test_full_validation_builds_registry_roster_once_before_checking_every_lineage(self):
        original = deepcopy(self.training)
        self.assertEqual(len(self.training['models'][self.cell]['source_lineage']), 8)
        with patch.object(registry, 'cells', wraps=registry.cells) as cells:
            self.assertIs(learning.verify_training(self.training), True)
        # One bound roster and the existing independent registry digest. The
        # complete registry must not be reconstructed for each lineage row.
        self.assertEqual(cells.call_count, 2)
        self.assertEqual(self.training, original)

    def test_default_validation_reads_current_registry_on_every_call(self):
        self.assertIs(learning.verify_training(self.training), True)
        with patch.object(registry, 'registry_sha256', return_value='f' * 64):
            with self.assertRaisesRegex(ValueError, 'REGISTRY_BINDING'):
                learning.verify_training(self.training)
        self.assertIs(learning.verify_training(self.training), True)

    def test_last_lineage_mutations_still_fail_after_all_outer_hashes_are_resealed(self):
        other_sport = next(cell['cell_key'] for cell in registry.cells() if cell['sport'] == 'horse')
        changes = (
            ('unknown_carrier', lambda proof: proof['partitions'][0].update(carrier_cell_key='boat/unknown')),
            ('wrong_sport', lambda proof: proof['partitions'][0].update(carrier_cell_key=other_sport)),
            ('unknown_field', lambda proof: proof['partitions'][0].update(verified=True)),
            ('wrong_type', lambda proof: proof['partitions'][0].update(training_sha256=True)),
            ('expired', lambda proof: proof['receipt']['artifact_metadata'].update(expired=True)),
            ('wrong_repository', lambda proof: proof['receipt']['artifact_metadata']['workflow_run'].update(repository_id=1)),
            ('boolean_id', lambda proof: proof['receipt'].update(artifact_id=True)),
            ('missing_field', lambda proof: proof['partitions'][0].pop('generated_at')),
        )
        for name, mutate in changes:
            bad = deepcopy(self.training)
            line = bad['models'][self.cell]['source_lineage'][-1]
            proof = line['native_generation_evidence']; mutate(proof)
            line['native_generation_receipt_sha256'] = digest(proof['receipt'])
            line['native_generation_partitions_sha256'] = digest(proof['partitions'])
            self._reseal(bad)
            before = deepcopy(bad)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'NATIVE_GENERATION'):
                learning.verify_training(bad)
            self.assertEqual(bad, before)

    def test_clock_and_container_subclasses_do_not_bypass_full_verification(self):
        class Mapping(dict):
            pass
        class Sequence(list):
            pass
        changes = (
            ('training_subclass', lambda body: Mapping(body)),
            ('partition_subclass', lambda body: self._replace_parts(body, Sequence)),
            ('late_partition', lambda body: self._late_partition(body)),
        )
        for name, mutate in changes:
            bad = mutate(deepcopy(self.training)); self._reseal(bad)
            with self.subTest(name=name), self.assertRaises(ValueError):
                learning.verify_training(bad)

    def _reseal(self, body):
        for model in body['models'].values():
            model['model_sha256'] = digest({key: value for key, value in model.items() if key != 'model_sha256'})
        body['training_sha256'] = digest({key: value for key, value in body.items() if key != 'training_sha256'})

    def _replace_parts(self, body, constructor):
        line = body['models'][self.cell]['source_lineage'][-1]
        proof = line['native_generation_evidence']
        proof['partitions'] = constructor(proof['partitions'])
        line['native_generation_partitions_sha256'] = digest(proof['partitions'])
        return body

    def _late_partition(self, body):
        line = body['models'][self.cell]['source_lineage'][-1]
        proof = line['native_generation_evidence']
        proof['partitions'][0]['generated_at'] = line['cutoff_at']
        line['actual_native_generated_at'] = line['cutoff_at']
        line['native_generation_partitions_sha256'] = digest(proof['partitions'])
        return body


if __name__ == '__main__':
    unittest.main()
