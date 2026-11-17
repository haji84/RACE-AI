"""Three-model scorecard source-free tests, using fictional riders and payout."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import unittest

from race_ai import keirin_line_three_arm_audit as a
from race_ai import keirin_round_paired_audit as paired
from race_ai import keirin_round_six_phase_rank as six
from tests.test_keirin_round_six_phase_rank import stage_ctx, snapshot
from tests.test_keirin_line_cohesion import run


def fixture():
    original=snapshot()
    line_study=run()
    stage_receipt={
        "race_id":original["race_id"],
        "private_forecast_file_sha256":sha256(
            six.canonical(line_study["stage_only"])+b"\n").hexdigest(),
        "saved_at":"2026-11-17T11:02:00+09:00"}
    line_receipt={
        "race_id":original["race_id"],
        "private_forecast_file_sha256":sha256(
            six.canonical(line_study["stage_plus_line"])+b"\n").hexdigest(),
        "saved_at":"2026-11-17T11:03:00+09:00"}
    original_receipt={
        "race_id":original["race_id"],
        "model_prediction_sha256":original["baseline_prediction_sha256"],
        "saved_at":"2026-11-17T11:01:00+09:00"}
    result={
        "schema":paired.RESULT_SCHEMA,"race_id":original["race_id"],
        "source_published_at":"2026-11-17T11:30:00+09:00",
        "observed_at":"2026-11-17T11:31:00+09:00",
        "status":"FINAL_NORMAL","refund_status":"NONE",
        "winning_triples":[[2,4,1]],
        "payouts_100yen":[{"triple":[2,4,1],"yen":40000}],
        "source_proof":"synthetic-unverified-only"}
    return {
        "original":original,"line_study":line_study,
        "original_receipt":original_receipt,
        "round_receipt":stage_receipt,"line_receipt":line_receipt,
        "event_context":stage_ctx(),"result":result}


def score(bundle=None, *,vbase=lambda a,b:True,vstage=lambda a,b:True,
          vline=lambda a,b:True,vlabels=lambda a:True,vresult=lambda a:True):
    return a.compare_three(
        **(bundle if bundle is not None else fixture()),
        verify_original=vbase,verify_round=vstage,verify_line=vline,
        verify_video_labels=vlabels,verify_result=vresult)


def cohort():
    return paired.make_cohort(
        race_ids=["202611175004","202611175005"],
        registered_at="2026-11-17T10:40:00+09:00",
        race_cutoffs={"202611175004":"2026-11-17T11:15:00+09:00",
                      "202611175005":"2026-11-17T11:15:00+09:00"},
        candidate_model_version="stage-line-shrinkage-shadow-v1",
        original_model_id="multisport-factor-interaction-v1")


class ThreeArmStudy(unittest.TestCase):
    def test_three_models_same_input_one_fictional_race(self):
        r=score()
        self.assertEqual(r["state"],"PRIVATE_THREE_ARM_SAME_RACE_RESEARCH")
        self.assertTrue(r["paired_evaluable"])
        self.assertFalse(r["original"]["hit_at_1"])
        self.assertFalse(r["round_stage_only"]["hit_at_1"])
        self.assertTrue(r["round_and_line"]["hit_at_1"])
        self.assertEqual(r["line_vs_round_hit1_delta"],1)
        # Reordering the same two combinations improves Hit@1 here, but
        # cannot improve Hit@all if both models already include the winner.
        self.assertEqual(r["line_vs_round_all_delta"],0)
        self.assertTrue(r["round_stage_only"]["hit_at_all"])
        self.assertTrue(r["round_and_line"]["hit_at_all"])
        self.assertEqual(r["round_and_line"]["virtual_payout_yen"],40000)
        self.assertFalse(r["formal_uplift_proven"])
        self.assertFalse(r["actual_money_wagered"])

    def test_independent_history_review_required_or_hold(self):
        r=score(vlabels=None)
        self.assertEqual(r["reason"],"LINE_HISTORY_INDEPENDENT_READER_UNAVAILABLE")
        r=score(vlabels=lambda _:False)
        self.assertEqual(r["reason"],"LINE_HISTORY_INDEPENDENT_READER_UNAVAILABLE")

    def test_official_result_unauthenticated_is_not_loss(self):
        r=score(vresult=lambda _:False)
        self.assertFalse(r["paired_evaluable"])
        self.assertIn("RESULT_NOT_INDEPENDENTLY_AUTHENTICATED",r["reason"])

    def test_candidate_missing_real_line_evidence_is_not_compared(self):
        b=fixture()
        b["line_study"]["state"]="HOLD_NO_ADMITTED_PAIR_CONDITIONING"
        r=score(b)
        self.assertEqual(r["reason"],"NO_ADMITTED_LINE_CONDITIONING")

    def test_parent_sha_inherited_not_modified(self):
        b=fixture()
        b["line_study"]["stage_plus_line"]["parent_prediction_sha256"]="f"*64
        r=score(b)
        self.assertEqual(r["reason"],"LINE_CONDITIONING_PROVENANCE_OR_LINEAGE_MISMATCH")

    def test_same_cohort_but_late_line_freeze_refused(self):
        b=fixture()
        b["line_receipt"]["saved_at"]="2026-11-17T11:14:30+09:00"
        r=score(b)
        self.assertEqual(r["reason"],
                         "COHESION_ARM_NOT_BOTH_FORECASTS_FROZEN_PRE_CUTOFF")

    def test_independently_read_back_two_shadows(self):
        r=score(vstage=lambda a,b:True,vline=lambda a,b:False)
        self.assertEqual(r["reason"],
                         "COHESION_ARM_INDEPENDENT_ORIGINAL_AND_CANDIDATE_READBACK_REQUIRED")

    def test_refund_is_hold_for_all_three(self):
        b=fixture()
        b["result"]["refund_status"]="FULL"
        r=score(b)
        self.assertEqual(r["reason"],
                         "ROUND_STAGE_ARM_REFUND_OR_PARTIAL_SETTLEMENT_UNSUPPORTED")

    def test_line_model_can_lose_on_different_fictional_outcome(self):
        b=fixture()
        b["result"]["winning_triples"]=[[6,3,1]]
        b["result"]["payouts_100yen"]=[
            {"triple":[6,3,1],"yen":35000}]
        r=score(b)
        self.assertEqual(r["line_vs_round_hit1_delta"],-1)
        self.assertFalse(r["round_and_line"]["hit_at_1"])
        self.assertTrue(r["round_stage_only"]["hit_at_1"])
        self.assertFalse(r["formal_uplift_proven"])

    def test_frozen_future_cohort_counts_unreported_as_hold(self):
        summary=a.summarize(cohort(),[score()])
        self.assertEqual(summary["planned_races"],2)
        self.assertEqual(summary["three_arm_paired_races"],1)
        self.assertEqual(summary["unpaired_holds"],{"UNREPORTED":1})
        g=summary["by_class_round_program"]["A1_A2:SEMI_FINAL:TEST_PROGRAM"]
        self.assertEqual(g["original"]["hit_at_1"],0)
        self.assertEqual(g["round_stage_only"]["hit_at_1"],0)
        self.assertEqual(g["round_and_line"]["hit_at_1"],1)
        self.assertFalse(summary["real_accuracy_uplift_proven"])

    def test_noncohort_and_duplicate_rejected(self):
        b=score()
        b["race_id"]="202611175099"
        with self.assertRaisesRegex(paired.PairedAuditError,"OUT_OF_COHORT"):
            a.summarize(cohort(),[b])
        with self.assertRaisesRegex(paired.PairedAuditError,"OUT_OF_COHORT"):
            a.summarize(cohort(),[score(),score()])

    def test_result_unknown_from_other_race_is_hold(self):
        b=fixture()
        b["result"]["race_id"]="202611175005"
        r=score(b)
        self.assertEqual(r["reason"],
                         "ROUND_STAGE_ARM_RESULT_UNOBSERVED_OR_OTHER_RACE")


if __name__=="__main__":
    unittest.main()
