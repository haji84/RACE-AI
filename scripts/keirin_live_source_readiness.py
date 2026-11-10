"""Read-only GitHub Actions gate for the first real KEIRIN race pilot.

Config presence does NOT establish rights, a forecast, actual start, or a
source receipt. The existing pinned owner-source admission is the only
boundary allowed to ingest any provider data. Do not log secret values.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

SCHEMA = "RACE_AI_KEIRIN_LIVE_PILOT_SOURCE_CONFIGURATION_V1"
REQUIRED = (
    "RACE_AI_STATE_KEY",
    "RACE_AI_KEIRIN_FEED_ENDPOINT",
    "RACE_AI_KEIRIN_FEED_RIGHTS_REF",
    "RACE_AI_KEIRIN_LICENSE_MANIFEST_B64",
    "RACE_AI_KEIRIN_LICENSE_DOCUMENT_B64",
)


def assess(environ):
    missing = [name for name in REQUIRED if not environ.get(name)]
    return {
        "schema": SCHEMA,
        "status": ("SOURCE_CONFIG_PRESENT_ADMISSION_STILL_REQUIRED"
                   if not missing else "HOLD_MISSING_TRUSTED_SOURCE_CONFIGURATION"),
        "missing_config_names": missing,
        "eligible_to_attempt_existing_owner_admission": not missing,
        "source_rights_verified": False,
        "real_race_15min_proven": False,
        "official_result_authenticated": False,
        "provider_requests_by_readiness": 0,
    }


def main():
    verdict = assess(os.environ)
    # These outputs contain boolean and reason names only, never secret data.
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
