"""Source-free fictional line-chemistry samples and six-phase ranking tests.

Fixture counts are INVENTED. They are neither empirical KEIRIN probabilities,
official rider identities nor observed video/track truths.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from race_ai import keirin_line_cohesion as line
from tests.test_keirin_round_six_phase_rank import (
    stage_ctx, snapshot, priors, plans,
)

JST = timezone(timedelta(hours=9))
IDS = {"1":"10001","2":"10002","3":"10003","4":"10004",
       "5":"10005","6":"10006","7":"10007"}


def config():
    return line.make_config(
        min_group=6,min_pair=2,alpha=1,pair_shrinkage=4,max_factor=3,
        frozen_at="2026-11-17T10:30:00+09:00")


def label(n, *, leader="10001",follower="10002",
          outcome="HELD",tactic="KAMASHI",role="SECOND_WHEEL",
          stage="SEMI_FINAL",competition="A1_A2"):
    # Synthetic historical race IDs of 12 digits with the same raceID format.
    date=datetime(2026,9,1,tzinfo=JST)+timedelta(days=n//12)
    rid=date.strftime("%Y%m%d")+"50"+f"{n%12+1:02d}"
    return line.make_label(
        race_id=rid,
        event_ended_at=date.replace(hour=13).isoformat(),
        source_published_at=date.replace(hour=14).isoformat(),
        available_at=date.replace(hour=15).isoformat(),
        source_sha256="c"*64,
        review_receipt_sha256="d"*64,
        leader_athlete_id=leader,follower_athlete_id=follower,
        role=role,competition=competition,round_stage=stage,
        leader_tactic=tactic,outcome=outcome)


def empirical_fixture():
    """Deliberately fictional, not fitted rider parameters.

    Branch A: a leader-follower with strong reviewed follow continuity but
    peer-group weak co-ride continuity (higher held likelihood ratio).
    Branch B: a pair with a high gapped sample despite a strong peer group.
    """
    rows=[]
    for i in range(4):
        rows.append(label(i,leader="10001",follower="10002",
                          tactic="KAMASHI",outcome="HELD"))
    for i in range(20):
        rows.append(label(100+i,leader=f"{20001+i}",follower=f"{30001+i}",
                          tactic="KAMASHI",outcome="GAPPED"))
    for i in range(8):
        rows.append(label(200+i,leader="10003",follower="10006",
                          tactic="TSUPPARI",outcome="GAPPED"))
    for i in range(20):
        rows.append(label(300+i,leader=f"{40001+i}",follower=f"{50001+i}",
                          tactic="TSUPPARI",outcome="HELD"))
    return rows


def run(*, history=None, idmap=None, cfg=None, verify_label=lambda r:True,
        verify_identity=lambda ids:True, verify_parent=lambda x:True,
        computed_at="2026-11-17T10:59:30+09:00"):
    return line.forecast_with_pair_evidence(
        context=stage_ctx(),snapshot=snapshot(),plans=plans(),
        priors=priors(),history=empirical_fixture() if history is None else history,
        athlete_ids_by_car=IDS if idmap is None else idmap,
        config=config() if cfg is None else cfg,
        independently_verify_label=verify_label,
        independently_verify_identity=verify_identity,
        independently_verify_original=verify_parent,
        computed_at=computed_at)


class TestPriorLineCohesion(unittest.TestCase):
    def test_same_pair_experience_reweights_six_phase_and_changes_trifecta(self):
        result=run()
        self.assertEqual(result["state"],"RESEARCH_STAGE_PLUS_LINE")
        self.assertEqual(result["stage_original_rank1"],[6,3,1])
        self.assertEqual(result["line_research_rank1"],[2,4,1])
        self.assertTrue(result["line_conditioning_changed_rank1"])
        self.assertGreaterEqual(result["conditioning"]["conditioned_pair_events"],2)
        self.assertEqual(result["stage_only"]["parent_prediction_sha256"],"d"*64)
        self.assertEqual(result["stage_plus_line"]["parent_prediction_sha256"],"d"*64)
        self.assertFalse(result["actual_model_promoted"])
        self.assertFalse(result["formal_accuracy_improvement_proven"])
        self.assertTrue(result["conditioning"]["untrained_and_uncalibrated"])
        self.assertIsNone(result["stage_plus_line"]["calibrated_win_probability"])

    def test_empty_history_does_not_label_a_new_pair_weak_or_first_ever(self):
        result=run(history=[])
        self.assertEqual(result["state"],"HOLD_NO_ADMITTED_PAIR_CONDITIONING")
        self.assertEqual(result["stage_original_rank1"],result["line_research_rank1"])
        self.assertEqual(result["conditioning"]["history_state"],"NO_REVIEWED_HISTORY")
        self.assertTrue(result["conditioning"]["never_classifies_zero_history_as_first_ride"])
        self.assertEqual(result["conditioning"]["conditioned_pair_events"],0)

    def test_group_history_without_actual_same_pair_has_no_penalty(self):
        other=[row for row in empirical_fixture()
               if not ((row["leader_athlete_id"]=="10001" and
                        row["follower_athlete_id"]=="10002") or
                       (row["leader_athlete_id"]=="10003" and
                        row["follower_athlete_id"]=="10006"))]
        result=run(history=other)
        self.assertEqual(result["stage_original_rank1"],result["line_research_rank1"])
        self.assertEqual(result["conditioning"]["conditioned_pair_events"],0)
        self.assertGreater(result["conditioning"]["insufficient_pair_events"],0)

    def test_same_district_alone_or_unseen_history_never_enters_formula(self):
        mapping=dict(IDS)
        mapping["2"]="10099"
        outcome=run(idmap=mapping)
        self.assertEqual(outcome["stage_original_rank1"],
                         outcome["line_research_rank1"])
        self.assertEqual(outcome["conditioning"]["conditioned_pair_events"],1)
        self.assertFalse(outcome["actual_model_promoted"])

    def test_older_ride_count_and_role_do_not_equal_follow_success(self):
        extra=[label(901+i,leader="10001",follower="10002",
                     tactic="KAMASHI",outcome="UNKNOWN")
               for i in range(5)]
        out=run(history=empirical_fixture()+extra)
        a=out["conditioning"]["per_scenario"]["kamashi_yield_third_surge"]
        one=next(x for x in a["pair_evidence"]
                 if x["state"]=="RESEARCH_SHRUNK_CONDITIONAL_RATIO")
        self.assertEqual(one["verified_pair_races"],9)
        self.assertEqual(one["labelled_pair_samples"],4)

    def test_future_or_same_race_observation_never_enters_training(self):
        history=empirical_fixture()
        modified=deepcopy(history)
        modified[0]["available_at"]="2026-11-17T11:01:00+09:00"
        modified[0]["label_sha256"]=line.digest({
            k:v for k,v in modified[0].items() if k!="label_sha256"})
        with self.assertRaisesRegex(line.LineHistoryError,
                                    "FUTURE_OR_SAME_RACE"):
            run(history=modified)
        modified=deepcopy(history)
        modified[0]["race_id"]=stage_ctx()["race_id"]
        modified[0]["label_sha256"]=line.digest({
            k:v for k,v in modified[0].items() if k!="label_sha256"})
        with self.assertRaisesRegex(line.LineHistoryError,
                                    "FUTURE_OR_SAME_RACE"):
            run(history=modified)

    def test_label_tamper_or_duplicate_does_not_count(self):
        history=empirical_fixture()
        modified=deepcopy(history)
        modified[0]["outcome"]="GAPPED"
        with self.assertRaisesRegex(line.LineHistoryError,"TAMPERED"):
            run(history=modified)
        with self.assertRaisesRegex(line.LineHistoryError,"DUPLICATED"):
            run(history=history+[history[0]])

    def test_source_review_must_be_independently_admitted(self):
        with self.assertRaisesRegex(line.LineHistoryError,"INDEPENDENT_LINE_LABEL_READER"):
            run(verify_label=None)
        with self.assertRaisesRegex(line.LineHistoryError,"NOT_INDEPENDENTLY_ADMITTED"):
            run(verify_label=lambda r:False)
        with self.assertRaisesRegex(line.LineHistoryError,"IDENTITIES_UNVERIFIED"):
            run(verify_identity=lambda ids:False)

    def test_no_current_source_verifier_no_model_conditioning(self):
        with self.assertRaisesRegex(line.LineHistoryError,"CURRENT_FROZEN_ORIGINAL_UNVERIFIED"):
            run(verify_parent=lambda x:False)

    def test_config_must_precede_forecast_and_be_immutable(self):
        conf=config()
        conf["pair_shrinkage"]=2
        with self.assertRaisesRegex(line.LineHistoryError,"CONFIG_MODIFIED"):
            run(cfg=conf)
        with self.assertRaisesRegex(line.LineHistoryError,"COMPUTED_AFTER_CUTOFF"):
            run(computed_at="2026-11-17T11:00:01+09:00")

    def test_rider_ids_are_not_car_numbers_from_historical_races(self):
        wrong=dict(IDS)
        wrong["6"]=wrong["3"]
        with self.assertRaisesRegex(line.LineHistoryError,"IDENTITY_NOT_VERIFIED"):
            run(idmap=wrong)
        wrong=dict(IDS);wrong["6"]="6"
        with self.assertRaisesRegex(line.LineHistoryError,"IDENTITY_NOT_VERIFIED"):
            run(idmap=wrong)

    def test_historical_labels_dont_infer_follow_from_finish_order(self):
        row=label(1)
        row["finish_order"]=[1,2,3]
        with self.assertRaisesRegex(line.LineHistoryError,"LABEL_SCHEMA"):
            line.validate_label(row)
        unknown=label(5,outcome="UNKNOWN")
        self.assertEqual(line.validate_label(unknown)["outcome"],"UNKNOWN")

    def test_group_minimum_denominator_enforced(self):
        limited=[row for row in empirical_fixture()
                 if row["leader_tactic"]=="KAMASHI"][:5]
        output=run(history=limited)
        self.assertEqual(output["state"],"HOLD_NO_ADMITTED_PAIR_CONDITIONING")
        self.assertGreater(output["conditioning"]["missing_group_events"],0)

    def test_stage_only_and_adjusted_probabilities_are_normalized(self):
        result=run()
        for output in (result["stage_only"],result["stage_plus_line"]):
            self.assertAlmostEqual(sum(
                x["research_relative_branch_mass"]
                for x in output["six_phase_branches"]),1)
            self.assertTrue(all(len(set(x["projected_3ren_tan"]))==3
                                for x in output["six_phase_branches"]))
            self.assertFalse(output["formal_model_promoted"])


if __name__=="__main__":
    unittest.main()
