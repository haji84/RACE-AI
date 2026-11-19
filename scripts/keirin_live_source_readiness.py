"""Read-only fail-closed gate for existing PR71 owner-source acquisition.

The operator already approved limited personal WINTICKET/KEIRIN.JP public-page
research. The producer's earlier _licensed_inputs() implements that fallback
independently of the optional authenticated JSON export. Do not reclassify
optional API/contract secrets as mandatory for this existing OWNER mode.

This checks configuration only, not provider terms, an actual data license,
model completeness, official outcomes, forecasts, or live timing. Private
owner collector retains its host allowlist, 403/429 stop circuit, limited
work budget, private temp-only storage and no model promotion.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from scripts.keirin_cloud_owner_inputs import PROFILE

SCHEMA = "RACE_AI_KEIRIN_LIVE_PILOT_SOURCE_CONFIGURATION_V1"
KEY = "RACE_AI_STATE_KEY"
PROVIDER_KEYS = (
    "RACE_AI_KEIRIN_FEED_ENDPOINT",
    "RACE_AI_KEIRIN_FEED_RIGHTS_REF",
    "RACE_AI_KEIRIN_LICENSE_MANIFEST_B64",
    "RACE_AI_KEIRIN_LICENSE_DOCUMENT_B64",
)
REQUIRED = (KEY, *PROVIDER_KEYS)  # diagnostic vocabulary, not universal mandatory keys


def assess(environ):
    key_present = bool(environ.get(KEY))
    provider_present = [name for name in PROVIDER_KEYS if environ.get(name)]
    provider_complete = len(provider_present) == len(PROVIDER_KEYS)
    provider_partial = bool(provider_present) and not provider_complete
    owner_profile = environ.get("RACE_AI_OWNER_AUTO_SOURCE_PROFILE") == PROFILE

    # Priority matches the trusted producer: configured authorized export first,
    # otherwise the explicitly opted-in owner collector. An incomplete provider
    # bundle is an operator configuration error, not a fallback permission grant.
    if not key_present:
        status, mode, eligible = "HOLD_NO_PRIVATE_AES_KEY", "NONE", False
    elif provider_partial:
        status, mode, eligible = "HOLD_PARTIAL_PROVIDER_CONFIG", "NONE", False
    elif provider_complete:
        status = "PROVIDER_CONFIG_PRESENT_INDEPENDENT_ADMISSION_REQUIRED"
        mode, eligible = "EXISTING_PROVIDER_JSON_EXPORT", True
    elif owner_profile:
        status = "OWNER_APPROVED_PUBLIC_RESEARCH_CANDIDATE_COLLECTION_ONLY"
        mode, eligible = "EXISTING_OWNER_PUBLIC_PAGE_RESEARCH", True
    else:
        status, mode, eligible = "HOLD_NO_ENABLED_OWNER_OR_PROVIDER_SOURCE", "NONE", False

    return {
        "schema": SCHEMA,
        "status": status,
        "source_mode": mode,
        "missing_config_names": (
            [KEY] if not key_present else
            [k for k in PROVIDER_KEYS if not environ.get(k)]
            if provider_partial else []
        ),
        "optional_provider_config_unset_count": len(PROVIDER_KEYS) - len(provider_present),
        "eligible_to_attempt_existing_owner_admission": eligible,
        "owner_profile_attested_by_existing_configuration": owner_profile,
        "source_rights_verified": False,
        "complete_model_inputs_verified": False,
        "real_race_15min_proven": False,
        "official_result_authenticated": False,
        "provider_requests_by_readiness": 0,
    }


def main():
    verdict = assess(os.environ)
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        p = Path(output)
        if not p.is_file() or p.is_symlink():
            raise SystemExit("GITHUB_OUTPUT_UNAVAILABLE")
        with p.open("a", encoding="utf-8") as out:
            out.write("eligible=" + (
                "true" if verdict["eligible_to_attempt_existing_owner_admission"]
                else "false") + "\n")
    print(json.dumps(verdict, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
