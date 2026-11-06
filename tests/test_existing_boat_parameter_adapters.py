"""Native BOAT research coefficients; fictional inputs, no source acquisition."""
from copy import deepcopy
import importlib
import importlib.util
import math
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_ab_shadow import build_pair, MODEL_IDS as AB
from race_ai.boat_live_feature_shadow import build_live_feature_shadow, MODEL_ID as CLITE
from race_ai.boat_tactical_scenarios import predict_tactical_shadow, MODEL_ID as TACTICAL
from race_ai.boat_multi_feature_models import run_models, MODEL_IDS as FULL
from tests.test_boat_ab_shadow import fixture as ab_fixture
from tests.test_boat_live_feature_shadow import fixture as clite_fixture
from tests.test_boat_tactical_scenarios import inputs as tactical_fixture, FORECAST_AT
from tests.test_boat_multi_feature_models import fixture as full_fixture


ORIGINAL_HASHES = {
    AB[0]: '558dbc4cf2daa35e4d0a90973c07b1469dc7861e4901310e9db3b0e7a9999085',
    AB[1]: 'e248a7ff145ef47c1605be95acc4d65e6f11957eabb9d54302dd7415abedf35d',
    CLITE: 'e13106f426fb16aed7abb772f82456e9a7d5e9d76704f7c76ba6ec29e5fb4f45',
    TACTICAL: 'd5c44d339175e637a96f2a2ac90cf17ecbc9c328cb48c136f80a6b70b4f65c4f',
    FULL[0]: '02fa29ebbd4e2d3dd88dd053c1f584e616a44f25b983f9a3300ef77beb1c8856',
    FULL[1]: '341c25449441466406c8049ea2c9cba7e391cd09b0ddca7c16e40be7342cdf1e',
}


def cases():
    source = ab_fixture(); at = '2030-11-03T13:18:00+09:00'
    pair = build_pair(source, at)
    out = [(mid, {'source': deepcopy(source)}, at, pair['models'][i]) for i, mid in enumerate(AB)]
    source, extra, at = clite_fixture()
    out.append((CLITE, {'base_source': source, 'extra': extra}, at,
                build_live_feature_shadow(source, extra, at)))
    source, histories, venue = tactical_fixture()
    out.append((TACTICAL, {'source': source, 'histories': histories, 'venue': venue}, FORECAST_AT,
                predict_tactical_shadow(source, histories, venue, FORECAST_AT)))
    snapshot = full_fixture(); results = run_models(snapshot)
    out.extend((mid, {'snapshot': deepcopy(snapshot)}, snapshot['as_of'], results[mid]) for mid in FULL)
    return out


def distribution(output):
    return output.get('candidates', output.get('full_120'))


def combination(row):
    return row.get('combination', [int(v) for v in row.get('ticket', '').split('-') if v])


