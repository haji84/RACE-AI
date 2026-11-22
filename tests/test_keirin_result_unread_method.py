"""Regressions for corrections that must not admit target-result data."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

g=module('unread_current',ROOT/'scripts/keirin_generate_result_unread_analysis.py')
c=module('stability_current',ROOT/'race_ai/keirin_research_stability.py')

class CurrentMethodEvidenceTests(unittest.TestCase):
    def test_results_are_rejected_at_any_input_depth(self):
        for field in ('official_result','results','payout','current_meeting_results'):
            with self.assertRaisesRegex(ValueError,'RESULT_FIELD_PRESENT'):
                g.check_no_result_fields({'riders':[{'nested':{field:[]}}]})

    def test_zero_points_are_unknown_but_zero_win_rate_is_real(self):
        riders=[dict(number=n,name='Synthetic'+str(n),score=0 if n==1 else 80+n,
            style='逃',win_rate=0,H=0,B=0,S=0,nige=0,makuri=0,sashi=0,mark=0,
            top2_rate=0,top3_rate=0,source_tip='',gear='3.92') for n in range(1,6)]
        rows=g.normalized_riders({'riders':riders})
        self.assertIsNone(rows[0]['competition_points'])
        self.assertEqual(rows[0]['win_rate'],0)
        self.assertIsNone(rows[0]['recent_form_score'])

    def test_more_tickets_and_repeated_stories_cannot_raise_grade(self):
        scenarios=[dict(scenario_id='a',projected_3ren_tan=[1,2,3],support_A=2,support_B=2),
                   dict(scenario_id='b',projected_3ren_tan=[1,2,4],support_A=1,support_B=1),
                   dict(scenario_id='c',projected_3ren_tan=[4,2,1],support_A=1,support_B=1)]
        analysis=dict(race_id='209901016201',generated_at='2099-01-01T01:00:00+09:00',
            line_warnings=[],missing_model_features=[],condition_evidence=[],
            A=dict(six_phase_scenarios=scenarios,ranked_tickets=[[1,2,3]]),
            B=dict(six_phase_scenarios=scenarios,ranked_tickets=[[1,2,3]]))
        before=c.assess_research_analysis(analysis)
        changed=copy.deepcopy(analysis)
        for arm in ('A','B'):
            changed[arm]['ranked_tickets'] += [[1,2,4],[4,2,1]]
            changed[arm]['six_phase_scenarios'] += [dict(scenarios[0],scenario_id='reworded')]
        after=c.assess_research_analysis(changed)
        self.assertEqual(before['evaluations'],after['evaluations'])

    def test_condition_filter_uses_observed_car_not_hardcoded_race(self):
        analysis=dict(race_id='209901016201',generated_at='2099-01-01T01:00:00+09:00',
            form_and_fall=[dict(car=7,name='Synthetic',confirmed_facts={})],
            A=dict(ranked_tickets=[[7,1,2],[1,2,7]],ranked_2ren_tan=[[7,1],[1,2]]),
            B=dict(ranked_tickets=[[7,2,1],[2,7,1]],ranked_2ren_tan=[[7,2],[2,7]]))
        observation=dict(race_id='209901016201',car=7,name='Synthetic',
            fact='本人は痛みが残ると説明。',judgement='影響は未確定。',
            possible_ticket_impact='痛みが走りに影響する場合の頭固定を避ける。',
            evidence_type='synthetic self report',source_url='https://example.invalid/pre-race',
            captured_at='2099-01-01T00:00:00+09:00')
        g.apply_condition_observations(analysis,[observation])
        self.assertEqual(analysis['A']['ranked_tickets'],[[7,1,2],[1,2,7]])
        self.assertEqual(analysis['condition_adjusted']['A']['ranked_tickets'],[[1,2,7]])
        self.assertIn('7番',analysis['condition_adjusted']['assumption'])

    def test_condition_car_name_must_match(self):
        analysis=dict(race_id='209901016201',generated_at='2099-01-01T01:00:00+09:00',
            form_and_fall=[dict(car=1,name='SyntheticA',confirmed_facts={})])
        with self.assertRaisesRegex(ValueError,'CONDITION_COMMENT_IDENTITY_MISMATCH'):
            g.apply_condition_observations(analysis,[dict(race_id='209901016201',car=1,name='SyntheticB')])

    def test_condition_state_checks_both_independent_markets(self):
        observation=dict(race_id='209901016201',car=1,name='Synthetic',
            fact='本人は痛みが残ると説明。',judgement='影響は未確定。',
            possible_ticket_impact='痛みが影響する場合の条件付き案。',
            evidence_type='synthetic self report',source_url='https://example.invalid/pre-race',
            captured_at='2099-01-01T00:00:00+09:00')
        cases=[([],[[1,2],[2,3]],'GENERATED_CONDITIONAL_REFERENCE'),
               ([[1,2,3],[2,3,4]],[],'GENERATED_CONDITIONAL_REFERENCE'),
               ([[1,2,3]],[[1,2]],'NO_TICKETS_UNDER_CONDITION')]
        for triples,pairs,state in cases:
            with self.subTest(triples=triples,pairs=pairs):
                packet=dict(ranked_tickets=triples,ranked_2ren_tan=pairs)
                analysis=dict(race_id='209901016201',generated_at='2099-01-01T01:00:00+09:00',
                    form_and_fall=[dict(car=1,name='Synthetic',confirmed_facts={})],
                    A=copy.deepcopy(packet),B=copy.deepcopy(packet))
                g.apply_condition_observations(analysis,[observation])
                for arm in ('A','B'):
                    self.assertEqual(analysis['condition_adjusted'][arm]['state'],state)
                    self.assertEqual(analysis[arm],packet)

if __name__=='__main__':unittest.main()
