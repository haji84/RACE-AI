"""Synthetic 7-rider real-observation-mode tests; no web requests."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_real_rider_shadow import (
    MODEL, SparseRealForecastError, forecast_from_real_observations,
    save_private_shadow_once,
)
from race_ai.keirin_owner_manual import (
    PersonalOwnerObservations, PERSONAL_MARKER,
)
from race_ai.keirin_allowed_delivery import assemble_permitted_pre_race
from test_keirin_owner_manual import manual_fixture

ISSUED = "2030-01-15T09:20:00+09:00"
RID = "keirin:2030-01-15:fictional-venue:1"


def fixture():
    packet = manual_fixture()
    # Noncalibrated shadow needs real observed scores, S/H/B, style counts,
    # lineup, and the roster. All unrelated observations may be missing.
    retain = {"race/line_order_all_riders",
              "race/all_entrants_and_vehicle_numbers"}
    for n in range(1,8):
        for suffix in (
            "identity_number_and_grade", "race_score",
            "back_B_count", "style_escape", "style_makuri",
        ):
            retain.add("rider/%d/%s" % (n,suffix))
    packet["observations"] = [
        obs for obs in packet["observations"] if obs["key"] in retain
    ]
    # All seven entrants have sourced data even if PR71 is missing features.
    return packet


def grants():
    return PersonalOwnerObservations(
        source_hosts=["example.invalid"],now=ISSUED)


def execute(packet=None,at=ISSUED):
    return forecast_from_real_observations(
        fixture() if packet is None else packet,
        grant_check=grants().allowed,issued_at=at
    )


class SparseRealRiderShadowTests(unittest.TestCase):
    def test_sourced_rider_score_lineups_create_untrained_research_top8(self):
        item=execute()
        self.assertEqual(item["race_id"],RID)
        self.assertEqual(item["model_id"],MODEL)
        self.assertFalse(item["full_pr71_model_ran"])
        self.assertFalse(item["official_prediction"])
        self.assertFalse(item["eligible_for_formal_hit_at_8"])
        self.assertFalse(item["probabilities_calibrated"])
        self.assertEqual(item["all_factor_statuses_checked"],347)
        self.assertGreater(item["unknown_or_unusable_factor_count"],0)
        self.assertGreater(len(item["unverified_critical_keys"]),0)
        self.assertEqual(item["candidate_count"],210)
        self.assertEqual(len(item["ordered_top8"]),8)
        self.assertEqual(len(set(tuple(x) for x in item["ordered_top8"])),8)
        self.assertTrue(all(len(set(x))==3 for x in item["ordered_top8"]))
        self.assertEqual(item["betting_action"],"NONE")

    def test_no_result_or_market_inputs_admitted(self):
        packet=fixture()
        packet["observations"][0]["value"]={"odds":99}
        with self.assertRaises(SparseRealForecastError):
            execute(packet)

    def test_after_close_and_margin_never_predict(self):
        for late in ("2030-01-15T09:59:00+09:00",
                     "2030-01-15T10:00:00+09:00",
                     "2030-01-15T10:00:01+09:00"):
            with self.subTest(late=late):
                with self.assertRaisesRegex(
                        SparseRealForecastError,"NO_PROSPECTIVE"):
                    execute(at=late)

    def test_no_invented_rider_or_unverified_lineup(self):
        packet=fixture()
        packet["observations"]=[
            x for x in packet["observations"]
            if x["key"]!="race/line_order_all_riders"
        ]
        with self.assertRaisesRegex(
                SparseRealForecastError,"MISSING_REAL_OBSERVATION"):
            execute(packet)

    def test_no_unverified_synthetic_ability_score(self):
        packet=fixture()
        packet["observations"]=[
            x for x in packet["observations"]
            if x["key"]!="rider/3/race_score"
        ]
        with self.assertRaisesRegex(
                SparseRealForecastError,"MISSING_REAL_OBSERVATION"):
            execute(packet)

    def test_uncapped_raw_race_score_changes_prospective_ranking(self):
        original=execute()
        packet=fixture()
        next(v for v in packet["observations"]
             if v["key"]=="rider/7/race_score")["value"]=260.5
        adjusted=execute(packet)
        self.assertNotEqual(original["input_sha256"],adjusted["input_sha256"])
        self.assertEqual(adjusted["all_factor_statuses_checked"],347)
        self.assertEqual(adjusted["candidate_count"],210)
        self.assertIn(7,adjusted["ordered_top8"][0])

    def test_optional_missing_is_excluded_globally_not_imputed_zero(self):
        packet=fixture()
        for n in range(1,8):
            if n in (1,2):
                packet["observations"].append({
                    "key":"rider/%d/win_rate"%n,
                    "value":0.30,
                    "source_url":"https://example.invalid/synthetic-rider",
                    "rights_ref":PERSONAL_MARKER,
                    "published_at":"2030-01-15T08:00:00+09:00",
                    "captured_at":"2030-01-15T08:05:00+09:00",
                    "sample_n":20,
                })
        item=execute(packet)
        self.assertFalse(item["used_optional_win_rate_all_riders"])
        self.assertEqual(len(item["ordered_top8"]),8)

    def test_immutable_private_research_does_not_replace_history(self):
        item=execute()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"immutable-shadow.json"
            self.assertTrue(save_private_shadow_once(path,item))
            self.assertFalse(save_private_shadow_once(path,item))
            revised=deepcopy(item)
            revised["ordered_top8"].reverse()
            with self.assertRaisesRegex(
                    SparseRealForecastError,"SHADOW_ORIGINAL_IMMUTABILITY"):
                save_private_shadow_once(path,revised)


if __name__=="__main__":
    unittest.main()
