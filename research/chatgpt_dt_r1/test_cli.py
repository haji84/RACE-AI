"""CLI integration boundaries, all with synthetic inputs and no remote calls."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from research.chatgpt_dt_r1.cli import main
from research.chatgpt_dt_r1.test_calibration_policy_comparison import forecast, odds


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def run_cli(self, *args):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = main(list(args))
        self.assertEqual(result, 0)
        return json.loads(stdout.getvalue())

    def test_selection_end_to_end_preserves_pin_and_can_choose_one(self):
        f = forecast(cohort='prospective')
        args = ('select', '--forecast', self.put('f.json', f), '--odds', self.put('odds.json', odds(f)),
                '--at', '2026-10-01T10:04:00Z', '--output', str(self.root / 'choice.json'))
        result = self.run_cli(*args)
        self.assertEqual(result['ticket_count'], 1)
        self.assertEqual(result['confidence'], 'HOLD')
        saved = json.loads((self.root / 'choice.json').read_text())
        from research.chatgpt_dt_r1.policy import digest
        selected = saved['selection']
        self.assertEqual(selected['selection_sha256'], digest({k: v for k, v in selected.items() if k != 'selection_sha256'}))
        self.assertFalse(saved['independent_source_attestation'])
        with self.assertRaises(FileExistsError):
            main(list(args))

    def test_private_cli_output_rejected_under_git(self):
        (self.root / '.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'PRIVATE_STATE_MUST_BE_OUTSIDE_GIT'):
            main(['select', '--forecast', self.put('f.json', forecast(cohort='prospective')),
                  '--at', '2026-10-01T10:04:00Z', '--output', str(self.root / 'private.json')])
        self.assertFalse((self.root / 'private.json').exists())

    def test_empty_phase_evidence_does_not_produce_fake_model(self):
        response = self.run_cli('fit-phases', '--history', self.put('history.json', []),
            '--observations', self.put('labels.json', []), '--before', '2026-07-01',
            '--available-by', '2026-07-01T00:00:00Z', '--output', str(self.root / 'phases.json'))
        self.assertEqual(response['status'], 'HOLD')
        self.assertTrue(all(row['usable_label_pairs'] == 0 for row in response['coverage'].values()))

    def test_ledger_cli_explicit_init_and_missing_state_stop(self):
        path = str(self.root / 'ledger.sqlite')
        with self.assertRaisesRegex(ValueError, 'MISSING_STATE_STOP_NO_RESET'):
            main(['ledger-status', '--path', path])
        response = self.run_cli('ledger-init', '--path', path, '--participant-id', 'existing-integrated',
            '--participant-id', 'codex-new', '--participant-id', 'chatgpt-dt-r1')
        self.assertEqual(response['verified_forecasts'], 0)
        self.run_cli('ledger-status', '--path', path)
        with self.assertRaises(ValueError):
            main(['ledger-init', '--path', path, '--participant-id', 'existing-integrated',
                  '--participant-id', 'codex-new', '--participant-id', 'chatgpt-dt-r1'])

    def test_aggregate_report_cli_does_not_leak_attached_raw_rows(self):
        response = self.run_cli('report', '--report', self.put('report.json', {'private_forecasts': 'NEVER_PUBLIC'}),
                               '--output', str(self.root / 'aggregate.html'))
        self.assertEqual(response['mode'], 'aggregate')
        self.assertNotIn('NEVER_PUBLIC', (self.root / 'aggregate.html').read_text())

    def test_forecast_cli_rebuilds_agari_schema(self):
        from research.chatgpt_dt_r1.agari import augment_agari
        from research.chatgpt_dt_r1.features import build_features
        from research.chatgpt_dt_r1.model import RankModel
        from research.chatgpt_dt_r1.test_agari import records
        history, row = records()
        feature = augment_agari(build_features([history, row]))[-1]
        model = RankModel.zero(feature['feature_names'])
        status = self.run_cli('forecast', '--model', self.put('agari-model.json',model.to_dict()),
            '--record',self.put('target.json',row),'--history',self.put('history.json',[history]),
            '--output',str(self.root/'agari-prediction.json'))
        self.assertEqual(status['status'],'READY')
        out=json.loads((self.root/'agari-prediction.json').read_text())
        self.assertEqual(out['feature_input_sha256'],feature['feature_input_sha256'])

    def test_prospective_cli_rejects_future_or_untimed_history_result(self):
        from research.chatgpt_dt_r1.features import FEATURE_NAMES
        from research.chatgpt_dt_r1.model import RankModel
        from research.chatgpt_dt_r1.test_context import card
        target = card()
        target.update(day='2026-10-01', cohort='prospective', available_at='2026-10-01T09:00:00Z',
                      cutoff_at='2026-10-01T10:30:00Z', source_attestation_sha256='b' * 64)
        prior = card()
        prior.update(race_id='history', day='2026-09-30', available_at='2026-09-30T09:00:00Z',
                     result_at='2026-10-01T11:00:00Z', result_rows=[{'car': 1, 'rank': 1}])
        model = RankModel.zero(FEATURE_NAMES)
        model.fit_meta.update(created_at='2026-09-01T00:00:00Z', training_last_day='2026-08-31')
        command = ['forecast', '--model', self.put('model.json', model.to_dict()),
                   '--record', self.put('record.json', target), '--history', str(self.root / 'history.json'),
                   '--at', '2026-10-01T10:05:00Z', '--output', str(self.root / 'out.json')]
        for result_at, reason in [('2026-10-01T11:00:00Z', 'HISTORY_RESULT_AFTER_PREDICTION'),
                                  (None, 'HISTORY_RESULT_AVAILABILITY_REQUIRED')]:
            prior['result_at'] = result_at
            self.put('history.json', [prior])
            with self.assertRaisesRegex(ValueError, reason):
                main(command)
        self.assertFalse((self.root / 'out.json').exists())


if __name__ == '__main__':
    unittest.main()
