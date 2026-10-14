"""Synthetic offline learning tests; none are live accuracy evidence."""
import copy
from datetime import datetime, timedelta, timezone
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


BASE = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)


def stamp(value):
    return value.isoformat(timespec='seconds')


def dataset():
    rows = []
    for index in range(12):
        start = BASE + timedelta(hours=index * 2 + 1)
        asof = start - timedelta(minutes=10)
        snapshots = []
        for lane in range(1, 7):
            snapshots.append(dict(lane=lane, features={'historical_win_rate': (7 - lane) / 10},
                available_at=stamp(asof - timedelta(minutes=1)), captured_at=stamp(asof - timedelta(minutes=1)),
                generated_at=stamp(asof - timedelta(minutes=1)), source_ref='synthetic-feature'))
        rows.append(dict(race_id=f'synthetic-{index:02d}', race_start_at=stamp(start), as_of=stamp(asof),
            source_kind='synthetic', boats=snapshots, label=dict(status='settled', confirmed=True,
                top3=[1, 2, 3], available_at=stamp(start + timedelta(minutes=5)),
                captured_at=stamp(start + timedelta(minutes=5)), source_ref='synthetic-result')))
    return rows


def config(**changes):
    value = dict(feature_names=['historical_win_rate'], train_end_at=stamp(BASE + timedelta(hours=8)),
                 validation_end_at=stamp(BASE + timedelta(hours=16)), evaluation_as_of=stamp(BASE + timedelta(hours=25)),
                 epochs=100, learning_rate=.1, l2=.02, temperature_grid=[.5, 1, 2], calibration_bins=10)
    value.update(changes)
    return value


class TrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.t = importlib.import_module('race_ai.model_training')
        except ModuleNotFoundError:
            cls.t = None

    def setUp(self):
        self.assertIsNotNone(self.t, 'offline chronological learning pipeline must exist')

    def run_training(self, records=None, settings=None):
        return self.t.train_and_evaluate(records or dataset(), settings or config())

    def test_chronological_split_is_stable_and_reports_all_sample_ids(self):
        run = self.run_training(list(reversed(dataset())))
        self.assertEqual(run['report']['splits']['train'], [f'synthetic-{i:02d}' for i in range(4)])
        self.assertEqual(run['report']['splits']['validation'], [f'synthetic-{i:02d}' for i in range(4, 8)])
        self.assertEqual(run['report']['splits']['final_test'], [f'synthetic-{i:02d}' for i in range(8, 12)])
        self.assertEqual(run['artifact']['artifact_sha256'], self.run_training()['artifact']['artifact_sha256'])
        self.assertTrue(run['report']['retrospective_research'])
        self.assertFalse(run['report']['actual_pre_race_performance'])

    def test_fitted_model_learns_synthetic_order_and_beats_uniform_on_same_holdout(self):
        run = self.run_training()
        self.assertGreater(run['artifact']['weights'][0], 0)
        self.assertEqual(run['artifact']['selected_model'], 'linear_plackett_luce')
        final = run['report']['metrics']['final_test']
        self.assertEqual(final['uniform']['race_count'], 4)
        self.assertEqual(final['fitted']['race_count'], 4)
        self.assertAlmostEqual(final['uniform']['log_loss'], math.log(120), places=12)
        self.assertAlmostEqual(final['uniform']['multiclass_brier'], 119 / 120, places=12)
        self.assertLess(final['fitted']['log_loss'], final['uniform']['log_loss'])
        self.assertEqual(sum(row['sample_count'] for row in final['fitted']['calibration']), 480)

    def test_final_test_labels_do_not_change_scaler_weights_calibration_or_selection(self):
        original = self.run_training()
        changed = dataset()
        for row in changed[8:]:
            row['label']['top3'] = [6, 5, 4]
        revised = self.run_training(changed)
        self.assertEqual(original['artifact'], revised['artifact'])
        self.assertNotEqual(original['report']['metrics']['final_test']['fitted']['log_loss'],
                            revised['report']['metrics']['final_test']['fitted']['log_loss'])

    def test_final_test_features_do_not_fit_the_training_scaler(self):
        original = self.run_training()
        changed = dataset()
        for row in changed[8:]:
            for boat in row['boats']:
                boat['features']['historical_win_rate'] = 1
        revised = self.run_training(changed)
        self.assertEqual(original['artifact'], revised['artifact'])

    def test_validation_only_selection_can_retain_uniform_without_promoting_it(self):
        changed = dataset()
        for row in changed[4:8]:
            row['label']['top3'] = [6, 5, 4]
        run = self.run_training(changed)
        self.assertEqual(run['artifact']['selected_model'], 'uniform')
        self.assertEqual(run['artifact']['selection_reason'], 'validation_did_not_improve_over_uniform')
        self.assertEqual(run['artifact']['validation_status'], 'UNVALIDATED')
        self.assertFalse(run['artifact']['eligible_for_live_recommendations'])

    def test_future_features_current_outcomes_missing_values_and_duplicate_races_rejected(self):
        for mutate in (
            lambda d: d[0]['boats'][0].update(captured_at=d[0]['race_start_at']),
            lambda d: d[0]['boats'][0]['features'].update(actual_st=.1),
            lambda d: d[0]['boats'][0]['features'].update(historical_win_rate=float('nan')),
            lambda d: d[0]['boats'][0]['features'].clear(),
            lambda d: d.append(copy.deepcopy(d[0])),
            lambda d: d[0].update(finish=[1,2,3]),
        ):
            records = dataset()
            mutate(records)
            with self.subTest(mutation=repr(mutate)), self.assertRaises(self.t.TrainingError):
                self.run_training(records)

    def test_labels_must_be_known_before_each_phase_freeze(self):
        for index, after in ((0, BASE + timedelta(hours=9)), (4, BASE + timedelta(hours=17)),
                             (8, BASE + timedelta(hours=26))):
            records = dataset()
            records[index]['label']['captured_at'] = stamp(after)
            with self.subTest(index=index), self.assertRaises(self.t.TrainingError):
                self.run_training(records)

    def test_validation_and_test_decision_times_cannot_precede_model_freezes(self):
        records = dataset()
        records[4]['as_of'] = stamp(BASE + timedelta(hours=7, minutes=59))
        for boat in records[4]['boats']:
            for field in ('available_at', 'captured_at', 'generated_at'):
                boat[field] = records[4]['as_of']
        with self.assertRaises(self.t.TrainingError):
            self.run_training(records)

    def test_invalid_split_optimizer_schema_and_unconfirmed_labels_rejected(self):
        for settings in (config(train_end_at=config()['validation_end_at']), config(epochs=0),
                         config(feature_names=['actual_st']), config(l2=-1), config(temperature_grid=[])):
            with self.subTest(settings=settings), self.assertRaises(self.t.TrainingError):
                self.run_training(settings=settings)
        records = dataset()
        records[0]['label']['confirmed'] = False
        with self.assertRaises(self.t.TrainingError):
            self.run_training(records)

    def test_empty_chronological_partition_is_not_reported_as_zero_error(self):
        with self.assertRaises(self.t.TrainingError):
            self.run_training(dataset()[:8])

    def test_export_load_integrity_and_inference_remain_research_only(self):
        run = self.run_training()
        encoded = self.t.export_model(run)
        bundle = self.t.load_model(encoded)
        self.assertEqual(bundle['artifact'], run['artifact'])
        next_record = copy.deepcopy(dataset()[0])
        next_record.pop('label')
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        next_record.update(race_id='future-research', race_start_at=stamp(future),
                           as_of=stamp(future - timedelta(minutes=30)))
        for boat in next_record['boats']:
            for field in ('available_at', 'captured_at', 'generated_at'):
                boat[field] = next_record['as_of']
        forecast = self.t.predict_with_artifact(bundle, next_record, generated_at=stamp(future - timedelta(minutes=20)))
        self.assertEqual(len(forecast['triples']), 120)
        self.assertEqual(forecast['validation_status'], 'UNVALIDATED')
        self.assertEqual(forecast['purchase_recommendations'], [])
        self.assertEqual(forecast['model_version'], run['artifact']['artifact_sha256'])
        broken = json.loads(encoded)
        broken['artifact']['weights'][0] += 1
        with self.assertRaises(self.t.TrainingError):
            self.t.load_model(json.dumps(broken))

    def test_artifact_created_after_historical_asof_cannot_be_used_as_prerace_model(self):
        bundle = self.run_training()
        historical = copy.deepcopy(dataset()[0])
        historical.pop('label')
        with self.assertRaises(self.t.TrainingError):
            self.t.predict_with_artifact(bundle, historical, generated_at=historical['as_of'])

    def test_offline_cli_outputs_a_replayable_report_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'data.json').write_text(json.dumps(dataset()), encoding='utf-8')
            (path / 'config.json').write_text(json.dumps(config(epochs=10)), encoding='utf-8')
            execution = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'race_ai.model_training',
                '--dataset', str(path / 'data.json'), '--config', str(path / 'config.json'),
                '--output', str(path / 'run.json')], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(execution.returncode, 0, execution.stderr)
            saved = json.loads((path / 'run.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['artifact']['validation_status'], 'UNVALIDATED')
            self.assertTrue(saved['report']['retrospective_research'])

    def test_duplicate_model_json_keys_and_invalid_manifest_are_rejected(self):
        run = self.run_training()
        encoded = self.t.export_model(run)
        duplicated = encoded.replace('"format_version":1', '"format_version":1,"format_version":1', 1)
        with self.assertRaises(self.t.TrainingError):
            self.t.load_model(duplicated)
        broken = json.loads(encoded)
        broken['manifest']['created_at'] = '2020-01-01T00:00:00Z'
        with self.assertRaises(self.t.TrainingError):
            self.t.load_model(json.dumps(broken))

    def test_future_evaluation_cutoff_cannot_manufacture_observed_labels(self):
        future = datetime.now(timezone.utc) + timedelta(days=1)
        with self.assertRaises(self.t.TrainingError):
            self.run_training(settings=config(evaluation_as_of=stamp(future)))

    def test_unsupported_outcomes_are_explicit_exclusions(self):
        records = dataset()
        records[0]['label']['status'] = 'dead_heat'
        report = self.run_training(records)['report']
        self.assertEqual(report['excluded'], [dict(race_id='synthetic-00', phase='train', reason='unsupported_result:dead_heat')])
        self.assertEqual(len(report['splits']['train']), 3)

    def test_validly_hashed_but_incomplete_or_wrong_version_artifact_is_rejected(self):
        original = json.loads(self.t.export_model(self.run_training()))
        for mutation in ('missing_selection_reason', 'boolean_format_version'):
            bundle = copy.deepcopy(original)
            if mutation == 'missing_selection_reason':
                del bundle['artifact']['selection_reason']
            else:
                bundle['artifact']['format_version'] = True
            body = {k: v for k, v in bundle['artifact'].items() if k != 'artifact_sha256'}
            bundle['artifact']['artifact_sha256'] = self.t._sha(body)
            bundle['manifest']['artifact_sha256'] = bundle['artifact']['artifact_sha256']
            bundle['manifest']['manifest_sha256'] = self.t._sha({k: v for k, v in bundle['manifest'].items() if k != 'manifest_sha256'})
            with self.subTest(mutation=mutation), self.assertRaises(self.t.TrainingError):
                self.t.load_model(json.dumps(bundle))


if __name__ == '__main__':
    unittest.main()
