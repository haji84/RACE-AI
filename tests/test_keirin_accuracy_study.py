"""Frozen selection and scoring rules, using invented uniform fields."""
from itertools import permutations
from math import log
import unittest

from scripts import keirin_accuracy_study as study


class AccuracyStudyTests(unittest.TestCase):
    def test_feature_missing_race_is_held_without_using_its_result_or_stopping_others(self):
        def card(points):
            return dict(input=dict(race_id='209901016201',line_groups=[[1,2],[3,4],[5]],riders=[
                dict(car=car,competition_points=points,win_rate=10,top2_rate=20,top3_rate=30,
                     style='NIGE',mark_rank='UNMARKED') for car in range(1,6)]),outcomes={})
        good,bad=card(80),card(0)
        accepted,held=study.model_examples([good,bad])
        self.assertEqual(accepted,[good])
        self.assertEqual(held,{'COMPETITION_POINTS_UNAVAILABLE_FOR_ALL':1})
        bad['outcomes']={'3t':[[5,4,3]]}
        self.assertEqual(study.model_examples([bad])[1],held)

    def test_selection_uses_tuning_only_and_does_not_trade_away_exacta_top2(self):
        data={
            'saved':dict(n=100,top4_3t=20,top2_2t=40,top8_3t=30,logloss_3t=3.),
            'first_two_24':dict(n=100,top4_3t=24,top2_2t=39,top8_3t=34,logloss_3t=2.9),
            'all_56':dict(n=100,top4_3t=22,top2_2t=40,top8_3t=33,logloss_3t=2.8),
        }
        self.assertEqual(study.choose_arm(data),'all_56')
        data['all_56']['top4_3t']=19
        self.assertEqual(study.choose_arm(data),'saved')

    def test_uniform_law_scores_all_outcomes_without_renormalizing_top8(self):
        cars=[1,2,3,4]
        law={order:1/24 for order in permutations(cars,3)}
        row=study.score_distribution(cars,law,[1,2,3,4])
        self.assertEqual((row['top1_3t'],row['top4_3t'],row['top8_3t']),(1,1,1))
        self.assertEqual((row['top1_2t'],row['top2_2t']),(1,1))
        self.assertAlmostEqual(row['logloss_3t'],log(24))
        self.assertAlmostEqual(row['brier_3t'],23/24)
        self.assertAlmostEqual(row['logloss_2t'],log(12))
        self.assertAlmostEqual(row['top4_mass_3t'],1/6)

    def test_bad_law_and_inconsistent_outcome_do_not_score(self):
        cars=[1,2,3,4]
        mass={order:1/24 for order in permutations(cars,3)}
        for truth in ([1,1,3,4],[1,2,3],[1,2,3,5]):
            with self.subTest(truth=truth),self.assertRaises(ValueError):
                study.score_distribution(cars,mass,truth)
        mass.pop((1,2,3))
        with self.assertRaises(ValueError):study.score_distribution(cars,mass,[1,2,3,4])

    def test_day_block_interval_counts_missing_days_as_no_information(self):
        self.assertEqual(study.day_bootstrap_interval([]),None)
        self.assertEqual(study.day_bootstrap_interval([('20990101',0.)]*3),[0.,0.])
        interval=study.day_bootstrap_interval([('20990101',1.),('20990102',1.)])
        self.assertEqual(interval,[1.,1.])


if __name__=='__main__':unittest.main()
