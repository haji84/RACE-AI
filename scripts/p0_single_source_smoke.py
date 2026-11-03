"""Single bounded official BOAT RACE page transport smoke; 0 raw publishing.

No scheduler, no retry, no odds/results ingestion, no training or model writes.
Run ONLY by a specially scoped single-use GitHub Actions push workflow.
A successful public GET != a source-rights/training permission grant.
"""
from __future__ import annotations
from datetime import datetime,timezone
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
import hashlib,json,os,sys
from race_ai.boat_official_web_adapter import (
    transform_official_screen,MAX_HTML_BYTES,
)

EXPECTED_REF="refs/heads/p0-source-smoke-20261024"
TARGET="https://www.boatrace.jp/owpc/pc/race/racelist?hd=20261025&jcd=11&rno=1"
class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError("redirect not approved for one-shot source test")

def smoke(*, opener=None, env=None):
    ctx=os.environ if env is None else env
    if (ctx.get("GITHUB_EVENT_NAME")!="push"
        or ctx.get("GITHUB_REF")!=EXPECTED_REF
        or ctx.get("RACE_AI_SINGLE_GET_ALLOWED")!="20261025-jcd11-rno1"
        or not ctx.get("GITHUB_SHA","")
        or len(ctx.get("GITHUB_SHA",""))!=40):
        raise RuntimeError("one-shot official smoke not explicitly gated")
    opener=opener or build_opener(_NoRedirect(),HTTPSHandler())
    req=Request(TARGET,method="GET",headers={
        "Accept":"text/html",
        "User-Agent":"RACE-AI-source-transport-validation/1 (one-request; no crawling)",
    })
    metadata={"schema":"RACE_AI_SINGLE_PAGE_TRANSPORT_SMOKE_V1",
              "target":TARGET,"request_count_limit":1,
              "purpose":"CONNECTIVITY_AND_FORMAT_TEST_ONLY",
              "automatic_periodic_collection_started":False,
              "copyrighted_html_persisted":False,
              "source_rights_admitted":False,
              "model_input_admitted":False,
              "provider_publication_time_proven":False,
              "external_pre_cutoff_forecast_proven":False}
    try:
        with opener.open(req,timeout=8) as resp:
            metadata["http_status"]=getattr(resp,"status",None)
            metadata["final_url_matches"]=resp.geturl()==TARGET
            headers=resp.headers
            mime=headers.get("Content-Type","").split(";",1)[0].lower().strip()
            metadata["mime"]=mime
            # HTTP Date is a server/proxy *response* header, NOT when stats
            # were first published. Last-Modified is a hint only.
            metadata["http_date_header_unverified"]=headers.get("Date")
            metadata["last_modified_header_unverified"]=headers.get("Last-Modified")
            if (metadata["http_status"]!=200
                or not metadata["final_url_matches"]
                or mime not in ("text/html","application/xhtml+xml")):
                raise ValueError("official source HTTP response was not acceptable")
            raw=resp.read(MAX_HTML_BYTES+1)
        if not 0<len(raw)<=MAX_HTML_BYTES:
            raise ValueError("official page empty or beyond 1.5 MiB budget")
        metadata["sha256"]=hashlib.sha256(raw).hexdigest()
        metadata["byte_count"]=len(raw)
        captured=datetime.now(timezone.utc).isoformat(timespec="seconds")
        metadata["captured_at_runner_clock_unattested"]=captured
        try:
            report=transform_official_screen(
                raw,source_url=TARGET,captured_at=captured,
                rights_ref="TRANSPORT_SMOKE_NOT_A_LICENSE")
        except (ValueError,TypeError) as e:
            metadata["schema_parse_ok"]=False
            metadata["schema_error_type"]=type(e).__name__
            metadata["status"]="HTTP_OK_SCHEMA_NOT_ACCEPTED"
        else:
            metadata["schema_parse_ok"]=True
            metadata["race_count"]=len(report["records"])
            metadata["status"]="HTTP_AND_AUDIT_ONLY_SCHEMA_OK"
        return metadata
    except (HTTPError,URLError,TimeoutError,OSError,RuntimeError,ValueError) as e:
        metadata["status"]="CONNECTIVITY_OR_RESPONSE_FAILED"
        metadata["error_type"]=type(e).__name__
        if isinstance(e,HTTPError):
            metadata["http_status"]=e.code
        # No raw error string: URLs in exceptions can reveal query credentials.
        return metadata

def main():
    try:result=smoke()
    except RuntimeError as e:
        print("SMOKE_NOT_RUN",type(e).__name__)
        return 2
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))
    return 0 if result["status"]=="HTTP_AND_AUDIT_ONLY_SCHEMA_OK" else 2
if __name__=="__main__":
    sys.exit(main())
