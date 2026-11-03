"""Official BOAT RACE public fact observation -> private AUDIT_ONLY ledger.

This is *not* a Web scraper or a prediction-feature normalizer. It accepts
a one-race, human/web-reader observed factual record without auto-contacting
the provider. Never upgrades a claimed time, model feature or source license.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qsl,urlsplit
import argparse,hashlib,json,re,sys

from .operator_export_intake import IntakeError,transform,SCHEMA

OBS_SCHEMA="RACE_AI_OFFICIAL_BOAT_FACT_OBSERVATION_V1"
MAX=16_384
JST=timezone(timedelta(hours=9))
REQUIRED={"schema","event_date_jst","venue_jcd","race_no",
          "scheduled_sales_cutoff_at","observed_at_claimed",
          "official_racelist_url","official_venue_url",
          "entrant_registration_numbers","event_kind",
          "race_distance_m","source_access_basis"}

def _timestamp(s):
    if not isinstance(s,str):
        raise IntakeError("timestamp required")
    try:d=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError as e:raise IntakeError("invalid timestamp") from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise IntakeError("timezone offset required")
    return d

def _source_url(value):
    if not isinstance(value,str) or len(value)>500:
        raise IntakeError("official source URL missing")
    u=urlsplit(value)
    if (u.scheme!="https" or u.hostname not in {"www.boatrace.jp","boatrace.jp"}
        or u.path!="/owpc/pc/race/racelist" or u.username or u.password
        or u.fragment or u.port not in (None,443)):
        raise IntakeError("only exact BOAT RACE official source permitted")
    args=parse_qsl(u.query,keep_blank_values=True)
    if len(args)!=3 or set(k for k,_ in args)!={"hd","jcd","rno"}:
        raise IntakeError("official URL must carry hd, jcd, rno once")
    return dict(args)

def convert(observation):
    if not isinstance(observation,dict) or set(observation)!=REQUIRED:
        raise IntakeError("invalid official observation schema")
    if observation["schema"]!=OBS_SCHEMA:
        raise IntakeError("unexpected schema")
    day=observation["event_date_jst"]
    if not isinstance(day,str) or not re.fullmatch(r"\d{4}-\d\d-\d\d",day):
        raise IntakeError("date format invalid")
    try:canonical=datetime.fromisoformat(day).date().isoformat()
    except ValueError as e:raise IntakeError("invalid date") from e
    if day!=canonical:raise IntakeError("non-canonical event day")
    jcd=observation["venue_jcd"]
    race_no=observation["race_no"]
    if not isinstance(jcd,str) or not re.fullmatch(r"0[1-9]|1[0-9]|2[0-4]",jcd):
        raise IntakeError("invalid venue code")
    if type(race_no) is not int or not 1<=race_no<=12:
        raise IntakeError("invalid boat race number")
    args=_source_url(observation["official_racelist_url"])
    if args!={"hd":day.replace("-",""),"jcd":jcd,"rno":str(race_no)}:
        raise IntakeError("source URL and race identity mismatch")
    venue_source=observation["official_venue_url"]
    u=urlsplit(venue_source) if isinstance(venue_source,str) else None
    if (u is None or u.scheme!="https" or u.hostname not in
        {"boatrace-biwako.jp","www.boatrace-biwako.jp"}
        or u.username or u.password or u.fragment or u.port not in (None,443)
        or not u.path.startswith("/sp/") or u.query or jcd!="11"):
        raise IntakeError("independent venue site not grounded")
    cutoff=_timestamp(observation["scheduled_sales_cutoff_at"])
    observed=_timestamp(observation["observed_at_claimed"])
    if cutoff.astimezone(JST).date().isoformat()!=day:
        raise IntakeError("reported cutoff not on JST race day")
    if observed>=cutoff:
        raise IntakeError("observation claims occur after scheduled cutoff")
    if observation["event_kind"]!="予選" or observation["race_distance_m"]!=1800:
        raise IntakeError("observed race type/distance unsupported")
    numbers=observation["entrant_registration_numbers"]
    if (not isinstance(numbers,list) or len(numbers)!=6 or
        any(type(v) is not int or v<1 or v>9999 for v in numbers)
        or len(set(numbers))!=6):
        raise IntakeError("six distinct actual registration numbers required")
    if observation["source_access_basis"]!="PUBLIC_WEB_VIEW_ONLY_NOT_REVIEWED_FOR_AUTOMATED_FETCH":
        raise IntakeError("no inherited source authorization")
    venue="boatrace-jcd-"+jcd
    record={
        "schema":SCHEMA,"event_date_jst":day,
        "source_ref":observation["official_racelist_url"],
        "source_rights_ref":"PUBLIC_FACT_VIEW_ONLY_NOT_FETCH_APPROVAL",
        "captured_at":observation["observed_at_claimed"],
        "races":[{"sport":"boat","venue":venue,
                  "race_no":race_no,
                  "sales_cutoff_at":observation["scheduled_sales_cutoff_at"],
                  "offering_status":"UNKNOWN"}]}
    digest=hashlib.sha256(json.dumps(observation,sort_keys=True,
                         ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    ledger=transform(record,digest)
    ledger["actual_public_observation"]={
        "status":"REAL_SOURCE_FACTS_REPORTED_NOT_AUTHENTICATED",
        "source_observation_sha256":digest,
        "race_id":f"boat:{day}:{venue}:{race_no}",
        "entrant_registration_numbers":numbers,
        "scheduled_sales_cutoff_at":observation["scheduled_sales_cutoff_at"],
        "official_racelist_url":observation["official_racelist_url"],
        "official_venue_url":observation["official_venue_url"],
        "event_kind":observation["event_kind"],
        "race_distance_m":observation["race_distance_m"],
        "source_access_approved_for_auto_fetch":False,
        "capture_time_independently_proven":False,
        "race_roster_authoritative_snapshot_verified":False,
        "actual_sales_cutoff_verified":False,
        "feature_normalization_completed":False,
        "prediction_generated":False,
        "external_forecast_freeze_verified":False,
        "result_verified":False,
        "eligible_for_kpi":False,
        "missing_model_features":"REQUIRED_NOT_OBSERVED",
    }
    return ledger

def _no_dupes(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise IntakeError("duplicate input field")
        out[k]=v
    return out

def main(argv=None):
    p=argparse.ArgumentParser(description="One observed BOAT RACE official fact snapshot -> AUDIT_ONLY")
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args(argv)
    try:
        with Path(a.input).open("rb") as f:data=f.read(MAX+1)
        if len(data)>MAX:raise IntakeError("observation too large")
        observed=json.loads(data,object_pairs_hook=_no_dupes)
        output=convert(observed)
        destination=Path(a.output).absolute()
        if any((q/".git").exists() for q in (destination.parent,*destination.parent.parents)):
            raise IntakeError("do not write the data audit to a public git checkout")
        with destination.open("x",encoding="utf-8") as stream:
            json.dump(output,stream,ensure_ascii=False,sort_keys=True)
            stream.write("\n")
        print("OFFICIAL_FACTS_AUDIT_ONLY race="+output["actual_public_observation"]["race_id"])
        return 0
    except (OSError,ValueError,TypeError) as exc:
        print("OFFICIAL_FACTS_REJECTED: "+str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":raise SystemExit(main())
