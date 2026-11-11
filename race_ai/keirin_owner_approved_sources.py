"""Owner-approved WINTICKET and KEIRIN.JP sources for private RACE-AI research.

On 2026-11-09 the owner confirmed that automatic acquisition is allowed.
An explicit owner-attested mode can now request approved, provided URLs.
This is NOT independent provider licensing or permission to bypass access
controls, probe undocumented internal APIs or redistribute source content.
GitHub public AES-GCM ciphertext consent is a separate instruction.
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
        "allowed_context": "OWNER_PERSONAL_RESEARCH_INCLUDING_ATTESTED_AUTOMATED_FETCH",
        "owner_confirmed_automated_fetch": True,
        "provider_machine_permission_independently_verified": False,
        "owner_confirmed_date_jst": "2026-11-09",
        "direct_html_machine_fetch_authorized": False,
        "third_party_api_authorized": False,
        "commercial_or_redistribution_authorized": False,
        "no_unlicensed_scraping": True,
        "real_forecast_or_pre_cutoff_witness_proven": False,
    }
