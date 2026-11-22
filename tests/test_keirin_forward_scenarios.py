"""Forward paths and independent markets; synthetic riders, no race results."""
from collections import defaultdict
from copy import deepcopy
import unittest

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_research_stability as stability
from tests.test_keirin_evidence_selection import fixture


def identical_solo_fixture():
    snapshot = fixture()
    for rider in snapshot['riders']:
        rider.update(competition_points=90, win_rate=20, top2_rate=40,
                     top3_rate=60, mark_rank='UNMARKED', h_count=8,
                     b_count=10, S=0, nige=5, makuri=3, sashi=4, mark=4,
                     style='ALLROUND', comment='自力。')
    snapshot['line_groups'] = [[r['car']] for r in snapshot['riders']]
    return snapshot


def dominant_forward_analysis():
    # Reuse the pre-existing dominant case from EvidenceSelection. These are
    # invented riders, not values fitted to a target-day race or outcome.
    snapshot = fixture()
    for rider in snapshot['riders']:
        car = rider['car']
        rider['competition_points'] = {1:100, 2:90, 3:80}.get(car, 50)
        rider['win_rate'] = {1:90, 2:1, 3:0}.get(car, 0)
        rider['top2_rate'] = {1:95, 2:80, 3:1}.get(car, 0)
        rider['top3_rate'] = {1:100, 2:90, 3:80}.get(car, 0)
    analysis = model.generate_evidence_analysis(snapshot)
    analysis.update(race_id='209901016201', generated_at='2099-01-01T01:00:00+09:00',
                    missing_model_features=[], line_warnings=[], condition_evidence=[])
    return analysis


