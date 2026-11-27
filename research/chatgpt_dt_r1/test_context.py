import copy
import unittest
import numpy as np

from research.chatgpt_dt_r1.context import augment_features
from research.chatgpt_dt_r1.features import FeatureBuilder, _bind_feature_input
from research.chatgpt_dt_r1.venues import VenueStore


def card():
    return {'race_id': 'target', 'day': '2026-07-10', 'venue_code': 'v', 'cohort': 'retrospective',
            'input_sha256': 'a' * 64, 'lines_known': False,
            'riders': [{'car': i, 'identity_key': str(i), 'identity_usable': True,
                        'style': 'NIGE' if i == 1 else 'OI', 'competition_points': 90 + i} for i in (1, 2, 3)]}


def observation(day='2026-07-01', kind='official_record'):
    return {'observation_id': 'o1', 'race_id': 'past', 'rider_id': '1', 'venue_id': 'v',
            'event_at': None, 'event_day': day, 'timings': {'agari_half_seconds': 12.},
            'identity_confidence': 1., 'uncertainties': {'agari_half_seconds': .05},
            'provenance': {'kind': kind, 'source_url': 'urn:synthetic:timing', 'source_sha256': 'c' * 64,
                           'retrieved_at': '2026-07-11T00:00:00Z', 'available_at': '2026-07-11T00:00:00Z'}}


