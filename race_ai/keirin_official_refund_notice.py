"""Literal support for two reviewed official refund notices, without settlement.

Only the two individually reviewed URLs and their observed article grammars are
supported. Unknown articles, partial refunds and changed claims require review.
Receipts contain raw HTML: keep them owner-private/encrypted. Only the summary
function is intended for public logs. A saved-byte reparse proves consistency,
not a provider signature or an independently witnessed first-publication time.
No schedules, predictions, payouts, scores, files or source flags are changed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, build_opener


SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_REFUND_NOTICE_V1"
STATE = "OFFICIAL_REFUND_NOTICE_SOURCE_SUPPORTED"
MAX_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 20
JST = timezone(timedelta(hours=9))
UTSUNOMIYA_NOTICE_URL = "https://blog.utsunomiya-keirin.jp/notification/2025/02/fii-a267.html"
KUMAMOTO_NOTICE_URL = (
    "https://www.kumamotokeirin.jp/news/"
    "%E3%80%90%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B%EF%BD%9C"
    "%E7%86%8A%E6%9C%AC%E5%B8%82%E5%96%B6%E7%AB%B6%E8%BC%AA%E3%80%91"
    "5%E6%9C%8829%E6%97%A5%EF%BC%88%E9%87%91%EF%BC%891%E6%97%A5%E7%9B%AE9r%E4%B8%80/"
)
_NOTICES = {
    UTSUNOMIYA_NOTICE_URL: ("2025-02-17", "24", 10),
    KUMAMOTO_NOTICE_URL: ("2026-05-29", "87", 9),
}
_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img",
                        "input", "link", "meta", "param", "source", "track", "wbr"})
_IGNORED_TAGS = frozenset({"head", "script", "style", "template", "noscript"})


class RefundNoticeError(ValueError):
    """The source does not support this narrow notice contract."""


class RefundNoticeProviderStop(RefundNoticeError):
    """Provider refusal or rate limit: no retry or alternate route this run."""

    def __init__(self, status):
        self.status = status
        super().__init__(f"REFUND_NOTICE_PROVIDER_STOP_{status}")


def _need(ok, code):
    if not ok:
        raise RefundNoticeError(code)


def _known(url):
    _need(type(url) is str and url in _NOTICES, "REFUND_NOTICE_URL_UNREVIEWED")
    return _NOTICES[url]


def _aware(value):
    if type(value) is str:
        _need(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
                           r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value),
              "REFUND_NOTICE_TIMESTAMP_INVALID")
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise RefundNoticeError("REFUND_NOTICE_TIMESTAMP_INVALID") from None
    _need(isinstance(value, datetime) and value.utcoffset() is not None,
          "REFUND_NOTICE_TIMESTAMP_INVALID")
    return value


def _norm(value):
    value = unicodedata.normalize("NFKC", value).replace("、", ",")
    return re.sub(r"\s+", "", value)


class _Node:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []


class _Document(HTMLParser):
    """Small inert HTML tree; no CSS, JavaScript, images or links are fetched."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.node_count = 0
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.node_count += 1
        _need(self.node_count <= 20000 and len(self.stack) < 128,
              "REFUND_NOTICE_HTML_LIMIT_EXCEEDED")
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _hidden(node):
    style = _norm(node.attrs.get("style") or "").lower()
    return (node.tag in _IGNORED_TAGS or "hidden" in node.attrs or
            node.attrs.get("aria-hidden") == "true" or
            "display:none" in style or "visibility:hidden" in style)


def _walk(root):
    pending = [root]
    while pending:
        item = pending.pop()
        if isinstance(item, _Node) and _hidden(item):
            continue
        yield item
        if isinstance(item, _Node):
            pending.extend(reversed(item.children))


def _one(root, css_class, tag, *, optional=False):
    matches = [node for node in _walk(root) if isinstance(node, _Node) and
               node.tag == tag and css_class in (node.attrs.get("class") or "").split()]
    _need(len(matches) == 1 or (optional and not matches),
          "REFUND_NOTICE_ARTICLE_STRUCTURE_UNVERIFIED")
    return matches[0] if matches else None


def _text(root):
    return _norm("".join(item for item in _walk(root) if isinstance(item, str)))


def _match(pattern, text, code="REFUND_NOTICE_LITERAL_UNVERIFIED"):
    match = re.fullmatch(pattern, text)
    _need(match is not None, code)
    return match


def _same_day(day, month, number, weekday=None):
    _need(int(month) == day.month and int(number) == day.day and
          (weekday is None or weekday == "月火水木金土日"[day.weekday()]),
          "REFUND_NOTICE_IDENTITY_UNVERIFIED")


def _sentences(root, allowed_tail):
    parts = _text(root).split("。")
    _need(parts[-1] == "" and len(parts) >= 3, "REFUND_NOTICE_LITERAL_UNVERIFIED")
    parts.pop()
    tail = parts[2:]
    _need(len(tail) == len(set(tail)) and all(part in allowed_tail for part in tail),
          "REFUND_NOTICE_SUPPLEMENT_UNREVIEWED")
    return parts[:2]


