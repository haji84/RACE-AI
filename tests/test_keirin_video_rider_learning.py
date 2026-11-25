import copy
import math
import unittest

from scripts import keirin_video_rider_learning as learning


def race(day, suffix='01'):
    return {
        'race_id': day.replace('-', '') + '-21-' + suffix, 'race_date': day,
        'riders': [{'car': 1, 'rider_id': '012345'}, {'car': 2, 'rider_id': '012346'},
                   {'car': 3, 'rider_id': '012347'}, {'car': 4, 'rider_id': None}],
    }


def observation(race, *, car=1, task='attack', value='H', scope='H', level='clip', **extra):
    return {**{k: race[k] for k in ('race_id', 'race_date')}, 'car': car,
            'rider_id': race['riders'][car - 1]['rider_id'], 'task': task,
            'value': value, 'scope': scope, 'window_level': level, **extra}


class RiderVideoLearningTests(unittest.TestCase):
    def test_scores_prior_days_only_and_retains_eligible_cold_riders(self):
        d1 = race('2025-01-01')
        d2 = race('2025-01-02')
        again = race('2025-01-02', '02')
        census = [again, d2, d1]
        rows = [observation(d1), observation(d2, value='no_attack'),
                observation(again, value='no_attack'), observation(d2, car=2)]
        report, profiles = learning.study(census, reversed(rows))
        section, = report['strata']
        self.assertEqual(section['bootstrap_observations'], 1)
        self.assertEqual(section['scores']['all']['n'], 3)
        self.assertEqual(section['scores']['prior_rider']['n'], 2)
        # Only the Jan 1 label can affect either Jan 2 prediction.
        self.assertAlmostEqual(section['scores']['prior_rider']['rider']['log_loss'], -math.log(4 / 15))
        self.assertEqual(section['scores']['cold_rider']['n'], 1)
        self.assertEqual(section['scores']['cold_rider']['rider'], section['scores']['cold_rider']['population'])
        self.assertEqual(report['eligible_riders'], 3)
        self.assertEqual(profiles['012347'], [])
        self.assertEqual(profiles['012345'][0]['observations'], 3)
        self.assertEqual(profiles['012345'][0]['counts'], {'H': 1, 'no_attack': 2})
        self.assertEqual(learning.study(census, rows), (report, profiles))
        graph, prior = learning.study(census, rows, before='2025-01-02')
        self.assertEqual(prior['012345'][0]['observations'], 1)
        self.assertEqual(graph['census_through_jst'], '2025-01-01')
        self.assertEqual(graph['last_training_race_date_jst'], '2025-01-01')
        self.assertAlmostEqual(sum(graph['strata'][0]['population_probabilities'].values()), 1)
        self.assertEqual(graph['strata'][0]['scores']['all']['n'], 0)

    def test_scope_level_task_and_missing_do_not_leak(self):
        d1, d2 = race('2025-01-01'), race('2025-01-02')
        rows = [observation(d1), observation(d2, scope='H', level='sector'),
                observation(d2, scope='4C', value='4C'),
                observation(d2, car=2, value='unknown'),
                observation(d2, task='follow', value='held', target_car=2, target_rider_id='012346')]
        report, profiles = learning.study([d1, d2], rows)
        self.assertEqual(len(report['strata']), 4)
        self.assertEqual(report['unknown_observations'], 1)
        self.assertTrue(all(row['scores']['all']['n'] == 0 for row in report['strata']))
        self.assertEqual(len(profiles['012345']), 4)
        self.assertEqual(profiles['012346'], [])
        empty, profiles = learning.study([d1], [])
        self.assertEqual(empty['strata'], [])
        self.assertEqual(empty['reviewed_races'], 0)
        self.assertEqual(len(profiles), 3)

    def test_whole_race_location_separate_from_whether_an_attack_happened(self):
        d1, d2 = race('2025-02-01'), race('2025-02-02')
        def full(r, car, outcome):
            return observation(r, car=car, scope='whole_race', level='whole_race', value=outcome)
        records = [full(d1, 1, 'before_bell'), full(d2, 1, 'bell_to_H'), full(d2, 2, 'no_attack')]
        records.append(observation(d1, car=2, scope='bell', value='bell'))
        report, _ = learning.study([d1, d2], records)
        early, whole = report['strata']
        self.assertNotIn('first_location_given_attack', early)
        self.assertEqual(whole['first_location_given_attack']['all']['n'], 1)
        self.assertEqual(whole['any_attack_in_observed_window']['all']['n'], 2)
        with self.assertRaises(ValueError):
            learning.study([d1], [observation(d1, value='bell', scope='whole_final_lap', level='whole_final_lap')])

    def test_passing_changes_the_follow_category_and_keeps_both_identities_bound(self):
        day = race('2025-02-10')
        row = observation(day, task='follow', value='passed_target', target_car=2, target_rider_id='012346')
        report, profiles = learning.study([day], [row])
        self.assertEqual(profiles['012345'][0]['counts'], {'passed_target': 1})
        self.assertEqual(len(report['strata'][0]['population_probabilities']), 5)
        with self.assertRaises(ValueError):
            learning.study([day], [{**row, 'target_rider_id': '012347'}])

    def test_no_duplicates_or_unbound_evidence(self):
        r = race('2025-01-01')
        good = observation(r)
        for bad in ({'car': True}, {'race_date': '2025-01-02'}, {'rider_id': '000123'},
                    {'value': 'mixed'}, {'scope': 'unknown'}, {'window_level': 'unknown'},
                    {'task': 'follow', 'value': 'held'}, {'task': 'follow', 'value': 'passed_target'},
                    {'task': 'follow', 'value': 'no_target', 'target_car': 1},
                    {'task': 'follow', 'value': 'held', 'target_car': 1, 'target_rider_id': '012345'},
                    {'task': 'follow', 'value': 'held', 'target_car': 2, 'target_rider_id': '012347'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                learning.study([r], [{**good, **bad}])
        with self.assertRaises(ValueError):
            learning.study([r], [good, good])
        wrong = copy.deepcopy(r)
        wrong['riders'][1]['rider_id'] = '012345'
        with self.assertRaises(ValueError):
            learning.study([wrong], [])
