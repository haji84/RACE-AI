"""Vercel Python function: approved same-day feed only, fail closed.

A trusted publisher must place data/today.json in this deployment and set
RACE_AI_FEED_APPROVED=1. This endpoint does not scrape official sites.
"""
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status=503
        payload={"error":"FEED_UNAVAILABLE"}
        if os.environ.get("RACE_AI_FEED_APPROVED")=="1":
            try:
                path=Path(__file__).resolve().parents[1]/"data"/"today.json"
                data=json.loads(path.read_text(encoding="utf-8"))
                today=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
                if (data.get("date_jst")==today and
                    data.get("redistribution_authorized") is True and
                    isinstance(data.get("source_url"),str) and
                    isinstance(data.get("first_observed_at"),str)):
                    status=200
                    payload=data
                else:
                    payload={"error":"FEED_STALE_OR_UNAPPROVED"}
            except (OSError,ValueError,TypeError,AttributeError):
                pass
        body=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
