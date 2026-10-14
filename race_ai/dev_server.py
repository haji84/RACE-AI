"""Loopback app server with same-origin feed and no file-upload requirement.

Never serves repository sources, credentials, directory listings or local raw data.
Cloud deployment remains Vercel's responsibility. Local API approval is enforced
by the existing feed reader; an empty development install is honestly degraded.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from race_ai.today_feed_server import read_feed

WEB = Path(__file__).resolve().parents[1] / 'web'
ASSETS = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/ui-core.js': ('ui-core.js', 'text/javascript; charset=utf-8'),
    '/money.js': ('money.js', 'text/javascript; charset=utf-8'),
}
CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"


def health(feed_status: int, payload: dict) -> tuple[int, dict]:
    ready = feed_status == 200
    feed = {'status': 'available' if ready else 'unavailable'}
    if ready:
        feed.update(date_jst=payload.get('date_jst'), updated_at=payload.get('first_observed_at'))
    else:
        reason = payload.get('error', 'FEED_UNAVAILABLE')
        feed['reason'] = reason if isinstance(reason, str) and reason.replace('_', '').isalnum() and reason.isupper() else 'FEED_UNAVAILABLE'
    return (200 if ready else 503), {
        'status': 'ready' if ready else 'degraded',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'feed': feed,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        # URL query strings and user-entered values must not become local logs.
        pass

    def _send(self, status, body, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', CSP)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/api/today', '/api/health'):
            try:
                status, payload = self.server.feed_reader()
            except Exception:
                status, payload = 503, {'error': 'FEED_UNAVAILABLE'}
            if path == '/api/health':
                status, payload = health(status, payload)
            self._send(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'))
            return
        asset = ASSETS.get(path)
        if asset:
            try:
                body = (WEB / asset[0]).read_bytes()
            except OSError:
                self._send(404, b'{"error":"NOT_FOUND"}')
                return
            self._send(200, body, asset[1])
            return
        self._send(404, b'{"error":"NOT_FOUND"}')


def create_server(*, port: int = 8080, feed_reader=read_feed):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.feed_reader = feed_reader
    return server


def main():
    parser = argparse.ArgumentParser(description='Run RACE AI on this computer')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    server = create_server(port=args.port)
    print(f'RACE AI: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
