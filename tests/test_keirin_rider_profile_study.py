import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'Optional research dependency')
class KeirinRiderProfileStudyTests(unittest.TestCase):
    def test_score_expectations_preserve_the_total_probability_of_each_place(self):
        import numpy as np
        from scripts.keirin_rider_profile_history import expected_finish

        equal = expected_finish([80.0] * 7)
        np.testing.assert_allclose(equal, np.full((7, 3), 1 / 7))
        unequal = expected_finish([102.0, 90.0, 89.0, 82.0, 80.0])
        np.testing.assert_allclose(unequal.sum(axis=0), [1, 1, 1])
        self.assertGreater(unequal[0, 0], unequal[-1, 0])

    def test_field_with_extreme_competition_points_has_nonnegative_probabilities(self):
        import numpy as np
        from scripts.keirin_rider_profile_history import expected_finish

        expected = expected_finish([150, 25, 1, 1, 1])
        self.assertTrue(np.all(expected >= 0), expected.min())
        np.testing.assert_allclose(expected.sum(axis=0), [1, 1, 1])

    def test_profile_excludes_target_day_and_future_observations(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        older = Ride('202610012101', '012345', 2, (0.1, 0.2, 0.2), 'SECOND', 'A', s=True, b=False)
        same_day = Ride('202610022102', '012345', 1, (0.1, 0.2, 0.2), 'SECOND', 'A', s=True, b=True)
        future = Ride('202610032101', '012345', 1, (0.1, 0.2, 0.2), 'LEAD', 'A', s=True, b=True)
        sample = HistoryBook([older, same_day, future])
        expected = HistoryBook([older])
        context = dict(race_id='202610022101', role='SECOND', grade='A')
        self.assertEqual(sample.features('012345', **context), expected.features('012345', **context))
        values, counts = sample.features('012345', **context)
        self.assertEqual(counts['career'], 1)
        self.assertEqual(counts['role'], 1)
        self.assertGreater(values['overall_second'], 0.0)

    def test_unknown_registration_has_zero_features_and_duplicate_rows_are_refused(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        row = Ride('202610012101', '012345', 2, None, None, 'A')
        with self.assertRaisesRegex(ValueError, 'Repeated rider and race'):
            HistoryBook([row, row])
        self.assertRaises(ValueError, Ride, '202610012101', 'not-a-registration', 2, None, None, 'A')
        values, counts = HistoryBook([row]).features('054321', race_id='202610022101', role='SECOND', grade='A')
        self.assertTrue(all(value == 0 for value in values.values()))
        self.assertTrue(all(count == 0 for count in counts.values()))

    def test_venue_and_role_features_are_conditioned_separately(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        rows = [
            Ride('202610012101', '012345', 1, (0.2, 0.2, 0.2), 'LEAD', 'A', b=True),
            Ride('202610022201', '012345', 5, (0.2, 0.2, 0.2), 'SECOND', 'A', b=False),
            Ride('202610032201', '012345', 3, (0.2, 0.2, 0.2), 'SECOND', 'A', b=False),
        ]
        sample = HistoryBook(rows)
        values, counts = sample.features('012345', race_id='202610042101', role='LEAD', grade='A')
        self.assertEqual((counts['career'], counts['track'], counts['role']), (3, 1, 1))
        self.assertGreater(values['role_b'], 0.0)
        self.assertGreater(values['track_top3'], 0.0)

    def test_identity_cannot_leak_via_an_unbound_profile(self):
        from scripts.keirin_rider_profile_study import profile_columns

        columns = profile_columns([{'car': 1, 'profile': {'overall_win': 0.4}}], [1])
        self.assertEqual(columns['overall_win'][0], 0.0)

    def test_locked_history_keeps_later_evaluation_results_out(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        before = Ride('202609292101', '012345', 2, None, 'SECOND', 'A', b=True)
        after = Ride('202610012101', '012345', 1, None, 'SECOND', 'A', b=False)
        context = dict(race_id='202611242104', role='SECOND', grade='A', latest_day='20260930')
        self.assertEqual(HistoryBook([before, after]).features('012345', **context),
                         HistoryBook([before]).features('012345', **context))

    def test_registration_binding_recovers_the_documented_prefecture_split(self):
        from scripts.keirin_rider_profile_identity import IdentityIndex

        catalog = IdentityIndex([{'registration': '012345', 'name': '競輪 選手',
                                  'cohort': 100, 'prefecture_or_country': '福岡'}], [])
        self.assertEqual(catalog.bind(('競輪選手福', 100, '岡'), from_csv=True), '012345')
        self.assertIsNone(catalog.bind(('競輪選手福', 101, '岡'), from_csv=True))
        self.assertIsNone(catalog.bind(('競輪選手福', 100, '岡')))
        self.assertIsNone(catalog.bind(('競輪選手福', 100, '島'), from_csv=True))

    def test_observing_one_rider_does_not_remove_another_rider_with_the_same_name(self):
        from scripts.keirin_rider_profile_identity import IdentityIndex

        catalog = IdentityIndex([
            {'registration': registration, 'name': '競輪選手', 'cohort': 100, 'prefecture_or_country': prefecture}
            for registration, prefecture in (('012345', '福岡'), ('054321', '福島'))
        ], [])
        catalog.observe_exact_race(('競輪選手', 100, '福岡'), '012345')
        self.assertEqual(catalog.bind(('競輪選手', 100, '福島')), '054321')
        catalog.observe_exact_race(('競輪選手', 100, '福島'), '012345')
        self.assertIsNone(catalog.bind(('競輪選手', 100, '福島')))

    def test_profile_features_participate_in_all_three_finishing_stages(self):
        from scripts import keirin_rider_profile_study as study

        card = {'race_id': '202611012201', 'line_groups': [[1, 3, 4], [2, 5]],
                'riders': [{'car': car, 'competition_points': 105.0, 'registration': f'{car:06d}',
                            'profile': {'overall_win': float(car == 5), 'overall_second': float(car == 3),
                                        'overall_third': float(car == 4)}}
                           for car in range(1, 6)]}
        coefficients = {mode: [dict.fromkeys(study.names_for(mode, stage), 0.0) for stage in range(3)]
                        for mode in study.MODES}
        coefficients['rider_form'][0]['overall_win'] = 2.0
        coefficients['rider_form'][1]['overall_second'] = 2.0
        coefficients['rider_form'][2]['overall_third'] = 2.0
        ranked = study.predict(card, coefficients)
        self.assertEqual(ranked['published_line']['3t'][0], (1, 2, 3))
        self.assertEqual(ranked['rider_form']['2t'][0], (5, 3))
        self.assertEqual(ranked['rider_form']['3t'][0], (5, 3, 4))

    def test_current_b_profile_adjustment_preserves_pair_when_only_third_changes(self):
        from race_ai.keirin_nationwide_auto_generator import select_scenario_markets
        from scripts import keirin_rider_profile_study as study

        card = {'riders': [{'car': car, 'registration': f'{car:06d}',
                            'profile': {'overall_third': float(car == 4)}} for car in range(1, 5)]}
        paths = [dict(tactical_branch_id='branch', projected_3ren_tan=(1, 2, third),
                      scenario_id=f's{third}', rationale=[], pair_support_B=1.0, support_B=support)
                 for third, support in ((3, 0.6), (4, 0.4))]
        original = {'six_phase_scenarios': paths, **select_scenario_markets(paths, arm='B')}
        keep = [{}, {}, {'overall_third': 2.0}]
        adjusted = study.current_b_with_profile(card, original, keep)
        self.assertEqual(adjusted['2t'], original['candidate_tickets']['2t'])
        self.assertEqual(adjusted['3t'][0], [1, 2, 4])
        self.assertEqual(paths[0]['support_B'], .6)
        self.assertEqual(study.current_b_with_profile(card, original, [{}, {}, {}]), original['candidate_tickets'])