class NativeBoatParameterAdaptersTests(unittest.TestCase):
    def adapter(self):
        name = 'race_ai.existing_boat_parameter_adapters'
        self.assertIsNotNone(importlib.util.find_spec(name), 'native BOAT parameter adapter is required')
        return importlib.import_module(name)

    def test_default_adapter_preserves_original_native_bytes_and_hashes(self):
        adapter = self.adapter()
        for mid, payload, at, original in cases():
            with self.subTest(model=mid):
                actual = adapter.predict(mid, payload, None, at=at)
                self.assertEqual(actual, original)
                self.assertEqual(digest(actual), ORIGINAL_HASHES[mid])
                self.assertNotIn('research_parameters', actual)

    def test_fitted_coefficients_change_native_distribution_without_mutating_inputs_or_defaults(self):
        adapter = self.adapter()
        changed = {AB[0]: 'log_national_rate', AB[1]: 'course_log_bonus_6',
                   CLITE: 'local_rate_delta', TACTICAL: 'course_logratio',
                   FULL[0]: 'ability', FULL[1]: 'attack_ability'}
        for mid, payload, at, original in cases():
            with self.subTest(model=mid):
                specification = adapter.specs(mid, 'boat')
                parameters = {name: bounds[0] for name, bounds in specification.items()}
                parameters[changed[mid]] = specification[changed[mid]][2]
                before = deepcopy((payload, parameters))
                actual = adapter.predict(mid, payload, parameters, at=at)
                self.assertNotEqual(distribution(actual), distribution(original))
                self.assertEqual(len(distribution(actual)), 120)
                self.assertAlmostEqual(math.fsum(r['score'] for r in distribution(actual)), 1., places=9)
                self.assertEqual(actual['research_parameters'], parameters)
                self.assertEqual(actual['model_id'], mid)
                self.assertEqual((payload, parameters), before)
                self.assertEqual(adapter.predict(mid, payload, None, at=at), original)

    def test_parameter_contract_rejects_missing_foreign_boolean_nonfinite_and_unbounded_values(self):
        adapter = self.adapter()
        for mid, payload, at, _ in cases():
            specification = adapter.specs(mid, 'boat')
            parameters = {name: bounds[0] for name, bounds in specification.items()}
            name = next(iter(parameters))
            invalid = [{}, dict(parameters, foreign_coefficient=1)]
            invalid.extend(dict(parameters, **{name: value}) for value in
                           (True, float('nan'), float('inf'), specification[name][2] + 1))
            for supplied in invalid:
                with self.subTest(model=mid, supplied=supplied), self.assertRaises(ValueError):
                    adapter.predict(mid, payload, supplied, at=at)
            with self.assertRaises(ValueError):
                adapter.specs(mid, 'horse')
            with self.assertRaises(ValueError):
                adapter.predict(mid, {}, parameters, at=at)

    def test_winner_objective_matches_native_full_mixture_at_bounds_and_utility_clamp(self):
        adapter = self.adapter()
        for mid, payload, at, _ in cases():
            specification = adapter.specs(mid, 'boat')
            parameters = {name: bounds[2] for name, bounds in specification.items()}
            if mid == TACTICAL:
                # Force one native utility below -20 without changing identity/history.
                payload['source']['boats'][0].update(national_win_rate=.01, exhibition_time_seconds=12.)
                for boat in payload['source']['boats'][1:]:
                    boat.update(national_win_rate=10., exhibition_time_seconds=4.)
            actual = adapter.predict(mid, payload, parameters, at=at)
            rows = distribution(actual)
            for row in (rows[0], rows[61], rows[-1]):
                with self.subTest(model=mid, winner=combination(row)):
                    p = adapter.probability(mid, payload, parameters, combination(row), at=at)
                    self.assertAlmostEqual(p, row['score'], delta=max(1e-14, row['score']*1e-10))
            for winner in ([1, 1, 2], [1, 2, 7], [True, 2, 3], [1, 2]):
                with self.assertRaises(ValueError):
                    adapter.probability(mid, payload, parameters, winner, at=at)

    def test_bounded_parameters_keep_pl_normalized_when_two_boats_dominate(self):
        adapter = self.adapter()
        for mid, payload, at, _ in cases():
            parameters = {name: bounds[2] for name, bounds in adapter.specs(mid).items()}
            if mid in AB or mid == TACTICAL or mid == CLITE:
                source = payload.get('source', payload.get('base_source'))
                for boat in source['boats']:
                    strong = boat['lane'] <= 2
                    boat.update(national_win_rate=10. if strong else .01,
                                exhibition_time_seconds=4. if strong else 12.)
            else:
                for boat in payload['snapshot']['entrants']:
                    strong = boat['lane'] <= 2
                    for name in ('ability_rating', 'recent_form_rating', 'motor_rating',
                                 'course_suitability_rating', 'start_consistency_rating'):
                        boat['features'][name] = 100. if strong else 0.
                    boat['features']['exhibition_time_seconds'] = 1. if strong else 20.
                    boat['features']['exhibition_start_seconds'] = 0. if strong else 1.
            with self.subTest(model=mid):
                output = adapter.predict(mid, payload, parameters, at=at)
                rows = distribution(output)
                self.assertTrue(all(math.isfinite(r['score']) and 0 <= r['score'] <= 1 for r in rows))
                self.assertAlmostEqual(math.fsum(r['score'] for r in rows), 1., places=9)
                self.assertAlmostEqual(adapter.probability(mid, payload, parameters, [1, 2, 3], at=at),
                                       next(r['score'] for r in rows if combination(r) == [1, 2, 3]), places=10)


if __name__ == '__main__':
    unittest.main()
