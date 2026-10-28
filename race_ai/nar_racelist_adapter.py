"""Offline NAR race-list ZIP/CSV index reader; no network or license grant.

Accepts only the four documented initial racelist columns, never odds,
finish position, official refunds or post-event attributes as forecasts.
Sales cutoff is UNKNOWN even if scheduled start is supplied.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,os,re,sys
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile,BadZipFile
from .operator_export_intake import IntakeError,SCHEMA,MAX_BYTES,transform,_dt

NAR_SOURCE="https://www.keiba.go.jp/"
HEADER=("競馬場","競走年月日","レース番号","発走時刻")
MAX_RACES=1000

def _load_racelist_bytes(path):
    with Path(path).open("rb") as stream:
        data=stream.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:
        raise IntakeError("local NAR file exceeds 4 MiB")
    if str(path).lower().endswith(".zip"):
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                matches=[m for m in archive.infolist() if not m.is_dir()
                         and re.fullmatch(r"\d{6,8}_racelist\.csv",m.filename)]
                if len(matches)!=1:
                    raise IntakeError("exactly one NAR racelist member required")
                info=matches[0]
                if info.file_size>MAX_BYTES or info.flag_bits & 1:
                    raise IntakeError("oversized or encrypted ZIP member")
                with archive.open(info) as reader:
                    raw=reader.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES:
                    raise IntakeError("decompressed file too large")
                return raw
        except (BadZipFile,RuntimeError) as exc:
            raise IntakeError("invalid ZIP container") from exc
    if not re.fullmatch(r"\d{6,8}_racelist\.csv",Path(path).name):
        raise IntakeError("not a NAR racelist CSV filename")
    return data

def parse_racelist(data,captured_at,rights_ref):
    _dt(captured_at,"captured_at")
    if not isinstance(rights_ref,str) or not rights_ref.strip() or len(rights_ref)>1024:
        raise IntakeError("source_rights_ref required, not a license grant")
    try:
        text=data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:text=data.decode("cp932")
        except UnicodeDecodeError as exc:
            raise IntakeError("unknown CSV encoding") from exc
    reader=csv.reader(io.StringIO(text,newline=""),strict=True)
    first=next(reader,None)
    if first is None:
        raise IntakeError("empty racelist")
    # NAR documentation specifies column POSITIONS, not that CSVs contain a
    # header row. Support either a verified header or documented positional
    # data. Reject other text; do not infer arbitrary column mappings.
    has_header=tuple(cell.strip() for cell in first[:4]) == HEADER
    if not has_header and (len(first)<4 or not re.fullmatch(r"\d{8}",first[1].strip())):
        raise IntakeError("NAR racelist header/positional schema mismatch")
    day=None;entries=[]
    for row in (reader if has_header else __import__("itertools").chain([first],reader)):
        if not row or not any(v.strip() for v in row):continue
        if len(row)<4:raise IntakeError("missing racelist columns")
        venue,raw_date,n,scheduled=[v.strip() for v in row[:4]]
        if not venue or ":" in venue or len(venue)>128:
            raise IntakeError("invalid venue")
        if not re.fullmatch(r"\d{8}",raw_date):
            raise IntakeError("invalid event date")
        try:dt=datetime.strptime(raw_date,"%Y%m%d")
        except ValueError as exc:raise IntakeError("invalid event date") from exc
        this_day=dt.strftime("%Y-%m-%d")
        if day is None:day=this_day
        if day!=this_day:raise IntakeError("mixed event dates")
        if not n.isascii() or not n.isdigit() or not 1<=int(n)<=99:
            raise IntakeError("invalid race number")
        if not re.fullmatch(r"\d{4}",scheduled) or int(scheduled[:2])>23 or int(scheduled[2:])>59:
            raise IntakeError("invalid scheduled start")
        entries.append({"sport":"horse_local","venue":venue,"race_no":int(n),
                        "sales_cutoff_at":None,"offering_status":"UNKNOWN"})
        if len(entries)>MAX_RACES:raise IntakeError("too many races")
    if not entries:raise IntakeError("empty racelist")
    return {"schema":SCHEMA,"event_date_jst":day,"source_ref":NAR_SOURCE,
            "source_rights_ref":rights_ref,"captured_at":captured_at,"races":entries}

def main(argv=None):
    p=argparse.ArgumentParser(description="Offline NAR CSV/ZIP -> AUDIT_ONLY")
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--captured-at",required=True)
    p.add_argument("--source-rights-ref",required=True)
    a=p.parse_args(argv)
    try:
        raw=_load_racelist_bytes(a.input)
        manifest=parse_racelist(raw,a.captured_at,a.source_rights_ref)
        result=transform(manifest,hashlib.sha256(raw).hexdigest())
        with Path(a.output).open("x",encoding="utf-8") as stream:
            json.dump(result,stream,ensure_ascii=False,sort_keys=True,allow_nan=False)
            stream.write("\n");stream.flush();os.fsync(stream.fileno())
        print("NAR_AUDIT_ONLY_CREATED races="+str(len(result["records"])))
        return 0
    except (OSError,ValueError,TypeError,csv.Error) as exc:
        print("NAR_LOCAL_IMPORT_REJECTED: "+str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
