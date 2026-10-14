"""GitHub Actions-only private Blob probe caller.

Secret is supplied through environment variables, never arguments, logs,
query strings, or the repository. Uses POST with a fixed Preview URL.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def run():
    url=os.environ.get("RACE_AI_PROBE_URL","")
    secret=os.environ.get("RACE_AI_PROBE_SECRET","")
    parts=urlsplit(url)
    if (parts.scheme!="https" or not parts.hostname or
        not parts.hostname.endswith(".vercel.app") or
        parts.path!="/api/blob-probe" or parts.query or parts.fragment or
        len(secret)<32):
        raise RuntimeError("missing or invalid Preview URL/secret")
    req=urllib.request.Request(url,data=b"",method="POST",
        headers={"X-Race-AI-Probe-Secret":secret,"Content-Type":"application/octet-stream"})
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            body=response.read(8193)
            status=response.status
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"probe rejected: HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("probe transport failed") from None
    if len(body)>8192 or status!=200:
        raise RuntimeError("probe did not return success")
    result=json.loads(body)
    if result.get("status")!="verified" or not result.get("pathname","").startswith("race-ai/probe/"):
        raise RuntimeError("unexpected probe result")
    print(json.dumps({"result":"BLOB_PROBE_VERIFIED","bytes":result.get("bytes")},sort_keys=True))


if __name__=="__main__":
    run()
