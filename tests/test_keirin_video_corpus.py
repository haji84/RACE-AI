import sqlite3
import unittest

from scripts import keirin_video_corpus as corpus


class FullCorpusTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        corpus.setup(self.db)
        self.race = dict(
            race_id="20260102-12-03",
            race_date="2026-01-02",
            roster_complete=True,
            event_status="finish_verified",
            riders=[{"car": 1, "rider_id": "015001"}, {"car": 2, "rider_id": "015002"}],
        )
        self.media = dict(
            race_id=self.race["race_id"],
            race_date=self.race["race_date"],
            source_ref="verified source",
            kind="frames",
            status="verified",
            frames=[dict(at_ms=t, sha256=c * 64) for t, c in [(400, "a"), (800, "b")]],
        )
        self.label = dict(
            race_id=self.race["race_id"],
            race_date=self.race["race_date"],
            car=1,
            rider_id="015001",
            task="follow",
            value="held",
            scope="B4C",
            window_level="clip",
            target_car=2,
            target_rider_id="015002",
            note="visible",
            reviewer="reader",
            start_ms=400,
            end_ms=800,
            source_ref="verified source",
            evidence_frames=self.media["frames"],
        )
        corpus.load_race(self.db, self.race)
        corpus.load_media(self.db, self.media)

    def tearDown(self):
        self.db.close()

    def test_repeat_and_missing_starters_remain_in_queue(self):
        corpus.load_review(self.db, self.label)
        corpus.load_review(self.db, self.label)
        corpus.load_race(self.db, self.race)
        corpus.load_media(self.db, self.media)
        stat = corpus.report(self.db)
        self.assertEqual(stat["readable_starter_starts"], 1)
        self.assertEqual(stat["full_races"], 0)
        self.assertEqual(stat["observations"], {"follow": 1})
        queue = list(corpus.pending(self.db))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["stage"], "review")
        self.assertEqual(queue[0]["open_starters"], 2)

    def test_mismatched_or_unobserved_evidence_rejected(self):
        for changes in (
            {"rider_id": "015002"},
            {"end_ms": 790},
            {"evidence_frames": [{"at_ms": 400, "sha256": "c" * 64}]},
            {"target_rider_id": "015001"},
            {"race_date": "2026-01-03"},
            {"evidence_frames": []},
            {"scope": "whole_final_lap", "window_level": "whole_final_lap"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                corpus.load_review(self.db, {**self.label, **changes})

    def test_unknown_can_be_resolved_and_conflict_keeps_first_observation(self):
        corpus.load_review(
            self.db,
            {
                **self.label,
                "value": "unknown",
                "reason": "occluded",
                "target_car": None,
                "target_rider_id": None,
            },
        )
        self.assertEqual(corpus.report(self.db)["unresolved_reviews"], 1)
        corpus.load_review(self.db, self.label)
        self.assertEqual(corpus.report(self.db)["unresolved_reviews"], 0)
        with self.assertRaises(ValueError):
            corpus.load_review(self.db, {**self.label, "value": "lost"})
        self.assertEqual([r["value"] for r in corpus.training_rows(self.db)], ["held"])

    def test_empty_and_incomplete_roster_never_vacuously_complete(self):
        for r, riders in [("04", []), ("05", [{"car": 1, "rider_id": None}])]:
            corpus.load_race(
                self.db,
                {
                    **self.race,
                    "race_id": "20260102-12-" + r,
                    "riders": riders,
                    "roster_complete": False,
                },
            )
        self.assertEqual(corpus.report(self.db)["full_races"], 0)
        self.assertEqual(len(list(corpus.pending(self.db))), 3)

    def test_media_interval_bounds_and_distinct_race(self):
        movie = {
            **self.media,
            "kind": "clip",
            "source_ref": "movie",
            "sha256": "e" * 64,
            "coverage": "owner_declared_clip",
            "start_ms": 100,
            "duration_ms": 800,
        }
        corpus.load_media(self.db, movie)
        label = {**self.label, "source_ref": "movie", "media_sha256": movie["sha256"]}
        label.pop("evidence_frames")
        corpus.load_review(self.db, label)
        with self.assertRaises(ValueError):
            corpus.load_review(self.db, {**label, "end_ms": 1000})
        with self.assertRaises(ValueError):
            corpus.load_media(self.db, {**self.media, "race_id": "20260102-12-04"})

    def test_learning_uses_merged_coverage_and_temporal_cutoff(self):
        from scripts.keirin_video_rider_learning import study

        corpus.load_review(self.db, self.label)
        later = {
            **self.race,
            "race_id": "20260103-12-03",
            "race_date": "2026-01-03",
            "riders": [],
        }
        corpus.load_race(self.db, later)
        self.assertEqual(
            [len(r["riders"]) for r in corpus.census_rows(self.db)], [2, 0]
        )
        report, profiles = study(
            corpus.census_rows(self.db),
            corpus.training_rows(self.db),
            before="2026-01-03",
        )
        self.assertEqual(report["observed_riders"], 1)
        self.assertEqual(len(profiles), 2)

    def test_continuous_queue_includes_verified_frames_until_movie_is_available(self):
        self.assertEqual(len(list(corpus.pending(self.db, stage="continuous"))), 1)
        corpus.load_media(
            self.db,
            {
                **self.media,
                "kind": "clip",
                "sha256": "d" * 64,
                "start_ms": 0,
                "duration_ms": 2000,
                "coverage": "owner_declared_clip",
            },
        )
        self.assertEqual(len(list(corpus.pending(self.db, stage="continuous"))), 0)
        self.assertEqual(len(list(corpus.pending(self.db, stage="review"))), 1)

    def test_whole_fields_require_both_observations_for_every_identified_starter(self):
        movie = {
            **self.media,
            "kind": "full",
            "sha256": "1" * 64,
            "start_ms": 0,
            "duration_ms": 150000,
            "coverage": "owner_declared_full",
        }
        corpus.load_media(self.db, movie)
        for car, rider in ((1, "015001"), (2, "015002")):
            corpus.load_bounds(self.db, {
                **self.label, "car": car, "rider_id": rider, "scope": "whole_race",
                "media_sha256": movie["sha256"], "start_ms": 500, "end_ms": 149000,
                "note": "Observed this car at the starter and on the goal line",
            })
            for task, value in (("follow", "no_target"), ("attack", "no_attack")):
                label = {
                    **self.label,
                    "start_ms": 0,
                    "end_ms": 150000,
                    "task": task,
                    "value": value,
                    "car": car,
                    "rider_id": rider,
                    "target_car": None,
                    "target_rider_id": None,
                    "scope": "whole_race",
                    "window_level": "whole_race",
                    "media_sha256": movie["sha256"],
                }
                corpus.load_review(self.db, label)
            self.assertEqual(corpus.report(self.db)["full_races"], int(car == 2))
        self.assertEqual(list(corpus.pending(self.db)), [])
        self.assertEqual(corpus.report(self.db)["full_field_final_lap_races"], 0)

    def test_closed_windows_need_car_specific_boundaries_after_upgrade(self):
        movie = {**self.media, "kind": "clip", "sha256": "c"*64, "start_ms": 0,
                 "duration_ms": 20000, "coverage": "owner_declared_clip"}
        corpus.load_media(self.db, movie)
        label = {**self.label, "scope": "whole_final_lap", "window_level": "whole_final_lap",
                 "media_sha256": movie["sha256"], "start_ms": 100, "end_ms": 101}
        with self.assertRaisesRegex(ValueError, "independently recorded"):
            corpus.load_review(self.db, label)
        # Old ledgers may already retain a known whole-lap entry without endpoints.
        old = corpus.pack(label)
        self.db.execute("INSERT INTO review VALUES(?,?,?,?,?,?,1)",
                        (self.race["race_id"], 1, "follow", "whole_final_lap", "whole_final_lap", old))
        self.assertEqual(list(corpus.training_rows(self.db)), [])
        self.assertEqual(corpus.report(self.db)["known_reviews_awaiting_valid_evidence"], 1)
        bound = {**label, "start_ms": 1000, "end_ms": 19000}
        corpus.load_bounds(self.db, bound)
        corpus.load_bounds(self.db, bound)
        self.assertEqual(corpus.report(self.db)["whole_window_bounds"], 1)
        with self.assertRaisesRegex(ValueError, "conflicting recorded"):
            corpus.load_bounds(self.db, {**bound, "end_ms": 19001})
        with self.assertRaisesRegex(ValueError, "independently recorded"):
            corpus.load_review(self.db, label)
        uncensored = {**label, "start_ms": 700, "end_ms": 19100}
        corpus.load_review(self.db, uncensored)
        self.assertEqual([i["start_ms"] for i in corpus.training_rows(self.db)], [700])
        with self.assertRaisesRegex(ValueError, "independently recorded"):
            corpus.load_review(self.db, {**uncensored, "car": 2, "rider_id": "015002",
                                         "target_car": 1, "target_rider_id": "015001"})
        unknown = {**uncensored, "car": 2, "rider_id": "015002", "target_car": None,
                   "target_rider_id": None, "value": "unknown", "reason": "obscured"}
        corpus.load_review(self.db, unknown)
        self.assertEqual(corpus.report(self.db)["unresolved_reviews"], 1)

    def test_partial_identification_independent_of_review_and_source(self):
        other = {**self.race, "race_id": "20260102-12-04", "roster_complete": False,
                 "riders": [{"car": 1, "rider_id": "015001"}, {"car": 2, "rider_id": None}]}
        corpus.load_race(self.db, other)
        ids = lambda stage: [r["race_id"] for r in corpus.pending(self.db, stage=stage)]
        self.assertIn(other["race_id"], ids("source"))
        self.assertIn(other["race_id"], ids("identify"))
        corpus.load_media(self.db, {**self.media, "race_id": other["race_id"]})
        self.assertIn(other["race_id"], ids("review"))
        self.assertIn(other["race_id"], ids("identify"))
        self.assertNotIn(self.race["race_id"], ids("identify"))

    def test_identical_images_cannot_be_admitted_as_known_movement(self):
        frames = [{"at_ms": 1100, "sha256": "f"*64}, {"at_ms": 1500, "sha256": "f"*64}]
        corpus.load_media(self.db, {**self.media, "frames": frames})
        with self.assertRaisesRegex(ValueError, "frame hashes"):
            corpus.load_review(self.db, {**self.label, "start_ms": 1100, "end_ms": 1500,
                                         "evidence_frames": frames})

    def test_discrete_frames_do_not_establish_absence(self):
        with self.assertRaises(ValueError):
            corpus.load_review(
                self.db,
                {
                    **self.label,
                    "task": "attack",
                    "value": "no_attack",
                    "target_car": None,
                    "target_rider_id": None,
                },
            )