class ForwardScenarioRegression(unittest.TestCase):
    def test_forward_high_is_reachable_from_a_generated_dominant_field(self):
        out = stability.assess_research_analysis(dominant_forward_analysis())
        self.assertEqual({key: value['grade'] for key, value in out['evaluations'].items()},
                         {'A_3t':'高', 'A_2t':'高', 'B_3t':'高', 'B_2t':'高'})
        self.assertEqual(out['rules_version'], 'forward-scenario-stability-20261122-v2')
        for key, entry in out['evaluations'].items():
            reasons = {reason['code']: reason['message'] for reason in entry['reasons']}
            self.assertNotIn('FORWARD_METHOD_NOT_CALIBRATED', reasons)
            self.assertIn('40%' if key.endswith('3t') else '55%', reasons['CANDIDATE_CONCENTRATION'])
            self.assertIn('15%' if key.endswith('3t') else '25%', reasons['CANDIDATE_CONCENTRATION'])
            self.assertIn('的中率', reasons['CANDIDATE_CONCENTRATION'])

    def test_forward_ticket_count_changes_do_not_raise_or_lower_confidence(self):
        analysis = model.generate_evidence_analysis(fixture())
        analysis.update(race_id='209901016201', generated_at='2099-01-01T01:00:00+09:00',
                        missing_model_features=[], line_warnings=[], condition_evidence=[])
        original = stability.assess_research_analysis(analysis)
        for include_all in (False, True):
            changed = deepcopy(analysis)
            for arm in ('A', 'B'):
                for market, field in (('3t', 'ranked_tickets'), ('2t', 'ranked_2ren_tan')):
                    pool = changed[arm]['candidate_tickets'][market]
                    chosen = pool if include_all else pool[:1]
                    changed[arm][field] = deepcopy(chosen)
                    changed[arm]['point_count_' + market] = len(chosen)
                    changed[arm]['markets'][market]['tickets'] = deepcopy(chosen)
                    changed[arm]['markets'][market]['point_count'] = len(chosen)
            self.assertEqual(original, stability.assess_research_analysis(changed))

    def test_forward_high_keeps_missing_condition_and_abstention_restrictions(self):
        original = dominant_forward_analysis()
        self.assertTrue(all(e['rank'] == 3 for e in
                            stability.assess_research_analysis(original)['evaluations'].values()))
        for field, value, expected_rank in (
            ('condition_evidence', [{'fact':'Synthetic pre-race caution'}], 2),
            ('missing_model_features', ['riders.1.competition_points'], 0),
            ('line_warnings', ['Synthetic unresolved source conflict'], 0),
        ):
            changed = deepcopy(original)
            changed[field] = value
            with self.subTest(field=field):
                self.assertTrue(all(e['rank'] == expected_rank for e in
                                    stability.assess_research_analysis(changed)['evaluations'].values()))
        held = deepcopy(original)
        held['A']['selection']['3t']['recommendation'] = 'ABSTAIN_INSUFFICIENT_SEPARATION'
        out = stability.assess_research_analysis(held)['evaluations']
        self.assertEqual(out['A_3t']['rank'], 1)
        self.assertEqual(out['A_2t']['rank'], 3)
        self.assertEqual(out['B_3t']['rank'], 3)
        self.assertEqual(out['B_2t']['rank'], 3)

    def test_same_tactical_branch_cannot_rewrite_corner_to_fit_ticket(self):
        scenarios = model.generate_evidence_analysis(fixture())["B"]["six_phase_scenarios"]
        prefixes = defaultdict(set)
        for scenario in scenarios:
            key = (scenario["branch_kind"], scenario["attacking_car"], scenario["challenger_car"])
            prefixes[key].add(tuple(tuple(p["projected_order"])
                                    for p in scenario["six_phases"][:-1]))
        self.assertTrue(prefixes)
        self.assertTrue(all(len(orders) == 1 for orders in prefixes.values()),
                        "one tactical branch was given different pre-goal orders to fit tickets")

    def test_goal_is_replayable_from_corner_using_evidenced_adjacent_passes(self):
        scenarios = model.generate_evidence_analysis(fixture())["B"]["six_phase_scenarios"]
        for scenario in scenarios:
            with self.subTest(scenario=scenario["scenario_id"]):
                transitions = scenario.get("finish_transitions")
                self.assertIsNotNone(transitions, "goal lacks a movement trace from the corner")
                order = list(scenario["six_phases"][-2]["projected_order"])
                for event in transitions:
                    overtaker, passed = event["overtaker"], event["passed"]
                    i = order.index(overtaker)
                    self.assertGreater(i, 0)
                    self.assertEqual(order[i - 1], passed)
                    self.assertTrue(event["evidence"])
                    order[i - 1], order[i] = order[i], order[i - 1]
                self.assertEqual(order, scenario["six_phases"][-1]["projected_order"])
                self.assertEqual(order[:3], scenario["projected_3ren_tan"])

    def test_third_candidate_count_cannot_create_pair_support(self):
        base = [dict(scenario_id="first", projected_3ren_tan=[1, 2, 3],
                     support_A=.25, support_B=.25, pair_support_A=1., pair_support_B=1.,
                     rationale=["pair evidence is unchanged"]),
                dict(scenario_id="other", projected_3ren_tan=[3, 4, 5],
                     support_A=.8, support_B=.8, pair_support_A=.8, pair_support_B=.8,
                     rationale=["other pair"]),
                dict(scenario_id="weak", projected_3ren_tan=[5, 4, 3],
                     support_A=.1, support_B=.1, pair_support_A=.1, pair_support_B=.1,
                     rationale=["weak pair"])]
        expanded = deepcopy(base)
        for third in (4, 5, 6):
            expanded.append(dict(base[0], scenario_id=f"third-{third}",
                                 projected_3ren_tan=[1, 2, third]))
        for arm in ("A", "B"):
            before = model.select_scenario_markets(base, arm=arm)
            after = model.select_scenario_markets(expanded, arm=arm)
            self.assertEqual(before["ranked_2ren_tan"], after["ranked_2ren_tan"])
            self.assertEqual(before["ticket_evidence"]["2t"][0]["support"], 1.)
            self.assertEqual(after["ticket_evidence"]["2t"][0]["support"], 1.)

    def test_equal_candidates_are_held_without_arbitrary_truncation(self):
        rows = [dict(ticket=[a, b, 6], support=1., scenario_ids=[f"{a}-{b}"],
                     reasons=["equal evidence"])
                for a in range(1, 6) for b in range(1, 6) if a != b]
        selected, meta = model.select_evidence_tickets(rows, market="3t")
        self.assertEqual(selected, [])
        self.assertEqual(meta["candidate_count"], 20)
        self.assertEqual(meta["held_count"], 20)
        self.assertEqual(meta["recommendation"], "ABSTAIN_INSUFFICIENT_SEPARATION")

    def test_supported_group_can_still_exceed_twelve(self):
        rows = [dict(ticket=[a, b, 6], support=1., scenario_ids=[f"{a}-{b}"],
                     reasons=["strong branch"])
                for a in range(1, 6) for b in range(1, 6) if a != b]
        rows.append(dict(ticket=[6, 1, 2], support=.1, scenario_ids=["weak"],
                         reasons=["weak alternative"]))
        selected, meta = model.select_evidence_tickets(rows, market="3t")
        self.assertEqual(len(selected), 20)
        self.assertEqual(meta["point_count"], 20)

    def test_identical_solo_riders_cannot_be_ranked_by_car_number(self):
        snapshot = identical_solo_fixture()
        out = model.generate_evidence_analysis(snapshot)
        for arm in ('A', 'B'):
            self.assertEqual(out[arm]['ranked_tickets'], [])
            self.assertEqual(out[arm]['ranked_2ren_tan'], [])
            self.assertTrue(out[arm]['candidate_tickets']['3t'])
            self.assertEqual(out[arm]['selection']['3t']['abstention_code'],
                             'INDISTINGUISHABLE_RIDER_EVIDENCE')
        renamed = deepcopy(snapshot)
        for rider in renamed['riders']:
            rider['car'] = 8 - rider['car']
        renamed['line_groups'] = [[8 - g[0]] for g in snapshot['line_groups']]
        after = model.generate_evidence_analysis(renamed)
        for arm in ('A', 'B'):
            self.assertEqual(after[arm]['ranked_tickets'], [])
            self.assertEqual(after[arm]['ranked_2ren_tan'], [])

    def test_irrelevant_comment_or_style_cannot_break_solo_abstention(self):
        baseline = model.generate_evidence_analysis(identical_solo_fixture())
        for change in ({'comment': ''}, {'style': 'NIGE'}):
            with self.subTest(change=change):
                snapshot = identical_solo_fixture()
                snapshot['riders'][0].update(change)
                out = model.generate_evidence_analysis(snapshot)
                # The observable evidence differences are preserved, but do
                # not change any effective role or computed scenario support.
                if 'comment' in change:
                    self.assertFalse(out['feature_audit']['riders'][0]['comment_attack_intent'])
                    self.assertTrue(out['feature_audit']['riders'][0]['explicit_attack'])
                for arm in ('A', 'B'):
                    weights = lambda packet: [(s['scenario_id'], s['support_' + arm],
                                              s['pair_support_' + arm])
                                             for s in packet['six_phase_scenarios']]
                    self.assertEqual(weights(out[arm]), weights(baseline[arm]))
                    self.assertEqual(out[arm]['ranked_tickets'], [])
                    self.assertEqual(out[arm]['ranked_2ren_tan'], [])
                for rider in snapshot['riders']:
                    rider['car'] = 8 - rider['car']
                snapshot['line_groups'] = [[8 - g[0]] for g in snapshot['line_groups']]
                renamed = model.generate_evidence_analysis(snapshot)
                for arm in ('A', 'B'):
                    self.assertEqual(renamed[arm]['ranked_tickets'], [])
                    self.assertEqual(renamed[arm]['ranked_2ren_tan'], [])

    def test_ability_only_has_no_invented_attacker_or_forward_position_claim(self):
        snapshot = fixture()
        snapshot['line_groups'] = None
        out = model.generate_evidence_analysis(snapshot)
        for scenario in out['A']['six_phase_scenarios']:
            self.assertIsNone(scenario['attacking_car'])
            self.assertEqual(scenario['branch_kind'], 'ABILITY_ONLY')
            for phase in scenario['six_phases'][:-1]:
                self.assertIsNone(phase['projected_order'])
        self.assertFalse(any('位置を先に決め' in reason for reason in out['A']['rationale']))
        self.assertFalse(any('局所遷移から' in reason for reason in out['A']['rationale']))
        self.assertTrue(any('並び未取得' in reason for reason in out['A']['rationale']))

    def test_hold_does_not_gain_confidence_from_a_smaller_candidate_universe(self):
        scenarios = [dict(scenario_id="a", projected_3ren_tan=[1, 2, 3],
                          support_A=1., support_B=1., pair_support_A=1., pair_support_B=1.),
                     dict(scenario_id="b", projected_3ren_tan=[1, 2, 4],
                          support_A=1., support_B=1., pair_support_A=1., pair_support_B=1.)]
        packet = dict(six_phase_scenarios=scenarios, selection={
            "3t": {"recommendation": "ABSTAIN_INSUFFICIENT_SEPARATION"},
            "2t": {"recommendation": "CONDITIONAL_CANDIDATES"}})
        analysis = dict(race_id="209901016201", generated_at="2099-01-01T01:00:00+09:00",
                        line_warnings=[], missing_model_features=[], A=packet, B=deepcopy(packet))
        out = stability.assess_research_analysis(analysis)
        self.assertEqual(out["evaluations"]["A_3t"]["grade"], "低")
        self.assertEqual(out["evaluations"]["B_3t"]["grade"], "低")

    def test_legacy_confidence_distribution_keeps_its_original_contract(self):
        scenarios = [dict(projected_3ren_tan=[1, 2, 3], support_A=2.),
                     dict(projected_3ren_tan=[1, 2, 4], support_A=1.),
                     dict(projected_3ren_tan=[4, 2, 1], support_A=1.)]
        self.assertEqual(stability._distribution(scenarios, 'A', 2),
                         {(1, 2): .75, (4, 2): .25})


if __name__ == "__main__":
    unittest.main()
