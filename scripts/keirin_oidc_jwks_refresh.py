"""Refresh GitHub's public OIDC verification keys through a signed main workflow.

GitHub Actions can reach the official public GitHub JWKS endpoint while the
Cloudflare Worker cannot. The main-branch Actions OIDC JWT authenticates the
submission, and the Worker enforces signer-key continuity before updating D1.
No private JWKs exist, no token/JWK printed and no forecast data transmitted.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import re
import sys

from scripts.keirin_d1_bridge_once import get_github_oidc_token, WORKER

JWKS="https://token.actions.githubusercontent.com/.well-known/jwks"
REFRESH_URL=WORKER+"/v1/jwks-refresh"
MAX_BODY=60000
ASCII=re.compile(r"^[a-zA-Z0-9_-]+$")


class JwksRefreshError(ValueError):
    pass


def parse_official_public_jwks(raw: bytes):
    if type(raw) is not bytes or not 0<len(raw)<=MAX_BODY:
        raise JwksRefreshError("OFFICIAL_JWKS_SIZE_INVALID")
    try:
        obj=json.loads(raw.decode("utf-8"))
    except (UnicodeError,ValueError):
        raise JwksRefreshError("OFFICIAL_JWKS_UNPARSABLE") from None
    keys=obj.get("keys") if type(obj) is dict else None
    if type(keys) is not list or len(keys)>40:
        raise JwksRefreshError("OFFICIAL_JWKS_SHAPE_INVALID")
    ret=[]
    seen=set()
    for key in keys:
        if type(key) is not dict or key.get("kty")!="RSA":
            continue
        kid=key.get("kid")
        n=key.get("n")
        exponent=key.get("e")
        if (type(kid) is not str or not 8<=len(kid)<=128 or
            not ASCII.fullmatch(kid) or type(n) is not str or
            not 250<=len(n)<=900 or not ASCII.fullmatch(n) or
            exponent!="AQAB"):
            raise JwksRefreshError("OFFICIAL_RSA_JWK_MALFORMED")
        if key.get("alg","RS256")!="RS256" or key.get("use","sig")!="sig":
            continue
        if kid in seen:
            raise JwksRefreshError("DUPLICATE_OFFICIAL_JWK")
        seen.add(kid)
        ret.append({"kid":kid,"kty":"RSA","alg":"RS256",
                    "use":"sig","n":n,"e":"AQAB"})
    if not 1<=len(ret)<=20:
        raise JwksRefreshError("OFFICIAL_SIGNING_KEYS_MISSING")
    return ret


def refresh(*, http=urlopen, jwt_minter=get_github_oidc_token,
            clock=None):
    now=clock if clock is not None else (
        lambda: datetime.now(timezone.utc))
    request=Request(JWKS,method="GET",headers={
        "Accept":"application/json",
        "User-Agent":"RACE-AI-GitHubOIDC-public-signing-key-update/1"
    })
    try:
        with http(request,timeout=9) as response:
            if response.status!=200 or response.geturl()!=JWKS:
                raise JwksRefreshError("PUBLIC_JWKS_ENDPOINT_UNVERIFIED")
            raw=response.read(MAX_BODY+1)
    except HTTPError as exc:
        raise JwksRefreshError("PUBLIC_JWKS_HTTP_"+str(exc.code)) from None
    except (URLError,TimeoutError,OSError):
        raise JwksRefreshError("PUBLIC_JWKS_FETCH_UNAVAILABLE") from None
    keys=parse_official_public_jwks(raw)
    instant=now()
    if not isinstance(instant,datetime) or instant.utcoffset() is None:
        raise JwksRefreshError("AWARE_CLOCK_REQUIRED")
    stamp=instant.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    body={"schema":"RACE_AI_GITHUB_OIDC_JWKS_REFRESH_V1",
          "retrieved_at":stamp,
          "source_sha256":sha256(raw).hexdigest(),
          "keys":keys}
    encoded=json.dumps(body,sort_keys=True,separators=(",",":")).encode()
    if len(encoded)>MAX_BODY:
        raise JwksRefreshError("JWK_REFRESH_REQUEST_OVERSIZED")
    token=jwt_minter()
    if not isinstance(token,str) or token.count(".")!=2 or len(token)>10000:
        raise JwksRefreshError("SIGNED_MAIN_IDENTITY_REQUIRED")
    outbound=Request(REFRESH_URL,method="POST",data=encoded,
                     headers={
            "Content-Type":"application/json","Accept":"application/json",
            "Authorization":"Bearer "+token,
            "User-Agent":"RACE-AI-GitHubOIDC-jwks-rotation/1",
        })
    try:
        with http(outbound,timeout=12) as response:
            if response.status!=200 or response.geturl()!=REFRESH_URL:
                raise JwksRefreshError("JWK_REFRESH_ACK_HTTP_INVALID")
            answer=response.read(14000)
    except HTTPError as exc:
        raise JwksRefreshError("JWK_REFRESH_HTTP_"+str(exc.code)) from None
    except (URLError,TimeoutError,OSError):
        raise JwksRefreshError("JWK_REFRESH_TRANSPORT_UNAVAILABLE") from None
    try:
        ack=json.loads(answer.decode("utf-8"))
    except (UnicodeError,ValueError):
        raise JwksRefreshError("JWK_REFRESH_ACK_INVALID") from None
    if (type(ack) is not dict or
        ack.get("schema")!="RACE_AI_GITHUB_OIDC_JWKS_REFRESH_ACK_V1" or
        ack.get("source_sha256")!=body["source_sha256"] or
        ack.get("retrieved_at")!=stamp or
        ack.get("key_count")!=len(keys) or
        ack.get("authenticated_update") is not True or
        ack.get("private_forecast_data_returned") is not False):
        raise JwksRefreshError("JWK_REFRESH_ACK_IDENTITY_MISMATCH")
    return {
        "schema":"RACE_AI_GITHUB_OIDC_PUBLIC_KEYS_ROTATION_EVIDENCE_V1",
        "status":"SIGNED_PUBLIC_JWKS_REFRESH_VERIFIED",
        "key_count":len(keys),
        "source_sha256":body["source_sha256"],
        "retrieved_at":stamp,
        "token_or_private_forecast_logged":False,
    }


def main():
    try:
        status=refresh()
        print(json.dumps(status,sort_keys=True))
        return 0
    except (JwksRefreshError,ValueError,TypeError):
        print('{"state":"SIGNED_PUBLIC_JWKS_REFRESH_NOT_VERIFIED"}')
        return 2

if __name__=="__main__":
    sys.exit(main())
