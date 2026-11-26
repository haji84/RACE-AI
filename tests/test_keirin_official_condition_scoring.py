"""Forward-only evaluation of the preregistered meeting-condition pair."""
from copy import deepcopy
from datetime import date, timedelta
from unittest import TestCase

from race_ai import keirin_official_condition_scoring as score
from race_ai import keirin_official_condition_trial as trial
from tests import test_keirin_official_condition_trial as trial_fixture
from tests.test_keirin_nationwide_auto_generator import CUTOFF

DAY = '2026-11-18'
SEALED = DAY + 'T09:03:00+09:00'
WITNESSED = DAY + 'T11:45:00+09:00'


class OfficialConditionScoringTests(TestCase):
    def inputs(self):
        pair = trial.build_pair(*trial_fixture.ConditionTrialTests().inputs())
        ranking = sorted(pair['baseline']['trifectas'], key=lambda row: (-row['probability'], row['order']))
        winner = ranking[0]['order'][:]
        full_order = winner + [car for car in pair['baseline']['cars'] if car not in winner]
        official = dict(race_id=pair['race_id'], status='FINAL_NORMAL', refund_status='NONE',
                        official_cutoff_at=CUTOFF, observed_at=DAY+'T12:10:00+09:00',
                        monetary_comparison_eligible=True,
                        finishes=[dict(car=car, status='FINISHED', place=place)
                                  for place, car in enumerate(full_order, 1)],
                        winning_triples=[winner], payouts_100yen=[dict(triple=winner, yen=1300)])
        return pair, official

    def observe(self, pair, result, **options):
        return score.observe(pair, result, sealed_at=SEALED, latest_server_evidence_at=WITNESSED, **options)

    def test_official_same_race_proper_scores_all_ranks_and_fixed_budget_payout(self):
        pair, result = self.inputs()
        row = self.observe(pair, result, competition='A1_A2', largest_line_size=3)
        report = score.summarize_day(DAY, [row])
        self.assertEqual(report['eligible_paired_races'], 1)
        self.assertEqual(report['markets']['trifecta_top4']['published']['hits'], 1)
        self.assertEqual(report['markets']['trifecta_top4']['virtual_returns']['published']['payout_yen'], 1300)
        self.assertEqual(report['markets']['exacta_top2']['paired_races'], 1)
        self.assertEqual(report['markets']['exacta_top2']['virtual_returns']['paired_races'], 0)
        self.assertEqual(report['markets']['top3_set_top1']['paired_races'], 1)
        self.assertEqual(report['probability_scores']['trial']['rider_full_rank']['count'], 7)
        self.assertEqual(report['probability_scores']['trial']['first_three_order']['count'], 1)
        self.assertEqual(report['subgroups']['meeting_grade']['F1']['exacta_top2']['paired_races'], 1)
        self.assertNotIn(pair['race_id'], str(report))
        for rider in pair['baseline']['riders']:
            self.assertNotIn(rider['name'], str(report))

    def test_late_readback_or_tied_race_never_enter_main_cohort(self):
        pair, result = self.inputs()
        with self.assertRaisesRegex(ValueError,'T15'):
            score.observe(pair, result, sealed_at=SEALED, latest_server_evidence_at=DAY+'T11:45:01+09:00')
        result['finishes'][1]['place'] = 1
        with self.assertRaisesRegex(ValueError,'PREMISE'):
            self.observe(pair, result)

    def test_official_exacta_payout_is_included_only_with_exact_result_binding(self):
        pair, result = self.inputs()
        order = tuple(result['winning_triples'][0][:2])
        observation = self.observe(pair, result, confirmed_exacta_payout=(order, 550))
        report = score.summarize_day(DAY, [observation])
        self.assertEqual(report['markets']['exacta_top2']['virtual_returns']['paired_races'], 1)
        with self.assertRaisesRegex(ValueError,'EXACTA_PAYOUT'):
            self.observe(pair, result, confirmed_exacta_payout=(order[::-1], 550))

    def test_pooled_progress_and_intervals_use_day_blocks_and_hold_adoption(self):
        pair,result = self.inputs()
        report = score.summarize_day(DAY,[self.observe(pair,result)])
        one = score.summarize_days([report])
        self.assertIsNone(one['primary']['trifecta_top4']['day_block_difference_ci95'])
        report2 = dict(deepcopy(report),day_jst=(date.fromisoformat(DAY)+timedelta(days=1)).isoformat())
        two = score.summarize_days([report2,report])
        self.assertEqual((two['measured_days'],two['eligible_paired_races']), (2,2))
        self.assertEqual(len(two['primary']['trifecta_top4']['day_block_difference_ci95']), 2)
        self.assertEqual(two['milestones'], {'100':False,'500':False,'1000':False})
        self.assertEqual(two['adoption_status'], 'HOLD_MINIMUM_SAMPLE_OR_DAYS')
        with self.assertRaisesRegex(ValueError,'DAILY_COHORT'):
            score.summarize_days([report,report])
