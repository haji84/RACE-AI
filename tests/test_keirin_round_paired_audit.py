"""Paired A/B audit synthetic fixtures: no organizer authentication or bets."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import unittest

from race_ai import keirin_round_paired_audit as a
from pathlib import Path
from tempfile import TemporaryDirectory
from race_ai import keirin_round_six_phase_rank as tactical
from tests.test_keirin_round_six_phase_rank import (
    stage_ctx, snapshot, plans, priors, generate,
)



def cutoffs(*races):
    return {rid:"2026-11-17T11:15:00+09:00" for rid in races}


def bundle():
    original=snapshot()
    candidate=generate(stage_ctx("FINAL"))
    orig_receipt={
        "race_id":original["race_id"],
        "model_prediction_sha256":original["baseline_prediction_sha256"],
        "saved_at":"2026-11-17T11:01:00+09:00"}
    new_receipt={
        "race_id":original["race_id"],
        "private_forecast_file_sha256":sha256(
            tactical.canonical(candidate)+b"\n").hexdigest(),
        "saved_at":"2026-11-17T11:02:00+09:00"}
    result={
        "schema":a.RESULT_SCHEMA,
        "race_id":original["race_id"],
        "source_published_at":"2026-11-17T11:30:00+09:00",
        "observed_at":"2026-11-17T11:32:00+09:00",
        "status":"FINAL_NORMAL","refund_status":"NONE",
        "winning_triples":[[2,4,1]],
        "payouts_100yen":[{"triple":[2,4,1],"yen":40000}],
        "provider_revision_ref":"synthetic-no-organizer-attestation"}
    return original,candidate,orig_receipt,new_receipt,result


def calc(*, data=None, orig_cb=lambda o,r:True, new_cb=lambda n,r:True,
         result_cb=lambda r:True):
    original,candidate,old_receipt,new_receipt,result=data or bundle()
    return a.compare(original=original,candidate=candidate,
                     original_receipt=old_receipt,
                     candidate_receipt=new_receipt,result=result,
                     verify_original=orig_cb,verify_candidate=new_cb,
                     verify_organizer_result=result_cb)


class TestPairedStageScore(unittest.TestCase):
    def test_stage_new_candidate_wins_synthetic_but_original_does_not(self):
        r=calc()
        self.assertEqual(r["state"],"PRIVATE_PAIRED_RESEARCH_SETTLED")
        self.assertTrue(r["paired_evaluable"])
        self.assertFalse(r["original"]["hit_at_1"])
        self.assertFalse(r["original"]["hit_at_all"])
        self.assertTrue(r["candidate"]["hit_at_1"])
        self.assertTrue(r["candidate"]["hit_at_all"])
        self.assertEqual(r["hit_at_1_delta"],1)
        self.assertEqual(r["hit_at_all_delta"],1)
        self.assertEqual(r["original"]["virtual_payout_yen"],0)
        self.assertEqual(r["candidate"]["virtual_payout_yen"],40000)
        self.assertEqual(r["original"]["virtual_stake_yen"],300)
        self.assertEqual(r["candidate"]["virtual_stake_yen"],200)
        self.assertFalse(r["formal_production_improvement_proven"])
        self.assertFalse(r["candidate"]["real_wagers_placed"])

    def test_no_real_independent_authentication_is_hold_not_a_loss(self):
        r=calc(result_cb=None)
        self.assertEqual(r["reason"],"OFFICIAL_RESULT_NOT_INDEPENDENTLY_AUTHENTICATED")
        self.assertFalse(r["paired_evaluable"])
        self.assertIsNone(r["original"])
        self.assertIsNone(r["candidate"])

    def test_missing_source_or_result_is_hold(self):
        data=list(bundle())
        data[-1]=None
        r=calc(data=data)
        self.assertEqual(r["reason"],"RESULT_UNOBSERVED_OR_OTHER_RACE")

    def test_unconfirmed_private_candidate_receipt_fails_closed(self):
        r=calc(new_cb=lambda n,t:False)
        self.assertEqual(r["reason"],"INDEPENDENT_ORIGINAL_AND_CANDIDATE_READBACK_REQUIRED")
        r=calc(orig_cb=lambda n,t:False)
        self.assertEqual(r["reason"],"INDEPENDENT_ORIGINAL_AND_CANDIDATE_READBACK_REQUIRED")

    def test_after_cutoff_candidate_cannot_be_retroactively_admitted(self):
        data=list(bundle())
        data[3]["saved_at"]="2026-11-17T11:14:30+09:00"
        r=calc(data=data)
        self.assertEqual(r["reason"],"NOT_BOTH_FORECASTS_FROZEN_PRE_CUTOFF")

    def test_original_vs_candidate_same_race_and_same_source(self):
        data=list(bundle())
        data[1]["pre_race_input_sha256"]="f"*64
        r=calc(data=data)
        self.assertEqual(r["reason"],"ORIGINAL_CANDIDATE_SOURCE_OR_TIME_MISMATCH")
        data=list(bundle())
        data[3]["private_forecast_file_sha256"]="f"*64
        r=calc(data=data)
        self.assertEqual(r["reason"],"PREDICTION_RECEIPT_SHA_MISMATCH")

    def test_refund_and_cancelled_do_not_fake_losses(self):
        data=list(bundle())
        data[-1]["refund_status"]="PARTIAL"
        self.assertEqual(calc(data=data)["reason"],
                         "REFUND_OR_PARTIAL_SETTLEMENT_UNSUPPORTED")
        data=list(bundle())
        data[-1]["status"]="CANCELLED"
        self.assertEqual(calc(data=data)["reason"],"NO_FINAL_SETTLED_RESULT")

    def test_source_published_before_deadline_is_rejected(self):
        data=list(bundle())
        data[-1]["source_published_at"]="2026-11-17T11:00:00+09:00"
        self.assertEqual(calc(data=data)["reason"],"RESULT_SOURCE_CLOCK_INVALID")

    def test_tied_multiple_winning_triples_evaluate_all_winners(self):
        data=list(bundle())
        result=data[-1]
        result["winning_triples"]=[[2,4,1],[3,6,1]]
        result["payouts_100yen"]=[
            {"triple":[2,4,1],"yen":40000},
            {"triple":[3,6,1],"yen":800}]
        r=calc(data=data)
        self.assertTrue(r["original"]["hit_at_1"])
        self.assertTrue(r["candidate"]["hit_at_1"])
        self.assertEqual(r["original"]["virtual_payout_yen"],800)
        self.assertEqual(r["candidate"]["virtual_payout_yen"],40000)

    def test_payout_mismatch_or_fake_amount_rejected(self):
        data=list(bundle())
        data[-1]["winning_triples"]=[[1,2,3]]
        with self.assertRaisesRegex(a.PairedAuditError,
                                    "WINNING_TRIPLES_AND_PAYOUTS_DIFFER"):
            calc(data=data)
        data=list(bundle())
        data[-1]["payouts_100yen"][0]["yen"]=-1
        with self.assertRaisesRegex(a.PairedAuditError,"PAYOUT_ROW_INVALID"):
            calc(data=data)

    def test_pre_registered_cohort_rejects_posthoc_race_selection(self):
        cohort=a.make_cohort(
            race_ids=["202611175004","202611175005"],
            registered_at="2026-11-17T10:45:00+09:00",
            race_cutoffs=cutoffs("202611175004","202611175005"),
            candidate_model_version="round-tactics-shadow-v1",
            original_model_id="multisport-factor-interaction-v1")
        one=calc()
        result=a.summarize(cohort,[one])
        self.assertEqual(result["total_planned"],2)
        self.assertEqual(result["paired_evaluable"],1)
        self.assertEqual(result["hold_reasons"],{"UNREPORTED":1})
        g=result["by_competition_and_round"]["A1_A2:FINAL"]
        self.assertEqual(g["candidate"]["hit_at_1"],1)
        self.assertEqual(g["original"]["hit_at_1"],0)
        self.assertAlmostEqual(g["candidate"]["virtual_roi"],200)
        self.assertFalse(result["real_race_improvement_proven"])

    def test_non_enrolled_result_or_duplicate_rejected(self):
        cohort=a.make_cohort(
            race_ids=["202611175005"],registered_at="2026-11-17T10:45:00+09:00",
            race_cutoffs=cutoffs("202611175005"),
            candidate_model_version="test",original_model_id="multisport-factor-interaction-v1")
        with self.assertRaisesRegex(a.PairedAuditError,"OUT_OF_COHORT"):
            a.summarize(cohort,[calc()])
        cohort2=a.make_cohort(
            race_ids=["202611175004"],registered_at="2026-11-17T10:45:00+09:00",
            race_cutoffs=cutoffs("202611175004"),
            candidate_model_version="test",original_model_id="multisport-factor-interaction-v1")
        with self.assertRaisesRegex(a.PairedAuditError,"COHORT_REPORT_SIZE"):
            a.summarize(cohort2,[calc(),calc()])

    def test_cohort_sha_tamper_fails(self):
        cohort=a.make_cohort(
            race_ids=["202611175004"],registered_at="2026-11-17T10:45:00+09:00",
            race_cutoffs=cutoffs("202611175004"),
            candidate_model_version="test",original_model_id="multisport-factor-interaction-v1")
        cohort["model_promotion_allowed"]=True
        with self.assertRaisesRegex(a.PairedAuditError,"COHORT_SHA_MISMATCH"):
            a.summarize(cohort,[])


    def test_cohort_after_any_cutoff_rejected_before_results(self):
        with self.assertRaisesRegex(a.PairedAuditError,"MUST_BE_REGISTERED_BEFORE_ALL_CUTOFFS"):
            a.make_cohort(
                race_ids=["202611175004"],
                registered_at="2026-11-17T11:14:30+09:00",
                race_cutoffs=cutoffs("202611175004"),
                candidate_model_version="test",
                original_model_id="multisport-factor-interaction-v1")

    def test_cohort_private_create_once_sha_readback(self):
        cohort=a.make_cohort(
            race_ids=["202611175004"],registered_at="2026-11-17T10:45:00+09:00",
            race_cutoffs=cutoffs("202611175004"),
            candidate_model_version="test",
            original_model_id="multisport-factor-interaction-v1")
        with TemporaryDirectory() as td:
            folder=Path(td);folder.chmod(0o700)
            p=folder/"cohort-frozen.json"
            file_sha=a.freeze_cohort_once(p,cohort)
            self.assertEqual(file_sha,sha256(p.read_bytes()).hexdigest())
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with self.assertRaisesRegex(a.PairedAuditError,"PRIVATE_CREATE_ONCE"):
                a.freeze_cohort_once(p,cohort)


if __name__=="__main__":
    unittest.main()
