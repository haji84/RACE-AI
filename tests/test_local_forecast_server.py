"""Loopback forecast HTTP boundary; no provider calls or real race fixtures."""
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from race_ai.local_forecast_server import make_server


class RecordingService:
    def __init__(self):
        self.calls = []
        self.failure = None

    def status(self):
        return {"ready": True, "sports": {"boat": {"stages": ["P0", "P1"]}}}

    def generate(self, sport, stage):
        self.calls.append((sport, stage))
        if self.failure:
            raise self.failure
        return {"view": {"schema": "RACE_AI_PRIVATE_CYCLE_VIEW_V1", "records": []},
                "summary": {"generated": 0, "reused": 0, "missing": 16}}


@contextmanager
def serving(service=None, web_root=None):
    service = service or RecordingService()
    server = make_server(service, port=0, web_root=web_root)
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
                               "/api/forecast/status?file=private.sqlite", "/app.js", "/.git/config"):
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
