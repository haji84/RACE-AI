"""Bridge parsed individual results to the existing verified-entry reconciler.

No actual-course guess. Result source provenance must be separately reviewed
before the adapter is called. This is not a web fetcher or a rights grant.
"""
from __future__ import annotations
from datetime import date
from .core import SourceError
from .venue_individual_result import parse_individual_result
from .venue_result_reconciliation import reconcile_results


def parse_and_reconcile(html: str, *, source_url: str, day: date,
                        race_no: int, column_map: dict, table_index: int,
                        entries: list[dict], captured_at: str,
                        independently_verified: bool) -> dict:
    if independently_verified is not True or not captured_at:
        raise SourceError("real source provenance not independently verified")
    parsed=parse_individual_result(html,source_url=source_url,day=day,
                                   race_no=race_no,column_map=column_map,
                                   table_index=table_index)
    normalized=[]
    for row in parsed["results"]:
        normalized.append({
            "race_id":row["race_id"],"lane":row["lane"],
            "racer_registration_id":row["racer_registration_id"],
            "finish":row["finish"],"actual_course":None,
            "verified_official":True,"source_url":source_url,
            "captured_at":captured_at
        })
    result=reconcile_results(entries,normalized,day=day)
    result["actual_course_status"]="UNKNOWN_REQUIRES_VERIFIED_START_ORDER"
    result["result_parser_status"]=parsed["status"]
    return result
