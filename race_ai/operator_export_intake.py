"""Offline, no-network race-index intake. No rights or pre-cutoff proof inferred."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

SPORTS = frozenset({"boat","keirin","autorace","horse_jra","horse_local"})
SCHEMA = "RACE_AI_OPERATOR_EXPORT_V1"
MAX_BYTES = 4 * 1024 * 1024
MAX_RACES = 1000
ALLOWED_STATUS = frozenset({"UNKNOWN","TRIFECTA_REPORTED","NO_TRIFECTA_REPORTED"})

class IntakeError(ValueError):
    pass

def _unique_pairs(pairs):
    result = {}
    for k,v in pairs:
        if k in result:
            raise IntakeError("duplicate JSON key")
        result[k] = v
    return result

def _dt(value,field):
    if not isinstance(value,str):
        raise IntakeError(field + " requires timezone timestamp")
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise IntakeError("invalid "+field) from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise IntakeError(field+" requires timezone offset")
    return d

def parse_file(path):
    with Path(path).open("rb") as stream:
        raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:
        raise IntakeError("export file exceeds 4 MiB")
    try:
        obj=json.loads(raw.decode("utf-8"),object_pairs_hook=_unique_pairs,
                       parse_constant=lambda x: (_ for _ in ()).throw(IntakeError("NaN/Infinity forbidden")))
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise IntakeError("invalid UTF-8 JSON") from exc
    return obj,hashlib.sha256(raw).hexdigest()

def transform(export, source_sha):
    """Supplied normalized metadata -> AUDIT_ONLY ledger, never official real predictions."""
    if not isinstance(export,dict) or set(export)!={
            "schema","event_date_jst","source_ref","source_rights_ref","captured_at","races"}:
        raise IntakeError("unexpected export fields")
    if export["schema"]!=SCHEMA:
        raise IntakeError("unsupported export schema")
    day=export["event_date_jst"]
    if not isinstance(day,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day):
        raise IntakeError("event_date_jst invalid")
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise IntakeError("event_date_jst impossible") from exc
    for field in ("source_ref","source_rights_ref"):
        s=export[field]
        if not isinstance(s,str) or not s.strip() or len(s)>1024:
            raise IntakeError(field+" reference required")
    _dt(export["captured_at"],"captured_at")
    entries=export["races"]
    if not isinstance(entries,list) or not 1<=len(entries)<=MAX_RACES:
        raise IntakeError("bounded nonempty race list required")
    seen=set()
    rows=[]
    for rec in entries:
        if not isinstance(rec,dict) or set(rec)!={
                "sport","venue","race_no","sales_cutoff_at","offering_status"}:
            raise IntakeError("unexpected race fields / odds and results prohibited")
        sport,venue,n=rec["sport"],rec["venue"],rec["race_no"]
        if sport not in SPORTS or not isinstance(venue,str) or not venue.strip() or len(venue)>128 or ":" in venue:
            raise IntakeError("invalid sport or venue")
        if type(n) is not int or not 1<=n<=99:
            raise IntakeError("invalid race number")
        key=(sport,venue,n)
        if key in seen:
            raise IntakeError("duplicate race identity")
        seen.add(key)
        cutoff=rec["sales_cutoff_at"]
        if cutoff is not None:
            d=_dt(cutoff,"sales_cutoff_at")
            if d.astimezone(timezone(timedelta(hours=9))).date().isoformat()!=day:
                raise IntakeError("cutoff date differs from JST race date")
        if rec["offering_status"] not in ALLOWED_STATUS:
            raise IntakeError("untrusted offering status")
        rows.append({"race_id":f"{sport}:{day}:{venue}:{n}","sport":sport,
                     "venue":venue,"race_no":n,"sales_cutoff_at":cutoff,
                     "cutoff_verified":False,"offering_status":rec["offering_status"],
                     "prediction":None,"no_forecast_reason":"EXPORT_UNVERIFIED_AND_NOT_FROZEN",
                     "result":None})
    rows.sort(key=lambda x:(x["sport"],x["venue"],x["race_no"]))
    return {"schema":"RACE_AI_FORECAST_AUDIT_V1","dataset_status":"AUDIT_ONLY",
            "event_date_jst":day,"records":rows,
            "intake_meta":{"scope":"OPERATOR_SUPPLIED_OFFLINE_NOT_ADMITTED",
             "source_ref":export["source_ref"],"source_rights_ref":export["source_rights_ref"],
             "source_sha256":source_sha,"captured_at_claimed":export["captured_at"],
             "captured_at_independently_proven":False,
             "permission_independently_verified":False,
             "source_is_officially_complete":False,
             "real_forecasts_verified":False,
             "missing_sports_not_proven_no_meeting":sorted(SPORTS-{x["sport"] for x in rows})}}

def main(argv=None):
    parser=argparse.ArgumentParser(description="Local index -> AUDIT_ONLY; no network")
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    a=parser.parse_args(argv)
    try:
        export,sha=parse_file(a.input)
        report=transform(export,sha)
        rendered=json.dumps(report,ensure_ascii=False,sort_keys=True,
                            separators=(",",":"),allow_nan=False)
        with Path(a.output).open("x",encoding="utf-8") as f:
            f.write(rendered+"\n")
            f.flush()
            os.fsync(f.fileno())
        print("AUDIT_ONLY_CREATED races="+str(len(report["records"])))
        return 0
    except (OSError,IntakeError,TypeError,ValueError) as exc:
        print("OFFLINE_INTAKE_REJECTED: "+str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
