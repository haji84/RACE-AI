"""All reports in this file are synthetic and are NEVER real results."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from race_ai import keirin_available_prediction_audit as audit
from race_ai import keirin_nationwide_AB_results as results

INDEX=(Path(__file__).resolve().parents[1]/
       "docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json")
RID="202611182601"


def cohort():
    return json.loads(INDEX.read_text(encoding="utf-8"))


def fake(three=False):
    a={"hit_at_1":False,"hit_at_all":True,
       "stake_yen":800,"payout_yen":6700}
    b={"hit_at_1":True,"hit_at_all":True,
       "stake_yen":800,"payout_yen":6700}
    out={"schema":audit.AUDIT_SCHEMA,"race_id":RID,
         "state":"A_B_RESEARCH_SETTLED","ab_evaluable":True,
         "abc_evaluable":False,"A_existing":a,"B_six_phase":b,
         "C_six_phase_plus_line":None}
    if three:
        out["state"]="A_B_C_RESEARCH_SETTLED"
        out["abc_evaluable"]=True
        out["C_six_phase_plus_line"]={
            "hit_at_1":False,"hit_at_all":False,
            "stake_yen":400,"payout_yen":0}
    return out


class NationalABScorecard(unittest.TestCase):
    def test_zero_forecasts_in_79_races_all_HOLD_not_MISS(self):
        r=results.summarize(registry=cohort(),paired_reports=[])
        self.assertEqual(r["registered_races"],79)
        self.assertEqual(r["ab_independently_scored_races"],0)
        self.assertEqual(r["not_yet_independently_scored_races"],79)
        self.assertEqual(r["states"],{"HOLD_NO_OUTCOME_RECEIPT":79})
        self.assertIsNone(r["A_existing"]["virtual_roi"])
        self.assertEqual(r["by_venue"]["宇都宮"]["registered"],9)
        self.assertEqual(r["by_venue"]["静岡"]["registered"],11)

    def test_single_result_without_independent_witness_is_HOLD(self):
        r=results.summarize(registry=cohort(),paired_reports=[fake()])
        self.assertEqual(r["ab_independently_scored_races"],0)
        self.assertEqual(r["states"]["HOLD_SETTLEMENT_NOT_INDEPENDENTLY_RESTORED"],1)

    def test_fictional_1r_AB_comparison_keeps_78_other_races(self):
        r=results.summarize(
            registry=cohort(),paired_reports=[fake()],
            independently_verify_settled_report=lambda rid,x:True)
        self.assertEqual(r["ab_independently_scored_races"],1)
        self.assertEqual(r["not_yet_independently_scored_races"],78)
        self.assertEqual(r["states"]["AB_SCORED"],1)
        self.assertEqual(r["states"]["C_OPTIONAL_HOLD"],1)
        self.assertEqual(r["A_existing"]["eligible"],1)
        self.assertEqual(r["B_six_phase"]["eligible"],1)
        self.assertEqual(r["C_optional"]["eligible"],0)
        self.assertEqual(r["A_existing"]["virtual_roi"],6700/800)
        self.assertEqual(r["B_six_phase"]["hit_at_1"],1)
        self.assertEqual(r["by_venue"]["西武園"]["AB_scored"],1)
        self.assertEqual(r["by_venue"]["西武園"]["holds"],9)
        self.assertTrue(r["C_not_prerequisite_for_AB"])

    def test_C_on_only_same_eligible_races_not_all_AB(self):
        r=results.summarize(
            registry=cohort(),paired_reports=[fake(three=True)],
            independently_verify_settled_report=lambda *args:True)
        self.assertEqual(r["B_on_same_races_as_C"]["eligible"],1)
        self.assertEqual(r["C_optional"]["eligible"],1)
        self.assertEqual(r["states"]["C_SCORED_ON_SAME_RACE"],1)
        self.assertFalse(r["C_optional"]["hit_at_all"])

    def test_forged_C_flag_does_not_create_C_hit(self):
        report=fake()
        report["abc_evaluable"]=True
        r=results.summarize(
            registry=cohort(),paired_reports=[report],
            independently_verify_settled_report=lambda *args:True)
        self.assertEqual(r["C_optional"]["eligible"],0)
        self.assertEqual(r["states"]["C_OPTIONAL_HOLD"],1)

    def test_paid_without_hit_rejected(self):
        report=fake()
        report["A_existing"]["hit_at_all"]=False
        with self.assertRaisesRegex(results.NationwideScoreError,
                                    "PAIRED_RESULT_SCORE_CORRUPTED"):
            results.summarize(registry=cohort(),paired_reports=[report],
            independently_verify_settled_report=lambda *args:True)

    def test_duplicate_or_unregistered_race_not_allowed(self):
        with self.assertRaisesRegex(results.NationwideScoreError,
                                    "DUPLICATE"):
            results.summarize(registry=cohort(),paired_reports=[fake(),fake()])
        wrong=fake()
        wrong["race_id"]="202611189901"
        with self.assertRaisesRegex(results.NationwideScoreError,
                                    "OUTSIDE_COHORT"):
            results.summarize(registry=cohort(),paired_reports=[wrong])

    def test_HOLD_report_is_not_equivalent_to_missed_prediction(self):
        report=fake()
        report["state"]="HOLD_NO_AUTHENTICATED_RESULT"
        report["ab_evaluable"]=False
        r=results.summarize(registry=cohort(),paired_reports=[report])
        self.assertEqual(r["A_existing"]["eligible"],0)
        self.assertEqual(r["states"]["HOLD_RESULT_OR_PRE_CUTOFF_EVIDENCE_MISSING"],1)
        self.assertEqual(r["not_yet_independently_scored_races"],79)


if __name__=="__main__":
    unittest.main()
