"""One real official preview HTML format & as-of availability audit.

Existing PR64 parser, no new forecast model; no original HTML persistence.
Exactly one bounded GET, no retries/schedule. Single HTML receipt is not an
upstream publication time, rights grant, or official confirmed final cutoff.
"""
from __future__ import annotations
from datetime import date,datetime,timezone
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from pathlib import Path
import hashlib,json,os,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
PIN=ROOT/"pr64-parser-reference"/"race_ai"
if PIN.is_dir() and str(PIN) not in race_ai.__path__:
    race_ai.__path__.append(str(PIN))

RACE="20261024-10-08"
URL="https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20261024&jcd=10&rno=8"
CUTOFF="2026-10-24T12:11:00+09:00"
BRANCH="refs/heads/p0-exhibition-beforeinfo-20261024"
TOKEN="ONE-MIKUNI-8R-PREVIEW-20261024"
MAX=1_000_000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError("source redirect rejected")

def audit(*,env=None,opener=None,parser=None,clock=None):
    e=os.environ if env is None else env
    if e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=BRANCH or e.get("RACE_AI_EXHIBIT_ONE_SHOT")!=TOKEN or len(e.get("GITHUB_SHA",""))!=40:
        raise RuntimeError("unadmitted preview experiment")
    now=clock() if clock else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise RuntimeError("aware capture clock required")
    record={"schema":"RACE_AI_REAL_BOAT_PREVIEW_ONE_GET_AUDIT_V1",
        "race_id":RACE,"provider_get_budget":1,"provider_get_attempts":0,
        "source_url":URL,"race_scheduled_cutoff_at":CUTOFF,
        "raw_html_published_to_git":False,"racer_data_published_to_git":False,
        "source_use_rights_independently_reviewed":False,
        "source_original_published_at_verified":False,
        "source_asof_exhibition_admitted_to_full_model":False,
        "source_asof_weather_admitted_to_full_model":False,
        "full_model_run":False,"official_prediction":False,
        "formal_hit_at_8_eligible":False,
        "status":"NOT_STARTED"}
    try:
        transport=opener or build_opener(NoRedirect(),HTTPSHandler())
        req=Request(URL,method="GET",headers={"Accept":"text/html",
            "User-Agent":"RACE-AI-one-off-preview-parser-validation/1"})
        record["provider_get_attempts"]=1
        with transport.open(req,timeout=10) as r:
            if r.status!=200 or r.geturl()!=URL:raise ValueError("status or URL conflict")
            record["http_status"]=r.status
            record["http_date_hint_unverified"]=r.headers.get("Date")
            raw=r.read(MAX+1)
        if not 0<len(raw)<=MAX:raise ValueError("page body oversize or empty")
        record["captured_bytes"]=len(raw)
        record["source_html_sha256"]=hashlib.sha256(raw).hexdigest()
        captured=(clock() if clock else datetime.now(timezone.utc)).isoformat()
        if parser is None:
            from race_ai.official_race_updates import parse_update
            parser=lambda x:parse_update(x,kind="beforeinfo",
                day=date(2026,10,24),venue="10",race_no=8,
                source_url=URL,captured_at=captured)
        state=parser(raw)
        if state.get("race_id")!=RACE or state.get("closed_at")!=CUTOFF:
            raise ValueError("selected race/source deadline mismatch")
        record["capture_clock_unattested"]=captured
        record["source_parser_status"]=state.get("status")
        record["parser_body_identity_verified"]=state.get("body_identity_verified",False)
        record["eligible_pre_race_by_local_capture_clock"]=state.get("eligible_pre_race",False)
        if state["status"]=="PENDING":
            record["status"]="OFFICIAL_PREVIEW_NOT_YET_PUBLISHED_OR_PENDING"
            record["missing_reason"]=state.get("missing_reason")
        elif state["status"]=="AVAILABLE":
            data=state["data"];boats=data.get("boats")
            if not isinstance(boats,list) or len(boats)!=6 or {b["lane"] for b in boats}!=set(range(1,7)):
                raise ValueError("preview six-lane observations incomplete")
            ex=[b for b in boats if b.get("display_time") is not None]
            starts=[b for b in boats if b.get("preview_st_status")=="OK" and b.get("preview_st") is not None]
            weather=data.get("weather",{})
            record.update({
                "preview_matched_six_lanes":True,
                "numeric_display_times_available":len(ex),
                "numeric_start_exhibition_ST_available":len(starts),
                "weather_wind_mps":weather.get("wind_speed_mps"),
                "weather_wave_cm":weather.get("wave_height_cm"),
                "weather_air_temperature_c":weather.get("air_temperature_c"),
                "weather_upstream_time_label":weather.get("source_reported_local_time"),
                "relative_wind_angle_from_source_proven":False,
                "wet_surface_factor_from_source_proven":False,
                "exhibition_first_published_at":None,
                "forecast_valid_at_cutoff_attested":False,
                "status":"REAL_PREVIEW_NUMERIC_FIELDS_OBSERVED_NOT_MODEL_ADMITTED"
            })
        else:raise ValueError("unknown official preview status")
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,
            ImportError,KeyError,UnicodeError) as exc:
        record["status"]="REAL_PREVIEW_SOURCE_OR_PARSER_UNVERIFIED"
        record["error_type"]=type(exc).__name__
        if isinstance(exc,HTTPError):record["http_status"]=exc.code
    record["runner_finished_at_unattested"]=(clock() if clock else datetime.now(timezone.utc)).isoformat()
    return record

def main():
    try:r=audit()
    except RuntimeError:print("NOT_ADMITTED");return 2
    print(json.dumps(r,sort_keys=True,ensure_ascii=False))
    return 0 if r["status"] in ("REAL_PREVIEW_NUMERIC_FIELDS_OBSERVED_NOT_MODEL_ADMITTED",
          "OFFICIAL_PREVIEW_NOT_YET_PUBLISHED_OR_PENDING") else 2
if __name__=="__main__":raise SystemExit(main())
