"""Synthetic, source-free research tests for official-program-aware KEIRIN tactics.

The real 2026 official KEIRIN.JP PDF URL is only a schema example. The
event-program assignment, SHA and riders here are FICTIONAL fixtures.
Nothing below asserts that this program governed a November 17 race.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest

from race_ai import keirin_round_motivation as s

PROGRAM = "https://www.keirin.jp/pc/dfw/portal/guest/data/prize/2026/gaitei/2026_gaitei_202576_A3ka.pdf"
FAKE = {
    "url":PROGRAM,
    "sha256":"a"*64,
    "observed_at":"2026-11-17T10:00:00+09:00",
    "program_code":"A3カ",
    "event_program_receipt_sha256":"b"*64,
}


def context(*, competition="A1_A2",stage="SEMI_FINAL",label="準決勝",
            rule=None,race_size=7):
    rule = rule if rule is not None else {
        "kind":"RANK_AND_CROSS_RACE", "direct_through":2,
        "conditional_ranks":[3], "points_rule":None,
    }
    return s.build_context(
        race_id="202611175004",competition=competition,stage=stage,
        label=label,race_size=race_size,
        as_of="2026-11-17T11:00:00+09:00",
        official_cutoff_at="2026-11-17T11:15:00+09:00",
        parent_input_sha256="c"*64,
        event_program_code="A3カ",
        program_pdf=deepcopy(FAKE),rule=deepcopy(rule))


def candidate(scenario, rank_mass, *, observed="2026-11-17T10:55:00+09:00"):
    return {
        "scenario_id":scenario,"rider_no":1,
        "rank_mass":rank_mass,"as_of":observed,
        "input_sha256":"c"*64,
    }


class RoundMotivationTest(unittest.TestCase):
    def test_challenge_is_competition_and_not_prediction_stage(self):
        c=context(competition="CHALLENGE",stage="PRELIMINARY",
                  label="チャレンジ予選")
        p=s.conditions(c)
        self.assertEqual(p["class"],"CHALLENGE")
        self.assertEqual(p["round_stage"],"PRELIMINARY")
        self.assertEqual(p["guaranteed_rank_through"],2)
        self.assertIn("CROSS_RACE_WILDCARD_NOT_AUTOMATIC",
                      p["strategic_conditions"])
        self.assertIsNone(p["hit_at_1_uplift"])
        self.assertFalse(p["candidate_top12_reranked"])

    def test_semifinal_cross_race_third_not_guaranteed(self):
        c=context()
        p=s.conditions(c)
        self.assertEqual(p["conditional_finish_ranks"],[3])
        self.assertIn("BOUNDARY_POSITION_TACTIC_DEPENDS_ON_OTHER_HEATS",
                      p["strategic_conditions"])
        self.assertFalse(c["official_program_match_independently_authenticated"])

    def test_final_uses_win_objective_instead_of_qualification(self):
        final=context(stage="FINAL",label="決勝",
                      rule={"kind":"NO_ADVANCEMENT","direct_through":None,
                            "conditional_ranks":[],"points_rule":None})
        p=s.conditions(final)
        self.assertIn("WIN_IS_ONLY_TITLE_RANK",p["strategic_conditions"])
        self.assertIsNone(p["guaranteed_rank_through"])
        with self.assertRaisesRegex(s.RoundError,"FINAL_MUST_NOT_PROMOTE"):
            context(stage="FINAL",label="決勝")

    def test_girls_points_two_rounds_need_standings(self):
        rule={"kind":"CUMULATIVE_POINTS","direct_through":None,
              "conditional_ranks":[],"points_rule":"two-race-points-top7"}
        c=context(competition="GIRLS",stage="PRELIMINARY_2",
                  label="ガールズ予2B",rule=rule)
        p=s.conditions(c)
        self.assertIn("OFFICIAL_POINTS_TIEBREAKER_NEEDED",p["strategic_conditions"])
        shadow=s.shadow_strategy_intervals(c,[candidate("A",[1,0,0,0,0,0,0])])
        self.assertEqual(shadow["state"],"HOLD_POINTS_OR_PROGRAM_UNKNOWN")
        self.assertEqual(shadow["ranked"],[])

    def test_initial_special_all_ranks_may_advance_if_program_says_so(self):
        c=context(stage="INITIAL_SPECIAL",label="初特選",
                  rule={"kind":"DIRECT_RANK","direct_through":7,
                        "conditional_ranks":[],"points_rule":None})
        p=s.conditions(c)
        self.assertIn("ALL_FINISHES_DIRECTLY_ADVANCE",p["strategic_conditions"])
        self.assertNotIn("ATTACK_IF_OUTSIDE_DIRECT_ZONE",p["strategic_conditions"])

    def test_program_code_must_match_event(self):
        args={"race_id":"202611175004","competition":"A1_A2",
             "stage":"SEMI_FINAL","label":"準決勝","race_size":7,
             "as_of":"2026-11-17T11:00:00+09:00",
             "official_cutoff_at":"2026-11-17T11:15:00+09:00",
             "parent_input_sha256":"c"*64,
             "event_program_code":"WRONG_2026_PROGRAM",
             "program_pdf":deepcopy(FAKE),
             "rule":{"kind":"DIRECT_RANK","direct_through":2,
                     "conditional_ranks":[],"points_rule":None}}
        with self.assertRaisesRegex(s.RoundError,"EVENT_AND_PROGRAM_NOT_BOUND"):
            s.build_context(**args)

    def test_program_must_be_observed_before_forecast_cutoff(self):
        args={"race_id":"202611175004","competition":"A1_A2",
              "stage":"SEMI_FINAL","label":"準決勝","race_size":7,
              "as_of":"2026-11-17T11:00:00+09:00",
              "official_cutoff_at":"2026-11-17T11:15:00+09:00",
              "parent_input_sha256":"c"*64,
              "event_program_code":"A3カ",
              "program_pdf":dict(FAKE,observed_at="2026-11-17T11:01:00+09:00"),
              "rule":{"kind":"DIRECT_RANK","direct_through":2,
                      "conditional_ranks":[],"points_rule":None}}
        with self.assertRaisesRegex(s.RoundError,"PROGRAM_NOT_OBSERVED_PRE_CUTOFF"):
            s.build_context(**args)
        args["program_pdf"]=deepcopy(FAKE)
        args["as_of"]="2026-11-17T11:14:30+09:00"
        with self.assertRaisesRegex(s.RoundError,"PROGRAM_NOT_OBSERVED_PRE_CUTOFF"):
            s.build_context(**args)

    def test_no_generic_pdf_for_other_host_or_malicious_url(self):
        args=dict(FAKE)
        for bad in ["http://www.keirin.jp/gaitei.pdf",
                    "https://evil.invalid/program.pdf",
                    "https://user:pass@keirin.jp/gaitei.pdf",
                    "https://www.keirin.jp/gaitei.html"]:
            args["url"]=bad
            with self.assertRaises(s.RoundError):
                s.build_context(
                    race_id="202611175004",competition="A1_A2",
                    stage="SEMI_FINAL",label="準決勝",race_size=7,
                    as_of="2026-11-17T11:00:00+09:00",
                    official_cutoff_at="2026-11-17T11:15:00+09:00",
                    parent_input_sha256="c"*64,event_program_code="A3カ",
                    program_pdf=deepcopy(args),
                    rule={"kind":"DIRECT_RANK","direct_through":2,
                          "conditional_ranks":[],"points_rule":None})

    def test_wrong_round_label_rejected(self):
        with self.assertRaisesRegex(s.RoundError,"ROUND_LABEL_DISAGREES"):
            context(stage="SEMI_FINAL",label="予選")
        with self.assertRaisesRegex(s.RoundError,"CHALLENGE_LABEL_DISAGREES"):
            context(competition="CHALLENGE",label="準決勝")
        with self.assertRaisesRegex(s.RoundError,"GIRLS_LABEL_DISAGREES"):
            context(competition="GIRLS",label="準決勝")

    def test_wildcard_mass_must_not_count_as_direct_qualification(self):
        c=context()
        A=candidate("safe_top_two",[.2,.6,.1,.1,0,0,0])
        B=candidate("win_or_fourth",[.55,0,.05,.4,0,0,0])
        study=s.shadow_strategy_intervals(c,[A,B])
        self.assertEqual(study["state"],"RESEARCH_PROXY_STRICTLY_SEPARATED")
        self.assertEqual(study["ranked"][0]["scenario_id"],"safe_top_two")
        a=next(x for x in study["candidate_details"]
               if x["scenario_id"]=="safe_top_two")
        self.assertAlmostEqual(a["guaranteed_or_win_proxy_lower"],.8)
        self.assertAlmostEqual(a["conditional_proxy_upper"],.9)
        self.assertFalse(study["calibrated"])
        self.assertFalse(study["formal_top12_changed"])

    def test_final_different_research_preference_without_model_rewrite(self):
        final=context(stage="FINAL",label="決勝",
                      rule={"kind":"NO_ADVANCEMENT","direct_through":None,
                            "conditional_ranks":[],"points_rule":None})
        A=candidate("safe_top_two",[.2,.6,.1,.1,0,0,0])
        B=candidate("win_or_fourth",[.55,0,.05,.4,0,0,0])
        study=s.shadow_strategy_intervals(final,[A,B])
        self.assertEqual(study["ranked"][0]["scenario_id"],"win_or_fourth")
        self.assertIs(study["formal_top12_changed"],False)

    def test_overlap_refuses_rank_and_unknown_does_not_impute(self):
        c=context()
        A=candidate("A",[.2,.4,.1,.3,0,0,0])
        B=candidate("B",[.5,0,.25,.25,0,0,0])
        study=s.shadow_strategy_intervals(c,[A,B])
        self.assertEqual(study["state"],"HOLD_OVERLAPPING_CONDITIONAL_OUTCOMES")
        self.assertEqual(study["ranked"],[])
        missing=context(rule={"kind":"UNKNOWN","direct_through":None,
                              "conditional_ranks":[],"points_rule":None})
        hold=s.shadow_strategy_intervals(missing,[A])
        self.assertEqual(hold["state"],"HOLD_POINTS_OR_PROGRAM_UNKNOWN")

    def test_no_postcutoff_mass_or_different_source_sha(self):
        c=context()
        for p in [
            candidate("X",[1,0,0,0,0,0,0],
                      observed="2026-11-17T11:01:00+09:00"),
            dict(candidate("X",[1,0,0,0,0,0,0]),input_sha256="d"*64),
        ]:
            with self.assertRaisesRegex(s.RoundError,"SCENARIO_POST_CUTOFF_OR_INPUT_MISMATCH"):
                s.shadow_strategy_intervals(c,[p])
        with self.assertRaisesRegex(s.RoundError,"SCENARIO_UNCALIBRATED_MASS_INVALID"):
            s.shadow_strategy_intervals(c,[candidate("X",[1,1,0,0,0,0,0])])

    def test_private_sidecar_freeze_create_once_and_readback(self):
        c=context()
        with TemporaryDirectory() as root:
            p=Path(root)/"research-sidecar.json"
            proof=s.freeze_context_once(p,c)
            self.assertEqual(proof,s.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with self.assertRaisesRegex(s.RoundError,"PRIVATE_CREATE_ONCE"):
                s.freeze_context_once(p,c)

    def test_no_source_fetch_result_or_original_ranking_changes(self):
        p=s.conditions(context())
        self.assertIsNone(p["win_or_advancement_probability"])
        self.assertIsNone(p["hit_at_1_uplift"])
        self.assertFalse(p["model_promotion_allowed"])
        self.assertFalse(p["candidate_top12_reranked"])


if __name__=="__main__":
    unittest.main()
