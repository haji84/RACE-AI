"""NAR native *daily race ZIP* audit bridge. Offline by design.

The user/provider must supply the ZIP via an independently permitted channel.
No HTTP, schedule invention, cutoff inference, real freeze, model training,
prediction scoring, settlement or raw data publication.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from zipfile import ZipFile, BadZipFile
from .operator_export_intake import IntakeError, MAX_BYTES, transform
from .nar_racelist_adapter import parse_racelist
from .nar_payback_adapter import parse_payback

MAX_ZIP_BYTES=8*1024*1024
MAX_MEMBER_BYTES=8*1024*1024
MAX_UNCOMPRESSED_TOTAL=18*1024*1024
ZIP_NAME=re.compile(r"(\d{8})_(\d{10,13})_race\.zip\Z")
MEMBER_TYPES=("racelist","horselist","payback")

def _members(zip_bytes, *, day):
    if not isinstance(zip_bytes, bytes) or len(zip_bytes)>MAX_ZIP_BYTES:
        raise IntakeError("NAR ZIP bytes must be bounded")
    try:
        with ZipFile(io.BytesIO(zip_bytes)) as archive:
            found={}
            total=0
            for info in archive.infolist():
                if info.is_dir():
                    continue
                # No ZIP path traversal, arbitrary extra exports, symlinks,
                # odds archives, duplicate names, encrypted/huge members.
                if "/" in info.filename or "\\" in info.filename or ".." in info.filename:
                    raise IntakeError("unexpected ZIP member path")
                match=re.fullmatch(r"(\d{8})_(racelist|horselist|payback)\.csv",info.filename)
                if not match or match.group(1)!=day:
                    raise IntakeError("unexpected ZIP member or mismatched day")
                kind=match.group(2)
                if kind in found or info.file_size>MAX_MEMBER_BYTES or info.flag_bits & 1:
                    raise IntakeError("duplicate, encrypted or oversized ZIP member")
                total+=info.file_size
                if total>MAX_UNCOMPRESSED_TOTAL:
                    raise IntakeError("ZIP aggregate decompression limit")
                with archive.open(info) as stream:
                    data=stream.read(MAX_MEMBER_BYTES+1)
                if len(data)!=info.file_size:
                    raise IntakeError("ZIP size mismatch")
                found[kind]=data
    except (BadZipFile,RuntimeError,EOFError) as exc:
        raise IntakeError("unreadable ZIP archive") from exc
    if "racelist" not in found:
        raise IntakeError("daily ZIP needs racelist")
    return found

def audit_daily_zip(zip_bytes, *, filename, captured_at, rights_ref):
    if not isinstance(filename,str):
        raise IntakeError("daily ZIP filename required")
    matched=ZIP_NAME.fullmatch(Path(filename).name)
    if not matched:
        raise IntakeError("official daily race ZIP filename required")
    rawday=matched.group(1)
    try:
        day=datetime.strptime(rawday,"%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise IntakeError("invalid ZIP date") from exc
    files=_members(zip_bytes,day=rawday)
    manifest=parse_racelist(files["racelist"],captured_at,rights_ref)
    if manifest["event_date_jst"]!=day:
        raise IntakeError("ZIP and race list date mismatch")
    ledger=transform(manifest,hashlib.sha256(files["racelist"]).hexdigest())
    payback=None
    if "payback" in files:
        payback=parse_payback(files["payback"],captured_at,rights_ref)
        if payback["event_date_jst"]!=day:
            raise IntakeError("ZIP and payout date mismatch")
    indexed={x["race_id"] for x in ledger["records"]}
    candidate_ids={x["race_id"] for x in payback["records"]} if payback else set()
    # Candidates remain UNVERIFIED and NEVER become an official result just
    # because the archive contains a payout row.
    return {
        "schema":"RACE_AI_NAR_DAILY_BUNDLE_AUDIT_V1",
        "status":"SOURCE_UNVERIFIED_OFFLINE_AUDIT_ONLY",
        "event_date_jst":day,
        "source_ref":"https://www.keiba.go.jp/",
        "source_rights_ref_claimed":rights_ref,
        "captured_at_claimed":captured_at,
        "source_rights_confirmed":False,
        "official_capture_time_proven":False,
        "complete_daily_coverage_proven":False,
        "official_sales_cutoff_proven":False,
        "external_pre_cutoff_freeze_proven":False,
        "official_result_finality_proven":False,
        "forecast_comparison_allowed":False,
        "model_training_eligible":False,
        "source_zip_sha256":hashlib.sha256(zip_bytes).hexdigest(),
        "members_sha256":{k:hashlib.sha256(v).hexdigest() for k,v in sorted(files.items())},
        "members_present":sorted(files),
        "daily_index":ledger,
        "payout_candidates":payback,
        "payout_unlisted_in_race_index":sorted(candidate_ids-indexed),
        "races_without_payout_candidate":sorted(indexed-candidate_ids),
    }

def _is_inside_git_worktree(path):
    p=path.parent.resolve()
    return any((q/".git").exists() for q in (p,*p.parents))

def main(argv=None):
    p=argparse.ArgumentParser(description="Locally provided official-layout ZIP -> audit-only")
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--captured-at",required=True)
    p.add_argument("--source-rights-ref",required=True)
    args=p.parse_args(argv)
    try:
        input_path=Path(args.input)
        with input_path.open("rb") as stream:
            raw=stream.read(MAX_ZIP_BYTES+1)
        result=audit_daily_zip(raw,filename=input_path.name,captured_at=args.captured_at,
                               rights_ref=args.source_rights_ref)
        dest=Path(args.output).absolute()
        if _is_inside_git_worktree(dest):
            raise IntakeError("do not store source-derived audit data in public Git checkout")
        payload=json.dumps(result,ensure_ascii=False,sort_keys=True,
                           allow_nan=False,separators=(",",":"))+"\n"
        with dest.open("x",encoding="utf-8") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        print("NAR_DAILY_AUDIT_ONLY races="+str(len(result["daily_index"]["records"]))+
              " payout_candidates="+str(len(result["payout_candidates"]["records"])
                                       if result["payout_candidates"] else 0))
        return 0
    except (OSError,ValueError,TypeError) as exc:
        print("NAR_DAILY_BUNDLE_REJECTED: "+str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
