"""Real future WINTICKET SSR probe, safe counts/SHA only, no predictions.

An ordinary public racecard + odds page is fetched in memory from the two
exact owner-approved URLs. The racecard has source-observed entrants and
closeAt, which are checked against the odds race identity. No source HTML,
rider data, prices or nonencrypted SQLite is published in CI.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime,timezone
from hashlib import sha256
import json

from race_ai.keirin_owner_public_page_fetch import (
    network_page_once,PublicPageFetchError
)
from race_ai.keirin_winticket_embedded_odds import (
    private_winticket_trifecta,checked_race_and_url,EmbeddedOddsError
)
from race_ai.keirin_winticket_embedded_racecard import (
    EmbeddedRacecardError,safe_public_racecard_counts,
    safe_public_racecard_key_inventory
)
from race_ai.keirin_winticket_ex_connection import (
    racecard_with_observed_ex as racecard_from_public_html,ExSourceError,
)
from race_ai.keirin_real_source_gap_report import inspect_source_gaps
from race_ai.keirin_result_delivery import utc

SCHEMA="RACE_AI_KEIRIN_FUTURE_LIVE_PUBLIC_SSR_PROBE_V1"


def public_future_race_probe(*,race_id,racecard_url,odds_url,
                             fetch=None,clock=None):
    """Returns structurally safe metadata, no private source rows."""
    if fetch is None:fetch=network_page_once
    if clock is None:clock=lambda:datetime.now(timezone.utc)
    try:
        checked_race_and_url(url=odds_url,race_id=race_id)
    except EmbeddedOddsError:
        raise EmbeddedRacecardError("FUTURE_RACE_ODDS_URL_INVALID") from None
    if ("/racecard/" not in racecard_url or
        racecard_url.replace("/racecard/","/odds/",1)!=odds_url):
        raise EmbeddedRacecardError("RACECARD_ODDS_IDENTITY_MISMATCH")
    card_html=fetch(racecard_url)
    card_at=clock()
    if not isinstance(card_at,datetime) or card_at.utcoffset() is None:
        raise EmbeddedRacecardError("RACECARD_CAPTURE_CLOCK_NOT_AWARE")
    try:
        card=racecard_from_public_html(
            card_html,url=racecard_url,race_id=race_id,
            captured_at=card_at.isoformat())
    except (EmbeddedRacecardError,ExSourceError) as e:
        return {
            "schema":SCHEMA,"status":"RACECARD_PENDING_OR_CUTOFF_PASSED",
            "race_id":race_id,"racecard_html_sha256":sha256(card_html).hexdigest(),
            "racecard_rejection":str(e),"odds_get_attempted":False,
            "actual_210_or_504_verified":False,
            "full_official_model_preflight":False,
            "two_version_prediction_saved":False,
        }
    odds_html=fetch(odds_url)
    odds_at=clock()
    if not isinstance(odds_at,datetime) or odds_at.utcoffset() is None:
        raise EmbeddedOddsError("ODDS_CAPTURE_CLOCK_NOT_AWARE")
    # A separate odds request can cross the cutoff. Never reuse card time.
    odds_before_published_cutoff=(
        odds_at < utc(card["source_published_cutoff_at_utc"]))
    prices=None
    reason=None
    if odds_before_published_cutoff:
        try:
            prices=private_winticket_trifecta(
                odds_html,url=odds_url,race_id=race_id,
                captured_at=odds_at.isoformat(),
                official_cutoff_at=card["source_published_cutoff_at_utc"])
        except EmbeddedOddsError as e:
            reason=str(e)
    else:
        reason="ODDS_CAPTURE_AFTER_PUBLISHED_CUTOFF"
    counts=safe_public_racecard_counts(card)
    gaps=inspect_source_gaps(card)
    sources=safe_public_racecard_key_inventory(card,card_html)
    result={
        "schema":SCHEMA,"race_id":race_id,
        "status":("ODDS_CAPTURE_AFTER_PUBLISHED_CUTOFF"
                  if not odds_before_published_cutoff else
                  "LIVE_TRIFECTA_PRICE_UNIVERSE_VERIFIED" if prices
                  else "ODDS_PENDING_OR_INCOMPLETE"),
        "racecard_html_sha256":card["html_sha256"],
        "odds_html_sha256":sha256(odds_html).hexdigest(),
        "observed_before_winticket_closeAt":odds_before_published_cutoff,
        "racecard_verified_riders":counts["rider_identity_count"],
        "preflight_checked_items":counts["registry_checked_count"],
        "preflight_source_verified_items":counts["registry_verified_count"],
        "preflight_unavailable_items":counts["registry_unavailable_count"],
        "ex_observed_attack_input_slots":len(card["ex_action_ratio_evidence"]),
        "ex_attack_input_unavailable_reasons":dict(Counter(
            card["ex_action_ratio_unavailable_reasons"].values())),
        "ex_attack_transform":card["ex_action_ratio_transform"],
        "ex_attack_denominator_kind":"recorded_actions_not_unique_races",
        "ssr_collection_field_names_only":sources["collection_field_names"],
        "ssr_collection_field_types_only":sources["collection_field_types_only"],
        "ssr_selected_nested_field_names_only":{
            **sources["selected_nested_field_names_only"],
            **card["ex_nested_source_key_names_only"],
        },
        "model_required_total_A":
            gaps["model_A_source_coverage"]["required_model_input_slots"],
        "model_required_observed_A":
            gaps["model_A_source_coverage"]["source_observed_required_slots"],
        "model_required_missing_A":
            gaps["model_A_source_coverage"]["source_unobserved_required_slots"],
        "missing_source_groups_A":
            gaps["model_A_source_coverage"][
                "missing_model_input_slots_by_source_field"],
        "model_required_observed_B":
            gaps["model_B_source_coverage"]["source_observed_required_slots"],
        "model_required_missing_B":
            gaps["model_B_source_coverage"]["source_unobserved_required_slots"],
        "missing_source_groups_B":
            gaps["model_B_source_coverage"][
                "missing_model_input_slots_by_source_field"],
        "missing_source_groups_are_counts_only":True,
        "preflight_core_required_missing":
            gaps["source_unobserved_critical_slots"],
        "actual_210_or_504_verified":prices is not None,
        "actual_full_trifecta_rows":(
            prices["receipt"]["combination_count"] if prices else 0),
        "real_price_sha256":(
            prices["receipt"].get(
                f"full_{prices['receipt']['combination_count']}_prices_sha256")
            if prices else None),
        "winticket_published_close_at_utc":
            card["source_published_cutoff_at_utc"],
        "racecard_347_or_437_complete":card["full_347_or_437_verified"],
        "full_official_model_preflight":False,
        "third_party_publication_clock_independently_proven":False,
        "provider_licence_independently_certified":False,
        "two_version_prediction_saved":False,
        "actual_betting":False,
        "public_rider_or_odds_payload_written":False,
    }
    if reason is not None:result["odds_rejection"]=reason
    return result


def main(args=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--race-id",required=True)
    p.add_argument("--racecard-url",required=True)
    p.add_argument("--odds-url",required=True)
    a=p.parse_args(args)
    try:
        result=public_future_race_probe(
            race_id=a.race_id,
            racecard_url=a.racecard_url,
            odds_url=a.odds_url)
    except (PublicPageFetchError,EmbeddedOddsError,
            EmbeddedRacecardError,ExSourceError,OSError,ValueError) as exc:
        allowed=(
            "PUBLIC_PAGE_NOT_PUBLISHED_OR_GONE",
            "PUBLIC_PAGE_BLOCKED_OR_RATE_LIMITED_NO_RETRY",
            "PUBLIC_PAGE_HTTP_NOT_OK",
            "PUBLIC_PAGE_NETWORK_UNAVAILABLE",
            "UNTRUSTED_WINTICKET_ODDS_ORIGIN",
            "WINTICKET_EVENT_DAY_MISMATCH",
        )
        kind=str(exc) if str(exc) in allowed else "UNVERIFIED_SOURCE"
        result={
            "schema":SCHEMA,
            "status":"PUBLIC_SOURCE_UNAVAILABLE_FAIL_CLOSED",
            "source_failure_kind":kind,
            "actual_210_or_504_verified":False,
            "full_official_model_preflight":False,
            "two_version_prediction_saved":False,
        }
    print(json.dumps(result,sort_keys=True,separators=(",",":"),
                     ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
