"""Hand-authored synthetic contracts, never real boat-identification evidence."""
from copy import deepcopy
import importlib
import unittest


MEDIA = "a" * 64


def engine(test):
    try:
        return importlib.import_module("race_ai.boat_video_benchmark")
    except ModuleNotFoundError:
        test.fail("the pure independent-reference benchmark is missing")


def boat(lane, x=10, *, readable=True):
    return {"box": [x, 10, 10, 10], "lane": lane if readable else None,
            "readability": "READABLE" if readable else "UNREADABLE"}


def frame(index=0, *, boats=None, exhaustive=True, partition="DEVELOPMENT", group="shot-a"):
    return {"frame_index": index, "t": index / 10,
            "decoded_frame_sha256": "%064x" % (index + 1),
            "continuity_group": group, "exhaustive": exhaustive, "partition": partition,
            "boats": [boat(1)] if boats is None else boats}


def reference(frames=None, **changes):
    result = {"schema_version": "RACE_AI_BOAT_VIDEO_REFERENCE_V1", "media_sha256": MEDIA,
              "width": 160, "height": 90, "media_class": "SYNTHETIC",
              "reference_class": "CONTROLLED_FIXTURE", "human_verified": False,
              "blind_to_predictions": True, "split_scope": "WHOLE_MEDIA",
              "split_frozen_before_predictions": True, "frames": frames or [frame()]}
    result.update(changes)
    return result


def region(lane, x=10, *, track="T000001"):
    return {"lane": lane, "box": [x, 10, 10, 10], "track_id": track,
            "identity_status": "NUMBER_TEMPORAL_CANDIDATE", "number_evidence": {"number": lane}}


def tracking(ref, predictions=None):
    observations = [{"frame_index": row["frame_index"], "t": row["t"], "scene": 0,
                     "decoded_frame_sha256": row["decoded_frame_sha256"],
                     "regions": [region(1)] if predictions is None else predictions[n]}
                    for n, row in enumerate(ref["frames"])]
    return {"schema_version": "RACE_AI_BOAT_VIDEO_TRACKS_V1", "media_sha256": MEDIA,
            "width": 160, "height": 90, "timeline_source": "MEDIA_PTS",
            "coordinate_space": "REFERENCE_IMAGE_PX", "model_eligible": False,
            "validation_status": "UNVALIDATED", "tracks": [],
            "quality": {"identity_provider": {"detector": {"engine": "INJECTED_DETECTOR"},
                        "number_reader": {"engine": "INJECTED_NUMBER_READER"}},
                        "identity_observations": observations}}


