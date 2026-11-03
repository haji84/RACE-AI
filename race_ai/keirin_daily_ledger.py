"""Daily, bounded, non-sensitive KEIRIN discovery archive.

Each run fetches only one dated index page through keirin_discovery.get_single_day.
The output records ALL discovered race identities, including those lacking
source/forecast/result evidence. No result/odds/predictions are in this file.
This is not the completed all-race forecast->PDCA production system.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path

from .keirin_discovery import get_single_day, DiscoveryError

JST=timezone(timedelta(hours=9))


def daily_run(*, today=None, collector=get_single_day):
    if today is None:
        today=datetime.now(JST).date().isoformat()
    discovery=collector(today)
    rows=[{
        "race_id":r["race_id"],"event_date_jst":today,
        "venue_code":r["venue_code"],"race_no":r["race_no"],
        "stage":"DISCOVERED_ONLY","official_cutoff_at":None,
        "forecast_status":"NOT_GENERATED_INPUTS_UNVERIFIED",
        "result_status":"NOT_FETCHED",
        "hit8":None,"model_version":None,
    } for r in discovery["races"]]
    return {
        "schema":"RACE_AI_KEIRIN_ALL_DISCOVERED_RACES_LEDGER_V1",
        "event_date_jst":today,
        "discovered_count":len(rows),
        "source_url":discovery["source_url"],
        "source_sha256":discovery["source_sha256"],
        "race_ids":[r["race_id"] for r in rows],
        "records":rows,
        "national_coverage_verified":False,
        "private_forecasts_generated":0,
        "provider_result_final_verified":0,
        "official_model_hit8":None,
        "source_access_is_personal_research_only":True,
    }


def save_once(path,record):
    target=Path(path)
    if target.exists() or target.is_symlink():
        raise ValueError("IMMUTABLE_OUTPUT_EXISTS")
    target.parent.mkdir(parents=True,exist_ok=True)
    serialized=(json.dumps(record,sort_keys=True,
                           ensure_ascii=False,separators=(",",":"))+"\n").encode("utf-8")
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,"O_NOFOLLOW"):
        flags|=os.O_NOFOLLOW
    fd=os.open(str(target),flags,0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(serialized)
        f.flush()
        os.fsync(f.fileno())
    return len(serialized)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--day",help="YYYY-MM-DD; default current JST day")
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    try:
        obj=daily_run(today=args.day)
        size=save_once(args.output,obj)
        print(json.dumps({"schema":obj["schema"],"day":obj["event_date_jst"],
            "source_sha256":obj["source_sha256"],"discovered":obj["discovered_count"],
            "venue_count":len(set(r["venue_code"] for r in obj["records"])),
            "output_bytes":size,"forecast_generated":0,
            "official_hit8":None,"raw_source_saved":False},ensure_ascii=False))
        return 0
    except (DiscoveryError, OSError, ValueError):
        print('{"state":"DAILY_DISCOVERY_INCOMPLETE","forecasts_generated":0}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
