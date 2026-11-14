"""Same-as-of, four-sport pick-count research: fully synthetic fixtures."""
import copy
import math
import unittest

from test_comprehensive_four_sport_models import sample
from race_ai.comprehensive_four_sport_models import digest
from race_ai.four_sport_model_suite import run_suite, verify_suite, ALL_MODELS
from race_ai.ticket_selection_engine import (
    MIN_TICKETS, MAX_TICKETS, PLAN_NAMES, TicketSelectionError,
    build_ticket_trials, verify_ticket_trials, evaluate_ticket_trials
)


def revised_distribution(prediction, weights):
    """Synthetic recoring only, NEVER reuse as a historic real forecast."""
    original = copy.deepcopy(prediction)
    choices = sorted(tuple(row["combination"]) for row in original["candidates"])
    assert len(weights) == len(choices)
    total = math.fsum(weights)
    original["candidates"] = [
        {"combination": list(combo), "score": weight / total}
        for combo, weight in zip(choices, weights)
    ]
    original["candidates"].sort(key=lambda row: (
        -row["score"], row["combination"]))
    original["ordered_top8"] = [
        row["combination"] for row in original["candidates"][:8]]
    original["prediction_sha256"] = digest({
        k: v for k, v in original.items() if k != "prediction_sha256"})
    return original


def outcome(trials, winner, payout=1000, refunded=None, status="SETTLED"):
    return {
        "race_id": trials["race_id"], "status": status,
        "observed_at": "2030-01-15T11:00:00+09:00",
        "winning_combinations": [] if status == "CANCELLED" else [
            {"combination": winner, "payout_per_100_yen": payout}],
        "refunded_numbers": refunded or [],
        "source_grade": "unverified",
        "source_url": "https://example.test/unverified-result",
        "revision": 1,
    }


