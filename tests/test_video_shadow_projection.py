"""Saved controlled fixtures only: zero real videos or field accuracy evidence."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import unittest
from unittest.mock import patch
import zipfile

from race_ai import boat_video_learning as video
from race_ai import frozen_day_cycle as frozen
from race_ai import observed_weight_learning as existing
from race_ai import private_cycle_projection as projection
from race_ai import private_saved_comparison as comparison
from race_ai.boat_observed_pairwise_models import MODEL_IDS
from tests.test_boat_video_learning import controlled_inputs, NOW
from tests.test_frozen_day_cycle import observation
from tests.test_observed_p1_connection import archive
from tests.test_private_cycle_projection import seal
from tests.test_video_existing_hooks import saved_training, target_bundle, target_video


def member(raw, receipt, name):
    """Pin the exact saved member bytes, without inventing authentication."""
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        body = bundle.read(name)
    return dict(artifact_id=receipt['id'], member_name=name,
        member_sha256=hashlib.sha256(body).hexdigest(), document=json.loads(body))


class SavedVideoProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai.boat_ab_shadow import build_pair
        from race_ai.boat_live_feature_shadow import build_live_feature_shadow
        rows, observations, contexts, verifier = controlled_inputs()
        training = video.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        cls.training_raw, cls.training_receipt = saved_training(training, dict(id=700,
            name='race-existing-cycle-99', created_at=(NOW+timedelta(seconds=2)).isoformat(),
            expired=False, workflow_run=dict(id=99, head_repository_id=1416489937)))
        # The archive getter checks the actual ZIP digest before use. The
        # callback below is a controlled independent reader, never real video.
        context = existing.context_from_result_archive(cls.training_raw, cls.training_receipt)
        base, extra, bundle = target_bundle()
        envelope, callback = target_video(next(iter(contexts.values())), bundle['snapshot'])
        cls.video_verifier = staticmethod(callback)
        shadows = existing.make_shadows(bundle['snapshot'], bundle['suite'], context,
            video_context=envelope, video_receipt_verifier=callback)
        document = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
            paired_forecasts=[build_pair(base, bundle['snapshot']['as_of'])],
            additional_official_feature_shadows=[build_live_feature_shadow(base, extra, bundle['snapshot']['as_of'])],
            observed_pairwise_p1_bundles=[bundle], learned_pairwise_shadows=shadows)
        cls.forecast_raw, cls.forecast_receipt = archive(document, saved=(NOW+timedelta(minutes=11)).isoformat())
        cls.document, cls.baselines = frozen.read_p1(cls.forecast_raw, cls.forecast_receipt)

    def setUp(self):
        self.state = dict(schema='RACE_AI_PRIVATE_ARTIFACT_READBACK_V1', day_jst='2030-04-01',
            rows=deepcopy(self.baselines), observations=[], receipts=[deepcopy(self.forecast_receipt)],
            complete=False, original_documents=[member(self.forecast_raw, self.forecast_receipt, 'national.json')])
        self.add_training()
        native = self.document['learned_pairwise_shadows'][0]
        base_native = self.document['observed_pairwise_p1_bundles'][0]['suite']['models'][native['model_id']]
        self.pins = dict(comparison_id='controlled-video-version', sport='boat', stage='P1',
            starts_at='2030-04-01T08:05:00Z', ends_at='2030-04-01T09:00:00Z',
            baseline=dict(model_id=native['model_id'], model_version=base_native['model_version']),
            learned=dict(model_id=native['model_id'], model_version=native['model_version'],
                         training_sha256=native['training_sha256']))
        self.schedule = [dict(race_id=self.baselines[0]['race_id'], sport='boat',
                              cutoff_at=self.baselines[0]['cutoff_at'], trifecta_offered=True)]

    def add_training(self):
        self.state['receipts'].append(deepcopy(self.training_receipt))
        self.state['original_documents'].append(member(self.training_raw, self.training_receipt,
                                                       'trained_observed_models.json'))

    def view(self):
        # Exercise the actual strict saved-JSON entry point, after creation has
        # ended, with all inference/training/network/write paths forbidden.
        saved = json.dumps(seal(self.state)).encode()
        with ExitStack() as guards:
            for target in ('race_ai.observed_weight_learning.make_shadows',
                           'race_ai.observed_weight_learning.fit_from_verified',
                           'race_ai.observed_weight_learning.read_shadow_rows',
                           'race_ai.boat_video_learning.make_video_shadows',
                           'race_ai.boat_video_learning.fit_with_video',
                           'race_ai.boat_observed_pairwise_models.predict_pair',
                           'urllib.request.urlopen', 'pathlib.Path.write_text', 'pathlib.Path.write_bytes'):
                guards.enter_context(patch(target, side_effect=AssertionError('saved viewing must be pure')))
            return projection.project_state(projection.read_state_json(saved), dataset_status='SYNTHETIC_ONLY')

    def predictions(self, view):
        record = view['records'][0]
        return [record['prediction']] + record['comparison_predictions']

    def evaluate(self):
        return comparison.evaluate_saved_comparison(seal(self.state), schedule=self.schedule,
            comparison=self.pins, evaluated_at='2030-04-01T08:45:00Z', dataset_status='SYNTHETIC_ONLY')

    def store_forecast(self, document):
        raw, receipt = archive(document, saved=self.forecast_receipt['created_at'])
        _, self.state['rows'] = frozen.read_p1(raw, receipt)
        self.state['receipts'][0] = receipt
        self.state['original_documents'][0] = member(raw, receipt, 'national.json')

    def test_saved_video_originals_add_two_versions_and_preserve_five_baselines(self):
        before = deepcopy(seal(self.state))
        variants = self.predictions(self.view())
        self.assertEqual(len(self.baselines), 5)
        self.assertEqual(len(variants), 7)
        self.assertEqual([p['prediction_sha256'] for p in variants[:5]],
                         [row['model_sha256'] for row in self.baselines])
        learned = [p for p in variants if p.get('variant') == 'LEARNED_VIDEO_EXPERIMENTAL']
        self.assertEqual({p['model_id'] for p in learned}, set(MODEL_IDS))
        for actual, native in zip(learned, self.document['learned_pairwise_shadows']):
            self.assertEqual(actual['model_version'], '0.3.0-VIDEO-EXPERIMENTAL')
            self.assertEqual(actual['prediction_sha256'], native['prediction_sha256'])
            self.assertEqual(actual['training_sha256'], native['training_sha256'])
            self.assertEqual(actual['ordered_top8'], native['ordered_top8'])
            self.assertEqual(actual['ordered_candidates'], [c['combination'] for c in native['candidates']])
            self.assertEqual(actual['video_context_sha256'], native['video_context_sha256'])
            self.assertEqual(actual['raw_report_validation_status'], 'UNVALIDATED')
            for flag in ('calibrated', 'production_eligible', 'independent_human_heldout_verified',
                         'video_context_receipt_verified', 'external_receipt_verified'):
                self.assertIs(actual[flag], False, flag)
            for reason in ('VIDEO_CONTEXT_RECEIPT_NOT_INDEPENDENTLY_VERIFIED',
                           'VIDEO_FIELD_VALIDATION_NOT_PROVEN', 'TRAINING_RECEIPT_NOT_INDEPENDENTLY_VERIFIED'):
                self.assertIn(reason, actual['missing_reasons'])
        self.assertEqual(self.state, before)

    def test_existing_saved_shadow_rows_keep_native_version_without_replay_or_duplicates(self):
        self.state['learning_shadows'] = existing.read_shadow_rows(self.document, self.forecast_receipt,
            self.baselines, video_receipt_verifier=self.video_verifier)
        predictions = self.predictions(self.view())
        self.assertEqual(len(predictions), 7)
        learned = [p for p in predictions if p.get('variant') == 'LEARNED_VIDEO_EXPERIMENTAL']
        self.assertEqual(len(learned), 2)
        self.assertTrue(all(p.get('raw_report_validation_status') == 'UNVALIDATED' for p in learned))
        self.assertTrue(all(p['model_version'] == '0.3.0-VIDEO-EXPERIMENTAL' for p in learned))
        self.state['learning_shadows'][0]['model_version'] = '0.1.0-UNTRAINED'
        with self.assertRaisesRegex(ValueError, 'metadata conflict'):
            self.view()

    def test_video_rows_already_in_saved_rows_do_not_get_added_twice(self):
        self.state['rows'] += existing.read_shadow_rows(self.document, self.forecast_receipt,
            self.baselines, video_receipt_verifier=self.video_verifier)
        self.assertEqual(len(self.predictions(self.view())), 7)

    def test_new_original_never_borrows_missing_metadata_from_its_baseline(self):
        for row in self.state['rows']:
            if row['model_id'] in MODEL_IDS:
                row.update(generated_at=row['as_of'], source_sha256='f'*64, odds_independent=True)
        learned = [p for p in self.predictions(self.view()) if p.get('variant') == 'LEARNED_VIDEO_EXPERIMENTAL']
        self.assertEqual(len(learned), 2)
        for prediction in learned:
            self.assertIsNone(prediction['generated_at'])
            self.assertIsNone(prediction['source_sha256'])
            self.assertIsNone(prediction['odds_independent'])

    def test_video_version_is_learned_research_with_separate_saved_training(self):
        report = self.evaluate()
        learned = report['races'][0]['learned']
        self.assertEqual(learned['state'], 'SAVED_ORIGINAL')
        self.assertEqual(learned['training_state'], 'SEPARATE_SAVED_TRAINING_CONSISTENT')
        self.assertEqual(learned['prediction']['variant'], 'LEARNED_VIDEO_EXPERIMENTAL')
        self.assertEqual(learned['prediction']['raw_report_validation_status'], 'UNVALIDATED')
        self.assertFalse(learned['prediction']['video_context_receipt_verified'])
        self.assertTrue(report['races'][0]['same_conditions'])
        self.assertFalse(report['accuracy_improvement_proven'])
        self.pins['baseline']['model_version'] = self.pins['learned']['model_version']
        self.assertEqual(self.evaluate()['races'][0]['baseline']['state'], 'NO_SAVED_PINNED_ORIGINAL')

    def test_saved_normal_result_allows_only_a_descriptive_controlled_pair(self):
        event = observation(self.baselines[0])
        event['captured_at'] = '2030-04-01T08:31:00Z'
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as bundle:
            bundle.writestr('official-result-observations.json', json.dumps([event]))
        raw = out.getvalue()
        receipt = dict(id=701, name='race-existing-cycle-99', expired=False,
            created_at='2030-04-01T08:40:00Z', digest='sha256:'+hashlib.sha256(raw).hexdigest(),
            workflow_run=dict(id=99, head_repository_id=1416489937))
        self.state['observations'] = [event]
        self.state['receipts'].append(receipt)
        self.state['original_documents'].append(member(raw, receipt, 'official-result-observations.json'))
        report = self.evaluate()
        self.assertEqual(report['denominator']['normal_final_eligible'], 1)
        self.assertEqual(report['paired']['races'], 1)
        self.assertIsInstance(report['races'][0]['learned']['hit'], bool)
        self.assertIsNone(report['official_hit_at_8_all'])
        self.assertFalse(report['accuracy_improvement_proven'])

    def test_saved_json_cannot_self_attest_video_receipts_or_field_validation(self):
        document = deepcopy(self.document)
        for native in document['learned_pairwise_shadows']:
            native.update(authenticated=True, video_context_receipt_verified=True)
            existing.seal(native, 'prediction_sha256')
        self.store_forecast(document)
        self.state.update(independent_receipts_verified=True, accuracy_improvement_proven=True)
        learned = [p for p in self.predictions(self.view()) if p.get('variant') == 'LEARNED_VIDEO_EXPERIMENTAL']
        self.assertEqual(len(learned), 2)
        self.assertTrue(all(p['video_context_receipt_verified'] is False for p in learned))
        for field, value in (('calibrated', True), ('production_eligible', True),
                             ('raw_report_validation_status', 'VALIDATED')):
            bad = deepcopy(document)
            native = bad['learned_pairwise_shadows'][0]
            native[field] = value
            existing.seal(native, 'prediction_sha256')
            self.store_forecast(bad)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'video research flags'):
                self.view()

    def test_video_comparison_pins_exact_version_and_training_sha(self):
        for field, value in (('model_version', '0.2.0-LEARNED'), ('training_sha256', 'f'*64)):
            with self.subTest(field=field):
                original = self.pins['learned'][field]
                self.pins['learned'][field] = value
                self.assertEqual(self.evaluate()['races'][0]['learned']['state'], 'NO_SAVED_PINNED_ORIGINAL')
                self.pins['learned'][field] = original

    def test_embedded_video_training_cannot_replace_missing_or_foreign_separate_original(self):
        for change in ('missing', 'foreign', 'later', 'invalid_training'):
            state = deepcopy(self.state)
            if change == 'missing':
                self.state['original_documents'] = self.state['original_documents'][:1]
            elif change == 'foreign':
                self.state['receipts'][1]['workflow_run']['head_repository_id'] = 1
            elif change == 'later':
                self.state['receipts'][1]['created_at'] = self.document['learned_pairwise_shadows'][0]['as_of']
            else:
                training = self.state['original_documents'][1]['document']
                training['models'][MODEL_IDS[0]]['video_weights'][0] = 5.
                existing.seal(training, 'training_sha256')
            with self.subTest(change=change):
                report = self.evaluate()
                self.assertEqual(report['races'][0]['learned']['state'], 'TRAINING_UNVERIFIED')
                self.assertEqual(report['races'][0]['learned']['training_state'], 'UNVERIFIED')
                self.assertTrue(any(d['reason'] == 'LEARNED_SEPARATE_TRAINING_OR_RECEIPT_UNVERIFIED'
                    for d in report['unresolved_learned_dependencies']))
            self.state = state

    def test_resealed_matching_training_must_satisfy_experimental_parameter_constraints(self):
        training = deepcopy(self.state['original_documents'][1]['document'])
        training['models'][MODEL_IDS[0]]['video_weights'][0] = 5.
        existing.seal(training, 'training_sha256')
        training_raw, receipt = saved_training(training, self.training_receipt)
        document = deepcopy(self.document)
        for native in document['learned_pairwise_shadows']:
            native.update(training=deepcopy(training), training_receipt=deepcopy(receipt),
                          training_sha256=training['training_sha256'])
            existing.seal(native, 'prediction_sha256')
        self.store_forecast(document)
        self.state['receipts'][1] = receipt
        self.state['original_documents'][1] = member(training_raw, receipt, 'trained_observed_models.json')
        self.pins['learned']['training_sha256'] = training['training_sha256']
        report = self.evaluate()
        self.assertEqual(report['races'][0]['learned']['state'], 'TRAINING_UNVERIFIED')
        self.assertEqual(report['races'][0]['learned']['training_state'], 'UNVERIFIED')


if __name__ == '__main__':
    unittest.main()
