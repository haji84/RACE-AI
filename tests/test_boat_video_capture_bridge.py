"""A capture receipt must not silently authenticate a current race."""
from copy import deepcopy
import unittest

from pathlib import Path
from datetime import datetime, timezone
import io
import importlib.util
import shutil
import subprocess
import tempfile
from unittest.mock import patch
from race_ai.boat_video_capture_bridge import build_job, enqueue_export


class CaptureRaceBindingTests(unittest.TestCase):
    def setUp(self):
        self.export = {
            "schema": "RACE_AI_HLS_CAPTURE_EXPORT_V1", "source_id": "owner-feed",
            "source_role": "OWNER_AUTHORIZED", "manifest_sha256": "a" * 64,
            "window_id": 1, "media_path": "/private/window.mp4",
            "media_sha256": "b" * 64, "receipt_path": "/private/receipt.json",
            "receipt_sha256": "c" * 64, "captured_at": "2026-11-07T01:00:00+00:00",
        }
        self.template = {
            "schema_version": "RACE_AI_BOAT_VIDEO_JOB_V1",
            "race_id": "20261107-01-01", "cutoff_at": "2026-11-07T01:10:00+00:00",
            "roster": [{"lane": lane, "registration_number": str(4000 + lane)}
                       for lane in range(1, 7)],
            "source": {"kind": "OWNER_LOCAL", "identity_status": "OWNER_DECLARED"},
        }

    def test_absent_race_binding_keeps_completed_capture_out_of_intake(self):
        self.assertIsNone(build_job(self.export, None))

    def test_owner_binding_uses_actual_capture_clock_and_receipt(self):
        before = deepcopy(self.template)
        job = build_job(self.export, self.template)
        self.assertEqual(job["source"], {
            "kind": "OWNER_LOCAL", "identity_status": "OWNER_DECLARED",
            "media_sha256": "b" * 64, "captured_at": "2026-11-07T01:00:00+00:00",
            "source_metadata_sha256": "c" * 64,
        })
        self.assertEqual(self.template, before)

    def test_template_cannot_rewrite_capture_time_hash_or_official_identity(self):
        for field, value in (("captured_at", "2026-11-07T00:00:00+00:00"),
                             ("media_sha256", "d" * 64),
                             ("source_metadata_sha256", "e" * 64),
                             ("kind", "OFFICIAL_BROWSER_CAPTURE"),
                             ("identity_status", "SOURCE_METADATA_LINKED")):
            with self.subTest(field=field):
                template = deepcopy(self.template)
                template["source"][field] = value
                with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
                    build_job(self.export, template)

    def test_licensed_historical_footage_cannot_become_current_race_by_declaration(self):
        self.export["source_role"] = "LICENSED_DEVELOPMENT"
        self.assertIsNone(build_job(self.export, None))
        with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
            build_job(self.export, self.template)

    def test_late_export_clock_is_preserved_for_existing_historical_classification(self):
        self.export["captured_at"] = "2026-11-07T01:11:00+00:00"
        job = build_job(self.export, self.template)
        self.assertEqual(job["source"]["captured_at"], "2026-11-07T01:11:00+00:00")

    def test_duplicate_roster_or_previous_day_capture_is_rejected(self):
        self.template["roster"][1]["registration_number"] = "4001"
        with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
            build_job(self.export, self.template)
        self.template["roster"][1]["registration_number"] = "4002"
        self.export["captured_at"] = "2026-11-05T01:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
            build_job(self.export, self.template)

    def test_synthetic_source_cannot_masquerade_as_owner_local(self):
        self.export["source_role"] = "SYNTHETIC_TEST"
        with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
            build_job(self.export, self.template)
        self.template["source"] = {"kind": "SYNTHETIC_TEST", "identity_status": "SYNTHETIC"}
        self.assertEqual(build_job(self.export, self.template)["source"]["kind"], "SYNTHETIC_TEST")

    def test_fabricated_export_cannot_create_intake_even_without_a_race_template(self):
        with tempfile.TemporaryDirectory() as root:
            for template in (None, self.template):
                with self.subTest(bound=template is not None):
                    with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
                        enqueue_export(root, self.export, template)
                    self.assertFalse((Path(root) / "video-intake").exists())


