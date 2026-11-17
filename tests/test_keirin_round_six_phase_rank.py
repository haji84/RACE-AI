"""Source-free six-phase stage-based ranking tests. All cars/results are FAKE.

No provider fetch, actual runner, historical rider label, calibrated
probability, official event assignment, or real prediction is asserted.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import permutations
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest

from race_ai import keirin_round_motivation as rounds
from race_ai import keirin_round_six_phase_rank as s


def stage_ctx(stage="SEMI_FINAL",kind=None,competition="A1_A2"):
    if kind is None:
        kind="NO_ADVANCEMENT" if stage == "FINAL" else "RANK_AND_CROSS_RACE"
    rule=({"kind":"RANK_AND_CROSS_RACE","direct_through":2,
           "conditional_ranks":[3],"points_rule":None}
          if kind == "RANK_AND_CROSS_RACE" else
          {"kind":kind,"direct_through":None,
           "conditional_ranks":[],"points_rule":None})
    return rounds.build_context(
        race_id="202611175004",competition=competition,
        stage=stage,label=("準決勝" if stage=="SEMI_FINAL" else "決勝"),
        race_size=7,as_of="2026-11-17T11:00:00+09:00",
        official_cutoff_at="2026-11-17T11:15:00+09:00",
        parent_input_sha256="a"*64,event_program_code="TEST_PROGRAM",
        program_pdf={
            "url":"https://keirin.jp/example/test_program.pdf",
            "sha256":"b"*64,"observed_at":"2026-11-17T10:58:00+09:00",
            "program_code":"TEST_PROGRAM",
            "event_program_receipt_sha256":"c"*64},
        rule=rule)


def snapshot():
    return {
        "race_id":"202611175004",
        "input_sha256":"a"*64,
        "baseline_model_id":"multisport-factor-interaction-v1",
        "baseline_prediction_sha256":"d"*64,
        "as_of":"2026-11-17T11:00:00+09:00",
        "official_cutoff_at":"2026-11-17T11:15:00+09:00",
        "starting_order":[3,6,1,2,7,4,5],
        "line_groups":[[3,6],[1,2,7],[4,5]],
        "baseline_top12":[[3,6,1],[3,1,6],[1,2,7]],
    }


def events(stage, *actions):
    return [
        {"phase":stage,"action":action,"actor":actor,
         "target":target,"success":success}
        for action,actor,target,success in actions
    ]


def plans():
    attack = (
        events("BELL",("KAMASHI",1,3,True),("YIELD",3,1,True))+
        events("FINAL_HOME",("FOLLOW_HELD",2,1,True))+
        events("FINAL_BACK",("THIRD_LINE_SURGE",4,1,True))+
        events("FOURTH_CORNER",("SASHI",2,1,True))+
        events("GOAL",("PACE_FADE",4,None,True))
    )
    defended = (
        events("BELL",("KAMASHI",1,3,False),
               ("TSUPPARI",3,1,True))+
        events("FINAL_HOME",("FOLLOW_HELD",6,3,True))+
        events("FINAL_BACK",("WAIT",4,None,True))+
        events("GOAL",("SASHI",6,3,True))
    )
    return [
        {"scenario_id":"kamashi_yield_third_surge",
         "observed_at":"2026-11-17T10:55:00+09:00",
         "input_sha256":"a"*64,"events":attack},
        {"scenario_id":"kamashi_fail_tsuppari",
         "observed_at":"2026-11-17T10:55:00+09:00",
         "input_sha256":"a"*64,"events":defended},
    ]


def priors():
    return {
        "schema":s.WEIGHTS_SCHEMA,"race_id":"202611175004",
        "input_sha256":"a"*64,"source_sha256":"e"*64,
        "observed_at":"2026-11-17T10:59:00+09:00",
        "independent_calibration_verified":False,
        "scenario_masses_by_objective":{
            "TITLE_WIN":{
                "kamashi_yield_third_surge":.8,
                "kamashi_fail_tsuppari":.2},
            "DIRECT_QUALIFY":{
                "kamashi_yield_third_surge":.2,
                "kamashi_fail_tsuppari":.8}
        }
    }


def generate(ctx=None,p=None,w=None,snap=None,verify=lambda x:True):
    return s.forecast_shadow(context=ctx or stage_ctx(),
                             snapshot=snap or snapshot(),
                             plans=p or plans(),priors=w or priors(),
                             independently_verified_parent=verify)


class RoundSixPhaseTests(unittest.TestCase):
    def test_semifinal_and_final_really_change_six_phase_3ren_tan_rank1(self):
        semi=generate(stage_ctx("SEMI_FINAL"))
        final=generate(stage_ctx("FINAL"))
        self.assertEqual(semi["advancement_objective"],"DIRECT_QUALIFY")
        self.assertEqual(final["advancement_objective"],"TITLE_WIN")
        self.assertEqual(semi["ranked_top12"][0]["cars"],[6,3,1])
        self.assertEqual(final["ranked_top12"][0]["cars"],[2,4,1])
        self.assertTrue(semi["research_rank1_differs_from_original"])
        self.assertTrue(final["research_rank1_differs_from_original"])
        self.assertFalse(semi["pr71_original_replaced"])
        self.assertEqual(semi["original_rank1"],[3,6,1])
        self.assertIsNone(semi["calibrated_win_probability"])
        self.assertFalse(semi["formal_model_promoted"])
        self.assertEqual(semi["real_forecast_count_claimed"],0)

    def test_each_branch_contains_six_real_state_transitions(self):
        result=generate()
        for branch in result["six_phase_branches"]:
            stages=branch["six_phases"]
            self.assertEqual(tuple(x["phase"] for x in stages),s.PHASES)
            self.assertEqual(len(stages),6)
            for item in stages:
                self.assertEqual(len(item["projected_order"]),7)
                self.assertEqual(len(set(item["projected_order"])),7)
                self.assertFalse(item["observed_from_video"])
                self.assertEqual(item["front_car"],item["projected_order"][0])
                self.assertEqual(item["projected_top3"],item["projected_order"][:3])
        example=result["six_phase_branches"][0]
        self.assertEqual(example["six_phases"][0]["front_car"],3)
        self.assertEqual(example["six_phases"][1]["front_car"],1)
        self.assertEqual(example["six_phases"][3]["front_car"],4)
        self.assertEqual(example["six_phases"][5]["front_car"],2)

    def test_kamashi_requires_other_rider_joint_yield_or_tsuppari(self):
        p=plans()
        p[0]["events"][1]["action"]="TSUPPARI"
        with self.assertRaisesRegex(s.TacticalRoundError,"CAUSALLY_INCONSISTENT"):
            generate(p=p)
        p=plans()
        p[0]["events"].pop(1)
        with self.assertRaisesRegex(s.TacticalRoundError,"REACTION_UNSPECIFIED"):
            generate(p=p)

    def test_role_reactions_reject_illegal_same_wheel_and_third_line(self):
        p=plans()
        p[0]["events"][2]["actor"]=5
        with self.assertRaisesRegex(s.TacticalRoundError,"WHEEL_NOT_ON_ORIGINAL_LINE"):
            generate(p=p)
        p=plans()
        p[0]["events"][3]["actor"]=2
        with self.assertRaisesRegex(s.TacticalRoundError,"THIRD_LINE_ACTOR_REQUIRED"):
            generate(p=p)

    def test_future_or_post_cutoff_source_is_rejected(self):
        p=plans()
        p[0]["observed_at"]="2026-11-17T11:02:00+09:00"
        with self.assertRaisesRegex(s.TacticalRoundError,"SOURCE_OR_TIME_MISMATCH"):
            generate(p=p)
        w=priors()
        w["observed_at"]="2026-11-17T11:01:00+09:00"
        with self.assertRaisesRegex(s.TacticalRoundError,"PRIORS_SOURCE_INVALID"):
            generate(w=w)

    def test_no_verified_parent_or_wrong_input_fails(self):
        with self.assertRaisesRegex(s.TacticalRoundError,"ORIGINAL_NOT_ADMITTED"):
            generate(verify=lambda x:False)
        wrong=snapshot()
        wrong["input_sha256"]="f"*64
        with self.assertRaisesRegex(s.TacticalRoundError,"ORIGINAL_OR_TIME_NOT_BOUND"):
            generate(snap=wrong)

    def test_non_normalized_or_missing_stage_mass_rejected(self):
        w=priors()
        w["scenario_masses_by_objective"]["DIRECT_QUALIFY"]["kamashi_fail_tsuppari"]=.9
        with self.assertRaisesRegex(s.TacticalRoundError,"NOT_NORMALIZED"):
            generate(w=w)
        w=priors()
        del w["scenario_masses_by_objective"]["DIRECT_QUALIFY"]
        with self.assertRaisesRegex(s.TacticalRoundError,"OBJECTIVE_OR_SCENARIO_MISSING"):
            generate(w=w)

    def test_last_result_winner_or_payout_is_not_a_feature(self):
        p=plans()
        p[0]["official_results"]={"triple":[2,4,1]}
        with self.assertRaisesRegex(s.TacticalRoundError,"SOURCE_OR_TIME_MISMATCH"):
            generate(p=p)
        w=priors()
        w["2026-11-17_actual_winner"]=[2,4,1]
        with self.assertRaisesRegex(s.TacticalRoundError,"PRIORS_SOURCE_INVALID"):
            generate(w=w)

    def test_unknown_or_points_without_prior_points_returns_hold(self):
        rule={"kind":"UNKNOWN","direct_through":None,
              "conditional_ranks":[],"points_rule":None}
        c=rounds.build_context(
            race_id="202611175004",competition="GIRLS",
            stage="PRELIMINARY_2",label="ガールズ予選2",
            race_size=7,as_of="2026-11-17T11:00:00+09:00",
            official_cutoff_at="2026-11-17T11:15:00+09:00",
            parent_input_sha256="a"*64,
            event_program_code="TEST_PROGRAM",program_pdf={
                "url":"https://keirin.jp/program.pdf",
                "sha256":"b"*64,"observed_at":"2026-11-17T10:58:00+09:00",
                "program_code":"TEST_PROGRAM",
                "event_program_receipt_sha256":"c"*64},rule=rule)
        res=generate(ctx=c)
        self.assertEqual(res["state"],"HOLD_ADVANCEMENT_OR_POINTS_UNVERIFIED")
        self.assertEqual(res["ranked_top12"],[])

    def test_wrong_initial_lines_and_duplicate_riders_fail(self):
        snap=snapshot()
        snap["line_groups"]=[[3,6],[1,2,7],[4,4]]
        with self.assertRaisesRegex(s.TacticalRoundError,"LINE_MEMBERSHIP_NOT_EXACT"):
            generate(snap=snap)
        snap=snapshot()
        snap["starting_order"]=[3,6,1,2,7,4,4]
        with self.assertRaisesRegex(s.TacticalRoundError,"STARTING_ORDER_INVALID"):
            generate(snap=snap)

    def test_out_of_order_tactical_phase_rejected(self):
        p=plans()
        p[0]["events"]=p[0]["events"][::-1]
        with self.assertRaisesRegex(s.TacticalRoundError,"NOT_CHRONOLOGICAL"):
            generate(p=p)

    def test_research_top12_has_no_duplicate_combinations(self):
        result=generate()
        tickets=result["ranked_top12"]
        self.assertGreaterEqual(len(tickets),2)
        self.assertLessEqual(len(tickets),12)
        self.assertEqual(len(set(tuple(row["cars"]) for row in tickets)),len(tickets))
        self.assertEqual(sum(x["research_relative_mass"] for x in tickets),1.0)

    def test_private_freeze_is_create_once_and_raw_readback(self):
        result=generate()
        with TemporaryDirectory() as td:
            parent=Path(td)
            parent.chmod(0o700)
            path=parent/"frozen-stage-shadow.json"
            proof=s.freeze_private_once(path,result)
            self.assertEqual(proof,sha256(path.read_bytes()).hexdigest())
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaisesRegex(s.TacticalRoundError,"PRIVATE_CREATE_ONCE"):
                s.freeze_private_once(path,result)

    def test_actual_existing_pr71_full_rank_ledger_adapts_into_six_phase_top12(self):
        c=stage_ctx()
        before=snapshot()
        rider_ids=[1,2,3,4,5,6,7]
        candidates=[{"combination":list(x),"score":0.0}
                    for x in permutations(rider_ids,3)]
        model_id="multisport-factor-interaction-v1"
        models={mid:{"model_id":mid,"prediction_sha256":"d"*64,
                     "snapshot_sha256":"a"*64,
                     "candidates":deepcopy(candidates)}
                for mid in s.KNOWN_PR71}
        saved={
            "source":{
                "race_id":c["race_id"],
                "starters":rider_ids,
                "as_of":c["as_of"],
                "official_cutoff_at":c["official_cutoff_at"],
            },
            "suite":{
                "race_id":c["race_id"],
                "sales_cutoff_at":c["official_cutoff_at"],
                "as_of":c["as_of"],
                "input_sha256":"a"*64,
                "models":models,
            },
            "persisted_at":"2026-11-17T11:02:00+09:00",
            "source_sha256":"f"*64
        }
        line={
            "race_id":c["race_id"],
            "source_input_sha256":"a"*64,
            "observed_at":"2026-11-17T10:59:00+09:00",
            "source_sha256":"e"*64,
            "starting_order":before["starting_order"],
            "line_groups":before["line_groups"],
        }
        result=s.forecast_from_existing_pr71(
            saved=saved,context=c,line_receipt=line,
            tactical_plans=plans(),stage_priors=priors(),
            independently_verify_suite=lambda x: True,
            independently_verify_lines=lambda x: True)
        self.assertEqual(result["original_rank1"],[1,2,3])
        self.assertEqual(result["ranked_top12"][0]["cars"],[6,3,1])
        self.assertEqual(result["parent_prediction_sha256"],"d"*64)
        self.assertFalse(result["formal_model_promoted"])
        with self.assertRaisesRegex(s.TacticalRoundError,
                                    "SOURCE_NOT_INDEPENDENTLY_VERIFIED"):
            s.forecast_from_existing_pr71(
                saved=saved,context=c,line_receipt=line,
                tactical_plans=plans(),stage_priors=priors(),
                independently_verify_suite=lambda x: True,
                independently_verify_lines=lambda x: False)
        line["observed_at"]="2026-11-17T11:01:00+09:00"
        with self.assertRaisesRegex(s.TacticalRoundError,
                                    "LINE_HYPOTHESIS_AFTER_CUTOFF"):
            s.forecast_from_existing_pr71(
                saved=saved,context=c,line_receipt=line,
                tactical_plans=plans(),stage_priors=priors(),
                independently_verify_suite=lambda x: True,
                independently_verify_lines=lambda x: True)

    def test_context_modified_not_promoted(self):
        c=stage_ctx()
        c["formal_prediction_created"]=True
        with self.assertRaises(rounds.RoundError):
            generate(c)


if __name__=="__main__":
    unittest.main()
