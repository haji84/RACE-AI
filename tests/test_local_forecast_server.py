"""Loopback forecast HTTP boundary; no provider calls or real race fixtures."""
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from race_ai.local_forecast_server import make_server


class RecordingService:
    def __init__(self):
        self.calls = []
        self.latest_calls = []
        self.failure = None

    def status(self):
        return {"ready": True, "sports": {"boat": {"stages": ["P0", "P1"]}}}

    def generate(self, sport, stage):
        self.calls.append((sport, stage))
        if self.failure:
            raise self.failure
        return {"view": {"schema": "RACE_AI_PRIVATE_CYCLE_VIEW_V1", "records": []},
                "summary": {"generated": 0, "reused": 0, "missing": 16}}

    def latest(self, sport, stage):
        self.latest_calls.append((sport, stage))
        return {"available": True, "revision": "saved-revision", "day_jst": "2030-01-01",
                "view": {"schema": "RACE_AI_PRIVATE_CYCLE_VIEW_V1", "records": []},
                "summary": {"generated": 0, "reused": 1, "missing": 15}}


class RecordingAutomation:
    def __init__(self):
        self.starts = 0
        self.stops = 0
        self.started = threading.Event()
        self.state = "WAITING"

    def start(self):
        self.starts += 1
        self.started.set()

    def stop(self):
        self.stops += 1

    def status(self):
        return {"enabled": True, "state": "STOPPED" if self.stops else self.state,
                "interval_seconds": 180, "round_no": 1}


