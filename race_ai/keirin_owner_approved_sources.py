"""Owner-approved public reference sources for PRIVATE manual KEIRIN research.

User confirmed on 2026-11-09 that WINTICKET and KEIRIN.JP can be used.
This selects exact domain names for existing *owner-saved* observations.
It does not certify an upstream license for automated requests, API reverse
engineering, redistribution, paid distribution, or source bulk archival.

All collection is offline/manual until a separately authenticated machine
acquisition grant exists. Public exposure of production AES-GCM ciphertext
is a different, independently scoped owner instruction.
"""
from __future__ import annotations

from urllib.parse import urlsplit

PROFILE_ID = "owner-approved-winticket-keirinjp-20261109"
PROFILE_HOSTS = (
    "keirin.jp",
    "www.keirin.jp",
    "winticket.jp",
    "www.winticket.jp",
)
VALID_HOSTS = frozenset(PROFILE_HOSTS)
RESEARCH_PURPOSES = frozenset((
    "schedule", "pre_race", "analysis", "model_inference",
    "private_retention",
))


class OwnerApprovedSourceError(ValueError):
    pass


def approved_source_hosts(profile):
    if profile != PROFILE_ID:
        raise OwnerApprovedSourceError("UNKNOWN_OWNER_SOURCE_PROFILE")
    return PROFILE_HOSTS


def classify_owner_source(url):
    """Pure, strict URL admission; never calls a webpage or confers a licence."""
    if type(url) is not str or len(url) > 2048:
        return "INVALID_SOURCE_URL"
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.port not in (None, 443)
                or parts.username or parts.password or parts.fragment):
            return "INVALID_SOURCE_URL"
        host = (parts.hostname or "").lower().rstrip(".")
        if host not in VALID_HOSTS:
            return "SOURCE_NOT_IN_OWNER_PROFILE"
        return "OWNER_APPROVED_PRIVATE_MANUAL_REFERENCE_ONLY"
    except ValueError:
        return "INVALID_SOURCE_URL"


def owner_approved_source_profile():
    return {
        "schema": "RACE_AI_KEIRIN_OWNER_SOURCE_APPROVAL_V1",
        "profile_id": PROFILE_ID,
        "source_hosts": list(PROFILE_HOSTS),
        "source_ids": ["keirin_official", "winticket"],
        "allowed_context": "OWNER_PERSONAL_OFFLINE_RESEARCH",
        "owner_confirmed_date_jst": "2026-11-09",
        "direct_html_machine_fetch_authorized": False,
        "third_party_api_authorized": False,
        "commercial_or_redistribution_authorized": False,
        "no_unlicensed_scraping": True,
        "real_forecast_or_pre_cutoff_witness_proven": False,
    }