@unittest.skipUnless(shutil.which("ffmpeg"), "local FFmpeg unavailable")
class SavedCaptureIntakeTests(unittest.TestCase):
    """Actual local remux/receipt verification and intake, no external HTTP."""
    def setUp(self):
        from race_ai.boat_video_capture import Collector, HTTPResult
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        sample = self.root / "fictional.ts"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                        "testsrc2=size=160x96:rate=6", "-t", "1", "-an", "-c:v",
                        "mpeg2video", "-threads", "1", "-f", "mpegts", str(sample)],
                       check=True, capture_output=True)
        raw = sample.read_bytes()
        url = "https://fictional.example/live.m3u8"
        routes = {url: b"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nclip.ts\n#EXT-X-ENDLIST\n",
                  "https://fictional.example/clip.ts": raw}
        def transport(target, headers):
            return HTTPResult(200, {}, io.BytesIO(routes[target]))
        manifest = {"schema": "RACE_AI_AUTHORIZED_HLS_SOURCE_V1", "source_id": "fictional",
                    "playlist_url": url, "allowed_origins": ["https://fictional.example"],
                    "source_role": "SYNTHETIC_TEST", "source_evidence_sha256": "a" * 64}
        self.collector = Collector(self.root / "capture", manifest, fetch=transport,
                                   clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.addCleanup(self.collector.close)
        ready = self.collector.tick()["ready_windows"]
        self.export = self.collector.export_window(ready[0])
        self.intake = self.root / "intake"
        self.intake.mkdir(mode=0o700)
        self.template = {"schema_version": "RACE_AI_BOAT_VIDEO_JOB_V1", "race_id": "20300101-01-01",
                         "cutoff_at": "2030-01-01T00:10:00+00:00",
                         "roster": [{"lane": i, "registration_number": str(4000 + i)} for i in range(1, 7)],
                         "source": {"kind": "SYNTHETIC_TEST", "identity_status": "SYNTHETIC"}}

    def test_verified_export_replay_creates_one_content_addressed_intake_job(self):
        first = enqueue_export(self.intake, self.export, self.template)
        second = enqueue_export(self.intake, self.export, self.template)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ENQUEUED_UNVALIDATED")
        self.assertEqual(len(list((self.intake / "video-intake" / "jobs").iterdir())), 1)

    def test_failed_enqueue_can_replay_the_already_exported_capture(self):
        with patch("race_ai.boat_video_intake.enqueue", side_effect=OSError("private OS detail")):
            with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
                enqueue_export(self.intake, self.export, self.template)
        saved = self.collector.export_window(self.export["window_id"])
        self.assertEqual(saved, self.export)
        result = enqueue_export(self.intake, saved, self.template)
        self.assertEqual(result["status"], "ENQUEUED_UNVALIDATED")

    def test_forged_role_or_modified_media_is_rejected_before_intake(self):
        altered = {**self.export, "source_role": "OWNER_AUTHORIZED"}
        with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
            enqueue_export(self.intake, altered, self.template)
        Path(self.export["media_path"]).write_bytes(b"altered")
        with self.assertRaisesRegex(ValueError, "CAPTURE_BINDING_REJECTED"):
            enqueue_export(self.intake, self.export, self.template)
        self.assertFalse((self.intake / "video-intake").exists())

    def test_actual_ineligible_window_does_not_block_next_real_local_export(self):
        from race_ai.boat_video_capture import Collector, HTTPResult
        script = Path(__file__).resolve().parents[1] / "scripts" / "boat_video_capture.py"
        spec = importlib.util.spec_from_file_location("capture_cli_gate", script)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        playlist = (b"#EXTM3U\n#EXT-X-TARGETDURATION:121\n#EXTINF:121,\na.ts\n"
                    b"#EXTINF:1,\nb.ts\n#EXT-X-ENDLIST\n")
        raw = (self.root / "fictional.ts").read_bytes()
        url = "https://fictional.example/long.m3u8"
        def fetch(target, headers):
            return HTTPResult(200, {}, io.BytesIO(playlist if target == url else raw))
        source = {"schema": "RACE_AI_AUTHORIZED_HLS_SOURCE_V1", "source_id": "fictional-long",
                  "playlist_url": url, "allowed_origins": ["https://fictional.example"],
                  "source_role": "SYNTHETIC_TEST", "source_evidence_sha256": "a" * 64}
        collector = Collector(self.root / "long-capture", source, fetch=fetch,
                              clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.addCleanup(collector.close)
        self.assertEqual(collector.tick()["segments_saved"], 2)
        rows = collector.list_windows()
        self.assertFalse(rows[0]["analysis_exportable"])
        self.assertTrue(rows[1]["analysis_exportable"])
        cursor, results = cli.export_closed(collector, 0)
        self.assertEqual(cursor, 2)
        self.assertEqual([r["status"] for r in results], ["ARCHIVED_ANALYSIS_INELIGIBLE", "CAPTURE_ONLY"])
        self.assertFalse((self.root / "long-capture" / "exports" / "1.mp4").exists())
        self.assertTrue((self.root / "long-capture" / "exports" / "2.mp4").is_file())
