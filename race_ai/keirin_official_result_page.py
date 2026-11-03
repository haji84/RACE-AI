"""Bounded, single-page KEIRIN.JP race-result transport / format probe.

NOT an unrestricted crawler or grant to republish/train on provider content.
Only one publicly linked official page is fetched at most once per invocation.
Never persists HTML or sends result text to public CI logs.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.parse import urlencode
from unicodedata import normalize
import re

BASE = "https://keirin.jp/pc/dfw/dataplaza/guest/raceresult"
MAX_BODY = 600_000
ACK = "ONE_KEIRIN_RESULT_PAGE_PERSONAL_TECHNICAL_CHECK"
RESULT_MIME = frozenset(("text/html", "application/xhtml+xml"))


class OfficialResultTransportError(ValueError):
    pass


class RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise OfficialResultTransportError("OFFICIAL_REDIRECT_REJECTED")


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if self.hidden == 0:
            self.text_parts.append(value)


def result_url(kcd: int, ymd: str, rno: int) -> str:
    if type(kcd) is not int or not 1 <= kcd <= 99:
        raise OfficialResultTransportError("BAD_VENUE_CODE")
    if type(rno) is not int or not 1 <= rno <= 12:
        raise OfficialResultTransportError("BAD_RACE_NUMBER")
    if type(ymd) is not str or not re.fullmatch(r"\d{8}", ymd):
        raise OfficialResultTransportError("BAD_EVENT_DATE")
    try:
        if datetime.strptime(ymd, "%Y%m%d").strftime("%Y%m%d") != ymd:
            raise ValueError("not valid date")
    except ValueError:
        raise OfficialResultTransportError("BAD_EVENT_DATE") from None
    return BASE + "?" + urlencode({"KCD": f"{kcd:02d}", "KBI": ymd, "RNO": f"{rno:02d}"})


def _decode(body: bytes, raw_content_type: str) -> tuple[str, str]:
    ct = raw_content_type.lower()
    candidates = []
    match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", ct)
    if match:
        candidates.append(match.group(1))
    prefix = body[:10000].decode("ascii", "ignore")
    match = re.search(r"<meta[^>]+charset\s*=\s*['\"]?([\w-]+)", prefix, re.I)
    if match:
        candidates.append(match.group(1))
    candidates.extend(("utf-8", "cp932"))
    for declared in candidates:
        encoding = {"shift_jis": "cp932", "shift-jis": "cp932",
                    "sjis": "cp932", "x-sjis": "cp932"}.get(declared.lower(), declared)
        if encoding not in ("cp932", "utf-8", "euc_jp", "iso2022_jp"):
            continue
        try:
            return body.decode(encoding, errors="strict"), encoding
        except UnicodeDecodeError:
            continue
    raise OfficialResultTransportError("SOURCE_CHARSET_UNVERIFIED")


def _report(body: bytes, content_type: str, kcd: int, ymd: str, rno: int):
    html, encoding = _decode(body, content_type)
    visible = Visible()
    visible.feed(html)
    text = normalize("NFKC", " ".join(visible.text_parts))
    event = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))
    day_shapes = (f"{event.year}/{event.month:02d}/{event.day:02d}",
                  f"{event.year}年{event.month}月{event.day}日",
                  f"{event.year}/{event.month}/{event.day}")
    race = bool(re.search(rf"(?<!\d)(?:第\s*)?0?{rno}\s*(?:レース|R\b)",
                          text, flags=re.I))
    return {
        "schema": "RACE_AI_KEIRIN_OFFICIAL_SINGLE_PAGE_FORMAT_PROBE_V1",
        "mode": "ONE_PAGE_TECHNICAL_CHECK_NO_RESULT_AUTHENTICATION",
        "source_url": result_url(kcd, ymd, rno),
        "event_date_jst": event.isoformat(),
        "venue_code": kcd, "race_no": rno,
        "source_sha256": sha256(body).hexdigest(),
        "source_bytes": len(body), "source_charset": encoding,
        "event_date_marker_in_body": any(d in text for d in day_shapes),
        "race_number_marker_in_body": race,
        "threefold_bet_label_present": "3連単" in text,
        "payout_label_present": "払戻" in text or "払戻金" in text,
        "result_table_label_present": "着順" in text or "競走結果" in text,
        "results_parsed": False,
        "result_finalized_verified": False,
        "source_original_published_at_verified": False,
        "provider_rights_for_bulk_collection_verified": False,
        "model_training_permitted_verified": False,
        "persistent_monitoring_enabled": False,
        "source_html_persisted": False,
    }


def probe_one_result(kcd, ymd, rno, *, acknowledgement,
                     opener=None, observed_at=None):
    """Return public-safe metadata, not raw results; no retries / no storage."""
    if acknowledgement != ACK:
        raise OfficialResultTransportError("ONE_SHOT_EXPLICIT_SCOPE_REQUIRED")
    url = result_url(kcd, ymd, rno)
    client = opener if opener is not None else build_opener(
        RefuseRedirect(), HTTPSHandler())
    request = Request(url, headers={
        "Accept": "text/html",
        "User-Agent": "RACE-AI/0.1 (one-shot private official result technical check)",
    }, method="GET")
    try:
        with client.open(request, timeout=8) as response:
            if response.status != 200 or response.geturl() != url:
                raise OfficialResultTransportError("OFFICIAL_RESPONSE_IDENTITY_MISMATCH")
            ct = response.headers.get("Content-Type", "")
            if ct.split(";", 1)[0].strip().lower() not in RESULT_MIME:
                raise OfficialResultTransportError("UNEXPECTED_PROVIDER_MIME")
            body = response.read(MAX_BODY + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        if isinstance(exc, HTTPError):
            raise OfficialResultTransportError(
                "OFFICIAL_PAGE_HTTP_" + str(exc.code)) from None
        raise OfficialResultTransportError(
            "OFFICIAL_PAGE_UNAVAILABLE_" + type(exc).__name__) from None
    if not 0 < len(body) <= MAX_BODY:
        raise OfficialResultTransportError("OFFICIAL_PAGE_SIZE_INVALID")
    report = _report(body, ct, kcd, ymd, rno)
    stamp = datetime.now(timezone.utc) if observed_at is None else observed_at
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise OfficialResultTransportError("OBSERVED_CLOCK_INVALID")
    report["observed_at_runner_not_provider_time"] = stamp.isoformat()
    return report
