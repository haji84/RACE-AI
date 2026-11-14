"""Actual completed Nov7 reader binding; fixture keys/capsules stay synthetic."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import boat_venue_future_grid as grid


class Nov7WitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((Path(__file__).parent/'fixtures/boat_grid_nov7_readback.json').read_text())
        cls.log = gzip.decompress(base64.b64decode(cls.fixture['log_gzip_base64'], validate=True))
        projection = cls.fixture['projection']
        cls.actual_run = deepcopy(projection['run'])
        cls.actual_run['pull_requests'] = [{'number': n} for n in cls.actual_run.pop('pull_request_numbers')]
        cls.job = dict(deepcopy(projection['job']), steps=deepcopy(projection['required_steps']))
        cls.jobs = dict(total_count=1, jobs=[cls.job])
        cls.pointer = dict(schema='RACE_AI_BOAT_VENUE_DATASET_INPUT_V1', status='READY',
            repository_id='1416489937', source_commit=cls.fixture['dataset_commit'],
            dataset_sha256=cls.fixture['dataset_sha256'], dataset_path='state/boat-venue-history/v1/datasets/'+
            cls.fixture['dataset_sha256']+'/dataset.json')
        cls.manifest = dict(schema=grid.SCHEMA, dataset_pointer=cls.pointer, observed_only=True,
            course_feature_policy=grid.POLICY, readback=dict(run_id=cls.actual_run['id'], run_attempt=1,
                job_id=cls.job['id'], head_sha=cls.actual_run['head_sha'],
                metadata_sha256=cls.fixture['metadata_sha256'], log_sha256=cls.fixture['log_sha256']))
        cls.now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    def verify(self, **changes):
        values = dict(manifest=self.manifest, run=self.actual_run, jobs=self.jobs, log=self.log, now=self.now)
        values.update(changes)
        return grid.verify_readback(**values)

    def test_actual_completed_reader_and_log_match_literal_new_witness(self):
        self.assertEqual(digest(self.fixture['projection']), self.fixture['metadata_sha256'])
        self.assertEqual(sha256(self.log).hexdigest(), self.fixture['log_sha256'])
        self.assertIn(b'"source_days": 7964', self.log)
        self.assertIn(b'"manifest_sha256": "'+self.fixture['history_manifest_sha256'].encode()+b'"', self.log)
        self.assertEqual(self.verify()['completed_at'], '2026-11-07T17:18:24Z')

    def test_actual_job_owner_head_steps_or_log_tamper_cannot_admit(self):
        for mutate in (
            lambda r,j: r['actor'].update(id=1),
            lambda r,j: r.update(head_sha='f'*40),
            lambda r,j: j['jobs'][0].update(id=128471073053),
            lambda r,j: j['jobs'][0].update(run_attempt=2),
            lambda r,j: j['jobs'][0].update(status='in_progress', conclusion=None, completed_at=None),
            lambda r,j: j['jobs'][0]['steps'][-1].update(conclusion='skipped'),
        ):
            with self.subTest(mutate=mutate):
                run, jobs = deepcopy(self.actual_run), deepcopy(self.jobs); mutate(run, jobs)
                with self.assertRaises(ValueError): self.verify(run=run, jobs=jobs)
        with self.assertRaises(ValueError): self.verify(log=self.log+b'changed')

    def test_cross_spliced_legacy_readback_or_other_dataset_commit_is_rejected(self):
        for mutation in ('legacy_readback', 'other_commit', 'other_head', 'other_metadata'):
            value = deepcopy(self.manifest)
            if mutation == 'legacy_readback':
                value['readback'] = dict(run_id=grid.READBACK_RUN, run_attempt=1, job_id=grid.READBACK_JOB,
                    head_sha=grid.READBACK_HEAD, metadata_sha256=grid.METADATA_SHA, log_sha256=grid.LOG_SHA)
            elif mutation == 'other_commit': value['dataset_pointer']['source_commit'] = 'f'*40
            elif mutation == 'other_head': value['readback']['head_sha'] = 'f'*40
            else: value['readback']['metadata_sha256'] = 'f'*64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): grid.validate_manifest(value)

    def test_new_preload_uses_exact_new_routes_and_rejects_sibling_counts(self):
        from tests.test_boat_pdca_recipient import OWNER
        responses = {f'actions/runs/{self.actual_run["id"]}/attempts/1': self.actual_run,
            f'actions/runs/{self.actual_run["id"]}/attempts/1/jobs?per_page=100': self.jobs,
            f'actions/jobs/{self.job["id"]}/logs': self.log}
        calls = []
        def fetch(path):
            calls.append(path); value = responses[path]
            return value if type(value) is bytes else json.dumps(value).encode()
        ready = dict(status='ENCRYPTED_ALL_VENUE_GRID_READBACK_VERIFIED', plaintext_published=False,
            verified_cells=63432, known_racers=2643, venues=24, source_days=7964)
        for report in (dict(ready, source_days=7963), dict(ready, verified_cells=63408), ready):
            with self.subTest(report=report), tempfile.TemporaryDirectory() as folder, \
                    patch('race_ai.boat_venue_dataset.readback_dataset', return_value=report), \
                    patch('race_ai.boat_venue_dataset._manifest', return_value=(b'synthetic manifest',
                        dict(available_at=self.fixture['dataset_available_at']))), \
                    patch('race_ai.boat_venue_dataset._sha', return_value=self.pointer['dataset_sha256']):
                options = dict(gh=fetch, clock=lambda:self.now, run_id='42', head_sha='a'*40, round_no=1, key=OWNER)
                if report is ready:
                    record = grid.prepare_capability(self.manifest, folder, '.', **options)
                    self.assertEqual(record['data']['manifest'], self.manifest)
                else:
                    with self.assertRaisesRegex(ValueError, 'DATASET_RESTORE_NOT_READY'):
                        grid.prepare_capability(self.manifest, folder, '.', **options)
        self.assertEqual(set(calls), set(responses))

    def test_new_witness_retains_all_original_source_clock_gates(self):
        from tests.test_boat_pdca_recipient import OWNER
        proof = self.verify(); completed = datetime.fromisoformat(proof['completed_at'])
        with self.assertRaisesRegex(ValueError, 'READBACK_FROM_FUTURE'):
            self.verify(now=completed-timedelta(microseconds=1))
        with tempfile.TemporaryDirectory() as folder:
            verified = completed+timedelta(microseconds=500000)
            record = grid.seal_capability(self.manifest, proof, folder,
                available_at=self.fixture['dataset_available_at'], verified_at=verified.isoformat(),
                run_id='42', head_sha='a'*40, round_no=1, key=OWNER)
            cap = grid.open_capability(record, run_id='42', head_sha='a'*40, round_no=1, key=OWNER)
            for source in (self.fixture['dataset_available_at'], verified.isoformat(),
                           (completed+timedelta(seconds=1)).isoformat()):
                with self.subTest(source=source), self.assertRaises(ValueError): grid.require_before_source(cap, source)
            grid.require_before_source(cap, (completed+timedelta(seconds=1, microseconds=1)).isoformat())

    def test_reader_routes_are_only_both_literal_witnesses(self):
        from scripts import boat_all_model_cycle as cli
        expected = {f'actions/runs/{run}/attempts/1{tail}' for run in (grid.READBACK_RUN, self.actual_run['id'])
            for tail in ('', '/jobs?per_page=100')}
        expected |= {f'actions/jobs/{job}/logs' for job in (grid.READBACK_JOB, self.job['id'])}
        expected |= {f'actions/runs/{run}/attempts/1/logs' for run in (grid.READBACK_RUN,self.actual_run['id'])}
        self.assertEqual(set(grid.readback_routes()), expected)
        with patch('scripts.github_existing_cycle._live_gh', return_value=b'actual GitHub fixture') as fetch, \
                patch('race_ai.boat_history_log_archive.extract_readback_log',return_value=b'actual GitHub fixture'):
            for path in expected: self.assertEqual(cli._prospective_grid_get(path), b'actual GitHub fixture')
            self.assertEqual(fetch.call_count, 8)
            for path in ('actions/runs/1/attempts/1', f'actions/runs/{self.actual_run["id"]}/attempts/2',
                         f'actions/jobs/{self.job["id"]+1}/logs'):
                with self.assertRaises(ValueError): cli._prospective_grid_get(path)
            self.assertEqual(fetch.call_count, 8)

    def test_fourteen_new_native_cells_use_selected_proof(self):
        from race_ai import all_existing_model_registry as registry
        info = dict(as_of='2026-11-07T17:18:25.000001Z', stage='P1', race_id='synthetic',
                    race_cutoff_at='2030-01-01T01:00:00Z', roster=['1','2','3','4','5','6'], scope='synthetic')
        audit = dict(schema='RACE_AI_PROSPECTIVE_BOAT_GRID_NATIVE_EVIDENCE_V1', manifest=self.manifest,
            readback_proof=self.verify(), dataset_pointer=self.pointer,
            original_source_as_of=info['as_of'], new_native_as_of=info['as_of'],
            dataset_available_at=self.fixture['dataset_available_at'], dataset_verified_at='2026-11-07T17:18:24.5Z')
        rows = [dict(cell_key=c['cell_key'], native_payload=dict(prospective_grid_evidence=deepcopy(audit)))
                for c in registry.active_cells() if c['sport']=='boat']
        self.assertEqual(len(rows), 14)
        with patch.object(registry, 'validate_payload', return_value=info), \
                patch('race_ai.all_existing_model_learning._sources', return_value=set()), \
                patch('race_ai.existing_model_dispatch._race_key', return_value='synthetic'):
            self.assertEqual(grid.prospective_requests(rows, now=self.now), rows)
            with self.assertRaisesRegex(ValueError, 'CARRIER_INCOMPLETE_FOURTEEN'):
                grid.prospective_requests(rows[:-1], now=self.now)
            for mutation in ('log', 'dataset', 'completed_at'):
                changed = deepcopy(rows)
                evidence = changed[0]['native_payload']['prospective_grid_evidence']
                if mutation == 'log': evidence['readback_proof']['log_sha256'] = grid.LOG_SHA
                elif mutation == 'dataset':
                    evidence['dataset_pointer'] = dict(evidence['dataset_pointer'], dataset_sha256='f'*64)
                else: evidence['readback_proof']['completed_at'] = '2026-11-07T11:00:00Z'
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'CARRIER_GRID_PROOF'):
                    grid.prospective_requests(changed, now=self.now)

    def test_carrier_rejects_one_native_clock_before_common_original_source_clock(self):
        from race_ai import all_existing_model_registry as registry
        master = '2026-11-07T17:18:26.000001Z'
        info = dict(as_of=master, stage='P1', race_id='synthetic',
            race_cutoff_at='2030-01-01T01:00:00Z', roster=['1','2','3','4','5','6'], scope='synthetic')
        audit = dict(schema='RACE_AI_PROSPECTIVE_BOAT_GRID_NATIVE_EVIDENCE_V1', manifest=self.manifest,
            readback_proof=self.verify(), dataset_pointer=self.pointer,
            original_source_as_of=master, new_native_as_of=master,
            dataset_available_at=self.fixture['dataset_available_at'], dataset_verified_at='2026-11-07T17:18:24.5Z')
        rows = [dict(cell_key=c['cell_key'], native_payload=dict(native_as_of=master,
                    prospective_grid_evidence=deepcopy(audit)))
                for c in registry.active_cells() if c['sport']=='boat']
        self.assertEqual(len(rows), 14)

        # The native schema validators supply identity; this consumer must
        # additionally require its clock to equal the common capture clock.
        def accepted_identity(model_id, sport, native, *, at, allow_source):
            return dict(info, as_of=native['native_as_of'])

        with patch.object(registry, 'validate_payload', side_effect=accepted_identity), \
                patch('race_ai.all_existing_model_learning._sources', return_value=set()), \
                patch('race_ai.existing_model_dispatch._race_key', return_value='synthetic'):
            self.assertEqual(grid.prospective_requests(rows, now=self.now), rows)
            earlier = deepcopy(rows)
            earlier[0]['native_payload']['native_as_of'] = '2026-11-07T17:18:26Z'
            with self.assertRaisesRegex(ValueError, 'CARRIER_ORIGINAL_CLOCK'):
                grid.prospective_requests(earlier, now=self.now)


if __name__ == '__main__': unittest.main()
