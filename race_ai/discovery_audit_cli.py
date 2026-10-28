"""Offline coverage audit runner. No network, prediction, or rights escalation.

All input is explicitly supplied; a matching manual reference is never proof of
official race completeness, lawful ingestion, or a pre-cutoff real freeze.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .discovery_reconcile import CoverageError, SPORTS, compare_daily

MAX_BYTES = 8 * 1024 * 1024


def _no_duplicate_keys(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise CoverageError("duplicate JSON key: " + key)
        output[key] = value
    return output


def _read_json(path: str) -> dict:
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CoverageError("input exceeds bounded local file size")
    try:
        return json.loads(raw, object_pairs_hook=_no_duplicate_keys,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              CoverageError("non-finite JSON number")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CoverageError("invalid UTF-8 JSON input") from exc



def _compare_manual_references(primary: dict, secondary: dict) -> dict:
    """Compare two independently supplied lists, without conferring authority.

    Both references have already passed compare_daily's strict schema/date
    validation. Missing information is an uncertainty, not proof of no race.
    """
    left = {(v["sport"], v["venue"]): v["race_numbers"] for v in primary["venues"]}
    right = {(v["sport"], v["venue"]): v["race_numbers"] for v in secondary["venues"]}
    left_keys, right_keys = set(left), set(right)
    only_left, only_right, unknown, differing_races = [], [], [], []
    for key in sorted(left_keys - right_keys):
        only_left.append(list(key))
    for key in sorted(right_keys - left_keys):
        only_right.append(list(key))
    for key in sorted(left_keys & right_keys):
        a, b = left[key], right[key]
        if a is None or b is None:
            unknown.append(list(key))
            continue
        a, b = set(a), set(b)
        for n in sorted(a - b):
            differing_races.append([key[0], key[1], n, "PRIMARY_ONLY"])
        for n in sorted(b - a):
            differing_races.append([key[0], key[1], n, "SECONDARY_ONLY"])
    differing_races.sort()
    return {
        "scope": "MANUAL_TWO_SOURCE_COMPARISON_ONLY",
        "only_primary_venues": only_left,
        "only_secondary_venues": only_right,
        "differing_races": differing_races,
        "unknown_either_race_count": unknown,
        "sources_disagree": bool(only_left or only_right or differing_races),
        "sources_complete_and_authorized": False,
    }


def audit(reference: dict, ledger: dict, secondary_reference: dict | None = None) -> dict:
    comparison = compare_daily(reference, ledger)
    secondary_comparison = None
    cross_reference = None
    if secondary_reference is not None:
        # Re-use the strict reference validation, including the same JST date.
        secondary_comparison = compare_daily(secondary_reference, ledger)
        cross_reference = _compare_manual_references(reference, secondary_reference)
    covered_sports = {v["sport"] for v in reference["venues"]}
    absent_sports = sorted(SPORTS - covered_sports)
    # A sport with no listed venue is NOT evidence of a no-meeting day.
    gap_fields = ("missing_venues", "missing_races", "unlisted_venues", "unlisted_races")
    gaps = any(comparison[name] for name in gap_fields)
    if secondary_comparison is not None:
        gaps = gaps or any(secondary_comparison[name] for name in gap_fields)
    uncertainties = bool(
        absent_sports or comparison["unknown_expected_race_counts"]
        or comparison["unverified_cutoffs"]
        or comparison["missing_no_forecast_reasons"]
        or comparison["unauthenticated_prediction_claims"]
        or (cross_reference is not None and bool(cross_reference["unknown_either_race_count"]))
    )
    status = ("SOURCE_DISAGREEMENT" if cross_reference is not None and cross_reference["sources_disagree"] else
              "REFERENCE_DISCREPANCY" if gaps else
              "UNRESOLVED_COVERAGE_OR_PROOF" if uncertainties else
              "MANUAL_REFERENCE_MATCH_ONLY")
    return {
        "schema": "RACE_AI_OFFLINE_COVERAGE_GATE_V1",
        "status": status,
        "event_date_jst": comparison["event_date_jst"],
        "sports_without_reference": absent_sports,
        "evidence_scope": "MANUAL_REFERENCE_ONLY",
        "automatic_source_collection_admitted": False,
        "official_completeness_verified": False,
        "real_pre_cutoff_forecast_verified": False,
        "prediction_write_allowed": False,
        "reasons": {
            "source_permission": "NOT_ESTABLISHED_BY_MANUAL_REFERENCE",
            "immutable_external_receipt": "NOT_VERIFIED_BY_THIS_TOOL",
            "unobserved_sports": absent_sports,
        },
        "reconciliation": comparison,
        "secondary_reconciliation": secondary_comparison,
        "cross_reference": cross_reference,
        "reference_count": 2 if cross_reference is not None else 1,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two supplied JSON files; never fetch a provider or admit a prediction")
    parser.add_argument("--reference", required=True, help="manually reviewed reference JSON")
    parser.add_argument("--ledger", required=True, help="AUDIT_ONLY JSON ledger")
    parser.add_argument("--secondary-reference", help="independently reviewed second manual reference")
    parser.add_argument("--output", help="optional new report file; cannot overwrite")
    args = parser.parse_args(argv)
    try:
        report = audit(_read_json(args.reference), _read_json(args.ledger),
                       _read_json(args.secondary_reference) if args.secondary_reference else None)
        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False) + "\n"
        if args.output:
            # Exclusive creation protects previous audit reports from replacement.
            with Path(args.output).open("x", encoding="utf-8") as file:
                file.write(rendered)
                file.flush()
                os.fsync(file.fileno())
        else:
            sys.stdout.write(rendered)
        # An incomplete/manual comparison never becomes an official PASS.
        return 2 if report["status"] != "MANUAL_REFERENCE_MATCH_ONLY" else 0
    except (CoverageError, OSError, TypeError, KeyError, ValueError) as exc:
        print("COVERAGE_AUDIT_REJECTED: " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
