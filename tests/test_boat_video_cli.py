"""The local-video command writes private evidence without editing its inputs."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "boat_video_analyze.py"
RACE = "20200401-01-01"
CUTOFF = "2020-04-01T12:00:00+09:00"


def cli(test):
    if not SCRIPT.is_file():
        test.fail("isolated local-video CLI is missing")
    spec = importlib.util.spec_from_file_location("boat_video_cli_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BoatVideoCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / "owner-secret-recording.mp4"
        self.media.write_bytes(b"injected extractor fixture")
        self.digest = sha256(self.media.read_bytes()).hexdigest()
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.manifest = self.root / "job.json"
        self.job = {"schema_version": "RACE_AI_BOAT_VIDEO_JOB_V1", "race_id": RACE,
            "cutoff_at": CUTOFF,
            "roster": [{"lane": n, "registration_number": str(4200 + n)} for n in range(1, 7)],
            "source": {"kind": "OWNER_LOCAL", "media_sha256": self.digest,
                "captured_at": "2020-04-01T11:40:00+09:00", "identity_status": "OWNER_DECLARED"}}
        self.manifest.write_text(json.dumps(self.job), encoding="utf-8")
        self.tracking = {"schema_version": "RACE_AI_BOAT_VIDEO_TRACKS_V1",
            "media_sha256": self.digest, "width": 320, "height": 240,
            "duration_seconds": 1.0, "timeline_source": "MEDIA_PTS",
            "media_pts_origin_seconds": 0.0, "coordinate_space": "REFERENCE_IMAGE_PX",
            "model_eligible": False, "validation_status": "UNVALIDATED",
            "tracks": [{"lane": n, "identity_status": "COLOR_CANDIDATE", "samples": []}
                       for n in range(1, 7)],
            "quality": {"flags": ["INJECTED_TEST_ONLY"], "camera_estimates": [],
                        "position_error_scope": "UNCERTIFIED", "decoded_frame_count": 10}}
        self.tracking["tracks"][2]["samples"] = [
            {"t": i / 10, "frame_index": i, "scene": 0, "valid": True,
             "x": float(3 * i), "y": 0.0, "position_error": 0.1} for i in range(6)]

    def arguments(self):
        return ["--video", str(self.media), "--job", str(self.manifest),
                "--private-root", str(self.private)]

    def invoke(self, arguments=None, *, extractor=None, use_real=False):
        stdout, stderr = io.StringIO(), io.StringIO()
        module = cli(self)
        if extractor is None and not use_real:
            extractor = lambda path, *, options=None: deepcopy(self.tracking)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = module.main(self.arguments() if arguments is None else arguments,
                                   extractor=extractor)
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()

    def view(self):
        return {"event_date_jst": "2020-04-01", "records": [{"sport": "boat",
            "race_id": RACE, "cutoff_at": CUTOFF,
            "participants": [{"number": n, "registration_no": str(4200 + n)} for n in range(1, 7)],
            "prediction": {"model_id": "saved", "ordered_top8": [[1, 2, 3]], "sha256": "b" * 64},
            "result": {"order": [2, 1, 3]}, "result_observations": [{"seen": "later"}],
            "saved_cutoff_variants": [CUTOFF], "saved_schedule_cutoff_variants": [CUTOFF]}]}

    def test_writes_sealed_private_report_and_prints_only_digest_paths_and_counts(self):
        before = self.media.read_bytes(), self.manifest.read_bytes()
        code, output, error = self.invoke()
        self.assertEqual((code, error), (0, ""))
        summary = json.loads(output)
        self.assertEqual(set(summary), {"report_sha256", "report_path", "lane_count", "measured_phase_count"})
        report_path = self.private / "video-evaluations" / (summary["report_sha256"] + ".json")
        self.assertEqual(summary["report_path"], str(report_path))
        self.assertEqual(summary["lane_count"], 6)
        self.assertEqual(summary["measured_phase_count"], 1)
        report = json.loads(report_path.read_bytes())
        self.assertFalse(report["model_eligible"])
        self.assertFalse(report["pre_cutoff_available"])
        self.assertEqual(report["validation_status"], "UNVALIDATED")
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
        self.assertNotIn(self.media.name, output)
        # A valid hexadecimal digest can coincidentally contain registration
        # digits. The exact summary field set above prevents roster disclosure;
        # check the emitted digest against the saved report instead.
        self.assertRegex(summary["report_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(summary["report_sha256"], report["report_sha256"])
        self.assertEqual(before, (self.media.read_bytes(), self.manifest.read_bytes()))

    def test_enriches_only_new_copy_and_preserves_original_json_bytes_and_mtime(self):
        original = self.root / "original-view.json"
        raw = json.dumps(self.view(), ensure_ascii=False, indent=3).encode() + b"\n"
        original.write_bytes(raw)
        before_mtime = original.stat().st_mtime_ns
        destination = self.root / "enriched-view.json"
        code, output, error = self.invoke(self.arguments() + ["--view-in", str(original), "--view-out", str(destination)])
        self.assertEqual((code, error), (0, ""))
        summary = json.loads(output)
        self.assertEqual(summary["view_out"], str(destination))
        self.assertEqual(summary["attached_report_count"], 1)
        enriched = json.loads(destination.read_bytes())
        reports = enriched["records"][0].pop("boat_video_evaluations")
        self.assertEqual(len(reports), 1)
        self.assertEqual(enriched, self.view())
        self.assertEqual(original.read_bytes(), raw)
        self.assertEqual(original.stat().st_mtime_ns, before_mtime)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_unpaired_view_options_fail_before_creating_reports(self):
        for option in ("--view-in", "--view-out"):
            with self.subTest(option=option):
                code, output, _ = self.invoke(self.arguments() + [option, str(self.root / "missing")])
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertEqual(list(self.private.iterdir()), [])

    def test_unrelated_view_metadata_does_not_break_new_copy_or_report_count(self):
        original = self.root / "original-view.json"
        value = self.view()
        value["records"].append({"sport": "horse", "boat_video_evaluations": 71})
        original.write_text(json.dumps(value), encoding="utf-8")
        destination = self.root / "enriched-view.json"
        code, output, error = self.invoke(self.arguments() + ["--view-in", str(original), "--view-out", str(destination)])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output)["attached_report_count"], 1)
        self.assertEqual(json.loads(destination.read_bytes())["records"][1], value["records"][1])

    def test_url_missing_and_linked_inputs_fail_without_printing_private_values(self):
        linked = self.root / "linked.mp4"
        linked.symlink_to(self.media)
        hardlink = self.root / "hardlink-job.json"
        os.link(self.manifest, hardlink)
        fifo = self.root / "fifo-job"
        os.mkfifo(fifo)
        cases = (("--video", "https://user:secret@private.example/signed.mp4?token=secret"),
                 ("--job", "file:///owner-secret-job.json"), ("--video", str(linked)),
                 ("--job", str(hardlink)), ("--job", str(fifo)),
                 ("--video", str(self.root / "missing-owner-secret.mp4")))
        for flag, value in cases:
            with self.subTest(flag=flag, value=value):
                arguments = self.arguments()
                arguments[arguments.index(flag) + 1] = value
                code, output, error = self.invoke(arguments)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertNotIn(value, error)
                self.assertNotIn("secret", error)
                self.assertEqual(list(self.private.iterdir()), [])

    def test_malformed_duplicate_nonfinite_and_missing_identity_jobs_fail_closed(self):
        missing = deepcopy(self.job)
        del missing["roster"]
        injected = deepcopy(self.job)
        injected["model_eligible"] = True
        for raw in (b"{", b'{"schema_version":1,"schema_version":2}', b'{"x":NaN}',
                    json.dumps(missing).encode(), json.dumps(injected).encode()):
            with self.subTest(raw=raw):
                self.manifest.write_bytes(raw)
                code, output, error = self.invoke()
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertNotIn("4201", error)
                self.assertEqual(list(self.private.iterdir()), [])

    def test_existing_git_and_symlink_outputs_are_rejected_before_analysis(self):
        original = self.root / "original-view.json"
        original.write_text(json.dumps(self.view()), encoding="utf-8")
        existing = self.root / "existing.json"
        existing.write_bytes(b"keep exactly")
        linked = self.root / "symlink.json"
        linked.symlink_to(existing)
        hardlink = self.root / "hardlink.json"
        os.link(existing, hardlink)
        checkout = self.root / "checkout"
        checkout.mkdir()
        (checkout / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(self.private, target_is_directory=True)
        for destination in (original, existing, linked, hardlink,
                            checkout / "new.json", linked_parent / "new.json"):
            with self.subTest(destination=destination):
                code, output, error = self.invoke(self.arguments() + ["--view-in", str(original), "--view-out", str(destination)])
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertEqual(existing.read_bytes(), b"keep exactly")
                self.assertEqual(list(self.private.iterdir()), [])
                self.assertFalse((checkout / "new.json").exists())

    def test_extractor_errors_do_not_leak_private_content_or_leave_output(self):
        def rejected(path, *, options=None):
            raise ValueError("owner-secret-file https://private.example/?token=secret")
        code, output, error = self.invoke(extractor=rejected)
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertNotIn("secret", error)
        self.assertEqual(list(self.private.iterdir()), [])

    def test_local_identity_flags_configure_extractor_without_persisting_asset_paths(self):
        model = self.root / "owner-secret-hull.onnx"
        executable = self.root / "owner-secret-tesseract"
        data = self.root / "owner-secret-tessdata"
        model.write_bytes(b"controlled factory fixture")
        executable.write_bytes(b"controlled factory fixture")
        data.mkdir()
        original = self.root / "original-view.json"
        original.write_text(json.dumps(self.view(), indent=3), encoding="utf-8")
        destination = self.root / "enriched-view.json"
        original_bytes, original_mtime = original.read_bytes(), original.stat().st_mtime_ns
        self.job["options"] = {"sampling_fps": 5.0}
        self.manifest.write_text(json.dumps(self.job), encoding="utf-8")
        inputs = (self.media.read_bytes(), self.manifest.read_bytes())
        tracking = deepcopy(self.tracking)
        for track in tracking["tracks"]:
            track["identity_status"] = "NUMBER_TEMPORAL_CANDIDATE"
        tracking["quality"]["identity_provider"] = {
            "engine": "CONTROLLED_TEST", "model_sha256": "c" * 64,
            "identity_validated": False, "model_eligible": False}
        arguments = self.arguments() + ["--hull-model", str(model), "--detector-kind", "nanodet",
            "--tesseract", str(executable), "--tessdata", str(data),
            "--view-in", str(original), "--view-out", str(destination)]
        extract = Mock(return_value=tracking)
        with patch("race_ai.boat_video_identity.make_local_identity_extractor", return_value=extract) as factory:
            code, output, error = self.invoke(arguments, use_real=True)
        self.assertEqual((code, error), (0, ""))
        factory.assert_called_once_with(model_path=model, detector_kind="nanodet",
            tesseract_path=executable, tessdata_path=data)
        extract.assert_called_once_with(self.media, options={"sampling_fps": 5.0})
        summary = json.loads(output)
        report_bytes = Path(summary["report_path"]).read_bytes()
        report = json.loads(report_bytes)
        self.assertEqual(report["analysis_parameters"], {"options": {"sampling_fps": 5.0}})
        self.assertEqual([lane["identity_status"] for lane in report["measurements"]["lanes"]],
                         ["NUMBER_TEMPORAL_CANDIDATE"] * 6)
        self.assertFalse(report["model_eligible"])
        self.assertFalse(report["measurements"]["identity_validated"])
        self.assertEqual(report["validation_status"], "UNVALIDATED")
        for private_path in (model, executable, data):
            self.assertNotIn(str(private_path), report_bytes.decode())
            self.assertNotIn(str(private_path), output + error)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(original.stat().st_mtime_ns, original_mtime)
        self.assertEqual(inputs, (self.media.read_bytes(), self.manifest.read_bytes()))
        enriched = json.loads(destination.read_bytes())
        self.assertEqual(enriched["records"][0].pop("boat_video_evaluations"), [report])
        self.assertEqual(enriched, self.view())

    def test_local_identity_defaults_use_system_ocr_and_standard_english_data(self):
        model = self.root / "model.onnx"
        standard = Path("/usr/share/tesseract-ocr/5/tessdata")
        is_file = Path.is_file
        with patch("race_ai.boat_video_identity.make_local_identity_extractor",
                   return_value=lambda path, *, options=None: deepcopy(self.tracking)) as factory, \
                patch("shutil.which", return_value="/usr/bin/tesseract"), \
                patch("pathlib.Path.is_file", autospec=True,
                      side_effect=lambda path: path == standard / "eng.traineddata" or is_file(path)):
            code, output, error = self.invoke(self.arguments() + ["--hull-model", str(model)], use_real=True)
        self.assertEqual((code, error), (0, ""))
        factory.assert_called_once()
        supplied = factory.call_args.kwargs
        self.assertEqual(supplied["model_path"], model)
        self.assertEqual(supplied["detector_kind"], "yolox")
        self.assertEqual(supplied["tesseract_path"], Path("/usr/bin/tesseract"))
        self.assertEqual(supplied["tessdata_path"], standard)
        self.assertNotIn("tesseract", output)

    def test_no_identity_flags_preserve_default_extractor_boundary(self):
        with patch("race_ai.boat_video_identity.make_local_identity_extractor") as factory, \
                patch("race_ai.boat_video_tracking.extract_tracks", return_value=deepcopy(self.tracking)) as extract:
            code, output, error = self.invoke(use_real=True)
        self.assertEqual((code, error), (0, ""))
        factory.assert_not_called()
        extract.assert_called_once_with(self.media, options=None)
        report = json.loads(Path(json.loads(output)["report_path"]).read_bytes())
        self.assertEqual(report["tracking"], self.tracking)
        self.assertEqual(report["analysis_parameters"], {})

    def test_missing_system_ocr_fails_without_creating_report_or_leaking_assets(self):
        with patch("shutil.which", return_value=None), \
                patch("race_ai.boat_video_identity.make_local_identity_extractor") as factory:
            code, output, error = self.invoke(self.arguments() + ["--hull-model", "/owner-secret/model.onnx"], use_real=True)
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertEqual(error, "BOAT_VIDEO_ANALYSIS_REJECTED\n")
        self.assertEqual(list(self.private.iterdir()), [])
        factory.assert_not_called()

    def test_identity_flags_require_model_and_refuse_ambiguous_extractor_injection(self):
        for extra in (["--detector-kind", "yolox"], ["--tesseract", "/owner-secret/ocr"],
                      ["--tessdata", "/owner-secret/data"], ["--hull-model", "/owner-secret/model"]):
            with self.subTest(extra=extra):
                code, output, error = self.invoke(self.arguments() + extra, use_real=extra[0] != "--hull-model")
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertNotIn("owner-secret", error)
                self.assertEqual(list(self.private.iterdir()), [])

    def test_invalid_identity_assets_and_flags_fail_without_private_values_or_output(self):
        corrupt = self.root / "owner-secret-hull.onnx"
        corrupt.write_bytes(b"not a pinned model")
        for extra in (["--hull-model", str(corrupt)],
                      ["--hull-model", str(self.root / "owner-secret-missing.onnx")],
                      ["--hull-model", "https://owner-secret.example/model"],
                      ["--hull-model", str(corrupt), "--detector-kind", "owner-secret-kind"]):
            with self.subTest(extra=extra):
                code, output, error = self.invoke(self.arguments() + extra, use_real=True)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertNotIn("owner-secret", error)
                self.assertEqual(list(self.private.iterdir()), [])

    def test_import_and_help_do_not_require_optional_video_libraries(self):
        cli(self)
        command = ("import runpy, sys; "
                   "runpy.run_path(sys.argv[1], run_name='cli_import_only'); "
                   "assert 'cv2' not in sys.modules; assert 'numpy' not in sys.modules")
        result = subprocess.run([sys.executable, "-I", "-c", command, str(SCRIPT)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--private-root", result.stdout)
        self.assertIn("--hull-model", result.stdout)


if __name__ == "__main__":
    unittest.main()
