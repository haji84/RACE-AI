"""Synthetic before-cutoff forecasts and hypothetical outcomes only."""
from copy import deepcopy
import unittest

from race_ai import keirin_nationwide_auto_generator as base
from race_ai import keirin_form_fall_blind_pdca as pdca
from race_ai import keirin_form_fall_shadow as shadow
from tests.test_keirin_nationwide_auto_generator import fixture
from tests.test_keirin_form_history_admission import simulated_export,raw,rights,identity,AT,SOURCE_URL
from race_ai import keirin_form_history_admission as admission

RID="202611182601"
OTHER="202611182602"


def make():
    snap=fixture()
    prediction=base.generate_A_B(snap, generated_at=AT)
    export=simulated_export(snap)
    supplement=admission.build_supplement(
        raw_export=raw(export),source_url=SOURCE_URL,
        captured_at=AT,snapshot=snap,
        independently_authorize_source=rights,
        independently_verify_identity=identity)
    conditioned=shadow.generate_shadow(
        snap,supplement,baseline=prediction,generated_at=AT)
    ticket=prediction["A"]["ranked_tickets"][0]
    row={
        "baseline":prediction, "conditioned":conditioned,
        "starters":[r["car"] for r in snap["riders"]],
        "baseline_sealed_at":"2026-11-18T09:01:06+09:00",
        "conditioned_sealed_at":"2026-11-18T09:01:11+09:00",
        "result":{
            "race_id":RID, "status":"FINAL_NORMAL", "refund_status":"NONE",
            "winning_triples":[ticket],
            "payouts_100yen":[{"triple":ticket,"yen":700}]},
        "verified_receipts":{
            "baseline_origin":"original",
            "condition_origin":"conditional",
            "official_final":"official"},
    }
    return row


def trusted():
    # Fake callback is confined to test; real use requires API/server proof.
    expected={"baseline_origin":"original",
              "condition_origin":"conditional","official_final":"official"}
    return {key:(lambda rid, row, receipt, expected=value:
                 rid==RID and receipt == expected)
            for key,value in expected.items()}


