"""Separate NAR POST-RACE payback CSV staging, never a forecast feature.

NAR's published payback layout is 54 columns; trifecta at columns 50..53.
Dead heats may produce multiple rows per race. Actual official release /
authenticity is NOT verified merely by parsing a locally supplied file.
Reference: https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf
"""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
import re

from .comprehensive_four_sport_models import digest, moment
from .nar_official_csv_adapter import (
    NarFormatError, MAX_BYTES, MAX_ROWS, _ymd, _nr
)
from .permissioned_source_delivery import PermissionPolicy

RESULT_SCHEMA = "RACE_AI_NAR_SETTLEMENT_STAGING_V1"
COLUMNS = 54


def _get_rows(data, *, encoding, has_header):
    if encoding not in ("cp932", "utf-8-sig") or type(has_header) is not bool:
        raise NarFormatError("explicit encoding and header mode required")
    if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
        raise NarFormatError("bounded payback CSV required")
    try:
        rows=list(csv.reader(io.StringIO(data.decode(encoding),newline=""),strict=True))
    except (UnicodeError, csv.Error) as exc:
        raise NarFormatError("payback CSV decoding invalid") from exc
    if not rows or len(rows) > MAX_ROWS or any(len(r)!=COLUMNS for r in rows):
        raise NarFormatError("payback CSV must use documented 54 columns")
    if has_header:
        if tuple(x.strip() for x in rows[0][:3]) != ("競馬場","競走年月日","レース番号"):
            raise NarFormatError("payback CSV header invalid")
        rows=rows[1:]
    elif rows[0][0].strip()=="競馬場":
        raise NarFormatError("unexpected payback header")
    return rows


def stage_nar_payback(payback_bytes, policy, *, at, observed_at,
                      source_ref, rights_ref, event_date_jst, venue,
                      race_no, scheduled_start_at, encoding, has_header):
    """Only after scheduled start, keep a separate unverified result event.

    Uses no odds or popularity for model selection and never changes a
    pre-cutoff forecast. Source verification is a separate acceptance gate.
    """
    if not isinstance(policy,PermissionPolicy):
        raise NarFormatError("reviewed independent source policy required")
    for purpose in ("analysis","private_storage","private_derived"):
        if not policy.authorize(source_ref,rights_ref,purpose):
            raise NarFormatError("SOURCE_PERMISSION_NOT_ADMITTED:"+purpose)
    try:
        now, observed, start = (moment(x) for x in (at,observed_at,scheduled_start_at))
    except (ValueError,TypeError) as exc:
        raise NarFormatError("timezone-aware result provenance required") from exc
    if not start <= observed <= now:
        raise NarFormatError("result cannot be observed before scheduled start or in future")
    if event_date_jst != _ymd(event_date_jst.replace("-","")):
        raise NarFormatError("invalid settlement race day")
    if type(race_no) is not int or not 1 <= race_no <= 99:
        raise NarFormatError("settlement race number invalid")
    selected=[]
    for row in _get_rows(payback_bytes,encoding=encoding,has_header=has_header):
        if (_ymd(row[1].strip())==event_date_jst and row[0].strip()==venue
            and _nr(row[2].strip())==race_no):
            selected.append(row)
    if not selected:
        raise NarFormatError("no matching payback rows: do not infer zero payouts")
    win=[]
    combos=set()
    for row in selected:
        parts=[p.strip() for p in row[49:52]]
        amount=row[52].strip()
        if all(not p for p in parts) and not amount:
            continue
        if not all(parts) or not amount or not re.fullmatch(r"\d+",amount):
            raise NarFormatError("incomplete trifecta settlement data")
        triple=tuple(_nr(x) for x in parts)
        if len(set(triple))!=3 or triple in combos:
            raise NarFormatError("duplicate/invalid official trifecta combination")
        if len(win) >= 20:
            raise NarFormatError("unexpected excessive dead-heat combinations")
        yen=int(amount)
        if not 1 <= yen <= 10**9:
            raise NarFormatError("trifecta payback amount out of range")
        combos.add(triple)
        win.append({"combination":list(triple),"official_stated_payback_yen":yen})
    event={
        "schema":RESULT_SCHEMA,
        "race_id":f"horse_local:{event_date_jst}:{venue}:{race_no}",
        "event_date_jst":event_date_jst,"venue":venue,"race_no":race_no,
        "scheduled_start_at":scheduled_start_at,
        "source_ref":source_ref,"source_rights_ref":rights_ref,
        "observed_at_claimed":observed_at,
        "source_payload_sha256":hashlib.sha256(payback_bytes).hexdigest(),
        "signed_review_policy_sha256":policy.document_sha256,
        "format_manual":"https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf",
        "winning_trifectas_reported":win,
        "dead_heat_multiple_combinations":len(win)>1,
        "race_outcome_status":"REPORTED_UNVERIFIED" if win else "NOT_EVALUABLE_UNKNOWN",
        "official_result_authenticated":False,
        "settlement_external_timestamp_attested":False,
        "forecast_changed":False,
        "may_count_in_hit_at_8":False,
        "result_revision_confirmed":False,
    }
    event["settlement_stage_sha256"]=digest(event)
    return event
