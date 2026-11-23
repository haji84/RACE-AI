import copy
import unittest

from race_ai import keirin_nationwide_auto_generator as original
from race_ai import keirin_rider_context as context


def card():
    rows = [
        dict(car=car, competition_points=91-car, win_rate=22, top2_rate=44, top3_rate=62,
             mark_rank=car, style='MARK', h_count=0, b_count=0, S=0,
             nige=0, makuri=0, sashi=2, mark=3)
        for car in range(1, 8)
    ]
    rows[0].update(style='NIGE', h_count=7, b_count=4, nige=3)
    rows[1].update(style='ALLROUND', h_count=4, makuri=2, S=3)
    rows[3].update(style='NIGE', h_count=6, b_count=9, nige=4, S=12)
    return dict(race_id='209901016201', riders=rows, line_groups=[[1,2,3],[4,5,6],[7]])


def scenarios(result, *, kind, rider):
    return [s for s in result['candidate']['A']['six_phase_scenarios']
            if s['branch_kind'] == kind and s['attacking_car'] == rider]


class RiderContextTests(unittest.TestCase):
    def test_home_tally_admits_a_follower_move_and_s_sets_initial_line(self):
        race = card()
        saved = copy.deepcopy(race)
        result = context.compare(race)
        self.assertEqual(race, saved)
        self.assertEqual(result['baseline'], original.generate_evidence_analysis(saved))
        paths = scenarios(result, kind='FOLLOWER_SELF_ATTACK', rider=2)
        self.assertTrue(paths)
        for path in paths:
            self.assertEqual(path['attack_phase'], 'FINAL_HOME')
            initial, bell, home, back, corner, goal = path['six_phases']
            self.assertEqual(initial['projected_order'][:3], [4,5,6])
            self.assertEqual(bell['projected_order'][:2], [1,2])
            self.assertEqual(home['projected_order'][:2], [2,1])
            self.assertEqual(back['projected_order'][:2], [2,1])
            self.assertEqual(home['local_transitions'][0]['overtaker'], 2)
        rider = result['candidate']['position_evidence'][2]
        self.assertEqual(rider['line_role'], 'FOLLOWER')
        self.assertEqual(rider['lead_counts'], {'S': 3.0, 'H': 4.0, 'B': 0.0})

    def test_back_tally_delays_the_same_move_until_the_back(self):
        race = card()
        race['riders'][1].update(h_count=0, b_count=5)
        result = context.compare(race)
        paths = scenarios(result, kind='FOLLOWER_SELF_ATTACK', rider=2)
        self.assertTrue(paths)
        for path in paths:
            self.assertEqual(path['attack_phase'], 'FINAL_BACK')
            self.assertEqual(path['six_phases'][2]['projected_order'][:2], [1,2])
            self.assertEqual(path['six_phases'][3]['projected_order'][:2], [2,1])

    def test_competing_leaders_can_both_drop_behind_the_two_followers(self):
        result = context.compare(card())
        paths = scenarios(result, kind='CONTESTED_FOLLOWER_ATTACK', rider=2)
        self.assertTrue(paths)
        self.assertTrue(any(path['projected_3ren_tan'][:2] == [2,5] for path in paths))
        for path in paths:
            for step in path['six_phases']:
                self.assertEqual(sorted(step['projected_order']), list(range(1,8)))
            self.assertFalse({1,4}.intersection(event['overtaker'] for event in path['finish_transitions']))
        self.assertIn([2,5], result['candidate']['A']['candidate_tickets']['2t'])
        self.assertNotIn([2,5], result['baseline']['A']['candidate_tickets']['2t'])

    def test_same_finish_with_two_timing_hypotheses_keeps_one_unit_of_support(self):
        race = card()
        one = context.compare(race)['candidate']
        race['riders'][1]['b_count'] = 5
        two = context.compare(race)['candidate']
        def branch_share(output):
            return sum(path['relative_research_weight'] for path in output['A']['six_phase_scenarios']
                       if path['branch_kind'] in ('FOLLOWER_SELF_ATTACK','CONTESTED_FOLLOWER_ATTACK'))
        self.assertGreater(two['new_scenario_count'], one['new_scenario_count'])
        self.assertAlmostEqual(branch_share(two), branch_share(one))

    def test_contest_requires_self_propulsion_on_both_lines(self):
        race = card()
        race['riders'][0].update(style='MARK', h_count=0, b_count=0, nige=0, makuri=0)
        result = context.compare(race)
        self.assertEqual(scenarios(result, kind='CONTESTED_FOLLOWER_ATTACK', rider=2), [])

    def test_marking_and_start_tally_alone_never_admit_an_independent_attack(self):
        race = card()
        race['riders'][1].update(style='MARK', h_count=0, makuri=0, S=21)
        result = context.compare(race)
        self.assertEqual(result['candidate']['new_scenario_count'], 0)
        for arm in ('A','B'):
            self.assertEqual(result['candidate'][arm]['markets'], result['baseline'][arm]['markets'])

    def test_missing_line_preserves_unavailable_tactical_forecast(self):
        race = card()
        race['line_groups'] = None
        result = context.compare(race)
        self.assertEqual(result['candidate']['new_scenario_count'], 0)
        self.assertEqual(result['candidate']['B']['state'], 'UNGENERATED_LINE_EVIDENCE_MISSING')