@contextmanager
def serving(service=None, web_root=None, automatic=None):
    service = service or RecordingService()
    server = make_server(service, port=0, web_root=web_root, automatic=automatic)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, service
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(server, method, target, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request(method, target, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def admitted_headers(server, nonce):
    return {"Content-Type": "application/json", "Origin": server.origin,
            "X-Race-AI-Nonce": nonce}


class LocalForecastServerTests(unittest.TestCase):
    def test_latest_is_a_read_only_cached_display_endpoint(self):
        with serving() as (server, service):
            status, headers, body = request(server, "GET", "/api/forecast/latest?sport=boat&stage=P0")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["revision"], "saved-revision")
            self.assertEqual(service.latest_calls, [("boat", "P0")])
            self.assertEqual(service.calls, [])
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_latest_rejects_extra_duplicate_missing_or_forged_display_query(self):
        with serving() as (server, service):
            for query in ("sport=boat", "sport=boat&stage=P0&at=old", "sport=boat&sport=horse",
                          "sport=boat&stage=P0&stage=P1", "sport=boat&stage=old", "sport=unknown&stage=P0",
                          "sport=boat&stage=", "file=private.sqlite&stage=P0", "sport=boat&stage=P0#fragment"):
                status, _, body = request(server, "GET", "/api/forecast/latest?" + query)
                self.assertEqual(status, 400, query)
                self.assertNotIn(b"private.sqlite", body)
            self.assertEqual(request(server, "GET", "/api/forecast/latest?sport=boat&stage=P0",
                headers={"Host": "attacker.invalid"})[0], 403)
            self.assertEqual(service.latest_calls, [])
            self.assertEqual(service.calls, [])

    def test_automatic_lifecycle_starts_only_when_serving_and_blocks_manual_bypass(self):
        automation = RecordingAutomation()
        service = RecordingService()
        server = make_server(service, port=0, automatic=automation)
        self.assertIs(service.automation, automation)
        self.assertEqual(automation.starts, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertTrue(automation.started.wait(5))
            status = json.loads(request(server, "GET", "/api/forecast/status")[2])
            self.assertTrue(status["auto"]["enabled"])
            self.assertEqual(status["auto"]["state"], "WAITING")
            headers = admitted_headers(server, status["nonce"])
            code, _, body = request(server, "POST", "/api/forecast/generate",
                '{"sport":"boat","stage":"P0"}', headers)
            self.assertEqual(code, 409)
            self.assertEqual(json.loads(body)["error"]["code"], "AUTOMATIC_MANAGED")
            self.assertEqual(service.calls, [])
            self.assertEqual(request(server, "GET", "/api/forecast/latest?sport=boat&stage=P0")[0], 200)
            self.assertEqual(automation.starts, 1)
            # A stopped automatic session cannot be bypassed by manual POST.
            automation.state = "STOPPED"
            self.assertEqual(request(server, "POST", "/api/forecast/generate",
                '{"sport":"boat","stage":"P0"}', headers)[0], 409)
        finally:
            server.shutdown(); server.server_close(); server.server_close()
            thread.join(5)
        self.assertEqual(automation.starts, 1)
        self.assertEqual(automation.stops, 1)

    def test_close_during_controller_start_cannot_leave_a_live_worker(self):
        entered = threading.Event(); release = threading.Event(); stopped = threading.Event()
        class StartingAutomation(RecordingAutomation):
            active = False
            def start(self):
                entered.set()
                release.wait(5)
                self.active = True
            def stop(self):
                self.active = False
                stopped.set()
        automation = StartingAutomation()
        server = make_server(RecordingService(), port=0, automatic=automation)
        with patch("http.server.ThreadingHTTPServer.serve_forever", return_value=None):
            serving_thread = threading.Thread(target=server.serve_forever)
            serving_thread.start()
            self.assertTrue(entered.wait(5))
            closing_thread = threading.Thread(target=server.server_close)
            closing_thread.start()
            # Closing must serialize against a not-yet-completed start. On
            # the old path stop ran first and start subsequently leaked work.
            stopped.wait(0.2)
            release.set()
            serving_thread.join(5); closing_thread.join(5)
        self.assertFalse(serving_thread.is_alive())
        self.assertFalse(closing_thread.is_alive())
        self.assertFalse(automation.active)

    def test_default_controller_constructs_after_binding_and_never_starts_on_close(self):
        service = RecordingService(); service.automatic_supported = True
        automation = RecordingAutomation()
        module = types.ModuleType("race_ai.local_forecast_automation")
        module.ForecastAutomation = lambda actual: automation
        with patch.dict("sys.modules", {"race_ai.local_forecast_automation": module}):
            server = make_server(service, port=0)
            self.assertIs(service.automation, automation)
            self.assertEqual(automation.starts, 0)
            server.server_close(); server.server_close()
        self.assertEqual(automation.starts, 0)
        self.assertEqual(automation.stops, 1)
        # An occupied socket must fail before constructing a controller.
        with serving() as (occupied, _):
            with patch.dict("sys.modules", {"race_ai.local_forecast_automation": module}), \
                    patch.object(module, "ForecastAutomation") as factory:
                with self.assertRaises(OSError):
                    make_server(service, port=occupied.server_port)
                factory.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "No-follow static file serving requires POSIX")
    def test_explicit_post_calls_service_and_served_index_advertises_capability(self):
        original = Path("web/index.html").read_bytes()
        with serving() as (server, service):
            self.assertEqual(server.server_address[0], "127.0.0.1")
            status, headers, body = request(server, "GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(b'<meta name="race-ai-generation-api" content="/api/forecast">', body)
            self.assertEqual(headers["Cache-Control"], "no-store")
            status, headers, body = request(server, "GET", "/api/forecast/status")
            self.assertEqual(status, 200)
            capability = json.loads(body)
            self.assertTrue(capability["ready"])
            nonce = capability["nonce"]
            self.assertGreaterEqual(len(nonce), 32)
            self.assertEqual(service.calls, [])
            status, headers, body = request(server, "POST", "/api/forecast/generate",
                json.dumps({"sport": "boat", "stage": "P0"}), admitted_headers(server, nonce))
            self.assertEqual(status, 200)
            self.assertEqual(service.calls, [("boat", "P0")])
            self.assertEqual(json.loads(body)["summary"]["missing"], 16)
            self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(Path("web/index.html").read_bytes(), original)
        self.assertNotIn(b'name="race-ai-generation-api"', original)

    def test_cross_origin_forged_host_and_missing_nonce_do_not_generate(self):
        with serving() as (server, service):
            nonce = json.loads(request(server, "GET", "/api/forecast/status")[2])["nonce"]
            valid = admitted_headers(server, nonce)
            cases = [dict(valid, Origin="https://example.invalid"),
                     dict(valid, Origin="null"),
                     {k:v for k,v in valid.items() if k != "Origin"},
                     {k:v for k,v in valid.items() if k != "X-Race-AI-Nonce"},
                     dict(valid, **{"X-Race-AI-Nonce": "wrong"}),
                     dict(valid, Host="attacker.invalid:" + str(server.server_port))]
            for headers in cases:
                with self.subTest(headers=list(headers)):
                    status, _, body = request(server, "POST", "/api/forecast/generate",
                        '{"sport":"boat","stage":"P0"}', headers)
                    self.assertEqual(status, 403)
                    self.assertNotIn(b"Traceback", body)
            self.assertEqual(service.calls, [])
            self.assertEqual(request(server, "GET", "/api/forecast/status",
                headers={"Host":"attacker.invalid"})[0], 403)

    def test_browser_cannot_supply_clock_model_scope_grants_or_paths(self):
        with serving() as (server, service):
            nonce = json.loads(request(server, "GET", "/api/forecast/status")[2])["nonce"]
            for key in ("at", "now", "model_ids", "scope", "allow_source", "private_dir", "input_url"):
                body = {"sport":"boat", "stage":"P0", key:"forged"}
                self.assertEqual(request(server, "POST", "/api/forecast/generate",
                    json.dumps(body), admitted_headers(server, nonce))[0], 400)
            for body in ('{"sport":"boat","sport":"horse","stage":"P0"}',
                         '{"sport":"boat","stage":"P0","value":NaN}',
                         '[]', '{}', '{bad', '{"sport":"unknown","stage":"P0"}'):
                self.assertEqual(request(server, "POST", "/api/forecast/generate",
                    body, admitted_headers(server, nonce))[0], 400)
            self.assertEqual(service.calls, [])

    def test_size_content_type_and_method_guards_have_no_generation_side_effect(self):
        with serving() as (server, service):
            nonce = json.loads(request(server, "GET", "/api/forecast/status")[2])["nonce"]
            headers = admitted_headers(server, nonce)
            self.assertEqual(request(server,"POST","/api/forecast/generate","x"*1025,headers)[0],413)
            self.assertEqual(request(server,"POST","/api/forecast/generate",'{}',dict(headers,**{"Content-Type":"text/plain"}))[0],415)
            self.assertEqual(request(server,"GET","/api/forecast/generate")[0],405)
            for method in ("OPTIONS", "PUT", "DELETE", "PATCH", "HEAD"):
                self.assertEqual(request(server,method,"/api/forecast/generate")[0],405)
            self.assertEqual(service.calls, [])

    def test_extreme_content_length_is_rejected_before_body_read(self):
        with serving() as (server, service):
            nonce = json.loads(request(server,"GET","/api/forecast/status")[2])["nonce"]
            headers = admitted_headers(server,nonce)
            headers["Content-Length"] = "9" * 5000
            status, _, body = request(server,"POST","/api/forecast/generate",b"",headers)
            self.assertEqual(status,413)
            self.assertEqual(service.calls,[])
            self.assertNotIn(b"Traceback",body)

    @unittest.skipUnless(os.name == "posix", "No-follow static file serving requires POSIX")
    def test_private_files_path_traversal_and_symlink_assets_are_not_served(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); web = root/"web";web.mkdir()
            secret = root/"private.sqlite";secret.write_text("PRIVATE_TEST_VALUE")
            (web/"index.html").write_text("<!doctype html><head></head><body>fixture</body>")
            (web/"app.js").symlink_to(secret)
            with serving(web_root=web) as (server, _):
                for target in ("/../private.sqlite", "/%2e%2e/private.sqlite", "/private.sqlite",
                               "/api/forecast/status?file=private.sqlite", "/app.js", "/.git/config", "//[", "invalid://["):
                    status, _, body = request(server,"GET",target)
                    self.assertEqual(status,404,target)
                    self.assertNotIn(b"PRIVATE_TEST_VALUE",body)
                    self.assertNotIn(str(root).encode(),body)

    def test_internal_source_and_storage_failures_return_fixed_actionable_errors(self):
        with serving() as (server, service):
            nonce = json.loads(request(server,"GET","/api/forecast/status")[2])["nonce"]
            for error, expected in ((PermissionError("secret-key /private/path"),403),
                                    (TimeoutError("secret-key /private/path"),504),
                                    (ValueError("secret-key /private/path"),422),
                                    (OSError("secret-key /private/path"),503),
                                    (RuntimeError("secret-key /private/path"),503)):
                service.failure=error
                status, headers, body=request(server,"POST","/api/forecast/generate",
                    '{"sport":"boat","stage":"P1"}',admitted_headers(server,nonce))
                self.assertEqual(status,expected)
                parsed=json.loads(body)
                self.assertTrue(parsed["error"]["code"])
                self.assertTrue(parsed["error"]["message"])
                self.assertNotIn(b"secret-key",body)
                self.assertNotIn(b"/private/path",body)
                self.assertEqual(headers["Cache-Control"],"no-store")

    def test_public_binding_is_not_an_argument(self):
        with self.assertRaises(TypeError):
            make_server(RecordingService(),host="0.0.0.0")
        for invalid in (True,-1,65536,"8765"):
            with self.assertRaises(ValueError):make_server(RecordingService(),port=invalid)