class BoatVideoBenchmarkTests(unittest.TestCase):
    def score(self, ref, predictions=None, **configuration):
        return engine(self).benchmark_identity(tracking(ref, predictions), ref,
                                                configuration=configuration or None)

    def test_swapped_numbers_are_wrong_even_when_both_boxes_are_exact(self):
        ref = reference([frame(boats=[boat(1, 10), boat(2, 40)])])
        report = self.score(ref, [[region(2, 10), region(1, 40)]])
        metrics = report["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["matched_regions"], 2)
        self.assertEqual(metrics["wrong_id_matches"], 2)
        self.assertEqual(metrics["confusion"]["1"]["2"], 1)
        self.assertEqual(metrics["confusion"]["2"]["1"], 1)
        for lane in ("1", "2"):
            self.assertEqual(metrics["lanes"][lane]["precision"], 0.)
            self.assertEqual(metrics["lanes"][lane]["coverage"], 0.)
            self.assertEqual(metrics["lanes"][lane]["false_positives"], 1)
            self.assertEqual(metrics["lanes"][lane]["misses"], 1)
        self.assertEqual(metrics["anonymous_id_switches"], 0)
        self.assertFalse(report["production_eligible"])

    def test_maximum_cardinality_geometry_matching_is_not_greedy(self):
        ref = reference([frame(boats=[boat(1, 10), boat(2, 20)])])
        report = self.score(ref, [[region(2, 14), region(1, 10)]], iou_threshold=.2)
        metrics = report["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["matched_regions"], 2)
        self.assertEqual(metrics["lanes"]["1"]["correct"], 1)
        self.assertEqual(metrics["lanes"]["2"]["correct"], 1)

    def test_duplicate_predictions_cannot_both_match_one_reference(self):
        metrics = self.score(reference(), [[region(1), region(1)]])["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["matched_regions"], 1)
        self.assertEqual(metrics["false_positive_regions"], 1)
        self.assertEqual(metrics["lanes"]["1"]["predictions_scored"], 2)
        self.assertEqual(metrics["lanes"]["1"]["precision"], .5)

    def test_empty_observations_are_misses_but_missing_mode_is_unavailable(self):
        ref = reference()
        metrics = self.score(ref, [[]])["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["missed_reference_boats"], 1)
        self.assertEqual(metrics["lanes"]["1"]["coverage"], 0.)
        self.assertIsNone(metrics["lanes"]["1"]["precision"])
        self.assertIsNone(metrics["lanes"]["6"]["coverage"])
        for quality in ({}, {"identity_observations": []}):
            tracks = tracking(ref); tracks["quality"] = quality
            report = engine(self).benchmark_identity(tracks, ref)
            self.assertEqual(report["status"], "UNAVAILABLE")
            self.assertIsNone(report["partitions"])

    def test_unmatched_predictions_on_sparse_labels_are_excluded(self):
        ref = reference([frame(exhaustive=False)])
        metrics = self.score(ref, [[region(1), region(2, 80)]])["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["false_positive_regions"], 0)
        self.assertEqual(metrics["unmatched_predictions_excluded"], 1)
        self.assertIsNone(metrics["lanes"]["2"]["precision"])

    def test_unreadable_number_is_hull_evidence_without_an_identity_target(self):
        ref = reference([frame(boats=[boat(None, readable=False)])])
        metrics = self.score(ref)["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["matched_regions"], 1)
        self.assertEqual(metrics["identity_unknown_matches"], 1)
        self.assertEqual(metrics["wrong_id_matches"], 0)
        self.assertIsNone(metrics["lanes"]["1"]["precision"])
        self.assertIsNone(metrics["lanes"]["1"]["coverage"])

    def test_inference_failure_flags_are_counted_without_excluding_visible_misses(self):
        ref = reference([frame(), frame(1)])
        tracks = tracking(ref, [[], [region(1)]])
        tracks["quality"]["identity_observations"][0]["quality_flags"] = ["LOCAL_OCR_TIMEOUT", "LOCAL_OCR_TIMEOUT"]
        report = engine(self).benchmark_identity(tracks, ref)
        self.assertIn("quality_flag_counts", report)
        self.assertEqual(report["quality_flag_counts"], {"LOCAL_OCR_TIMEOUT": 1})
        metrics = report["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["evaluated_frames"], 2)
        self.assertEqual(metrics["lanes"]["1"]["reference_visible"], 2)
        self.assertEqual(metrics["lanes"]["1"]["coverage"], .5)

    def test_all_six_denominator_requires_exhaustive_known_six(self):
        boats = [boat(n, 15 * n) for n in range(1, 7)]
        frames = [frame(boats=deepcopy(boats)), frame(1, boats=deepcopy(boats), exhaustive=False),
                  frame(2, boats=boats[:-1])]
        predictions = [[region(n, 15 * n, track="T%06d" % n) for n in range(1, 7)] for _ in frames]
        metrics = self.score(reference(frames), predictions)["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["whole_six_eligible_frames"], 1)
        self.assertEqual(metrics["whole_six_correct_frames"], 1)
        self.assertEqual(metrics["whole_six_accuracy"], 1.)
        no_six = self.score(reference())["partitions"]["DEVELOPMENT"]
        self.assertIsNone(no_six["whole_six_accuracy"])

    def test_switches_and_observed_fragmentation_are_separate(self):
        ref = reference([frame(i) for i in range(5)])
        predictions = [[region(1, track="A")], [region(1, track="B")], [],
                       [region(1, track="C")], [region(2, track="C")]]
        metrics = self.score(ref, predictions)["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["anonymous_id_switches"], 1)
        self.assertEqual(metrics["number_id_switches"], 1)
        self.assertEqual(metrics["fragmentations"], 1)
        self.assertEqual(metrics["matched_identity_transitions"], 2)

    def test_unlabeled_frames_and_new_shots_do_not_manufacture_switches(self):
        ref = reference([frame(0), frame(2), frame(3, group="shot-b")])
        tracks = tracking(ref, [[region(1, track="A")], [region(1, track="B")], [region(1, track="C")]])
        extra = {"frame_index": 1, "t": .1, "scene": 0, "decoded_frame_sha256": "f" * 64,
                 "regions": [region(2, 80, track="Z")]}
        tracks["quality"]["identity_observations"].insert(1, extra)
        report = engine(self).benchmark_identity(tracks, ref)
        metrics = report["partitions"]["DEVELOPMENT"]
        self.assertEqual(report["unlabeled_prediction_frames"], 1)
        self.assertEqual(metrics["false_positive_regions"], 0)
        self.assertEqual(metrics["anonymous_id_switches"], 0)
        self.assertEqual(metrics["fragmentations"], 0)
        self.assertEqual(metrics["matched_identity_transitions"], 0)

    def test_real_pixels_ai_reference_and_controlled_engine_stay_distinct(self):
        ref = reference(media_class="REAL", reference_class="INDEPENDENT_AI_VISUAL_REFERENCE")
        report = self.score(ref)
        self.assertEqual(report["media_class"], "REAL")
        self.assertEqual(report["reference_class"], "INDEPENDENT_AI_VISUAL_REFERENCE")
        self.assertEqual(report["engine_class"], "CONTROLLED")
        self.assertFalse(report["human_verified"])
        self.assertFalse(report["real_engine_performance_established"])
        human = self.score(reference(reference_class="HUMAN_ANNOTATION_DECLARED"))
        self.assertEqual(human["reference_class"], "HUMAN_ANNOTATION_DECLARED")
        self.assertFalse(human["human_verified"])

    def test_whole_media_roles_cannot_mix_and_within_clip_is_not_disjoint(self):
        frames = [frame(), frame(1, partition="HELDOUT")]
        with self.assertRaises(ValueError):
            engine(self).validate_reference(reference(frames))
        report = self.score(reference(frames, split_scope="WITHIN_CLIP"))
        self.assertEqual(set(report["partitions"]), {"DEVELOPMENT", "HELDOUT"})
        self.assertFalse(report["disjoint_source_heldout"])
        self.assertEqual(report["heldout_scope"], "WITHIN_CLIP_ONLY")

    def test_source_frame_pts_and_pixel_bindings_are_required(self):
        ref = reference()
        mutations = [lambda t: t.update(media_sha256="b" * 64),
                     lambda t: t.update(width=161),
                     lambda t: t["quality"]["identity_observations"][0].update(t=.01),
                     lambda t: t["quality"]["identity_observations"][0].update(decoded_frame_sha256="b" * 64)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                tracks = tracking(ref); mutate(tracks)
                with self.assertRaises(ValueError):
                    engine(self).benchmark_identity(tracks, ref)

    def test_unsampled_reference_frames_are_explicit_missing_input(self):
        ref = reference([frame(), frame(1)])
        tracks = tracking(ref)
        tracks["quality"]["identity_observations"].pop()
        report = engine(self).benchmark_identity(tracks, ref)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["reference_frames_without_predictions"], 1)
        self.assertEqual(report["partitions"]["DEVELOPMENT"]["evaluated_frames"], 1)

    def test_png_file_hash_does_not_replace_canonical_decoded_pixel_hash(self):
        ref = reference()
        ref["frames"][0]["image_file_sha256"] = "f" * 64
        report = self.score(ref)
        self.assertEqual(report["status"], "SCORED")
        self.assertEqual(report["partitions"]["DEVELOPMENT"]["lanes"]["1"]["correct"], 1)

    def test_config_cannot_upgrade_controlled_metadata_to_a_pinned_engine(self):
        with self.assertRaises(ValueError):
            self.score(reference(), engine_class="PINNED")
        for configuration in ({"iou_threshold": 0}, {"iou_threshold": float("nan")},
                              {"max_transition_gap_seconds": -1}, {"unknown": True}):
            with self.subTest(configuration=configuration), self.assertRaises(ValueError):
                self.score(reference(), **configuration)

    def test_reference_validation_rejects_unknown_identity_laundering_and_bad_geometry(self):
        mutations = [lambda r: r.update(human_verified=True),
                     lambda r: r.update(media_class="REALISH"),
                     lambda r: r["frames"][0]["boats"][0].update(lane=7),
                     lambda r: r["frames"][0]["boats"][0].update(readability="UNREADABLE"),
                     lambda r: r["frames"][0]["boats"][0].update(box=[159, 0, 10, 10]),
                     lambda r: r["frames"][0]["boats"][0].update(box=[0, 0, 1e-200, 1e-200]),
                     lambda r: r["frames"][0].update(t=float("nan")),
                     lambda r: r["frames"].append(deepcopy(r["frames"][0]))]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                ref = reference(); mutate(ref)
                with self.assertRaises(ValueError):
                    engine(self).validate_reference(ref)

    def test_inputs_are_unchanged_and_results_are_deterministic(self):
        ref = reference(); tracks = tracking(ref)
        original = deepcopy((ref, tracks))
        first = engine(self).benchmark_identity(tracks, ref)
        self.assertEqual(first, engine(self).benchmark_identity(tracks, ref))
        self.assertEqual((ref, tracks), original)
        checked = engine(self).validate_reference(ref)
        checked["frames"][0]["boats"].clear()
        self.assertEqual(ref, original[0])


class BoatHullBenchmarkTests(unittest.TestCase):
    def tracks(self, ref, boxes):
        tracks = tracking(ref, [[] for _ in ref["frames"]])
        for observation, raw in zip(tracks["quality"]["identity_observations"], boxes):
            if raw is not None:
                observation["exclusion_boxes"] = raw
        return tracks

    def score(self, ref, boxes, **configuration):
        module = engine(self)
        self.assertTrue(callable(getattr(module, "benchmark_hulls", None)), "raw-hull benchmark is missing")
        return module.benchmark_hulls(self.tracks(ref, boxes), ref, configuration=configuration or None)

    def test_real_unreadable_hulls_score_geometry_without_inventing_identities(self):
        ref = reference([frame(boats=[boat(None, 10, readable=False), boat(None, 40, readable=False)])],
                        media_class="REAL", reference_class="INDEPENDENT_AI_VISUAL_REFERENCE")
        report = self.score(ref, [[[10, 10, 10, 10], [40, 10, 10, 10], [80, 10, 10, 10]]])
        metrics = report["partitions"]["DEVELOPMENT"]
        self.assertEqual(report["scope"], "HULL_CANDIDATE_COVERAGE_ONLY")
        self.assertEqual(report["prediction_scope"], "RAW_HULL_EXCLUSION_BOXES_BEFORE_OVERLAY_FILTER")
        self.assertFalse(report["identity_evaluated"])
        self.assertNotIn("lanes", metrics)
        self.assertEqual((metrics["matched_regions"], metrics["false_positive_regions"],
                          metrics["missed_reference_boats"]), (2, 1, 0))
        self.assertEqual(metrics["precision"], 2 / 3)
        self.assertEqual(metrics["coverage"], 1.)
        self.assertEqual(report["reference_class"], "INDEPENDENT_AI_VISUAL_REFERENCE")
        self.assertEqual(report["engine_class"], "CONTROLLED")
        self.assertFalse(report["human_verified"])
        self.assertFalse(report["production_eligible"])

    def test_empty_raw_boxes_are_misses_while_omitted_raw_data_is_unavailable(self):
        ref = reference()
        empty = self.score(ref, [[]])
        metrics = empty["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["missed_reference_boats"], 1)
        self.assertEqual(metrics["coverage"], 0.)
        self.assertIsNone(metrics["precision"])
        omitted = self.score(ref, [None])
        self.assertEqual(omitted["status"], "UNAVAILABLE")
        self.assertIsNone(omitted["partitions"])
        partial = self.score(reference([frame(), frame(1)]), [[], None])
        self.assertEqual(partial["status"], "PARTIAL")
        self.assertEqual(partial["reference_frames_without_predictions"], 1)

    def test_sparse_hull_references_exclude_unmatched_predictions_from_precision(self):
        report = self.score(reference([frame(exhaustive=False)]),
                            [[[10, 10, 10, 10], [80, 10, 10, 10]]])
        metrics = report["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["unmatched_predictions_excluded"], 1)
        self.assertEqual(metrics["false_positive_regions"], 0)
        self.assertEqual(metrics["predictions_scored"], 1)
        self.assertEqual(metrics["precision"], 1.)

    def test_hull_mode_keeps_strict_source_pts_and_decoded_hash_bindings(self):
        ref = reference()
        mutations = [lambda t: t.update(media_sha256="b" * 64),
                     lambda t: t.update(width=161),
                     lambda t: t["quality"]["identity_observations"][0].update(t=.01),
                     lambda t: t["quality"]["identity_observations"][0].update(decoded_frame_sha256="f" * 64)]
        self.score(ref, [[]])
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                tracks = self.tracks(ref, [[]]); mutate(tracks)
                with self.assertRaises(ValueError):
                    engine(self).benchmark_hulls(tracks, ref)

    def test_hull_partitions_preserve_within_clip_and_engine_limits(self):
        ref = reference([frame(), frame(1, partition="HELDOUT")], split_scope="WITHIN_CLIP")
        report = self.score(ref, [[[10, 10, 10, 10]], []])
        self.assertEqual(report["partitions"]["DEVELOPMENT"]["coverage"], 1.)
        self.assertEqual(report["partitions"]["HELDOUT"]["coverage"], 0.)
        self.assertEqual(report["heldout_scope"], "WITHIN_CLIP_ONLY")
        self.assertFalse(report["disjoint_source_heldout"])
        with self.assertRaises(ValueError):
            self.score(ref, [[], []], engine_class="PINNED")

    def test_hull_matching_is_one_to_one_and_ignores_numbered_region_contents(self):
        ref = reference([frame(boats=[boat(1, 10), boat(2, 20)])])
        report = self.score(ref, [[[14, 10, 10, 10], [10, 10, 10, 10]]], iou_threshold=.2)
        self.assertEqual(report["partitions"]["DEVELOPMENT"]["matched_regions"], 2)
        tracks = self.tracks(reference(), [[[10, 10, 10, 10], [10, 10, 10, 10]]])
        tracks["quality"]["identity_observations"][0]["regions"] = [{"unusable_identity": True}]
        duplicate = engine(self).benchmark_hulls(tracks, reference())
        metrics = duplicate["partitions"]["DEVELOPMENT"]
        self.assertEqual(metrics["matched_regions"], 1)
        self.assertEqual(metrics["precision"], .5)

    def test_hull_failure_flags_do_not_remove_reference_misses(self):
        ref = reference([frame(), frame(1)])
        self.score(ref, [[], []])
        tracks = self.tracks(ref, [[], [[10, 10, 10, 10]]])
        tracks["quality"]["identity_observations"][0]["quality_flags"] = ["LOCAL_OCR_TIMEOUT"]
        original = deepcopy(tracks)
        report = engine(self).benchmark_hulls(tracks, ref)
        self.assertEqual(report["quality_flag_counts"], {"LOCAL_OCR_TIMEOUT": 1})
        self.assertEqual(report["partitions"]["DEVELOPMENT"]["coverage"], .5)
        self.assertEqual(tracks, original)
        self.assertEqual(report, engine(self).benchmark_hulls(tracks, ref))


if __name__ == "__main__":
    unittest.main()
