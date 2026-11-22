"""Forward paths and independent markets; synthetic riders, no race results."""
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_confidence as confidence
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


def hot_forward_snapshot():
    """Synthetic single-line case; generated tickets/support remain untouched."""
    snapshot = fixture()
    snapshot['line_groups'] = [[1, 2, 3, 4, 5, 6, 7]]
    for rider in snapshot['riders']:
        car = rider['car']
        strong = car in (1, 2)
        rider.update(competition_points=90 if strong else 60 if car == 3 else 50,
            win_rate=40 if strong else 0, top2_rate=70 if strong else 30 if car == 3 else 0,
            top3_rate=90 if strong else 75 if car == 3 else 1, mark_rank='UNMARKED',
            h_count=0, b_count=0, nige=0, makuri=1 if car == 1 else 0,
            sashi=7 if car == 2 else 1 if car == 3 else 0,
            mark=5 if car in (2, 3) else 0,
            style='NIGE' if car == 1 else 'MARK',
            comment='自力。' if car == 1 else '前の選手へ。')
    return snapshot


def hot_forward_analysis():
    analysis = model.generate_evidence_analysis(hot_forward_snapshot())
    analysis.update(race_id='209901016201', generated_at='2099-01-01T13:00:00+09:00',
                    missing_model_features=[], line_warnings=[], condition_evidence=[])
    return analysis


def coherence_analysis():
    """Hand-counted synthetic paths, independent of any selected ticket set.

    Top two winners and top four pairs each carry .95 of this fixed pool.
    All six triples carry 1.0. The ordinary selection covers the first four
    outcomes (.95), including the highest-weight counterattack.
    """
    rows = [
        ('main', 'HOLD', [1, 2, 3], .45),
        ('counter', 'COUNTER', [1, 3, 2], .40),
        ('second-a', 'HOLD', [2, 1, 3], .05),
        ('second-b', 'HOLD', [2, 3, 1], .05),
        ('minor-a', 'HOLD', [4, 5, 1], .025),
        ('minor-b', 'HOLD', [5, 4, 1], .025),
    ]
    phases = ('INITIAL', 'BELL', 'FINAL_HOME', 'FINAL_BACK', 'FOURTH_CORNER', 'GOAL')
    scenarios = []
    for sid, kind, goal, weight in rows:
        order = goal + [car for car in range(1, 8) if car not in goal]
        scenarios.append(dict(scenario_id=sid, tactical_branch_id=sid,
            branch_kind=kind, projected_3ren_tan=list(goal),
            six_phases=[dict(phase=phase, projected_order=list(order),
                projected_top3=list(goal), hypothesis_actions=['SYNTHETIC_HYPOTHESIS'],
                actual_rider_position_video_verified=False) for phase in phases],
            support_A=weight, support_B=weight,
            pair_support_A=weight, pair_support_B=weight,
            relative_research_weight=weight))
    arm = dict(six_phase_scenarios=scenarios,
               ranked_tickets=[list(row[2]) for row in rows[:4]],
               ranked_2ren_tan=[list(row[2][:2]) for row in rows[:4]],
               selection={market: {'recommendation':'CONDITIONAL_CANDIDATES'}
                          for market in ('3t','2t')})
    return dict(race_id='209901016201', generated_at='2099-01-01T13:00:00+09:00',
        source_as_of='2099-01-01T12:30:00+09:00',
        published_cutoff_at='2099-01-01T12:00:00+09:00',
        created_after_published_cutoff=True,
        timing_label='締切後作成・結果欄未参照の参考分析',
        method={'id':'forward-phase-independent-pair-selection-20261122'},
        missing_model_features=[], line_warnings=[], condition_evidence=[],
        A=deepcopy(arm), B=deepcopy(arm))


