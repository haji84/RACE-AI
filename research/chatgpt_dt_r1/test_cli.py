"""CLI integration boundaries, all with synthetic inputs and no remote calls."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from research.chatgpt_dt_r1.cli import main
from research.chatgpt_dt_r1.test_calibration_policy_comparison import forecast, odds, MODEL_IDS, SPLITS


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

    def test_fixed_selection_uses_saved_calibrator_without_inventing_clocks(self):
        from research.chatgpt_dt_r1.policy import fixed_selection
        from research.chatgpt_dt_r1.calibration import fit_calibrator, audit_calibrator
        f = forecast()
        template = fixed_selection(f, 2)
        def rows(month):
            return [dict(template, race_id=f'fixture-{month}-{i}',
                         day=f'2026-{month}-{10 + i % 2}', hit=1) for i in range(80)]
        fitted = fit_calibrator(rows('08'), split_manifest=SPLITS,
            lineage={k: template[k] for k in ('model_id', 'model_sha256', 'policy_sha256')},
            config={'min_calibration_n': 20, 'min_audit_n': 20, 'min_audit_days': 2})
        calibrator = self.put('calibrator.json', audit_calibrator(fitted, rows('09')))
        for cohort, label in [('retrospective', 'HOT'), ('prospective', 'HOLD')]:
            with self.subTest(cohort=cohort):
                output = self.root / (cohort + '.json')
                result = self.run_cli('select', '--forecast', self.put('forecast.json', forecast(cohort=cohort)),
                    '--fixed-k', '2', '--calibrator', calibrator, '--output', str(output))
                saved = json.loads(output.read_text())
                selection, confidence = saved['selection'], saved['confidence_assessment']
                self.assertEqual(selection['policy'], {'version': 'dt-r1-fixed-k-v1',
                    'market': 'trifecta', 'k': 2, 'tie_break': 'cars_ascending'})
                self.assertAlmostEqual(selection['raw_coverage'], .7)
                self.assertEqual(selection['selected_tickets'][0]['cars'], [1, 2, 3])
                self.assertEqual(result['confidence'], label)
                self.assertEqual(confidence['audit_n'], 80)
                self.assertFalse(saved['independent_source_attestation'])
                if cohort == 'retrospective':
                    self.assertIsNone(selection['prediction_at'])
                    self.assertIsNone(selection['decision_at'])
                else:
                    self.assertIn('COHORT_TRANSFER_UNVALIDATED', confidence['hold_reasons'])

    def test_fixed_exacta_selection_does_not_use_trifecta_policy(self):
        output = self.root / 'exacta.json'
        self.run_cli('select', '--forecast', self.put('f.json', forecast()),
                     '--fixed-k', '2', '--market', 'exacta', '--output', str(output))
        selection = json.loads(output.read_text())['selection']
        self.assertEqual(selection['market'], 'exacta')
        self.assertEqual([t['cars'] for t in selection['selected_tickets']], [[1, 2], [1, 3]])
        self.assertEqual(selection['ticket_count'], 2)

    def test_fixed_and_odds_modes_cannot_silently_ignore_options(self):
        f = forecast(cohort='prospective')
        base = ['select', '--forecast', self.put('f.json', f), '--fixed-k', '1',
                '--output', str(self.root / 'choice.json')]
        for option in [('--odds', self.put('odds.json', odds(f))),
                       ('--policy-config', self.put('config.json', {})),
                       ('--at', '2026-10-01T10:04:00Z')]:
            with self.subTest(option=option[0]), redirect_stderr(io.StringIO()):
                with self.assertRaises((SystemExit, ValueError)):
                    main(base + list(option))
        with self.assertRaisesRegex(ValueError, 'ODDS_DECISION_CLOCK_REQUIRED'):
            main(['select', '--forecast', str(self.root / 'f.json'),
                  '--output', str(self.root / 'choice.json')])
        with self.assertRaisesRegex(ValueError, 'MARKET_OPTION_REQUIRES_FIXED_K'):
            main(['select', '--forecast', str(self.root / 'f.json'), '--market', 'exacta',
                  '--at', '2026-10-01T10:04:00Z', '--output', str(self.root / 'choice.json')])
        self.assertFalse((self.root / 'choice.json').exists())

    def test_compare_uses_external_pin_file_sha_and_preserves_missing_rivals(self):
        from research.chatgpt_dt_r1.policy import fixed_selection
        f = forecast()
        f['selection'] = fixed_selection(f, 1)
        pins = {model: {'model_sha256': forecast(model_id=model)['model_sha256'],
                        'policy_sha256': f['selection']['policy_sha256']} for model in MODEL_IDS}
        pin_file = Path(self.put('pins.json', pins))
        expected_sha = sha256(pin_file.read_bytes()).hexdigest()
        output = self.root / 'comparison.json'
        args = ['compare', '--forecasts', self.put('forecasts.json', [f]),
            '--outcomes', self.put('outcomes.json', [{'race_id': 'r1', 'day': '2026-10-01',
                'top3': [1, 2, 3], 'field_size': 3, 'status': 'settled', 'incidents': ['DNF_tail']}]),
            '--registry', self.put('registry.json', [{'race_id': 'r1', 'day': '2026-10-01',
                'input_sha256': 'c' * 64, 'cohort': 'retrospective'}]),
            '--pins', str(pin_file), '--pins-sha256', expected_sha, '--output', str(output)]
        for model in MODEL_IDS:
            args.extend(['--model-id', model])
        self.run_cli(*args)
        saved = json.loads(output.read_text())
        self.assertEqual(saved['participant_manifest']['file_sha256'], expected_sha)
        self.assertEqual(saved['participant_manifest']['pins'], pins)
        self.assertFalse(saved['participant_manifest']['independently_authenticated'])
        self.assertEqual(saved['all_target']['eligible_n'], 1)
        self.assertEqual(saved['all_target']['models']['integrated']['missing_or_held_n'], 1)
        self.assertEqual(saved['common_cohort']['eligible_n'], 0)
        self.assertIsNone(saved['verdict']['winner'])
        self.assertFalse(saved['source_attested'])
        output.unlink()
        pin_file.write_text(json.dumps({**pins, 'integrated': dict(pins['integrated'], model_sha256='f' * 64)}))
        with self.assertRaisesRegex(ValueError, 'PIN_FILE_SHA256_MISMATCH'):
            main(args)
        self.assertFalse(output.exists())

    def test_compare_requires_external_sha_when_pin_file_is_requested(self):
        base = ['compare', '--forecasts', self.put('forecasts.json', []),
                '--outcomes', self.put('outcomes.json', []), '--registry', self.put('registry.json', []),
                '--output', str(self.root / 'comparison.json')]
        for model in MODEL_IDS:
            base.extend(['--model-id', model])
        for option in [('--pins', self.put('pins.json', {})), ('--pins-sha256', 'a' * 64)]:
            with self.subTest(option=option[0]):
                with self.assertRaisesRegex(ValueError, 'PIN_FILE_AND_EXTERNAL_SHA_REQUIRED'):
                    main(base + list(option))
        self.assertFalse((self.root / 'comparison.json').exists())

    def test_compare_strict_option_cannot_count_unbound_card_only_exports(self):
        args = ['compare', '--forecasts', self.put('forecasts.json', [forecast()]),
                '--outcomes', self.put('outcomes.json', [{'race_id': 'r1', 'day': '2026-10-01',
                    'status': 'settled', 'top3': [1, 2, 3], 'field_size': 3}]),
                '--registry', self.put('registry.json', [{'race_id': 'r1', 'day': '2026-10-01'}]),
                '--require-shared-evidence', '--output', str(self.root / 'strict.json')]
        for model in MODEL_IDS:
            args.extend(['--model-id', model])
        self.run_cli(*args)
        report = json.loads((self.root / 'strict.json').read_text())
        own = report['all_target']['models']['chatgpt-dt-r1']
        self.assertEqual(own['eligible_n'], 1)
        self.assertEqual(own['forecast_n'], 0)
        self.assertEqual(own['hold_reasons'], {'SHARED_EVIDENCE_BINDING_INCOMPLETE': 1})
        self.assertEqual(report['shared_evidence']['status'], 'ENFORCED')
        self.assertEqual(report['common_cohort']['eligible_n'], 0)

    def test_compare_rejects_null_or_duplicate_pin_manifests_even_with_matching_file_sha(self):
        from research.chatgpt_dt_r1.policy import fixed_selection
        pin = {'model_sha256': 'a' * 64, 'policy_sha256': fixed_selection(forecast(), 1)['policy_sha256']}
        pins = {model: pin for model in MODEL_IDS}
        duplicate = '{"integrated":' + json.dumps(pin) + ',' + json.dumps(pins)[1:]
        base = ['compare', '--forecasts', self.put('forecasts.json', []),
                '--outcomes', self.put('outcomes.json', []), '--registry', self.put('registry.json', [])]
        for model in MODEL_IDS:
            base.extend(['--model-id', model])
        path = self.root / 'pins.json'
        for raw, reason in [('null', 'EXACTLY_THREE_PARTICIPANT_PINS_REQUIRED'),
                            (duplicate, 'DUPLICATE_PIN_KEY')]:
            with self.subTest(reason=reason):
                path.write_text(raw)
                expected_sha = sha256(path.read_bytes()).hexdigest()
                output = self.root / (reason + '.json')
                with self.assertRaisesRegex(ValueError, reason), redirect_stdout(io.StringIO()):
                    main(base + ['--pins', str(path), '--pins-sha256', expected_sha, '--output', str(output)])
                self.assertFalse(output.exists())

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
        from research.chatgpt_dt_r1.policy import digest
        self.assertEqual(out.get('feature_schema_sha256'), digest(feature['feature_names']))

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
