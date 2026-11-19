"""Conservative observed third-party trifecta results, NEVER organizer-certified.

Kdreams + netkeirin public HTML can supply a research result candidate.
Both must have the same real race ID/date, winning triple and 100-yen payout.
Official organizer settlement remains a separate authenticated intake gate.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit
import re
import unicodedata

SCHEMA = "RACE_AI_KEIRIN_INDEPENDENT_SECONDARY_RESULT_MATCH_V1"
RID = re.compile(r"^20[0-9]{10}$")
KD_PATH = re.compile(
    r"^/[a-z0-9-]+/racedetail/([0-9]{2})(20[0-9]{6})([0-9]{2})00([0-9]{2})/$")
JPN_DAY = re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日")
TRIFECTA = re.compile(
    r"(?:3連単|三連単)\s*(?:払戻|結果)?\s*"
    r"([1-9])\s*(?:>|-|→|ー|－)\s*([1-9])\s*(?:>|-|→|ー|－)\s*([1-9])"
    r"\s*(?:的中|配当|払戻|:|：)?\s*([1-9][0-9,]{0,11})\s*円")
# Kdreams payout grid separates '3連単' and the winning trio into
# distant cells. An odds listing has no 円 amount; require a paid triple.
KD_TRIFECTA_PAYOUT = re.compile(
    r"(?<!\d)([1-9])\s*[-－→>]\s*([1-9])\s*[-－→>]\s*([1-9])"
    r"\s+([1-9][0-9,]{0,11})\s*円")
MAX_BYTES = 6_000_000


class ResultConsensusError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ResultConsensusError(code)


def check_race_url(*, provider, url, race_id):
    require(type(race_id) is str and RID.fullmatch(race_id),
            "RESULT_RACE_ID_INVALID")
    day = date.fromisoformat(
        f"{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}")
    require(type(url) is str and len(url) < 2048,
            "RESULT_SOURCE_URL_REQUIRED")
    parts = urlsplit(url)
    require(parts.scheme == "https" and
            parts.username is None and parts.password is None and
            parts.port is None and parts.fragment == "",
            "RESULT_URL_NOT_SAFE")
    if provider == "netkeirin":
        require(parts.hostname == "keirin.netkeiba.com" and
                parts.path == "/race/result/" and
                parse_qs(parts.query) == {"race_id":[race_id]},
                "NETKEIRIN_RESULT_RACE_LINK_INVALID")
    elif provider == "Kdreams":
        found = KD_PATH.fullmatch(parts.path)
        require(parts.hostname == "keirin.kdreams.jp" and
                found is not None and parts.query in ("", "pageType=result"),
                "KDREAMS_RESULT_LINK_INVALID")
        code, begin, ordinal, number = found.groups()
        try:
            from datetime import timedelta
            actual = (date.fromisoformat(
                f"{begin[:4]}-{begin[4:6]}-{begin[6:8]}") +
                timedelta(days=int(ordinal)-1))
        except ValueError:
            raise ResultConsensusError("KDREAMS_EVENT_DATE_INVALID") from None
        require(code == race_id[8:10] and number == race_id[10:12] and
                actual == day, "KDREAMS_URL_OTHER_RACE")
    else:
        raise ResultConsensusError("UNSUPPORTED_RESULT_PROVIDER")
    return True


def normalize_html(value):
    require(type(value) is bytes and 0 < len(value) <= MAX_BYTES,
            "RESULT_HTML_BYTES_MISSING_OR_OVERSIZED")
    from bs4 import BeautifulSoup
    try:
        text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
        return unicodedata.normalize("NFKC", text)
    except (UnicodeError, TypeError, ValueError):
        raise ResultConsensusError("RESULT_HTML_NOT_READABLE") from None


def parse_observation(*, raw, provider, source_url, race_id, observed_at):
    """Extract one clear finished race, or hold. Never infer a publication time."""
    check_race_url(provider=provider, url=source_url, race_id=race_id)
    require(type(observed_at) is str, "RESULT_OBSERVATION_TIME_REQUIRED")
    try:
        at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        raise ResultConsensusError("RESULT_OBSERVATION_TIME_INVALID") from None
    require(at.utcoffset() is not None, "RESULT_TIMEZONE_REQUIRED")
    text = normalize_html(raw)
    day = f"{int(race_id[:4])}年{int(race_id[4:6])}月{int(race_id[6:8])}日"
    displayed = {
        f"{int(y)}年{int(m)}月{int(d)}日"
        for y,m,d in JPN_DAY.findall(text)}
    require(day in displayed, "SOURCE_HTML_WRONG_OR_UNKNOWN_DAY")
    require(re.search(r"(?<!\d)" + str(int(race_id[10:12])) +
                      r"\s*R(?!\d)", text, flags=re.I),
            "SOURCE_HTML_RACE_NUMBER_MISSING")
    require("払戻" in text and ("結果" in text or "確定" in text),
            "SOURCE_HTML_NOT_FINAL_RESULT_PAGE")
    if any(k in text for k in ("レース中止", "発売中止", "返還", "同着")):
        raise ResultConsensusError("SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL")
    matches = []
    apparent = TRIFECTA.findall(text)
    if provider == "Kdreams":
        # The actual grid sometimes emits '... 単 7-3-4 5,590円'
        # while the 3連単 label is in a different column.
        apparent += KD_TRIFECTA_PAYOUT.findall(text)
    for a,b,c,yen in apparent:
        order = [int(a),int(b),int(c)]
        if len(set(order)) != 3:
            continue
        amount = int(yen.replace(",", ""))
        if 100 <= amount <= 1_000_000_000:
            matches.append((tuple(order),amount))
    # Never choose one of several conflicting apparent results in the same HTML.
    require(len(matches) > 0, "TRIFECTA_RESULT_NOT_PUBLISHED")
    require(len(set(matches)) == 1, "MULTIPLE_CONFLICTING_TRIFECTA_VALUES")
    tickets, payout = matches[0]
    return {
        "race_id":race_id, "provider":provider,
        "source_url":source_url,
        "source_bytes_sha256":sha256(raw).hexdigest(),
        "observed_at":observed_at,
        "winning_triple":list(tickets),
        "payout_per_100yen":payout,
        "source_published_at":"UNVERIFIED",
        "official_organizer_result":False,
    }


def compare_sources(first, second):
    require(type(first) is dict and type(second) is dict and
            first.get("race_id") == second.get("race_id") and
            {first.get("provider"),second.get("provider")} ==
            {"Kdreams","netkeirin"}, "DISTINCT_PROVIDERS_SAME_RACE_REQUIRED")
    match = (first["winning_triple"] == second["winning_triple"] and
             first["payout_per_100yen"] == second["payout_per_100yen"])
    return {
        "schema":SCHEMA,
        "race_id":first["race_id"],
        "state":("SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL" if match else
                 "HOLD_SECONDARY_RESULT_DISAGREEMENT"),
        "winning_triple":first["winning_triple"] if match else None,
        "payout_per_100yen":first["payout_per_100yen"] if match else None,
        "provider_receipts":[{
            "provider":obs["provider"],
            "source_bytes_sha256":obs["source_bytes_sha256"],
            "observed_at":obs["observed_at"],
            "source_url":obs["source_url"]} for obs in (first,second)],
        "official_primary_result_authenticated":False,
        "actual_organizer_cutoff_authenticated":False,
        "qualifies_for_formal_settlement":False,
    }
