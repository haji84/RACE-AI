"""Explicit historical snapshot endpoint, independent of current-day APIs."""
from http.server import BaseHTTPRequestHandler

from archived_cohort_contract import SnapshotUnavailable, load_snapshot


class handler(BaseHTTPRequestHandler):
    def _reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Robots-Tag', 'noindex')
        self.send_header('Content-Length', str(len(body)))
        if status == 405:
            self.send_header('Allow', 'GET')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if '?' in self.path:
            self._reply(400, b'{"error":"HISTORICAL_SNAPSHOT_QUERY_NOT_ALLOWED"}')
            return
        try:
            self._reply(200, load_snapshot())
        except SnapshotUnavailable:
            self._reply(503, b'{"error":"AUDITED_SNAPSHOT_UNAVAILABLE"}')

    def do_POST(self):
        self._reply(405, b'{"error":"READ_ONLY_HISTORICAL_SNAPSHOT"}')
