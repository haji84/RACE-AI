"""Authorized operator-only Vercel private Blob upload from a validated snapshot.

Uses the documented Vercel CLI. No background execution or web scraping.
Dry-run by default. CLI credentials must be configured outside the repository.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import argparse
import subprocess

from .day_feed_store import read_current_snapshot


def upload_day(store: Path, *, day: date, scope: str, execute: bool=False) -> dict:
    if not scope or any(c.isspace() for c in scope):
        raise ValueError("explicit Vercel scope required")
    snapshot=read_current_snapshot(store,today=day)
    if snapshot.get("date_jst")!=day.isoformat():
        raise ValueError("stale snapshot")
    path=store/(day.isoformat()+".json")
    args=["vercel","--scope",scope,"blob","put",str(path),"--access","private"]
    if not execute:
        return {"status":"DRY_RUN","date_jst":day.isoformat(),
                "source_file":str(path),"cloud_upload":False}
    proc=subprocess.run(args,capture_output=True,text=True,timeout=60,check=False)
    if proc.returncode!=0:
        raise RuntimeError("Vercel private Blob upload failed (see local CLI logs)")
    return {"status":"UPLOAD_COMMAND_SUCCEEDED_REQUIRES_BLOB_READBACK",
            "date_jst":day.isoformat(),"cloud_upload":True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--store",required=True)
    parser.add_argument("--date",type=date.fromisoformat,required=True)
    parser.add_argument("--scope",required=True)
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args()
    print(upload_day(Path(args.store),day=args.date,scope=args.scope,execute=args.execute))


if __name__=="__main__":
    main()
