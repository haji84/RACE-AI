"""Fictional context evidence. Never use actual rider data in public CI."""
import unittest

from race_ai.keirin_historical_context_gates import (
    compare_racecard_samples, contextual_track_geometry,
    classify_weather_evidence, classify_prior_race_video,
    HistoricalContextError
)

CUTOFF="2030-01-15T21:00:00+09:00"


def dummy_counts(n=7,extra=False):
    return [{
        "number":i,
        "first_reported_starts":21,
        "other_reported_starts":24 if extra else 21,
        "other_wins":5,
        "other_seconds":4,
        "other_thirds":2,
        "other_unplaced":10,
    } for i in range(1,n+1)]


class HistoricalContextGateTests(unittest.TestCase):
    def test_unclassified_finish_status_is_not_invented_loss(self):
        report=compare_racecard_samples(
            dummy_counts(extra=True),race_id="203001157507",
            first_source_url="https://example.invalid/private-research",
            other_source_url="https://example.invalid/past-racecard")
        self.assertEqual(report["denominators_disagree_count"],7)
        self.assertEqual(report["uncategorized_finish_statuses_count"],21)
        self.assertEqual(report["state"],"HOLD_SOURCE_DENOMINATOR_DEFINITION")
        self.assertFalse(report["safe_to_merge_sources_into_pr71_without_review"])
        self.assertFalse(report["reason_for_residual_finishes_verified"])
        self.assertFalse(report["source_publication_before_target_cutoff_independently_proven"])

    def test_even_consistent_rider_counts_do_not_prove_publication_time(self):
        report=compare_racecard_samples(
            dummy_counts(),race_id="203001157502",
            first_source_url="https://example.invalid/first",
            other_source_url="https://example.invalid/second")
        self.assertEqual(report["denominators_disagree_count"],0)
        self.assertEqual(report["uncategorized_finish_statuses_count"],0)
        self.assertEqual(report["state"],"ARITHMETICALLY_CONSISTENT_ASOF_UNVERIFIED")

    def test_oversize_outcomes_and_duplicate_rider_rejected(self):
        sample=dummy_counts()
        sample[0]["other_unplaced"]=300
        with self.assertRaisesRegex(HistoricalContextError,
                                    "FINISH_COUNTS_EXCEED_STARTS"):
            compare_racecard_samples(
                sample,race_id="203001157507",
                first_source_url="https://example.invalid/first",
                other_source_url="https://example.invalid/second")
        sample=dummy_counts()
        sample[1]["number"]=1
        with self.assertRaisesRegex(HistoricalContextError,
                                    "DUPLICATED_OR_INVALID"):
            compare_racecard_samples(
                sample,race_id="203001157507",
                first_source_url="https://example.invalid/first",
                other_source_url="https://example.invalid/second")

    def test_venue_static_geometry_does_not_infer_rider_bank_fitness(self):
        sample={
            "venue":"松山",
            "source_url":"https://example.invalid/past-geometric-spec",
            "source_document_date":"2026-08-06",
            "track_length_m":400,
            "straight_length_m":58.6,
            "center_cant_deg":34.03,
            "home_width_m":10.3,
            "surface_resurfaced_month":"2026-02",
        }
        out=contextual_track_geometry(sample,race_cutoff="2026-11-08T20:55:00+09:00")
        self.assertTrue(out["surface_resurfaced_prior_to_race"])
        self.assertFalse(out["pr71_rider_bank_fit_admitted"])
        self.assertFalse(out["pr71_bank_steepness_normalization_preagreed"])
        bad=dict(sample,source_document_date="2027-01-01")
        with self.assertRaisesRegex(HistoricalContextError,
                                    "VENUE_METADATA_CREATED_AFTER_RACE"):
            contextual_track_geometry(bad,race_cutoff="2026-11-08T20:55:00+09:00")

    def test_weather_model_initialization_is_not_public_availability(self):
        earlier=classify_weather_evidence(
            issued_or_initialised_at="2026-11-07T06:00:00+00:00",
            first_available_at=None,
            forecast_valid_at="2026-11-08T21:00:00+09:00",
            race_cutoff="2026-11-08T20:55:00+09:00")
        self.assertTrue(earlier["weather_run_initialised_before_cutoff"])
        self.assertTrue(earlier["research_asof_candidate_only"])
        self.assertFalse(earlier["asof_model_feature_accepted"])
        # Even a caller-provided release claim is NOT independent source proof.
        claimed=classify_weather_evidence(
            issued_or_initialised_at="2026-11-07T06:00:00+00:00",
            first_available_at="2026-11-07T12:00:00+00:00",
            forecast_valid_at="2026-11-08T21:00:00+09:00",
            race_cutoff="2026-11-08T20:55:00+09:00",
            provider_availability_attested=True)
        self.assertTrue(claimed["release_timing_attestation_claimed"])
        self.assertFalse(claimed["asof_model_feature_accepted"])

    def test_jma_later_station_and_same_race_video_cannot_train(self):
        after=classify_weather_evidence(
            issued_or_initialised_at="2026-11-08T21:00:00+09:00",
            first_available_at="2026-11-09T00:00:00+09:00",
            forecast_valid_at="2026-11-08T21:00:00+09:00",
            race_cutoff="2026-11-08T20:55:00+09:00",
            weather_kind="JMA_FINAL_HOURLY_OBSERVED")
        self.assertFalse(after["asof_model_feature_accepted"])
        current=classify_prior_race_video(
            video_race_end_at="2026-11-08T21:08:00+09:00",
            target_cutoff_at="2026-11-08T20:55:00+09:00",
            actual_frames_available=True,
            replay_segments_identified=True,
            source_rights_verified=True,
            video_first_available_at="2026-11-08T21:11:00+09:00")
        self.assertFalse(current["eligible_as_historical_training_candidate"])
        self.assertTrue(current["result_race_same_as_target_forbidden"])

    def test_prior_video_without_real_frames_cannot_invent_acceleration(self):
        sample=classify_prior_race_video(
            video_race_end_at="2026-11-01T21:20:00+09:00",
            target_cutoff_at="2026-11-08T20:55:00+09:00",
            actual_frames_available=False,
            replay_segments_identified=False,
            source_rights_verified=False,
            video_first_available_at=None)
        self.assertFalse(sample["eligible_as_historical_training_candidate"])
        self.assertIsNone(sample["measured_acceleration_mps2"])
        self.assertIsNone(sample["measured_stamina_score"])
        self.assertFalse(sample["real_previous_race_lap_1_4_frame_grounding"])


if __name__=="__main__":
    unittest.main()
