"""Synthetic A/B shadows against the ORIGINAL retained bulk settlement engine."""
from copy import deepcopy
import json
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_six_way_saved_ab_score import score_ab_view, score_ab_views, SCHEMA
from tests.test_racer_result_bridge import saved_view
from tests.test_retained_model_pdca_audit import HistoricalModelPdcaAudit


def vector(leading):
    tickets = [f"{a}-{b}-{c}" for a in range(1,7)
               for b in range(1,7) for c in range(1,7)
               if len({a,b,c}) == 3]
    weights = {t:(10 if t.startswith(str(leading)+"-") else 1) for t in tickets}
    scale = sum(weights.values())
    pairs = [{"ticket":t,"score":v/scale} for t,v in weights.items()]
    ordered = sorted(pairs,key=lambda p:(-p["score"],p["ticket"]))[:8]
    return pairs,[[int(c) for c in r["ticket"].split("-")] for r in ordered]


def fixture(*,settled=True):
    v = saved_view()
    row = v["records"][0]
    a = row["prediction"]
    a["stage"] = "P1"
    a["full_120"], a["ordered_top8"] = vector(1)
    a["race_id"] = row["race_id"]
    b = deepcopy(a)
    b["model_id"] = "boat-sixway-tactics-research-not-production"
    b["variant"] = "B_SIX_COURSE_TACTICS"
    b["research_variant"] = "B_SIX_COURSE_TACTICS"
    b["research_schema"] = "RACE_AI_BOAT_SIXWAY_OVERLAY_V1"
    b["full_120"], b["ordered_top8"] = vector(2)
    b["baseline_prediction_sha256"] = digest(a)
    b["six_way_context"] = {"race_id":row["race_id"],"research_stage":"P1"}
    b["research_feature_sha256"] = digest(b["six_way_context"])
    row["comparison_predictions"] = [b]
    if settled:
        v = HistoricalModelPdcaAudit().capture(v)
    return v


