"""Offline BOAT RACE official screen HTML schedule adapter.

Accepts previously acquired HTML, never makes HTTP requests. The screen's
"締切予定時刻" is an announced schedule, not proof of the official actual
sales deadline. No prediction, actual result, license or permission is inferred.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlsplit

from .operator_export_intake import IntakeError, SCHEMA, _dt, transform

MAX_HTML_BYTES = 1_500_000
OFFICIAL_HOSTS = {"www.boatrace.jp", "boatrace.jp"}
ROW_LABEL = "締切予定時刻"


class _TableRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.depth = 0
        self.rows = None
        self.current_row = None
        self.current_cell = None
        self.cell_depth = 0
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template"):
            self.ignored += 1
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.rows = []
        if self.depth == 1 and tag == "tr":
            self.current_row = []
        if self.depth == 1 and tag in ("td", "th") and self.current_row is not None:
            self.current_cell = []
            self.cell_depth = 1
        elif self.current_cell is not None and tag in ("td", "th"):
            self.cell_depth += 1

    def handle_data(self, data):
        if self.ignored == 0 and self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template"):
            self.ignored = max(0, self.ignored - 1)
        if tag in ("td", "th") and self.current_cell is not None:
            self.cell_depth -= 1
            if self.cell_depth == 0:
                normalized = "".join(self.current_cell)
                self.current_row.append("".join(normalized.split()))
                self.current_cell = None
        if tag == "tr" and self.depth == 1 and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None
        if tag == "table" and self.depth > 0:
            self.depth -= 1
            if self.depth == 0:
                self.tables.append(self.rows)
                self.rows = None


def _identity(url):
    if not isinstance(url, str) or len(url) > 500:
        raise IntakeError("official URL required")
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname not in OFFICIAL_HOSTS
            or u.username or u.password or u.port not in (None, 443)
            or u.fragment or u.path != "/owpc/pc/race/racelist"):
        raise IntakeError("non-official or unexpected race-card URL")
    try:
        pairs = parse_qsl(u.query, strict_parsing=True, keep_blank_values=True)
    except ValueError as exc:
        raise IntakeError("invalid official query string") from exc
    if sorted(k for k, _ in pairs) != ["hd", "jcd", "rno"]:
        raise IntakeError("race-card query must contain exactly hd/jcd/rno")
    q = dict(pairs)
    if not re.fullmatch(r"\d{8}", q["hd"]):
        raise IntakeError("invalid official date")
    try:
        event_date = datetime.strptime(q["hd"], "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise IntakeError("impossible official date") from exc
    if not re.fullmatch(r"\d{2}", q["jcd"]) or not 1 <= int(q["jcd"]) <= 24:
        raise IntakeError("invalid official venue code")
    if not re.fullmatch(r"(?:[1-9]|1[0-2])", q["rno"]):
        raise IntakeError("invalid race number")
    return event_date, q["jcd"], int(q["rno"])


def _schedule_from_html(html):
    parser = _TableRows()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError) as exc:
        raise IntakeError("malformed local HTML") from exc
    candidates = []
    for table in parser.tables:
        for i, row in enumerate(table):
            if len(row) < 2 or row[0] != "レース":
                continue
            if i + 1 >= len(table):
                continue
            next_row = table[i + 1]
            if not next_row or next_row[0] != ROW_LABEL:
                continue
            races = row[1:]
            times = next_row[1:]
            if len(races) != len(times) or not 1 <= len(races) <= 12:
                raise IntakeError("schedule race/time length mismatch")
            mapping = {}
            for number, time in zip(races, times):
                if not re.fullmatch(r"(?:[1-9]|1[0-2])R", number):
                    raise IntakeError("unexpected screen race heading")
                if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time):
                    raise IntakeError("invalid announced time")
                n = int(number[:-1])
                if n in mapping:
                    raise IntakeError("duplicate race number in screen")
                mapping[n] = time
            candidates.append(mapping)
    if len(candidates) != 1:
        raise IntakeError("official screen race/time table absent or ambiguous")
    return candidates[0]


def transform_official_screen(raw, *, source_url, captured_at, rights_ref):
    """Return explicit AUDIT_ONLY list from saved HTML; no permission inference."""
    day, venue_code, race_no = _identity(source_url)
    _dt(captured_at, "captured_at")
    if not isinstance(rights_ref, str) or not rights_ref.strip() or len(rights_ref) > 512:
        raise IntakeError("provenance reference required")
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_HTML_BYTES:
        raise IntakeError("bounded HTML snapshot required")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeError("only UTF-8 saved HTML accepted") from exc
    mapping = _schedule_from_html(text)
    if race_no not in mapping:
        raise IntakeError("URL race number absent from schedule")
    if len(mapping) < 1:
        raise IntakeError("empty race list")
    venue = "boatrace-jcd-" + venue_code
    manifest = {
        "schema": SCHEMA, "event_date_jst": day,
        "source_ref": source_url, "source_rights_ref": rights_ref,
        "captured_at": captured_at, "races": [
            {"sport": "boat", "venue": venue, "race_no": n,
             "sales_cutoff_at": f"{day}T{time}:00+09:00",
             "offering_status": "UNKNOWN"}
            for n, time in sorted(mapping.items())]}
    result = transform(manifest, hashlib.sha256(raw).hexdigest())
    result["screen_capture_audit"] = {
        "status": "UNVERIFIED_OFFLINE_WEB_SNAPSHOT",
        "screen_url": source_url,
        "source_html_sha256": hashlib.sha256(raw).hexdigest(),
        "source_html_not_in_report": True,
        "captured_at_claimed": captured_at,
        "schedule_kind": "ANNOUNCED_CUTOFF_NOT_VERIFIED",
        "automatic_site_collection_authorized": False,
        "actual_cutoff_verified": False,
        "forecast_freeze_proven": False,
        "official_race_result_verified": False,
        "official_complete_day_proven": False,
        "head_count": len(mapping),
    }
    # The existing audit ledger contains announced deadlines, but verification
    # flags remain false. Do not treat them as actual cutoffs for prediction.
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Saved BOAT RACE HTML -> audit-only race index")
    parser.add_argument("--html", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--source-rights-ref", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        with Path(args.html).open("rb") as stream:
            raw = stream.read(MAX_HTML_BYTES + 1)
        audit = transform_official_screen(raw, source_url=args.source_url,
                                         captured_at=args.captured_at,
                                         rights_ref=args.source_rights_ref)
        payload = json.dumps(audit, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False) + "\n"
        # Do not accidentally publish saved-provider audit files via public Git.
        dest = Path(args.output).absolute()
        parent = dest.parent.resolve(strict=True)
        if any((p / ".git").exists() for p in (parent, *parent.parents)):
            raise IntakeError("private audit output cannot be in Git checkout")
        with dest.open("x", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        print("BOAT_WEB_AUDIT_ONLY races=" + str(len(audit["records"])))
        return 0
    except (OSError, IntakeError, TypeError, ValueError) as exc:
        print("BOAT_WEB_AUDIT_REJECTED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
