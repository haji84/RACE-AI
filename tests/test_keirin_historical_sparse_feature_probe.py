"""Synthetic-only historical reconstruction of observed KEIRIN rider fields."""
from copy import deepcopy
import json
import math
import unittest

from race_ai.keirin_historical_sparse_feature_probe import (
    SCHEMA, HistoricalSparseProbeError, probe_saved_sparse_research
)


def source(n=7):
    return {
        "schema":"RACE_AI_KEIRIN_REAL_RIDER_SHADOW_ONE_SHOT_V1",
        "source_type":"assistant_current_turn_web_page_manual_numeric_facts",
        "event_date_jst":"2030-01-15",
        "race_id":"203001157507",
        "issued_at_jst":"2030-01-15T09:20:00+09:00",
        "published_sales_cutoff_at":"2030-01-15T10:00:00+09:00",
        "event_cutoff_independently_verified":False,
        "independent_pre_cutoff_timestamp_receipt":None,
        "all_347_checked_in_this_local_run":False,
        "full_PR71_model_was_executed":False,
        "lineups_only_expected":[[1,2],[3,4],[5,6,7]]+
                                ([[8,9]] if n==9 else []),
        "riders":[{
            "number":i,"name":f"fictional_rider_{i}",
            "observed_4mo_starts":20+i,"race_score":80+i,
            "B_count":i,"escape_count":i%5,"makuri_count":i%4,
        } for i in range(1,n+1)],
    }


class HistoricalSparseFeatureProofTests(unittest.TestCase):
    def test_seven_rider_provenance_limited_counts_are_not_four_model_forecasts(self):
        report=probe_saved_sparse_research(source())
        summary=report["public_summary"]
        self.assertEqual(summary["schema"],SCHEMA)
        stats=summary["counts"]
        self.assertEqual(stats["source_observed_riders"],7)
        self.assertEqual(stats["model_required_features_per_rider"],12)
        self.assertEqual(stats["model_required_feature_slots"],84)
        self.assertEqual(stats["required_candidates_normalized_not_admitted"],7)
        self.assertEqual(stats["required_slots_not_supported"],77)
        self.assertEqual(stats["environment_required_slots"],9)
        self.assertEqual(stats["environment_candidates"],0)
        self.assertEqual(stats["optional_candidate_slots"],35)
        self.assertEqual(stats["all_candidate_slots"],42)
        self.assertFalse(summary["eligible_for_pr71_four_model_replay"])
        self.assertFalse(summary["model_inference_executed"])
        self.assertIsNone(summary["official_predictive_performance"])
        self.assertNotIn("fictional_rider_",json.dumps(summary))
        self.assertEqual(set(report["private_candidate_values_by_rider"]),set(range(1,8)))
        one=report["private_candidate_values_by_rider"][1]
        self.assertAlmostEqual(one["ability"],81/181)
        self.assertAlmostEqual(one["recent_points"],81/181)
        self.assertAlmostEqual(one["back_count_form"],1/21)
        self.assertAlmostEqual(one["hsb_form"],1/21)
        self.assertAlmostEqual(one["escape_style"],1/21)
        self.assertAlmostEqual(one["makuri_style"],1/21)

    def test_nine_rider_504_universe_compatibility_but_no_winner_prediction(self):
        r=probe_saved_sparse_research(source(9))["public_summary"]
        self.assertEqual(r["counts"]["model_required_feature_slots"],108)
        self.assertEqual(r["counts"]["required_slots_not_supported"],99)
        self.assertEqual(r["counts"]["optional_candidate_slots"],45)
        self.assertFalse(r["eligible_for_pr71_four_model_replay"])

    def test_invalid_capture_time_and_false_claims_are_rejected(self):
        for key,value in [
            ("issued_at_jst","2030-01-15T10:00:00+09:00"),
            ("event_cutoff_independently_verified",True),
            ("independent_pre_cutoff_timestamp_receipt","not-a-witness"),
            ("full_PR71_model_was_executed",True),
            ("all_347_checked_in_this_local_run",True),
            ("source_type","some_post_result_invention"),
        ]:
            record=source()
            record[key]=value
            with self.subTest(key=key):
                with self.assertRaises(HistoricalSparseProbeError):
                    probe_saved_sparse_research(record)

    def test_missing_bad_statistics_do_not_turn_into_assumed_zero(self):
        for key,value in [
            ("observed_4mo_starts",0),
            ("B_count",300),
            ("escape_count",-1),
            ("race_score",float("nan")),
            ("race_score",float("inf")),
            ("makuri_count",2.5),
        ]:
            record=source()
            record["riders"][0][key]=value
            with self.subTest(key=key):
                with self.assertRaises(HistoricalSparseProbeError):
                    probe_saved_sparse_research(record)

    def test_roster_lineup_unknown_or_mutated_raises_not_fills(self):
        bad=source()
        bad["lineups_only_expected"]=[[1,2],[3,4],[5,6]]
        with self.assertRaisesRegex(HistoricalSparseProbeError,"LINEUP"):
            probe_saved_sparse_research(bad)
        bad=source()
        bad["riders"][1]["number"]=1
        with self.assertRaisesRegex(HistoricalSparseProbeError,"DUPLICATE"):
            probe_saved_sparse_research(bad)
        bad=source()
        bad["riders"][1]["actual_result_1st"]=True
        with self.assertRaisesRegex(HistoricalSparseProbeError,"RIDER_FIELDS"):
            probe_saved_sparse_research(bad)

    def test_model_input_12_required_and_9_environment_remain_missing(self):
        check=probe_saved_sparse_research(source())["public_summary"]
        absent=set(check["required_feature_names_without_source"])
        for key in ("sprint_acceleration","bank_fit","finishing_power",
                    "stamina","line_coordination","attack_success",
                    "tactical_adaptability"):
            self.assertIn(key,absent)
        self.assertTrue(check["normalized_feature_candidates_are_not_admitted_model_inputs"])
        self.assertEqual(check["state"],
                         "BLOCKED_SOURCE_PUBLISHED_AT_AND_PER_PURPOSE_RIGHTS_NOT_ATTESTED")


if __name__=="__main__":
    unittest.main()
