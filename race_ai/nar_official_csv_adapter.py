"""Offline, purpose-gated NAR official CSV format adapter.

Parses the documented 66-column racelist and 36-column horselist layout.
Never downloads from NAR. Never imports current-race finish, odds, popularity,
payback, sectional or corner positions as pre-race facts. Neither the
download ZIP timestamp nor a caller-supplied observation time authenticates
pre-cutoff acquisition. A horse name is NOT a durable horse identifier.
Reference format: https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import re

from .comprehensive_four_sport_models import COMMON_REQUIRED, SPORT_REQUIRED, digest, moment
from .permissioned_source_delivery import PermissionPolicy, SourceDeliveryError

JST = timezone(timedelta(hours=9))
STAGE_SCHEMA = "RACE_AI_NAR_CSV_PREFLIGHT_V1"
DOC_URL = "https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf"
MAX_BYTES = 4_000_000
MAX_ROWS = 10000
RACELIST_COLUMNS = 66
HORSELIST_COLUMNS = 36
# As documented by NAR (2026 manual). These are one-based column indexes.
# Racelist 34..66 includes post-race sectionals/corner order, not forecast inputs.
# Horselist 32..36 includes FINISH, race time, margin, closing 3F, POPULARITY.
POST_RACE_RACELIST_START = 34
POST_RACE_HORSELIST_START = 32


class NarFormatError(SourceDeliveryError):
    pass


def _rows(raw, *, kind, encoding, header):
    required = RACELIST_COLUMNS if kind == "racelist" else HORSELIST_COLUMNS
    if encoding not in ("utf-8-sig", "cp932"):
        raise NarFormatError("explicit supported encoding required")
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise NarFormatError("CSV file size invalid")
    try:
        text = raw.decode(encoding, errors="strict")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise NarFormatError("CSV decoding or quoting invalid") from exc
    if len(rows) > MAX_ROWS or not rows:
        raise NarFormatError("CSV row count invalid")
    if any(len(r) != required for r in rows):
        raise NarFormatError(kind + " column layout changed or truncated")
    if type(header) is not bool:
        raise NarFormatError("header mode must be explicitly supplied")
    if header:
        names = ("競馬場", "競走年月日", "レース番号")
        if tuple(x.strip() for x in rows[0][:3]) != names:
            raise NarFormatError("CSV header differs from documented NAR layout")
        rows = rows[1:]
    elif rows[0][0].strip() == "競馬場":
        raise NarFormatError("CSV contains unannounced header")
    if not rows:
        raise NarFormatError("CSV contains no records")
    return rows


def _ymd(raw):
    if not isinstance(raw, str) or not re.fullmatch(r"\d{8}", raw):
        raise NarFormatError("NAR race day is not YYYYMMDD")
    try:
        dt = datetime.strptime(raw, "%Y%m%d").date()
    except ValueError as exc:
        raise NarFormatError("NAR race day invalid") from exc
    if dt.strftime("%Y%m%d") != raw:
        raise NarFormatError("noncanonical NAR race date")
    return dt.isoformat()


def _nr(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise NarFormatError("NAR race or horse number invalid")
    number = int(value)
    if not 1 <= number <= 99:
        raise NarFormatError("NAR number out of range")
    return number


def _target_rows(rows, day, venue, race_no):
    chosen = []
    for row in rows:
        actual_date = _ymd(row[1].strip())
        nr = _nr(row[2].strip())
        if actual_date == day and row[0].strip() == venue and nr == race_no:
            chosen.append(row)
    return chosen


def _time(day, hhmm):
    if not isinstance(hhmm, str) or not re.fullmatch(r"\d{4}", hhmm):
        raise NarFormatError("scheduled start time HHMM missing")
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    if hour > 23 or minute > 59:
        raise NarFormatError("scheduled start time HHMM invalid")
    return f"{day}T{hour:02d}:{minute:02d}:00+09:00"


def _allowed(policy, ref, rights_ref, purposes):
    if not isinstance(policy, PermissionPolicy):
        raise NarFormatError("independently authenticated reviewer policy required")
    for purpose in purposes:
        if not policy.authorize(ref, rights_ref, purpose):
            raise NarFormatError("SOURCE_PERMISSION_NOT_ADMITTED:" + purpose)


def _career(value):
    """Raw pre-race career record, NOT an inferred score or probability."""
    if not value:
        return None
    if not re.fullmatch(r"\d+-\d+-\d+-\d+", value):
        raise NarFormatError("unexpected published career statistics structure")
    return value


def stage_nar_csv(racelist_bytes, horselist_bytes, policy, *, at, observed_at,
                  source_ref, rights_ref, event_date_jst, venue, race_no,
                  encoding, has_header):
    """One selected NAR local CSV race -> private pre-model staging record.

    No official sales cutoff is contained in the CSV racelist start-time field.
    Thus a pre-race data stage is deliberately NOT a model-ready forecast.
    The caller's observed_at timestamp is an unverified claim, not server proof.
    """
    _allowed(policy, source_ref, rights_ref, ("analysis", "private_storage", "private_derived"))
    try:
        now, observed = moment(at), moment(observed_at)
    except (TypeError, ValueError) as exc:
        raise NarFormatError("capture/as-of timezone required") from exc
    if observed > now:
        raise NarFormatError("source observation lies in the future")
    if (not isinstance(event_date_jst, str) or
        event_date_jst != _ymd(event_date_jst.replace("-", "")) or
        not isinstance(venue, str) or not 1 <= len(venue.strip()) <= 90 or
        type(race_no) is not int or not 1 <= race_no <= 99):
        raise NarFormatError("target event identity invalid")

    race_rows = _target_rows(
        _rows(racelist_bytes, kind="racelist", encoding=encoding, header=has_header),
        event_date_jst, venue, race_no)
    horse_rows = _target_rows(
        _rows(horselist_bytes, kind="horselist", encoding=encoding, header=has_header),
        event_date_jst, venue, race_no)
    if len(race_rows) != 1 or not horse_rows:
        raise NarFormatError("requested race must appear once with entrants in BOTH CSV files")
    race = race_rows[0]
    if any(cell.strip() for cell in race[POST_RACE_RACELIST_START-1:]):
        raise NarFormatError("POST_RACE_RACELIST_FIELDS_PRESENT")
    if any(any(cell.strip() for cell in r[POST_RACE_HORSELIST_START-1:]) for r in horse_rows):
        raise NarFormatError("POST_RACE_HORSELIST_OR_MARKET_FIELDS_PRESENT")
    start_at = _time(event_date_jst, race[3].strip())
    if observed >= moment(start_at) or now >= moment(start_at):
        raise NarFormatError("MISSED_START_OR_UNVERIFIED_PRE_RACE_CAPTURE")
    declared_n = _nr(race[26].strip())
    if not 3 <= declared_n <= 18:
        raise NarFormatError("horse field size unsupported or missing")
    entrants, seen = [], set()
    for row in horse_rows:
        num = _nr(row[5].strip())
        if num in seen:
            raise NarFormatError("duplicate horse number")
        seen.add(num)
        if not row[6].strip() or not row[14].strip() or not row[18].strip():
            raise NarFormatError("horse/jockey/trainer pre-race identity missing")
        try:
            weight = float(row[16].strip())
        except ValueError as exc:
            raise NarFormatError("declared carried weight missing") from exc
        if not 30 <= weight <= 90:
            raise NarFormatError("declared weight out of range")
        entrants.append({
            "horse_number": num,
            "frame_number": _nr(row[3].strip()),
            "horse_name": row[6].strip(),
            "jockey_name": row[14].strip(),
            "trainer_name": row[18].strip(),
            "age": row[8].strip() or None,
            "sex": row[7].strip() or None,
            "carried_weight_kg": weight,
            "career_record": _career(row[24].strip()),
            "venue_record": _career(row[27].strip()),
            "venue_distance_record": _career(row[28].strip()),
            "horse_stable_id": None,
            "horse_identity_status": "NO_UNIQUE_ID_IN_NAR_CSV",
        })
    if len(entrants) != declared_n:
        status = "HORSE_COUNT_MISMATCH_OR_SCRATCH_UNVERIFIED"
    else:
        status = "MISSING_STABLE_HORSE_IDS_AND_FEATURES_AND_CUTOFF"
    # Race name, current weather/going, race outcome, odds and current-race
    # fractional times are deliberately NOT returned here.
    staged = {
        "schema": STAGE_SCHEMA,
        "scope": "PRIVATE_SOURCE_PREFLIGHT_ONLY",
        "race_id": f"horse_local:{event_date_jst}:{venue}:{race_no}",
        "event_date_jst": event_date_jst,
        "venue": venue,
        "race_no": race_no,
        "scheduled_start_at": start_at,
        "sales_cutoff_at": None,
        "official_cutoff_verified": False,
        "surface": race[21].strip() or None,
        "turn_direction": race[22].strip() or None,
        "distance_m": race[23].strip() or None,
        "race_kind": race[4].strip() or None,
        "declared_entries": declared_n,
        "observed_entries": len(entrants),
        "participants": sorted(entrants, key=lambda row: row["horse_number"]),
        "original_csv_sha256": {
            "racelist": hashlib.sha256(racelist_bytes).hexdigest(),
            "horselist": hashlib.sha256(horselist_bytes).hexdigest()
        },
        "source_ref": source_ref,
        "source_rights_ref": rights_ref,
        "signed_review_policy_sha256": policy.document_sha256,
        "observed_at_claimed": observed_at,
        "adapter_version": "nar-official-66-36-columns-v1",
        "format_manual": DOC_URL,
        "model_ready": False,
        "forecast_frozen": False,
        "external_receipt": None,
        "eligible_hit_at_8": False,
        "missing_model_required_features": sorted(
            set(COMMON_REQUIRED + SPORT_REQUIRED["horse"])),
        "missing_pre_cutoff_evidence": [
            "HORSE_ID_NOT_PROVIDED_BY_NAR",
            "ACTUAL_SALES_CUTOFF_NOT_IN_RACELIST",
            "FULL_HISTORICAL_FEATURES_NOT_PROVIDED_BY_TWO_CSVS",
            "EXTERNAL_CAPTURE_TIME_NOT_ATTESTED",
            "INDEPENDENT_FREEZE_RECEIPT_MISSING",
        ],
        "status": status,
    }
    staged["stage_sha256"] = digest(staged)
    return staged
