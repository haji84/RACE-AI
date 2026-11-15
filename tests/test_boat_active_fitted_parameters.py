"""Synthetic fitted coefficients retain active lanes and sparse observations."""
from copy import deepcopy
import itertools
import math
import unittest

from race_ai import existing_boat_parameter_adapters as adapter
from race_ai.boat_ab_shadow import MODEL_IDS as AB, _rank
from race_ai.boat_live_feature_shadow import MODEL_ID as CLITE
from race_ai.boat_multi_feature_models import MODEL_IDS as FULL, run_models
from race_ai.boat_tactical_scenarios import MODEL_ID as TACTICAL
from tests.test_boat_live_feature_shadow import fixture as live_fixture
from tests.test_boat_multi_feature_models import fixture as multi_fixture
from tests.test_boat_sparse_multi_feature_models import sparse
from tests.test_boat_tactical_scenarios import inputs as tactical_inputs, FORECAST_AT


ROSTERS = ((1, 3, 6), (1, 2, 4, 6), (1, 3, 4, 5, 6))


def coefficients(mid, *, zero=False):
    return {name: 0. if zero else bounds[0] for name, bounds in adapter.specs(mid).items()}


def rows(output):
    return output.get('candidates', output.get('full_120'))


def ticket(row):
    return tuple(row['combination']) if 'combination' in row else tuple(map(int, row['ticket'].split('-')))


def pl(strengths, winning):
    a, b, c = winning
    return (strengths[a]/math.fsum(strengths.values()) *
            strengths[b]/math.fsum(v for lane, v in strengths.items() if lane != a) *
            strengths[c]/math.fsum(v for lane, v in strengths.items() if lane not in (a, b)))


