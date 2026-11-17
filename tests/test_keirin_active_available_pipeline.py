"""Research-only A/B/C pipeline tests with fictional data and callbacks."""
from copy import deepcopy
import unittest

from race_ai import keirin_active_available_pipeline as pipeline
from race_ai import keirin_available_forecast_sources as existing
from tests.test_keirin_available_forecast_comparison import source_row
from tests.test_keirin_round_six_phase_rank import stage_ctx,snapshot,plans,priors
from tests.test_keirin_line_cohesion import empirical_fixture,IDS,config


def call(**updates):
    r=source_row()
    snap=snapshot()
    data={
        "saved_generated_race":r,
        "context":stage_ctx(),
        "official_line_receipt":{
            "race_id":r["race_id"],
            "source_input_sha256":"a"*64,
            "observed_at":"2026-11-17T10:59:00+09:00"},
        "starting_order":snap["starting_order"],
        "line_groups":snap["line_groups"],
        "tactical_plans":plans(),
        "stage_priors":priors(),
        "b_generated_at":"2026-11-17T11:04:00+09:00",
        "c_generated_at":"2026-11-17T11:05:00+09:00",
        "historical_line_labels":None,
        "rider_ids_by_car":IDS,
        "line_config":config(),
        "line_computed_at":"2026-11-17T11:00:30+09:00",
        "verify_owner_generated":lambda x:True,
        "verify_source_roster":lambda x:True,
        "verify_official_cutoff":lambda x:True,
        "verify_historical_follow":lambda x:True,
        "verify_rider_id_mapping":lambda x:True,
    }
    data.update(updates)
    return pipeline.prepare(**data)


class RealGeneratedResearchPath(unittest.TestCase):
    def test_existing_A_six_phase_B_without_four_model_or_C(self):
        res=call()
        self.assertEqual(res["state"],"A_B_RESEARCH_READY_C_HISTORY_HOLD")
        a,b=res["A_existing"],res["B_six_phase"]
        self.assertEqual(a["ranked_tickets"][0],[3,6,1])
        self.assertEqual(a["arm"],"EXISTING_GENERATED")
        self.assertEqual(b["arm"],"SIX_PHASE")
        self.assertEqual(list(b["phase_hypotheses"]),list(pipeline.six.PHASES))
        self.assertIsNone(res["C_six_phase_plus_line"])
        self.assertEqual(res["four_model_dependencies"],0)
        self.assertFalse(res["AES_private_originals_and_independent_runner_proven"])

    def test_existing_A_and_C_research_with_synthetic_history(self):
        result=call(historical_line_labels=empirical_fixture())
        self.assertEqual(result["state"],"A_B_C_RESEARCH_READY_FOR_PRIVATE_FREEZE")
        self.assertEqual(result["A_existing"]["common_input_sha256"],
                         result["C_six_phase_plus_line"]["common_input_sha256"])
        self.assertEqual(result["C_six_phase_plus_line"]["arm"],
                         "SIX_PHASE_PLUS_LINE")
        self.assertFalse(result["formal_accuracy_proven"])

    def test_unauthenticated_history_keeps_AB(self):
        result=call(historical_line_labels=empirical_fixture(),
                    verify_historical_follow=None)
        self.assertEqual(result["state"],"A_B_RESEARCH_READY_C_HISTORY_HOLD")
        self.assertEqual(result["C_hold"],"REAL_LINE_HISTORY_UNADMITTED_OR_C_CUTOFF_INVALID")
        self.assertIsNotNone(result["B_six_phase"])

    def test_fake_prior_71R_lineup_never_enters_C(self):
        result=call(historical_line_labels=[{"race_id":"202611098402","expected_line_cars":[5,3,6]}])
        self.assertEqual(result["state"],"A_B_RESEARCH_READY_C_HISTORY_HOLD")
        self.assertIsNone(result["C_six_phase_plus_line"])

    def test_missing_existing_original_or_cutoff_stops_A_and_B(self):
        with self.assertRaisesRegex(existing.AvailableSourceError,
                                    "INDEPENDENT_GENERATED"):
            call(verify_owner_generated=None)
        with self.assertRaisesRegex(existing.AvailableSourceError,
                                    "INDEPENDENT_GENERATED"):
            call(verify_official_cutoff=None)

    def test_C_late_computation_must_not_cancel_AB(self):
        result=call(historical_line_labels=empirical_fixture(),
                    c_generated_at="2026-11-17T11:14:15+09:00")
        self.assertEqual(result["state"],"A_B_RESEARCH_READY_C_HISTORY_HOLD")
        self.assertIsNotNone(result["B_six_phase"])


if __name__=="__main__":
    unittest.main()