def spread_thirds_analysis():
    """Six selected triples; top four carry .82, but four pairs cover 1.0."""
    analysis = coherence_analysis()
    rows = [([1, 2, 3], .30), ([1, 2, 4], .25),
            ([2, 1, 3], .15), ([2, 1, 4], .12),
            ([1, 3, 4], .10), ([2, 3, 4], .08)]
    for arm in ('A', 'B'):
        for scenario, (goal, support) in zip(analysis[arm]['six_phase_scenarios'], rows):
            scenario.update(projected_3ren_tan=list(goal), support_A=support,
                support_B=support, pair_support_A=support, pair_support_B=support,
                relative_research_weight=support)
            for phase in scenario['six_phases']:
                phase['projected_order'] = goal + [car for car in range(1, 8) if car not in goal]
                phase['projected_top3'] = list(goal)
        analysis[arm]['ranked_tickets'] = [list(goal) for goal, _ in rows]
        analysis[arm]['ranked_2ren_tan'] = [[1, 2], [2, 1], [1, 3], [2, 3]]
    return analysis


class ForwardScenarioRegression(unittest.TestCase):
    def test_dominant_single_ticket_does_not_hide_uncovered_counter_branches(self):
        out = stability.assess_research_analysis(dominant_forward_analysis())
        self.assertEqual({key: value['grade'] for key, value in out['evaluations'].items()},
                         {'A_3t':'中', 'A_2t':'中', 'B_3t':'中', 'B_2t':'中'})
        self.assertEqual(out['rules_version'], 'forward-research-coherence-20261122-v4')
        for key, entry in out['evaluations'].items():
            reasons = {reason['code']: reason['message'] for reason in entry['reasons']}
            self.assertIn('MAJOR_SCENARIO_UNCOVERED', reasons)
            self.assertIn('NEXT_LEVEL_NOT_MET', reasons)
            self.assertLess(entry['metrics']['scenario_coverage'], .8)

    def test_reducing_forward_tickets_cannot_raise_confidence_or_shrink_denominator(self):
        analysis = model.generate_evidence_analysis(fixture())
        analysis.update(race_id='209901016201', generated_at='2099-01-01T01:00:00+09:00',
                        missing_model_features=[], line_warnings=[], condition_evidence=[])
        original = stability.assess_research_analysis(analysis)
        changed = deepcopy(analysis)
        for arm in ('A', 'B'):
            for field in ('ranked_tickets', 'ranked_2ren_tan'):
                changed[arm][field] = changed[arm][field][:1]
        reduced = stability.assess_research_analysis(changed)
        self.assertEqual(original['scenario_universe_sha256'], reduced['scenario_universe_sha256'])
        for key, entry in reduced['evaluations'].items():
            self.assertLessEqual(entry['rank'], original['evaluations'][key]['rank'])
            self.assertIn('scenario_coverage', entry['metrics'])
            self.assertLessEqual(entry['metrics']['scenario_coverage'],
                                 original['evaluations'][key]['metrics']['scenario_coverage'])

    def test_forward_high_keeps_missing_condition_and_abstention_restrictions(self):
        original = coherence_analysis()
        self.assertTrue(all(e['rank'] == 4 for e in
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
        self.assertEqual(out['A_2t']['rank'], 4)
        self.assertEqual(out['B_3t']['rank'], 4)
        self.assertEqual(out['B_2t']['rank'], 4)

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


class ForwardCoherenceRegression(unittest.TestCase):
    def test_historical_research_versions_keep_their_original_assessment_bytes(self):
        # Captured from main 4711b9b1 before the top-four change, using only the
        # hand-counted synthetic input above. A v3 rewrite to top four changes
        # its old hot grade and fails both the literal grade and byte digest.
        analysis = spread_thirds_analysis()
        old_analysis = deepcopy(analysis)
        old_analysis.pop('method')
        cases = [
            (stability._assess_legacy_research_analysis(old_analysis), '中',
             '6d65c067e4f7d3c2f8ae3a2c7724ae33a55bd906a849e22e4a2e903e81331b0b'),
            (stability._assess_legacy_research_analysis(analysis), '中',
             '5bbd63b660929c28d155d46ece28f688ae7dedc8107a7240c08ace422e5ab4dc'),
            (stability._assess_forward_research_analysis(
                analysis, rules_version='forward-research-coherence-20261122-v3'),
             '激アツ', 'd8546f134f7dacf53bc7390130b8c7b0346e9f35a7b13aec70941e1cc89febf6'),
        ]
        for packet, grade, digest in cases:
            with self.subTest(version=packet['rules_version']):
                self.assertEqual(packet['evaluations']['A_3t']['grade'], grade)
                raw = json.dumps(packet, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':'), allow_nan=False).encode()
                self.assertEqual(sha256(raw).hexdigest(), digest)

    def test_two_car_evaluation_is_unchanged_apart_from_null_triple_field_name(self):
        analysis = spread_thirds_analysis()
        old = stability._assess_forward_research_analysis(
            analysis, rules_version='forward-research-coherence-20261122-v3')
        new = stability.assess_research_analysis(analysis)
        for arm in ('A', 'B'):
            expected = deepcopy(old['evaluations'][arm + '_2t'])
            self.assertIsNone(expected['metrics'].pop('triple_top6_share'))
            expected['metrics']['triple_top4_share'] = None
            self.assertEqual(new['evaluations'][arm + '_2t'], expected)
            self.assertEqual(new['evaluations'][arm + '_2t']['metrics']['axis_cars'], [1, 2])

    def test_six_triples_cannot_receive_hot_when_top_four_hold_only_82_percent(self):
        analysis = spread_thirds_analysis()
        before = deepcopy(analysis)
        out = stability.assess_research_analysis(analysis)
        for arm in ('A', 'B'):
            entry = out['evaluations'][arm + '_3t']
            self.assertEqual(entry['grade'], '高')
            self.assertEqual(entry['metrics'].get('triple_top4_share'), .82)
            self.assertNotIn('triple_top6_share', entry['metrics'])
            self.assertEqual(entry['metrics']['axis_top2_share'], 1.0)
            self.assertEqual(entry['metrics']['pair_top4_share'], 1.0)
            self.assertEqual(entry['metrics']['scenario_coverage'], 1.0)
            self.assertEqual(entry['metrics']['major_uncovered_ids'], [])
            reasons = {reason['code']: reason['message'] for reason in entry['reasons']}
            self.assertIn('上位4組', reasons['PARTNER_GOAL_CONCENTRATION'])
            self.assertIn('82.0%', reasons['NEXT_LEVEL_NOT_MET'])
            self.assertIn('90.0%', reasons['NEXT_LEVEL_NOT_MET'])
            self.assertEqual(out['evaluations'][arm + '_2t']['grade'], '激アツ')
            self.assertEqual(len(analysis[arm]['ranked_tickets']), 6)
        self.assertEqual(out['rules_version'], 'forward-research-coherence-20261122-v4')
        self.assertEqual(analysis, before)

    def test_top_four_triples_must_reach_the_unchanged_90_percent_hot_boundary(self):
        cases = [([.35, .25, .20, .10, .06, .04], '激アツ', .9),
                 ([.35, .25, .20, .0999, .0601, .04], '高', .8999)]
        for supports, grade, top_four in cases:
            with self.subTest(top_four=top_four):
                analysis = spread_thirds_analysis()
                for arm in ('A', 'B'):
                    for scenario, weight in zip(analysis[arm]['six_phase_scenarios'], supports):
                        scenario.update(support_A=weight, support_B=weight)
                out = stability.assess_research_analysis(analysis)
                self.assertEqual(out['evaluations']['A_3t']['grade'], grade)
                self.assertEqual(out['evaluations']['A_3t']['metrics'].get('triple_top4_share'), top_four)
                self.assertEqual(out['evaluations']['A_2t']['grade'], '激アツ')

    def test_direct_cli_checks_shared_confidence_without_pythonpath(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/keirin_generate_result_unread_analysis.py'
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run([sys.executable, '-I', '-B', str(script), '--self-check'],
                                    cwd=cwd, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout).get('synthetic_confidence_contract'), 'passed')

    def test_unchanged_forward_generator_and_selection_reach_hot_for_both_markets(self):
        analysis = hot_forward_analysis()
        before = deepcopy(analysis)
        out = stability.assess_research_analysis(analysis)
        self.assertEqual({key: value['grade'] for key, value in out['evaluations'].items()},
                         {'A_3t':'激アツ', 'A_2t':'激アツ', 'B_3t':'激アツ', 'B_2t':'激アツ'})
        self.assertEqual(analysis, before)
        for entry in out['evaluations'].values():
            self.assertGreaterEqual(entry['metrics'].get('scenario_coverage', 0), .9)
            self.assertEqual(entry['metrics'].get('major_uncovered_ids'), [])

    def test_all_four_grades_use_whole_pool_and_actual_selection_coverage(self):
        cases = [([[1, 2, 3]], '低', .45),
                 ([[1, 2, 3], [2, 1, 3], [2, 3, 1]], '中', .55),
                 ([[1, 2, 3], [1, 3, 2]], '高', .85),
                 ([[1, 2, 3], [1, 3, 2], [2, 1, 3], [2, 3, 1]], '激アツ', .95)]
        for tickets, grade, coverage in cases:
            with self.subTest(grade=grade):
                analysis = coherence_analysis()
                analysis['A']['ranked_tickets'] = tickets
                before = deepcopy(analysis)
                out = stability.assess_research_analysis(analysis)
                self.assertEqual(out['evaluations']['A_3t']['grade'], grade)
                metrics = out['evaluations']['A_3t']['metrics']
                self.assertEqual(metrics.get('axis_top2_share'), .95)
                self.assertEqual(metrics.get('pair_top4_share'), .95)
                self.assertEqual(metrics.get('triple_top4_share'), .95)
                self.assertEqual(metrics.get('scenario_coverage'), coverage)
                self.assertEqual(analysis, before)

    def test_hot_path_never_creates_or_backdates_a_formal_assessment(self):
        analysis = coherence_analysis()
        out = stability.assess_research_analysis(analysis, assessed_at='2099-01-01T14:00:00+09:00')
        self.assertEqual(out['evaluations']['A_3t']['grade'], '激アツ')
        self.assertEqual(out['assessed_at'], '2099-01-01T14:00:00+09:00')
        self.assertEqual(out['timing_label'], analysis['timing_label'])
        self.assertFalse(out['official_pre_cutoff_assessment_created'])
        self.assertFalse(out['production_guard_modified'])
        self.assertFalse(out['production_guard_bypassed'])
        self.assertFalse(out['target_results_used'])
        self.assertNotIn('confidence_assessment', analysis)
        self.assertEqual(analysis['published_cutoff_at'], '2099-01-01T12:00:00+09:00')
        with self.assertRaisesRegex(ValueError, 'ASSESSMENT_BEFORE_CREATION'):
            stability.assess_research_analysis(analysis, assessed_at='2099-01-01T12:59:59+09:00')

    def test_extra_unmodeled_tickets_do_not_gain_count_bonus(self):
        analysis = coherence_analysis()
        original = stability.assess_research_analysis(analysis)
        analysis['A']['ranked_tickets'] += [[7, 6, 5], [6, 7, 5]]
        analysis['A']['point_count_3t'] = 999
        changed = stability.assess_research_analysis(analysis)
        self.assertEqual(changed, original)

    def test_missing_or_invalid_six_phase_orders_do_not_receive_a_grade(self):
        for defect in ('missing', 'order', 'goal', 'actual', 'branch', 'counter', 'line', 'boolean_goal'):
            with self.subTest(defect=defect):
                analysis = coherence_analysis()
                rows = analysis['A']['six_phase_scenarios']
                if defect == 'missing':
                    rows[0]['six_phases'].pop(1)
                elif defect == 'order':
                    rows[0]['six_phases'][0]['projected_order'] = [1, 1, 2, 3, 4, 5, 6]
                elif defect == 'goal':
                    rows[0]['six_phases'][-1]['projected_top3'] = [7, 6, 5]
                elif defect == 'actual':
                    rows[0]['six_phases'][0]['actual_rider_position_video_verified'] = True
                elif defect == 'branch':
                    rows[0]['branch_kind'] = 'UNSOURCED_COUNTER'
                elif defect == 'line':
                    rows[0]['known_line_hypothesis'] = False
                elif defect == 'boolean_goal':
                    rows[0]['projected_3ren_tan'][0] = True
                else:
                    rows[1]['branch_kind'] = 'HOLD'
                out = stability.assess_research_analysis(analysis)
                self.assertEqual(out['evaluations']['A_3t']['rank'], 0)
                self.assertEqual(out['evaluations']['A_2t']['rank'], 0)
                self.assertEqual(out['evaluations']['B_3t']['rank'], 4)

    def test_unavailable_line_status_blocks_complete_looking_scenarios(self):
        analysis = coherence_analysis()
        analysis['line_status'] = 'UNAVAILABLE'
        out = stability.assess_research_analysis(analysis)
        self.assertTrue(all(entry['rank'] == 0 for entry in out['evaluations'].values()))

    def test_pair_support_and_pair_major_branches_ignore_extra_thirds(self):
        analysis = coherence_analysis()
        original = stability.assess_research_analysis(analysis)
        for arm in ('A', 'B'):
            extra = deepcopy(analysis[arm]['six_phase_scenarios'][1])
            extra['scenario_id'] = 'counter-extra-third'
            extra['projected_3ren_tan'] = [1, 3, 7]
            for phase in extra['six_phases']:
                phase['projected_order'] = [1, 3, 7, 2, 4, 5, 6]
                phase['projected_top3'] = [1, 3, 7]
            extra['support_A'] = extra['support_B'] = .001
            analysis[arm]['six_phase_scenarios'].append(extra)
        changed = stability.assess_research_analysis(analysis)
        for arm in ('A', 'B'):
            old = original['evaluations'][arm + '_2t']
            new = changed['evaluations'][arm + '_2t']
            self.assertEqual(new['rank'], 4)
            self.assertEqual(new['metrics'], old['metrics'])
            self.assertIsNone(new['metrics'].get('triple_top4_share'))

    def test_uncovered_family_blocks_high_despite_adequate_total_coverage(self):
        analysis = coherence_analysis()
        for arm in ('A', 'B'):
            analysis[arm]['six_phase_scenarios'][-1]['branch_kind'] = 'ATTACKER_FADE'
        out = stability.assess_research_analysis(analysis)
        for entry in out['evaluations'].values():
            self.assertEqual(entry['rank'], 2)
            self.assertIn('minor-b', entry['metrics'].get('major_uncovered_ids', []))
            self.assertEqual(entry['metrics']['scenario_coverage'], .95)

    def test_distinct_markets_and_arms_do_not_inherit_hot(self):
        analysis = coherence_analysis()
        analysis['A']['ranked_2ren_tan'] = [[7, 6]]
        analysis['B']['ranked_tickets'] = [[7, 6, 5]]
        out = stability.assess_research_analysis(analysis)['evaluations']
        self.assertEqual({key: value['grade'] for key, value in out.items()},
                         {'A_3t':'激アツ', 'A_2t':'低', 'B_3t':'低', 'B_2t':'激アツ'})

    def test_canonical_time_gate_still_rejects_post_cutoff_new_sidecar(self):
        from tests.test_keirin_confidence import baseline_fixture
        snapshot, baseline = baseline_fixture('hot')
        with self.assertRaisesRegex(confidence.ConfidenceAssessmentError, 'AFTER_OR_TOO_CLOSE_TO_CUTOFF'):
            confidence.assess_baseline(snapshot, baseline, assessed_at='2099-01-01T13:00:00+09:00')


if __name__ == "__main__":
    unittest.main()
