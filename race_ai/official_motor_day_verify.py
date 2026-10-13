"""One-day official B motor extraction smoke, no copied B archive output."""
from __future__ import annotations
import argparse
from datetime import date,datetime,timezone
import hashlib
import json
import sys
from urllib import request,error,parse
from .core import SourceError, parse_b
from .official_archive_probe import official_url,inspect_lzh,StrictRedirect,MAX_ARCHIVE_BYTES,HOST
from .official_lzh_extract import extract_daily_lzh
from .official_b_motors import parse_b_motors


def verify(day:date, sample_venue:str|None=None,sample_race:int=1)->dict:
    url=official_url(day,"B")
    req=request.Request(url,headers={"User-Agent":"RACE-AI-official-motor-verify/0.13"})
    try:
        with request.build_opener(StrictRedirect).open(req,timeout=25) as response:
            if parse.urlsplit(response.geturl()).netloc!=HOST:
                raise SourceError("unexpected official host")
            raw=response.read(MAX_ARCHIVE_BYTES+1)
    except (TimeoutError,error.URLError) as exc:
        raise SourceError(f"official B unavailable: {type(exc).__name__}") from exc
    info=inspect_lzh(raw)
    text=extract_daily_lzh(raw,'B'+day.strftime('%y%m%d')+'.TXT')
    parsed=parse_b(text,day.isoformat())
    motors=parse_b_motors(text,day.isoformat())
    if len(parsed)!=len(motors):
        raise SourceError("motor parse count differs from B boat count")
    counts={}
    for x in motors:
        item=counts.setdefault(x["venue"],dict(boats=0,races=set(),motors=set()))
        item["boats"]+=1
        item["races"].add(x["race_id"])
        item["motors"].add(x["motor_no"])
    for venue,v in counts.items():
        # Some riders appear in multiple races; avoid mistaking
        # allocations-per-race for distinct active motors.
        if len(v["motors"])<6:
            raise SourceError("too few unique motors for an actual venue")
    summary=dict(day_jst=day.isoformat(),source_kind="OFFICIAL_B",
        source_url=url,archive_sha256=info["sha256"],
        extracted_text_sha256=hashlib.sha256(text).hexdigest(),
        verified_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        assigned_boat_rows=len(motors),races=len({x["race_id"] for x in motors}),
        venues=len(counts), venue_counts={
          k:dict(races=len(v["races"]),boaters=v["boats"],distinct_active_motor_numbers_seen=len(v["motors"]))
          for k,v in sorted(counts.items())},
        race_motor_reuse_contradictions=0,
        motor_usage_period_verified=False,entire_active_motor_inventory_verified=False,
        official_race_card_spotcheck_completed=False,
        historical_previous_rider_join_completed=False,
        original_exhibition_retrieved=False,
        source_published_at=None,status="OFFICIAL_B_MOTOR_COLUMNS_STRUCTURAL_CHECK_ONLY")
    if sample_venue is not None:
        rid=f'{day.strftime("%Y%m%d")}-{sample_venue}-{sample_race:02d}'
        sample=[dict(lane=x["lane"],motor_no=x["motor_no"],
                     motor_top2_rate=x["motor_top2_rate"],
                     boat_no=x["boat_no"]) for x in motors if x["race_id"]==rid]
        summary["sample_race_id"]=rid
        summary["sample_source_boats"]=sample
        if not sample:
            summary["sample_validation"]="REQUESTED_RACE_NOT_HELD"
        else:
            summary["sample_validation"]="B_SOURCE_ONLY_NEEDS_OFFICIAL_RACE_CARD_CROSSCHECK"
    return summary


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--date",required=True)
    p.add_argument("--venue",default="19")
    p.add_argument("--race",type=int,default=1)
    p.add_argument("--output",help="write derived metadata-only JSON snapshot")
    a=p.parse_args()
    try:
        result=verify(date.fromisoformat(a.date),a.venue,a.race)
        rendered=json.dumps(result,ensure_ascii=False,indent=2)
        if a.output:
            from pathlib import Path
            Path(a.output).write_text(rendered+"\n",encoding="utf-8")
        print(rendered)
    except (SourceError,ValueError,TypeError) as exc:
        print("SAFE_STOP: "+str(exc),file=sys.stderr)
        raise SystemExit(2)

if __name__=="__main__":
    main()
