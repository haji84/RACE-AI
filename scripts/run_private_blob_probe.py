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
    oidc_url=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL","")
    oidc_auth=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN","")
    parts=urlsplit(url)
    if (parts.scheme!="https" or not parts.hostname or
        not parts.hostname.endswith(".vercel.app") or
        parts.path!="/api/blob-probe" or parts.query or parts.fragment or
        not oidc_url.startswith("https://") or not oidc_auth):
        raise RuntimeError("missing or invalid Preview URL/secret")
    separator="&" if "?" in oidc_url else "?"
    token_request=urllib.request.Request(oidc_url+separator+"audience=race-ai-preview-blob-probe",
        headers={"Authorization":"Bearer "+oidc_auth})
    with urllib.request.urlopen(token_request,timeout=15) as oidc_response:
        oidc=json.loads(oidc_response.read(16384))["value"]
    req=urllib.request.Request(url,data=b"",method="POST",
        headers={"Authorization":"Bearer "+oidc,"Content-Type":"application/octet-stream"})
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
