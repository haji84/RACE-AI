"""GitHub Actions-only private Blob probe caller.

Short-lived OIDC tokens are supplied by GitHub Actions, never arguments, logs,
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
        raise RuntimeError("PROBE_CONFIG_INVALID: missing Preview URL or GitHub OIDC runtime variables")
    separator="&" if "?" in oidc_url else "?"
    token_request=urllib.request.Request(oidc_url+separator+"audience=race-ai-preview-blob-probe",
        headers={"Authorization":"Bearer "+oidc_auth})
    try:
        with urllib.request.urlopen(token_request,timeout=15) as oidc_response:
            oidc=json.loads(oidc_response.read(16384))["value"]
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OIDC_ISSUE_FAILED: HTTP {exc.code}") from None
    except (urllib.error.URLError, KeyError, ValueError):
        raise RuntimeError("OIDC_ISSUE_FAILED: transport or token response") from None
    print("OIDC_TOKEN_ISSUED")
    req=urllib.request.Request(url,data=b"",method="POST",
        headers={"Authorization":"Bearer "+oidc,"Content-Type":"application/octet-stream"})
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            body=response.read(8193)
            status=response.status
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"PREVIEW_PROBE_REJECTED: HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("PREVIEW_PROBE_TRANSPORT_FAILED") from None
    if len(body)>8192 or status!=200:
        raise RuntimeError("PREVIEW_PROBE_RESPONSE_INVALID")
    result=json.loads(body)
    if result.get("status")!="verified" or not result.get("pathname","").startswith("race-ai/probe/"):
        raise RuntimeError("PREVIEW_PROBE_RESULT_INVALID")
    print(json.dumps({"result":"BLOB_PROBE_VERIFIED","bytes":result.get("bytes")},sort_keys=True))


if __name__=="__main__":
    run()
