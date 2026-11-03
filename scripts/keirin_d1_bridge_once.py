"""Private D1 race-inventory bridge using GitHub Actions OIDC, no API secrets.

One permitted dated public source index GET -> verified race identities ->
Cloudflare Worker bound to private D1. This does NOT run a model, gather
athlete details, scrape results, or export private forecast originals.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote, urlsplit
import json
import os
import re
import sys

from race_ai.keirin_discovery import get_single_day, DiscoveryError

AUD = "race-ai-keirin-private-state-v1"
WORKER = "https://race-ai-keirin-private-state.qq-1130034.workers.dev"
JST = timezone(timedelta(hours=9))
ALLOWED_EVENTS = {"push", "schedule", "workflow_dispatch"}
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BridgeError(ValueError):
    pass


def get_github_oidc_token(*, env=None, open_url=urlopen):
    env=os.environ if env is None else env
    if (env.get("GITHUB_REPOSITORY") != "haji84/RACE-AI" or
        env.get("GITHUB_REF") != "refs/heads/main" or
        env.get("GITHUB_EVENT_NAME") not in ALLOWED_EVENTS):
        raise BridgeError("UNTRUSTED_ACTIONS_ORIGIN")
    endpoint=env.get("ACTIONS_ID_TOKEN_REQUEST_URL","")
    request_token=env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN","")
    if (not endpoint.startswith("https://") or
            len(request_token)<10 or len(endpoint)>5000):
        raise BridgeError("GITHUB_OIDC_NOT_AVAILABLE")
    from_url=urlsplit(endpoint)
    hostname=from_url.hostname or ""
    # GitHub-hosted runners use region-specific pipelines*.actions.github*
    # endpoints; require the exact GitHub Actions domain boundary.
    if (from_url.scheme!="https" or
        not hostname.endswith(".actions.githubusercontent.com") or
        from_url.username or from_url.password or from_url.port):
        safe_prefix=hostname.split(".")[0]
        if not re.fullmatch(r"[a-zA-Z0-9-]{1,80}",safe_prefix):
            safe_prefix="UNRECOGNIZED"
        raise BridgeError("GITHUB_OIDC_ISSUER_UNEXPECTED_"+safe_prefix)
    separator="&" if "?" in endpoint else "?"
    url=endpoint+separator+"audience="+quote(AUD,safe="")
    req=Request(url,method="GET",headers={
        "Authorization":"bearer "+request_token,
        "Accept":"application/json",
    })
    try:
        with open_url(req,timeout=10) as r:
            if r.status!=200:
                raise BridgeError("GITHUB_OIDC_HTTP_NOT_OK")
            raw=r.read(16000)
    except HTTPError as e:
        raise BridgeError("GITHUB_OIDC_HTTP_"+str(e.code)) from None
    except (URLError,TimeoutError,OSError):
        raise BridgeError("GITHUB_OIDC_UNAVAILABLE") from None
    try:
        token=json.loads(raw.decode("utf-8"))["value"]
    except (ValueError,KeyError,UnicodeError):
        raise BridgeError("GITHUB_OIDC_RESPONSE_INVALID") from None
    if type(token) is not str or len(token)>10000 or token.count(".")!=2:
        raise BridgeError("GITHUB_OIDC_TOKEN_INVALID")
    return token


def submit_day(*, event_day=None, collector=get_single_day,
               token_provider=get_github_oidc_token, open_url=urlopen):
    day=event_day or datetime.now(JST).date().isoformat()
    if type(day) is not str or not DAY.fullmatch(day):
        raise BridgeError("DAY_INVALID")
    # Validate full actual event-day identity before OIDC submission.
    index=collector(day)
    rows=index.get("races")
    if not isinstance(rows,list) or not 1 <= len(rows) <= 200:
        raise BridgeError("INCOMPLETE_DAY_DISCOVERY")
    body={
        "schema":"RACE_AI_KEIRIN_PRIVATE_COHORT_SYNC_V1",
        "event_date_jst":day,
        "source_sha256":index["source_sha256"],
        "races":[{
           "race_id":row["race_id"],
           "venue_code":row["venue_code"],
           "race_no":row["race_no"],
        } for row in rows],
    }
    token=token_provider()
    raw=json.dumps(body,ensure_ascii=False,
                   separators=(",",":"),sort_keys=True).encode("utf-8")
    if len(raw)>45000:
        raise BridgeError("PRIVATE_COHORT_TOO_LARGE")
    req=Request(WORKER+"/v1/cohort",method="POST",data=raw,headers={
        "Authorization":"Bearer "+token,
        "Accept":"application/json",
        "Content-Type":"application/json",
        "User-Agent":"RACE-AI-GitHubOIDC-private-inventory/1",
    })
    try:
        with open_url(req,timeout=12) as r:
            if r.status!=200 or r.geturl()!=WORKER+"/v1/cohort":
                raise BridgeError("CLOUDFLARE_PRIVATE_INGEST_NOT_OK")
            incoming=r.read(16000)
    except HTTPError as e:
        # The Worker exposes a small set of fixed, non-sensitive error codes.
        # Never print the JWT, response headers, raw body or race data.
        detail="UNKNOWN"
        try:
            problem=json.loads(e.read(500).decode("utf-8"))
            candidate=problem.get("error","")
            if candidate in ("AUTH_SOURCE_UNAVAILABLE",
                             "PRIVATE_STORAGE_UNAVAILABLE",
                             "UNAUTHORIZED","DATABASE_UNBOUND",
                             "INVALID_COHORT_INPUT"):
                detail=candidate
        except (ValueError,UnicodeError,AttributeError):
            pass
        raise BridgeError("CLOUDFLARE_PRIVATE_HTTP_"+str(e.code)+"_"+detail) from None
    except (URLError,TimeoutError,OSError):
        raise BridgeError("CLOUDFLARE_PRIVATE_INGEST_UNAVAILABLE") from None
    try:
        ack=json.loads(incoming.decode("utf-8"))
    except (ValueError,UnicodeError):
        raise BridgeError("PRIVATE_ACK_UNREADABLE") from None
    if (ack.get("schema")!="RACE_AI_KEIRIN_PRIVATE_COHORT_ACK_V1" or
        ack.get("event_date_jst")!=day or
        ack.get("submitted_races")!=len(rows) or
        type(ack.get("saved_races_for_day")) is not int or
        ack["saved_races_for_day"]<len(rows) or
        ack.get("private_forecasts_exposed") is not False):
        raise BridgeError("CLOUDFLARE_PRIVATE_READBACK_INVALID")
    return {
        "schema":"RACE_AI_KEIRIN_D1_BRIDGE_OBSERVATION_V1",
        "event_day":day,
        "submitted":len(rows),
        "stored_at_least":ack["saved_races_for_day"],
        "source_sha256":index["source_sha256"],
        "status":"PRIVATE_D1_RACE_IDENTITIES_COMMITTED",
        "original_forecasts_sent":False,
        "results_parsed":False,
        "formal_hit_at_8_all":None,
    }


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--day",default=None)
    args=p.parse_args()
    try:
        report=submit_day(event_day=args.day)
        print(json.dumps(report,sort_keys=True,ensure_ascii=False))
        return 0
    except (DiscoveryError,BridgeError,ValueError,KeyError,TypeError) as e:
        # All BridgeError codes are static literals; never output OIDC JWT.
        reason = str(e) if isinstance(e,BridgeError) else type(e).__name__
        print(json.dumps({"state":"PRIVATE_D1_INGEST_NOT_VERIFIED",
            "reason_code":reason,"provider_raw_records_exposed":False}))
        return 2


if __name__=="__main__":
    sys.exit(main())
