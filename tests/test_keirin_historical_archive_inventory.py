"""Synthetic classification tests, zero real personal/provider input in CI."""
from copy import deepcopy
import unittest

from race_ai.keirin_historical_archive_inventory import (
    inspect_archive_document, private_batch_inventory, HistoricalInventoryError
)
from tests.test_keirin_pr71_model_adapter import make_sources


class HistoricalInputInventoryTests(unittest.TestCase):
    def test_legacy_top8_76_are_not_four_model_scores(self):
        original={"date_jst":"2026-11-03",
                  "source_version":"20261103-am-reference-v1",
                  "races":[{"baseline_top8":["1-2-3"]*8} for _ in range(76)]}
        out=inspect_archive_document(original)
        self.assertEqual(out["historic_race_count"],76)
        self.assertFalse(out["ready_for_pr71_asof_comparison"])
        self.assertEqual(out["original_pr71_four_model_input_count"],0)

    def test_other_model_full_210_is_not_the_four_existing_models(self):
        out=inspect_archive_document({
            "schema":"MATS2R_RESEARCH_SCENARIO_PREDICTION_V1",
            "all_210":[{} for _ in range(210)]})
        self.assertEqual(out["source_kind"],"OTHER_MODEL_210_RANK_RESEARCH")
        self.assertFalse(out["ready_for_pr71_asof_comparison"])
        self.assertEqual(out["historic_race_count"],1)

    def test_sparse_riders_does_not_count_as_a_347_item_original(self):
        out=inspect_archive_document({
            "schema":"RACE_AI_KEIRIN_REAL_RIDER_SHADOW_ONE_SHOT_V1",
            "riders":[{"race_score":80+i} for i in range(7)]})
        self.assertEqual(out["observed_riders"],7)
        self.assertEqual(out["original_pr71_four_model_input_count"],0)

    def test_full_research_model_shape_still_requires_independent_source_checks(self):
        source=make_sources()[0]
        assessed=inspect_archive_document(source)
        self.assertEqual(assessed["expected_required_rider_observations"],84)
        self.assertEqual(assessed["required_environment_observations"],9)
        self.assertEqual(assessed["missing_rider_required_observations"],0)
        self.assertEqual(assessed["missing_environment_observations"],0)
        self.assertFalse(assessed["complete_field_shapes_present"])
        self.assertFalse(assessed["ready_for_pr71_asof_comparison"])

    def test_missing_required_field_rejected_and_never_filled(self):
        source=make_sources()[0]
        source["facts"]["pr71_evidenced_snapshot"]["participants"][0][
            "features"].pop("sprint_acceleration")
        out=inspect_archive_document(source)
        self.assertEqual(out["missing_rider_required_observations"],1)
        self.assertEqual(out["missing"],"REQUIRED_PR71_INPUTS_MISSING")

    def test_batch_is_safe_counts_and_hashes_only(self):
        docs=[
            {"date_jst":"2026-11-03",
             "source_version":"20261103-am-reference-v1",
             "races":[{"baseline_top8":["1-2-3"]*8}]},
            {"schema":"MATS2R_RESEARCH_SCENARIO_PREDICTION_V1",
             "all_210":[{} for _ in range(210)]},
            {"schema":"RACE_AI_KEIRIN_REAL_RIDER_SHADOW_ONE_SHOT_V1",
             "riders":[{"name":"PRIVATE_SOURCE_NAME"} for _ in range(7)]}
        ]
        a=private_batch_inventory(docs)
        self.assertEqual(a["archived_historic_race_references"],3)
        self.assertEqual(a["pr71_real_full_sources_admitted"],0)
        self.assertNotIn("PRIVATE_SOURCE_NAME",str(a))
        self.assertFalse(a["source_bytes_logged"])

    def test_sourced_sparse_riders_report_7_of_84_only_and_no_promotion(self):
        from tests.test_keirin_historical_sparse_feature_probe import source
        doc=source()
        row=inspect_archive_document(doc)
        self.assertEqual(row["strict_sparse_probe_status"],"CANDIDATES_ONLY")
        self.assertEqual(row["candidate_feature_counts"][
            "required_candidates_normalized_not_admitted"],7)
        self.assertEqual(row["candidate_feature_counts"][
            "required_slots_not_supported"],77)
        self.assertEqual(row["candidate_feature_counts"][
            "environment_candidates"],0)
        batch=private_batch_inventory([doc])
        self.assertEqual(batch[
            "sparse_required_model_slots_reconstructed_as_candidates"],7)
        self.assertEqual(batch["pr71_real_full_sources_admitted"],0)
        self.assertFalse(row["ready_for_pr71_asof_comparison"])

    def test_second_race_reconstruction_from_other_model_still_blocks_pr71(self):
        from tests.test_keirin_historical_sparse_feature_probe import second_reference
        source=second_reference()
        source["all_210"]=[{} for _ in range(210)]
        one=inspect_archive_document(source)
        self.assertEqual(one["strict_second_race_probe_status"],
                         "CANDIDATES_ONLY")
        self.assertEqual(one["candidate_feature_counts"][
            "required_candidates_normalized_not_admitted"],14)
        self.assertEqual(one["candidate_feature_counts"][
            "required_slots_not_supported"],70)
        self.assertFalse(one["ready_for_pr71_asof_comparison"])
        batch=private_batch_inventory([source])
        self.assertEqual(batch[
            "observed_required_model_slots_reconstructed_as_candidates"],14)
        self.assertEqual(batch["pr71_real_full_sources_admitted"],0)

    def test_invalid_historical_row_count_fail_closed(self):
        with self.assertRaisesRegex(HistoricalInventoryError,"RANK_COUNT"):
            inspect_archive_document({
                "schema":"MATS2R_RESEARCH_SCENARIO_PREDICTION_V1",
                "all_210":[{}]*209})


if __name__=="__main__":
    unittest.main()
