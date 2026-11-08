"""Synthetic archived-input retrospective PR71: never a live backtest claim."""
from copy import deepcopy
from hashlib import sha256
import unittest

from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.keirin_historical_asof_replay import (
    prepare_historical_pr71, evaluate_historical_without_repredicting,
    select_out_of_time_cohorts, HistoricalReplayGateError
)
from test_keirin_pr71_model_adapter import make_sources, RID

AFTER = "2030-01-16T13:00:00+09:00"
PIN = "c73fa3d8fe4ee4a22fdb7c90451be215155768b8"


def historical():
    return prepare_historical_pr71(
        make_sources()[0],performed_at=AFTER,model_code_commit_sha=PIN)


def result(winner, *, stamp="2030-01-15T10:10:00+09:00", paid=17500):
    return {"race_id":RID,"observed_at":stamp,"status":"FINAL_NORMAL",
            "refund_status":"NONE","winning_triples":[winner],
            "payouts_100yen":[{"triple":winner,"yen":paid}]}


class HistoricalTimeSplitAndReplayTests(unittest.TestCase):
    def test_two_steps_four_real_algorithms_run_on_fictional_historical_data(self):
        document=historical()
        self.assertTrue(document["forecast_generated_after_race"])
        self.assertIsNone(document["independent_original_pre_cutoff_forecast_receipt"])
        self.assertFalse(document["official_or_prospective_performance"])
        self.assertEqual(set(document["full_model_suite"]["models"]),set(ALL_MODELS))
        for name in ALL_MODELS:
            self.assertEqual(document["full_model_suite"]["models"][name][
                "candidate_count"],210)
        winning=document["full_model_suite"]["models"][ALL_MODELS[0]][
            "candidates"][9]["combination"]
        comparison=evaluate_historical_without_repredicting(
            document,result(winning))
        selected=comparison["four_existing_models"][ALL_MODELS[0]]
        self.assertEqual(selected["winning_rank_and_payout"][0]["rank"],10)
        self.assertFalse(selected["top8_hit"])
        self.assertTrue(selected["top12_hit"])
        self.assertFalse(comparison["count_as_formal_accuracy"])
        self.assertEqual(selected["variable_mode"],
                         "NOT_EVALUABLE_NO_PRE_EVENT_SELECTION")

    def test_historical_source_facts_later_than_asof_are_rejected(self):
        sample=make_sources()[0]
        obs=sample["facts"]["pr71_evidenced_snapshot"]["participants"][0][
            "features"]["ability"]
        obs["captured_at"]="2030-01-15T10:05:00+09:00"
        with self.assertRaises(ValueError):
            prepare_historical_pr71(
                sample,performed_at=AFTER,model_code_commit_sha=PIN)

    def test_genuine_real_scope_without_full_347_audit_or_admission_rejected(self):
        sample=make_sources()[0]
        sample["facts"]["pr71_evidenced_snapshot"]["scope"]=(
            "OPERATOR_SUPPLIED_RESEARCH")
        with self.assertRaisesRegex(HistoricalReplayGateError,
                                    "REAL_HISTORICAL_SOURCE_RIGHTS"):
            prepare_historical_pr71(
                sample,performed_at=AFTER,model_code_commit_sha=PIN)
        with self.assertRaisesRegex(HistoricalReplayGateError,
                                    "HISTORICAL_347_FACTOR_AUDIT_MISSING"):
            prepare_historical_pr71(
                sample,performed_at=AFTER,model_code_commit_sha=PIN,
                source_admission=lambda *args:True)

    def test_missing_or_reconstructed_original_input_is_not_treated_as_full(self):
        src=make_sources()[0]
        src["facts"]["pr71_evidenced_snapshot"]["participants"][0][
            "features"].pop("sprint_acceleration")
        with self.assertRaises(ValueError):
            prepare_historical_pr71(
                src,performed_at=AFTER,model_code_commit_sha=PIN)
        with self.assertRaisesRegex(HistoricalReplayGateError,
                                    "FULL_HISTORICAL_PR71_SNAPSHOT_MISSING"):
            prepare_historical_pr71(
                {"race_id":RID, "top8":["1-2-3"]},
                performed_at=AFTER,model_code_commit_sha=PIN)

    def test_no_backdate_future_or_fake_model_sha(self):
        src=make_sources()[0]
        with self.assertRaisesRegex(HistoricalReplayGateError,
                                    "THIS_IS_NOT_A_PAST_EVENT"):
            prepare_historical_pr71(
                src,performed_at="2030-01-15T09:20:00+09:00",
                model_code_commit_sha=PIN)
        with self.assertRaisesRegex(HistoricalReplayGateError,
                                    "EXACT_MODEL_COMMIT_SHA"):
            prepare_historical_pr71(
                src,performed_at=AFTER,model_code_commit_sha="unversioned")

    def test_no_result_in_model_input_and_race_result_tampering(self):
        sample=make_sources()[0]
        sample["facts"]["pr71_evidenced_snapshot"][
            "participants"][0]["features"]["winning_ticket"]={"value":1}
        with self.assertRaises(ValueError):
            prepare_historical_pr71(
                sample,performed_at=AFTER,model_code_commit_sha=PIN)
        source=historical()
        ticket=source["full_model_suite"]["models"][ALL_MODELS[0]][
            "candidates"][4]["combination"]
        source["full_model_suite"]["models"][ALL_MODELS[0]][
            "candidates"][4]["score"]+=0.1
        with self.assertRaisesRegex(HistoricalReplayGateError,
                                    "HISTORICAL_FROZEN_RESEARCH_SUITE"):
            evaluate_historical_without_repredicting(source,result(ticket))

    def test_holdout_requires_prior_nonoverlapping_training_days(self):
        safe=select_out_of_time_cohorts(
            ["2026-11-03"],["2026-11-08"],embargo_days=2)
        self.assertFalse(safe["holdout_labels_allowed_as_model_inputs"])
        for train,holdout,embargo in [
            (["2026-11-03"],["2026-11-03"],0),
            (["2026-11-08"],["2026-11-03"],0),
            (["2026-11-03"],["2026-11-04"],1),
            (["2026-11-03","2026-11-03"],["2026-11-08"],0),
        ]:
            with self.subTest(train=train,holdout=holdout):
                with self.assertRaises(HistoricalReplayGateError):
                    select_out_of_time_cohorts(
                        train,holdout,embargo_days=embargo)

    def test_nonfinal_and_refund_stay_unscored(self):
        stored=historical()
        pending={"race_id":RID,"observed_at":"2030-01-15T10:10:00+09:00",
                 "status":"PENDING","refund_status":"UNKNOWN",
                 "winning_triples":[],"payouts_100yen":[]}
        report=evaluate_historical_without_repredicting(stored,pending)
        self.assertEqual(report["result_status"],"UNSETTLED")
        self.assertTrue(all(
            r["top8_hit"] is None and r["reference_top8_payout"] is None
            for r in report["four_existing_models"].values()))
        bad=deepcopy(pending)
        bad["race_id"]="other"
        with self.assertRaisesRegex(HistoricalReplayGateError,
                                    "RESULT_TIME_OR_RACE_MISMATCH"):
            evaluate_historical_without_repredicting(stored,bad)


if __name__=="__main__":
    unittest.main()