class ContextTests(unittest.TestCase):
    def test_external_join_identity_cannot_change_after_feature_binding(self):
        changes={'identity_key':'another-rider','athlete_id':'another-athlete',
                 'official_registration_id':'999999','identity_usable':False,
                 'identity_status':'ALTERED','style':'SASHI'}
        for key,value in changes.items():
            with self.subTest(field=key):
                row=FeatureBuilder().transform(card())
                row['riders']=copy.deepcopy(row['riders'])
                row['riders'][0][key]=value
                with self.assertRaisesRegex(ValueError,'FEATURE_INPUT_HASH_MISMATCH'):
                    augment_features([row],timing_records=[observation()],as_of='2026-07-12T00:00:00Z')

    def test_external_context_clocks_cannot_change_after_binding(self):
        for key,value in (('race_at','2026-07-10T12:00:00Z'),('event_at','2026-07-10T12:00:00Z'),
                          ('venue_id','another-venue')):
            with self.subTest(field=key):
                row=FeatureBuilder().transform(card());row[key]=value
                with self.assertRaisesRegex(ValueError,'FEATURE_INPUT_HASH_MISMATCH'):
                    augment_features([row],as_of='2026-07-12T00:00:00Z')

    def test_legacy_binding_requires_rebuild_before_external_join(self):
        row=FeatureBuilder().transform(card())
        row['feature_binding_schema']='dt-r1-feature-input-v2'
        _bind_feature_input(row)
        with self.assertRaisesRegex(ValueError,'EXTERNAL_FEATURE_JOIN_REQUIRES_V3_REBUILD'):
            augment_features([row],timing_records=[observation()],as_of='2026-07-12T00:00:00Z')

    def test_context_cannot_rehash_a_changed_base_feature(self):
        row = FeatureBuilder().transform(card())
        row['features'][0, 0] += 1
        with self.assertRaisesRegex(ValueError, 'FEATURE_INPUT_HASH_MISMATCH'):
            augment_features([row], as_of='2026-07-12T00:00:00Z')

    def test_measured_timing_enters_only_later_targets(self):
        base = FeatureBuilder().transform(card())
        with_past = augment_features([base], timing_records=[observation()], as_of='2026-07-12T00:00:00Z')[0]
        names = with_past['feature_names']
        col = names.index('history_observed_agari_half_seconds_mean')
        self.assertAlmostEqual(with_past['features'][0, col], 12 / 20)
        self.assertEqual(with_past['features'][1, col], 0.)
        future = augment_features([base], timing_records=[observation(day='2026-07-10')], as_of='2026-07-12T00:00:00Z')[0]
        empty = augment_features([base], timing_records=[], as_of='2026-07-12T00:00:00Z')[0]
        np.testing.assert_array_equal(future['features'], empty['features'])
        self.assertEqual(future['feature_input_sha256'], empty['feature_input_sha256'])

    def test_prospective_timing_requires_earlier_jst_day_and_other_race(self):
        target=card()
        target.update(cohort='prospective',race_at='2026-07-10T10:00:00Z',
                      cutoff_at='2026-07-10T09:30:00Z')
        base=FeatureBuilder().transform(target)
        as_of='2026-07-10T09:00:00Z'
        prior=observation(day='2026-07-09')
        prior['event_at']='2026-07-09T06:00:00Z'
        prior['provenance'].update(retrieved_at='2026-07-09T07:00:00Z',
                                   available_at='2026-07-09T07:00:00Z')
        accepted=augment_features([base],timing_records=[prior],as_of=as_of)[0]
        mean=accepted['feature_names'].index('history_observed_agari_half_seconds_mean')
        self.assertAlmostEqual(accepted['features'][0,mean],.6)
        empty=augment_features([base],as_of=as_of)[0]
        cases=(dict(event_at='2026-07-10T06:00:00Z',event_day='2026-07-10'),
               dict(event_at='2026-07-09T18:00:00Z',event_day='2026-07-09'),
               dict(race_id='target'))
        for changes in cases:
            with self.subTest(changes=changes):
                held=copy.deepcopy(prior);held.update(changes)
                held['provenance'].update(retrieved_at='2026-07-10T07:00:00Z',
                                          available_at='2026-07-10T07:00:00Z')
                actual=augment_features([base],timing_records=[held],as_of=as_of)[0]
                np.testing.assert_array_equal(actual['features'],empty['features'])
                self.assertEqual(actual['feature_input_sha256'],empty['feature_input_sha256'])

    def test_retrospective_timing_uses_jst_event_day_at_utc_boundary(self):
        base=FeatureBuilder().transform(card())
        same_day=observation(day='2026-07-09')
        same_day['event_at']='2026-07-09T18:00:00Z'
        actual=augment_features([base],timing_records=[same_day],as_of='2026-07-12T00:00:00Z')[0]
        empty=augment_features([base],as_of='2026-07-12T00:00:00Z')[0]
        np.testing.assert_array_equal(actual['features'],empty['features'])
        self.assertEqual(actual['feature_input_sha256'],empty['feature_input_sha256'])

    def test_full_lap_only_is_ignored_and_never_converted_to_agari(self):
        base = FeatureBuilder().transform(card())
        full = observation()
        full['timings'] = {'full_last_lap_seconds': 24.}
        full['uncertainties'] = {'full_last_lap_seconds': .05}
        held = augment_features([base], timing_records=[full], as_of='2026-07-12T00:00:00Z')[0]
        empty = augment_features([base], timing_records=[], as_of='2026-07-12T00:00:00Z')[0]
        np.testing.assert_array_equal(held['features'], empty['features'])
        self.assertEqual(held['feature_input_sha256'], empty['feature_input_sha256'])
        self.assertEqual(held['context_evidence']['measured_timing_rider_count'], 0)
        both = observation()
        both['timings']['full_last_lap_seconds'] = 24.
        row = augment_features([base], timing_records=[both], as_of='2026-07-12T00:00:00Z')[0]
        self.assertEqual(row['features'][0, row['feature_names'].index('history_observed_full_last_lap_seconds_mean')], 0.)
        self.assertAlmostEqual(row['features'][0, row['feature_names'].index('history_observed_agari_half_seconds_mean')], .6)

    def test_ai_timing_is_not_promoted_to_measured_feature(self):
        row = augment_features([FeatureBuilder().transform(card())], timing_records=[observation(kind='ai_estimate')],
                               as_of='2026-07-12T00:00:00Z')[0]
        i = row['feature_names'].index('history_observed_agari_half_seconds_mean')
        self.assertEqual(row['features'][0, i], 0.)

    def test_geometry_current_value_assumption_is_explicit(self):
        store = VenueStore.from_records([{'venue_code': 'v', 'name': 'Synthetic', 'source_url': 'https://example.test/venue',
                                          'source_sha256': 'b' * 64, 'retrieved_at': '2026-07-11T00:00:00Z',
                                          'circumference_m': 400., 'straight_m': 60., 'cant_deg': 30.}])
        base = FeatureBuilder().transform(card())
        default = augment_features([base], venue_store=store, as_of='2026-07-12T00:00:00Z')[0]
        explicit = augment_features([base], venue_store=store, as_of='2026-07-12T00:00:00Z',
                                    allow_current_geometry_assumption=True)[0]
        col = explicit['feature_names'].index('context_venue_circumference_m')
        self.assertEqual(default['features'][0, col], 0.)
        self.assertEqual(explicit['features'][0, col], 1.)
        self.assertTrue(explicit['context_evidence']['current_geometry_assumption'])
        self.assertNotEqual(explicit['feature_input_sha256'], default['feature_input_sha256'])

    def test_weather_requires_source_and_availability(self):
        row = card()
        row['weather_observation'] = {'wind_speed_m_s': 3., 'available_at': '2026-07-13T00:00:00Z',
                                      'issued_at': '2026-07-10T00:00:00Z', 'source_sha256': 'd' * 64,
                                      'kind': 'forecast'}
        f = augment_features([FeatureBuilder().transform(row)], as_of='2026-07-12T00:00:00Z')[0]
        col = f['feature_names'].index('context_weather_wind_speed_m_s')
        self.assertEqual(f['features'][0, col], 0.)

    def test_unusable_identity_and_empty_roster_remain_unknown(self):
        row = card(); row['riders'][0]['identity_usable'] = False
        f = augment_features([FeatureBuilder().transform(row)], timing_records=[observation()], as_of='2026-07-12T00:00:00Z')[0]
        col = f['feature_names'].index('history_observed_agari_half_seconds_mean')
        self.assertEqual(f['features'][0, col], 0.)
        row['riders'] = []
        held = augment_features([FeatureBuilder().transform(row)], as_of='2026-07-12T00:00:00Z')[0]
        self.assertEqual(held['feature_status'], 'HOLD_UNSUPPORTED_ROSTER')
        self.assertEqual(held['features'].shape[0], 0)

    def test_context_after_prediction_is_rejected(self):
        from research.chatgpt_dt_r1.model import RankModel
        from research.chatgpt_dt_r1.pipeline import forecast_row
        row = card()
        row.update(cohort='prospective', cutoff_at='2026-07-10T10:30:00Z', available_at='2026-07-10T09:00:00Z',
                   source_attestation_sha256='f' * 64)
        row['weather_observation'] = {'wind_speed_m_s': 7., 'kind': 'forecast', 'source_sha256': 'e' * 64,
                                     'available_at': '2026-07-10T10:05:00Z', 'issued_at': '2026-07-10T10:05:00Z'}
        f = augment_features([FeatureBuilder().transform(row)], as_of='2026-07-10T10:10:00Z')[0]
        model = RankModel.zero(f['feature_names'])
        model.fit_meta.update(created_at='2026-07-01T00:00:00Z', training_last_day='2026-06-30')
        with self.assertRaisesRegex(ValueError, 'CONTEXT_AFTER_PREDICTION'):
            forecast_row(model, f, prediction_at='2026-07-10T10:00:00Z')


if __name__ == '__main__':
    unittest.main()