class ActiveFittedParameterTests(unittest.TestCase):
    def assert_distribution(self, output, lanes):
        actual = rows(output)
        self.assertEqual({ticket(row) for row in actual}, set(itertools.permutations(lanes, 3)))
        self.assertTrue(all(math.isfinite(row['score']) and 0 <= row['score'] <= 1 for row in actual))
        self.assertAlmostEqual(math.fsum(row['score'] for row in actual), 1., places=10)

    def test_ab_and_current_features_apply_fits_to_physical_active_lanes(self):
        for lanes in ROSTERS:
            source, extra, at = live_fixture()
            source['boats'] = [row for row in source['boats'] if row['lane'] in lanes]
            extra['participants'] = [row for row in extra['participants'] if row['lane'] in lanes]
            for mid, changed in ((AB[0], 'log_national_rate'), (AB[1], 'course_log_bonus_6'),
                                 (CLITE, 'average_st_delta')):
                payload = {'base_source': source, 'extra': extra} if mid == CLITE else {'source': source}
                parameters = coefficients(mid)
                parameters[changed] = adapter.specs(mid)[changed][2]
                before = deepcopy((payload, parameters))
                with self.subTest(lanes=lanes, model=mid):
                    original = adapter.predict(mid, payload, None, at=at)
                    actual = adapter.predict(mid, payload, parameters, at=at)
                    self.assert_distribution(actual, lanes)
                    self.assertNotEqual(rows(actual), rows(original))
                    self.assertEqual(actual['research_parameters'], parameters)
                    self.assertEqual((payload, parameters), before)
                    winning = ticket(rows(actual)[0])
                    self.assertAlmostEqual(adapter.probability(mid, payload, parameters, winning, at=at),
                                           rows(actual)[0]['score'], places=12)

    def test_fitting_one_multi_feature_family_keeps_other_family_unchanged(self):
        for lanes in ROSTERS:
            snapshot = multi_fixture()
            snapshot['entrants'] = [row for row in snapshot['entrants'] if row['lane'] in lanes]
            original = run_models(snapshot)
            for mid, changed in ((FULL[0], 'ability'), (FULL[1], 'attack_ability')):
                parameters = coefficients(mid)
                parameters[changed] = adapter.specs(mid)[changed][2]
                actual = run_models(snapshot, parameters={mid: parameters})
                with self.subTest(lanes=lanes, model=mid):
                    self.assert_distribution(actual[mid], lanes)
                    self.assertNotEqual(rows(actual[mid]), rows(original[mid]))
                    other = next(model for model in FULL if model != mid)
                    self.assertEqual(actual[other], original[other])

    def test_sparse_fit_applies_observed_ability_and_omits_unavailable_terms(self):
        snapshot = sparse()
        strengths = {}
        for row, ability in zip(snapshot['entrants'], (100., 25., 0.)):
            row['missing'].pop('ability_rating')
            row['features']['ability_rating'] = ability
            strengths[row['lane']] = math.exp(2.*ability/100)
        parameters = coefficients(FULL[0], zero=True)
        parameters['ability'] = 2.
        before = deepcopy(snapshot)
        actual = run_models(snapshot, parameters={FULL[0]: parameters})[FULL[0]]
        for row in actual['candidates']:
            self.assertAlmostEqual(row['score'], pl(strengths, ticket(row)), places=13)
        parameters['recent'] = adapter.specs(FULL[0])['recent'][2]
        omitted = run_models(snapshot, parameters={FULL[0]: parameters})[FULL[0]]
        self.assertEqual(actual['candidates'], omitted['candidates'])
        self.assertEqual(snapshot, before)
        self.assertEqual(actual['missingness_policy'], 'OMIT_UNAVAILABLE_TERMS')

    def test_complete_sparse_observations_match_fitted_full_equations(self):
        for lanes in ROSTERS:
            snapshot = multi_fixture()
            snapshot['entrants'] = [row for row in snapshot['entrants'] if row['lane'] in lanes]
            parameters = {mid: {name: bounds[2] for name, bounds in adapter.specs(mid).items()} for mid in FULL}
            expected = run_models(snapshot, parameters=parameters)
            snapshot['schema'] = 'RACE_AI_BOAT_MULTI_FEATURE_SNAPSHOT_SPARSE_V1'
            snapshot['conditions_missing'] = {}
            for row in snapshot['entrants']:
                row['missing'] = {}
            actual = run_models(snapshot, parameters=parameters)
            for mid in FULL:
                with self.subTest(lanes=lanes, model=mid):
                    self.assert_distribution(actual[mid], lanes)
                    predicted = {ticket(row): row['score'] for row in rows(actual[mid])}
                    for row in rows(expected[mid]):
                        self.assertAlmostEqual(predicted[ticket(row)], row['score'], places=12)

    def test_sparse_weather_fit_uses_only_the_observed_weather(self):
        snapshot = sparse()
        snapshot['conditions'] = {'wave_height_cm': 50.}
        snapshot['conditions_missing'].pop('wave_height_cm')
        snapshot.update(conditions_source='fictional-observed-weather',
                        conditions_published_at='2030-04-01T10:30:00+09:00',
                        conditions_captured_at='2030-04-01T10:40:00+09:00')
        parameters = coefficients(FULL[1], zero=True)
        parameters['rough_swell'] = -1.
        actual = run_models(snapshot, parameters={FULL[1]: parameters})[FULL[1]]
        rough = {lane: math.exp(-lane/6) for lane in (1, 3, 6)}
        for row in actual['candidates']:
            expected = (1.-actual['scenario_weights']['rough'])/6 + actual['scenario_weights']['rough']*pl(rough, ticket(row))
            self.assertAlmostEqual(row['score'], expected, places=13)
        parameters['rough_breeze'] = adapter.specs(FULL[1])['rough_breeze'][1]
        self.assertEqual(actual['candidates'], run_models(snapshot, parameters={FULL[1]: parameters})[FULL[1]]['candidates'])

    def test_tactical_winner_objective_matches_active_physical_lane_forecasts(self):
        for lanes in ROSTERS:
            source, histories, venue = tactical_inputs()
            source['boats'] = [row for row in source['boats'] if row['lane'] in lanes]
            identities = {row['racer_id'] for row in source['boats']}
            histories = [row for row in histories if row['racer_id'] in identities]
            payload = {'source': source, 'histories': histories, 'venue': venue}
            fitted = {name: bounds[2] for name, bounds in adapter.specs(TACTICAL).items()}
            for parameters in (None, fitted):
                with self.subTest(lanes=lanes, fitted=parameters is not None):
                    actual = adapter.predict(TACTICAL, payload, parameters, at=FORECAST_AT)
                    self.assert_distribution(actual, lanes)
                    self.assertEqual(actual['entry_scenario_count'], math.factorial(len(lanes)))
                    for row in (rows(actual)[0], rows(actual)[len(rows(actual))//2], rows(actual)[-1]):
                        self.assertAlmostEqual(adapter.probability(TACTICAL, payload, parameters, ticket(row), at=FORECAST_AT),
                                               row['score'], delta=max(1e-14, row['score']*1e-10))
                    absent = next(lane for lane in range(1, 7) if lane not in lanes)
                    with self.assertRaises(ValueError):
                        adapter.probability(TACTICAL, payload, parameters, [lanes[0], lanes[1], absent], at=FORECAST_AT)

    def test_stable_rank_supports_extreme_fitted_strengths_and_active_lanes(self):
        for lanes in (*ROSTERS, (1, 2, 3, 4, 5, 6)):
            strengths = [math.exp(20.) if lane in lanes[:2] else math.exp(-20.) for lane in lanes]
            actual = {'full_120': _rank(strengths, lanes, stable=True)}
            self.assertEqual({tuple(row['ticket']) for row in actual['full_120']}, set(itertools.permutations(lanes, 3)))
            self.assertAlmostEqual(math.fsum(row['score'] for row in actual['full_120']), 1., places=12)


if __name__ == '__main__':
    unittest.main()
