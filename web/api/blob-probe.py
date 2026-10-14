"""Preview-only private Blob roundtrip endpoint.

Requires both Vercel Preview environment and a separate random probe secret.
Uses an isolated probe/ key; never touches race-ai/day/ live feeds.
No user-supplied path or data is accepted.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime,timezone
from github_oidc import verify_github_oidc
import hashlib
import json
import os
import secrets


def authorized(headers):
    if os.environ.get("VERCEL_ENV")!="preview":
        return False
    header=headers.get("Authorization","")
    if not header.startswith("Bearer "):
        return False
    try:
        verify_github_oidc(header[7:])
        return True
    except Exception:
        return False


async def roundtrip():
    from vercel.blob import AsyncBlobClient
    client=AsyncBlobClient()
    key="race-ai/probe/"+secrets.token_hex(16)+".json"
    payload=json.dumps({"probe":True,"timestamp":datetime.now(timezone.utc).isoformat()},
                       separators=(",",":")).encode("utf-8")
    created=await client.put(key,payload,access="private",content_type="application/json",
                             add_random_suffix=False,overwrite=False)
    actual_key=getattr(created,"pathname",None)
    if actual_key!=key:
        raise ValueError("Blob key mismatch")
    readback=await client.get(key,access="private")
    if readback is None or getattr(readback,"status_code",200)!=200:
        raise ValueError("Blob readback failed")
    digest=hashlib.sha256()
    total=0
    async for chunk in readback.stream:
        total+=len(chunk)
        if total>8192:raise ValueError("probe too large")
        digest.update(chunk)
    if digest.hexdigest()!=hashlib.sha256(payload).hexdigest():
        raise ValueError("readback mismatch")
    return {"status":"verified","pathname":key,"bytes":total}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not authorized(self.headers):
            self.send_response(404)
            self.send_header("Content-Length","0")
            self.end_headers()
            return
        import asyncio
        try:
            result=asyncio.run(roundtrip())
            status=200
        except Exception:
            result={"status":"probe_failed"}
            status=503
        body=json.dumps(result).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
