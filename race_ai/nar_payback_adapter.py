"""Offline NAR payback CSV -> result CANDIDATES, never authenticated settlement.

Reads position 50-53 (1-indexed) for 3連単組番馬番1/2/3 and 3連単払戻金.
Positions are from the official published NAR data layout. Settlement, refunds,
official finality, source rights and pre-cutoff provenance remain separately gated.
No HTTP, betting, model imports, or previous forecast modifications.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from zipfile import BadZipFile, ZipFile

from .operator_export_intake import IntakeError, _dt

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 25000
SOURCE = "https://www.keiba.go.jp/"
HEADER = ("競馬場", "競走年月日", "レース番号")
CSV_NAME = re.compile(r"\d{6}(?:\d{2})?_payback\.csv\Z")


def load_payback_bytes(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise IntakeError("NAR payback file exceeds 8MiB")
    if str(path).lower().endswith(".zip"):
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                matches = [i for i in archive.infolist() if not i.is_dir()
                           and CSV_NAME.fullmatch(i.filename)]
                if len(matches) != 1:
                    raise IntakeError("exactly one root payback CSV required")
                member = matches[0]
                if member.file_size > MAX_BYTES or (member.flag_bits & 1):
                    raise IntakeError("oversized/encrypted member")
                with archive.open(member) as reader:
                    uncompressed = reader.read(MAX_BYTES + 1)
                if len(uncompressed) > MAX_BYTES:
                    raise IntakeError("oversized uncompressed member")
                return uncompressed
        except (BadZipFile, RuntimeError) as exc:
            raise IntakeError("invalid ZIP") from exc
    if not CSV_NAME.fullmatch(Path(path).name):
        raise IntakeError("not a NAR payback CSV filename")
    return data


def parse_payback(data, captured_at, rights_ref):
    _dt(captured_at, "captured_at")
    if not isinstance(rights_ref, str) or not rights_ref.strip() or len(rights_ref) > 1024:
        raise IntakeError("source rights reference required, not an automatic grant")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp932")
        except UnicodeDecodeError as exc:
            raise IntakeError("unsupported payback encoding") from exc
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        first = next(rows, None)
        if first is None:
            raise IntakeError("empty payback CSV")
        has_header = tuple(v.strip() for v in first[:3]) == HEADER
        if not has_header and (len(first) < 54 or not re.fullmatch(r"\d{8}", first[1].strip())):
            raise IntakeError("unknown payback CSV layout")
        from itertools import chain
        data_rows = rows if has_header else chain([first], rows)
        outcomes = {}
        event_days = set()
        for index, row in enumerate(data_rows, start=1):
            if index > MAX_ROWS:
                raise IntakeError("too many payback rows")
            if not row or not any(v.strip() for v in row):
                continue
            # Exactly 54 columns in the documented v2026 NAR payback layout.
            if len(row) != 54:
                raise IntakeError("payback column count changed; adapter review required")
            venue, day_raw, race_raw = [v.strip() for v in row[:3]]
            if not venue or len(venue) > 128 or ":" in venue:
                raise IntakeError("invalid venue")
            if not re.fullmatch(r"\d{8}", day_raw):
                raise IntakeError("invalid date")
            try:
                day = datetime.strptime(day_raw, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError as exc:
                raise IntakeError("invalid date") from exc
            if not race_raw.isascii() or not race_raw.isdigit() or not 1 <= int(race_raw) <= 99:
                raise IntakeError("invalid race number")
            event_days.add(day)
            race_id = f"horse_local:{day}:{venue}:{int(race_raw)}"
            record = outcomes.setdefault(race_id, {"race_id": race_id,
                "trifecta_payouts": [], "refund_status": "UNKNOWN",
                "result_finality": "UNVERIFIED",
                "status": "UNVERIFIED_PAYBACK_CANDIDATE_ONLY"})
            combo_raw = [x.strip() for x in row[49:52]]
            yen_raw = row[52].strip()
            if not any(combo_raw) and not yen_raw:
                continue  # This is NOT proof of a canceled or no-trifecta race.
            if any(not v.isascii() or not v.isdigit() for v in combo_raw):
                raise IntakeError("incomplete/non-numeric trifecta combination")
            combo = [int(v) for v in combo_raw]
            if not all(1 <= x <= 99 for x in combo) or len(set(combo)) != 3:
                raise IntakeError("invalid ordered trifecta combination")
            if not yen_raw.isascii() or not yen_raw.isdigit() or int(yen_raw) <= 0:
                raise IntakeError("invalid positive yen payout")
            if any(p["combination"] == combo for p in record["trifecta_payouts"]):
                raise IntakeError("duplicate trifecta in same file")
            record["trifecta_payouts"].append({
                "combination": combo, "yen_per_100": int(yen_raw)})
        if not outcomes:
            raise IntakeError("no payback races")
        if len(event_days) != 1:
            raise IntakeError("mixed event dates cannot form one daily audit")
        return {"schema": "RACE_AI_NAR_PAYBACK_AUDIT_V1", "status": "OFFLINE_UNVERIFIED",
                "event_date_jst": next(iter(event_days)),
                "source_ref": SOURCE, "source_rights_ref": rights_ref,
                "captured_at_claimed": captured_at,
                "source_rights_independently_admitted": False,
                "official_finality_independently_verified": False,
                "refunds_independently_verified": False,
                "forecast_comparison_allowed": False,
                "records": sorted(outcomes.values(), key=lambda x: x["race_id"])}
    except csv.Error as exc:
        raise IntakeError("invalid payback CSV") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline NAR payback audit; no settlement")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--source-rights-ref", required=True)
    args = parser.parse_args(argv)
    try:
        raw = load_payback_bytes(args.input)
        obj = parse_payback(raw, args.captured_at, args.source_rights_ref)
        obj["raw_sha256"] = hashlib.sha256(raw).hexdigest()
        with Path(args.output).open("x", encoding="utf-8") as file:
            json.dump(obj, file, ensure_ascii=False, sort_keys=True, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        print("NAR_PAYBACK_OFFLINE_UNVERIFIED races=" + str(len(obj["records"])))
        return 0
    except (OSError, IntakeError, TypeError, ValueError) as exc:
        print("NAR_PAYBACK_IMPORT_REJECTED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
