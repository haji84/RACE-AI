"""Entirely fictional odds and participants; no claimed live race or profit."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from race_ai.comprehensive_four_sport_models import digest
from race_ai.four_sport_model_suite import run_suite
from race_ai.keirin_variable_selection import (
    AUDIT_SCHEMA, ODDS_SCHEMA, SCHEMA, VariableSelectionError,
    aggregate_latest_audits, evaluate_settled_result,
    freeze_private_document_once, read_private_document, seal,
    select_research_tickets,
)
from tests.test_keirin_pr71_model_adapter import make_sources

DECISION = "2030-01-15T09:23:00+09:00"


def fixture(*, positive=2, all_edges=False, narrow=False):
    snapshot, _, _ = make_sources()
    suite = run_suite(snapshot["facts"]["pr71_evidenced_snapshot"])
    model = suite["models"]["multisport-scenario-ensemble-v1"]
    if narrow:
        rows = model["candidates"]
        length = len(rows)
        for i, row in enumerate(rows):
            row["score"] = 0.90 if i == 0 else 0.10/(length-1)
        model["ordered_top8"] = [row["combination"] for row in rows[:8]]
        model["prediction_sha256"] = digest(
            {k: v for k, v in model.items() if k != "prediction_sha256"})
        suite["suite_sha256"] = digest(
            {k: v for k, v in suite.items() if k != "suite_sha256"})
    prices = []
    for i, row in enumerate(model["candidates"]):
        p = row["score"]
        gross = (1.4 if all_edges or i < positive else 0.7)/p
        prices.append({"triple": row["combination"],
                       "decimal_odds": gross})
    odds = {
        "schema": ODDS_SCHEMA, "race_id": suite["race_id"],
        "captured_at": "2030-01-15T09:22:00+09:00",
        "source_ref": "synthetic://fictional-odds",
        "source_rights_ref": "SYNTHETIC_ONLY",
        "prices": prices,
    }
    return suite, model["model_id"], odds


class VariableKeirinSelectionTests(unittest.TestCase):
    def pick(self, **kwargs):
        suite, mid, odds = fixture(**kwargs)
        return select_research_tickets(suite, mid, odds,
                                       decision_at=DECISION)

    def test_two_picks_reduce_stake_and_are_not_claimed_calibrated(self):
        r = self.pick(positive=2)
        self.assertEqual(r["pick_count"], 2)
        self.assertEqual(r["reference_investment_yen"], 200)
        self.assertTrue(r["hypothetical_expected_roi"] > 0)
        self.assertFalse(r["model_accuracy_independently_verified"])
        self.assertEqual(r["real_money_recommendation"], "NO_BET_UNVERIFIED")
        self.assertTrue(r["selection_at"] < r["official_cutoff_at"])

    def test_wide_distribution_permits_up_to_twelve(self):
        r = self.pick(all_edges=True)
        self.assertEqual(r["dispersion_assessment"], "WIDE_HEURISTIC")
        self.assertEqual(r["max_picks"], 12)
        self.assertEqual(r["pick_count"], 12)

    def test_concentrated_distribution_never_exceeds_eight(self):
        r = self.pick(all_edges=True, narrow=True)
        self.assertEqual(r["dispersion_assessment"], "FOCUSED_HEURISTIC")
        self.assertEqual(r["max_picks"], 8)
        self.assertEqual(r["pick_count"], 8)

    def test_non_positive_hypothetical_edge_skips(self):
        r = self.pick(positive=0)
        self.assertEqual(r["pick_count"], 0)
        self.assertEqual(r["reference_investment_yen"], 0)
        self.assertIsNone(r["hypothetical_expected_roi"])
        self.assertIn("SKIP", r["research_status"])

    def test_after_cutoff_and_stale_future_odds_fail_closed(self):
        suite, mid, odds = fixture()
        with self.assertRaisesRegex(VariableSelectionError, "PRE_CUTOFF"):
            select_research_tickets(suite, mid, odds,
                decision_at="2030-01-15T10:00:00+09:00")
        odds["captured_at"] = "2030-01-15T09:25:00+09:00"
        with self.assertRaisesRegex(VariableSelectionError, "ODDS_AFTER"):
            select_research_tickets(suite, mid, odds, decision_at=DECISION)

    def test_duplicate_and_nonfinite_odds_fail_closed(self):
        suite, mid, odds = fixture()
        second = deepcopy(odds["prices"][1])
        odds["prices"][1] = deepcopy(odds["prices"][0])
        with self.assertRaisesRegex(VariableSelectionError, "DUPLICATE_ODDS"):
            select_research_tickets(suite, mid, odds, decision_at=DECISION)
        odds["prices"][1] = second
        odds["prices"][0]["decimal_odds"] = float("nan")
        with self.assertRaisesRegex(VariableSelectionError, "FINITE"):
            select_research_tickets(suite, mid, odds, decision_at=DECISION)

    def test_no_real_odds_admission_without_explicit_callback(self):
        suite, mid, odds = fixture()
        suite["scope"] = "OPERATOR_SUPPLIED_RESEARCH"
        suite["suite_sha256"] = digest({
            k:v for k,v in suite.items() if k != "suite_sha256"})
        with self.assertRaisesRegex(VariableSelectionError, "ADMISSION"):
            select_research_tickets(suite, mid, odds, decision_at=DECISION)

    def test_settled_hit_and_profit_are_based_on_payout_not_model_p(self):
        sel = self.pick(positive=2)
        winning = sel["tickets"][0]["triple"]
        result = {
            "race_id":sel["race_id"], "observed_at":"2030-01-15T10:10:00+09:00",
            "status":"FINAL_NORMAL", "refund_status":"NONE",
            "winning_triples":[winning],
            "payouts_100yen":[{"triple":winning, "yen":690}],
        }
        audit = evaluate_settled_result(sel, result, revision=1)
        self.assertTrue(audit["research_hit"])
        self.assertEqual(audit["reference_investment_yen"], 200)
        self.assertEqual(audit["reference_payout_yen"], 690)
        self.assertEqual(audit["reference_profit_yen"], 490)
        self.assertEqual(audit["reference_roi"], 3.45)
        self.assertFalse(audit["result_auth_independently_verified"])
        summary = aggregate_latest_audits([audit])
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["reference_profit_yen"], 490)
        self.assertEqual(summary["reference_roi"], 3.45)

    def test_refund_does_not_become_fake_loss(self):
        sel = self.pick(positive=2)
        audit = evaluate_settled_result(sel, {
            "race_id":sel["race_id"], "observed_at":"2030-01-15T10:10:00+09:00",
            "status":"PENDING", "refund_status":"UNKNOWN",
        }, revision=1)
        self.assertIsNone(audit["research_hit"])
        self.assertIsNone(audit["reference_profit_yen"])
        self.assertEqual(aggregate_latest_audits([audit])[
            "unresolved_or_refunded"], 1)

    def test_skip_is_excluded_from_hit_rate_denominator(self):
        sel = self.pick(positive=0)
        audit = evaluate_settled_result(sel, {
            "race_id":sel["race_id"], "observed_at":"2030-01-15T10:10:00+09:00",
            "status":"FINAL_NORMAL", "refund_status":"NONE",
            "winning_triples":[[1, 2, 3]],
            "payouts_100yen":[{"triple":[1, 2, 3], "yen":700}],
        }, revision=1)
        report = aggregate_latest_audits([audit])
        self.assertEqual(report["skipped"], 1)
        self.assertIsNone(report["hit_rate"])
        self.assertIsNone(report["reference_roi"])

    def test_immutable_owner_private_save_readback_and_no_rewrite(self):
        sel = self.pick(positive=2)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "selection.json"
            first = freeze_private_document_once(path, sel, schema=SCHEMA)
            self.assertEqual(first["state"], "CREATED_AND_READ_BACK")
            self.assertEqual(read_private_document(path, schema=SCHEMA), sel)
            self.assertEqual(freeze_private_document_once(
                path, sel, schema=SCHEMA)["state"], "ALREADY_SAVED_IDENTICAL")
            changed = deepcopy(sel)
            changed["tickets"][0]["reference_stake_yen"] = 200
            changed["document_sha256"] = seal({
                k:v for k,v in changed.items() if k!="document_sha256"})
            with self.assertRaisesRegex(VariableSelectionError, "IMMUTABLE"):
                freeze_private_document_once(path, changed, schema=SCHEMA)

    def test_revisions_not_silently_counted_twice(self):
        sel = self.pick(positive=2)
        winning = sel["tickets"][0]["triple"]
        result = {
            "race_id":sel["race_id"], "observed_at":"2030-01-15T10:10:00+09:00",
            "status":"FINAL_NORMAL", "refund_status":"NONE",
            "winning_triples":[winning],
            "payouts_100yen":[{"triple":winning, "yen":690}],
        }
        a1 = evaluate_settled_result(sel, result, revision=1)
        a2 = evaluate_settled_result(sel, result, revision=2)
        with self.assertRaisesRegex(VariableSelectionError, "DUPLICATE_RACE"):
            aggregate_latest_audits([a1, a2])


if __name__ == "__main__":
    unittest.main()
