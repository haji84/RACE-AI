"""Real transcribed finish order, no fictitious same-line following labels."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from race_ai import keirin_real_pair_finish_outcome as final
from race_ai import keirin_real_line_evidence as planned


BASE=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"2026-11-18"


def load(name):
    return json.loads((BASE/name).read_text(encoding="utf-8"))


def docs():
    return (load("keirin_takeo_public_planned_pairs_v1.json"),
            load("keirin_takeo_public_pair_finishes_v1.json"))


class RealPairFinishResearch(unittest.TestCase):
    def test_two_referenced_races_join_to_real_final_order_not_tactical_labels(self):
        a,b=docs()
        out=final.join_planned_and_finishes(
            a,b,as_of="2026-11-19T08:00:00+09:00")
        self.assertEqual(out["planned_co_appearance_rows"],2)
        self.assertEqual(out["co_finish_1st_2nd_count"],1)
        self.assertEqual(out["rows"][0]["leader_finish_rank"],1)
        self.assertEqual(out["rows"][0]["follower_finish_rank"],2)
        self.assertEqual(out["rows"][1]["leader_finish_rank"],6)
        self.assertEqual(out["rows"][1]["follower_finish_rank"],3)
        self.assertEqual(out["validated_on_track_follow_outcome_labels"],0)
        self.assertFalse(out["eligible_as_C_model_held_gapped_switched_history"])
        self.assertFalse(out["eligible_for_formal_A_B_C_prospective_result"])

    def test_date_only_sources_not_backfilled_to_same_day(self):
        a,b=docs()
        out=final.join_planned_and_finishes(
            a,b,as_of="2026-11-18T23:59:59+09:00")
        self.assertEqual(out["status"],"HOLD_SOURCE_DATE_NOT_YET_AVAILABLE")
        self.assertEqual(out["planned_co_appearance_rows"],0)
        self.assertIsNone(out["rows"][0]["leader_finish_rank"])

    def test_tampered_winning_triple_rejected(self):
        a,b=docs()
        b["races"][1]["winner_3ren_tan"]=[7,2,4]
        with self.assertRaisesRegex(final.PairFinishError,
                                    "WINNING_TRIPLE_NOT_MATCH"):
            final.join_planned_and_finishes(
                a,b,as_of="2026-11-19T08:00:00+09:00")

    def test_result_not_used_as_held_label(self):
        a,b=docs()
        b["races"][0]["tactical_follow_outcome"]="HELD"
        with self.assertRaisesRegex(final.PairFinishError,"NOT_SIGNED_TACTICAL"):
            final.join_planned_and_finishes(
                a,b,as_of="2026-11-19T08:00:00+09:00")

    def test_pair_car_mismatch_rejected(self):
        a,b=docs()
        b["races"][0]["follower_car"]=6
        with self.assertRaisesRegex(final.PairFinishError,
                                    "PLANNED_AND_FINISH_RIDER_PAIR_MISMATCH"):
            final.join_planned_and_finishes(
                a,b,as_of="2026-11-19T08:00:00+09:00")

    def test_fake_independent_official_attestation_rejected(self):
        a,b=docs()
        b["races"][1]["organizer_result_independently_attested"]=True
        with self.assertRaisesRegex(final.PairFinishError,
                                    "NOT_SIGNED_TACTICAL"):
            final.join_planned_and_finishes(
                a,b,as_of="2026-11-19T08:00:00+09:00")

    def test_well_known_host_but_wrong_race_is_not_evidence(self):
        a,b=docs()
        b["races"][0]["public_result_urls"][0]=(
            "https://www.keirin-mobile.jp/top/result.php?"
            "date=20261110&jcode=84&race=02")
        with self.assertRaisesRegex(final.PairFinishError,
                                    "SOURCE_NOT_BOUND_TO_RACE"):
            final.join_planned_and_finishes(
                a,b,as_of="2026-11-19T08:00:00+09:00")

    def test_duplicate_row_rejected(self):
        a,b=docs()
        b["races"].append(deepcopy(b["races"][0]))
        with self.assertRaisesRegex(final.PairFinishError,"DUPLICATE"):
            final.validate_results(b)


if __name__=="__main__":
    unittest.main()
