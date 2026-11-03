"""Build an auditable A/B multi-race report from externally verified ledger JSON.

Input is a complete official-schedule registry supplied by a trusted caller.
No HTTP, no Vercel, no bettor money, no model coefficients updated.
The output is private by default in an Actions artifact, not committed to Git.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from race_ai.boat_ab_cohort import analyze

MAX_BYTES = 4_000_000


def no_duplicate_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate field in audit input")
        out[key] = value
    return out


def parse_ledger(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError("bounded input required")
    data = json.loads(raw, object_pairs_hook=no_duplicate_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError("non-finite JSON input")))
    if (not isinstance(data, dict)
            or set(data) != {"schema", "registry", "rows"}
            or data["schema"] != "RACE_AI_BOAT_AB_EVIDENCE_LEDGER_V1"):
        raise ValueError("explicit evidence ledger contract required")
    registry = data["registry"]
    if (not isinstance(registry, dict)
            or set(registry) != {"source_url", "source_sha256", "independently_verified",
                                 "coverage_scope", "source_captured_at"}
            or registry["coverage_scope"] not in ("ONE_VENUE_DAY", "SELECTED_RACES")
            or type(registry["independently_verified"]) is not bool):
        raise ValueError("bounded official registry source required")
    if not isinstance(registry["source_url"], str) or not registry["source_url"].startswith(
            "https://www.boatrace.jp/owpc/pc/race/"):
        raise ValueError("official registry identity required")
    if (not isinstance(registry["source_sha256"], str)
            or len(registry["source_sha256"]) != 64
            or not all(c in "0123456789abcdef" for c in registry["source_sha256"])):
        raise ValueError("official registry digest required")
    datetime.fromisoformat(registry["source_captured_at"].replace("Z", "+00:00"))
    if not isinstance(data["rows"], list):
        raise ValueError("complete list of discovered race slots required")
    return data


def report(raw, *, minimum_paired=100, minimum_days=5):
    input_data = parse_ledger(raw)
    totals = analyze(input_data["rows"],
                     minimum_paired=minimum_paired, minimum_days=minimum_days)
    registry = input_data["registry"]
    totals["registry_evidence"] = registry
    totals["all_race_denominator_authenticated"] = bool(
        registry["independently_verified"]
        and registry["coverage_scope"] == "ONE_VENUE_DAY"
        and totals["total_discovered"] == 12
        and len({r["race_id"][9:11] for r in input_data["rows"]}) == 1
        and len({r["race_id"][:8] for r in input_data["rows"]}) == 1)
    totals["source_ledger_sha256"] = hashlib.sha256(raw).hexdigest()
    totals["generated_at"] = datetime.now(timezone.utc).isoformat()
    totals["conclusion_scope"] = ("ONE_VENUE_DAY" if totals["all_race_denominator_authenticated"]
                                  else "SELECTED_RACES_NOT_ALL_EVENTS")
    return totals


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--minimum-paired", type=int, default=100)
    p.add_argument("--minimum-days", type=int, default=5)
    args = p.parse_args()
    raw = args.input.read_bytes()
    evaluated = report(raw, minimum_paired=args.minimum_paired,
                       minimum_days=args.minimum_days)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(evaluated, stream, ensure_ascii=False, sort_keys=True,
                  separators=(",",":"), allow_nan=False)
    print(json.dumps({key:evaluated[key] for key in
        ("total_discovered","officially_settled_eligible","paired_forecast_count",
         "unforecast_or_unverified","conclusion_scope","statement","model_auto_promoted")},
        ensure_ascii=False))


if __name__=="__main__":
    try:
        main()
    except (OSError,TypeError,KeyError,ValueError,OverflowError) as exc:
        print("COHORT_EVIDENCE_REJECTED: "+type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