class ConditionBlindPDCA(unittest.TestCase):
    def test_same_verified_eligible_race_and_missing_denominator(self):
        row=make()
        r=pdca.compare_cohort(
            registered_race_ids=[RID,OTHER],
            joined_private_rows={RID:row},
            independently_verify=trusted())
        self.assertEqual(r["registered_races"],2)
        self.assertEqual(r["paired_comparable_races"],1)
        self.assertEqual(r["statuses"]["HOLD_NO_AUTHENTICATED_PAIRED_ORIGINAL"],1)
        for role in ("A","B"):
            self.assertEqual(r["metrics"][role]["original"]["eligible_same_races"],1)
            self.assertEqual(r["metrics"][role]["conditioned"]["eligible_same_races"],1)
        self.assertEqual(r["metrics"]["A"]["original"]["first_hit"],1)
        self.assertEqual(r["metrics"]["A"]["original"]["all_hit"],1)
        self.assertEqual(r["metrics"]["A"]["original"]["stake_yen"],1200)
        self.assertEqual(r["metrics"]["A"]["original"]["payout_yen"],700)
        self.assertTrue(r["missing_never_scored_as_miss"])

    def test_without_condition_shadows_no_false_hit_or_roi(self):
        r=pdca.compare_cohort(
            registered_race_ids=[RID,OTHER],
            joined_private_rows={},
            independently_verify={})
        self.assertEqual(r["paired_comparable_races"],0)
        self.assertIsNone(r["metrics"]["A"]["conditioned"]["virtual_roi"])
        self.assertIsNone(r["metrics"]["B"]["conditioned"]["hit_rate"])

    def test_wrong_or_absent_external_witnesses_hold_race(self):
        row=make()
        for alteration in (
                lambda x:x["verified_receipts"].pop("condition_origin"),
                lambda x:x["verified_receipts"].update(official_final="fabricated"),
                lambda x:x["conditioned"].update(baseline_prediction_sha256="f"*64)):
            clone=deepcopy(row)
            alteration(clone)
            r=pdca.compare_cohort(
                registered_race_ids=[RID],
                joined_private_rows={RID:clone},
                independently_verify=trusted())
            self.assertEqual(r["paired_comparable_races"],0)
            self.assertEqual(r["statuses"]["HOLD_UNVERIFIED_PRE_CUTOFF_OR_FINAL"],1)

    def test_retrospective_shadow_at_or_after_cutoff_is_hold(self):
        row=make()
        row["conditioned_sealed_at"]="2026-11-18T11:59:10+09:00"
        r=pdca.compare_cohort(registered_race_ids=[RID],
            joined_private_rows={RID:row}, independently_verify=trusted())
        self.assertEqual(r["paired_comparable_races"],0)

    def test_bad_final_and_refund_never_marked_misses(self):
        for status,refund in (("CANCELLED","FULL"),("FINAL_NORMAL","UNKNOWN")):
            row=make()
            row["result"]["status"]=status
            row["result"]["refund_status"]=refund
            r=pdca.compare_cohort(registered_race_ids=[RID],
                joined_private_rows={RID:row}, independently_verify=trusted())
            self.assertEqual(r["paired_comparable_races"],0)
            self.assertEqual(r["statuses"]["HOLD_UNVERIFIED_PRE_CUTOFF_OR_FINAL"],1)
        self.assertTrue(r["missing_never_scored_as_miss"])

    def test_duplicate_ticket_rejection_isolated_to_affected_race(self):
        row=make()
        row["conditioned"]["A_research"]["ranked_tickets"][1] = (
            row["conditioned"]["A_research"]["ranked_tickets"][0])
        row["conditioned"]["sha256"] = base.digest({
            k:v for k,v in row["conditioned"].items() if k!="sha256"})
        report=pdca.compare_cohort(registered_race_ids=[RID],
            joined_private_rows={RID:row}, independently_verify=trusted())
        self.assertEqual(report["paired_comparable_races"],0)
        self.assertEqual(report["statuses"]["HOLD_UNVERIFIED_PRE_CUTOFF_OR_FINAL"],1)

    def test_unknown_races_and_duplicates_rejected(self):
        with self.assertRaisesRegex(pdca.ForwardComparisonError,
                                    "FORM_PDCA_COHORT_INVALID"):
            pdca.compare_cohort(registered_race_ids=[RID,RID],
                joined_private_rows={}, independently_verify=trusted())
        with self.assertRaisesRegex(pdca.ForwardComparisonError,
                                    "FORM_PDCA_UNKNOWN_RACE"):
            pdca.compare_cohort(registered_race_ids=[RID],
                joined_private_rows={OTHER:make()}, independently_verify=trusted())

    def test_invalid_b_does_not_commit_any_a_metrics(self):
        row = make()
        row["conditioned"]["B_research"]["ranked_tickets"][1] = (
            row["conditioned"]["B_research"]["ranked_tickets"][0])
        row["conditioned"]["sha256"] = base.digest({
            k:v for k,v in row["conditioned"].items() if k != "sha256"})
        report = pdca.compare_cohort(
            registered_race_ids=[RID], joined_private_rows={RID:row},
            independently_verify=trusted())
        self.assertEqual(report["paired_comparable_races"], 0)
        self.assertEqual(report["statuses"], {
            "HOLD_UNVERIFIED_PRE_CUTOFF_OR_FINAL": 1})
        for role in ("A", "B"):
            for arm in ("original", "conditioned"):
                metrics = report["metrics"][role][arm]
                self.assertEqual(metrics["first_hit"], 0)
                self.assertEqual(metrics["all_hit"], 0)
                self.assertEqual(metrics["stake_yen"], 0)
                self.assertEqual(metrics["payout_yen"], 0)
                self.assertEqual(metrics["virtual_profit_yen"], 0)
                self.assertIsNone(metrics["virtual_roi"])
                self.assertIsNone(metrics["hit_rate"])


if __name__=="__main__":
    unittest.main()
