"""Optional one-day BOATRACE unofficial public API adapter.

This is not an official feed and does not include original lap/turn/straight
exhibition metrics or verified motor-use cycles. No raw upstream data is
committed or republished. Network access is limited to one fixed public host.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib import request, error, parse
from zoneinfo import ZoneInfo

from .core import SourceError, utc

HOST="boatraceopenapi.github.io"
MAX_BYTES=12_000_000
JST=ZoneInfo("Asia/Tokyo")


def endpoint(day:date)->str:
    if day.year < 2026:
        raise SourceError("public API supports dates from 2026-01-01")
    return f"https://{HOST}/api/v1/{day.year}/{day.strftime('%Y%m%d')}.json"


class SameHostRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target=parse.urlsplit(newurl)
        if target.scheme!="https" or target.netloc!=HOST:
            raise SourceError("redirect to unapproved external host rejected")
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_one_day(day:date, *, permitted:bool=False, probe_only:bool=False):
    """One GET of the documented day endpoint, at most MAX_BYTES.

    For saving/deriving output, the operator must separately accept provider
    terms and confirm the intended downstream use. Probe returns metadata only.
    """
    if not (permitted or probe_only):
        raise SourceError("provider usage/rights must be explicitly acknowledged")
    url=endpoint(day)
    opener=request.build_opener(SameHostRedirects)
    req=request.Request(url,headers={"User-Agent":"RACE-AI-research/0.12 (one-day-audit)",
                                     "Accept":"application/json"})
    try:
        with opener.open(req,timeout=20) as response:
            final=parse.urlsplit(response.geturl())
            if final.scheme!="https" or final.netloc!=HOST:
                raise SourceError("unexpected host")
            if response.status!=200:
                raise SourceError(f"upstream status: {response.status}")
            blob=response.read(MAX_BYTES+1)
    except (error.URLError,TimeoutError) as exc:
        raise SourceError(f"one-day provider unavailable: {type(exc).__name__}") from exc
    if len(blob)>MAX_BYTES:
        raise SourceError("provider response exceeds size cap")
    retrieved=datetime.now(timezone.utc).isoformat(timespec="seconds")
    return blob,dict(url=url,sha256=hashlib.sha256(blob).hexdigest(),
                     first_observed_at=retrieved,upstream_published_at=None,
                     original_provider="UNOFFICIAL_NON_GUARANTEED")


def _int(value, label, low, high):
    if type(value) is not int or not low<=value<=high:
        raise SourceError(f"bad {label}")
    return value


def normalize(blob:bytes,*, day:date, received_at:str, source_url:str,
              source_sha256:str)->dict:
    """Normalize race-day programs; all unknown originals remain null.

    Data are considered available no earlier than received_at. Result and
    preview presence must not imply they existed before that timestamp.
    """
    if source_url!=endpoint(day) or not re.fullmatch(r"[0-9a-f]{64}",source_sha256):
        raise SourceError("unexpected provider identity")
    asof=utc(received_at)
    if hashlib.sha256(blob).hexdigest()!=source_sha256:
        raise SourceError("provider blob hash mismatch")
    if len(blob)>MAX_BYTES:
        raise SourceError("provider blob is too large")
    try:
        root=json.loads(blob)
        stadiums=root["programs"]["stadiums"]
    except (UnicodeDecodeError,ValueError,KeyError,TypeError) as exc:
        raise SourceError("unrecognized provider JSON shape") from exc
    if not isinstance(stadiums,dict):
        raise SourceError("stadiums must be a JSON object")
    venues=[]
    for key,stadium in stadiums.items():
        if not str(key).isdigit() or not 1<=int(key)<=24:
            raise SourceError("invalid stadium identifier")
        venue=f"{int(key):02d}"
        races=stadium.get("races") if isinstance(stadium,dict) else None
        if not isinstance(races,dict):
            raise SourceError("race collection missing for stadium")
        report=[]
        for rk,r in sorted(races.items(),key=lambda x:int(x[0]) if str(x[0]).isdigit() else 99):
            if not str(rk).isdigit() or not 1<=int(rk)<=12 or not isinstance(r,dict):
                raise SourceError("invalid race number or object")
            rnum=int(rk)
            race_day=r.get("date")
            if race_day!=day.isoformat():
                raise SourceError("race date differs from requested day")
            if r.get("stadium_number") is not None and r.get("stadium_number")!=int(key):
                raise SourceError("stadium number mismatch")
            if r.get("race_number") is not None and r.get("race_number")!=rnum:
                raise SourceError("race number mismatch")
            participants=r.get("racers")
            if not isinstance(participants,dict):
                raise SourceError("race racers missing")
            preview=r.get("preview") if isinstance(r.get("preview"),dict) else {}
            preview_racers=preview.get("racers") or {}
            if not isinstance(preview_racers,dict):
                raise SourceError("preview racers must be an object")
            result=r.get("result") if isinstance(r.get("result"),dict) else {}
            result_racers=result.get("racers") or {}
            if not isinstance(result_racers,dict):
                raise SourceError("result racers must be an object")
            boats=[]
            motors_seen=set()
            for b in range(1,7):
                data=participants.get(str(b))
                if data is None:
                    continue
                if not isinstance(data,dict):
                    raise SourceError("bad racer object")
                lane=_int(data.get("entry_number",b),"boat lane",1,6)
                if lane!=b:
                    raise SourceError("racer lane/key mismatch")
                racer=_int(data.get("number"),"racer registration",1000,9999)
                motor=_int(data.get("motor_number"),"motor number",1,999)
                if motor in motors_seen:
                    raise SourceError("multiple boats use the same motor in a single race")
                motors_seen.add(motor)
                p=preview_racers.get(str(b)) or {}
                o=result_racers.get(str(b)) or {}
                if not isinstance(p,dict) or not isinstance(o,dict):
                    raise SourceError("bad preview/result racer object")
                if p.get("entry_number") is not None and p["entry_number"]!=b:
                    raise SourceError("preview boat number mismatch")
                if o.get("entry_number") is not None and o["entry_number"]!=b:
                    raise SourceError("result boat number mismatch")
                actual_result_course=o.get("course_number")
                if actual_result_course is not None:
                    _int(actual_result_course,"actual course",1,6)
                boat=dict(lane=b,racer_registration_id=str(racer),name=data.get("name"),
                    motor_no=motor,
                    motor_top2_rate=data.get("motor_top_2_percent"),
                    average_st=data.get("average_start_timing"),
                    preview_course=p.get("course_number"),preview_st=p.get("start_timing"),
                    display_time=p.get("exhibition_time"),
                    # This API does not document original lap/turn/straight metrics.
                    original_lap=None,original_turn=None,original_straight=None,
                    result_course=actual_result_course,result_st=o.get("start_timing"),
                    finish=o.get("place_number"),
                    original_exhibition_status="NOT_IN_PROVIDER_SCHEMA")
                boats.append(boat)
            if not boats:
                continue
            report.append(dict(race_id=f"{day.strftime('%Y%m%d')}-{venue}-{rnum:02d}",
                closed_at=r.get("closed_at"),boats=boats,
                boat_count=len(boats),
                result_available=bool(result_racers),
                preview_available=bool(preview_racers),
                weather_preview={
                    "wind_speed":preview.get("wind_speed"),
                    "wind_direction_number":preview.get("wind_direction_number"),
                    "wave_height":preview.get("wave_height")},
                source_status="UNOFFICIAL_NOT_OFFICIAL_VERIFIED"))
        if report:
            motor_set=sorted({b["motor_no"] for x in report for b in x["boats"]})
            venues.append(dict(venue=venue,listed_motor_numbers=motor_set,
                               motor_scope="TODAY_PROGRAMS_ONLY_NOT_ALL_ACTIVE_MOTORS",
                               race_count=len(report),races=report))
    if not venues:
        raise SourceError("no races in public provider data")
    n_races=sum(len(v["races"]) for v in venues)
    n_complete=sum(r["boat_count"]==6 for v in venues for r in v["races"])
    n_previews=sum(r["preview_available"] for v in venues for r in v["races"])
    n_results=sum(r["result_available"] for v in venues for r in v["races"])
    return dict(date_jst=day.isoformat(),source_url=source_url,
                source_sha256=source_sha256,first_observed_at=asof,
                upstream_published_at=None,
                provider="UNOFFICIAL_BOATRACE_OPEN_API",
                official_result_verified=False,
                provider_rights_require_separate_review=True,
                original_exhibition_supported=False,
                current_motor_cycle_known=False,
                nationwide_active_motor_inventory_complete=False,
                status="UNOFFICIAL_PARTIAL_FEATURES",
                venues_with_races=len(venues),
                races=n_races,complete_six_boat_races=n_complete,
                previews=n_previews,results=n_results,venues=venues)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--date",required=True,help="YYYY-MM-DD in JST")
    p.add_argument("--source-file",type=Path,help="saved provider JSON for offline parsing")
    p.add_argument("--fetch",action="store_true",help="one explicit network GET")
    p.add_argument("--probe-only",action="store_true",help="GET once; emit metadata only, no provider data")
    p.add_argument("--ack-provider-terms",action="store_true",
                   help="operator confirms lawful intended use and provider terms")
    p.add_argument("--output",type=Path,default=Path("public-day-report.json"))
    a=p.parse_args()
    try:
        day=date.fromisoformat(a.date)
        if int(bool(a.source_file))+int(a.fetch or a.probe_only)!=1:
            raise SourceError("provide exactly one of --source-file, --fetch, --probe-only")
        if a.source_file:
            blob=a.source_file.read_bytes()
            received=datetime.now(timezone.utc).isoformat(timespec="seconds")
            meta=dict(url=endpoint(day),sha256=hashlib.sha256(blob).hexdigest(),
                      first_observed_at=received)
        else:
            blob,meta=fetch_one_day(day,permitted=a.ack_provider_terms,
                                    probe_only=a.probe_only)
        report=normalize(blob,day=day,received_at=meta["first_observed_at"],
                         source_url=meta["url"],source_sha256=meta["sha256"])
        if a.probe_only:
            print(json.dumps({k:v for k,v in report.items() if k!="venues"},
                             ensure_ascii=False,indent=2))
            return
        if not a.ack_provider_terms:
            raise SourceError("cannot store derived provider results without confirmed source use rights")
        a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(f"{report['status']}: {report['venues_with_races']} venue(s), "
              f"{report['races']} races, {report['complete_six_boat_races']} complete")
    except (SourceError,ValueError,KeyError,OSError,TypeError) as exc:
        print("SAFE_STOP: "+str(exc),file=sys.stderr)
        raise SystemExit(2)


if __name__=="__main__":
    main()
