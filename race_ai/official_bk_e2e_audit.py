"""One-day B/K official archive audit, metadata only, no republishing.

An authorized operator may run this manually after reviewing source terms.
No automated polling, persistence of official rows, or Vercel upload.
"""
from __future__ import annotations
import argparse
from datetime import date
import json
import sys

from .core import SourceError
from .official_daily_verify import fetch_and_parse


def audit_pair(day: date) -> dict:
    results={}
    for kind in ("B","K"):
        report=fetch_and_parse(day,kind,include_rows=False)
        if report["date_jst"]!=day.isoformat() or report["kind"]!=kind:
            raise SourceError("B/K archive date or kind mismatch")
        if report["structural_entries"]!=report["races"]*6:
            raise SourceError("incomplete official six-boat structure")
        results[kind]={
            "archive_sha256":report["download_sha256"],
            "text_sha256":report["extracted_text_sha256"],
            "retrieved_at":report["retrieved_at"],
            "venue_count":report["venue_count"],
            "races":report["races"],
            "boats":report["structural_entries"],
            "status":report["status"]
        }
    return {"date_jst":day.isoformat(),"results":results,
            "verification":"STRUCTURAL_ONLY_NOT_PUBLICATION_PERMISSION"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--date",required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(audit_pair(date.fromisoformat(args.date)),ensure_ascii=False,indent=2))
    except (SourceError,ValueError,TypeError) as exc:
        print("SAFE_STOP: "+str(exc),file=sys.stderr)
        raise SystemExit(2)


if __name__=="__main__":
    main()
