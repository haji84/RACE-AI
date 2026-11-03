"""One-shot official B LZH archive connectivity test, not an ingestion right.

Only for a one-time dedicated GitHub Actions branch push. Raw payload is
checked in memory and immediately discarded. No odds, model, reuse or storage.
"""
import hashlib,json,os,sys
from urllib.request import Request,HTTPSHandler,HTTPRedirectHandler,build_opener
from urllib.error import HTTPError,URLError

TARGET="https://www1.mbrace.or.jp/od2/B/202610/b261025.lzh"
REF="refs/heads/p0-b-smoke-20261024"
MAX=4_000_000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError("redirect denied for HTTPS-only official B probe")

def one_shot(*,context=None,opener=None):
    e=os.environ if context is None else context
    if e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=REF or (
        e.get("RACE_AI_B_ONE_SHOT")!="20261025-B") or len(e.get("GITHUB_SHA",""))!=40:
        raise RuntimeError("special one-shot branch & gate required")
    client=opener or build_opener(NoRedirect(),HTTPSHandler())
    req=Request(TARGET,headers={"Accept":"application/octet-stream",
                "User-Agent":"RACE-AI-one-shot-B-transport-check/1"},method="GET")
    out={"schema":"RACE_AI_ONE_SHOT_BOAT_B_TRANSPORT_DIAGNOSTIC_V1",
         "official_candidate_url":TARGET,"allowlist_request_budget":1,
         "purpose":"SINGLE_CONNECTIVITY_TEST_NOT_AUTOMATED_COLLECTION",
         "scheduled_repeat":False,"raw_archive_stored":False,
         "model_feature_data_admitted":False,
         "source_license_or_first_publication_proven":False}
    try:
        with client.open(req,timeout=10) as resp:
            out["http_status"]=resp.status
            out["final_url_exact"]=resp.geturl()==TARGET
            out["mime"]=resp.headers.get("Content-Type","").split(";",1)[0].strip().lower()
            out["date_header_not_published_at"]=resp.headers.get("Date")
            out["last_modified_header_unverified"]=resp.headers.get("Last-Modified")
            if out["http_status"]!=200 or not out["final_url_exact"]:
                raise ValueError("bad status or redirect")
            if out["mime"] not in (
                "application/octet-stream","application/x-lzh-compressed",
                "application/x-lha","application/lzh","binary/octet-stream"):
                raise ValueError("unexpected archive content type")
            data=resp.read(MAX+1)
        if not 8<=len(data)<=MAX:raise ValueError("empty or oversized archive")
        out["sha256"]=hashlib.sha256(data).hexdigest()
        out["compressed_size"]=len(data)
        out["looks_like_lzh_header"]=data[2:7] in (
            b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-")
        out["status"]="OFFICIAL_B_BYTES_OBSERVED" if out["looks_like_lzh_header"] else "UNKNOWN_ARCHIVE_FORMAT"
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,RuntimeError) as exc:
        out["status"]="NETWORK_OR_SOURCE_RESPONSE_FAILED"
        out["error_type"]=type(exc).__name__
        if isinstance(exc,HTTPError):out["http_status"]=exc.code
    return out

def main():
    try:r=one_shot()
    except RuntimeError as exc:
        print("NOT_AUTHORIZED_FOR_ONE_SHOT",type(exc).__name__)
        return 2
    print(json.dumps(r,sort_keys=True,ensure_ascii=False))
    return 0 if r["status"]=="OFFICIAL_B_BYTES_OBSERVED" else 2
if __name__=="__main__":sys.exit(main())