class SavedABTests(unittest.TestCase):
    def test_retained_final_a_hit_b_miss_via_existing_bulk_engine(self):
        v = fixture()
        old = deepcopy(v)
        from race_ai import verified_bulk_backtest as bulk
        from unittest.mock import patch
        with patch.object(bulk, "settle", wraps=bulk.settle) as settle:
            out = score_ab_view(v, authenticated=True)
        self.assertEqual(settle.call_count, 2)
        self.assertEqual(v, old)
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["compared_ab_races"], 1)
        self.assertEqual(out["by_variant"]["A_FROZEN_BASELINE"]["hit_count"], 1)
        self.assertEqual(out["by_variant"]["B_SIX_COURSE_TACTICS"]["hit_count"], 0)
        self.assertEqual(out["by_variant"]["A_FROZEN_BASELINE"]["invested_yen"], 800)
        self.assertEqual(out["by_variant"]["A_FROZEN_BASELINE"]["received_yen"], 1250)
        self.assertEqual(out["by_variant"]["B_SIX_COURSE_TACTICS"]["received_yen"], 0)
        self.assertEqual(out["by_variant"]["A_FROZEN_BASELINE"]["probability_scored_races"],1)
        self.assertLess(out["by_variant"]["A_FROZEN_BASELINE"]["mean_log_loss"],
                        out["by_variant"]["B_SIX_COURSE_TACTICS"]["mean_log_loss"])
        self.assertLess(out["by_variant"]["A_FROZEN_BASELINE"]["mean_brier120"],
                        out["by_variant"]["B_SIX_COURSE_TACTICS"]["mean_brier120"])
        self.assertFalse(out["real_purchase_result_available"])
        self.assertEqual(out["provider_gets"], 0)
        self.assertNotIn(v["records"][0]["race_id"], json.dumps(out))

    def test_multiwinner_high_payout_capture_only_if_selected_ticket_is_high(self):
        from tests.test_boat_sp_settlement import document
        v = fixture(settled=False)
        d = document()
        d["maindata"]["teiinfolist"][1]["chk"] = "1"
        d["maindata"]["teiinfolist"][2]["chk"] = "3"
        d["maindata"]["infolist3t"] = [
            {"winno":"1-2-3","dividend":"1250円"},
            {"winno":"2-1-3","dividend":"15000円"},
        ]
        v = HistoricalModelPdcaAudit().capture(v, doc=d)
        out = score_ab_view(v, authenticated=True)
        self.assertEqual(out["compared_ab_races"],1)
        self.assertEqual(out["high_payout_events"],1)
        self.assertEqual(out["by_variant"]["A_FROZEN_BASELINE"]["high_payout_captured"],0)
        self.assertEqual(out["by_variant"]["B_SIX_COURSE_TACTICS"]["high_payout_captured"],1)
        self.assertEqual(out["by_variant"]["A_FROZEN_BASELINE"]["probability_scored_races"],0)
        self.assertEqual(out["by_variant"]["B_SIX_COURSE_TACTICS"]["probability_scored_races"],0)

    def test_full_refund_does_not_enter_either_miss_denominator(self):
        from unittest.mock import patch
        view = fixture()
        fake_a = {"status":"FULL_REFUND"}
        fake_b = {"status":"MISS"}
        with patch("race_ai.boat_six_way_saved_ab_score._score_using_existing_bulk_engine",
                   side_effect=[fake_a, fake_b]):
            out = score_ab_view(view, authenticated=True)
        self.assertEqual(out["compared_ab_races"],0)
        self.assertEqual(out["hold_reasons"],{"HOLD_FULL_REFUND_NOT_A_MISS":1})
        self.assertEqual(out["by_variant"]["A_FROZEN_BASELINE"]["hit_count"],0)
        self.assertEqual(out["by_variant"]["B_SIX_COURSE_TACTICS"]["invested_yen"],0)

    def test_no_b_or_unsettled_result_holds_without_money(self):
        v = saved_view()
        v["records"][0]["prediction"]["stage"] = "P1"
        out = score_ab_view(v, authenticated=True)
        self.assertEqual(out["compared_ab_races"],0)
        self.assertEqual(out["hold_reasons"],{"HOLD_SAME_RACE_P1_A_B_NOT_FROZEN":1})
        self.assertEqual(out["by_variant"]["A_FROZEN_BASELINE"]["invested_yen"],0)
        pending = fixture(settled=False)
        out = score_ab_view(pending,authenticated=True)
        self.assertEqual(out["compared_ab_races"],0)
        self.assertEqual(out["hold_reasons"],{"HOLD_OFFICIAL_RESULT_NOT_FINAL":1})

    def test_b_after_cutoff_is_not_retrospectively_scoreable(self):
        view = fixture()
        view["records"][0]["comparison_predictions"][0]["persisted_at"] = "2026-11-07T11:00:00+09:00"
        out = score_ab_view(view, authenticated=True)
        self.assertEqual(out["compared_ab_races"],0)
        self.assertEqual(out["hold_reasons"],{"HOLD_PRE_CUTOFF_SAVED_FULL120_OR_TOP8_INVALID":1})

    def test_baseline_or_tactics_hash_mismatch_is_hold(self):
        for field in ("baseline_prediction_sha256","research_feature_sha256"):
            with self.subTest(field=field):
                view = fixture()
                view["records"][0]["comparison_predictions"][0][field] = "0"*64
                out = score_ab_view(view, authenticated=True)
                self.assertEqual(out["compared_ab_races"],0)
                self.assertEqual(out["hold_reasons"],{"HOLD_SAME_RACE_P1_A_B_NOT_FROZEN":1})

    def test_incomplete_probability_vector_is_hold(self):
        view = fixture()
        view["records"][0]["comparison_predictions"][0]["full_120"] = []
        self.assertEqual(score_ab_view(view, authenticated=True)["compared_ab_races"],0)

    def test_aggregate_does_not_double_count_same_race(self):
        v = fixture()
        a = score_ab_views([v], authenticated=True)
        self.assertEqual(a["compared_ab_races"], 1)
        self.assertEqual(a["by_variant"]["A_FROZEN_BASELINE"]["invested_yen"], 800)
        self.assertEqual(a["by_variant"]["B_SIX_COURSE_TACTICS"]["received_yen"], 0)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SAVED_RACE_ACROSS_VIEWS"):
            score_ab_views([v, v], authenticated=True)

    def test_declaration_is_not_authentication(self):
        with self.assertRaisesRegex(ValueError, "AUTHENTICATED_REAL_SAVED_VIEW_REQUIRED"):
            score_ab_view(fixture(), authenticated=False)


if __name__ == "__main__":
    unittest.main()
