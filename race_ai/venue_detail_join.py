"""Evidence-gated racer registration and motor join for a venue race list.

No guessing from names. Only same-day, same-race, same-lane records from an
independently verified source are accepted; conflicting names fail closed.
"""
from __future__ import annotations
from datetime import date, datetime
import math
import re
import unicodedata

from .core import SourceError


def canonical_name(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def join_verified_details(index: dict, details: list[dict], *, day: date) -> dict:
    if index.get("date_jst") != day.isoformat() or index.get("venue") != "18":
        raise SourceError("venue index day or venue mismatch")
    expected={}
    for race in index.get("races",[]):
        for boat in race["boats"]:
            key=(race["race_id"],boat["lane"])
            if key in expected:
                raise SourceError("duplicate venue lane")
            expected[key]=boat
    matched={}
    for row in details:
        key=(row.get("race_id"),row.get("lane"))
        if key not in expected or key in matched:
            raise SourceError("unknown or duplicate detail row")
        if row.get("verified_source") is not True:
            raise SourceError("detail source not independently verified")
        if not row.get("source_url","").startswith("https://") or not row.get("captured_at"):
            raise SourceError("detail provenance incomplete")
        registration=row.get("racer_registration_id")
        motor=row.get("motor_no")
        if not isinstance(registration,str) or not re.fullmatch(r"[0-9]{4}",registration):
            raise SourceError("invalid racer registration")
        if type(motor) is not int or not 1 <= motor <= 999:
            raise SourceError("invalid motor number")
        if row.get('boat_no') is not None and (type(row['boat_no']) is not int or not 1 <= row['boat_no'] <= 999):
            raise SourceError('invalid boat number')
        for field in ('average_st', 'national_win_rate', 'local_win_rate'):
            value = row.get(field)
            maximum = 1 if field == 'average_st' else 10
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum):
                raise SourceError('invalid racer measurement')
        if canonical_name(row.get("name")) != canonical_name(expected[key].get("name")):
            raise SourceError("racer name conflict")
        matched[key]=row
    if len(matched)!=len(expected):
        raise SourceError("detail coverage incomplete")
    output=[]
    for race in index["races"]:
        boats=[]
        closing_values = {matched[(race['race_id'], boat['lane'])].get('closed_at') for boat in race['boats']}
        if closing_values != {None}:
            if len(closing_values) != 1 or None in closing_values:
                raise SourceError('closing time conflicts across lanes')
            from zoneinfo import ZoneInfo
            try:
                closing = datetime.fromisoformat(next(iter(closing_values)))
                if closing.tzinfo is None or closing.astimezone(ZoneInfo('Asia/Tokyo')).date() != day:
                    raise ValueError()
            except (ValueError, TypeError):
                raise SourceError('closing time day invalid')
        for boat in race["boats"]:
            row=matched[(race["race_id"],boat["lane"])]
            additional = {key: row[key] for key in
                ('boat_no', 'average_st', 'national_win_rate', 'local_win_rate', 'entry_status') if key in row}
            boats.append({**boat,"racer_registration_id":row["racer_registration_id"],
                          "motor_no":row["motor_no"],
                          **additional,
                          "detail_source_url":row["source_url"],
                          "detail_captured_at":row["captured_at"]})
        output.append({**race,"boats":boats,"closed_at":next(iter(closing_values))})
    return {**index,"races":output,"detail_status":"ALL_SIX_LANES_EVIDENCE_JOINED",
            "redistribution_authorized":False}
