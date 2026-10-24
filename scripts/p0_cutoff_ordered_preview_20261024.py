"""One-shot all-candidate cutoff-order trial, public official 2026-10-24 B + 2 beforeinfo.

Only 2-10 minute upcoming sources may be attempted. Never call original
PR71 predictor without independent publication, rights and source histories.
The earlier eligible race is preferred only among equally observed candidates.
At most 3 official GETs; no background polling, result or odds access.
"""
from __future__ import annotations
from datetime import date,datetime,timezone,timedelta
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
import hashlib,json,os,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
PIN=ROOT/"pr64-parser-reference"/"race_ai"
if PIN.is_dir() and str(PIN) not in race_ai.__path__:race_ai.__path__.append(str(PIN))
DAY="2026-10-24"
SOURCE="https://www1.mbrace.or.jp/od2/B/202610/b261024.lzh"
BRANCH="refs/heads/p0-cutoff-ordered-preview-20261024"
TOKEN="OCT24-13H-CUTOFF-SORTED"
CANDIDATES=(
  ("20261024-13-06","尼崎6R", "13","6","2026-10-24T13:21:00+09:00"),
  ("20261024-05-07","多摩川7R", "05","7","2026-10-24T13:23:00+09:00"),
  ("20261024-09-07","津7R","09","7","2026-10-24T13:25:00+09:00")
)
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError("redirect refused")

