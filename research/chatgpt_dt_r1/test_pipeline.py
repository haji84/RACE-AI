"""Synthetic pipeline boundary tests, not race-accuracy evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.chatgpt_dt_r1.pipeline import (
    DEFAULT_SPLITS, check_splits, partition, forecast_row, write_private_json,
    summarize_predictions, freeze_evaluation_contract,
)
from research.chatgpt_dt_r1.test_model import fixture
from research.chatgpt_dt_r1.model import RankModel


class PipelineTests(unittest.TestCase):
    def test_temporal_partition_and_overlap_rejected(self):
        rows = [fixture(i, day=day) for i, day in enumerate(
            ['2026-06-30', '2026-07-01', '2026-08-01', '2026-09-01', '2026-10-01'])]
        split = partition(rows, DEFAULT_SPLITS)
        self.assertEqual([len(split[k]) for k in ('fit', 'tune', 'calibration', 'audit', 'test')], [1] * 5)
        broken = {k: dict(v) for k, v in DEFAULT_SPLITS.items()}
        broken['test']['start'] = '2026-09-30'
        with self.assertRaisesRegex(ValueError, 'OVERLAP'):
            check_splits(broken)

    def test_retrospective_has_no_fake_prediction_clock(self):
        row = fixture()
        model = RankModel.zero(row['feature_names'])
        forecast = forecast_row(model, row)
        self.assertIsNone(forecast['prediction_at'])
        self.assertIsNone(forecast['cutoff_at'])
        self.assertEqual(forecast['cohort'], 'retrospective')
        self.assertEqual(forecast['confidence']['label'], 'HOLD')

    def test_held_feature_fallback_must_never_be_ready(self):
        row = fixture()
        row['feature_status'] = 'HOLD_NONFINITE_FEATURE'
        row['features'][:] = 0
        result = forecast_row(RankModel.zero(row['feature_names']), row)
        self.assertEqual(result['status'], 'HOLD')
        self.assertEqual(result['reason'], 'HOLD_NONFINITE_FEATURE')

    def test_prospective_checks_all_parameter_dates_and_jst_day(self):
        row = fixture(day='2026-07-15')
        row.update(cohort='prospective', cutoff_at='2026-07-15T03:00:00Z',
                   available_at='2026-07-15T01:00:00Z', source_attestation_sha256='a' * 64)
        model = RankModel.zero(row['feature_names'])
        model.fit_meta.update(created_at='2026-06-30T00:00:00Z', training_last_day='2026-06-29',
                              temperature_calibration={'end_day': '2026-07-31'})
        with self.assertRaisesRegex(ValueError, 'MODEL_FROM_FUTURE'):
            forecast_row(model, row, prediction_at='2026-07-15T02:00:00Z')
        del model.fit_meta['temperature_calibration']
        row['day'] = '2026-08-30'
        with self.assertRaisesRegex(ValueError, 'RACE_DAY'):
            forecast_row(model, row, prediction_at='2026-07-15T02:00:00Z')

    def test_all_target_coverage_and_non_predicted_miss(self):
        row = fixture()
        row['top3'] = [1, 2, 3]
        model = RankModel.zero(row['feature_names'])
        predicted = forecast_row(model, row)
        missing = fixture(99)
        cancelled = fixture(98); cancelled['top3'] = None; cancelled['result_status'] = 'cancelled'
        metrics = summarize_predictions([predicted], [row, missing, cancelled])
        self.assertEqual(metrics['registered'], 3)
        self.assertEqual(metrics['evaluable'], 2)
        self.assertEqual(metrics['predicted_evaluable'], 1)
        self.assertEqual(metrics['trifecta']['1']['hits'], 1)
        self.assertEqual(metrics['trifecta']['1']['all_target_rate'], .5)
        self.assertEqual(metrics['not_evaluable']['cancelled'], 1)

    def test_resolved_tail_ties_and_status_case_are_consistent(self):
        from research.chatgpt_dt_r1.pipeline import _result_key
        row = fixture()
        row.update(result_status='DEAD_HEAT')
        self.assertIsNone(_result_key(row))
        row['result_status'] = 'dead_heat'
        self.assertIsNone(_result_key(row))
        row['result_rows'] = [{'car': car, 'rank': rank} for rank, car in enumerate(row['top3'], 1)]
        self.assertEqual(_result_key(row), tuple(row['top3']))
        row['result_status'] = 'DEAD_HEAT'
        self.assertEqual(_result_key(row), tuple(row['top3']))
        row['result_status'] = 'CANCELLED'
        self.assertIsNone(_result_key(row))

    def test_private_write_create_only_and_contract_pin(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'model.json'
            write_private_json(path, {'a': 1})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_private_json(path, {'a': 2})
            root = Path(d) / 'run'
            contract = freeze_evaluation_contract(root, DEFAULT_SPLITS, {'sources': ['a' * 64]})
            self.assertEqual(json.loads((root / 'evaluation_contract.json').read_text()), contract)
            with self.assertRaises(FileExistsError):
                freeze_evaluation_contract(root, DEFAULT_SPLITS, {'sources': ['b' * 64]})

    def test_private_original_cannot_be_written_in_git(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / '.git').mkdir()
            with self.assertRaisesRegex(ValueError, 'PRIVATE_STATE_MUST_BE_OUTSIDE_GIT'):
                write_private_json(root / 'forecast.json', {'private': True})

    def test_context_hash_and_parse_consume_the_same_snapshot(self):
        from hashlib import sha256
        from research.chatgpt_dt_r1.pipeline import run_study
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'venues.json'
            original = {'records': [{'venue_code': '01', 'name': 'Synthetic',
                'source_url': 'https://example.com/geometry', 'source_sha256': 'a' * 64,
                'retrieved_at': '2026-01-01T00:00:00Z', 'circumference_m': 400,
                'straight_m': 50, 'cant_deg': 30}]}
            path.write_text(json.dumps(original))
            pinned = sha256(path.read_bytes()).hexdigest()
            observed = []
            def progress(message):
                if message.startswith('Admitted'):
                    altered = json.loads(json.dumps(original))
                    altered['records'][0]['straight_m'] = 70
                    path.write_text(json.dumps(altered))
            def stop_after_context(rows, **kwargs):
                observed.append(kwargs['venue_store'].records[0].straight_m)
                raise RuntimeError('STOP_AFTER_SNAPSHOT_CHECK')
            with patch('research.chatgpt_dt_r1.data.load_archives', return_value=([], {'sources': []})), \
                 patch('research.chatgpt_dt_r1.features.build_features', return_value=[]), \
                 patch('research.chatgpt_dt_r1.context.augment_features', side_effect=stop_after_context):
                with self.assertRaisesRegex(RuntimeError, 'STOP_AFTER_SNAPSHOT_CHECK'):
                    run_study([], root / 'run', venue_path=path, progress=progress)
            contract = json.loads((root / 'run' / 'evaluation_contract.json').read_text())
            self.assertEqual(observed, [50])
            self.assertEqual(contract['input_context']['venue_file_sha256'], pinned)


if __name__ == '__main__':
    unittest.main()
