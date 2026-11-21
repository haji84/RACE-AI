"""Synthetic pre-race examples. No real race outcome or stored rating is used."""
from copy import deepcopy
from itertools import combinations
import unittest

from race_ai import keirin_confidence as confidence
from race_ai import keirin_nationwide_auto_generator as generator


AS_OF = "2099-01-01T09:00:00+09:00"
ASSESSED_AT = "2099-01-01T09:02:00+09:00"
GENERATED_AT = "2099-01-01T09:01:00+09:00"
CUTOFF = "2099-01-01T12:00:00+09:00"


def synthetic_snapshot(kind="high"):
    """Importable fake fixture; high/hot describe intended test paths only."""
    n = 9 if kind == "medium" else 7
    groups = [[1, 2, 3], [4, 5], [6, 7]]
    if n == 9:
        groups += [[8, 9]]
    riders = [dict(car=i, athlete_id=f"{15000+i:06d}", mark_rank=i,
                   competition_points=90-i*1.3,
                   recent_form_score=round(1-i/(n+1), 3),
                   h_count=i % 5, b_count=i % 7,
                   style="MAKURI" if i % 2 else "MARK")
              for i in range(1, n+1)]
    if kind == "hot":
        groups = [[1, 2, 3], [4, 5, 6, 7]]
        for row in riders:
            car = row["car"]
            row.update(
                competition_points={1:100, 2:97, 3:92, 4:82, 5:85, 6:82, 7:80}[car],
                mark_rank={1:1, 2:2, 3:4, 4:"UNMARKED", 5:3, 6:"UNMARKED", 7:"UNMARKED"}[car],
                recent_form_score=.45 if car in (1, 2) else .1,
                style="NIGE" if car in (1, 4) else "MARK")
    return dict(schema=generator.SCHEMA, race_id="209901012601",
                as_of=AS_OF, published_cutoff_at=CUTOFF,
                cutoff_source=dict(url="https://example.invalid/cutoff",
                                   bytes_sha256="a"*64, captured_at=AS_OF),
                source_pages=[dict(kind=kind, url="https://example.invalid/"+kind.lower(),
                                   bytes_sha256=letter*64, captured_at=AS_OF)
                              for kind, letter in (("RACECARD", "b"), ("MARKS", "c"), ("LINE", "d"))],
                competition="A1_A2", round_stage="PRELIMINARY", round_rule=None,
                line_groups=groups, riders=riders)


def baseline_fixture(kind="high"):
    snapshot = synthetic_snapshot(kind)
    return snapshot, generator.generate_A_B(snapshot, generated_at=GENERATED_AT)


def authored_universe_fixture():
    """Independent narrative goals, listed before a selected ticket set exists."""
    return dict(
        schema="RACE_AI_KEIRIN_CONFIDENCE_UNIVERSE_V1", race_id="209901012601",
        source_as_of=AS_OF, cutoff=CUTOFF,
        source_prediction_sha256="a"*64, source_facts_sha256="b"*64,
        cars=list(range(1, 8)), evidence_kind="authored_goals",
        candidate_origin="independent_preselection_v1",
        source_status=dict(lineup="published_prediction", required_missing=[], conflicting_fields=[]),
        scenarios=[
            dict(id="S1", role="main", counter_family=None,
                 phases=["初周は二分戦。", "主線が上昇。", "主線が先行。", "番手が追走。", "先頭が踏み直す。", "先頭の押し切りを想定。"],
                 goal_candidates={"3t":[[1, 2, 3], [1, 2, 4]], "2t":[[1, 2]]}, research_weight=None),
            dict(id="S2", role="counter", counter_family="counterattack",
                 phases=["初周で別線が前。", "別線が仕掛ける。", "主線が応戦。", "番手に車間が開く。", "別線が二着へ進む。", "先頭は残り相手が変わる。"],
                 goal_candidates={"3t":[[1, 3, 2], [1, 3, 4]], "2t":[[1, 3]]}, research_weight=None),
        ])


