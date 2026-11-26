"""Synthetic coverage for projections tied to published KEIRIN tickets."""

from datetime import datetime
import unittest

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_public_forecasts as public
from race_ai import keirin_public_forecast_details as details
from tests.test_keirin_result_unread_racecard import RACE_ID, conditional_b, kdreams_card, snapshot


AT = datetime.fromisoformat('2030-01-15T09:01:00+09:00')
ASSESS_AT = datetime.fromisoformat('2030-01-15T09:20:00+09:00')
STARTERS = (1, 2, 3, 4, 5, 6, 7)
POINTS = {1: 103, 2: 101, 3: 91, 4: 92, 5: 89, 6: 72, 7: 72}
SCHEDULED = dict(race_id=RACE_ID, starters=[{'car': car} for car in STARTERS],
                 source_observed_at='2030-01-15T09:00:00+09:00', official_cutoff_at='2030-01-15T09:10:00+09:00')


def ordinary_snapshot():
    value = snapshot(kdreams_card(cars=STARTERS, points=POINTS,
                                  formation=(1, 2, 3, 'space', 4, 5, 'space', 6, 7)))
    value['riders'][3]['style'] = 'ALLROUND'
    value['riders'][5]['style'] = 'NIGE'
    return value


def contested_snapshot():
    raw = kdreams_card(cars=STARTERS, points=POINTS, formation=(
        1, 'bracket_open', (2, '競り'), (3, '競り'), 'bracket_close',
        'bracket_open', (4, '競り'), (5, '競り'), 'bracket_close', 'space', 6, 7,
    ))
    return snapshot(raw), conditional_b(raw)


class PublicForecastDetailTests(unittest.TestCase):
    def test_exact_ranked_tickets_and_real_phase_orders(self):
        value = ordinary_snapshot()
        research = public.project_research_race(value, SCHEDULED, generated_at=AT)
        result = details.project_race(value, SCHEDULED, research, assessed_at=ASSESS_AT)
        analysis = model.generate_evidence_analysis(value)
        for arm in ('a', 'b'):
            self.assertEqual(result[arm]['tickets'], research[arm])
            self.assertEqual(result[arm]['grade'], '未校正')
            self.assertIn('得点', result[arm]['reasons'][0])
            self.assertNotIn('例示選手', str(result[arm]))
            self.assertEqual([s['ticket'] for s in result[arm]['scenarios']], research[arm][:2])
            for scenario in result[arm]['scenarios']:
                self.assertEqual(len(scenario['orders']), 6)
                self.assertTrue(all(sorted(order) == list(STARTERS) for order in scenario['orders']))
                self.assertEqual(scenario['orders'][-1][:3], scenario['ticket'])
                source = min((candidate for candidate in analysis[arm.upper()]['six_phase_scenarios']
                              if candidate['projected_3ren_tan'] == scenario['ticket']),
                             key=lambda candidate: (-candidate['support_' + arm.upper()], candidate['scenario_id']))
                self.assertEqual(scenario['orders'], [phase['projected_order'] for phase in source['six_phases']])
        body = dict(schema=details.SCHEMA, day='2030-01-15', published_at=ASSESS_AT.isoformat(), races=[result])
        self.assertEqual(details.checked(body), body)
        result['a']['scenarios'][0]['orders'][2][0] = 9
        with self.assertRaises(ValueError):
            details.checked(body)

    def test_mismatched_ranking_and_chat_update_receive_no_reconstructed_detail(self):
        value = ordinary_snapshot()
        research = public.project_research_race(value, SCHEDULED, generated_at=AT)
        self.assertGreater(len(research['a']), 1)
        reordered = dict(research, a=list(reversed(research['a'])))
        self.assertIsNone(details.project_race(value, SCHEDULED, reordered, assessed_at=ASSESS_AT)['a'])
        updated = dict(race_id=RACE_ID, cutoff_at=research['cutoff_at'], starter_cars=list(STARTERS),
                       a=dict(kind='chat', registered_at=AT.isoformat(), tickets=research['a']), b=None)
        result = details.project_race(value, SCHEDULED, research, assessed_at=ASSESS_AT, update=updated)
        self.assertIsNone(result['a'])
        self.assertEqual(result['b']['tickets'], research['b'])

    def test_contest_attachments_match_exact_cases_and_keep_a_abstentions_and_unknown_orders(self):
        value, cases = contested_snapshot()
        research = public.project_research_race(value, SCHEDULED, generated_at=AT)
        public_cases = [dict(cars=case['cars'], tickets=case['tickets']['3t']) for case in cases]
        update = dict(race_id=RACE_ID, cutoff_at=research['cutoff_at'], starter_cars=list(STARTERS), a=None,
                      b=dict(kind='contested_lineup', registered_at=AT.isoformat(), hypotheses=public_cases))
        output = details.project_race(value, SCHEDULED, research, assessed_at=ASSESS_AT,
                                      update=update, contest_cases=cases)
        self.assertIsNone(output['b'])
        self.assertTrue(all(order is None for order in output['a']['scenarios'][0]['orders']))
        self.assertEqual([(case['cars'], case['tickets']) for case in output['b_conditions']],
                         [(case['cars'], case['tickets']) for case in public_cases])
        self.assertEqual(output['b_conditions'][1]['tickets'], [])
        self.assertEqual(output['b_conditions'][1]['scenarios'], [])
        self.assertIn('単独', output['b_conditions'][0]['condition'])
        changed = dict(update, b=dict(update['b'], hypotheses=list(reversed(public_cases))))
        mismatch = details.project_race(value, SCHEDULED, research, assessed_at=ASSESS_AT,
                                        update=changed, contest_cases=cases)
        self.assertNotIn('b_conditions', mismatch)
        self.assertEqual(mismatch['a']['tickets'], research['a'])
