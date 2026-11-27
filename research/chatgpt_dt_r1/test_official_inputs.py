"""Synthetic official-source normalization; no live admission or forecast claim."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from race_ai import keirin_learned_official_inputs as native
from research.chatgpt_dt_r1.data import input_digest
from research.chatgpt_dt_r1.features import FEATURE_INDEX
from research.chatgpt_dt_r1.model import _verify_feature_binding
from research.chatgpt_dt_r1.policy import clock, digest
from tests.test_keirin_learned_official_inputs import _original


class OfficialInputTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module('research.chatgpt_dt_r1.official_inputs')
        self.payload, self.original = _original()
        self.at = '2030-01-15T02:01:00+00:00'
        self.calls = []

    def verifier(self, packet):
        # The fixture is deliberately synthetic. A real callback must rerun
        # the existing independently authenticated archive admission.
        self.calls.append(deepcopy(packet))
        bound = digest(packet)
        return dict(verified=True, independent=True, verifier='synthetic-existing-admission',
                    payload_sha256=bound, receipt_sha256=digest({'fixture_payload': bound}),
                    verified_at=self.at)

    def project(self, **kwargs):
        return self.api.project(self.payload, self.original, prediction_at=self.at,
                                source_verifier=self.verifier, **kwargs)

    def prepare(self, **kwargs):
        return self.api.prepare(self.payload, self.original, prediction_at=self.at,
                                source_verifier=self.verifier, **kwargs)

    def history(self, target, *, different_person=False):
        row = deepcopy(target)
        row.update(race_id='203001149801', day='2030-01-14', cohort='retrospective',
                   available_at='2030-01-14T02:00:00+00:00',
                   source_available_at='2030-01-14T02:00:00+00:00',
                   source_verified_at='2030-01-14T02:01:00+00:00',
                   cutoff_at='2030-01-14T03:47:00+00:00',
                   published_cutoff_at='2030-01-14T03:47:00+00:00',
                   result_at='2030-01-14T04:00:00+00:00',
                   result_source_observed_at='2030-01-14T04:00:00+00:00',
                   result_source_sha256='b' * 64, result_admission_status='ADMITTED',
                   official_result_authenticated=True, result_status='PARTIAL_VALID_TOP3',
                   top3=[1, 2, 3], finish=None,
                   result_rows=[dict(car=i, rank=i, absence=False, cancelled=False,
                       incident=None, half_lap_seconds=None, sb_mark=None) for i in (1, 2, 3)])
        if different_person:
            rider = row['riders'][0]
            rider['official_registration_id'] = '880001'
            rider['identity_key'] = digest({'namespace': self.api.IDENTITY_NAMESPACE, 'registration': '880001'})
        row['input_sha256'] = input_digest(row)
        return row

    def test_native_projection_and_existing_official_identity_namespace_are_reused(self):
        before = deepcopy((self.payload, self.original))
        with patch.object(native, 'project', wraps=native.project) as projected:
            row = self.project()
        projected.assert_called_once()
        self.assertEqual((self.payload, self.original), before)
        self.assertEqual(row['race_class'], 'L1')
        self.assertEqual(row['race_type'], 'SELECTION')
        self.assertFalse(row['lines_applicable'])
        self.assertFalse(row['lines_known'])
        self.assertEqual(row['line_groups'], [])
        self.assertEqual(row['input_sha256'], input_digest(row))
        self.assertEqual(row['available_at'], self.original['snapshot']['as_of'])
        self.assertEqual(row['source_verified_at'],
                         self.original['origin_receipts']['baseline_origin']['latest_server_evidence_at'])
        self.assertEqual(row['source_attestation_sha256'],
                         digest({'fixture_payload': digest(self.calls[-1])}))
        self.assertNotIn('prediction_at', row)
        for actual, saved in zip(row['riders'], self.original['snapshot']['riders']):
            self.assertEqual(actual['official_registration_id'], saved['athlete_id'])
            self.assertEqual(actual['identity_key'], digest({'namespace': self.api.IDENTITY_NAMESPACE,
                                                            'registration': saved['athlete_id']}))
            self.assertTrue(actual['identity_usable'])
            self.assertIsNone(actual['age'])
            self.assertIsNone(actual['top2_rate'])
            self.assertIsNone(actual['gear_ratio'])
            self.assertAlmostEqual(actual['win_rate'], saved['recent_form_score'])

    def test_only_explicit_profile_values_enrich_age_and_rates(self):
        self.payload, self.original = _original(extra=(
            '<table><tr><th>年齢</th><td>30歳</td></tr>'
            '<tr><th>2連対率</th><td>40.5%</td></tr>'
            '<tr><th>3連対率</th><td>61.0%</td></tr></table>').encode())
        row = self.project()
        actual, = [r for r in row['riders'] if r['age'] is not None]
        self.assertEqual((actual['age'], actual['top2_rate'], actual['top3_rate']), (30., .405, .61))
        self.assertIsNone(actual['gear_ratio'])

    def test_wrong_registration_or_changed_source_never_reaches_admission_callback(self):
        for change in ('registration', 'raw'):
            with self.subTest(change=change):
                payload = deepcopy(self.payload)
                source = payload['baseline_arguments']['profile_sources'][0]
                if change == 'registration':
                    source['registration_id'] = '999998'
                else:
                    source['raw_bytes'] += b'PRIVATE_UNTRUSTED_TEXT'
                with self.assertRaisesRegex(ValueError, '^DT_R1_OFFICIAL_INPUT_NATIVE_SOURCE_PROJECTION_FAILED$'):
                    self.api.project(payload, self.original, prediction_at=self.at, source_verifier=self.verifier)
        self.assertEqual(self.calls, [])

    def test_boolean_or_incomplete_or_mismatched_receipts_are_not_admission(self):
        def changed(field, value):
            def callback(packet):
                result = self.verifier(packet)
                result[field] = value
                return result
            return callback
        for callback in (None, lambda packet: True, changed('independent', False),
                         changed('payload_sha256', '0' * 64), changed('receipt_sha256', 'bad')):
            with self.subTest(callback=callback), self.assertRaises(ValueError):
                self.api.project(self.payload, self.original, prediction_at=self.at, source_verifier=callback)

    def test_revalidation_does_not_invent_a_new_historical_source_clock(self):
        def later_check(packet):
            receipt = self.verifier(packet)
            receipt['verified_at'] = '2030-01-15T02:02:00+00:00'
            return receipt
        row = self.api.project(self.payload, self.original, prediction_at=self.at, source_verifier=later_check)
        self.assertEqual(row['source_verified_at'],
                         self.original['origin_receipts']['baseline_origin']['latest_server_evidence_at'])
        self.assertEqual(row['context_as_of'], self.at)
        self.assertNotIn('prediction_at', row)

    def test_prediction_clock_cannot_precede_source_or_exceed_cutoff_minus_fifteen(self):
        cutoff = clock(self.original['baseline']['published_cutoff_at'])
        for at in ('2030-01-15T02:00:12+00:00',
                   (cutoff - timedelta(minutes=15) + timedelta(microseconds=1)).isoformat(),
                   (cutoff + timedelta(hours=1)).isoformat()):
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.api.project(self.payload, self.original, prediction_at=at, source_verifier=self.verifier)
        exact = (cutoff - timedelta(minutes=15)).isoformat()
        self.api.project(self.payload, self.original, prediction_at=exact, source_verifier=self.verifier)

    def test_target_results_odds_and_conditioned_forecasts_never_enter_inputs(self):
        first = self.prepare()
        additions = dict(result_rows=[{'car': 7, 'rank': 1}], top3=[7, 6, 5],
                         official_result={'PRIVATE_TARGET_RESULT': True},
                         odds={'PRIVATE_ODDS': 99}, conditioned={'PRIVATE_RIVAL_FORECAST': True})
        self.payload.update(additions)
        self.original.update(deepcopy(additions))
        second = self.prepare()
        self.assertEqual(first['input_sha256'], second['input_sha256'])
        self.assertEqual(first['feature_input_sha256'], second['feature_input_sha256'])
        np.testing.assert_array_equal(first['features'], second['features'])
        self.assertEqual(second['result_rows'], [])
        self.assertIsNone(second['top3'])
        self.assertEqual(second['result_status'], 'PENDING')
        self.assertFalse(second['official_result_authenticated'])
        self.assertNotIn('PRIVATE_', str(self.calls))

    def test_empty_history_is_explicit_and_feature_binding_is_complete(self):
        row = self.prepare()
        _verify_feature_binding(row)
        self.assertEqual(row['features'].shape, (7, 106))
        self.assertTrue(np.all(row['features'][:, FEATURE_INDEX['history_missing']] == 1))
        self.assertEqual(row['confidence']['label'], 'HOLD')
        self.assertEqual(row['history_evidence']['official_support']['history_races'], 0)
        self.assertEqual(row['history_evidence']['official_support']['status'], 'MISSING_HISTORY')
        self.assertFalse(row['forecast_original_sealed'])
        self.assertFalse(row['production_promoted'])

    def test_verified_history_matches_official_registration_not_car_or_archive_composite(self):
        target = self.project()
        for different in (False, True):
            history = self.history(target, different_person=different)
            row = self.prepare(history_records=[history], history_verifier=self.verifier)
            _verify_feature_binding(row)
            self.assertEqual(row['features'][0, FEATURE_INDEX['history_missing']], float(different))
            self.assertEqual(row['features'][1, FEATURE_INDEX['history_missing']], 0.)
        composite = self.history(target)
        composite['riders'][0]['identity_status'] = 'UNRESOLVED_SOURCE_COMPOSITE'
        composite['input_sha256'] = input_digest(composite)
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_HISTORY_IDENTITY_REQUIRED'):
            self.prepare(history_records=[composite], history_verifier=self.verifier)

    def test_history_requires_independent_result_receipt_and_real_availability_clocks(self):
        target = self.project()
        history = self.history(target)
        with self.assertRaisesRegex(ValueError, 'HISTORY_VERIFIER_REQUIRED'):
            self.prepare(history_records=[history])
        changes = [dict(day=target['day']), dict(result_at='2030-01-15T02:02:00+00:00'),
                   dict(available_at='2030-01-15T02:02:00+00:00'),
                   dict(official_result_authenticated=False), dict(input_sha256='0' * 64)]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.prepare(history_records=[dict(history, **change)], history_verifier=self.verifier)
        with self.assertRaises(ValueError):
            self.prepare(history_records=[history, history], history_verifier=self.verifier)

    def test_callback_mutation_cannot_rewrite_the_source_or_projected_values(self):
        before = deepcopy((self.payload, self.original))
        def mutate(packet):
            result = self.verifier(packet)
            packet['normalized_input']['riders'][0]['competition_points'] = 150
            return result
        row = self.api.project(self.payload, self.original, prediction_at=self.at, source_verifier=mutate)
        self.assertEqual((self.payload, self.original), before)
        self.assertEqual(row['riders'][0]['competition_points'],
                         self.original['snapshot']['riders'][0]['competition_points'])

    def test_existing_authority_can_recompute_the_exact_request_without_self_admitting(self):
        packet = self.api.verification_payload(self.payload, self.original, prediction_at=self.at)
        self.assertNotIn('source_attestation_sha256', packet['normalized_input'])
        self.assertNotIn('source_admission_status', packet['normalized_input'])
        def callback(received):
            expected = self.api.verification_payload(self.payload, self.original,
                                                       prediction_at=received['prediction_at'])
            self.assertEqual(digest(received), digest(expected))
            return self.verifier(received)
        row = self.api.project(self.payload, self.original, prediction_at=self.at, source_verifier=callback)
        self.assertEqual(row['source_admission_status'], 'ADMITTED')

    def test_existing_full_augmenters_match_the_pinned_462_column_schema_without_padding(self):
        from research.chatgpt_dt_r1.context import augment_features
        from research.chatgpt_dt_r1.agari import augment_agari
        from research.chatgpt_dt_r1.abilities import augment_abilities
        from research.chatgpt_dt_r1.model import RankModel
        from research.chatgpt_dt_r1.venues import VenueStore
        root = Path(__file__).parent
        model = RankModel.from_dict(json.loads((root / 'evidence/20261128-resume/frozen_model.json').read_text()))
        path = root / 'fixtures/venue_geometry.json'
        self.assertEqual(sha256(path.read_bytes()).hexdigest(), model.fit_meta['context']['venue_file_sha256'])
        base = self.prepare()
        enriched = augment_features([base], venue_store=VenueStore.load(path), as_of=self.at)
        full = augment_abilities(augment_agari(enriched))[0]
        _verify_feature_binding(full)
        self.assertEqual(tuple(full['feature_names']), model.feature_names)
        self.assertEqual(full['features'].shape, (7, 462))
        # Invented venue 98 has no real geometry entry. Existing missing-value
        # indicators stay set; schema compatibility is not real data coverage.
        self.assertTrue(np.all(full['features'][:, full['feature_names'].index('context_venue_circumference_m_missing')] == 1))
        self.assertEqual(full['confidence']['label'], 'HOLD')


if __name__ == '__main__':
    unittest.main()
