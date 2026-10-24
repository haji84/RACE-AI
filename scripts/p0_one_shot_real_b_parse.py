"""One real, bounded official B download -> pinned PR64 parser smoke.

No loops, no schedule, no raw file persistence, no rights claim or model
forecast. An actual historical day is used ONLY for source layout validation.
"""
from __future__ import annotations
from datetime import date,datetime,timezone
from pathlib import Path
import hashlib,json,os,sys
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import race_ai
PR64=HERE/"pr64-parser-reference/race_ai"
if PR64.is_dir():
    race_ai.__path__.append(str(PR64))
TARGET="https://www1.mbrace.or.jp/od2/B/202610/b261022.lzh"
BRANCH="refs/heads/p0-b-parse-smoke-20261024"
MAX=4_000_000

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError("one-shot probe does not allow redirects")

def probe(*,env=None,opener=None,extract=None,parser=None):
    e=os.environ if env is None else env
    if (e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=BRANCH
        or e.get("RACE_AI_B_PARSE_ALLOWED")!="20261022-B-PARSER"
        or len(e.get("GITHUB_SHA",""))!=40):
        raise RuntimeError("one-shot read-only GitHub test admission required")
    metrics={"schema":"RACE_AI_REAL_B_ONE_SHOT_PARSER_SMOKE_V1",
             "source_url":TARGET,"date_jst":"2026-10-22",
             "planned_provider_get_count":1,"auto_schedule_enabled":False,
             "raw_archive_retained":False,"copied_racecard_republished":False,
             "official_source_rights_granted_by_test":False,
             "model_feature_ready":False,
             "independent_capture_time_proven":False,
             "independent_original_publication_time_proven":False}
    try:
        client=opener or build_opener(NoRedirect(),HTTPSHandler())
        request=Request(TARGET,headers={"Accept":"application/octet-stream",
            "User-Agent":"RACE-AI-single-B-layout-validation/1"},method="GET")
        with client.open(request,timeout=10) as response:
            metrics["http_status"]=getattr(response,"status",None)
            metrics["mime"]=response.headers.get("Content-Type","").split(";",1)[0].lower()
            metrics["http_date_hint_unverified"]=response.headers.get("Date")
            metrics["http_last_modified_hint_unverified"]=response.headers.get("Last-Modified")
            if response.geturl()!=TARGET or metrics["http_status"]!=200:
                raise ValueError("unexpected source response")
            raw=response.read(MAX+1)
        if not 25<=len(raw)<=MAX or raw[2:7] not in (
                b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-"):
            raise ValueError("unexpected LZH archive bytes or budget")
        metrics["compressed_bytes"]=len(raw)
        metrics["raw_archive_sha256"]=hashlib.sha256(raw).hexdigest()
        if extract is None:
            from race_ai.official_lzh_extract import extract_daily_lzh
            extract=extract_daily_lzh
        expanded=extract(raw,"B261022.TXT")
        metrics["uncompressed_bytes"]=len(expanded)
        metrics["expanded_text_sha256"]=hashlib.sha256(expanded).hexdigest()
        if parser is None:
            from race_ai.core import parse_b
            from race_ai.official_b_snapshot_adapter import program_details
            def parser(content):
                from race_ai.core import SourceError
                try:
                    entries=parse_b(content,"2026-10-22")
                except SourceError as exc:
                    metrics["parser_stage"]="official_parse_b"
                    metrics["parser_diagnostic"]=str(exc)[:140]
                    raise
                metrics["parsed_minimal_entrant_count"]=len(entries)
                try:
                    details,deadlines=program_details(content,date(2026,10,22))
                except SourceError as exc:
                    metrics["parser_stage"]="official_program_details"
                    metrics["parser_diagnostic"]=str(exc)[:140]
                    if str(exc) == "B program detail layout malformed":
                        # Only safe aggregate syntax counts; no source text
                        # or per-athlete/per-race fields in public CI logs.
                        from race_ai.b_layout_shape_diagnostic import summarize_b_layout
                        metrics["redacted_layout_diagnostic"] = summarize_b_layout(content)
                    raise
                metrics["parser_stage"]="fully_parsed"
                return entries,details,deadlines
        entrants,details,deadlines=parser(expanded)
        if not all(isinstance(x,dict) for x in entrants):
            raise ValueError("official program schema failed")
        if len(entrants)==0 or len(entrants)!=len(details) or len(entrants)!=6*len(deadlines):
            raise ValueError("B program entrants/limits/closing mismatch")
        if len({x["race_id"] for x in entrants})!=len(deadlines):
            raise ValueError("official race identity inconsistent")
        for r in entrants:
            key=(r["race_id"],r["lane"])
            if key not in details:
                raise ValueError("entrant identity not in detailed B")
            # Date-pinned actual B data is not the model's time-proven
            # current-race input. No records exported here.
        metrics["race_count"]=len(deadlines)
        metrics["entrant_count"]=len(entrants)
        metrics["detailed_stat_rows"]=len(details)
        metrics["cutoff_time_fields"]=len(deadlines)
        metrics["observed_at_runner_clock_unattested"]=datetime.now(timezone.utc).isoformat()
        metrics["status"]="REAL_OFFICIAL_B_FORMAT_ACCEPTED_AUDIT_ONLY"
    except (HTTPError,URLError,TimeoutError,OSError,RuntimeError,ValueError,
            ImportError,TypeError) as exc:
        metrics["status"]="REAL_B_TRANSPORT_OR_PARSE_UNVERIFIED"
        metrics["error_type"]=type(exc).__name__
        if isinstance(exc,HTTPError):metrics["http_status"]=exc.code
    return metrics

def main():
    try:out=probe()
    except RuntimeError as exc:
        print("PARSER_SMOKE_GATED",type(exc).__name__)
        return 2
    print(json.dumps(out,sort_keys=True,ensure_ascii=False))
    return 0 if out["status"]=="REAL_OFFICIAL_B_FORMAT_ACCEPTED_AUDIT_ONLY" else 2
if __name__=="__main__":sys.exit(main())