def _utsunomiya(root, day, race_no):
    header = _text(_one(root, "date-header", "h2"))
    match = _match(r"(\d{4})年(\d{1,2})月(\d{1,2})日\(([月火水木金土日])\)", header)
    _need(int(match[1]) == day.year, "REFUND_NOTICE_IDENTITY_UNVERIFIED")
    _same_day(day, match[2], match[3], match[4])
    article = _one(root, "entry", "div")
    title = _text(_one(article, "entry-header", "h3"))
    match = _match(r"(\d{1,2})月(\d{1,2})日\(([月火水木金土日])\)宇都宮競輪"
                   r"\(FII\)初日・第(\d{1,2})レース中止のお知らせ", title)
    _same_day(day, match[1], match[2], match[3])
    _need(int(match[4]) == race_no, "REFUND_NOTICE_IDENTITY_UNVERIFIED")
    first, second = _sentences(_one(article, "entry-body", "div"), {
        "ご迷惑をおかけし大変申し訳ありませんが,ご了承ください"})
    match = _match(r"本日\((\d{1,2})/(\d{1,2})\)(?:開催しております,)?"
                   r"宇都宮競輪\(FII\)初日(?:について,出場選手の欠場により,|・)"
                   r"第(\d{1,2})レースは中止となりました", first)
    _same_day(day, match[1], match[2])
    _need(int(match[3]) == race_no, "REFUND_NOTICE_IDENTITY_UNVERIFIED")
    _match(r"(?:なお,)?購入された当該レースの車券につきましては,すべて返還となります", second)
    footer = _one(article, "post-footers", "span", optional=True)
    displayed_time = None
    if footer is not None:
        match = _match(r"投稿時刻((?:[01]\d|2[0-3]):[0-5]\d)(?:レース情報)?", _text(footer))
        displayed_time = match[1]
    return {"race_status": "CANCELLED", "finishers_reported": None,
            "market_scope": {"kind": "ALL_MARKETS", "markets": []},
            "source_published_at": None, "source_posted_time_displayed": displayed_time,
            "source_time_basis": "DATE_WITH_UNZONED_DISPLAY_TIME" if displayed_time else "DATE_ONLY"}


def _kumamoto(root, day, race_no, observed):
    article = _one(root, "c-post", "article")
    date_node = _one(article, "c-post__date", "time")
    _need(_text(date_node) == day.strftime("%Y.%m.%d"), "REFUND_NOTICE_IDENTITY_UNVERIFIED")
    title = _text(_one(article, "c-post__heading", "h1"))
    match = _match(r"【お知らせ\|熊本市営競輪】(\d{1,2})月(\d{1,2})日"
                   r"\(([月火水木金土日])\)1日目(\d{1,2})R一部返還のお知らせ", title)
    _same_day(day, match[1], match[2], match[3])
    _need(int(match[4]) == race_no, "REFUND_NOTICE_IDENTITY_UNVERIFIED")
    first, second = _sentences(_one(article, "c-editor", "div"), {
        "なお,車券の有効期限は60日間でございます",
        "お客様には大変ご迷惑をおかけいたしますことをお詫び申し上げますとともに,"
        "何卒ご理解賜りますようお願い申し上げます"})
    match = _match(r"本日(\d{1,2})月(\d{1,2})日\(([月火水木金土日])\)の"
                   r"熊本競輪\(FII・1日目\)第(\d{1,2})レースは,落車棄権のため,"
                   r"2車のみの入着となりました", first)
    _same_day(day, match[1], match[2], match[3])
    _need(int(match[4]) == race_no, "REFUND_NOTICE_IDENTITY_UNVERIFIED")
    match = _match(r"これに伴い,3連勝式\(([^)]+)\)に関する投票は不成立となり,"
                   r"返還させていただきます", second)
    labels = match[1].split("および")
    _need(len(labels) == 2 and set(labels) == {"3連勝複式", "3連勝単式"},
          "REFUND_NOTICE_MARKET_SCOPE_UNREVIEWED")
    published = None
    if "datetime" in date_node.attrs:
        published = _aware(date_node.attrs["datetime"])
        _need(published.astimezone(JST).date() == day and published <= observed,
              "REFUND_NOTICE_PUBLICATION_CLOCK_INCONSISTENT")
    return {"race_status": "FINISHERS_REPORTED", "finishers_reported": 2,
            "market_scope": {"kind": "MARKET_SET", "markets": ["TRIFECTA", "TRIO"]},
            "source_published_at": published.isoformat() if published else None,
            "source_posted_time_displayed": None,
            "source_time_basis": "HTML_ARTICLE_DATETIME" if published else "DATE_ONLY"}


