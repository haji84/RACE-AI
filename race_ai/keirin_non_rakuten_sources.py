"""KEIRIN sources outside Rakuten. A catalog is not provider API proof.

The owner confirmed WINTICKET and KEIRIN.JP can be automatically read for
personal research on 2026-11-09; other sites remain unverified. The exact
automated intake is explicitly opt-in and must not bypass provider rate limits,
access controls, or infer commercial redistribution rights.
No HTTP calls in this pure source classifier.
"""
from __future__ import annotations

from urllib.parse import urlsplit

RAKUTEN_SUFFIXES = (
    "rakuten.co.jp", "rakuten.com", "kdreams.jp",
    "rakuten-bank.co.jp", "rakuten-card.co.jp",
)

# User-visible source shortlist; availability does NOT constitute permission.
# "direct_data" is a *possible* field category, not a claim that any live
# feed yields every item. The URLs below are official product help pages.
SOURCE_CATALOG = (
    {
        "source_id": "keirin_official",
        "name": "KEIRIN.JP",
        "hosts": ("keirin.jp", "www.keirin.jp"),
        "evidence_url": "https://keirin.jp/pc/dfw/portal/guest/policy/index.html",
        "direct_data": ("official_schedule", "racecard", "race_score",
                        "decisive_style", "rider_grade", "race_results"),
        "automated_machine_collection_status": "OWNER_ATTESTED_PERSONAL_USE_PROVIDER_PROOF_UNVERIFIED",
    },
    {
        "source_id": "winticket",
        "name": "WINTICKET",
        "hosts": ("winticket.jp", "www.winticket.jp"),
        "evidence_url": "https://www.winticket.jp/keirin/topics/9f4QV3dmkfQ8CZtLr1Fb52",
        "direct_data": ("race_score", "recent_10_results", "venue_record",
                        "head_to_head", "published_comments", "score_trend"),
        "automated_machine_collection_status": "OWNER_ATTESTED_PERSONAL_USE_PROVIDER_PROOF_UNVERIFIED",
    },
    {
        "source_id": "oddspark",
        "name": "オッズパーク",
        "hosts": ("oddspark.com", "www.oddspark.com", "sp.oddspark.com"),
        "evidence_url": "https://sp.oddspark.com/keirin/service/racelist/mikata.html",
        "direct_data": ("racecard", "race_score", "recent_results",
                        "S_H_B", "decisive_style", "gear_ratio",
                        "conditional_history"),
        "automated_machine_collection_status": "UNVERIFIED",
    },
    {
        "source_id": "chariloto",
        "name": "チャリロト",
        "hosts": ("chariloto.com", "www.chariloto.com"),
        "evidence_url": "https://www.chariloto.com/articles/6184",
        "direct_data": ("racecard", "race_score", "recent_10_results", "S_B"),
        "automated_machine_collection_status": "UNVERIFIED",
    },
    {
        "source_id": "keirin_hex",
        "name": "KEIRIN HEX",
        "hosts": ("keirinhex.jp", "www.keirinhex.jp"),
        "evidence_url": "https://keirinhex.jp/",
        "direct_data": ("pre_race_line_guess", "racecard", "race_score",
                        "starter_counts", "S_H_B", "style_counts",
                        "gear_ratio", "bank_geometry"),
        "automated_machine_collection_status": "UNVERIFIED",
    },
    {
        "source_id": "netkeirin",
        "name": "netkeirin",
        "hosts": ("keirin.netkeiba.com", "keirin.netkeiba.net"),
        "evidence_url": "https://keirin.netkeiba.com/info/kiyaku/",
        "direct_data": ("schedule", "racecard", "published_rider_results"),
        "automated_machine_collection_status": "UNVERIFIED",
    },
    {
        "source_id": "jma",
        "name": "気象庁",
        "hosts": ("data.jma.go.jp", "www.data.jma.go.jp",
                  "ds.data.jma.go.jp"),
        "evidence_url": "https://www.data.jma.go.jp/risk/obsdl/",
        "direct_data": ("weather_observations", "rain", "wind",
                        "temperature", "humidity"),
        "automated_machine_collection_status": "UNVERIFIED",
    },
)


def _hostname(url):
    if type(url) is not str or len(url) > 2048:
        return None
    try:
        u = urlsplit(url)
        return (u.hostname or "").lower().rstrip(".") if (
            u.scheme == "https" and u.username is None and
            u.password is None and u.port in (None, 443)) else None
    except ValueError:
        return None


def is_rakuten_domain(host):
    if not isinstance(host, str):
        return False
    host = host.lower().rstrip(".")
    return any(host == x or host.endswith("." + x)
               for x in RAKUTEN_SUFFIXES)


def is_rakuten_url(url):
    host = _hostname(url)
    return host is not None and is_rakuten_domain(host)


def source_id(url):
    """Return a known non-Rakuten origin only; never authorize collection."""
    host = _hostname(url)
    if not host or is_rakuten_domain(host):
        return None
    for source in SOURCE_CATALOG:
        if host in source["hosts"]:
            return source["source_id"]
    return None


def non_rakuten_source_status(url):
    host = _hostname(url)
    if host is None:
        return "INVALID_SOURCE_URL"
    if is_rakuten_domain(host):
        return "RAKUTEN_SOURCE_EXCLUDED_BY_OWNER"
    if source_id(url) is not None:
        return "NON_RAKUTEN_CANDIDATE_NOT_MACHINE_AUTHORIZED"
    return "NON_RAKUTEN_UNKNOWN_SOURCE_NEEDS_REVIEW"
