import copy
import unittest

from race_ai import keirin_nationwide_auto_generator as original


def snapshot(lines=None):
    return {
        'race_id': '202611232611',
        'line_groups': lines,
        'riders': [
            {'car': car, 'competition_points': 100-car, 'win_rate': 30-car*4,
             'top2_rate': 48-car*4, 'top3_rate': 65-car*2, 'mark_rank': car,
             'style': '逃' if car in (1,3) else '追'}
            for car in range(1,6)
        ],
    }


class RankingAdjustmentTests(unittest.TestCase):
    def setUp(self):
        from race_ai import keirin_ranking_adjustment
        self.method = keirin_ranking_adjustment

    def test_zero_blend_replays_the_original(self):
        race = snapshot()
        base = original.generate_evidence_analysis(race)['A']
        self.assertEqual(base,self.method.adjust(race,base,'A',[{}, {}, {}],0.0))

    def test_third_place_fit_does_not_change_the_two_car_market(self):
        race = snapshot()
        base = original.generate_evidence_analysis(race)['A']
        same = self.method.adjust(race,base,'A',[{}, {}, {}],1.0)
        explained = self.method.adjust(race,base,'A',[{}, {}, {'relative_points': -3.0}],1.0)
        self.assertEqual(same['markets']['2t'],explained['markets']['2t'])
        self.assertEqual(same['candidate_tickets']['2t'],explained['candidate_tickets']['2t'])
        self.assertNotEqual(same['candidate_tickets']['3t'],explained['candidate_tickets']['3t'])

    def test_tactical_reweighting_preserves_paths_and_does_not_mutate_inputs(self):
        race = snapshot([[1,2],[3,4],[5]])
        base = original.generate_evidence_analysis(race)['B']
        saved = copy.deepcopy(base)
        changed = self.method.adjust(race,base,'B',[{'win_rate': 1.8},{'mark_first': 0.4},{}],0.75)
        for market in ('2t','3t'):
            self.assertEqual({tuple(x) for x in base['candidate_tickets'][market]},
                             {tuple(x) for x in changed['candidate_tickets'][market]})
        self.assertEqual([s['scenario_id'] for s in base['six_phase_scenarios']],
                         [s['scenario_id'] for s in changed['six_phase_scenarios']])
        self.assertEqual(base,saved)

    def test_missing_rates_do_not_look_like_zero_finish_history(self):
        race = snapshot()
        for row in race['riders']:
            row.pop('win_rate')
            row.pop('top2_rate')
        values = self.method.feature_vectors(original._evidence_profiles(race)[0])
        self.assertTrue(all(row['second_only_rate']==0 for row in values.values()))
        self.assertTrue(all(row['second_only_known']==0 for row in values.values()))


if __name__ == '__main__':
    unittest.main()