def parse_refund_notice(snapshot, *, expected_race_id=None):
    """Parse literal claims from a private hash-bound snapshot; perform no I/O.

    ``source_published_at`` is a provider-declared article datetime only when a
    timezone-qualified HTML datetime exists. An unzoned wall time or date alone
    stays separate; neither becomes midnight, an inferred timezone, or proof of
    first publication. ``FULL_IN_SCOPE`` always refers to ``market_scope``.
    """
    _need(type(snapshot) is dict and set(snapshot) == {
        "url", "raw_bytes", "source_sha256", "observed_at"}, "REFUND_NOTICE_SNAPSHOT_INVALID")
    day_text, venue, race_no = _known(snapshot["url"])
    race_id = day_text.replace("-", "") + venue + f"{race_no:02d}"
    _need(expected_race_id is None or expected_race_id == race_id,
          "REFUND_NOTICE_EXPECTED_RACE_MISMATCH")
    raw, digest = snapshot["raw_bytes"], snapshot["source_sha256"]
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and type(digest) is str and
          re.fullmatch(r"[0-9a-f]{64}", digest) and sha256(raw).hexdigest() == digest,
          "REFUND_NOTICE_BYTES_OR_HASH_INVALID")
    _need(type(snapshot["observed_at"]) is str, "REFUND_NOTICE_TIMESTAMP_INVALID")
    observed, day = _aware(snapshot["observed_at"]), date.fromisoformat(day_text)
    _need(observed.astimezone(JST).date() >= day, "REFUND_NOTICE_OBSERVATION_BEFORE_EVENT")
    try:
        root = _Document(raw.decode("utf-8-sig")).root
    except UnicodeError:
        raise RefundNoticeError("REFUND_NOTICE_UTF8_REQUIRED") from None
    claims = (_utsunomiya(root, day, race_no) if venue == "24" else
              _kumamoto(root, day, race_no, observed))
    return {
        "schema": SCHEMA, "state": STATE, "race_id": race_id,
        "day_jst": day_text, "venue_code": venue, "race_no": race_no,
        **claims, "refund_status": "FULL_IN_SCOPE", "source_url": snapshot["url"],
        "source_sha256": digest, "observed_at": observed.isoformat(),
        "source_available_no_later_than": observed.isoformat(),
        "source_published_date": day_text, "source_first_publication_verified": False,
        "settlement_e2e_verified": False, "snapshot": deepcopy(snapshot),
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RefundNoticeError("REFUND_NOTICE_REDIRECT_NOT_FOLLOWED")


def _http_get(url):
    _known(url)
    with build_opener(_NoRedirect()).open(url, timeout=TIMEOUT_SECONDS) as response:
        _need(response.status == 200 and response.url == url, "REFUND_NOTICE_HTTP_RESPONSE_INVALID")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        _need(content_type == "text/html", "REFUND_NOTICE_HTML_CONTENT_TYPE_REQUIRED")
        return response.read(MAX_BYTES + 1)


def fetch_refund_notice(url, *, fetcher=None, clock=None, expected_race_id=None):
    """One bounded ordinary TLS GET; no auth, redirects, retry or fallback route."""
    _known(url)
    try:
        raw = (fetcher or _http_get)(url)
    except HTTPError as exc:
        if exc.code in (403, 429):
            raise RefundNoticeProviderStop(exc.code) from None
        raise RefundNoticeError(f"REFUND_NOTICE_HTTP_{exc.code}") from None
    except (URLError, OSError, TimeoutError):
        raise RefundNoticeError("REFUND_NOTICE_TRANSPORT_UNAVAILABLE") from None
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "REFUND_NOTICE_SOURCE_SIZE_INVALID")
    stamp = _aware(clock() if clock else datetime.now(timezone.utc)).isoformat()
    snapshot = {"url": url, "raw_bytes": raw, "source_sha256": sha256(raw).hexdigest(),
                "observed_at": stamp}
    return parse_refund_notice(snapshot, expected_race_id=expected_race_id)


def _canonical_claims(receipt):
    return json.dumps({key: value for key, value in receipt.items() if key != "snapshot"},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def reparse_refund_notice(receipt):
    """Check every normalized field against the saved HTML, not a signature."""
    try:
        if type(receipt) is not dict:
            return False
        rebuilt = parse_refund_notice(receipt["snapshot"])
        return receipt == rebuilt and _canonical_claims(receipt) == _canonical_claims(rebuilt)
    except (RefundNoticeError, KeyError, TypeError, ValueError, AttributeError, RecursionError,
            OverflowError):
        return False


def summarize_refund_notices(receipts):
    """Return only fixed state, counts and hashes; never claim settlement E2E."""
    _need(type(receipts) is list and 1 <= len(receipts) <= len(_NOTICES) and
          all(reparse_refund_notice(item) for item in receipts), "REFUND_NOTICE_RECEIPTS_INVALID")
    _need(len({item["source_url"] for item in receipts}) == len(receipts),
          "REFUND_NOTICE_DUPLICATE_SOURCE")
    return {
        "state": STATE, "verified_notice_count": len(receipts),
        "cancelled_race_notice_count": sum(item["race_status"] == "CANCELLED" for item in receipts),
        "market_scoped_notice_count": sum(item["market_scope"]["kind"] == "MARKET_SET"
                                           for item in receipts),
        "source_sha256": sorted(item["source_sha256"] for item in receipts),
        "receipt_sha256": sorted(sha256(_canonical_claims(item)).hexdigest() for item in receipts),
        "settlement_e2e_count": 0,
    }
