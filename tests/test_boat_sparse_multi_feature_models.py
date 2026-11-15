"""Unavailable official fields omit their terms; no weather or ratings invented."""
from copy import deepcopy
import math
import unittest

from race_ai.boat_multi_feature_models import run_models, FEATURE_RANGES, CONDITIONS, MODEL_IDS
from tests.test_boat_multi_feature_models import fixture


def sparse():
    snapshot = fixture()
    snapshot['schema'] = 'RACE_AI_BOAT_MULTI_FEATURE_SNAPSHOT_SPARSE_V1'
    snapshot['entrants'] = [r for r in snapshot['entrants'] if r['lane'] in (1, 3, 6)]
    for row in snapshot['entrants']:
        row['features'] = {'exhibition_time_seconds': 6.8}
        row['missing'] = {name: 'SOURCE_UNAVAILABLE' for name in FEATURE_RANGES
                          if name != 'exhibition_time_seconds'}
    snapshot['conditions'] = {}
    snapshot['conditions_missing'] = {name: 'SOURCE_UNAVAILABLE' for name in CONDITIONS}
    snapshot['conditions_source'] = None
    snapshot['conditions_published_at'] = None
    snapshot['conditions_captured_at'] = None
    return snapshot


class SparseMultiFeatureTests(unittest.TestCase):
    def test_only_observed_exhibition_and_physical_lane_terms_are_scored(self):
        snapshot = sparse()
        out = run_models(snapshot)
        comprehensive = out[MODEL_IDS[0]]
        candidates = {tuple(r['combination']): r['score'] for r in comprehensive['candidates']}
        # Equal observed exhibition cancels. The only differing known term is
        # the fixed physical lane prior, coefficient .3, on lanes 1, 3 and 6.
        first, second, third = math.exp(.3), math.exp(.2), math.exp(.05)
        total = first+second+third
        expected = first/total * second/(total-first) * third/(total-first-second)
        self.assertAlmostEqual(candidates[(1, 3, 6)], expected, places=13)
        self.assertEqual(out[MODEL_IDS[1]]['scenario_weights'],
                         {'calm_front': .53, 'attack': .32, 'rough': .15})
        for model in out.values():
            self.assertEqual(model['input_schema'], snapshot['schema'])
            self.assertEqual(model['model_version'], '0.2.0-SPARSE-UNTRAINED')
            self.assertEqual(model['missing_conditions'], snapshot['conditions_missing'])
            self.assertEqual(model['missingness_policy'], 'OMIT_UNAVAILABLE_TERMS')
            self.assertEqual(model['missing_features'], [dict(lane=r['lane'],
                participant_id=r['participant_id'], missing=r['missing']) for r in snapshot['entrants']])
            self.assertEqual(len(model['ordered_top8']), 6)
        self.assertEqual(snapshot, sparse())

    def test_observed_feature_changes_ranking_and_missing_reason_is_not_a_value(self):
        snapshot = sparse()
        before = run_models(snapshot)
        snapshot['entrants'][0]['missing']['ability_rating'] = 'NOT_YET_PUBLISHED'
        reclassified = run_models(snapshot)
        self.assertEqual(before[MODEL_IDS[0]]['candidates'], reclassified[MODEL_IDS[0]]['candidates'])
        snapshot['entrants'][0]['missing'].pop('ability_rating')
        snapshot['entrants'][0]['features']['ability_rating'] = 100.
        after = run_models(snapshot)
        p = lambda out: next(r['score'] for r in out[MODEL_IDS[0]]['candidates']
                             if r['combination'] == [1, 3, 6])
        self.assertGreater(p(after), p(before))

    def test_sparse_partition_values_and_provenance_stay_strict(self):
        mutations = (
            lambda s: s['entrants'][0]['missing'].pop('ability_rating'),
            lambda s: s['entrants'][0]['missing'].update(odds='MISSING'),
            lambda s: s['entrants'][0]['features'].update(ability_rating=None),
            lambda s: s['entrants'][0]['missing'].update(ability_rating='WITHDRAWN'),
            lambda s: s['conditions'].update(wind_speed_mps=0),
            lambda s: s['conditions_missing'].pop('wind_speed_mps'),
            lambda s: s.update(conditions_source='invented-source'),
            lambda s: s['entrants'][0].update(captured_at=s['sales_cutoff_at']),
            lambda s: s['entrants'][0]['features'].update(actual_finish=1),
        )
        for mutate in mutations:
            snapshot = sparse()
            mutate(snapshot)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                run_models(snapshot)

    def test_observed_partial_weather_requires_real_time_and_source(self):
        snapshot = sparse()
        snapshot['conditions']['wave_height_cm'] = 100.
        snapshot['conditions_missing'].pop('wave_height_cm')
        with self.assertRaises(ValueError):
            run_models(snapshot)
        snapshot.update(conditions_source='fictional-observed-weather',
            conditions_published_at='2030-04-01T10:30:00+09:00',
            conditions_captured_at='2030-04-01T10:40:00+09:00')
        out = run_models(snapshot)
        self.assertAlmostEqual(out[MODEL_IDS[1]]['scenario_weights']['rough'], .35)
        snapshot['conditions_captured_at'] = '2030-04-01T11:40:00+09:00'
        with self.assertRaises(ValueError):
            run_models(snapshot)


if __name__ == '__main__':
    unittest.main()
