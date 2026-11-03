"""One-shot all-candidate cutoff-order trial, public official 2026-10-24 B + 2 beforeinfo.

Upcoming sources are checked in cutoff order with NO arbitrary ten-minute cap.
Official beforeinfo AVAILABLE triggers eligibility; never call original
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
from race_ai.boat_deadline_first_selector import all_closing_candidates, pick_first_published_preview
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError("redirect refused")

def audit(*,env=None,clock=None,opener=None,extractor=None,parser_b=None,parser_details=None,parser_preview=None):
    e=os.environ if env is None else env
    if(e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=BRANCH or
       e.get("RACE_AI_CUTOFF_ORDERED_ONCE")!=TOKEN or len(e.get("GITHUB_SHA",""))!=40):
        raise RuntimeError("one-shot cutoff audit not authorized")
    now=clock() if clock else datetime.now(timezone.utc)
    if now.utcoffset() is None:raise RuntimeError("timezone aware runner clock required")
    report={"schema":"RACE_AI_CUTOFF_ORDERED_RACE_SELECTION_V1",
            "observed_on_runner_clock":now.isoformat(),
            "selected_race":None,
            "published_preview_count":0,
            "numeric_ready_race":None,
            "selection_trigger":"FIRST_PARTY_BEFOREINFO_OBSERVED_AVAILABLE_NOT_MINUTES",
            "no_arbitrary_upper_cutoff_minutes":True,
            "provider_GET_budget":3,
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
            "candidates_sorted":[],
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
        report["B_official_races_in_daily_source"]=len(deadlines)
        report["B_official_venues_in_daily_source"]=len({rid[9:11] for rid in deadlines})
        ordered=all_closing_candidates(deadlines,now=(clock() if clock else datetime.now(timezone.utc)),
                    day_jst="20261024",min_minutes=0,max_minutes=None)
        report["candidates_sorted"]=[{"race_id":r["race_id"],
                        "cutoff":r["scheduled_cutoff"]} for r in ordered]
        if not ordered:
            report["status"]="NO_UNEXPIRED_RACES_LEFT_IN_DAILY_B"
            report["finished_runner_clock_unattested"]=(clock() if clock else datetime.now(timezone.utc)).isoformat()
            return report
        for item in ordered[:2]:
            race=item["race_id"]
            venue=item["venue_code"]
            num=item["race_no"]
            cutoff=item["scheduled_cutoff"]
            title=f"venue-{venue}-{num}R"
            t=clock() if clock else datetime.now(timezone.utc)
            if datetime.fromisoformat(cutoff)<=t:
                report["checked"].append({"race_id":race,"status":"OFFICIAL_SCHEDULE_CUTOFF_ALREADY_PASSED"})
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
                    "preview_status":status,
                    "preview_identity_matched":info.get("body_identity_verified") is True,
                    "collected_before_scheduled_cutoff":datetime.fromisoformat(captured)<datetime.fromisoformat(cutoff),
                    "scheduled_cutoff":cutoff,
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
        report["published_preview_count"]=sum(r.get("preview_status")=="AVAILABLE" and r.get("preview_identity_matched") is True for r in report["checked"])
        first_published=pick_first_published_preview(report["checked"])
        selectable=[r for r in report["checked"] if r.get("all_public_preview_numeric_available")]
        if first_published:
            # Publication observation triggers admission review even when a
            # nonnumeric exhibition ST prevents the strict FULL model.
            report["selected_race"]=first_published["race_id"]
            report["numeric_ready_race"]=selectable[0]["race_id"] if selectable else None
            report["status"]="OFFICIAL_PREVIEW_OBSERVED_RUN_INPUT_GATES_NOT_FORECAST"
        else:
            report["status"]="NO_OBSERVED_OFFICIAL_PREVIEW_AVAILABLE"
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
        "OFFICIAL_PREVIEW_OBSERVED_RUN_INPUT_GATES_NOT_FORECAST",
        "NO_UNEXPIRED_RACES_LEFT_IN_DAILY_B",
        "NO_OBSERVED_OFFICIAL_PREVIEW_AVAILABLE") else 2
if __name__=="__main__":raise SystemExit(main())