def audit(*,env=None,clock=None,opener=None,extractor=None,parser_b=None,parser_details=None,parser_preview=None):
    e=os.environ if env is None else env
    if(e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=BRANCH or
       e.get("RACE_AI_CUTOFF_ORDERED_ONCE")!=TOKEN or len(e.get("GITHUB_SHA",""))!=40):
        raise RuntimeError("one-shot cutoff audit not authorized")
    now=clock() if clock else datetime.now(timezone.utc)
    if now.utcoffset() is None:raise RuntimeError("timezone aware runner clock required")
    within=[c for c in CANDIDATES
            if timedelta(minutes=2)<=datetime.fromisoformat(c[4])-now<=timedelta(minutes=10)]
    if not within:
        return {"schema":"RACE_AI_CUTOFF_ORDERED_RACE_SELECTION_V1",
                "status":"NO_CANDIDATE_WITHIN_2_TO_10_MINUTES",
                "provider_GET_attempts":0,"selected_race":None,"formal_model_executed":False}
    ordered=sorted(within,key=lambda x:(x[4],x[0]))
    report={"schema":"RACE_AI_CUTOFF_ORDERED_RACE_SELECTION_V1",
            "observed_on_runner_clock":now.isoformat(),
            "selected_race":None,
            "provider_GET_budget":1+min(2,len(ordered)),
            "provider_GET_attempts":0,
            "official_result_used":False,"odds_used":False,
            "source_published_at_independently_verified":False,
            "model_source_rights_independently_verified":False,
            "historical_K_previous_race_requirement_verified":False,
            "wind_true_bearing_verified":False,
            "wet_surface_factor_proven":False,
            "original_PR71_weights_changed":False,
            "formal_model_executed":False,
            "full_PR71_model_top8":None,
            "official_prediction":False,
            "raw_source_bytes_persisted":False,"full_racer_source_rows_published":False,
            "candidates_sorted":[{"race_id":x[0],"title":x[1],"cutoff":x[4]} for x in ordered],
            "checked":[],"status":"NO_MODEL_INPUT_PROOF"}
    if extractor is None:
        from race_ai.official_lzh_extract import extract_daily_lzh
        extractor=extract_daily_lzh
    if parser_b is None:
        from race_ai.core import parse_b
        parser_b=parse_b
    if parser_details is None:
        from race_ai.official_b_snapshot_adapter import program_details
        parser_details=program_details
    if parser_preview is None:
        from race_ai.official_race_updates import parse_update
        parser_preview=parse_update
    client=opener or build_opener(NoRedirect(),HTTPSHandler())
    def get(url,maxsize,accept):
        if report["provider_GET_attempts"]>=report["provider_GET_budget"]:
            raise ValueError("upstream request budget reached")
        report["provider_GET_attempts"]+=1
        with client.open(Request(url,method="GET",headers={
                "Accept":accept,"User-Agent":"RACE-AI-single-ordered-near-cutoff-study/1"}),timeout=8) as r:
            if r.status!=200 or r.geturl()!=url:raise ValueError("untrusted origin or HTTP")
            b=r.read(maxsize+1)
        if not 0<len(b)<=maxsize:raise ValueError("source bytes out of bound")
        return b
    try:
        raw=get(SOURCE,4000000,"application/octet-stream")
        if raw[2:7] not in (b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-"):
            raise ValueError("B source archive signature")
        text=extractor(raw,"B261024.TXT")
        entries=parser_b(text,DAY)
        details,deadlines=parser_details(text,date.fromisoformat(DAY))
        report["B_source_sha256"]=hashlib.sha256(raw).hexdigest()
        if len(entries)!=len(details):raise ValueError("B entrant detail mismatch")
        for race,title,venue,num,cutoff in ordered[:2]:
            t=clock() if clock else datetime.now(timezone.utc)
            if not timedelta(minutes=2)<=datetime.fromisoformat(cutoff)-t<=timedelta(minutes=10):
                report["checked"].append({"race_id":race,"status":"CUTOFF_WINDOW_NO_LONGER_SAFE"})
                continue
            if deadlines.get(race)!=cutoff:
                report["checked"].append({"race_id":race,"status":"OFFICIAL_B_DEADLINE_CONFLICT"})
                continue
            source=f"https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20261024&jcd={venue}&rno={num}"
            html=get(source,1000000,"text/html")
            captured=(clock() if clock else datetime.now(timezone.utc)).isoformat()
            if datetime.fromisoformat(captured)>=datetime.fromisoformat(cutoff):
                report["checked"].append({"race_id":race,"status":"PREVIEW_CAPTURE_AFTER_CUTOFF"})
                continue
            info=parser_preview(html,kind="beforeinfo",day=date.fromisoformat(DAY),
                venue=venue,race_no=int(num),source_url=source,captured_at=captured)
            if info.get("race_id")!=race or info.get("closed_at")!=cutoff:
                raise ValueError("actual race/cutoff identity mismatch")
            status=info.get("status")
            result={"race_id":race,"title":title,"cutoff_at":cutoff,
                    "captured_at_runner_unattested":captured,
                    "source_html_sha256":hashlib.sha256(html).hexdigest(),
                    "source_parser_status":status,
                    "schedule_proven_issued_as_scheduled_not_final":True}
            if status=="AVAILABLE":
                bylane={r["lane"]:r["racer_id"] for r in entries if r["race_id"]==race}
                observed=info["data"]["boats"]
                if len(bylane)!=6 or {b["lane"]:b["racer_registration_id"] for b in observed}!=bylane:
                    raise ValueError("B roster/preview mismatch")
                result["registered_six_match_official_B"]=True
                result["display_time_numeric_count"]=sum(b["display_time"] is not None for b in observed)
                result["exhibition_ST_numeric_count"]=sum(
                    b["preview_st_status"]=="OK" and b["preview_st"] is not None for b in observed)
                w=info["data"]["weather"]
                result["wind_mps_available"]=w.get("wind_speed_mps") is not None
                result["wave_cm_available"]=w.get("wave_height_cm") is not None
                result["all_public_preview_numeric_available"]=(
                    result["display_time_numeric_count"]==6 and
                    result["exhibition_ST_numeric_count"]==6 and
                    result["wind_mps_available"] and result["wave_cm_available"])
            else:
                result["all_public_preview_numeric_available"]=False
                result["source_missing_reason"]=info.get("missing_reason")
            report["checked"].append(result)
        selectable=[r for r in report["checked"] if r.get("all_public_preview_numeric_available")]
        if selectable:
            # earliest of equally complete preview observations, never odds.
            report["selected_race"]=selectable[0]["race_id"]
            report["status"]="PREVIEW_READY_EARLIEST_RACE_SELECTED_BUT_FULL_MODEL_UNADMITTED"
        else:
            report["status"]="NO_NEAR_TERM_RACE_WITH_ALL_PREVIEW_NUMERICS"
    except (HTTPError,URLError,OSError,TimeoutError,ValueError,TypeError,KeyError,ImportError,UnicodeError) as exc:
        report["status"]="NO_FORECAST_SOURCE_OR_PREVIEW_UNVERIFIED"
        report["error_type"]=type(exc).__name__
        if isinstance(exc,HTTPError):report["http_status"]=exc.code
    report["finished_runner_clock_unattested"]=(clock() if clock else datetime.now(timezone.utc)).isoformat()
    return report

def main():
    try:r=audit()
    except RuntimeError:print("NOT_ADMITTED");return 2
    print(json.dumps(r,ensure_ascii=False,sort_keys=True))
    return 0 if r["status"] in (
        "PREVIEW_READY_EARLIEST_RACE_SELECTED_BUT_FULL_MODEL_UNADMITTED",
        "NO_CANDIDATE_WITHIN_2_TO_10_MINUTES",
        "NO_NEAR_TERM_RACE_WITH_ALL_PREVIEW_NUMERICS") else 2
if __name__=="__main__":raise SystemExit(main())
