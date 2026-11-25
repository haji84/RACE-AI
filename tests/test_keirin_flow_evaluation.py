"""Behavior of independent flow scoring; all riders here are invented."""
from copy import deepcopy
import unittest

from race_ai import keirin_flow_evaluation as flow


PHASES = ('INITIAL', 'BELL', 'FINAL_HOME', 'FINAL_BACK', 'FOURTH_CORNER')
AT = '2099-01-01T12:00:00+09:00'


def prediction():
    return dict(phase_orders={p: [1, 2, 3] for p in PHASES},
                leaders={p: 1 for p in ('BELL', 'FINAL_HOME', 'FINAL_BACK')},
                attack_order=[dict(car=1, attempt=1), dict(car=3, attempt=1)])


def fact(metric, value, phase='RACE', kind='VIDEO_OBSERVATION', complete=True):
    return dict(metric=metric, phase=phase, value=value, complete=complete,
                source=dict(kind=kind, reference='synthetic:observation', recorded_at=AT,
                            sha256='a' * 64 if kind != 'USER_OBSERVATION' else None))


def observations():
    p = prediction()
    return ([fact('phase_order', order, phase) for phase, order in p['phase_orders'].items()]
            + [fact('leader', car, phase) for phase, car in p['leaders'].items()]
            + [fact('attack_order', p['attack_order'])])


