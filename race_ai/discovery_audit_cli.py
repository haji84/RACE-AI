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


def audit(reference: dict, ledger: dict) -> dict:
    comparison = compare_daily(reference, ledger)
    covered_sports = {v["sport"] for v in reference["venues"]}
    absent_sports = sorted(SPORTS - covered_sports)
    # A sport with no listed venue is NOT evidence of a no-meeting day.
    gaps = any(comparison[name] for name in (
        "missing_venues", "missing_races", "unlisted_venues", "unlisted_races"))
    uncertainties = bool(
        absent_sports or comparison["unknown_expected_race_counts"]
        or comparison["unverified_cutoffs"]
        or comparison["missing_no_forecast_reasons"]
        or comparison["unauthenticated_prediction_claims"]
    )
    status = ("REFERENCE_DISCREPANCY" if gaps else
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
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two supplied JSON files; never fetch a provider or admit a prediction")
    parser.add_argument("--reference", required=True, help="manually reviewed reference JSON")
    parser.add_argument("--ledger", required=True, help="AUDIT_ONLY JSON ledger")
    parser.add_argument("--output", help="optional new report file; cannot overwrite")
    args = parser.parse_args(argv)
    try:
        report = audit(_read_json(args.reference), _read_json(args.ledger))
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
