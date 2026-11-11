"""Owner-attested automatic retrieval scope for WINTICKET and KEIRIN.JP.

The owner explicitly confirmed on 2026-11-09 that automated collection is
allowed for these two sources in their private research. This accepts the
owner's claim without inventing a vendor API endpoint, authentication token,
legal contract, or commercial reuse rights. A provider-specific restriction
or 429/403 must still be respected. Never discover private/internal APIs.
"""
from __future__ import annotations

from .keirin_owner_manual import PersonalOwnerObservations, PERSONAL_MARKER
from .keirin_owner_approved_sources import (
    PROFILE_ID, PROFILE_HOSTS, classify_owner_source,
)

AUTOMATION_CONSENT = "OWNER_CONFIRMED_WINTICKET_KEIRINJP_AUTOMATED_USE_20261109"
PURPOSE = "automated_fetch"


class OwnerAutomationError(ValueError):
    pass


class OwnerAttestedAutomaticSources(PersonalOwnerObservations):
    """Exact official hosts, private research only; no automatic legal certification."""

    def __init__(self, *, profile, consent, now):
        if profile != PROFILE_ID or consent != AUTOMATION_CONSENT:
            raise OwnerAutomationError("EXPLICIT_OWNER_AUTO_SOURCE_SCOPE_REQUIRED")
        super().__init__(source_hosts=PROFILE_HOSTS, now=now)
        self.owner_automated_use_attested = True
        self.provider_terms_independently_verified = False
        self.commercial_redistribution_allowed = False

    def allowed(self, source_url, rights_ref, purpose):
        if purpose == PURPOSE:
            return (rights_ref == PERSONAL_MARKER
                    and classify_owner_source(source_url) ==
                    "OWNER_APPROVED_PRIVATE_MANUAL_REFERENCE_ONLY")
        return super().allowed(source_url, rights_ref, purpose)

    def acquisition_status(self):
        return {
            "schema": "RACE_AI_KEIRIN_OWNER_ATTESTED_AUTOMATED_SOURCE_V1",
            "profile": PROFILE_ID,
            "owner_confirmed_automated_retrieval": True,
            "actual_provider_machine_permission_independently_verified": False,
            "provider_endpoint_discovered_or_invented": False,
            "source_hosts": list(PROFILE_HOSTS),
            "commercial_or_redistribution_permitted": False,
            "published_site_rate_limits_still_apply": True,
            "public_github_plaintext_permitted": False,
        }