class FlowEvaluationTests(unittest.TestCase):
    def evaluate(self, expected=None, facts=None, hit=True):
        return flow.evaluate_case(prediction() if expected is None else expected,
                                  observations() if facts is None else facts,
                                  starters={1, 2, 3}, result_hit=hit, observed_at=AT)

    def test_finish_and_flow_are_independent_four_outcomes(self):
        for hit, different, want in [(True, False, 'A'), (True, True, 'B'),
                                      (False, False, 'C'), (False, True, 'D')]:
            with self.subTest(want=want):
                facts = observations()
                if different:
                    facts[0]['value'] = [3, 2, 1]
                result = self.evaluate(facts=facts, hit=hit)
                self.assertEqual(result['classification'], want)
                self.assertEqual(result['result_hit'], hit)
                self.assertEqual(result['confirmed_metrics']['phase_order']['compared'], 5)

    def test_one_matching_checkpoint_cannot_prove_whole_flow(self):
        out = self.evaluate(facts=[fact('phase_order', [1, 2, 3], 'FINAL_BACK')])
        self.assertEqual(out['classification'], 'E')
        self.assertFalse(out['confirmed_flow_complete'])
        self.assertEqual(out['confirmed_metrics']['phase_order']['matched'], 1)
        self.assertEqual(out['confirmed_metrics']['phase_order']['compared'], 1)
        self.assertEqual(self.evaluate(facts=[])['classification'], 'E')

    def test_confirmed_mismatch_is_sufficient_even_if_other_phases_are_missing(self):
        out = self.evaluate(facts=[fact('leader', 3, 'BELL')])
        self.assertEqual(out['classification'], 'B')
        self.assertFalse(out['confirmed_flow_complete'])

    def test_sparse_front_and_initiative_claims_need_no_invented_positions_or_timing(self):
        expected = dict(initial_front=2, initiative=1)
        facts = [fact('front_runner', 3, 'INITIAL', 'USER_OBSERVATION'),
                 fact('initiative', 2, kind='USER_OBSERVATION')]
        out = self.evaluate(expected=expected, facts=facts)
        self.assertEqual((out['classification'], out['provisional_classification']), ('E', 'B'))
        self.assertEqual(out['provisional_metrics']['front_runner']['matched'], 0)
        self.assertEqual(out['provisional_metrics']['initiative']['compared'], 1)

    def test_user_report_stays_provisional_and_ai_is_not_actual_flow(self):
        facts = [fact('leader', 3, 'BELL', 'USER_OBSERVATION')]
        out = self.evaluate(facts=facts)
        self.assertEqual((out['classification'], out['provisional_classification']), ('E', 'B'))
        self.assertEqual(out['confirmed_metrics']['leader']['compared'], 0)
        ai = self.evaluate(facts=[fact('leader', 3, 'BELL', 'AI_ESTIMATE')])
        self.assertEqual((ai['classification'], ai['provisional_classification']), ('E', 'E'))

    def test_duplicate_sources_do_not_inflate_denominator_and_conflicts_hold(self):
        facts = [fact('leader', 1, 'BELL'), fact('leader', 1, 'BELL', 'PUBLISHED_REPORT')]
        out = self.evaluate(facts=facts)
        self.assertEqual(out['confirmed_metrics']['leader']['compared'], 1)
        facts[1]['value'] = 3
        out = self.evaluate(facts=facts)
        self.assertEqual(out['classification'], 'E')
        self.assertEqual(out['confirmed_metrics']['leader']['conflicting'], 1)
        self.assertEqual(out['confirmed_metrics']['leader']['compared'], 0)

    def test_missing_original_flow_is_unknown_not_a_reconstructed_prediction(self):
        out = self.evaluate(expected={})
        self.assertEqual((out['classification'], out['provisional_classification']), ('E', 'E'))
        self.assertEqual(out['confirmed_metrics']['phase_order']['missing_prediction'], 5)
        out = self.evaluate(hit=None)
        self.assertIsNone(out['classification'])
        self.assertIsNone(out['result_hit'])

    def test_partial_attack_order_is_subsequence_and_repeated_acceleration_has_identity(self):
        p = prediction()
        p['attack_order'] = [dict(car=1, attempt=1), dict(car=3, attempt=1), dict(car=1, attempt=2)]
        partial = [fact('attack_order', [dict(car=1, attempt=1), dict(car=1, attempt=2)], complete=False)]
        out = self.evaluate(expected=p, facts=partial)
        self.assertEqual(out['confirmed_metrics']['attack_order']['matched'], 1)
        self.assertEqual(out['classification'], 'E')
        partial[0]['value'] = [dict(car=3, attempt=1), dict(car=1, attempt=1)]
        self.assertEqual(self.evaluate(expected=p, facts=partial)['classification'], 'B')

    def test_empty_or_single_partial_sequence_cannot_inflate_order_observation_count(self):
        for value in ([], [dict(car=1, attempt=1)]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.evaluate(facts=[fact('attack_order', value, complete=False)])
        for events in ([dict(car=1, attempt=2), dict(car=1, attempt=1)],
                       [dict(car=1, attempt=1), dict(car=1, attempt=1)]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                self.evaluate(facts=[fact('attack_order', events)])

    def test_original_front_claim_must_agree_with_its_original_initial_order(self):
        p = prediction()
        p['initial_front'] = 2
        with self.assertRaises(ValueError):
            self.evaluate(expected=p)

    def test_goal_order_never_substitutes_for_flow_and_bad_rosters_are_rejected(self):
        for invalid in [fact('phase_order', [1, 2, 3], 'GOAL'),
                        fact('phase_order', [1, 1, 3], 'INITIAL'),
                        fact('phase_order', [1, 2], 'INITIAL'),
                        fact('leader', 9, 'BELL'), fact('leader', True, 'BELL')]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.evaluate(facts=[invalid])

    def test_observation_source_and_clock_are_bound_and_inputs_stay_unchanged(self):
        p, facts = prediction(), observations()
        saved = deepcopy((p, facts))
        self.evaluate(expected=p, facts=facts)
        self.assertEqual((p, facts), saved)
        for invalid in [dict(kind='VIDEO_OBSERVATION', sha256=None),
                        dict(kind='UNKNOWN'), dict(recorded_at='2099-01-02T00:00:00Z')]:
            changed = deepcopy(facts)
            changed[0]['source'].update(invalid)
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.evaluate(facts=changed)


if __name__ == '__main__':
    unittest.main()
