"""Exercise the CLI boundary without external source requests."""
import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "boat_video_capture.py"


def load_cli():
    spec = importlib.util.spec_from_file_location("capture_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaptureCLIContractTests(unittest.TestCase):
    def test_private_user_json_accepts_whitespace_but_rejects_duplicate_keys_and_nan(self):
        cli = load_cli()
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / "source.json"
            manifest.write_text('{\n  "source_id": "owner-feed"\n}\n')
            manifest.chmod(0o600)
            self.assertEqual(cli._private_json(str(manifest)), {"source_id": "owner-feed"})
            for text in ('{"source_id":"one","source_id":"two"}', '{"x":NaN}'):
                manifest.write_text(text)
                with self.assertRaises(ValueError):
                    cli._private_json(str(manifest))

    def test_invalid_arguments_do_not_echo_signed_url_values(self):
        cli = load_cli()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--unknown", "https://example.invalid/?token=PRIVATE_SENTINEL"])
        self.assertEqual(code, 2)
        self.assertNotIn("PRIVATE_SENTINEL", out.getvalue() + err.getvalue())
        self.assertIn("CAPTURE_ARGUMENTS_REJECTED", err.getvalue())

    def test_unsafe_manifest_is_rejected_before_fetch_and_without_payload_echo(self):
        cli = load_cli()
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / "manifest.json"
            manifest.write_text('{"secret":"PRIVATE_SENTINEL"}')
            manifest.chmod(0o644)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["--private-root", root, "--manifest", str(manifest)])
            self.assertEqual(code, 2)
            self.assertNotIn("PRIVATE_SENTINEL", out.getvalue() + err.getvalue())

    def test_resume_exports_existing_closed_windows_before_advancing_cursor(self):
        cli = load_cli()
        events = []

        class Boundary:
            def list_windows(self, after_id=0, limit=100):
                return ([{"window_id": 1, "closed": True, "exported": True},
                         {"window_id": 2, "closed": False, "exported": False}]
                        if after_id == 0 else [])

            def export_window(self, ident):
                events.append(ident)
                return {"window_id": ident, "media_sha256": "a" * 64,
                        "receipt_sha256": "b" * 64}

        cursor, results = cli.export_closed(Boundary(), 0)
        self.assertEqual(events, [1])
        self.assertEqual(cursor, 1)
        self.assertEqual(results, [{"status": "CAPTURE_ONLY", "window_id": 1,
                                    "media_sha256": "a" * 64, "receipt_sha256": "b" * 64}])

    def test_failed_export_does_not_skip_window_on_next_attempt(self):
        cli = load_cli()

        class Boundary:
            def list_windows(self, after_id=0, limit=100):
                return [{"window_id": 7, "closed": True, "exported": False}]

            def export_window(self, ident):
                raise ValueError("PRIVATE_SENTINEL")

        with self.assertRaises(ValueError):
            cli.export_closed(Boundary(), 6)

    def test_drain_yields_between_pages_so_collection_can_resume(self):
        cli = load_cli()

        class Boundary:
            def list_windows(self, after_id=0, limit=100):
                return [{"window_id": after_id + 1, "closed": True}] if after_id < 2 else []

            def export_window(self, ident):
                return {"window_id": ident, "media_sha256": "a" * 64,
                        "receipt_sha256": "b" * 64}

        cursor, results = cli.export_closed(Boundary(), 0)
        self.assertEqual(cursor, 1)
        self.assertEqual(len(results), 1)

    def test_shutdown_during_backlog_leaves_unprocessed_windows_for_restart(self):
        cli = load_cli()
        exported = []

        class Boundary:
            def list_windows(self, after_id=0, limit=100):
                return [{"window_id": 1, "closed": True}, {"window_id": 2, "closed": True}]

            def export_window(self, ident):
                exported.append(ident)
                return {"window_id": ident, "media_sha256": "a" * 64,
                        "receipt_sha256": "b" * 64}

        cursor, _ = cli.export_closed(Boundary(), 0, should_stop=lambda: bool(exported))
        self.assertEqual(exported, [1])
        self.assertEqual(cursor, 1)

    def test_explicit_null_template_is_rejected_before_source_collection(self):
        cli = load_cli()
        boundary = types.ModuleType("race_ai.boat_video_capture")
        def forbidden_collector(*args, **kwargs):
            self.fail("explicit null binding reached source collection")
        boundary.Collector = forbidden_collector
        with tempfile.TemporaryDirectory() as root:
            manifest, template = Path(root) / "source.json", Path(root) / "job.json"
            manifest.write_text('{}')
            template.write_text('null')
            manifest.chmod(0o600)
            template.chmod(0o600)
            with patch.dict("sys.modules", {"race_ai.boat_video_capture": boundary}):
                with redirect_stderr(io.StringIO()):
                    code = cli.main(["--private-root", root, "--manifest", str(manifest),
                                     "--job-template", str(template), "--intake-root", root])
            self.assertEqual(code, 2)

    def test_completed_cli_cycle_releases_collector_database(self):
        cli = load_cli()
        events = []
        class Boundary:
            def __init__(self, *args):
                pass
            def tick(self):
                return {"status": "ENDED"}
            def list_windows(self, **kwargs):
                return []
            def close(self):
                events.append("closed")
        boundary = types.ModuleType("race_ai.boat_video_capture")
        boundary.Collector = Boundary
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / "source.json"
            manifest.write_text('{}')
            manifest.chmod(0o600)
            with patch.dict("sys.modules", {"race_ai.boat_video_capture": boundary}):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(["--private-root", root, "--manifest", str(manifest)]), 0)
        self.assertEqual(events, ["closed"])

    def test_analysis_ineligible_archived_window_does_not_block_later_exports(self):
        cli = load_cli()
        exported = []
        class Boundary:
            def list_windows(self, **kwargs):
                return [{"window_id": 1, "closed": True, "analysis_exportable": False,
                         "analysis_hold_reason": "ANALYSIS_CLIP_TOO_LARGE"},
                        {"window_id": 2, "closed": True, "analysis_exportable": True}]
            def export_window(self, ident):
                exported.append(ident)
                return {"window_id": ident, "media_sha256": "a" * 64,
                        "receipt_sha256": "b" * 64}
        cursor, results = cli.export_closed(Boundary(), 0)
        self.assertEqual(exported, [2])
        self.assertEqual(cursor, 2)
        self.assertEqual(results[0]["status"], "ARCHIVED_ANALYSIS_INELIGIBLE")

    def test_export_database_error_is_reported_without_stopping_follow_collection(self):
        cli = load_cli()
        events = []
        class Boundary:
            def __init__(self, *args):
                pass
            def tick(self):
                events.append("tick")
                if events.count("tick") == 2:
                    signal.raise_signal(signal.SIGTERM)
                return {"status": "ACQUIRING", "next_poll_at": "2000-01-01T00:00:00Z"}
            def list_windows(self, **kwargs):
                return [{"window_id": 1, "closed": True}]
            def export_window(self, ident):
                raise sqlite3.OperationalError("PRIVATE_SENTINEL")
            def close(self):
                events.append("closed")
        boundary = types.ModuleType("race_ai.boat_video_capture")
        boundary.Collector = Boundary
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / "source.json"
            manifest.write_text('{}')
            manifest.chmod(0o600)
            with patch.dict("sys.modules", {"race_ai.boat_video_capture": boundary}):
                with redirect_stdout(out), redirect_stderr(err):
                    code = cli.main(["--private-root", root, "--manifest", str(manifest), "--follow"])
        self.assertEqual(code, 0)
        self.assertEqual(events, ["tick", "tick", "closed"])
        self.assertIn("LOCAL_EXPORT_OR_BINDING_REQUIRES_REVIEW", out.getvalue())
        self.assertNotIn("PRIVATE_SENTINEL", out.getvalue() + err.getvalue())

    @unittest.skipUnless(shutil.which("ffmpeg"), "local FFmpeg unavailable")
    def test_follow_process_automatically_exports_real_http_media_and_honors_sigterm(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = root / "fixture.ts"
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                            "testsrc2=size=160x96:rate=6", "-t", "1", "-an", "-c:v",
                            "mpeg2video", "-threads", "1", "-f", "mpegts", str(fixture)],
                           check=True, capture_output=True)
            media = fixture.read_bytes()
            requests = []
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    requests.append(self.path)
                    body = (b"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nclip.ts\n#EXT-X-ENDLIST\n"
                            if self.path == "/source.m3u8" else media)
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                def log_message(self, *args):
                    pass
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = "http://127.0.0.1:" + str(server.server_port)
            manifest = root / "source.json"
            manifest.write_text(json.dumps({
                "schema": "RACE_AI_AUTHORIZED_HLS_SOURCE_V1", "source_id": "fictional-cli",
                "playlist_url": origin + "/source.m3u8", "allowed_origins": [origin],
                "source_role": "SYNTHETIC_TEST", "source_evidence_sha256": "a" * 64}, indent=2))
            manifest.chmod(0o600)
            capture_root = root / "capture"
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--private-root", str(capture_root),
                                        "--manifest", str(manifest), "--follow"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 20
                while not (capture_root / "exports" / "1.json").exists():
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail("follow exited before export: " + str(process.returncode) + " " + stderr.decode())
                    if time.monotonic() >= deadline:
                        process.kill()
                        stdout, stderr = process.communicate()
                        self.fail("follow did not export: " + stdout.decode() + stderr.decode())
                    time.sleep(.05)
                process.terminate()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr.decode())
                self.assertEqual(requests, ["/source.m3u8", "/clip.ts"])
                self.assertIn(b"CAPTURE_ONLY", stdout)
                self.assertTrue((capture_root / "exports" / "1.mp4").is_file())
                self.assertFalse((capture_root / "video-intake").exists())
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()
                server.shutdown()
                server.server_close()
                thread.join()
