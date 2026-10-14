"""Single-day official B archive structural E2E audit without republishing rows.

This is an explicit, bounded integrity check. It never persists raw archive,
extracted text, names, registration IDs or race rows. It does not grant rights
to use the extracted content in a public-facing application.
"""
from __future__ import annotations
import argparse
from datetime import date
import json
import sys

from .core import SourceError
from .official_daily_verify import fetch_and_parse


def audit(day: date) -> dict:
    summary = fetch_and_parse(day, "B", include_rows=False)
    if summary.get("kind") != "B" or summary.get("date_jst") != day.isoformat():
        raise SourceError("official B identity mismatch")
    if summary.get("structural_entries") != summary.get("races", 0) * 6:
        raise SourceError("official B contains incomplete six-boat races")
    if summary.get("venue_count", 0) < 1 or summary["venue_count"] > 24:
        raise SourceError("invalid official B venue count")
    return {"date_jst": summary["date_jst"], "kind": "B",
            "archive_sha256": summary["download_sha256"],
            "extracted_sha256": summary["extracted_text_sha256"],
            "retrieved_at": summary["retrieved_at"],
            "venues": summary["venue_count"], "races": summary["races"],
            "boats": summary["structural_entries"],
            "result": "STRUCTURAL_E2E_PASS_NOT_REPUBLICATION_PERMISSION"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--date",required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(audit(date.fromisoformat(args.date)),ensure_ascii=False,indent=2))
    except (SourceError,ValueError,TypeError) as exc:
        print("SAFE_STOP: "+str(exc),file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
