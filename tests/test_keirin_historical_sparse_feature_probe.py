"""Synthetic-only historical reconstruction of observed KEIRIN rider fields."""
from copy import deepcopy
import json
import math
import unittest

from race_ai.keirin_historical_sparse_feature_probe import (
    SCHEMA, HistoricalSparseProbeError, probe_saved_sparse_research,
    probe_saved_second_race_reference
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



def second_reference():
    lines=[[1,3,5],[2,4],[6,7]]
    role={n:(g[0],i) for g in lines for i,n in enumerate(g)}
    return {
        "schema":"MATS2R_RESEARCH_SCENARIO_PREDICTION_V1",
        "status":"research_only_uncalibrated_no_official_frozen_proof",
        "race":{
            "date_jst":"2026-11-08","venue":"松山","race_number":2,
            "as_of_jst":"2026-11-08T20:43:43+09:00",
            "sales_cutoff_jst":"20:55",
            "line_assumptions":lines,
        },
        "methodology":{
            "independent_validation":False,
            "calibrated":False,
            "source_admission_verified_for_RACE_AI":False,
        },
        "participants":[{
            "n":n,"name":f"fictional_{n}",
            "p":70+n,"w":2,"nr":20+n,"p3":6,"b":n,
            "esc":2,"mak":1,"sashi":1,"mark":1,
            "recent":[1,2,3,4,5,6],
            "line":role[n][0],"role":role[n][1],
        } for n in range(1,8)],
    }


class SecondRaceResearchInputTests(unittest.TestCase):
    def test_reconstruct_14_of_84_not_210_pr71_predictions(self):
        a=probe_saved_second_race_reference(second_reference())
        summary=a["public_summary"]
        count=summary["counts"]
        self.assertEqual(count["model_required_feature_slots"],84)
        self.assertEqual(count["required_candidates_normalized_not_admitted"],14)
        self.assertEqual(count["required_slots_not_supported"],70)
        self.assertEqual(count["environment_candidates"],0)
        self.assertEqual(count["optional_candidate_slots"],49)
        self.assertEqual(count["all_candidate_slots"],63)
        one=a["private_candidate_values_by_rider"][1]
        self.assertAlmostEqual(one["ability"],71/171)
        self.assertAlmostEqual(one["consistency"],6/21)
        self.assertAlmostEqual(one["recent_win_form"],2/21)
        self.assertFalse(summary["full_pr71_four_model_replay_eligible"])
        self.assertFalse(summary["existing_pr71_model_executed"])
        self.assertTrue(summary["historical_210_from_other_model_not_PR71"])
        self.assertNotIn("fictional_1",json.dumps(summary))

    def test_refuse_post_deadline_source_and_fake_rights(self):
        for patch in [
            ("race","as_of_jst","2026-11-08T20:55:00+09:00"),
            ("methodology","source_admission_verified_for_RACE_AI",True),
        ]:
            source=second_reference()
            source[patch[0]][patch[1]]=patch[2]
            with self.assertRaises(HistoricalSparseProbeError):
                probe_saved_second_race_reference(source)

    def test_no_fabricated_stat_and_no_lineup_mismatch(self):
        for field,value in [
            ("p3",100),("w",100),("nr",0),("p",float("nan")),
            ("b",-1),("sashi",1.5),("recent",[1,2]),
        ]:
            source=second_reference()
            source["participants"][0][field]=value
            with self.subTest(field=field):
                with self.assertRaises(HistoricalSparseProbeError):
                    probe_saved_second_race_reference(source)
        source=second_reference()
        source["participants"][0]["line"]=2
        with self.assertRaisesRegex(HistoricalSparseProbeError,
                                    "LINE_ROLE_CONFLICT"):
            probe_saved_second_race_reference(source)



class OwnerPrivateHistoricalProbeCliTests(unittest.TestCase):
    def test_only_counts_and_sha_are_printed_for_real_shaped_sources(self):
        import tempfile
        from pathlib import Path
        import io
        from contextlib import redirect_stdout
        from scripts.keirin_historical_sparse_probe import main
        with tempfile.TemporaryDirectory() as directory:
            sourcefile=Path(directory)/"research.json"
            sourcefile.write_text(json.dumps(second_reference()),
                                  encoding="utf-8")
            buffer=io.StringIO()
            with redirect_stdout(buffer):
                outcome=main(["--owner-archive",str(sourcefile)])
            self.assertEqual(outcome,0)
            report=json.loads(buffer.getvalue())
            self.assertEqual(report["counts"][
                "required_candidates_normalized_not_admitted"],14)
            self.assertNotIn("fictional_1",buffer.getvalue())
            self.assertNotIn("race_score",buffer.getvalue())
            self.assertFalse(report["existing_pr71_model_executed"])

    def test_invalid_json_refuses_without_exposing_private_bytes(self):
        import tempfile
        from pathlib import Path
        import io
        from contextlib import redirect_stdout
        from scripts.keirin_historical_sparse_probe import main
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/"bad.json"
            for body in ('[]','{"x":1,"x":2}',"PRIVATE_INVALID_FORMAT"):
                file.write_text(body,encoding="utf-8")
                output=io.StringIO()
                with redirect_stdout(output):
                    code=main(["--owner-archive",str(file)])
                self.assertEqual(code,2)
                self.assertNotIn(body,output.getvalue())
                self.assertIn("HISTORICAL_SOURCE_RECONSTRUCTION_BLOCKED",
                              output.getvalue())

if __name__=="__main__":
    unittest.main()
