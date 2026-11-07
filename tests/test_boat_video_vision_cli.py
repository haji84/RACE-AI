"""Explicit optional vision CLI dispatch; no video/model accuracy claims."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from tests import test_boat_video_cli as legacy_cli
from tests import test_boat_video_intake as intake_fixtures


class BoatVideoVisionCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.media = self.root / "private-media.mp4"
        self.media.write_bytes(b"controlled local extractor fixture")
        self.media.chmod(0o600)
        self.digest = sha256(self.media.read_bytes()).hexdigest()
        self.job = intake_fixtures.specification(self.digest, cutoff=legacy_cli.CUTOFF)
        self.job["race_id"] = legacy_cli.RACE
        self.job["source"]["captured_at"] = "2020-04-01T11:40:00+09:00"
        self.manifest = self.root / "job.json"
        self.manifest.write_text(json.dumps(self.job))
        self.manifest.chmod(0o600)
        self.hull = self.root / "owner-secret-hull.onnx"
        self.crnn = self.root / "owner-secret-crnn.onnx"
        self.tesseract = self.root / "owner-secret-tesseract"
        self.tessdata = self.root / "owner-secret-tessdata"
        for asset in (self.hull, self.crnn, self.tesseract):
            asset.write_bytes(b"controlled external model construction boundary")
            asset.chmod(0o600)
        self.tessdata.mkdir(mode=0o700)
        self.intake = importlib.import_module("race_ai.boat_video_intake")

    def extractor(self, path, *, options=None):
        report = intake_fixtures.tracking(self.digest)
        report["quality"]["identity_provider"] = {"engine": "INJECTED_TEST_BOUNDARY"}
        for row in report["tracks"]:
            row["identity_status"] = "NUMBER_TEMPORAL_CANDIDATE"
        return report

    def invoke(self, surface, flags=(), *, extractor=None):
        if surface == "analyze":
            module = legacy_cli.cli(self)
            arguments = ["--video", str(self.media), "--job", str(self.manifest),
                         "--private-root", str(self.private)]
        else:
            module = self.intake
            arguments = ["--private-root", str(self.private), "--once"]
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            try:
                code = module.main([*arguments, *flags], extractor=extractor)
            except SystemExit as failure:
                code = failure.code
        return code, output.getvalue(), error.getvalue()

    def enqueue(self):
        return self.intake.enqueue(self.private, self.media, self.job)

    def report(self, surface, output):
        summary = json.loads(output)
        if surface == "analyze":
            self.assertEqual(set(summary), {"report_sha256", "report_path", "lane_count", "measured_phase_count"})
            path = Path(summary["report_path"])
        else:
            self.assertEqual(summary["succeeded"], 1)
            reports = list((self.private / "video-evaluations").glob("*.json"))
            self.assertEqual(len(reports), 1)
            path = reports[0]
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        report = json.loads(path.read_text())
        self.assertFalse(report["model_eligible"])
        self.assertEqual(report["validation_status"], "UNVALIDATED")
        self.assertFalse(report["measurements"]["identity_validated"])
        for asset in (self.hull, self.crnn, self.tesseract, self.tessdata):
            self.assertNotIn(str(asset), json.dumps(report))
            self.assertNotIn(str(asset), output)
        self.assertEqual(report["analysis_parameters"], {})
        self.assertEqual(report["tracking"]["quality"]["identity_provider"],
                         {"engine": "INJECTED_TEST_BOUNDARY"})
        return report

    def test_analyze_crnn_and_tiles_dispatch_without_resolving_tesseract(self):
        crnn = importlib.import_module("race_ai.boat_video_crnn")
        with patch.object(crnn, "make_crnn_identity_extractor", return_value=self.extractor) as factory, \
                patch("shutil.which", side_effect=AssertionError("unexpected legacy OCR discovery")), \
                patch("race_ai.boat_video_identity.make_local_identity_extractor",
                      side_effect=AssertionError("unexpected legacy OCR factory")):
            code, output, error = self.invoke("analyze", ["--hull-model", str(self.hull),
                "--detector-kind", "nanodet", "--crnn-model", str(self.crnn), "--tiled-hulls"])
        self.assertEqual((code, error), (0, ""))
        factory.assert_called_once_with(model_path=self.hull, detector_kind="nanodet",
                                       crnn_model_path=self.crnn, tiled_hulls=True)
        self.report("analyze", output)

    def test_intake_crnn_dispatch_preserves_immutable_inputs_and_default_tile_choice(self):
        crnn = importlib.import_module("race_ai.boat_video_crnn")
        ident = self.enqueue()
        manifest = self.private / "video-intake" / "jobs" / (ident+".json")
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.media, self.manifest, manifest)}
        with patch.object(crnn, "make_crnn_identity_extractor", return_value=self.extractor) as factory, \
                patch("shutil.which", side_effect=AssertionError("unexpected legacy OCR discovery")):
            code, output, error = self.invoke("intake", ["--hull-model", str(self.hull),
                                                       "--crnn-model", str(self.crnn)])
        self.assertEqual((code, error), (0, ""))
        factory.assert_called_once_with(model_path=self.hull, detector_kind="yolox", crnn_model_path=self.crnn)
        self.report("intake", output)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_both_entrypoints_allow_explicit_tiles_with_existing_tesseract(self):
        for surface in ("analyze", "intake"):
            with self.subTest(surface=surface):
                if surface == "intake":
                    self.enqueue()
                with patch("race_ai.boat_video_identity.make_local_identity_extractor",
                           return_value=self.extractor) as factory:
                    code, output, error = self.invoke(surface, ["--hull-model", str(self.hull),
                        "--tesseract", str(self.tesseract), "--tessdata", str(self.tessdata), "--tiled-hulls"])
                self.assertEqual((code, error), (0, ""))
                factory.assert_called_once_with(model_path=self.hull, detector_kind="yolox",
                    tesseract_path=self.tesseract, tessdata_path=self.tessdata, tiled_hulls=True)
                self.assertNotIn("owner-secret", output+error)

    def test_crnn_requires_hull_and_cannot_mix_legacy_ocr_flags(self):
        bad = (["--crnn-model", str(self.crnn)], ["--tiled-hulls"],
               ["--hull-model", str(self.hull), "--crnn-model", str(self.crnn), "--tesseract", str(self.tesseract)],
               ["--hull-model", str(self.hull), "--crnn-model", str(self.crnn), "--tessdata", str(self.tessdata)])
        for surface in ("analyze", "intake"):
            for flags in bad:
                with self.subTest(surface=surface, flags=flags):
                    code, output, error = self.invoke(surface, flags)
                    self.assertEqual((code, output), (2, ""))
                    self.assertNotIn("owner-secret", error)
                    self.assertEqual(list(self.private.iterdir()), [])

    def test_optional_vision_flags_refuse_an_injected_extractor(self):
        for surface in ("analyze", "intake"):
            for flags in (["--hull-model", str(self.hull), "--crnn-model", str(self.crnn)],
                          ["--hull-model", str(self.hull), "--tiled-hulls"]):
                with self.subTest(surface=surface, flags=flags):
                    code, output, error = self.invoke(surface, flags, extractor=self.extractor)
                    self.assertEqual((code, output), (2, ""))
                    self.assertNotIn("owner-secret", error)
                    self.assertEqual(list(self.private.iterdir()), [])

    def test_invalid_option_values_and_remote_paths_are_sanitized(self):
        bad = (["--hull-model", str(self.hull), "--tiled-hulls=owner-secret"],
               ["--hull-model", str(self.hull), "--crnn-model"],
               ["--hull-model", str(self.hull), "--crnn-model", "https://user:owner-secret@example.invalid/model.onnx"],
               ["--hull-model", str(self.hull), "--crnn-model", "../owner-secret/model.onnx"],
               ["--hull-model", str(self.hull), "--crnn-model", ""])
        for surface in ("analyze", "intake"):
            for flags in bad:
                with self.subTest(surface=surface, flags=flags):
                    code, output, error = self.invoke(surface, flags)
                    self.assertEqual((code, output), (2, ""))
                    self.assertNotIn("owner-secret", error)
                    self.assertNotIn("example.invalid", error)
                    self.assertEqual(list(self.private.iterdir()), [])

    def test_model_setup_failures_do_not_expose_asset_paths_or_create_outputs(self):
        crnn = importlib.import_module("race_ai.boat_video_crnn")
        for surface in ("analyze", "intake"):
            with self.subTest(surface=surface), patch.object(crnn, "make_crnn_identity_extractor",
                    side_effect=ValueError("owner-secret filepath and token")):
                code, output, error = self.invoke(surface, ["--hull-model", str(self.hull),
                                                          "--crnn-model", str(self.crnn)])
                self.assertEqual((code, output), (2, ""))
                self.assertEqual(error, ("BOAT_VIDEO_ANALYSIS_REJECTED\n" if surface == "analyze"
                                         else "BOAT_VIDEO_INTAKE_REJECTED\n"))
                self.assertEqual(list(self.private.iterdir()), [])

    def test_missing_local_crnn_asset_is_reported_as_analysis_failure(self):
        self.crnn.unlink()
        crnn = importlib.import_module("race_ai.boat_video_crnn")
        # Isolate the real missing-CRNN-file check from hull model loading.
        with patch.object(crnn, "PinnedBoatDetector", return_value=lambda frame: []):
            code, output, error = self.invoke("analyze", ["--hull-model", str(self.hull),
                                                        "--crnn-model", str(self.crnn)])
        self.assertEqual((code, output, error), (2, "", "BOAT_VIDEO_ANALYSIS_REJECTED\n"))
        self.assertEqual(list(self.private.iterdir()), [])

    def test_intake_retains_terminal_failure_for_missing_local_crnn_without_path_disclosure(self):
        self.crnn.unlink()
        self.enqueue()
        crnn = importlib.import_module("race_ai.boat_video_crnn")
        with patch.object(crnn, "PinnedBoatDetector", return_value=lambda frame: []):
            code, output, error = self.invoke("intake", ["--hull-model", str(self.hull),
                                                       "--crnn-model", str(self.crnn)])
        self.assertEqual((code, error), (0, ""))
        summary = json.loads(output)
        self.assertEqual((summary["processed"], summary["failed"], summary["succeeded"]), (1, 1, 0))
        self.assertEqual(summary["counts"]["FAILED"], 1)
        self.assertNotIn("owner-secret", output)
        self.assertFalse(list((self.private / "video-evaluations").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
