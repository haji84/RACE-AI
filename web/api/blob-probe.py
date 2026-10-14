"""Preview-only private Blob roundtrip endpoint.

Requires Vercel Preview environment and a signed, scoped GitHub OIDC token.
Uses an isolated probe/ key; never touches race-ai/day/ live feeds.
No user-supplied path or data is accepted.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime,timezone
import hashlib
import json
import os
import secrets

def verify_github_oidc(token):
    # Vercel adds the project root, not api/, to sys.path.
    from api.github_oidc import verify_github_oidc as verify
    return verify(token)


def authorized(headers):
    if os.environ.get("VERCEL_ENV")!="preview":
        print('PROBE_AUTH_REJECTED environment', flush=True)
        return False
    header=headers.get("Authorization","")
    if not header.startswith("Bearer "):
        print('PROBE_AUTH_REJECTED bearer_missing', flush=True)
        return False
    try:
        verify_github_oidc(header[7:])
        return True
    except Exception as error:
        print('PROBE_AUTH_REJECTED ' + type(error).__name__, flush=True)
        return False


async def roundtrip():
    from vercel.blob import AsyncBlobClient
    key="race-ai/probe/"+secrets.token_hex(16)+".json"
    payload=json.dumps({"probe":True,"timestamp":datetime.now(timezone.utc).isoformat()},
                       separators=(",",":")).encode("utf-8")
    async with AsyncBlobClient() as client:
        try:
            created=await client.put(key,payload,access="private",content_type="application/json",
                                     add_random_suffix=False,overwrite=False)
            if getattr(created,"pathname",None)!=key:
                raise ValueError("Blob key mismatch")
            readback=await client.get(key,access="private",use_cache=False,timeout=10)
            if readback is None or getattr(readback,"status_code",None)!=200:
                raise ValueError("Blob readback failed")
            digest=hashlib.sha256()
            total=0
            content=getattr(readback,"content",None)
            if isinstance(content,bytes):
                total=len(content)
                if total>8192:raise ValueError("probe too large")
                digest.update(content)
            else:
                async for chunk in readback.stream:
                    if not isinstance(chunk,bytes):raise ValueError("invalid chunk")
                    total+=len(chunk)
                    if total>8192:raise ValueError("probe too large")
                    digest.update(chunk)
            expected=hashlib.sha256(payload).hexdigest()
            if digest.hexdigest()!=expected:
                raise ValueError("readback mismatch")
        finally:
            # Only this owned random key; cleanup errors must fail the probe.
            await client.delete(key)
    return {"status":"verified","pathname":key,"bytes":total,"sha256":expected,
            "cleanup":"deleted","commit_sha":os.environ.get("VERCEL_GIT_COMMIT_SHA","")}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not authorized(self.headers):
            self.send_response(404)
            self.send_header("Content-Length","0")
            self.end_headers()
            return
        import asyncio
        try:
            expected_commit=self.headers.get("X-Race-AI-Commit","")
            if expected_commit!=os.environ.get("VERCEL_GIT_COMMIT_SHA") or len(expected_commit)!=40:
                self.send_response(409)
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            result=asyncio.run(roundtrip())
            status=200
        except Exception as error:
            print('PROBE_STORAGE_REJECTED ' + type(error).__name__, flush=True)
            result={"status":"probe_failed"}
            status=503
        body=json.dumps(result).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_response(405)
        self.send_header("Allow","POST")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length","0")
        self.end_headers()

