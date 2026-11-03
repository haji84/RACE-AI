"""Research-only one-shot transport probe for one publicly linked race result.

Distinct from KEIRIN.JP; NOT an organizer-authorized machine data feed.
No result rows are persisted, no automated polling, no forecasts inferred.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from unicodedata import normalize
import re

MAX_BODY = 500_000
ACK = "ONE_THIRD_PARTY_KEIRIN_PAGE_PRIVATE_RESEARCH_ONLY"


class MobileProbeError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise MobileProbeError("UNEXPECTED_REDIRECT")


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script","style","template","noscript"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script","style","template","noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def page_url(ymd: str, venue_code: int, race_no: int) -> str:
    if type(ymd) is not str or re.fullmatch(r"\d{8}", ymd) is None:
        raise MobileProbeError("INVALID_DATE")
    try:
        dt = datetime.strptime(ymd, "%Y%m%d")
        if dt.strftime("%Y%m%d") != ymd:
            raise ValueError()
    except ValueError:
        raise MobileProbeError("INVALID_DATE") from None
    if type(venue_code) is not int or not (1 <= venue_code <= 99):
        raise MobileProbeError("INVALID_VENUE")
    if type(race_no) is not int or not (1 <= race_no <= 12):
        raise MobileProbeError("INVALID_RACE")
    return (f"https://www.keirin-mobile.jp/New/races/{ymd}/"
            f"{venue_code:02d}/{race_no:02d}/")


def _decode(raw: bytes, content_type: str) -> str:
    header = raw[:8192].decode("ascii", "ignore")
    tags = re.search(r"<meta[^>]+charset\s*=\s*['\"]?([\w-]+)",
                     header, re.I)
    ct = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.I)
    declared = []
    for match in (ct, tags):
        if match:
            declared.append(match.group(1).lower().replace("shift_jis","cp932"))
    for enc in [*declared,"utf-8","cp932"]:
        if enc not in ("utf-8","cp932"):
            continue
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    raise MobileProbeError("UNVERIFIED_CHARSET")


def probe_one(ymd, venue_code, race_no, *, acknowledgement, opener=None,
              observed_at=None):
    if acknowledgement != ACK:
        raise MobileProbeError("EXPLICIT_ONE_SHOT_SCOPE_REQUIRED")
    url = page_url(ymd, venue_code, race_no)
    client = opener or build_opener(_NoRedirect(), HTTPSHandler())
    request = Request(url, method="GET",
                      headers={"Accept":"text/html",
                               "User-Agent":"RACE-AI-one-shot-private-source-shape/1"})
    try:
        with client.open(request, timeout=8) as resp:
            status = resp.status
            final = resp.geturl()
            ctype = resp.headers.get("Content-Type","")
            if status != 200 or final != url:
                raise MobileProbeError("BAD_PROVIDER_RESPONSE")
            if ctype.split(";",1)[0].lower().strip() not in {
                "text/html","application/xhtml+xml"}:
                raise MobileProbeError("BAD_PROVIDER_CONTENT_TYPE")
            raw = resp.read(MAX_BODY+1)
    except HTTPError as exc:
        raise MobileProbeError(f"PROVIDER_HTTP_{exc.code}") from None
    except (URLError, OSError, TimeoutError) as exc:
        raise MobileProbeError("PROVIDER_UNAVAILABLE_"+type(exc).__name__) from None
    if not (0 < len(raw) <= MAX_BODY):
        raise MobileProbeError("PROVIDER_BODY_SIZE_REJECTED")
    page = _Visible()
    page.feed(_decode(raw, ctype))
    txt = normalize("NFKC"," ".join(page.parts))
    y,mo,d=ymd[:4],int(ymd[4:6]),int(ymd[6:])
    date_markers = (f"{y}年{mo:02d}月{d:02d}日",
                    f"{y}年{mo}月{d}日",
                    f"{y}/{mo:02d}/{d:02d}")
    stamp = observed_at or datetime.now(timezone.utc)
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        raise MobileProbeError("UNTRUSTED_OBSERVATION_CLOCK")
    return {
        "schema": "RACE_AI_KEIRIN_MOBILE_SINGLE_PAGE_RESEARCH_PROBE_V1",
        "source_kind": "THIRD_PARTY_NOT_KEIRIN_JP",
        "source_url": url,
        "source_sha256": sha256(raw).hexdigest(),
        "captured_at_unattested": stamp.isoformat(),
        "source_bytes": len(raw),
        "page_date_marker": any(m in txt for m in date_markers),
        "page_race_marker": bool(re.search(
            rf"(?<!\d)0?{race_no}\s*(?:R|レース)\b",txt,re.I)),
        "trifecta_label_present": "3連単" in txt,
        "payout_label_present": "払戻" in txt or "払い戻し" in txt,
        "race_results_parsed": False,
        "result_officially_authenticated": False,
        "machine_collection_rights_verified": False,
        "model_training_rights_verified": False,
        "raw_page_stored": False,
        "perpetual_polling_enabled": False,
        "forecast_generated": False,
    }
