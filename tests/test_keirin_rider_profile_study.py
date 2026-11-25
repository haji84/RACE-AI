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

    def test_finish_history_counts_distinct_calendar_windows_and_last_starts(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        rows = [Ride(f'{day}2101', '012345', finish, None, None, 'A') for day, finish in (
            ('20231124', 9), ('20231125', 8), ('20251125', 7), ('20260525', 6),
            ('20260725', 5), ('20260825', 4), ('20261025', 3), ('20261124', 2),
            ('20261125', 1), ('20261126', 1),
        )]
        rows.append(Ride('202611242102', '054321', 1, None, None, 'A'))
        report = HistoryBook(reversed(rows)).finish_history('012345', race_id='202611252611')
        self.assertEqual(report['as_of_exclusive'], '2026-11-25')
        self.assertEqual({key: row['observed_count'] for key, row in report['periods'].items()},
                         {'all': 8, '3_years': 7, '1_year': 6, '6_months': 5, '4_months': 4,
                          '3_months': 3, '1_month': 2})
        self.assertEqual(report['periods']['all']['missing_finish_count'], None)
        self.assertEqual(report['periods']['all']['finish_counts'][1], 0)
        self.assertEqual(report['periods']['1_month']['finish_rates'][2], 0.5)
        self.assertEqual(report['periods']['1_month']['first_observed_day'], '2026-10-25')
        self.assertEqual({key: row['unfilled_slots'] for key, row in report['last_starts'].items()},
                         {30: 22, 20: 12, 10: 2, 5: 0})
        last_five = report['last_starts'][5]
        self.assertEqual(last_five['finish_counts'], {1: 0, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 0, 8: 0, 9: 0})

    def test_finish_history_clamps_to_latest_allowed_day_and_preserves_missing(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        rows = [Ride(f'{day}2101', '012345', finish, None, None, 'A') for day, finish in (
            ('20260227', 9), ('20260228', 4), ('20260330', 2), ('20260331', 1),
        )]
        sample = HistoryBook(rows)
        report = sample.finish_history('012345', race_id='202604021301', latest_day='20260330')
        self.assertEqual(report['as_of_exclusive'], '2026-03-31')
        month = report['periods']['1_month']
        self.assertEqual(month['start_day_inclusive'], '2026-02-28')
        self.assertEqual(month['observed_count'], 2)
        self.assertEqual(month['finish_counts'][1], 0)
        self.assertEqual(month['finish_counts'][9], 0)
        empty = sample.finish_history('054321', race_id='202604021301')['last_starts'][5]
        self.assertEqual(empty['observed_count'], 0)
        self.assertEqual(empty['unfilled_slots'], 5)
        self.assertIsNone(empty['finish_rates'])
        self.assertIsNone(empty['first_observed_day'])
        self.assertIsNone(empty['latest_observed_day'])

    def test_finish_history_exposes_unordered_boundary_day_in_last_starts(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        rows = [Ride(race_id, '012345', finish, None, None, 'A') for race_id, finish in (
            ('202611202101', 9), ('202611202201', 8), ('202611212101', 7),
            ('202611222101', 6), ('202611232101', 5), ('202611242101', 4),
        )]
        last_five = HistoryBook(rows).finish_history('012345', race_id='202611252611')['last_starts'][5]
        self.assertEqual(last_five['observed_count'], 4)
        self.assertEqual(last_five['unfilled_slots'], 1)
        self.assertEqual(last_five['tied_boundary_observations'], 2)
        self.assertEqual(last_five['finish_counts'][8], 0)
        self.assertEqual(last_five['finish_counts'][9], 0)

    def test_finish_history_filters_intersection_before_taking_recent_runs(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        book = HistoryBook(Ride(race_id, '012345', finish, None, role, grade)
                           for race_id, finish, role, grade in (
            ('202611182401', 8, None, 'A'), ('202611192401', 3, 'LEAD', 'S'),
            ('202611202601', 2, 'LEAD', 'A'), ('202611210001', 7, 'LEAD', 'A'),
            ('202611222601', 4, None, 'A'), ('202611232601', 5, 'LEAD', None),
            ('202611242601', 6, 'SECOND', 'A'), ('202611252601', 1, 'LEAD', 'A'),
        ))
        race_id = '202611252611'
        unfiltered = book.finish_history('012345', race_id=race_id)
        self.assertEqual(unfiltered['periods']['all']['observed_count'], 7)
        self.assertNotIn('filter_coverage', unfiltered)
        filtered = book.finish_history('012345', race_id=race_id, track_code='26', role='LEAD', grade='A')
        self.assertEqual(filtered['filters'], {'track_code': '26', 'role': 'LEAD', 'grade': 'A'})
        self.assertEqual(filtered['filter_coverage'], {
            'examined_count': 7, 'matched_count': 1, 'known_nonmatch_count': 3, 'undetermined_count': 3,
            'missing_by_field': {'track_code': 1, 'role': 2, 'grade': 1},
        })
        one_month = filtered['periods']['1_month']
        self.assertEqual(one_month['observed_count'], 1)
        self.assertEqual(one_month['finish_counts'][2], 1)
        self.assertEqual(one_month['finish_counts'][1], 0)
        self.assertEqual(filtered['last_starts'][5]['unfilled_slots'], 4)

    def test_finish_history_applies_single_filters_and_the_earlier_history_lock(self):
        from scripts.keirin_rider_profile_history import HistoryBook, Ride

        book = HistoryBook(Ride(race_id, '012345', finish, None, role, grade)
                           for race_id, finish, role, grade in (
            ('202611192401', 3, 'LEAD', 'S'), ('202611202601', 2, 'SECOND', 'A'),
            ('202611212601', 1, 'LEAD', 'A'),
        ))
        context = dict(race_id='202611252611', latest_day='20261120')
        for filter_, chosen in (({'role': 'LEAD'}, 3), ({'grade': 'S'}, 3), ({'track_code': '26'}, 2)):
            with self.subTest(filter_=filter_):
                report = book.finish_history('012345', **context, **filter_)
                self.assertEqual(report['filter_coverage']['examined_count'], 2)
                self.assertEqual(report['periods']['all']['observed_count'], 1)
                self.assertEqual(report['periods']['all']['finish_counts'][chosen], 1)
        for filter_ in ({'role': 'unknown'}, {'grade': 'X'}, {'track_code': '00'}, {'track_code': 26}):
            with self.subTest(filter_=filter_), self.assertRaises(ValueError):
                book.finish_history('012345', **context, **filter_)

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

    def test_official_prefecture_suffixes_match_short_archive_labels(self):
        from scripts.keirin_rider_profile_identity import IdentityIndex

        catalog = IdentityIndex([
            {'registration': '012345', 'name': '選手一', 'cohort': 102, 'prefecture_or_country': '福岡県'},
            {'registration': '054321', 'name': '選手二', 'cohort': 101, 'prefecture_or_country': '京都府'},
            {'registration': '023456', 'name': '選手三', 'cohort': 100, 'prefecture_or_country': '北海道'},
        ], [])
        self.assertEqual(catalog.bind(('選手一', 102, '福岡')), '012345')
        self.assertEqual(catalog.bind(('選手一福', 102, '岡'), from_csv=True), '012345')
        self.assertEqual(catalog.bind(('選手二', 101, '京都')), '054321')
        self.assertEqual(catalog.bind(('選手三', 100, '北海道')), '023456')
        self.assertIsNone(catalog.bind(('選手二', 101, '東京')))

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
