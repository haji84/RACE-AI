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
from race_ai.keirin_licensed_api_ingest import fetch_licensed_export_once
from race_ai.keirin_owner_manual import PersonalOwnerObservations
from race_ai.keirin_owner_saved_csv import stage_owner_saved_csv
from race_ai.keirin_owner_odds_csv import (
    stage_owner_saved_odds_csv, OwnerOddsCsvError
)
from race_ai.keirin_owner_saved_hex import stage_owner_saved_hex_markdown
from race_ai.keirin_real_shadow_intake import stage_sourced_shadows
from race_ai.keirin_shadow_variable_intake import (
    ShadowPairIntakeError, stage_shadow_variable_pairs
)
from race_ai.keirin_open_meteo_stage import stage_one_free_weather


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--grant-manifest")
    parser.add_argument("--personal-manual", action="store_true",
                        help="consume locally owner-captured data only; NO API, NO provider GET")
    parser.add_argument("--owner-private-use-confirmed", action="store_true",
                        help="operator asserts use is limited to private personal research")
    parser.add_argument("--personal-source-host", action="append",
                        help="exact HTTPS host shown in owner's manual source material")
    parser.add_argument("--operator-reviewed-licenses", action="store_true",
                        help="Owner verified origin, permitted purposes and expiry out-of-band")
    parser.add_argument("--provider-endpoint", default=None,
                        help="explicitly licensed machine JSON feed endpoint; omitted means NO HTTP")
    parser.add_argument("--provider-rights-ref", default=None,
                        help="exact machine-acquisition rights reference in private grant")
    parser.add_argument("--api-token-env", default=None,
                        help="environment VARIABLE NAME containing optional provider bearer token")
    parser.add_argument("--free-modelled-weather", action="store_true",
                        help="opt-in noncommercial one Open-Meteo modeled grid forecast per race")
    parser.add_argument("--venue-coordinates-file",
                        help="private verified coordinates, source URL and venue keys")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    if bool(args.free_modelled_weather) != bool(args.venue_coordinates_file):
        print('{"state":"WEATHER_OPTIN_AND_OWNER_LOCATION_REQUIRED"}')
        return 2
    if args.free_modelled_weather and not args.personal_manual:
        print('{"state":"WEATHER_PRIVATE_NONCOMMERCIAL_SCOPE_REQUIRED"}')
        return 2
    if args.personal_manual:
        if (not args.owner_private_use_confirmed or
            not args.personal_source_host or args.provider_endpoint or
            args.provider_rights_ref or args.api_token_env or
            args.grant_manifest or args.operator_reviewed_licenses):
            print('{"state":"OWNER_MANUAL_ONLY_OR_PRIVATE_SCOPE_NOT_CONFIRMED"}')
            return 2
    elif (not args.operator_reviewed_licenses or
          not args.grant_manifest or args.personal_source_host or
          args.owner_private_use_confirmed):
        print('{"state":"SOURCE_LICENSE_REVIEW_NOT_ACKNOWLEDGED"}')
        return 2
    if bool(args.provider_endpoint) != bool(args.provider_rights_ref):
        print('{"state":"INCOMPLETE_LICENSED_PROVIDER_CONFIG"}')
        return 2
    if args.api_token_env is not None and (
            not args.provider_endpoint or
            not args.api_token_env.replace("_", "").isalnum() or
            len(args.api_token_env) > 100):
        print('{"state":"INVALID_PRIVATE_API_TOKEN_ENV"}')
        return 2
    if not 60 <= args.interval_seconds <= 3600:
        print('{"state":"INVALID_RESEARCH_INTERVAL"}')
        return 2
    db = Path(args.db).expanduser()
    inbox = Path(args.inbox).expanduser()
    manifest = Path(args.grant_manifest).expanduser() if args.grant_manifest else None
    coords = (Path(args.venue_coordinates_file).expanduser()
              if args.venue_coordinates_file else None)
    owner_paths=(db,inbox)+((manifest,) if manifest else ()) + ((coords,) if coords else ())
    if not all(x.is_absolute() for x in owner_paths):
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
        for p in owner_paths:
            if p.resolve() == public_root or public_root in p.resolve().parents:
                print('{"state":"PUBLIC_WORKSPACE_PRIVATE_SOURCE_FORBIDDEN"}')
                return 2
    try:
        with PrivateKeirinStore(db) as store:
            while True:
                now = datetime.now(timezone.utc).isoformat()
                # Reload grants every cycle; expired rights never remain valid
                # in an unattended long-running process.
                grants = (PersonalOwnerObservations(
                    source_hosts=args.personal_source_host, now=now,
                    allow_noncommercial_modelled_weather=args.free_modelled_weather)
                    if args.personal_manual else
                    load_operator_grants(manifest, now=now))
                fetch_report = None
                if args.provider_endpoint:
                    token = (os.environ.get(args.api_token_env)
                             if args.api_token_env else None)
                    if args.api_token_env and not token:
                        print('{"state":"LICENSED_FEED_TOKEN_UNCONFIGURED"}')
                        return 2
                    fetch_report = fetch_licensed_export_once(
                        inbox, grants,
                        endpoint=args.provider_endpoint,
                        rights_ref=args.provider_rights_ref,
                        token=token,
                    )
                owner_markdown = (stage_owner_saved_hex_markdown(inbox, now=now)
                                  if args.personal_manual else None)
                owner_csv = (stage_owner_saved_csv(inbox, now=now)
                             if args.personal_manual else None)
                # This does NOT fetch a market. Owner-supplied permitted
                # full-odds CSV is only staged after 210/504 completeness,
                # SHA, cutoff and distinct source admission have passed.
                owner_odds_csv = stage_owner_saved_odds_csv(
                    inbox,grant_check=grants.allowed,now=now)
                modelled_weather = (
                    stage_one_free_weather(inbox,coords,now=now)
                    if args.free_modelled_weather else None)
                stage = stage_permissioned_deliveries(inbox, grants, now=now)
                shadow = stage_sourced_shadows(
                    inbox,grant_check=grants.allowed,now=now)
                engine = KeirinPrivateSpool(
                    store, model_suite=run_suite, model_verifier=verify_suite,
                    source_observation_gate=grants.allowed,
                    source_odds_gate=lambda url,rights,purpose: (
                        purpose == "private_odds_research" and
                        grants.allowed(url,rights,"analysis")),
                    source_attestor=grants.certificate,
                    witness=None,  # Private research until independent receipt.
                )
                settled = engine.tick(inbox)
                # Prospective shadow8 and variable 0..12 points share the
                # same race/PR101 source hash. Both stay private and are
                # frozen together before cutoff in the owner SQLite file.
                dual = stage_shadow_variable_pairs(
                    inbox,store,grant_check=grants.allowed,now=now)
                # No filenames, source URLs, rider names, or buy picks in logs.
                print(json.dumps({
                    "schema": "RACE_AI_KEIRIN_LICENSED_LOCAL_CYCLE_V1",
                    "stage": stage, "spool": settled,
                    "owner_saved_csv_stage": owner_csv,
                    "owner_saved_full_odds_csv_stage": owner_odds_csv,
                    "owner_saved_markdown_stage": owner_markdown,
                    "source_grounded_private_shadow":shadow,
                    "same_race_shadow8_variable_research":dual,
                    "modelled_weather_stage": modelled_weather,
                    "automatic_provider_fetch": fetch_report is not None,
                    "provider_network_requests": (
                        (fetch_report["http_requests"] if fetch_report else 0) +
                        (modelled_weather["provider_get_requests"]
                         if modelled_weather else 0)),
                    "official_pre_cutoff_witness": False,
                    "licensed_rights_verified_by_program": False,
                    "commercial_use_authorized_by_program": False,
                    "owner_self_attested_private_only": args.personal_manual,
                    "provider_permission_inferred_from_personal_use": False,
                }, ensure_ascii=False, sort_keys=True), flush=True)
                if not args.loop:
                    break
                time.sleep(args.interval_seconds)
    except (LicenseDeliveryError, OwnerStoreError, InboxError,
            ShadowPairIntakeError, OwnerOddsCsvError,
            OSError, ValueError, KeyError, TypeError):
        print('{"state":"LICENSED_OWNER_CYCLE_FAILED_CLOSED"}')
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
