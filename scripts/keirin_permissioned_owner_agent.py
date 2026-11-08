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
from race_ai.keirin_licensed_api_ingest import fetch_authorized_exports
from race_ai.keirin_owner_auto_sources import (
    OwnerAttestedAutomaticSources, AUTOMATION_CONSENT,
)
from race_ai.keirin_owner_public_page_fetch import capture_approved_public_pages
from race_ai.keirin_owner_manual import PersonalOwnerObservations
from race_ai.keirin_owner_approved_sources import (
    PROFILE_ID, approved_source_hosts,
)
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
from race_ai.keirin_pr71_four_model_rank import (
    FourModelRankLedger, stage_existing_owner_pre_races
)


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
    parser.add_argument("--owner-approved-source-profile",
                        choices=(PROFILE_ID,), default=None,
                        help="use owner's 2026-11-09 WINTICKET/KEIRIN.JP "
                             "private manual reference hosts; no HTTP")
    parser.add_argument("--operator-reviewed-licenses", action="store_true",
                        help="Owner verified origin, permitted purposes and expiry out-of-band")
    parser.add_argument("--owner-automatic-fetch-confirmed", action="store_true",
                        help="owner confirms automated acquisition of WINTICKET "
                             "and KEIRIN.JP for private research; no provider API "
                             "endpoint is invented, no access controls bypassed")
    parser.add_argument("--owner-public-page-url", action="append",
                        help="repeat authorized public HTTPS webpage URLs to "
                             "archive as immutable private source HTML")
    parser.add_argument("--target-race-id",
                        help="canonical 12-digit race ID for prospective WINTICKET 210-odds intake")
    parser.add_argument("--target-cutoff-at",
                        help="already source-verified official sales cutoff (timezone aware)")
    parser.add_argument("--provider-endpoint", action="append",
                        help="repeat for EVERY explicitly approved JSON data "
                             "endpoint; no fixed single-GET application quota")
    parser.add_argument("--provider-rights-ref", action="append",
                        help="repeat corresponding rights reference for each endpoint")
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
    # Owner-confirmed automated use is confined to the two selected domains.
    # It is not independent proof of commercial/bulk provider data licensing.
    if args.owner_approved_source_profile and args.personal_source_host:
        print('{"state":"OWNER_SOURCE_PROFILE_AND_EXPLICIT_HOSTS_CONFLICT"}')
        return 2
    personal_hosts = (
        approved_source_hosts(args.owner_approved_source_profile)
        if args.owner_approved_source_profile else args.personal_source_host
    )
    auto_owner = args.owner_automatic_fetch_confirmed
    endpoints = args.provider_endpoint or []
    rights = args.provider_rights_ref or []
    if len(endpoints) != len(rights):
        print('{"state":"ENDPOINT_RIGHTS_PAIR_COUNT_MISMATCH"}')
        return 2
    if args.owner_public_page_url and not auto_owner:
        print('{"state":"PUBLIC_FETCH_REQUIRES_OWNER_AUTOMATIC_APPROVAL"}')
        return 2
    if bool(args.target_race_id) != bool(args.target_cutoff_at):
        print('{"state":"PROSPECTIVE_ODDS_RACE_CUTOFF_PAIR_REQUIRED"}')
        return 2
    if args.target_race_id and not (
        auto_owner and args.owner_public_page_url
    ):
        print('{"state":"PROSPECTIVE_ODDS_NEEDS_PUBLIC_SOURCE"}')
        return 2
    if auto_owner and (not args.personal_manual or
                       args.owner_approved_source_profile != PROFILE_ID or
                       not args.owner_private_use_confirmed):
        print('{"state":"OWNER_AUTOMATED_SOURCE_SCOPE_REQUIRED"}')
        return 2
    if args.personal_manual:
        if (not args.owner_private_use_confirmed or
            not personal_hosts or
            (bool(endpoints) and not auto_owner) or
            (bool(rights) and not auto_owner) or
            (args.api_token_env and not auto_owner) or
            args.grant_manifest or args.operator_reviewed_licenses):
            print('{"state":"OWNER_MANUAL_ONLY_OR_PRIVATE_SCOPE_NOT_CONFIRMED"}')
            return 2
    elif (not args.operator_reviewed_licenses or
          not args.grant_manifest or personal_hosts or
          args.owner_private_use_confirmed):
        print('{"state":"SOURCE_LICENSE_REVIEW_NOT_ACKNOWLEDGED"}')
        return 2
    if bool(endpoints) != bool(rights):
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
                grants = (
                    OwnerAttestedAutomaticSources(
                        profile=PROFILE_ID,consent=AUTOMATION_CONSENT,now=now)
                    if auto_owner else
                    PersonalOwnerObservations(
                        source_hosts=personal_hosts, now=now,
                        allow_noncommercial_modelled_weather=args.free_modelled_weather)
                    if args.personal_manual else
                    load_operator_grants(manifest, now=now))
                fetch_report = None
                if endpoints:
                    token = (os.environ.get(args.api_token_env)
                             if args.api_token_env else None)
                    if args.api_token_env and not token:
                        print('{"state":"LICENSED_FEED_TOKEN_UNCONFIGURED"}')
                        return 2
                    fetch_report = fetch_authorized_exports(
                        inbox, grants,
                        sources=list(zip(endpoints,rights)),token=token,
                    )
                public_pages = (
                    capture_approved_public_pages(
                        inbox,grants,urls=args.owner_public_page_url,
                        odds_race_id=args.target_race_id,
                        odds_official_cutoff_at=args.target_cutoff_at)
                    if args.owner_public_page_url else None)
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
                # Freeze original PR71 four-model full rankings while the
                # race is still future, independent of odds availability.
                four_rank = stage_existing_owner_pre_races(
                    inbox,store,source_admission=grants.allowed)
                shadow = stage_sourced_shadows(
                    inbox,grant_check=grants.allowed,now=now,store=store)
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
                # Post-result audit reads only previously frozen ranks,
                # including all four existing PR71 models.
                four_audit = FourModelRankLedger(store).replay_all()
                # No filenames, source URLs, rider names, or buy picks in logs.
                print(json.dumps({
                    "schema": "RACE_AI_KEIRIN_LICENSED_LOCAL_CYCLE_V1",
                    "stage": stage, "spool": settled,
                    "owner_saved_csv_stage": owner_csv,
                    "owner_automatic_public_page_capture": public_pages,
                    "owner_saved_full_odds_csv_stage": owner_odds_csv,
                    "owner_saved_markdown_stage": owner_markdown,
                    "source_grounded_private_shadow":shadow,
                    "same_race_shadow8_variable_research":dual,
                    "existing_pr71_four_model_ranking":four_rank,
                    "four_model_ranked_races":four_audit["ranked_forecast_races"],
                    "four_model_result_revision_count":
                        four_audit["replayed_result_revisions"],
                    "modelled_weather_stage": modelled_weather,
                    "automatic_provider_fetch": fetch_report is not None,
                    "provider_network_requests": (
                        (fetch_report["http_requests"] if fetch_report else 0) +
                        (public_pages["network_requests"] if public_pages else 0) +
                        (modelled_weather["provider_get_requests"]
                         if modelled_weather else 0)),
                    "official_pre_cutoff_witness": False,
                    "licensed_rights_verified_by_program": False,
                    "owner_confirmed_automated_fetch": auto_owner,
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
