"""Read-only Vercel API for independently approved daily feed in private Blob.

Requires a connected private Vercel Blob store and a verified publisher.
Never fetches official websites, publishes raw videos or writes to Blob.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.request import Request,urlopen
from urllib.parse import quote,urlsplit
import json
import os

MAX_BYTES=6_000_000

def current_day():
    return datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()

def load_feed():
    if os.environ.get("RACE_AI_FEED_APPROVED")!="1":
        return 503,{"error":"FEED_NOT_APPROVED"}
    token=os.environ.get("VERCEL_OIDC_TOKEN") or os.environ.get("BLOB_READ_WRITE_TOKEN")
    base=os.environ.get("RACE_AI_BLOB_BASE_URL","").rstrip("/")
    host=urlsplit(base)
    if (not token or host.scheme!="https" or not host.hostname or
        not host.hostname.endswith(".private.blob.vercel-storage.com") or
        host.path or host.query or host.fragment or host.username or host.password):
        return 503,{"error":"FEED_STORE_NOT_CONFIGURED"}
    # Exact day-specific key prevents yesterday's snapshot being used today.
    url=base+"/race-ai/day/"+quote(current_day())+".json"
    request=Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
    try:
        with urlopen(request,timeout=8) as response:
            if response.status!=200:
                return 503,{"error":"FEED_STORE_UNAVAILABLE"}
            raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            return 503,{"error":"FEED_TOO_LARGE"}
        data=json.loads(raw)
        if (data.get("date_jst")!=current_day() or
            data.get("redistribution_authorized") is not True or
            not isinstance(data.get("source_url"),str) or
            not isinstance(data.get("first_observed_at"),str)):
            return 503,{"error":"FEED_STALE_OR_UNAPPROVED"}
        return 200,data
    except (OSError,ValueError,TypeError,AttributeError):
        return 503,{"error":"FEED_STORE_UNAVAILABLE"}

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status,payload=load_feed()
        body=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
