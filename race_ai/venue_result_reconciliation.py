"""Reconcile an independently verified result snapshot with race entrants.

This is an offline join, not a result-page scraper. Finish positions and
actual courses must come from verified official result evidence, not estimates.
"""
from __future__ import annotations
from datetime import date
from .core import SourceError


def reconcile_results(entries: list[dict], results: list[dict], *,
                      day: date, venue: str="18") -> dict:
    prefix=f"{day:%Y%m%d}-{venue}-"
    entry_map={}
    for entry in entries:
        key=(entry.get("race_id"),entry.get("lane"))
        if not isinstance(key[0],str) or not key[0].startswith(prefix) or key in entry_map:
            raise SourceError("invalid or duplicate entry")
        entry_map[key]=entry
    if not entry_map:
        raise SourceError("no entries")
    result_map={}
    for result in results:
        key=(result.get("race_id"),result.get("lane"))
        if key not in entry_map or key in result_map:
            raise SourceError("unknown or duplicate result lane")
        if result.get("verified_official") is not True:
            raise SourceError("result not independently verified")
        if not result.get("source_url","").startswith("https://") or not result.get("captured_at"):
            raise SourceError("missing result provenance")
        if result.get("racer_registration_id")!=entry_map[key].get("racer_registration_id"):
            raise SourceError("racer identity mismatch")
        finish=result.get("finish")
        course=result.get("actual_course")
        if finish is not None and (type(finish) is not int or not 1<=finish<=6):
            raise SourceError("invalid finish")
        if course is not None and (type(course) is not int or not 1<=course<=6):
            raise SourceError("invalid actual course")
        result_map[key]=result
    if len(result_map)!=len(entry_map):
        raise SourceError("incomplete results coverage")
    output=[]
    for key,entry in sorted(entry_map.items()):
        result=result_map[key]
        output.append({**entry,"finish":result.get("finish"),
                       "actual_course":result.get("actual_course"),
                       "result_source_url":result["source_url"],
                       "result_captured_at":result["captured_at"]})
    return {"date_jst":day.isoformat(),"venue":venue,"entries":output,
            "status":"RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED"}
