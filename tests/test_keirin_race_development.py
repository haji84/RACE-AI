"""Rank and race-flow evidence have separate sources and denominators."""
from copy import deepcopy
import unittest

from race_ai import keirin_form_fall_blind_pdca as pdca

RACE = '202611252611'
STARTERS = [1, 2, 3, 4, 5, 6, 7]
JST_CUTOFF = '2026-11-25T20:10:00+09:00'


def predicted():
    initial=[5,3,4,6,1,2,7]
    full=[2,7,5,3,4,6,1]
    return dict(scope='registered', race_id=RACE, cutoff_at=JST_CUTOFF,
                sealed_at='2026-11-25T20:00:00+09:00', tickets=[[5,3,1],[3,5,1]],
                flow={'INITIAL':initial, 'BELL':full, 'FINAL_HOME':full,
                      'FINAL_BACK':full, 'FOURTH_CORNER':initial, 'INITIATIVE':2,
                      'ATTACK_ORDER':[4,1,5]})


def observed(aspect, value, *, source='video', complete=True):
    return dict(race_id=RACE, aspect=aspect, observed=value, source=source,
                complete=complete, receipt=f'{source}-{aspect}')


def completed(winning=(5,3,1)):
    return dict(race_id=RACE, winning_triples=[list(winning)])


def compare(forecast, order, observations, *, verify_forecast=lambda _: True, verify_order=lambda _: True):
    return pdca.compare_race_development(race_id=RACE, starters=STARTERS, forecast=forecast,
        order=order, observations=observations, verify_forecast=verify_forecast,
        verify_order=verify_order,
        verify_observation=lambda o: o['receipt']==f"{o['source']}-{o['aspect']}")


class DevelopmentComparisonTest(unittest.TestCase):
    def test_ordinary_hit_can_have_independently_disproved_race_flow(self):
        result=compare(predicted(),completed(),[observed('INITIAL',[2,7],complete=False)])
        self.assertTrue(result['placing']['hit'])
        self.assertEqual(result['grade'],'B')
        self.assertEqual(result['flow']['aspects']['INITIAL']['state'],'different')
        self.assertEqual(result['flow']['aspects']['BELL']['state'],'unobserved')

    def test_incomplete_coverage_has_zero_flow_credit_and_still_scores_placing(self):
        forecast=predicted()
        forecast['flow']={}
        result=compare(forecast,completed(),[observed('INITIAL',[5,3,4,6,1,2,7])])
        self.assertEqual(result['grade'],'E')
        self.assertEqual(result['placing']['matched_points'],1)
        self.assertTrue(result['placing']['formal'])
        self.assertEqual(result['flow']['aspects']['INITIAL']['state'],'forecast_missing')

    def test_complete_agreement_and_clear_mismatch_distinguish_a_c_d(self):
        forecast=predicted()
        full=[observed(key,value) for key,value in forecast['flow'].items()]
        self.assertEqual(compare(forecast,completed(),full)['grade'],'A')
        self.assertEqual(compare(forecast,completed((4,5,3)),full)['grade'],'C')
        full[-1]=observed('ATTACK_ORDER',[1,4,5])
        self.assertEqual(compare(forecast,completed((4,5,3)),full)['grade'],'D')

    def test_conversation_case_cannot_count_as_frozen_even_if_placing_is_right(self):
        forecast=predicted()
        forecast['scope']='conversation_reference'
        forecast.pop('sealed_at')
        result=compare(forecast,completed(),[observed('INITIAL',[2],source='user',complete=False)])
        self.assertTrue(result['placing']['hit'])
        self.assertFalse(result['placing']['formal'])
        self.assertIsNone(result['grade'])
        self.assertEqual(result['reference_grade'],'B')
        self.assertEqual(result['reference_flow']['aspects']['INITIAL']['sources'], ['user'])
        self.assertEqual(result['placing']['hit_rank'], 1)

    def test_unverified_or_conflicting_evidence_stays_held(self):
        forecast=predicted()
        a=observed('INITIATIVE',2)
        b=observed('INITIATIVE',4,source='article')
        duplicate=deepcopy(a)
        duplicate['receipt']='unchecked'
        result=compare(forecast,completed(),[a,b,duplicate])
        self.assertEqual(result['grade'],'E')
        self.assertEqual(result['flow']['aspects']['INITIATIVE']['state'],'conflict')
        self.assertEqual(result['flow']['unverified_observations'],1)
        result=compare(forecast,completed(),[a],verify_order=lambda _: False)
        self.assertIsNone(result['placing']['hit'])
        self.assertIsNone(result['grade'])

    def test_partial_attack_observation_does_not_invent_an_order_disagreement(self):
        result=compare(predicted(),completed(),[observed('ATTACK_ORDER',[4,5],complete=False)])
        self.assertEqual(result['grade'],'E')
        self.assertEqual(result['flow']['aspects']['ATTACK_ORDER']['state'],'partial_match')
        result=compare(predicted(),completed(),[observed('ATTACK_ORDER',[5,4],complete=False)])
        self.assertEqual(result['grade'],'B')

    def test_late_or_unverified_origins_cannot_score_as_formal(self):
        forecast=predicted()
        forecast['sealed_at']=JST_CUTOFF
        for candidate,verifier in ((forecast,lambda _: True),(predicted(),lambda _: False)):
            result=compare(candidate,completed(),[],verify_forecast=verifier)
            self.assertIsNone(result['placing']['hit'])
            self.assertFalse(result['placing']['formal'])
            self.assertIsNone(result['grade'])

    def test_observation_cannot_refer_to_another_race_or_unlisted_car(self):
        for evidence in (dict(observed('INITIAL',[9]),complete=False),
                         dict(observed('INITIATIVE',4),race_id='202611252612')):
            with self.assertRaises(pdca.ForwardComparisonError):
                compare(predicted(),completed(),[evidence])


if __name__=='__main__':
    unittest.main()
