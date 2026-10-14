"""Read-only same-origin feed API.

Serves only an independently approved current-day JSON snapshot.
No network scraping or invented races. Requires RACE_AI_FEED_PATH and
RACE_AI_FEED_APPROVED=1 configured by an authorized operator.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os


def read_feed():
    if os.environ.get("RACE_AI_FEED_APPROVED")!="1":
        return 503, {"error":"FEED_NOT_APPROVED"}
    path=os.environ.get("RACE_AI_FEED_PATH")
    if not path:
        return 503, {"error":"FEED_NOT_CONFIGURED"}
    try:
        raw=Path(path).read_bytes()
        if len(raw)>6_000_000:
            raise ValueError("feed too large")
        data=json.loads(raw)
        today=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
        if data.get("date_jst")!=today:
            return 503, {"error":"FEED_NOT_CURRENT"}
        if data.get("redistribution_authorized") is not True:
            return 503, {"error":"REDISTRIBUTION_NOT_AUTHORIZED"}
        if not data.get("source_url") or not data.get("first_observed_at"):
            return 503, {"error":"FEED_EVIDENCE_MISSING"}
        return 200,data
    except (OSError,ValueError,TypeError,AttributeError):
        return 503, {"error":"FEED_UNAVAILABLE"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path!="/api/today":
            self.send_error(404);return
        status,payload=read_feed()
        body=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__=="__main__":
    HTTPServer(("127.0.0.1",int(os.environ.get("PORT","8080"))),Handler).serve_forever()
