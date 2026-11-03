"""One K 2026-10-21 structural cause diagnostic; no record data emitted."""
from datetime import date,datetime,timezone
import hashlib,json,os,re,sys,unicodedata
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
PIN=ROOT/"pr64-parser-reference"/"race_ai"
if PIN.is_dir():race_ai.__path__.append(str(PIN))
from scripts.p0_real_b_k_pr71_history_join_20261024 import parse_prior_K_preserving_complete_races

URL="https://www1.mbrace.or.jp/od2/K/202610/k261021.lzh"
BRANCH="refs/heads/p0-k21-shape-20261024"
MAX=4_000_000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**k):raise ValueError("no redirection")

def category(exc):
    msg=str(exc)
    cases=[
        ("file header date","FILE_HEADER_DATE_MISMATCH"),
        ("no KBGN","MISSING_K_BLOCK"),
        ("unterminated KBGN","UNTERMINATED_K_BLOCK"),
        ("incomplete/nonunique result","INCOMPLETE_OR_NONUNIQUE_SIX_BOAT_RESULT"),
        ("no complete K race records","NO_COMPLETE_K_RACE_ROWS"),
        ("no recognizable race headers","VENUE_WITH_NO_RACE_HEADERS"),
        ("duplicate or invalid original K race header","DUPLICATE_OR_INVALID_HEADER"),
        ("no verified per-race","NO_VERIFIED_PER_RACE_K"),
    ]
    return next((v for k,v in cases if k in msg),"OTHER_STRUCTURAL_OR_FORMAT_ERROR")

def main():
    e=os.environ
    if e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=BRANCH or e.get("RACE_AI_K21_SHAPE")!="K21-ONE-DIAGNOSTIC" or len(e.get("GITHUB_SHA",""))!=40:
        print("NOT_ADMITTED");return 2
    report={"schema":"RACE_AI_K21_REDACTED_PARSER_SHAPE_V1",
            "scope":"READ_ONLY_FORMAT_DIAGNOSTIC",
            "date_jst":"2026-10-21",
            "provider_get_budget":1,"provider_get_attempts":0,
            "no_source_rows_logged":True,"original_source_bytes_saved":False,
            "forecast_executed":False,"model_input_admitted":False,
            "status":"UNKNOWN"}
    try:
        from race_ai.official_lzh_extract import extract_daily_lzh
        from race_ai.core import parse_k,_blocks,_ensure_day
        client=build_opener(NoRedirect(),HTTPSHandler())
        report["provider_get_attempts"]=1
        with client.open(Request(URL,headers={"Accept":"application/octet-stream",
               "User-Agent":"RACE-AI-one-K-layout-validation/1"},method="GET"),timeout=10) as response:
            if response.status!=200 or response.geturl()!=URL:raise ValueError("wrong provider status")
            raw=response.read(MAX+1)
        if not 25<len(raw)<=MAX or raw[2:7] not in (b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-"):
            raise ValueError("K archive malformed")
        report["archive_sha256"]=hashlib.sha256(raw).hexdigest()
        clear=extract_daily_lzh(raw,"K261021.TXT")
        body=unicodedata.normalize("NFKC",clear.decode("cp932"))
        report["text_sha256"]=hashlib.sha256(clear).hexdigest()
        blocks=list(_blocks(body,"K"))
        report["K_venue_blocks"]=len(blocks)
        report["start_marker_present"]="STARTK" in body[:200]
        report["body_date_mismatched_blocks"]=0
        report["venues_without_recognized_race_headers"]=0
        report["K_race_headers_total"]=0
        for venue,part in blocks:
            try:_ensure_day(part,"2026-10-21")
            except ValueError:report["body_date_mismatched_blocks"]+=1
            headers=len(re.findall(r"(?m)^\s*\d{1,2}R\s+.*?H\s*\d{3,4}m",part,re.I))
            report["K_race_headers_total"]+=headers
            if headers==0:report["venues_without_recognized_race_headers"]+=1
        try:
            entries=parse_k(clear,"2026-10-21")
            report["whole_K_parser_status"]="PASSED"
            report["whole_K_parsed_rows"]=len(entries)
        except ValueError as exc:
            report["whole_K_parser_status"]="REJECTED"
            report["whole_K_parser_error_classification"]=category(exc)
        try:
            entries,excluded=parse_prior_K_preserving_complete_races(clear,"2026-10-21",parse_k)
            report["per_race_parser_status"]="PARTIAL_ACCEPTED"
            report["per_race_accepted_rows"]=len(entries)
            report["per_race_excluded_complete_race_count"]=excluded
        except ValueError as exc:
            report["per_race_parser_status"]="REJECTED"
            report["per_race_parser_error_classification"]=category(exc)
        report["status"]="K_LAYOUT_CAUSE_AGGREGATE_REPORTED"
    except Exception as exc:
        report["status"]="K_LAYOUT_DIAG_UNVERIFIED"
        report["error_type"]=type(exc).__name__
    report["runner_clock_unattested"]=datetime.now(timezone.utc).isoformat()
    print(json.dumps(report,sort_keys=True,ensure_ascii=False))
    return 0 if report["status"]=="K_LAYOUT_CAUSE_AGGREGATE_REPORTED" else 2
if __name__=="__main__":raise SystemExit(main())
