"""A pinned historical report is read-only and independent of the live feed."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import hashlib
import importlib.util
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
import archived_cohort_contract as contract


class ArchivedCohortTests(unittest.TestCase):
    def test_exact_audited_bytes_and_original_clock_survive_later_days(self):
        raw = contract.load_snapshot(now=datetime(2026, 11, 1, tzinfo=timezone.utc))
        original = (ROOT / 'docs/evidence/2026-10-16/result-v2-publication-live.json').read_text(encoding='utf-8')
        import json
        self.assertEqual(json.loads(raw), json.loads(original)['aggregate']['report'])
        self.assertEqual(len(raw), 7173)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), contract.REPORT_SHA256)
        self.assertEqual(json.loads(raw)['as_of'], '2026-10-16T02:10:43.089393+00:00')

    def test_corruption_or_unavailable_snapshot_never_produces_rows(self):
        for raw in (b'{}', b'NaN', b'', b'x' * 256001):
            with self.subTest(raw=raw[:10]), patch.object(Path, 'read_bytes', return_value=raw):
                with self.assertRaises(contract.SnapshotUnavailable):
                    contract.load_snapshot(now=datetime(2026, 11, 1, tzinfo=timezone.utc))
        with patch.object(Path, 'read_bytes', side_effect=OSError('missing')):
            with self.assertRaises(contract.SnapshotUnavailable):
                contract.load_snapshot()

    def test_future_audit_and_naive_clock_are_rejected(self):
        for now in (datetime(2026, 10, 16, 2, 15, tzinfo=timezone.utc), datetime(2026, 11, 1)):
            with self.subTest(now=now), self.assertRaises(contract.SnapshotUnavailable):
                contract.load_snapshot(now=now)

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('archived_cohort_api', ROOT / 'web/api/archived-cohort.py')
        cls.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.api)

    def request(self, method, path):
        class Request:
            wfile = BytesIO()
            headers_sent = {}
            def send_response(self, status): self.status = status
            def send_header(self, key, value): self.headers_sent[key] = value
            def end_headers(self): pass
        request = Request()
        request.path = path
        request._reply = self.api.handler._reply.__get__(request)
        getattr(self.api.handler, 'do_' + method)(request)
        return request

    def test_get_is_exact_pinned_body_without_live_feed_or_network(self):
        import socket
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')):
            request = self.request('GET', '/api/archived-cohort')
        self.assertEqual(request.status, 200)
        self.assertEqual(hashlib.sha256(request.wfile.getvalue()).hexdigest(), contract.REPORT_SHA256)
        self.assertEqual(request.headers_sent['Cache-Control'], 'no-store')

    def test_query_and_post_rejected_without_reading_any_snapshot(self):
        with patch.object(self.api, 'load_snapshot', side_effect=AssertionError('must not read')):
            for path in ('/api/archived-cohort?date=2026-10-15', '/api/archived-cohort?'):
                self.assertEqual(self.request('GET', path).status, 400)
            request = self.request('POST', '/api/archived-cohort')
            self.assertEqual(request.status, 405)
            self.assertEqual(request.headers_sent['Allow'], 'GET')

    def test_missing_or_corrupt_bundle_returns_unavailable_only(self):
        with patch.object(self.api, 'load_snapshot', side_effect=contract.SnapshotUnavailable()):
            request = self.request('GET', '/api/archived-cohort')
        self.assertEqual(request.status, 503)
        self.assertNotIn(b'"models"', request.wfile.getvalue())
