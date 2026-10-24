"""Adapt an already acquired, extracted official B program to the day snapshot schema.

No network activity or publishing is performed here. This intentionally does
not infer names, motor numbers or display measurements from unknown fields.
The caller must supply independently validated motor allocation rows.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime
import hashlib
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

from .core import SourceError, parse_b, _blocks, _decode


def program_details(raw, day):
    text = unicodedata.normalize('NFKC', _decode(raw))
    output, closing = {}, {}
    row_pattern = re.compile(r'^\s*([1-6])\s+(\d{4})(.+?)(\d{2})(\D{2})(\d{2})([AB][12])\s+'
        r'(\d+\.\d{2})\s*(\d+\.\d{2})\s*(\d+\.\d{2})\s*(\d+\.\d{2})\s+'
        r'(\d+)\s+(\d+\.\d{2})\s*(\d+)\s+(\d+\.\d{2})(?:\s|$)')
    for venue, block in _blocks(text, 'B'):
        dates = re.findall(r'(20\d{2})\s*(?:年|/)\s*(\d{1,2})\s*(?:月|/)\s*(\d{1,2})\s*日?', block[:1400])
        if not dates or set((int(y),int(m),int(d)) for y,m,d in dates) != {(day.year,day.month,day.day)}:
            raise SourceError('B program body date unverified')
        if not 1 <= venue <= 24:
            raise SourceError('B program venue invalid')
        rid = None
        for line in block.splitlines():
            header = re.match(r'^\s*(\d{1,2})R\s+.*?H\s*\d{3,4}m',line,re.I)
            if header:
                number = int(header.group(1))
                time = re.search(r'電話投票締切予定\s*((?:[01]\d|2[0-3]):[0-5]\d)\s*$', line)
                if not 1 <= number <= 12 or time is None:
                    raise SourceError('B program closing time missing')
                rid = f'{day:%Y%m%d}-{venue:02d}-{number:02d}'
                if rid in closing:
                    raise SourceError('duplicate B race header')
                closing[rid] = f'{day.isoformat()}T{time.group(1)}:00+09:00'
                continue
            if re.match(r'^\s*[1-6]\s+\d{4}', line):
                row = row_pattern.match(line)
                if row is None or rid is None:
                    raise SourceError('B program detail layout malformed')
                lane, registration, name, age, branch, weight, grade, national, national2, local, local2, motor, motor2, boat, boat2 = row.groups()
                key = (rid, int(lane))
                values = [float(v) for v in (national,national2,local,local2,motor2,boat2)]
                if (key in output or not name.strip() or not 1 <= int(motor) <= 999 or not 1 <= int(boat) <= 999
                        or any(not 0 <= v <= 100 for v in values) or float(national) > 10 or float(local) > 10):
                    raise SourceError('B program allocation or statistics invalid')
                output[key] = dict(racer_registration_id=registration, name=name.strip(), motor_no=int(motor),
                    boat_no=int(boat), grade=grade, national_win_rate=float(national), local_win_rate=float(local),
                    national_top2_rate=float(national2), local_top2_rate=float(local2),
                    motor_top2_rate=float(motor2), boat_top2_rate=float(boat2))
    return output, closing


def normalize_b_snapshot(raw: bytes, *, day: date, source_url: str,
                         observed_at: str, motors: dict | None = None,
                         require_details: bool = False, archive_sha256: str | None = None) -> dict:
    """Construct race identities from official B; preserve absent motor data as unknown."""
    records = parse_b(raw, day.isoformat())
    fields, closing = program_details(raw, day) if require_details else ({}, {})
    if require_details:
        captured = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
        if captured.tzinfo is None or captured.astimezone(ZoneInfo('Asia/Tokyo')).date() != day:
            raise SourceError('B capture timestamp day invalid')
        if len({(r['race_id'],r['lane']) for r in records}) != len(records) or set(fields) != {(r['race_id'],r['lane']) for r in records}:
            raise SourceError('B identity/detail coverage conflict')
    if not source_url.startswith("https://"):
        raise SourceError("source must be HTTPS")
    grouped = defaultdict(lambda: defaultdict(list))
    for row in records:
        rid = row["race_id"]
        venue = rid[9:11]
        grouped[venue][rid].append(row)
    venues = []
    for venue, races in sorted(grouped.items()):
        items = []
        for rid, rows in sorted(races.items()):
            boats = []
            for row in sorted(rows, key=lambda item: item["lane"]):
                key = (rid, row["lane"])
                motor = motors.get(key) if motors else None
                details = fields.get(key, {})
                if details:
                    if details['racer_registration_id'] != row['racer_id'] or (motor is not None and motor != details['motor_no']):
                        raise SourceError('B detail identity or motor conflict')
                    motor = details['motor_no']
                if motor is not None and (type(motor) is not int or not 1 <= motor <= 999):
                    raise SourceError("invalid motor allocation")
                boats.append({"lane": row["lane"],
                              "racer_registration_id": row["racer_id"],
                              "motor_no": motor,
                              "name": None,
                              "average_st": None,
                              "display_time": None,
                              "preview_course": None})
                boats[-1].update(details)
            if require_details and any(len({b[field] for b in boats}) != 6 for field in ('racer_registration_id','motor_no','boat_no')):
                raise SourceError('duplicate B racer or allocation')
            items.append({"race_id": rid, "boats": boats, "closed_at": closing.get(rid),
                          "preview_available": False})
        venues.append({"venue": venue, "races": items})
        if require_details and len(items) != 12:
            raise SourceError('B day has incomplete venue coverage')
    text_hash = hashlib.sha256(raw).hexdigest()
    if archive_sha256 is not None and not re.fullmatch(r'[0-9a-f]{64}', archive_sha256):
        raise SourceError('invalid B archive hash')
    return {"date_jst": day.isoformat(), "source_url": source_url,
            "source_sha256": archive_sha256 or text_hash,
            "extracted_text_sha256": text_hash,
            "source_hash_scope": 'downloaded_archive' if archive_sha256 else 'extracted_program_text',
            "first_observed_at": observed_at, "venues": venues,
            "races": sum(len(v["races"]) for v in venues),
            "complete_six_boat_races": sum(len(r["boats"]) == 6 for v in venues for r in v["races"])}


def normalize_b_file(path: Path, *, day: date, source_url: str,
                     observed_at: str, motors: dict | None = None) -> dict:
    return normalize_b_snapshot(path.read_bytes(), day=day, source_url=source_url,
                                observed_at=observed_at, motors=motors)