class EngineSelectionTests(unittest.TestCase):
    def test_suite_integrates_four_plans_for_all_four_sports(self):
        for sport, n in (("boat", 6), ("keirin", 7),
                         ("autorace", 8), ("horse", 9)):
            with self.subTest(sport=sport):
                before = sample(sport, size=n)
                prior = copy.deepcopy(before)
                suite = run_suite(before)
                self.assertEqual(before, prior)
                self.assertTrue(verify_suite(suite))
                self.assertEqual(tuple(suite["ticket_trials"]), ALL_MODELS)
                self.assertEqual(suite["purchase_decision"], "NO_BET")
                for model_id, trials in suite["ticket_trials"].items():
                    model = suite["models"][model_id]
                    self.assertTrue(verify_ticket_trials(model, trials))
                    self.assertEqual(tuple(trials["plans"]), PLAN_NAMES)
                    self.assertEqual(trials["as_of"], suite["as_of"])
                    self.assertEqual(trials["source_prediction_sha256"],
                                     model["prediction_sha256"])
                    self.assertIsNone(trials["external_pre_cutoff_receipt"])
                    self.assertFalse(trials["official_prediction"])
                    for plan in trials["plans"].values():
                        k = plan["ticket_count"]
                        self.assertTrue(MIN_TICKETS <= k <= MAX_TICKETS)
                        self.assertEqual(k, len(plan["ordered_tickets"]))
                        self.assertEqual(plan["ordered_tickets"],
                                         [row["combination"] for row
                                          in model["candidates"][:k]])
                    self.assertEqual(
                        trials["plans"]["fixed_8"]["ticket_count"], 8)
                    self.assertEqual(
                        trials["plans"]["fixed_12"]["ticket_count"], 12)

    def test_can_reach_one_ticket_for_extremely_concentrated_synthetic_score(self):
        pred = run_suite(sample("boat"))["models"][ALL_MODELS[0]]
        n = len(pred["candidates"])
        weighted = revised_distribution(pred, [100] + [1]*(n-1))
        trials = build_ticket_trials(weighted)
        tiny = trials["plans"]["confidence_shortlist_1_to_8"]
        self.assertEqual(tiny["ticket_count"], 1)
        self.assertEqual(len(tiny["ordered_tickets"]), 1)
        self.assertEqual(trials["plans"]["spread_adaptive_8_or_12"]["ticket_count"],8)
        self.assertTrue(verify_ticket_trials(weighted, trials))

    def test_wide_synthetic_first_place_scores_choose_twelve(self):
        pred = run_suite(sample("boat"))["models"][ALL_MODELS[0]]
        flat = revised_distribution(pred, [1]*len(pred["candidates"]))
        trials = build_ticket_trials(flat)
        self.assertEqual(trials["plans"]["spread_adaptive_8_or_12"]["ticket_count"],12)
        self.assertEqual(trials["plans"]["confidence_shortlist_1_to_8"]["ticket_count"],8)

    def test_full_ranking_stays_untouched_and_trial_tamper_is_rejected(self):
        suite = run_suite(sample("boat"))
        original = copy.deepcopy(suite["models"])
        self.assertEqual(suite["models"],original)
        model_id = ALL_MODELS[0]
        bad = copy.deepcopy(suite)
        bad["ticket_trials"][model_id]["plans"]["fixed_12"]["ordered_tickets"][0] = [3,2,1]
        bad["suite_sha256"] = digest({
            k:v for k,v in bad.items() if k!="suite_sha256"})
        self.assertFalse(verify_suite(bad))
        no_picks = copy.deepcopy(suite)
        plan = no_picks["ticket_trials"][model_id]["plans"]["fixed_8"]
        plan["ordered_tickets"] = []
        plan["ticket_count"] = 0
        no_picks["suite_sha256"] = digest({
            k:v for k,v in no_picks.items() if k!="suite_sha256"})
        self.assertFalse(verify_suite(no_picks))

    def test_12th_place_winner_only_adds_hit_to_twelve(self):
        prediction = run_suite(sample("boat"))["models"][ALL_MODELS[0]]
        trials = build_ticket_trials(prediction)
        winning = prediction["candidates"][11]["combination"]
        result = outcome(trials, winning, 8100)
        report = evaluate_ticket_trials(prediction, trials, result)
        self.assertEqual(report["plans"]["fixed_8"]["hit_rank"], None)
        self.assertEqual(report["plans"]["fixed_8"]["received_yen"], 0)
        self.assertEqual(report["plans"]["fixed_12"]["hit_rank"], 12)
        self.assertEqual(report["plans"]["fixed_12"]["gross_yen"], 1200)
        self.assertEqual(report["plans"]["fixed_12"]["received_yen"],8100)
        self.assertFalse(report["independently_verified"])

    def test_cancelled_is_refunded_not_missed(self):
        prediction = run_suite(sample("boat"))["models"][ALL_MODELS[0]]
        trials = build_ticket_trials(prediction)
        cancelled = outcome(trials, [], status="CANCELLED")
        report = evaluate_ticket_trials(prediction,trials,cancelled)
        for plan in report["plans"].values():
            self.assertEqual(plan["status"], "FULL_REFUND")
            self.assertEqual(plan["net_yen"],0)
            self.assertIsNone(plan["hit_rank"])
            self.assertEqual(plan["refund_yen"], plan["gross_yen"])

    def test_unverified_and_special_not_counted_as_zero(self):
        prediction = run_suite(sample("boat"))["models"][ALL_MODELS[0]]
        trials = build_ticket_trials(prediction)
        self.assertIsNone(evaluate_ticket_trials(prediction,trials,None)["plans"])
        special=outcome(trials,[],status="SPECIAL")
        special["winning_combinations"]=[]
        self.assertIsNone(evaluate_ticket_trials(prediction,trials,special)["plans"])

    def test_no_pre_cutoff_outcomes_or_forecast_modification(self):
        prediction = run_suite(sample("boat"))["models"][ALL_MODELS[0]]
        trials = build_ticket_trials(prediction)
        winner = prediction["candidates"][0]["combination"]
        before=outcome(trials,winner)
        before["observed_at"]="2030-01-15T09:30:00+09:00"
        with self.assertRaisesRegex(TicketSelectionError,"result observed before cutoff"):
            evaluate_ticket_trials(prediction,trials,before)
        altered = copy.deepcopy(prediction)
        altered["candidates"][0]["score"] += .1
        self.assertFalse(verify_ticket_trials(altered,trials))


if __name__ == "__main__":
    unittest.main()
