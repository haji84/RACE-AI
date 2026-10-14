"""Evidence contract for a real official HTML six-boat reconciliation.

The actual captured HTML bytes must be supplied by a separately authorized
worker. No scraping, network access or source-rights claims are performed here.
"""
from __future__ import annotations
from datetime import date
import hashlib
import re
from .core import SourceError
from .venue_result_bridge import parse_and_reconcile


def verify_real_html(*, html_bytes: bytes, source_url: str, day: date,
                     race_no: int, table_index: int, column_map: dict,
                     entries: list[dict], captured_at: str,
                     expected_sha256: str, reviewed_by: str) -> dict:
    if not isinstance(html_bytes,bytes) or not html_bytes:
        raise SourceError("real HTML bytes required")
    if not re.fullmatch(r"[0-9a-f]{64}",expected_sha256):
        raise SourceError("source SHA-256 required")
    actual=hashlib.sha256(html_bytes).hexdigest()
    if actual!=expected_sha256:
        raise SourceError("HTML evidence SHA mismatch")
    if not reviewed_by:
        raise SourceError("independent source review required")
    try:
        html=html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError("HTML charset must be decoded by approved collector") from exc
    result=parse_and_reconcile(html,source_url=source_url,day=day,race_no=race_no,
        column_map=column_map,table_index=table_index,entries=entries,
        captured_at=captured_at,independently_verified=True)
    return {"race_id":f"{day:%Y%m%d}-18-{race_no:02d}",
            "source_sha256":actual,"reviewed_by":reviewed_by,
            "matched_entries":len(result["entries"]),
            "actual_course_status":result["actual_course_status"],
            "status":"EVIDENCE_MAPPED_STRUCTURAL_JOIN_NOT_PUBLICATION_PERMISSION"}
