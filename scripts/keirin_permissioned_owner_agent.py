"""Private, local-source KEIRIN permitted-delivery -> actual PR71 -> PDCA.

No public-provider GET, scraping, automation of buying, or implicit data
licensing. Requires owner-reviewed, private source-authorisation documents.
The licensed feeder MUST separately place bounded packets into inbox/raw.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from race_ai.keirin_owner_sqlite import PrivateKeirinStore, OwnerStoreError
from race_ai.keirin_private_spool import KeirinPrivateSpool, InboxError
from race_ai.keirin_permissioned_owner import (
    LicenseDeliveryError, load_operator_grants, stage_permissioned_deliveries
)
from race_ai.four_sport_model_suite import run_suite, verify_suite


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--grant-manifest", required=True)
    parser.add_argument("--operator-reviewed-licenses", action="store_true",
                        help="Owner verified origin, permitted purposes and expiry out-of-band")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    if not args.operator_reviewed_licenses or not 60 <= args.interval_seconds <= 3600:
        print('{"state":"SOURCE_LICENSE_REVIEW_NOT_ACKNOWLEDGED"}')
        return 2
    db = Path(args.db).expanduser()
    inbox = Path(args.inbox).expanduser()
    manifest = Path(args.grant_manifest).expanduser()
    if not all(x.is_absolute() for x in (db, inbox, manifest)):
        print('{"state":"ABSOLUTE_PRIVATE_PATHS_REQUIRED"}')
        return 2
    if os.environ.get("GITHUB_ACTIONS") == "true" and (
        os.environ.get("RACE_AI_PERSISTENT_PRIVATE_VOLUME") != "ACKNOWLEDGED"
    ):
        print('{"state":"GITHUB_EPHEMERAL_DB_NOT_DURABLE"}')
        return 2
    # Explicitly reject accidental writes of private source files into the
    # public GitHub working tree. No public repo files contain raw originals.
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        public_root = Path(workspace).resolve()
        for p in (db, inbox, manifest):
            if p.resolve() == public_root or public_root in p.resolve().parents:
                print('{"state":"PUBLIC_WORKSPACE_PRIVATE_SOURCE_FORBIDDEN"}')
                return 2
    try:
        with PrivateKeirinStore(db) as store:
            while True:
                now = datetime.now(timezone.utc).isoformat()
                # Reload grants every cycle; expired rights never remain valid
                # in an unattended long-running process.
                grants = load_operator_grants(manifest, now=now)
                stage = stage_permissioned_deliveries(inbox, grants, now=now)
                engine = KeirinPrivateSpool(
                    store, model_suite=run_suite, model_verifier=verify_suite,
                    source_observation_gate=grants.allowed,
                    source_attestor=grants.certificate,
                    witness=None,  # Private research until independent receipt.
                )
                settled = engine.tick(inbox)
                # No filenames, source URLs, rider names, or buy picks in logs.
                print(json.dumps({
                    "schema": "RACE_AI_KEIRIN_LICENSED_LOCAL_CYCLE_V1",
                    "stage": stage, "spool": settled,
                    "automatic_provider_fetch": False,
                    "official_pre_cutoff_witness": False,
                    "licensed_rights_verified_by_program": False,
                    "commercial_use_authorized_by_program": False,
                }, ensure_ascii=False, sort_keys=True), flush=True)
                if not args.loop:
                    break
                time.sleep(args.interval_seconds)
    except (LicenseDeliveryError, OwnerStoreError, InboxError,
            OSError, ValueError, KeyError, TypeError):
        print('{"state":"LICENSED_OWNER_CYCLE_FAILED_CLOSED"}')
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
