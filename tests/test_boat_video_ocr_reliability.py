"""Synthetic OCR process faults; these tests do not validate field identities."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


CV_AVAILABLE = importlib.util.find_spec("cv2") is not None
HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def process_output(text=None, confidence=98):
    body = "" if text is None else f"5\t1\t1\t1\t1\t1\t24\t18\t30\t36\t{confidence}\t{text}\n"
    return subprocess.CompletedProcess([], 0, (HEADER + body).encode(), b"")


@unittest.skipUnless(CV_AVAILABLE, "optional video dependencies are unavailable")
class LocalOCRReliabilityTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from race_ai import boat_video_identity
        self.module = boat_video_identity
        self.frame = np.full((180, 640, 3), 100, np.uint8)
        self.crop = self.frame[70:94, 50:80].copy()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.executable = self.root / "tesseract"
        self.executable.write_bytes(b"test executable boundary")
        self.executable.chmod(0o700)
        (self.root / "eng.traineddata").write_bytes(b"test language boundary")

    def reader(self):
        version = subprocess.CompletedProcess([], 0, b"tesseract 5.5.0\n", b"")
        with patch.object(self.module.subprocess, "run", return_value=version):
            return self.module.LocalTesseractNumberReader(
                tesseract_path=self.executable, tessdata_path=self.root)

    def provider(self, reader):
        return self.module.BoatIdentityProvider(detector=lambda frame: [], number_reader=reader)

    def identify(self, provider, detections, frame_index):
        return provider.identify(self.frame, detections, t=frame_index / 10,
                                 frame_index=frame_index, scene=0)

    def hull(self, x):
        return {"box": [x, 70, 30, 24], "score": .95}

    def test_low_confidence_sparse_digit_does_not_prevent_single_character_fallback(self):
        reader = self.reader()
        for low_score in (0, 89, 89.999):
            with self.subTest(low_score=low_score):
                replies = {11: process_output("6", low_score), 10: process_output("2", 98)}

                def run(command, **kwargs):
                    return replies[int(command[command.index("--psm") + 1])]

                with patch.object(self.module.subprocess, "run", side_effect=run):
                    rows = reader(self.crop)
                self.assertEqual(rows, [{"text": "2", "score": .98, "box": [8., 6., 10., 12.]}])

    def test_two_low_confidence_modes_never_supply_an_accepted_number(self):
        reader = self.reader()
        provider = self.provider(reader)
        for index in range(3):
            with patch.object(self.module.subprocess, "run", side_effect=[
                    process_output("6", 0), process_output("2", 89)]):
                output = self.identify(provider, [self.hull(50)], index)
            self.assertEqual(output["regions"], [])
        self.assertFalse(output["model_eligible"])
        self.assertFalse(output["identity_validated"])

    def test_accepted_sparse_confidence_preserves_identity_without_a_fallback(self):
        reader = self.reader()
        provider = self.provider(reader)
        for index, score in enumerate((90, 98, 100)):
            with patch.object(self.module.subprocess, "run", side_effect=[process_output("2", score)]):
                output = self.identify(provider, [self.hull(50)], index)
        self.assertEqual([row["lane"] for row in output["regions"]], [2])
        self.assertEqual(output["regions"][0]["number_evidence"]["minimum_confidence"], .9)

    def test_fallback_modes_share_the_original_three_second_deadline(self):
        reader = self.reader()
        timeouts = []
        replies = iter([process_output("6", 0), process_output("2", 98)])

        def run(command, **kwargs):
            timeouts.append(kwargs["timeout"])
            return next(replies)

        with patch.object(self.module.time, "monotonic", side_effect=[100., 100.25, 102.]):
            with patch.object(self.module.subprocess, "run", side_effect=run):
                rows = reader(self.crop)
        self.assertEqual(rows[0]["text"], "2")
        self.assertEqual(timeouts, [2.75, 1.])

    def test_exhausted_shared_deadline_is_a_typed_timeout(self):
        reader = self.reader()
        with patch.object(self.module.time, "monotonic", side_effect=[100., 100.25, 103.01]):
            with patch.object(self.module.subprocess, "run", side_effect=[process_output()]):
                with self.assertRaises(ValueError) as caught:
                    reader(self.crop)
        self.assertEqual(getattr(caught.exception, "code", None), "TIMEOUT")
        self.assertEqual(type(caught.exception).__name__, "LocalOCRInferenceError")

    def test_process_failures_have_safe_typed_codes(self):
        reader = self.reader()
        private = "/private/media/secret-clip.png"
        cases = [
            (subprocess.TimeoutExpired(private, 3, stderr=private.encode()), "TIMEOUT"),
            (subprocess.CalledProcessError(2, private, stderr=private.encode()), "PROCESS_FAILED"),
            (OSError(private), "PROCESS_FAILED"),
            (subprocess.CompletedProcess([], 0, b"\xff", private.encode()), "OUTPUT_REJECTED"),
            (subprocess.CompletedProcess([], 0, b"x" * 262145, private.encode()), "OUTPUT_REJECTED"),
            (subprocess.CompletedProcess([], 0, (HEADER + "x" * 150000).encode(),
                private.encode()), "OUTPUT_REJECTED"),
            (subprocess.CompletedProcess([], 0,
                (HEADER + "5\t1\t1\t1\t1\t1\t24\t18\t30\t36\tbad\t2\n").encode(),
                private.encode()), "OUTPUT_REJECTED"),
        ]
        for reply, expected in cases:
            with self.subTest(code=expected, reply=type(reply).__name__):
                with patch.object(self.module.subprocess, "run", side_effect=[reply]):
                    with self.assertRaises(Exception) as caught:
                        reader(self.crop)
                self.assertEqual(getattr(caught.exception, "code", None), expected)
                self.assertEqual(type(caught.exception).__name__, "LocalOCRInferenceError")
                self.assertNotIn(private, str(caught.exception))
                self.assertNotIn(str(self.root), str(caught.exception))

    def test_runtime_failure_blocks_only_affected_hull_and_requires_three_fresh_observations(self):
        for fault, flag in [
                (subprocess.TimeoutExpired("private", 3), "LOCAL_OCR_TIMEOUT"),
                (subprocess.CalledProcessError(2, "private"), "LOCAL_OCR_PROCESS_FAILED"),
                (subprocess.CompletedProcess([], 0, b"\xff", b"private"), "LOCAL_OCR_OUTPUT_REJECTED")]:
            with self.subTest(flag=flag):
                reader = self.reader()
                provider = self.provider(reader)
                hulls = [self.hull(50), self.hull(300)]
                with patch.object(self.module.subprocess, "run", side_effect=[
                        process_output("1"), process_output("2")] * 3):
                    for index in range(3):
                        output = self.identify(provider, hulls, index)
                ids = {row["lane"]: row["track_id"] for row in output["regions"]}
                self.assertEqual(set(ids), {1, 2})
                with patch.object(self.module.subprocess, "run", side_effect=[fault, process_output("2")]):
                    try:
                        interrupted = self.identify(provider, hulls, 3)
                    except ValueError as error:
                        self.fail(f"a single typed process fault aborted healthy hulls: {error}")
                self.assertEqual([row["lane"] for row in interrupted["regions"]], [2])
                self.assertEqual(interrupted["regions"][0]["track_id"], ids[2])
                self.assertIn(flag, interrupted["quality_flags"])
                self.assertEqual(interrupted["exclusion_boxes"], [[50., 70., 30., 24.], [300., 70., 30., 24.]])
                self.assertEqual(interrupted["unresolved_candidate_count"], 1)
                for index in (4, 5, 6):
                    with patch.object(self.module.subprocess, "run", side_effect=[
                            process_output("1"), process_output("2")]):
                        output = self.identify(provider, hulls, index)
                    self.assertEqual([row["lane"] for row in output["regions"]], [2] if index < 6 else [1, 2])
                recovered = next(row for row in output["regions"] if row["lane"] == 1)
                self.assertNotEqual(recovered["track_id"], ids[1])
                self.assertEqual(recovered["number_evidence"]["observations"], 3)
                self.assertEqual(recovered["number_evidence"]["first_frame_index"], 4)
                self.assertFalse(output["model_eligible"])
                self.assertFalse(output["identity_validated"])
                self.assertNotIn("private", json.dumps(interrupted))

    def test_failed_hull_cannot_redirect_previous_identity_to_an_unread_neighbor(self):
        reader = self.reader()
        provider = self.provider(reader)
        with patch.object(self.module.subprocess, "run", side_effect=[process_output("1")] * 3):
            for index in range(3):
                output = self.identify(provider, [self.hull(100)], index)
        self.assertEqual([row["lane"] for row in output["regions"]], [1])
        # The neighbor is geometrically close enough to inherit if the failed
        # hull's predicted prior track is incorrectly retained.
        with patch.object(self.module.subprocess, "run", side_effect=[
                subprocess.TimeoutExpired("private", 3), process_output(), process_output()]):
            try:
                interrupted = self.identify(provider, [self.hull(100), self.hull(135)], 3)
            except ValueError as error:
                self.fail(f"an OCR interruption aborted the frame: {error}")
        self.assertEqual(interrupted["regions"], [])
        self.assertEqual(len(interrupted["exclusion_boxes"]), 2)
        with patch.object(self.module.subprocess, "run", side_effect=[process_output("1")] * 3):
            for index in (4, 5, 6):
                output = self.identify(provider, [self.hull(100)], index)
                self.assertEqual([row["lane"] for row in output["regions"]], [] if index < 6 else [1])

    def test_moving_failed_hull_cannot_redirect_identity_but_adjacent_marked_hull_continues(self):
        reader = self.reader()
        provider = self.provider(reader)
        with patch.object(self.module.subprocess, "run", side_effect=[
                process_output("1"), process_output("2")] * 3):
            for index in range(3):
                output = self.identify(provider, [self.hull(100), self.hull(170)], index)
        ids = {row["lane"]: row["track_id"] for row in output["regions"]}
        self.assertEqual(set(ids), {1, 2})
        # A failed hull at x135 is within both old tracks' association gates,
        # without intersecting either old box. An unread hull at old lane 1's
        # position cannot inherit its identity; the explicit mark 2 anchors the
        # adjacent healthy hull and preserves that hull's evidence.
        with patch.object(self.module.subprocess, "run", side_effect=[
                subprocess.TimeoutExpired("private", 3), process_output(), process_output(),
                process_output("2")]):
            interrupted = self.identify(provider, [self.hull(135), self.hull(100), self.hull(170)], 3)
        self.assertEqual([row["lane"] for row in interrupted["regions"]], [2])
        self.assertEqual(interrupted["regions"][0]["track_id"], ids[2])
        self.assertEqual(interrupted["regions"][0]["number_evidence"]["observations"], 4)
        self.assertEqual(len(interrupted["exclusion_boxes"]), 3)
        for index in (4, 5, 6):
            with patch.object(self.module.subprocess, "run", side_effect=[
                    process_output("1"), process_output("2")]):
                output = self.identify(provider, [self.hull(135), self.hull(170)], index)
            self.assertEqual([row["lane"] for row in output["regions"]], [2] if index < 6 else [1, 2])
        recovered = next(row for row in output["regions"] if row["lane"] == 1)
        self.assertNotEqual(recovered["track_id"], ids[1])
        self.assertEqual(recovered["number_evidence"]["observations"], 3)

    def test_distant_failed_hull_does_not_interrupt_an_unread_healthy_track(self):
        reader = self.reader()
        provider = self.provider(reader)
        with patch.object(self.module.subprocess, "run", side_effect=[process_output("1")] * 3):
            for index in range(3):
                output = self.identify(provider, [self.hull(100)], index)
        old_id = output["regions"][0]["track_id"]
        with patch.object(self.module.subprocess, "run", side_effect=[
                subprocess.TimeoutExpired("private", 3), process_output(), process_output()]):
            output = self.identify(provider, [self.hull(220), self.hull(100)], 3)
        self.assertEqual([row["lane"] for row in output["regions"]], [1])
        self.assertEqual(output["regions"][0]["track_id"], old_id)
        self.assertFalse(output["regions"][0]["number_evidence"]["current_observation"])

    def test_initialization_failure_remains_fatal(self):
        private = "/private/assets/tesseract"
        with patch.object(self.module.subprocess, "run", side_effect=OSError(private)):
            with self.assertRaises(ValueError) as caught:
                self.module.LocalTesseractNumberReader(tesseract_path=self.executable, tessdata_path=self.root)
        self.assertEqual(type(caught.exception), ValueError)
        self.assertNotIn(private, str(caught.exception))

    def test_unexpected_reader_errors_and_malformed_contracts_remain_fatal(self):
        def broken(crop):
            raise ValueError("unexpected injected reader failure")

        with self.assertRaisesRegex(ValueError, "unexpected injected reader failure"):
            self.identify(self.provider(broken), [self.hull(50)], 0)
        with self.assertRaisesRegex(ValueError, "bounded OCR rows"):
            self.identify(self.provider(lambda crop: {"bad": "contract"}), [self.hull(50)], 0)
