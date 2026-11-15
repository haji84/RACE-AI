"""Unfitted multisport native input retention on fictional encrypted artifacts."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import all_existing_model_pairs as pairs
from race_ai import all_existing_model_registry as registry
from race_ai.boat_venue_learning import read_candidate
from tests import test_all_existing_model_pairs as pair_fixtures
from tests.test_comprehensive_four_sport_models import sample

FORECAST_NOW = pair_fixtures.FORECAST_NOW


class NativeInputBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pair_fixtures.AllExistingModelPrivatePairsTests.setUpClass()

    def setUp(self):
        self.fixture = pair_fixtures.AllExistingModelPrivatePairsTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def request(self, sport, number=1):
        member = next(cell for cell in registry.cells() if cell['sport'] == sport and cell['group'] == 'shared')
        snapshot = sample(sport, size=3)
        snapshot['race'].update(race_id=f'{sport}:2030-04-01:fictional-venue:{number}',
            event_date_jst='2030-04-01', as_of=(FORECAST_NOW-timedelta(seconds=1)).isoformat(),
            sales_cutoff_at=(FORECAST_NOW+timedelta(minutes=20)).isoformat())
        return dict(cell_key=member['cell_key'], native_payload=dict(
            snapshot=snapshot, stage='P1', scope='SYNTHETIC_ONLY'))

    def generate(self, requests):
        return pairs.make_private_pairs(self.fixture.context, requests, self.fixture.root/'pairs',
                                        now=FORECAST_NOW, allow_source=lambda *args: True)

    def payloads(self):
        return [read_candidate(folder) for folder in (self.fixture.root/'pairs').iterdir() if folder.is_dir()]

    def test_first_unfitted_keirin_horse_and_auto_inputs_freeze_without_predictions(self):
        requests = [self.request(sport) for sport in ('keirin', 'horse', 'autorace')]
        original = deepcopy(requests)
        with patch.object(pairs, 'forecast_pair', side_effect=AssertionError('unfitted inputs have no forecast')):
            summary = self.generate(requests)
            payloads = self.payloads()
            for payload in payloads:
                self.assertTrue(pairs.verify_private_record(payload))
        self.assertEqual(summary['partition_count'], 3)
        self.assertEqual(summary['forecast_partition_count'], 0)
        self.assertEqual(summary['frozen_input_only_partition_count'], 3)
        self.assertEqual(summary['baseline_forecast_count'], 0)
        self.assertEqual(summary['learned_forecast_count'], 0)
        self.assertEqual(summary['captured_native_input_count'], 3)
        self.assertEqual(summary['unretained_native_input_count'], 0)
        self.assertEqual(requests, original)
        for payload in payloads:
            self.assertEqual(payload['schema'], pairs.INPUTS_SCHEMA)
            self.assertNotIn('pair', payload); self.assertNotIn('baseline', payload); self.assertNotIn('learned', payload)
            self.assertEqual(payload['training'], self.fixture.context['training'])
            capsule = payload['captured_native_inputs'][0]
            request = next(row for row in requests if row['cell_key'] == capsule['cell_key'])
            self.assertEqual(capsule['native_payload'], request['native_payload'])
            self.assertEqual(capsule['input_sha256'], digest(request['native_payload']))
            self.assertEqual(payload['summary']['baseline_forecast_count'], 0)
        for secret in ('native_payload', 'synthetic-runner-', 'features', 'source_ref'):
            self.assertNotIn(secret, json.dumps(summary))

    def test_source_only_archive_checks_actual_digest_and_all_cutoffs(self):
        self.generate([self.request('horse')])
        raw, _ = self.fixture.archive(); summary = self.fixture.verify(raw)
        self.assertEqual(summary['forecast_partition_count'], 0)
        self.assertEqual(summary['frozen_input_only_partition_count'], 1)
        self.assertEqual(summary['baseline_forecast_count'], 0)
        self.assertEqual(summary['learned_forecast_count'], 0)
        self.assertEqual(summary['captured_native_input_count'], 1)
        self.assertTrue(summary['independent_pre_cutoff_receipt_verified'])
        bad = self.fixture.metadata(raw, digest='sha256:'+'0'*64)
        with self.assertRaises(ValueError):
            self.fixture.verify(raw, bad)
        cutoff = FORECAST_NOW+timedelta(minutes=20)
        late = self.fixture.metadata(raw, created_at=(cutoff-timedelta(seconds=1)).isoformat())
        with self.assertRaisesRegex(ValueError, 'CUTOFF'):
            self.fixture.verify(raw, late)

    def test_unfitted_families_share_one_input_only_race_partition(self):
        requests = [self.request('horse')]
        second = deepcopy(requests[0])
        second['cell_key'] = next(cell['cell_key'] for cell in registry.cells()
            if cell['sport'] == 'horse' and cell['group'] == 'shared' and cell['cell_key'] != requests[0]['cell_key'])
        requests.append(second)
        summary = self.generate(requests)
        self.assertEqual(summary['partition_count'], 1)
        self.assertEqual(summary['frozen_input_only_partition_count'], 1)
        self.assertEqual(summary['captured_native_input_count'], 2)
        self.assertEqual(len(self.payloads()[0]['captured_native_inputs']), 2)

    def test_input_only_late_seal_is_quarantined_and_existing_output_is_preserved(self):
        with patch.object(pairs.time, 'monotonic', side_effect=[0, 0, 3600]):
            with self.assertRaisesRegex(ValueError, 'CUTOFF_ELAPSED_DURING_SEAL'):
                self.generate([self.request('autorace')])
        root = self.fixture.root/'pairs'
        self.assertTrue((root/'quarantine.json').exists())
        self.assertEqual(len(self.payloads()), 1)
        before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
            self.generate([self.request('autorace')])
        self.assertEqual(before, {str(path.relative_to(root)): path.read_bytes()
                                 for path in root.rglob('*') if path.is_file()})

    def test_mixed_prediction_and_input_only_partitions_keep_counts_separate(self):
        requests = [dict(cell_key=self.fixture.cell, native_payload=self.fixture.native()), self.request('keirin')]
        summary = self.generate(requests)
        self.assertEqual(summary['partition_count'], 2)
        self.assertEqual(summary['forecast_partition_count'], 1)
        self.assertEqual(summary['frozen_input_only_partition_count'], 1)
        self.assertEqual(summary['baseline_forecast_count'], 1)
        raw, _ = self.fixture.archive(); admitted = self.fixture.verify(raw)
        self.assertEqual(admitted['partition_count'], 2)
        self.assertEqual(admitted['forecast_partition_count'], 1)
        self.assertEqual(admitted['frozen_input_only_partition_count'], 1)
        self.assertEqual(admitted['baseline_forecast_count'], 1)
        self.assertEqual(admitted['captured_native_input_count'], 2)

    def test_input_only_capsules_are_bound_to_hash_sport_race_and_clocks(self):
        self.generate([self.request('autorace')]); original = self.payloads()[0]
        for kind in ('hash', 'sport', 'race', 'future'):
            payload = deepcopy(original)
            if kind == 'hash':
                payload['captured_native_inputs'][0]['input_sha256'] = 'f'*64
            elif kind == 'sport':
                payload['sport'] = 'horse'
            elif kind == 'race':
                payload['race_id'] = 'autorace:2030-04-01:fictional-venue:2'
            else:
                payload['generated_at'] = (FORECAST_NOW+timedelta(hours=1)).isoformat()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                pairs.verify_private_record(payload)


if __name__ == '__main__':
    unittest.main()
