"""Synthetic participant-ledger/runtime tests; no proof of live automation."""
import copy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from research.chatgpt_dt_r1.policy import digest, fixed_selection, select_tickets
from research.chatgpt_dt_r1.test_calibration_policy_comparison import forecast

try:
    runtime = importlib.import_module('research.chatgpt_dt_r1.runtime')
except ModuleNotFoundError:
    runtime = None


def receipt(payload):
    return {'verified': True, 'independent': True, 'verifier': 'SYNTHETIC_TEST_ONLY',
            'receipt_sha256': 'e' * 64, 'payload_sha256': digest(payload)}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime, 'participant runtime missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.when = '2026-10-01T10:05:00Z'
        self.f = forecast(cohort='prospective')
        self.f['feature_input_sha256'] = 'f' * 64
        self.s = fixed_selection(self.f, 1)
        self.ids = ['existing-integrated', 'codex-new', self.f['model_id']]
        self.pin = {'model_sha256': self.f['model_sha256'], 'policy_sha256': self.s['policy_sha256']}
        self.ledger = runtime.ResearchLedger.initialize(self.directory / 'ledger.sqlite',
                      participant_ids=self.ids, pins={self.f['model_id']: self.pin}, now=lambda: self.when)
        self.addCleanup(self.ledger.close)

    def binding(self):
        return {k: self.f[k] for k in ('race_id', 'day', 'input_sha256', 'cutoff_at', 'cohort')} | {'starters': [1, 2, 3]}

    def register(self):
        self.ledger.register_race(self.binding(), source_verifier=receipt)
        self.ledger.register_forecast(self.f, self.s, readback_verifier=receipt)

    def test_missing_state_stops_and_initialize_never_replaces_existing(self):
        with self.assertRaises(ValueError):
            runtime.ResearchLedger.open(self.directory / 'missing.sqlite')
        with self.assertRaises(ValueError):
            runtime.ResearchLedger.initialize(self.ledger.path, participant_ids=self.ids)
        self.assertEqual(len(self.ledger.participant_ids), 3)

    def test_immutable_roster_model_and_forecast_bindings_and_sql_triggers(self):
        self.register()
        changed = self.binding(); changed['starters'] = [1, 2, 4]
        with self.assertRaises(ValueError):
            self.ledger.register_race(changed, source_verifier=receipt)
        before = len(self.ledger.events())
        self.ledger.register_forecast(self.f, self.s, readback_verifier=receipt)
        self.assertEqual(len(self.ledger.events()), before)
        changed_forecast = dict(self.f, prediction_at='2026-10-01T10:01:00+00:00')
        with self.assertRaises(ValueError):
            self.ledger.register_forecast(changed_forecast, fixed_selection(changed_forecast, 1), readback_verifier=receipt)
        with self.assertRaises(ValueError):
            self.ledger.bind_participant(self.f['model_id'], {'model_sha256': '9' * 64, 'policy_sha256': self.s['policy_sha256']})
        with self.assertRaises(sqlite3.DatabaseError):
            self.ledger.connection.execute("UPDATE events SET kind='changed' WHERE seq=1")

    def test_prospective_margin_and_no_backdated_seal(self):
        self.ledger.register_race(self.binding(), source_verifier=receipt)
        self.when = '2026-10-01T10:16:00Z'
        with self.assertRaises(ValueError):
            self.ledger.register_forecast(self.f, self.s, readback_verifier=receipt)
        self.when = '2026-10-01T09:00:00Z'
        with self.assertRaises(ValueError):
            self.ledger.record_hold('r1', 'codex-new', 'missing')

    def test_clock_crossing_fifteen_minute_boundary_cannot_gain_verified_status(self):
        self.ledger.register_race(self.binding(), source_verifier=receipt)
        moments = iter(['2026-10-01T10:14:59Z', '2026-10-01T10:15:01Z', '2026-10-01T10:15:02Z'])
        self.ledger._clock = lambda: next(moments)
        with self.assertRaises(ValueError):
            self.ledger.register_forecast(self.f, self.s, readback_verifier=receipt)
        self.assertEqual(self.ledger.coverage()['verified_forecasts'], 0)

    def test_bare_true_is_not_an_independent_verifier_and_missing_models_remain(self):
        self.ledger.register_race(self.binding(), source_verifier=lambda _: True)
        with self.assertRaises(ValueError):
            self.ledger.register_forecast(self.f, self.s, readback_verifier=receipt)
        self.assertEqual(len(self.ledger.registry()), 1)
        self.assertEqual(self.ledger.coverage()['expected_forecasts'], 3)
        self.assertEqual(self.ledger.coverage()['verified_forecasts'], 0)

    def test_result_revisions_append_and_readback_failure_keeps_original(self):
        self.ledger.register_race(self.binding(), source_verifier=receipt)
        with self.assertRaises(ValueError):
            self.ledger.register_forecast(self.f, self.s, readback_verifier=lambda _: True)
        self.assertEqual(len(self.ledger.forecasts(include_unverified=True)), 1)
        self.assertEqual(len(self.ledger.forecasts()), 0)
        self.ledger.register_forecast(self.f, self.s, readback_verifier=receipt)
        self.assertEqual(len(self.ledger.forecasts(include_unverified=True)), 1)
        self.assertEqual(len(self.ledger.forecasts()), 1)
        self.when = '2026-10-01T11:00:00Z'
        outcome = {'race_id': 'r1', 'day': '2026-10-01', 'top3': [1, 2, 3], 'status': 'settled',
                   'result_at': '2026-10-01T10:40:00Z'}
        self.ledger.append_result(outcome, result_verifier=receipt)
        self.ledger.append_result(outcome, result_verifier=receipt)
        self.assertEqual(len(self.ledger.events('result')), 1)
        self.when = '2026-10-01T11:10:00Z'
        second = dict(outcome, top3=[1, 3, 2], result_at='2026-10-01T11:05:00Z')
        self.ledger.append_result(second, result_verifier=receipt)
        self.assertEqual(self.ledger.latest_results()[0]['top3'], [1, 3, 2])
        self.assertEqual(len(self.ledger.events('result')), 2)

    def test_encrypted_checkpoint_restores_all_rows_and_refuses_unpinned_or_tampered_shards(self):
        from race_ai import keirin_official_run_history as codec
        self.register()
        private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        secret = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        pin = sha256(private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        with patch.object(codec.storage, 'PINNED_OWNER_SPKI_SHA256', pin):
            for i in range(24):
                self.ledger.record_hold('r1', 'codex-new', 'SYNTHETIC_MISSING_EXPORT_' + str(i))
            check = self.ledger.checkpoint(self.directory / 'checkpoint', public, max_shard_bytes=8192)
            self.assertGreater(check['shard_count'], 1)
            restored = runtime.restore_checkpoint(self.directory / 'checkpoint', self.directory / 'restored.sqlite',
                        expected_manifest_sha256=check['manifest_sha256'], owner_private_pem=secret)
            self.addCleanup(restored.close)
            self.assertEqual(restored.events(), self.ledger.events())
            self.assertEqual(restored.coverage()['verified_forecasts'], 1)
            with self.assertRaises(ValueError):
                runtime.restore_checkpoint(self.directory / 'checkpoint', restored.path,
                    expected_manifest_sha256=check['manifest_sha256'], owner_private_pem=secret)
            manifest = json.loads(Path(check['manifest_path']).read_text())
            self.assertNotIn('trifectas', json.dumps(manifest))
            with self.assertRaises(ValueError):
                runtime.restore_checkpoint(self.directory / 'checkpoint', self.directory / 'other.sqlite',
                    expected_manifest_sha256='0' * 64, owner_private_pem=secret)
            shard = self.directory / 'checkpoint' / manifest['shards'][0]['file']
            shard.write_bytes(shard.read_bytes()[:-1] + b'x')
            with self.assertRaises(ValueError):
                runtime.restore_checkpoint(self.directory / 'checkpoint', self.directory / 'bad.sqlite',
                    expected_manifest_sha256=check['manifest_sha256'], owner_private_pem=secret)
            self.assertFalse((self.directory / 'bad.sqlite').exists())
            shard.unlink()
            with self.assertRaises(ValueError):
                runtime.restore_checkpoint(self.directory / 'checkpoint', self.directory / 'missing-shard.sqlite',
                    expected_manifest_sha256=check['manifest_sha256'], owner_private_pem=secret)
            self.assertFalse((self.directory / 'missing-shard.sqlite').exists())

    def test_shadow_cycle_uses_real_feature_forecast_pipeline_and_keeps_missing_rivals(self):
        from research.chatgpt_dt_r1.test_data_features import archive
        from research.chatgpt_dt_r1.data import load_archives
        from research.chatgpt_dt_r1.features import build_features
        from research.chatgpt_dt_r1.model import RankModel
        from research.chatgpt_dt_r1.pipeline import forecast_row
        source = self.directory / 'source.sqlite'
        pins = archive(source, [{'day': '20260901'}, {'day': '20260902'}])
        records, _ = load_archives([source], expected_sha256=pins)
        featured = build_features(records)
        model = RankModel.zero(featured[0]['feature_names'])
        f = forecast_row(model, featured[0]); s = fixed_selection(f, 1)
        ledger = runtime.ResearchLedger.initialize(self.directory / 'cycle.sqlite', participant_ids=self.ids,
                 pins={f['model_id']: {'model_sha256': f['model_sha256'], 'policy_sha256': s['policy_sha256']}}, now=lambda: self.when)
        self.addCleanup(ledger.close)
        report = runtime.run_shadow_cycle(ledger, records, model, source_verifier=receipt,
                         result_verifier=receipt, readback_verifier=receipt)
        self.assertEqual(report['coverage']['scheduled_races'], 2)
        self.assertEqual(report['coverage']['verified_forecasts'], 2)
        self.assertEqual(report['coverage']['missing_forecasts'], 4)
        self.assertIsNone(report['comparison']['verdict']['winner'])

    def test_candidate_run_is_due_once_and_adoption_never_changes_pins(self):
        self.ledger.schedule_candidate('candidate-1', '2026-10-01T10:00:00Z')
        calls = []
        def fit(*, study_directory):
            calls.append(study_directory)
            return {'model_sha256': '8' * 64, 'study_manifest_sha256': '7' * 64}
        result = self.ledger.run_due_candidates(fit, self.directory / 'studies')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'REVIEW_RECOMMENDATION')
        self.assertEqual(self.ledger.run_due_candidates(fit, self.directory / 'studies'), [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.ledger.participant_pins()[self.f['model_id']], self.pin)
        decision = runtime.candidate_adoption_check({}, {'min_races': 100, 'min_days': 10}, evidence_verifier=receipt)
        self.assertEqual(decision['status'], 'KEEP')
        self.assertFalse(decision['changes_active_model'])

    def test_future_review_requires_fixed_metric_class_coverage_and_independent_receipt(self):
        contract = {'min_races': 100, 'min_days': 10, 'frozen_at': '2026-10-01T00:00:00Z',
                    'expected_model_ids': self.ids, 'required_class_counts': {'A': 30, 'S': 30, 'L': 20},
                    'primary_metric': 'trifecta_hit_at_1'}
        evidence = {'cohort': 'prospective', 'independent_future': True, 'previously_examined': False,
                    'contract_sha256': digest(contract), 'period_start': '2026-10-02T00:00:00Z',
                    'period_end': '2026-11-02T00:00:00Z', 'common_race_n': 300, 'common_day_n': 20,
                    'same_inputs_and_policy': True, 'model_ids': self.ids, 'paired_primary_ci': [.01, .04],
                    'class_counts': {'A': 100, 'S': 100, 'L': 100}, 'primary_metric': 'trifecta_hit_at_1'}
        self.assertEqual(runtime.candidate_adoption_check(evidence, contract, evidence_verifier=receipt)['status'], 'REVIEW_READY')
        bad = dict(evidence, primary_metric='chosen_after_seeing_results')
        self.assertEqual(runtime.candidate_adoption_check(bad, contract, evidence_verifier=receipt)['status'], 'KEEP')
        self.assertEqual(runtime.candidate_adoption_check(evidence, contract, evidence_verifier=lambda _: True)['status'], 'KEEP')

    def test_empty_source_roster_stays_registered_as_a_hold(self):
        row = self.binding(); row['starters'] = []
        self.ledger.register_race(row, source_verifier=lambda _: True)
        self.assertEqual(self.ledger.coverage()['scheduled_races'], 1)
        self.assertEqual(self.ledger.coverage()['missing_forecasts'], 3)

    def test_unknown_calendar_cutoff_stays_registered_without_source_admission(self):
        binding = dict(self.binding(), cutoff_at=None, starters=[])
        calls = []
        result = self.ledger.register_race(binding, source_verifier=lambda value: calls.append(value))
        self.assertEqual(result['status'], 'HOLD')
        self.assertEqual(result['reason'], 'AUTHENTIC_CUTOFF_REQUIRED')
        self.assertEqual(self.ledger.registry(), [binding])
        self.assertEqual(calls, [])
        self.assertEqual(self.ledger.coverage()['missing_forecasts'], 3)
        self.assertEqual(self.ledger.events('source_verified'), [])
        with self.assertRaises(ValueError):
            self.ledger.register_forecast(self.f, self.s, readback_verifier=receipt)

    def context_fixture(self):
        from research.chatgpt_dt_r1.test_data_features import archive
        from research.chatgpt_dt_r1.data import load_archives
        from research.chatgpt_dt_r1.features import build_features
        from research.chatgpt_dt_r1.context import augment_features
        from research.chatgpt_dt_r1.venues import VenueStore
        from research.chatgpt_dt_r1.model import RankModel
        source = self.directory / 'context-source.sqlite'
        pins = archive(source, [{'day': '20260901'}, {'day': '20260902'}])
        rows, _ = load_archives([source], expected_sha256=pins)
        store = VenueStore.from_records([{'venue_code': rows[1]['venue_code'], 'name': 'Synthetic geometry',
                    'source_url': 'https://example.test/synthetic', 'source_sha256': 'b' * 64,
                    'retrieved_at': '2026-08-31T00:00:00Z', 'geometry_scope': 'dated', 'effective_from': '2026-08-01',
                    'circumference_m': 400.0, 'straight_m': 60.0, 'cant_deg': 30.0}])
        featured = augment_features(build_features(rows), venue_store=store, as_of=self.when)
        self.assertEqual(len(featured[1]['feature_names']), 224)
        model = RankModel.zero(featured[1]['feature_names'])
        model.fit_meta['context'] = {'venue_file_sha256': 'b' * 64, 'timing_file_sha256': None}
        from research.chatgpt_dt_r1.pipeline import forecast_row
        f = forecast_row(model, featured[1]); s = fixed_selection(f, 1)
        ledger = runtime.ResearchLedger.initialize(self.directory / 'context-ledger.sqlite', participant_ids=self.ids,
                 pins={f['model_id']: {'model_sha256': f['model_sha256'], 'policy_sha256': s['policy_sha256'],
                                      'feature_schema_sha256': digest(list(featured[1]['feature_names']))}}, now=lambda: self.when)
        self.addCleanup(ledger.close)
        return rows, store, model, ledger, featured[1]

    def test_runtime_connects_224_context_features_history_and_snapshot_verification(self):
        rows, store, model, ledger, target_features = self.context_fixture()
        seen = []
        def verify_source(payload):
            seen.append(payload)
            return receipt(payload)
        report = runtime.run_shadow_cycle(ledger, rows[1:], model, history_records=rows[:1], venue_store=store,
                    context_as_of=self.when, source_verifier=verify_source, result_verifier=receipt, readback_verifier=receipt)
        self.assertEqual(report['coverage']['scheduled_races'], 1)
        self.assertEqual(report['coverage']['verified_forecasts'], 1)
        original = ledger.forecasts()[0]
        self.assertEqual(original['feature_input_sha256'], target_features['feature_input_sha256'])
        self.assertEqual(original['feature_schema_sha256'], digest(list(target_features['feature_names'])))
        for key in ('dataset_snapshot_sha256', 'history_snapshot_sha256', 'context_snapshot_sha256', 'feature_input_sha256'):
            self.assertEqual(len(seen[0][key]), 64)
        count = len(ledger.events())
        self.when = '2026-10-01T12:05:00Z'
        runtime.run_shadow_cycle(ledger, rows[1:], model, history_records=rows[:1], venue_store=store,
                    source_verifier=verify_source, result_verifier=receipt, readback_verifier=receipt)
        self.assertEqual(len(ledger.events()), count)

    def test_required_context_missing_is_hold_and_future_or_duplicate_history_rejected(self):
        rows, store, model, ledger, _ = self.context_fixture()
        report = runtime.run_shadow_cycle(ledger, rows[1:], model, history_records=rows[:1],
                    source_verifier=receipt, result_verifier=receipt, readback_verifier=receipt)
        self.assertEqual(report['coverage']['verified_forecasts'], 0)
        self.assertIn('FEATURE_SCHEMA', ledger.events('hold')[0]['body']['reason'])
        with self.assertRaises(ValueError):
            runtime.run_shadow_cycle(ledger, rows[1:], model, history_records=rows[1:], venue_store=store,
                    source_verifier=receipt, result_verifier=receipt, readback_verifier=receipt)
        future = dict(rows[0], day='2026-09-03')
        with self.assertRaises(ValueError):
            runtime.run_shadow_cycle(ledger, rows[1:], model, history_records=[future], venue_store=store,
                    source_verifier=receipt, result_verifier=receipt, readback_verifier=receipt)
        with self.assertRaises(ValueError):
            runtime.run_shadow_cycle(ledger, rows[1:], model, history_records=rows[:1], venue_store=store,
                    context_as_of='2026-10-02T00:00:00Z', source_verifier=receipt, result_verifier=receipt, readback_verifier=receipt)

    def test_repeated_source_hold_preserves_binding_and_deduplicates_reason(self):
        rows, store, model, ledger, _ = self.context_fixture()
        args = {'history_records': rows[:1], 'venue_store': store, 'source_verifier': lambda _: True,
                'result_verifier': receipt, 'readback_verifier': receipt}
        runtime.run_shadow_cycle(ledger, rows[1:], model, **args)
        before = len(ledger.events())
        self.when = '2026-10-01T12:05:00Z'
        runtime.run_shadow_cycle(ledger, rows[1:], model, **args)
        self.assertEqual(len(ledger.events()), before)
        self.assertEqual(len(ledger.events('source_hold')), 1)
        args['source_verifier'] = receipt
        report = runtime.run_shadow_cycle(ledger, rows[1:], model, **args)
        self.assertEqual(report['coverage']['verified_forecasts'], 1)

    def test_context_after_prediction_cannot_be_registered_as_pre_race_input(self):
        binding = dict(self.binding(), context_as_of='2026-10-01T10:04:00Z')
        self.ledger.register_race(binding, source_verifier=receipt)
        with self.assertRaises(ValueError):
            self.ledger.register_forecast(self.f, self.s, readback_verifier=receipt)

    def test_future_history_result_is_rejected_before_features_are_built(self):
        rows, store, model, ledger, _ = self.context_fixture()
        rows[0]['available_at'] = '2026-09-01T00:00:00Z'
        rows[0]['result_at'] = '2026-10-01T11:00:00Z'
        with self.assertRaisesRegex(ValueError, 'HISTORY_RESULT_AFTER_CONTEXT_SNAPSHOT'):
            runtime.run_shadow_cycle(ledger, rows[1:], model, history_records=rows[:1], venue_store=store,
                    source_verifier=receipt, result_verifier=receipt, readback_verifier=receipt)
        with self.assertRaisesRegex(ValueError, 'HISTORY_RESULT_AFTER_CONTEXT_SNAPSHOT'):
            runtime.run_shadow_cycle(ledger, rows, model, venue_store=store,
                    source_verifier=receipt, result_verifier=receipt, readback_verifier=receipt)
        self.assertEqual(ledger.registry(), [])

    def test_rehashed_selection_cannot_add_invalid_cars_or_false_set_coverage(self):
        self.ledger.register_race(self.binding(), source_verifier=receipt)
        for change in ('cars', 'coverage', 'count'):
            selection = copy.deepcopy(self.s)
            if change == 'cars':
                selection['selected_tickets'] = [{'cars': [9, 9, 9], 'probability': .99}]
            elif change == 'coverage':
                selection['raw_coverage'] = .99
            else:
                selection['ticket_count'] = 12
            selection['selection_sha256'] = digest({k: v for k, v in selection.items() if k != 'selection_sha256'})
            with self.assertRaises(ValueError):
                self.ledger.register_forecast(self.f, selection, readback_verifier=receipt)
        self.assertEqual(self.ledger.coverage()['verified_forecasts'], 0)

    def test_positive_loss_difference_is_not_an_improvement_recommendation(self):
        contract = {'min_races': 100, 'min_days': 10, 'frozen_at': '2026-10-01T00:00:00Z',
                    'expected_model_ids': self.ids, 'required_class_counts': {'A': 30},
                    'primary_metric': 'joint_top3_log_loss'}
        evidence = {'cohort': 'prospective', 'independent_future': True, 'previously_examined': False,
                    'contract_sha256': digest(contract), 'period_start': '2026-10-02T00:00:00Z',
                    'period_end': '2026-11-02T00:00:00Z', 'common_race_n': 300, 'common_day_n': 20,
                    'same_inputs_and_policy': True, 'model_ids': self.ids, 'paired_primary_ci': [.01, .04],
                    'class_counts': {'A': 100}, 'primary_metric': 'joint_top3_log_loss'}
        self.assertEqual(runtime.candidate_adoption_check(evidence, contract, evidence_verifier=receipt)['status'], 'KEEP')
        evidence['paired_primary_ci'] = [-.04, -.01]
        self.assertEqual(runtime.candidate_adoption_check(evidence, contract, evidence_verifier=receipt)['status'], 'REVIEW_READY')

    def test_restore_failure_after_publication_removes_only_its_plaintext_inode(self):
        from race_ai import keirin_official_run_history as codec
        private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        secret = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        pin = sha256(private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        target_parent = self.directory / 'publication-race'
        target_parent.mkdir(mode=0o700)
        destination = target_parent / 'restored.sqlite'
        real_link = runtime.os.link
        def move_into_git_during_publication(source, target):
            (Path(target).parent / '.git').mkdir()
            return real_link(source, target)
        with patch.object(codec.storage, 'PINNED_OWNER_SPKI_SHA256', pin):
            saved = self.ledger.checkpoint(self.directory / 'restore-race-checkpoint', public)
            with patch.object(runtime.os, 'link', side_effect=move_into_git_during_publication):
                with self.assertRaises(ValueError):
                    runtime.restore_checkpoint(self.directory / 'restore-race-checkpoint', destination,
                        expected_manifest_sha256=saved['manifest_sha256'], owner_private_pem=secret)
        self.assertFalse(destination.exists())

    def policy_fixture(self):
        from research.chatgpt_dt_r1.test_data_features import archive
        from research.chatgpt_dt_r1.data import load_archives
        from research.chatgpt_dt_r1.features import build_features
        from research.chatgpt_dt_r1.model import RankModel
        from research.chatgpt_dt_r1.pipeline import forecast_row
        number = getattr(self, '_policy_fixture_number', 0) + 1
        self._policy_fixture_number = number
        source = self.directory / f'policy-source-{number}.sqlite'
        pins = archive(source, [{'day': '20261001', 'ranks': []}])
        rows, _ = load_archives([source], expected_sha256=pins)
        rows[0].update(cohort='prospective', cutoff_at='2026-10-01T10:30:00Z',
                       available_at='2026-10-01T09:00:00Z', source_attestation_sha256='1' * 64,
                       pre_cutoff_authenticated=True, result_status='PENDING', top3=None)
        features = build_features(rows)
        model = RankModel.zero(features[0]['feature_names'])
        model.fit_meta.update(created_at='2026-09-30T00:00:00Z', training_last_day='2026-09-29')
        f = forecast_row(model, features[0], prediction_at=self.when)
        policy = select_tickets(f, None, decision_at=self.when)
        ledger = runtime.ResearchLedger.initialize(self.directory / f'policy-ledger-{number}.sqlite',
                    participant_ids=self.ids, pins={f['model_id']: {'model_sha256': f['model_sha256'],
                    'policy_sha256': policy['policy_sha256'], 'feature_schema_sha256': digest(list(model.feature_names))}},
                    now=lambda: self.when)
        self.addCleanup(ledger.close)
        return rows, model, ledger, f

    def runtime_odds(self, f):
        return {'race_id': f['race_id'], 'market': 'trifecta', 'complete': True,
                'source': 'SYNTHETIC_TEST_ONLY', 'source_sha256': '2' * 64,
                'published_at': '2026-10-01T10:04:00Z', 'captured_at': self.when,
                'tickets': [{'cars': row['cars'], 'odds': 12.0 if i == 0 else 1.0}
                            for i, row in enumerate(f['trifectas'])]}

    def run_policy_cycle(self, ledger, rows, model, **kwargs):
        return runtime.run_shadow_cycle(ledger, rows, model, source_verifier=receipt,
                result_verifier=receipt, readback_verifier=receipt, policy_config={}, **kwargs)

    def test_authenticated_odds_select_one_and_retries_reuse_original_selection(self):
        rows, model, ledger, _ = self.policy_fixture()
        report = self.run_policy_cycle(ledger, rows, model, odds_provider=self.runtime_odds, odds_verifier=receipt)
        self.assertEqual(report['coverage']['verified_forecasts'], 1)
        original = ledger.forecasts()[0]
        selected = original['selection']
        self.assertEqual(selected['status'], 'SELECTED')
        self.assertEqual(selected['ticket_count'], 1)
        self.assertEqual(selected['cap'], 4)
        self.assertEqual(selected['confidence'], 'HOLD')
        self.assertGreater(selected['expected_net'], 0)
        count = len(ledger.events())
        self.when = '2026-10-01T12:00:00Z'
        def never_fetch_again(_):
            raise AssertionError('a retry must not fetch replacement odds')
        self.run_policy_cycle(ledger, rows, model, odds_provider=never_fetch_again, odds_verifier=receipt)
        self.assertEqual(ledger.forecasts()[0], original)
        self.assertEqual(len(ledger.events()), count)

    def test_missing_late_partial_and_unverified_odds_preserve_forecast_as_policy_hold(self):
        for case in ('missing', 'late', 'late_available', 'partial', 'bad_receipt', 'no_verifier'):
            with self.subTest(case=case):
                rows, model, ledger, f = self.policy_fixture()
                snapshot = self.runtime_odds(f)
                verifier = receipt
                if case == 'missing':
                    snapshot = None
                elif case == 'late':
                    snapshot['captured_at'] = '2026-10-01T10:31:00Z'
                elif case == 'late_available':
                    snapshot['available_at'] = '2026-10-01T10:31:00Z'
                elif case == 'partial':
                    snapshot['tickets'].pop()
                elif case == 'bad_receipt':
                    verifier = lambda payload: dict(receipt(payload), payload_sha256='0' * 64)
                elif case == 'no_verifier':
                    verifier = None
                report = self.run_policy_cycle(ledger, rows, model,
                            odds_snapshots={f['race_id']: snapshot}, odds_verifier=verifier)
                self.assertEqual(report['coverage']['verified_forecasts'], 1)
                original = ledger.forecasts()[0]
                self.assertEqual(original['status'], 'READY')
                self.assertEqual(original['selection']['status'], 'HOLD')
                self.assertEqual(original['selection']['selected_tickets'], [])
                self.assertTrue(original['selection']['hold_reasons'])

    def runtime_calibrator(self, f, *, cohort='prospective'):
        from research.chatgpt_dt_r1.calibration import fit_calibrator, audit_calibrator
        from research.chatgpt_dt_r1.test_calibration_policy_comparison import SPLITS
        selected = select_tickets(f, self.runtime_odds(f), decision_at=self.when)
        lineage = {key: selected[key] for key in ('model_id', 'model_sha256', 'policy_sha256')}
        def samples(month):
            values = []
            for i in range(120):
                day = f'2026-{month:02d}-{i % 20 + 1:02d}'
                row = copy.deepcopy(selected)
                row.update(race_id=f'SYNTHETIC-CAL-{month}-{i}', day=day, hit=1, cohort=cohort,
                           prediction_at=f'{day}T10:00:00Z', cutoff_at=f'{day}T10:30:00Z',
                           decision_at=f'{day}T10:05:00Z', result_at=f'{day}T11:00:00Z')
                if cohort == 'retrospective':
                    row.update(prediction_at=None, cutoff_at=None, decision_at=None, result_at=None)
                values.append(row)
            return values
        artifact = fit_calibrator(samples(8), split_manifest=SPLITS, lineage=lineage)
        return audit_calibrator(artifact, samples(9))

    def calibration_receipt(self, payload):
        return dict(receipt(payload), frozen_at='2026-10-01T09:00:00Z', audit_verified=True)

    def test_confidence_requires_exact_frozen_policy_audit_and_does_not_transfer_archive_to_live(self):
        for case in ('valid', 'archive', 'tamper', 'wrong_policy', 'late_freeze', 'unverified'):
            with self.subTest(case=case):
                rows, model, ledger, f = self.policy_fixture()
                artifact = self.runtime_calibrator(f, cohort='retrospective' if case == 'archive' else 'prospective')
                policy_sha = artifact['lineage']['policy_sha256']
                expected = artifact['artifact_sha256']
                verifier = self.calibration_receipt
                if case == 'tamper':
                    artifact['calibration_n'] += 1
                elif case == 'late_freeze':
                    verifier = lambda payload: dict(self.calibration_receipt(payload), frozen_at='2026-10-01T10:06:00Z')
                elif case == 'unverified':
                    verifier = lambda _: True
                supplied_key = '0' * 64 if case == 'wrong_policy' else policy_sha
                self.run_policy_cycle(ledger, rows, model, odds_provider=self.runtime_odds, odds_verifier=receipt,
                    calibrators={supplied_key: artifact}, calibrator_sha256={supplied_key: expected},
                    calibration_verifier=verifier)
                selected = ledger.forecasts()[0]['selection']
                self.assertEqual(selected['status'], 'SELECTED')
                self.assertEqual(selected['confidence'], 'HOT' if case == 'valid' else 'HOLD')
                assessment = selected['confidence_assessment']
                if case == 'valid':
                    self.assertEqual(assessment['audit_n'], 120)
                    self.assertEqual(assessment['ticket_count'], 1)
                    self.assertEqual(assessment['calibrator_sha256'], expected)
                if case == 'archive':
                    self.assertIn('COHORT_TRANSFER_UNVALIDATED', assessment['hold_reasons'])

    def test_rehashed_odds_subset_or_confidence_label_cannot_bypass_frozen_evidence(self):
        rows, model, ledger, f = self.policy_fixture()
        self.run_policy_cycle(ledger, rows, model, odds_provider=self.runtime_odds, odds_verifier=receipt)
        original = ledger.forecasts()[0]
        for change in ('odds', 'confidence'):
            selected = copy.deepcopy(original['selection'])
            if change == 'odds':
                selected['selected_tickets'][0]['odds'] = 100.0
                selected['expected_gross'] = 100 * 100 * selected['raw_coverage']
                selected['expected_net'] = selected['expected_gross'] - 100
            else:
                selected['confidence'] = 'HOT'
                selected['confidence_assessment']['label'] = 'HOT'
            selected['selection_sha256'] = digest({k: v for k, v in selected.items() if k != 'selection_sha256'})
            expected_error = ('FROZEN_ODDS_POLICY_SELECTION_MISMATCH' if change == 'odds'
                              else 'AUDITED_CONFIDENCE_BINDING_REQUIRED')
            with self.assertRaisesRegex(ValueError, expected_error):
                ledger.register_forecast({k: v for k, v in original.items() if k != 'selection'}, selected, readback_verifier=receipt)

    def test_prospective_history_requires_real_source_and_result_clocks(self):
        from research.chatgpt_dt_r1.test_data_features import archive
        from research.chatgpt_dt_r1.data import load_archives
        rows, model, ledger, _ = self.policy_fixture()
        source = self.directory / 'prospective-prior-results.sqlite'
        pins = archive(source, [{'day': '20260930'}])
        history, _ = load_archives([source], expected_sha256=pins)
        history[0]['available_at'] = '2026-09-30T09:00:00Z'
        with self.assertRaisesRegex(ValueError, 'HISTORY_RESULT_AVAILABILITY_REQUIRED'):
            self.run_policy_cycle(ledger, rows, model, history_records=history,
                                  odds_provider=self.runtime_odds, odds_verifier=receipt)
        history[0]['result_at'] = '2026-10-01T11:00:00Z'
        with self.assertRaisesRegex(ValueError, 'HISTORY_RESULT_AFTER_PREDICTION'):
            self.run_policy_cycle(ledger, rows, model, history_records=history,
                                  odds_provider=self.runtime_odds, odds_verifier=receipt)
        history[0]['result_at'] = '2026-09-30T11:00:00Z'
        report = self.run_policy_cycle(ledger, rows, model, history_records=history,
                                      odds_provider=self.runtime_odds, odds_verifier=receipt)
        self.assertEqual(report['coverage']['verified_forecasts'], 1)

    def test_shadow_cycle_keeps_calendar_race_without_authentic_cutoff(self):
        rows, model, ledger, _ = self.policy_fixture()
        rows[0]['cutoff_at'] = None
        rows[0]['published_cutoff_at'] = None
        report = self.run_policy_cycle(ledger, rows, model, odds_provider=self.runtime_odds, odds_verifier=receipt)
        self.assertEqual(report['coverage']['scheduled_races'], 1)
        self.assertEqual(report['coverage']['missing_forecasts'], 3)
        self.assertEqual(report['comparison']['registry']['scheduled_n'], 1)
        self.assertEqual(ledger.events('source_verified'), [])

    def test_external_odds_selection_cannot_be_sealed_before_its_decision(self):
        rows, model, ledger, f = self.policy_fixture()
        f['feature_schema_sha256'] = digest(list(model.feature_names))
        binding = {key: f[key] for key in ('race_id', 'day', 'input_sha256', 'cohort', 'cutoff_at')}
        binding['starters'] = [1, 2, 3]
        ledger.register_race(binding, source_verifier=receipt)
        snapshot = self.runtime_odds(f)
        snapshot['captured_at'] = '2026-10-01T10:06:00Z'
        selected = select_tickets(f, snapshot, decision_at='2026-10-01T10:06:00Z')
        selected['odds_evidence'] = {'snapshot': snapshot, 'receipt': receipt(runtime._odds_payload(f, selected, snapshot))}
        selected = runtime._selection_seal(selected)
        with self.assertRaisesRegex(ValueError, 'SELECTION_DECISION_AFTER_SEAL'):
            ledger.register_forecast(f, selected, readback_verifier=receipt)
        self.assertEqual(ledger.coverage()['verified_forecasts'], 0)

    def calendar_record(self, row):
        calendar = copy.deepcopy(row)
        calendar.update(riders=[], cutoff_at=None, published_cutoff_at=None, input_sha256='9' * 64,
                        pre_cutoff_authenticated=False, source_admission_status='HOLD')
        return calendar

    def test_calendar_admission_appends_real_card_then_forecasts_at_fresh_context_clock(self):
        rows, model, ledger, _ = self.policy_fixture()
        calendar = self.calendar_record(rows[0])
        self.run_policy_cycle(ledger, [calendar], model, odds_provider=self.runtime_odds, odds_verifier=receipt)
        first = copy.deepcopy(ledger.events('race')[0])
        self.assertEqual(ledger.coverage()['verified_forecasts'], 0)
        self.when = '2026-10-01T10:06:00Z'
        source_calls = []
        def admitted_source(binding):
            source_calls.append(binding)
            return receipt(binding)
        report = runtime.run_shadow_cycle(ledger, rows, model, source_verifier=admitted_source,
                    result_verifier=receipt, readback_verifier=receipt, policy_config={},
                    odds_provider=self.runtime_odds, odds_verifier=receipt)
        self.assertEqual(report['coverage']['verified_forecasts'], 1)
        self.assertEqual(ledger.events('race')[0], first)
        self.assertEqual(len(ledger.events('race_admission')), 1)
        self.assertEqual(ledger.registry()[0]['starters'], [1, 2, 3])
        self.assertEqual(ledger.registry()[0]['input_sha256'], rows[0]['input_sha256'])
        self.assertEqual(ledger.registry()[0]['context_as_of'], '2026-10-01T10:06:00+00:00')
        self.assertNotEqual(ledger.registry()[0]['context_as_of'], first['body']['context_as_of'])
        self.assertEqual(len(source_calls), 1)
        count = len(ledger.events())
        self.when = '2026-10-01T10:07:00Z'
        self.run_policy_cycle(ledger, rows, model, odds_provider=self.runtime_odds, odds_verifier=receipt)
        self.assertEqual(len(ledger.events()), count)

    def test_calendar_only_official_result_scores_missing_predictions_without_invented_roster(self):
        rows, model, ledger, _ = self.policy_fixture()
        calendar = self.calendar_record(rows[0])
        self.run_policy_cycle(ledger, [calendar], model, odds_provider=self.runtime_odds, odds_verifier=receipt)
        original = copy.deepcopy(ledger.registry()[0])
        self.when = '2026-10-01T11:00:00Z'
        calendar.update(top3=[1, 2, 3], result_status='SETTLED', result_at='2026-10-01T10:40:00Z')
        seen = []
        def official_result(outcome):
            seen.append(outcome)
            return dict(receipt(outcome), authority='official', source_sha256='3' * 64)
        unverified = runtime.run_shadow_cycle(ledger, [calendar], model, source_verifier=receipt,
                    result_verifier=receipt, readback_verifier=receipt, policy_config={},
                    odds_provider=self.runtime_odds, odds_verifier=receipt)
        self.assertEqual(unverified['comparison']['all_target']['eligible_n'], 0)
        self.assertEqual(ledger.latest_results(), [])
        report = runtime.run_shadow_cycle(ledger, [calendar], model, source_verifier=receipt,
                    result_verifier=official_result, readback_verifier=receipt, policy_config={},
                    odds_provider=self.runtime_odds, odds_verifier=receipt)
        self.assertEqual(ledger.registry()[0], original)
        self.assertEqual(ledger.registry()[0]['starters'], [])
        self.assertEqual(ledger.events('race_admission'), [])
        self.assertEqual(report['comparison']['all_target']['eligible_n'], 1)
        for member in self.ids:
            result = report['comparison']['all_target']['models'][member]
            self.assertEqual(result['forecast_n'], 0)
            self.assertEqual(result['trifecta']['hit_at']['1']['rate'], 0)
            self.assertEqual(result['hold_reasons']['MISSING_FORECAST'], 1)
        self.assertTrue(ledger.latest_results()[0]['input_roster_unknown'])
        self.assertIsNone(ledger.latest_results()[0]['result_roster'])
        self.assertIsNone(ledger.latest_results()[0]['field_size'])
        self.assertTrue(seen[0]['input_roster_unknown'])

    def test_calendar_admission_cannot_replace_any_admitted_forecast_original(self):
        self.register()
        original = copy.deepcopy(self.ledger.events('forecast')[0])
        registered = copy.deepcopy(self.ledger.registry())
        changed = dict(self.binding(), input_sha256='8' * 64)
        attempted = self.ledger.admit_calendar('r1', changed, source_verifier=receipt)
        self.assertEqual(attempted['status'], 'HOLD')
        self.assertEqual(self.ledger.registry(), registered)
        self.assertEqual(self.ledger.events('forecast')[0], original)
        self.assertEqual(self.ledger.events('race_admission'), [])

    def test_calendar_admission_rejects_identity_changes_unverified_or_late_cards(self):
        calendar = dict(self.binding(), cutoff_at=None, starters=[])
        self.ledger.register_race(calendar, source_verifier=receipt)
        for changed in (dict(self.binding(), race_id='different-race'), dict(self.binding(), day='2026-10-02'),
                        dict(self.binding(), cohort='retrospective')):
            self.assertEqual(self.ledger.admit_calendar('r1', changed, source_verifier=receipt)['status'], 'HOLD')
        self.assertEqual(self.ledger.admit_calendar('r1', self.binding(), source_verifier=lambda _: True)['status'], 'HOLD')
        self.when = '2026-10-01T10:14:59Z'
        def crosses_margin(binding):
            self.when = '2026-10-01T10:15:01Z'
            return receipt(binding)
        self.assertEqual(self.ledger.admit_calendar('r1', self.binding(), source_verifier=crosses_margin)['status'], 'HOLD')
        self.when = '2026-10-01T10:16:00Z'
        self.assertEqual(self.ledger.admit_calendar('r1', self.binding(), source_verifier=receipt)['status'], 'HOLD')
        self.assertEqual(self.ledger.events('race_admission'), [])
        self.assertEqual(self.ledger.registry(), [calendar])

    def test_late_card_keeps_calendar_hold_but_independent_official_result_still_settles(self):
        rows, model, ledger, _ = self.policy_fixture()
        self.run_policy_cycle(ledger, [self.calendar_record(rows[0])], model,
                              odds_provider=self.runtime_odds, odds_verifier=receipt)
        calendar = copy.deepcopy(ledger.registry()[0])
        self.when = '2026-10-01T11:00:00Z'
        rows[0].update(top3=[1, 2, 3], result_status='SETTLED', result_at='2026-10-01T10:40:00Z',
                       result_roster=[1, 2, 3], result_field_size=3)
        source_calls = []
        def no_late_source_admission(binding):
            source_calls.append(binding)
            return receipt(binding)
        report = runtime.run_shadow_cycle(ledger, rows, model, source_verifier=no_late_source_admission,
                    result_verifier=lambda outcome: dict(receipt(outcome), authority='official', source_sha256='3' * 64),
                    readback_verifier=receipt, policy_config={}, odds_provider=self.runtime_odds, odds_verifier=receipt)
        self.assertEqual(report['comparison']['all_target']['eligible_n'], 1)
        self.assertEqual(report['coverage']['verified_forecasts'], 0)
        self.assertEqual(ledger.registry(), [calendar])
        self.assertEqual(ledger.events('race_admission'), [])
        self.assertEqual(source_calls, [])
        self.assertEqual(ledger.latest_results()[0]['result_roster'], [1, 2, 3])
        self.assertEqual(ledger.latest_results()[0]['field_size'], 3)
        self.assertTrue(ledger.latest_results()[0]['input_roster_unknown'])


if __name__ == '__main__':
    unittest.main()
