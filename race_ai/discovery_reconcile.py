"""Offline, fail-closed comparison of a manually checked schedule and audit ledger.

This module performs NO HTTP requests, grants NO data rights, and does NOT
authenticate official schedule information or an external freeze timestamp.
Reference entries are manually supplied; never mistake them for source licenses.
"""
from __future__ import annotations

from datetime import date
import re

SPORTS = frozenset({"boat", "keirin", "autorace", "horse_local", "horse_jra"})
SOURCE_SCOPE = "MANUAL_REFERENCE_ONLY"
LEDGER_SCOPE = "AUDIT_ONLY"


class CoverageError(ValueError):
    pass


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CoverageError("canonical event_date_jst required")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError as exc:
        raise CoverageError("invalid event_date_jst") from exc
    return value


def _key(sport, venue):
    if sport not in SPORTS or not isinstance(venue, str) or not venue.strip() or len(venue) > 128:
        raise CoverageError("invalid sport/venue identity")
    return sport, venue


def _number(n):
    if type(n) is not int or not 1 <= n <= 99:
        raise CoverageError("invalid race number")
    return n


def compare_daily(reference: dict, ledger: dict) -> dict:
    """Compare explicitly supplied race numbers; never infer twelve races per venue.

    Expected reference:
      {"scope":"MANUAL_REFERENCE_ONLY","event_date_jst":"YYYY-MM-DD",
       "venues":[{"sport":"boat","venue":"A","race_numbers":[1,2]}]}
    race_numbers=null means that this venue is reported, but its race count is UNKNOWN.
    Source availability and permission are distinct from this offline comparison.
    """
    if not isinstance(reference, dict) or set(reference) != {"scope", "event_date_jst", "venues"}:
        raise CoverageError("unexpected reference fields")
    if reference["scope"] != SOURCE_SCOPE:
        raise CoverageError("reference does not grant automated collection/training rights")
    day = _day(reference["event_date_jst"])
    if not isinstance(reference["venues"], list):
        raise CoverageError("expected venues list required")
    expected = {}
    for venue in reference["venues"]:
        if not isinstance(venue, dict) or set(venue) != {"sport", "venue", "race_numbers"}:
            raise CoverageError("invalid reference venue")
        key = _key(venue["sport"], venue["venue"])
        if key in expected:
            raise CoverageError("duplicate reference venue")
        nums = venue["race_numbers"]
        if nums is not None:
            if not isinstance(nums, list) or not nums:
                raise CoverageError("nonempty race number list or null required")
            checked = [_number(n) for n in nums]
            if len(checked) != len(set(checked)):
                raise CoverageError("duplicate reference race")
            nums = set(checked)
        expected[key] = nums

    if not isinstance(ledger, dict) or ledger.get("schema") != "RACE_AI_FORECAST_AUDIT_V1":
        raise CoverageError("unsupported audit schema")
    if ledger.get("dataset_status") != LEDGER_SCOPE or _day(ledger.get("event_date_jst")) != day:
        raise CoverageError("only matching-date AUDIT_ONLY ledgers are admitted")
    if not isinstance(ledger.get("records"), list):
        raise CoverageError("audit records required")
    actual = {}
    unverified_cutoffs = []
    reasons_missing = []
    prediction_claims_unverified = []
    for row in ledger["records"]:
        if not isinstance(row, dict):
            raise CoverageError("invalid audit row")
        k = _key(row.get("sport"), row.get("venue"))
        n = _number(row.get("race_no"))
        if row.get("race_id") != f"{k[0]}:{day}:{k[1]}:{n}":
            raise CoverageError("race identity mismatch")
        actual.setdefault(k, set())
        if n in actual[k]:
            raise CoverageError("duplicate audit race")
        actual[k].add(n)
        ident = row["race_id"]
        if row.get("cutoff_verified") is not True:
            unverified_cutoffs.append(ident)
        if row.get("prediction") is None and not row.get("no_forecast_reason"):
            reasons_missing.append(ident)
        if row.get("prediction") is not None:
            prediction_claims_unverified.append(ident)

    missing_venues = sorted(expected.keys() - actual.keys())
    unlisted_venues = sorted(actual.keys() - expected.keys())
    missing_races, unlisted_races, unknown_expected_counts = [], [], []
    for key in sorted(expected.keys() & actual.keys()):
        numbers = expected[key]
        if numbers is None:
            unknown_expected_counts.append(key)
            continue
        for n in sorted(numbers - actual[key]):
            missing_races.append([key[0], key[1], n])
        for n in sorted(actual[key] - numbers):
            unlisted_races.append([key[0], key[1], n])
    for key in missing_venues:
        numbers = expected[key]
        if numbers is None:
            unknown_expected_counts.append(key)
        else:
            for n in sorted(numbers):
                missing_races.append([key[0], key[1], n])
    missing_races.sort()
    unknown_expected_counts.sort()
    mismatched = bool(missing_venues or missing_races or unlisted_venues or unlisted_races)
    return {
        "event_date_jst": day,
        "reference_scope": SOURCE_SCOPE,
        "audit_scope": LEDGER_SCOPE,
        "reference_venues": len(expected),
        "ledger_venues": len(actual),
        "ledger_races": sum(map(len, actual.values())),
        "missing_venues": [list(k) for k in missing_venues],
        "missing_races": missing_races,
        "unlisted_venues": [list(k) for k in unlisted_venues],
        "unlisted_races": unlisted_races,
        "unknown_expected_race_counts": [list(k) for k in unknown_expected_counts],
        "unverified_cutoffs": sorted(unverified_cutoffs),
        "missing_no_forecast_reasons": sorted(reasons_missing),
        "unauthenticated_prediction_claims": sorted(prediction_claims_unverified),
        "comparison_status": "REPORTED_MISMATCH" if mismatched else "REFERENCE_MATCH_ONLY",
        "complete_official_coverage_verified": False,
        "real_pre_cutoff_freeze_verified": False,
        "auto_fetch_authorized": False,
        "real_prediction_admitted": False,
    }