class ConfidenceResearchRules(unittest.TestCase):
    def test_real_generator_synthetic_inputs_reach_middle_high_and_hot(self):
        for kind, expected in (("medium", "中"), ("high", "高"), ("hot", "激アツ")):
            with self.subTest(kind=kind):
                snapshot, baseline = baseline_fixture(kind)
                before = deepcopy((snapshot, baseline))
                bundle = confidence.assess_baseline(snapshot, baseline, assessed_at=ASSESSED_AT)
                self.assertEqual(bundle["evaluations"]["B"]["grade"], expected)
                self.assertEqual((snapshot, baseline), before)
                self.assertEqual(bundle["source_prediction_sha256"], baseline["prediction_sha256"])
                self.assertEqual(confidence.checked_assessment(bundle, snapshot=snapshot, baseline=baseline), bundle)
                self.assertTrue(any("未校正" in value for value in bundle["evaluations"]["B"]["limitations"]))

    def test_removing_tickets_cannot_raise_rating_or_change_denominator(self):
        snapshot, baseline = baseline_fixture("hot")
        universe = confidence.canonical_universe(snapshot, baseline)
        tickets = baseline["B"]["ranked_tickets"]
        original_hash = confidence.universe_sha256(universe)
        ranked = {}
        for size in range(1, len(tickets)+1):
            for indices in combinations(range(len(tickets)), size):
                result = confidence.evaluate_ticket_set(
                    universe, [tickets[i] for i in indices], market="3t", strategy="rollover", assessed_at=ASSESSED_AT)
                ranked[frozenset(indices)] = result["rank"]
                self.assertEqual(confidence.universe_sha256(universe), original_hash)
        for subset, rank in ranked.items():
            for car_index in set(range(len(tickets)))-set(subset):
                self.assertLessEqual(rank, ranked[subset | {car_index}])
        self.assertEqual(ranked[frozenset(range(len(tickets)))], 4)

    def test_uncovered_counter_scenario_blocks_high_even_with_many_main_tickets(self):
        universe = authored_universe_fixture()
        selected = universe["scenarios"][0]["goal_candidates"]["3t"]
        result = confidence.evaluate_ticket_set(universe, selected, market="3t", strategy="normal", assessed_at=ASSESSED_AT)
        self.assertLessEqual(result["rank"], 2)
        self.assertIn("S2", result["metrics"]["major_uncovered_ids"])
        self.assertTrue(any(r["code"] == "MAJOR_SCENARIO_UNCOVERED" for r in result["reasons"]))

    def test_valid_but_unsupported_ticket_is_low_not_hot_for_being_one_point(self):
        universe = authored_universe_fixture()
        result = confidence.evaluate_ticket_set(universe, [[7, 6, 5]], market="3t", strategy="rollover", assessed_at=ASSESSED_AT)
        self.assertEqual(result["grade"], "低")
        self.assertEqual(result["metrics"]["scenario_coverage"], 0)

    def test_authored_two_car_requires_its_own_goals_and_preserves_narrative(self):
        universe = authored_universe_fixture()
        before = deepcopy(universe)
        result = confidence.evaluate_ticket_set(universe, [{"combo":"1-2", "role":"本線"}, {"combo":"1-3", "role":"押さえ"}],
                                                market="2t", strategy="normal", assessed_at=ASSESSED_AT)
        self.assertEqual(result["grade"], "激アツ")
        self.assertIsNone(result["metrics"]["triple_top6_share"])
        self.assertIsNone(result["metrics"]["late_phase_axis_presence"])
        self.assertEqual(universe, before)
        for scenario in universe["scenarios"]:
            del scenario["goal_candidates"]["2t"]
        held = confidence.evaluate_ticket_set(universe, [[1, 2]], market="2t", strategy="normal", assessed_at=ASSESSED_AT)
        self.assertEqual(held["rank"], 0)
        self.assertTrue(any(r["code"] == "MARKET_GOALS_MISSING" for r in held["reasons"]))

    def test_missing_unknown_legacy_or_incomplete_evidence_never_promotes(self):
        for defect in ("missing", "conflict", "line", "legacy", "phases", "counter"):
            with self.subTest(defect=defect):
                universe = authored_universe_fixture()
                if defect == "missing": universe["source_status"]["required_missing"] = ["riders.1.H"]
                if defect == "conflict": universe["source_status"]["conflicting_fields"] = ["lineup"]
                if defect == "line": universe["source_status"]["lineup"] = "unknown"
                if defect == "legacy": universe["candidate_origin"] = "legacy_ticket_links"
                if defect == "phases": universe["scenarios"][1]["phases"].pop()
                if defect == "counter": universe["scenarios"] = [universe["scenarios"][0]]
                result = confidence.evaluate_ticket_set(universe, [[1, 2, 3]], market="3t", strategy="normal", assessed_at=ASSESSED_AT)
                self.assertEqual(result["rank"], 0)
                self.assertIsNone(result["metrics"]["scenario_coverage"])

    def test_late_or_future_source_time_is_not_backdated(self):
        universe = authored_universe_fixture()
        for at in ("2099-01-01T12:00:01+09:00", "2099-01-01T11:59:00+09:00", "2099-01-01T08:59:00+09:00"):
            with self.subTest(at=at):
                result = confidence.evaluate_ticket_set(universe, [[1, 2, 3]], market="3t", strategy="normal", assessed_at=at)
                self.assertEqual(result["rank"], 0)
        accepted = confidence.evaluate_ticket_set(universe, [[1, 2, 3]], market="3t", strategy="normal", assessed_at="2099-01-01T11:58:55+09:00")
        self.assertGreater(accepted["rank"], 0)

    def test_baseline_creation_stops_inside_cutoff_guard(self):
        snapshot, baseline = baseline_fixture()
        for at in ("2099-01-01T11:58:56+09:00", "2099-01-01T12:00:00+09:00", AS_OF):
            with self.subTest(at=at), self.assertRaises(confidence.ConfidenceAssessmentError):
                confidence.assess_baseline(snapshot, baseline, assessed_at=at)
        confidence.assess_baseline(snapshot, baseline, assessed_at="2099-01-01T11:58:55+09:00")

    def test_bundle_tampering_and_cross_prediction_bindings_are_rejected(self):
        snapshot, baseline = baseline_fixture()
        bundle = confidence.assess_baseline(snapshot, baseline, assessed_at=ASSESSED_AT)
        for mutate in (
            lambda b: b.update(source_prediction_sha256="c"*64),
            lambda b: b.update(scenario_universe_sha256="d"*64),
            lambda b: b["evaluations"]["B"].update(rank=4, grade="激アツ"),
            lambda b: b["evaluations"]["B"]["metrics"].update(scenario_coverage=.123),
            lambda b: b.update(extra=True),
        ):
            changed = deepcopy(bundle); mutate(changed)
            with self.assertRaises(confidence.ConfidenceAssessmentError):
                confidence.checked_assessment(changed, snapshot=snapshot, baseline=baseline)
        with self.assertRaises(confidence.ConfidenceAssessmentError):
            confidence.checked_assessment(bundle, snapshot=snapshot, baseline=baseline, sealed_at="2099-01-01T09:01:59+09:00")

    def test_partial_display_validation_does_not_call_public_assessment(self):
        from unittest.mock import patch
        snapshot, baseline = baseline_fixture()
        bundle = confidence.assess_baseline(snapshot, baseline, assessed_at=ASSESSED_AT)
        with patch.object(confidence, "assess_baseline", side_effect=AssertionError("must not generate a new assessment")):
            self.assertEqual(confidence.checked_assessment(bundle, snapshot=None, baseline=baseline), bundle)
            self.assertEqual(confidence.checked_assessment(bundle, snapshot=snapshot, baseline=baseline), bundle)

    def test_ticket_hash_is_order_metadata_independent_and_universe_changes_bind(self):
        universe = authored_universe_fixture()
        first = confidence.evaluate_ticket_set(universe, [[1, 2, 3], [1, 3, 2]], market="3t", strategy="normal", assessed_at=ASSESSED_AT)
        second = confidence.evaluate_ticket_set(universe, [{"combo":"1-3-2", "role":"本線"}, {"combo":"1-2-3", "role":"押さえ"}], market="3t", strategy="normal", assessed_at=ASSESSED_AT)
        self.assertEqual(first["tickets_sha256"], second["tickets_sha256"])
        changed = deepcopy(universe); changed["scenarios"][1]["goal_candidates"]["3t"].append([2, 1, 3])
        self.assertNotEqual(confidence.universe_sha256(changed), confidence.universe_sha256(universe))

    def test_labels_attention_and_results_are_not_evaluation_inputs(self):
        universe = authored_universe_fixture()
        for key, value in (("confidence", "激アツ"), ("attention", True), ("result", [1, 2, 3])):
            changed = deepcopy(universe); changed[key] = value
            with self.assertRaises(confidence.ConfidenceAssessmentError):
                confidence.evaluate_ticket_set(changed, [[1, 2, 3]], market="3t", strategy="normal", assessed_at=ASSESSED_AT)

    def test_inconsistent_structured_goal_and_malformed_enums_are_rejected(self):
        snapshot, baseline = baseline_fixture()
        universe = confidence.canonical_universe(snapshot, baseline)
        universe["scenarios"][0]["goal_candidates"]["3t"] = [[7, 6, 5]]
        with self.assertRaisesRegex(confidence.ConfidenceAssessmentError, "GOAL_MISMATCH"):
            confidence.evaluate_ticket_set(universe, [[7, 6, 5]], market="3t", strategy="normal", assessed_at=ASSESSED_AT)
        for field in ("lineup", "counter_family", "cars"):
            universe = authored_universe_fixture()
            if field == "lineup": universe["source_status"]["lineup"] = []
            if field == "counter_family": universe["scenarios"][1]["counter_family"] = []
            if field == "cars": universe["cars"][0] = "1"
            with self.subTest(field=field), self.assertRaises(confidence.ConfidenceAssessmentError):
                confidence.evaluate_ticket_set(universe, [[1, 2, 3]], market="3t", strategy="normal", assessed_at=ASSESSED_AT)

    def test_weight_wire_format_uses_javascript_decimal_tie_rule(self):
        # 1/8192 is an exact binary halfway case at twelve decimal places.
        self.assertEqual(confidence._wire_weight(1/8192), "0.000122070313")
        self.assertEqual(confidence._wire_weight(1.0), "1.000000000000")

    def test_saved_reasons_explain_this_forecast_and_its_next_grade_gap(self):
        snapshot, baseline = baseline_fixture("high")
        result = confidence.assess_baseline(snapshot, baseline, assessed_at=ASSESSED_AT)["evaluations"]["B"]
        reasons = {row["code"]:row["message"] for row in result["reasons"]}
        self.assertIn("1・5番", reasons["AXIS_GOAL_CONCENTRATION"])
        self.assertIn("約71.0%", reasons["AXIS_GOAL_CONCENTRATION"])
        self.assertIn("候補内比重", reasons["AXIS_GOAL_CONCENTRATION"])
        self.assertIn("全12シナリオ", reasons["FIXED_UNIVERSE_COVERAGE"])
        self.assertIn("激アツ", reasons["NEXT_LEVEL_NOT_MET"])
        self.assertIn("85.0%", reasons["NEXT_LEVEL_NOT_MET"])


if __name__ == "__main__":
    unittest.main()
