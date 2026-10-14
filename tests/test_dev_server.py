"""Real loopback HTTP checks, never a third-party feed or publication proof."""
import importlib
import json
import threading
import unittest
from urllib.request import urlopen
from urllib.error import HTTPError


class DevServerTests(unittest.TestCase):
    def setUp(self):
        try:
            module = importlib.import_module('race_ai.dev_server')
        except ModuleNotFoundError:
            module = None
        self.assertIsNotNone(module, 'same-origin application server must exist')
        self.server = module.create_server(port=0, feed_reader=lambda: (503, {'error': 'FEED_NOT_APPROVED'}))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        if hasattr(self, 'server'):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(2)

    def response(self, path):
        try:
            return urlopen(self.base + path, timeout=3)
        except HTTPError as error:
            return error

    def test_serves_actual_application(self):
        with self.response('/') as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'RACE AI', response.read())
            self.assertIn('text/html', response.headers['Content-Type'])

    def test_same_origin_today_preserves_unapproved_state(self):
        with self.response('/api/today') as response:
            self.assertEqual(response.status, 503)
            self.assertEqual(json.load(response), {'error': 'FEED_NOT_APPROVED'})

    def test_readiness_reports_degraded_without_secrets(self):
        with self.response('/api/health') as response:
            self.assertEqual(response.status, 503)
            data = json.load(response)
            self.assertEqual(data['status'], 'degraded')
            self.assertEqual(data['feed']['status'], 'unavailable')
            self.assertEqual(data['feed']['reason'], 'FEED_NOT_APPROVED')
            self.assertNotIn('environment', data)

    def test_paths_never_expose_sources_or_project_files(self):
        for path in ['/api/today.py', '/../README.md', '/%2e%2e/README.md', '/api/', '/.env', '/data/today.json', '/style.css/../api/today.py']:
            with self.subTest(path=path), self.response(path) as response:
                self.assertEqual(response.status, 404)

    def test_security_headers_and_known_assets(self):
        with self.response('/style.css') as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])

    def test_health_rejects_reader_exception_without_leaking_message(self):
        def fail():
            raise RuntimeError('PRIVATE_TOKEN_SHOULD_NOT_LEAK')
        self.server.feed_reader = fail
        with self.response('/api/health') as response:
            body = response.read()
            self.assertEqual(response.status, 503)
            self.assertNotIn(b'PRIVATE_TOKEN', body)


if __name__ == '__main__':
    unittest.main()
