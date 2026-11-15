"""Private video reports retain experimental evidence without altering forecasts."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


RACE = "20300401-01-01"
CUTOFF = "2030-04-01T12:00:00+09:00"
START = "2030-04-01T11:50:00+09:00"
END = "2030-04-01T11:50:02+09:00"
CAPTURE = "2030-04-01T11:40:00+09:00"


def engine(test):
    try:
        return importlib.import_module("race_ai.boat_video_evaluation")
    except ModuleNotFoundError:
        test.fail("typed private video evaluation module is missing")


def wire(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def reseal(value):
    value = deepcopy(value)
    value.pop("report_sha256", None)
    value["report_sha256"] = sha256(wire(value)).hexdigest()
    return value


def roster():
    return [{"lane": n, "registration_number": str(4200 + n)} for n in range(1, 7)]


def job(digest, kind="OWNER_LOCAL"):
    return {"schema_version": "RACE_AI_BOAT_VIDEO_JOB_V1", "race_id": RACE,
            "cutoff_at": CUTOFF, "roster": roster(), "source": {
                "kind": kind, "media_sha256": digest, "captured_at": CAPTURE,
                "identity_status": "SYNTHETIC" if kind == "SYNTHETIC_TEST" else "OWNER_DECLARED"}}


def extracted(digest):
    tracks = [{"lane": n, "identity_status": "COLOR_CANDIDATE", "samples": []}
              for n in range(1, 7)]
    tracks[0]["samples"] = [{"t": i / 10, "frame_index": i, "scene": 0,
        "valid": True, "x": float(i), "y": 0.0, "position_error": 0.1} for i in range(6)]
    tracks[1]["samples"] = [{"t": 0.0, "frame_index": 0, "scene": 0,
        "valid": False, "x": None, "y": None, "position_error": None,
        "reason": "ACHROMATIC_IDENTITY_AMBIGUOUS"}]
    return {"schema_version": "RACE_AI_BOAT_VIDEO_TRACKS_V1", "media_sha256": digest,
            "width": 320, "height": 240, "duration_seconds": 1.0,
            "timeline_source": "MEDIA_PTS", "media_pts_origin_seconds": 2.5,
            "coordinate_space": "REFERENCE_IMAGE_PX", "model_eligible": False,
            "validation_status": "UNVALIDATED", "tracks": tracks,
            "quality": {"flags": ["EXPERIMENTAL_TEST"], "camera_estimates": [],
                        "position_error_scope": "UNCERTIFIED", "decoded_frame_count": 10}}


def view():
    return {"event_date_jst": "2030-04-01", "records": [{"sport": "boat", "race_id": RACE,
        "cutoff_at": CUTOFF, "participants": [{"number": n, "registration_no": str(4200 + n)}
                                              for n in range(1, 7)],
        "prediction": {"model_id": "saved", "ordered_top8": [[1, 2, 3]], "sha256": "b" * 64},
        "result": {"order": [2, 1, 3]}, "result_observations": [{"seen": "later"}],
        "saved_cutoff_variants": [CUTOFF], "saved_schedule_cutoff_variants": [CUTOFF]}]}


class BoatVideoEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.media = self.root / "private-recording.mp4"
        self.media.write_bytes(b"injected extractor fixture, not real media")
        self.digest = sha256(self.media.read_bytes()).hexdigest()

    def analyze(self, *, specification=None, tracking=None, times=(START, END)):
        clock = iter(datetime.fromisoformat(v) for v in times)
        data = extracted(self.digest) if tracking is None else tracking
        return engine(self).analyze_video(self.media,
            job(self.digest) if specification is None else specification,
            clock=lambda: next(clock), extractor=lambda path, *, options=None: deepcopy(data))

    def test_orchestration_seals_true_times_real_measurements_and_complete_evidence(self):
        report = self.analyze()
        self.assertEqual(report["report_sha256"], reseal(report)["report_sha256"])
        self.assertEqual(report["analysis_started_at"], START)
        self.assertEqual(report["analysis_completed_at"], END)
        self.assertTrue(report["pre_cutoff_available"])
        self.assertFalse(report["model_eligible"])
        self.assertEqual(report["validation_status"], "UNVALIDATED")
        self.assertEqual(report["dataset_status"], "REAL_REPORTED")
        self.assertEqual(report["tracking"], extracted(self.digest))
        straight = report["measurements"]["lanes"][0]["phases"]["straight"]
        speed = next(m for m in straight["metrics"] if m["name"] == "mean_interval_speed")
        self.assertEqual(speed, {"name": "mean_interval_speed", "value": 10.0, "unit": "px/s"})
        self.assertEqual(report["measurements"]["lanes"][1]["phases"]["straight"]["status"], "MISSING")
        self.assertIsNone(report["tracking"]["tracks"][1]["samples"][0]["x"])
        self.assertNotIn(str(self.media), wire(report).decode())

    def test_cutoff_is_derived_from_capture_start_and_completion_not_job_claim(self):
        report = self.analyze(times=(START, CUTOFF))
        self.assertFalse(report["pre_cutoff_available"])
        late = self.analyze(times=("2030-04-01T12:01:00+09:00", "2030-04-01T12:01:02+09:00"))
        self.assertFalse(late["pre_cutoff_available"])
        for times in ((START, CAPTURE), (CAPTURE, START)):
            spec = job(self.digest)
            spec["source"]["captured_at"] = START
            with self.subTest(times=times), self.assertRaises(ValueError):
                self.analyze(specification=spec, times=times)

    def test_next_day_replay_capture_keeps_actual_late_availability(self):
        spec = job(self.digest)
        spec["source"]["captured_at"] = "2030-04-02T10:00:00+09:00"
        report = self.analyze(specification=spec,
            times=("2030-04-02T10:01:00+09:00", "2030-04-02T10:01:02+09:00"))
        self.assertEqual(report["source"]["captured_at"], "2030-04-02T10:00:00+09:00")
        self.assertFalse(report["pre_cutoff_available"])
        self.assertEqual(engine(self).enrich_view(view(), [report])["records"][0]["boat_video_evaluations"], [report])
        spec["source"]["captured_at"] = "2030-03-31T23:59:00+09:00"
        with self.assertRaises(ValueError): self.analyze(specification=spec)

    def test_noncanonical_timestamp_grammar_is_rejected_before_report_creation(self):
        for stamp in ("2030-04-01 11:40:00+09:00", "20300401T114000+0900",
                      "2030-04-01T11:40:00.1234567+09:00"):
            spec = job(self.digest); spec["source"]["captured_at"] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                self.analyze(specification=spec)

    def test_canonical_z_and_microsecond_offset_timestamps_preserve_originals(self):
        for stamp in ("2030-04-01T02:40:00Z", "2030-04-01T11:40:00.123456+09:00"):
            spec = job(self.digest); spec["source"]["captured_at"] = stamp
            report = self.analyze(specification=spec,
                times=("2030-04-01T11:50:00.123456+09:00", "2030-04-01T11:50:02.123456+09:00"))
            self.assertEqual(report["source"]["captured_at"], stamp)
            self.assertEqual(report["analysis_started_at"], "2030-04-01T11:50:00.123456+09:00")
            self.assertTrue(report["pre_cutoff_available"])

    def test_job_identity_time_and_promotion_injections_are_rejected(self):
        cases = []
        for key, val in (("model_eligible", True), ("validation_status", "VALIDATED"),
                         ("coordinate_space", "WATER_PLANE_METRES")):
            spec = job(self.digest); spec[key] = val; cases.append(spec)
        for source_key, val in (("media_sha256", "f" * 64), ("captured_at", "2030-04-02T00:00:00+09:00"),
                                ("captured_at", "2030-04-01T11:40:00"), ("identity_status", "VERIFIED")):
            spec = job(self.digest); spec["source"][source_key] = val; cases.append(spec)
        spec = job(self.digest); spec["roster"][1] = deepcopy(spec["roster"][0]); cases.append(spec)
        spec = job(self.digest); spec["race_id"] = "20300230-01-01"; cases.append(spec)
        spec = job(self.digest); spec["cutoff_at"] = "2030-04-02T12:00:00+09:00"; cases.append(spec)
        for spec in cases:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                self.analyze(specification=spec)

    def test_only_public_race_bound_official_metadata_is_serialized(self):
        spec = job(self.digest, "OFFICIAL_BROWSER_CAPTURE")
        spec["source"].update(identity_status="SOURCE_METADATA_LINKED", source_metadata_sha256="a" * 64,
            public_page_url="https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300401&jcd=01&rno=1")
        report = self.analyze(specification=spec)
        self.assertEqual(report["source"], spec["source"])
        for url in ("https://user:secret@www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300401&jcd=01&rno=1",
                    spec["source"]["public_page_url"] + "&token=secret",
                    spec["source"]["public_page_url"].replace("jcd=01", "jcd=02"),
                    "https://media.example/signed.mp4?signature=secret"):
            bad = deepcopy(spec); bad["source"]["public_page_url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError): self.analyze(specification=bad)

    def test_tracking_promotion_fake_physical_space_and_nonfinite_parameters_rejected(self):
        for mutate in (lambda x: x.update(model_eligible=True), lambda x: x.update(validation_status="VALIDATED"),
                       lambda x: x.update(coordinate_space="WATER_PLANE_METRES"),
                       lambda x: x.update(width=True), lambda x: x.update(duration_seconds=float("nan")),
                       lambda x: x["quality"].update(source_path="private-recording.mp4"),
                       lambda x: x["tracks"][0]["samples"][0].update(valid=True, x=None)):
            data = extracted(self.digest); mutate(data)
            with self.subTest(data=data), self.assertRaises(ValueError): self.analyze(tracking=data)
        for val in (True, float("inf"), float("nan"), 0):
            spec = job(self.digest); spec["max_gap_seconds"] = val
            with self.subTest(val=val), self.assertRaises(ValueError): self.analyze(specification=spec)

    def test_private_store_roundtrip_is_immutable_and_read_never_extracts(self):
        module = engine(self)
        report = self.analyze()
        digest = module.save_evaluation(self.root, report)
        target = self.root / "video-evaluations" / (digest + ".json")
        self.assertEqual(digest, report["report_sha256"])
        before = target.stat().st_mtime_ns
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
        self.assertEqual(module.save_evaluation(self.root, report), digest)
        self.assertEqual(target.stat().st_mtime_ns, before)
        with patch("race_ai.boat_video_tracking.extract_tracks", side_effect=AssertionError("read analyzed media")), \
             patch("race_ai.boat_video_evaluation.measure_tracks", side_effect=AssertionError("read remeasured tracks")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("read fetched media")):
            self.assertEqual(module.read_evaluations(self.root, day="2030-04-01"), [report])
            self.assertEqual(module.read_evaluations(self.root, day="2030-04-02"), [])
        self.assertEqual(wire(report), target.read_bytes())

    def test_absent_store_is_empty_but_missing_listed_version_is_an_integrity_failure(self):
        module = engine(self)
        self.assertEqual(module.read_evaluations(self.root), [])
        module.save_evaluation(self.root, self.analyze())
        with patch("race_ai.boat_video_evaluation.os.listdir", return_value=["f" * 64 + ".json"]):
            with self.assertRaises(ValueError): module.read_evaluations(self.root)

    def test_tampered_seal_resealed_promotion_and_inconsistent_identity_are_rejected(self):
        module = engine(self)
        report = self.analyze()
        for mutate in (lambda x: x.update(model_eligible=True),
                       lambda x: x.update(pre_cutoff_available=False),
                       lambda x: x["source"].update(media_sha256="f" * 64),
                       lambda x: x["measurements"]["lanes"][0].update(identity_validated=True)):
            changed = deepcopy(report); mutate(changed)
            for candidate in (changed, reseal(changed)):
                with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                    module.save_evaluation(self.root, candidate)
        digest = module.save_evaluation(self.root, report)
        file = self.root / "video-evaluations" / (digest + ".json")
        changed = deepcopy(report); changed["race_id"] = "20300401-01-02"
        file.write_bytes(wire(changed))
        with self.assertRaises(ValueError): module.read_evaluations(self.root)

    def test_resealed_media_boolean_cannot_impersonate_numeric_metadata(self):
        data = extracted(self.digest); data["duration_seconds"] = 1.0
        report = self.analyze(tracking=data)
        report["media"]["duration_seconds"] = True
        with self.assertRaises(ValueError): engine(self).save_evaluation(self.root, reseal(report))

    def test_resealed_measurement_scope_cannot_claim_physical_validation(self):
        for key, value in (("physical_velocity", "ESTABLISHED"),
                           ("calibration_status", "PHYSICALLY_VERIFIED"),
                           ("time_basis", "PHYSICAL_SECONDS"),
                           ("candidate_measurements", False)):
            report = self.analyze(); report["measurements"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                engine(self).save_evaluation(self.root, reseal(report))

    def test_store_rejects_unsafe_permissions_links_git_and_noncanonical_json(self):
        module = engine(self)
        report = self.analyze()
        self.root.chmod(0o755)
        with self.assertRaises((ValueError, OSError)): module.save_evaluation(self.root, report)
        self.root.chmod(0o700)
        (self.root / ".git").mkdir()
        with self.assertRaises((ValueError, OSError)): module.save_evaluation(self.root, report)
        (self.root / ".git").rmdir()
        digest = module.save_evaluation(self.root, report)
        target = self.root / "video-evaluations" / (digest + ".json")
        hardlink = self.root / "copy"; os.link(target, hardlink)
        with self.assertRaises(ValueError): module.read_evaluations(self.root)
        hardlink.unlink()
        target.write_bytes(json.dumps(report, indent=2).encode())
        with self.assertRaises(ValueError): module.read_evaluations(self.root)
        target.unlink(); target.symlink_to(self.media)
        with self.assertRaises((ValueError, OSError)): module.read_evaluations(self.root)

    def test_enrichment_preserves_every_original_byte_and_exact_six_roster_identity(self):
        module = engine(self)
        report = self.analyze(times=("2030-04-01T12:01:00+09:00", "2030-04-01T12:01:02+09:00"))
        original = view(); raw = wire(original)
        enriched = module.enrich_view(original, [report])
        attached = enriched["records"][0].pop("boat_video_evaluations")
        self.assertEqual(attached, [report])
        self.assertFalse(attached[0]["pre_cutoff_available"])
        self.assertEqual(wire(original), raw)
        self.assertEqual(wire(enriched), raw)
        for mutate in (lambda x: x.update(cutoff_at="2030-04-01T12:01:00+09:00"),
                       lambda x: x.update(race_id="20300401-01-02"),
                       lambda x: x["participants"][0].update(registration_no="9999"),
                       lambda x: x["participants"].pop(),
                       lambda x: x["saved_cutoff_variants"].append("2030-04-01T12:01:00+09:00")):
            mismatch = view(); mutate(mismatch["records"][0])
            self.assertNotIn("boat_video_evaluations", module.enrich_view(mismatch, [report])["records"][0])

    def test_synthetic_evidence_never_attaches_real_view_and_invalid_reports_never_display(self):
        module = engine(self)
        report = self.analyze(specification=job(self.digest, "SYNTHETIC_TEST"))
        self.assertEqual(report["dataset_status"], "SYNTHETIC_ONLY")
        self.assertEqual(module.enrich_view(view(), [report]), view())
        corrupted = self.analyze(); corrupted["tracking"]["quality"]["flags"].append("tampered")
        with self.assertRaises(ValueError): module.enrich_view(view(), [corrupted])


if __name__ == "__main__":
    unittest.main()
