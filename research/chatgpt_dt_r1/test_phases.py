import unittest
from research.chatgpt_dt_r1.phases import fit_phase_bundle, forecast_phase_paths
from research.chatgpt_dt_r1.test_model import fixture


class PhaseTests(unittest.TestCase):
    def test_phase_augmentation_must_not_launder_changed_feature_binding(self):
        from research.chatgpt_dt_r1.features import _bind_feature_input
        from research.chatgpt_dt_r1.phases import _state_row
        row = fixture()
        row.update(feature_version='synthetic-bound-v1', history_evidence={},
                   feature_status='READY', feature_scope='SYNTHETIC_TEST_ONLY')
        row = _bind_feature_input(row)
        row['features'][0, 0] += 1
        with self.assertRaisesRegex(ValueError, 'FEATURE_INPUT_HASH_MISMATCH'):
            _state_row(row, None, 'sampled_predictive_state')
        with self.assertRaisesRegex(ValueError, 'FEATURE_INPUT_HASH_MISMATCH'):
            fit_phase_bundle([row], [], train_before='2026-02-01', available_by='2026-02-01T00:00:00Z')

    def test_prospective_phase_api_obeys_source_and_cutoff_gates(self):
        from research.chatgpt_dt_r1.model import digest
        bundle = fit_phase_bundle([fixture()], [], train_before='2026-02-01', available_by='2026-02-01T00:00:00Z')
        bundle['created_at'] = '2026-02-01T00:00:00Z'
        bundle['artifact_sha256'] = digest({k: v for k, v in bundle.items() if k != 'artifact_sha256'})
        target = fixture(2, day='2026-03-01')
        target.update(cohort='prospective', available_at='2026-03-01T10:05:00Z',
                      cutoff_at='2026-03-01T10:30:00Z', source_attestation_sha256='a' * 64)
        with self.assertRaisesRegex(ValueError, 'SOURCE_AFTER_PREDICTION'):
            forecast_phase_paths(bundle, target, prediction_at='2026-03-01T10:00:00Z')
        target['available_at'] = '2026-03-01T09:00:00Z'
        target['cutoff_at'] = '2026-03-01T10:10:00Z'
        with self.assertRaisesRegex(ValueError, 'PRE_CUTOFF_15_MINUTES_REQUIRED'):
            forecast_phase_paths(bundle, target, prediction_at='2026-03-01T10:00:00Z')

    def test_no_labels_means_hold_not_invented_flow(self):
        bundle = fit_phase_bundle([fixture()], [], train_before='2026-02-01', available_by='2026-02-01T00:00:00Z')
        prediction = forecast_phase_paths(bundle, fixture(2, day='2026-03-01'))
        self.assertEqual(prediction['status'], 'HOLD')
        self.assertEqual(prediction['paths'], [])

    def test_ai_phase_labels_do_not_train_measured_phase_model(self):
        label = {'race_id': 'synthetic-0', 'phase': 'INITIAL', 'order': [1, 2, 3, 4, 5], 'complete': True,
                 'receipt': 'synthetic', 'provenance': {'kind': 'ai_estimate', 'source_url': 'urn:synthetic:phase',
                  'source_sha256': 'a' * 64, 'retrieved_at': '2026-01-02T00:00:00Z', 'available_at': '2026-01-02T00:00:00Z'}}
        bundle = fit_phase_bundle([fixture()], [label], train_before='2026-02-01', available_by='2026-02-01T00:00:00Z')
        self.assertEqual(bundle['models'], {})
        self.assertEqual(bundle['excluded']['unreviewed_source'], 1)

    def test_future_features_cannot_be_training_phase_rows(self):
        with self.assertRaisesRegex(ValueError, 'PHASE_TRAINING_DATE'):
            fit_phase_bundle([fixture(day='2026-03-01')], [], train_before='2026-02-01', available_by='2026-02-01T00:00:00Z')

    def test_trained_transition_sampler_uses_no_target_outcome(self):
        from research.chatgpt_dt_r1.phases import PHASES
        import copy
        rows = [fixture(i, n=3) for i in range(30)]
        labels = []
        for row in rows:
            for phase in PHASES:
                labels.append({'race_id': row['race_id'], 'phase': phase, 'order': row['finish'], 'complete': True,
                    'receipt': 'synthetic-only', 'provenance': {'kind': 'reviewed_video', 'source_url': 'urn:synthetic:phase',
                    'source_sha256': 'a' * 64, 'retrieved_at': '2026-01-02T00:00:00Z',
                    'reviewer_id': 'synthetic-reviewer', 'reviewed_at': '2026-01-02T01:00:00Z',
                    'available_at': '2026-01-02T01:00:00Z'}})
        bundle = fit_phase_bundle(rows, labels, train_before='2026-02-01', available_by='2026-02-01T00:00:00Z', max_iter=80)
        target = fixture(50, n=3, day='2026-03-01')
        prediction = forecast_phase_paths(bundle, target, samples=10, seed=7)
        changed = copy.deepcopy(target); changed['finish'].reverse(); changed['top3'] = changed['finish'][:3]
        self.assertEqual(prediction, forecast_phase_paths(bundle, changed, samples=10, seed=7))
        self.assertEqual(prediction['status'], 'SAMPLED_UNVALIDATED')
        for matrix in prediction['phase_marginals'].values():
            self.assertTrue(all(abs(sum(r['position_probabilities']) - 1) < 1e-10 for r in matrix))


if __name__ == '__main__':
    unittest.main()
